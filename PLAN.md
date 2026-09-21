# ha-kingspan-baga: bouwplan

Onofficiële Home Assistant-integratie (HACS) voor Kingspan BAGA-installaties voor afvalwater
(minireningsverk en slamavskiljare) die via de app **mittBAGA** te zien zijn.

- Repo: `joepherrmann/ha-kingspan-baga` (nog niet aangemaakt)
- HA-domein: `kingspan_baga`, titel "Kingspan BAGA"
- Status: API in kaart gebracht op 21-9-2026, er is nog geen code
- Testinstallatie: Idfjärden 16, machine_id `10319`, type **Easy Slamavskiljare G4** (machine_type_id `12`)

---

## 1. API (reverse-engineerd)

Bron: het verkeer van de iOS-app (`com.baga.app` v1.3, React Native/Hermes), op de Mac afgevangen met
mitmproxy in local mode. Er is geen certificate pinning. De afgevangen verzoeken staan geredigeerd in
`research/` (zie §9); die map staat in `.gitignore` omdat er persoonsgegevens in zitten.

### Basis
```
https://kingspanservice.se/applications/190_13/api/GET/<script>.php
https://kingspanservice.se/applications/190_13/api/POST/<script>.php
```
- Geldig Let's Encrypt-certificaat voor `kingspanservice.se`. De app zelf gebruikt het IP `91.106.193.70`; wij gebruiken de hostnaam.
- Elke aanroep krijgt `secret=<APP_SECRET>` en `lang=sv|en|…` mee.
  - `APP_SECRET` is een vaste string van 32 hextekens uit de app-bundel (`main.jsbundle`, zichtbaar in de login-query).
    Die komt in `const.py`, is niet persoonsgebonden en kan bij een app-update veranderen.
- Na het inloggen komt daar `key=<sessiesleutel>` bij.
- Het cookie `PHPSESSID` is **niet** nodig (getest met curl zonder cookie).
- Antwoorden hebben altijd deze vorm: `{"HEAD":{"action":…,"status":"SUCCESS"|…,"message"?:…},"DATA":…,"COUNT"?:n}`

### Authenticatie
```
GET login.php?secret=…&lang=sv
  headers: x-login: <e-mail>, x-password: <wachtwoord>
→ {"DATA":{"key":"<hex>","due_date":"YYYY-MM-DD HH:MM:SS"}}   (7 dagen geldig)
```
- Er is **geen refresh-endpoint**. De app logt bij elke start gewoon opnieuw in.
- ⚠️ Nog onbekend: hoe een fout bij het inloggen en een verlopen of ongeldige key eruitzien (HTTP-status of `HEAD.status`).
  Dat zoeken we uit bij de eerste echte test (§7, stap 3). Tot die tijd behandelen we elk `status != SUCCESS` op een
  endpoint dat een key nodig heeft als "key ongeldig": dan één keer opnieuw inloggen en opnieuw proberen, en pas daarna een fout.

### Endpoints voor de integratie

| Endpoint | Parameters | Gebruik |
|---|---|---|
| `GET get_user_info.php` | – | `DATA.id` = unique id van de config entry |
| `GET get_user_machines.php` | – | `DATA.Machines[]`: id, address, city, lat/lon, `machine_type{id,name}`, `unread_messages`, `has_flocculant`, `allow_sms_events`, `agreements[]` (servicecontract, interval) |
| `GET get_machine_info.php` | `machine_id` | `Workorders.DATA[]` (status, start/due/done_date), `Reports.DATA[]` (serviceprotocollen), `owner_data`, `data_variables` (bij ons leeg) |
| `GET get_machine_messages.php` | `machine_id, start_row, limit` | gebeurtenissen, gegroepeerd per uur en per code; zie hieronder |
| `GET get_machine_message_types.php` | `machine_id` | lijst `{type, description}`: vertaling van de codes, per model |
| `GET get_machine_message_classifications.php` | `machine_id` | (gezien in de bundel, nog niet aangeroepen) lijst met prioriteiten |
| `GET get_machine_communication_commands.php` | `machine_id` | lijst `{id, command, description, cardinality:"read", min/max/default}` |
| `POST send_machine_communication_command.php` | multipart: `machine_id, command, secret, key, lang` | → `"Kommando skickat utan fel"` |
| `GET get_communication_info.php` | `machine_type_id, name=<code\|commando>, type=info_code\|command` | uitgebreide uitleg per code, soms een afbeelding (base64); optioneel |

**Niet gebruiken:**
- `POST read_machine_message.php` markeert meldingen als gelezen. Dan verdwijnen ze als "ongelezen" in de app.
- `get_machine_articles.php` (webwinkel, 578 kB), het chatgedeelte, `add_user_device.php` (FCM-push).
- `/applications/190_10/functions/downloadReportPdf.php`: gebruikt een **vast gedeeld account** (`ext_usr`/`ext_pwd`) uit
  de app. Niet gebruiken en niet publiceren. Eventueel netjes melden bij Kingspan (mogelijk kun je daarmee andermans rapporten ophalen; niet getest).

### Structuur van de gebeurtenissen
```jsonc
"DATA": [ {                       // groep: één info_code per uur
  "info_code": {"info_code":"13001","description":"Avloppsanläggning Strömlös.",
                "classification_code":"47","classification_name":"Allvarligt fel","is_command":false},
  "data": "1300,00001691",
  "message_list": [ {
     "id":"13237434", "info_code":{…}, "data":"B1359,00001727", "machine_id":"10319",
     "user_has_read":false, "created_date":"2026-09-21 11:32:46",
     "created_date_strtotime":1789983166, "is_command":false, … } ] } ]
```
- **Deduplicatie** op `message_list[].id`, dat oploopt.
- `created_date` is lokale tijd (Europe/Stockholm); `created_date_strtotime` is een epoch. Die laatste gebruiken we.
- Het tweede getal in `data` (`00001691` → `00001727`) is een teller van de unit, betekenis onbekend. Mogelijk een dagteller:
  +36 in 19 dagen klopt niet helemaal, dus we tonen hem alleen als attribuut.

### Codes (Easy SA G4, machine_type 12)
| Code | Omschrijving | Classificatie | Paar |
|---|---|---|---|
| 13001 | Avloppsanläggning strömlös | 47 Allvarligt fel | ⬌ 13000 |
| 13000 | Ström tillbaka! Kontrollera funktion | 45 Informativ | |
| 11111 | Låg nivå flockningsmedel, byt dunk | `--` | ⬌ 11110 |
| 11110 | Nivå flockningsmedel OK | | |
| 11140 | Slamavskiljaren fylls på | | ⬌ 11141 |
| 11141 | Slamavskiljaren tömd | | |
| 13590 | GSM-modul har hittat nät, OK | 45 Informativ | hartslag |
| 14441 | Provtagning | | |

### Opdrachten (getest op 21-9-2026, antwoord binnen 5–60 s)
| Opdracht | Betekenis | Antwoord als message: `is_command:true`, `info_code:"--"`, `data` |
|---|---|---|
| RLSA | Actueel niveau in de tank (mm) | `LSA=249` |
| RDPT | Looptijd van de doseerpomp in seconden (0 = uit) | `DPT=20` |
| RFU1 | Status van zekering F1 | `FU1=OK` |

Het formaat is steeds `<opdracht zonder de eerste R>=<waarde>`. Elke opdracht gaat vermoedelijk per sms naar de unit, dus niet automatisch pollen.

---

## 2. Architectuur

```
ha-kingspan-baga/
├─ custom_components/kingspan_baga/
│  ├─ __init__.py          setup/unload entry, runtime_data
│  ├─ manifest.json        iot_class cloud_polling, integration_type hub, config_flow true
│  ├─ const.py             DOMAIN, BASE_URL, APP_SECRET, CODE_PAIRS, intervallen
│  ├─ api.py               BagaClient (aiohttp, via async_get_clientsession)
│  ├─ coordinator.py       BagaCoordinator (per config entry)
│  ├─ entity.py            BagaEntity-basis, DeviceInfo per machine
│  ├─ config_flow.py       user, reauth, reconfigure + OptionsFlow
│  ├─ event.py
│  ├─ binary_sensor.py
│  ├─ sensor.py
│  ├─ button.py
│  ├─ diagnostics.py       met redactie
│  ├─ strings.json
│  └─ translations/ en.json sv.json nl.json
├─ tests/                  pytest-homeassistant-custom-component + fixtures
├─ hacs.json               {"name":"Kingspan BAGA","render_readme":true,"homeassistant":"2025.1.0"}
├─ README.md               EN, plus korte NL/SV-sectie, disclaimer, screenshots
├─ LICENSE                 MIT
└─ .github/workflows/      validate.yml (hassfest + hacs/action), tests.yml, release.yml
```

De client in v1 **staat in de repo zelf**. Voor HA core moet hij later naar PyPI (`pybaga`); de interface van `api.py` houden we daarom zonder HA-imports.

### api.py
- `BagaClient(session, email, password, lang="sv")`
- `async_login()` → zet `_key`, `_key_expires`
- `_request(method, script, params|form, *, auth=True)`:
  - vernieuwt de key vooraf als `now > _key_expires - 24h`
  - bij een authenticatiefout (§1, ⚠️) één keer opnieuw inloggen en opnieuw proberen
  - excepties: `BagaAuthError` (credentials), `BagaConnectionError` (netwerk/timeout/5xx), `BagaApiError` (overig `status != SUCCESS`)
  - timeout 20 s; eigen User-Agent `ha-kingspan-baga/<versie>`
- Methoden: `get_user`, `get_machines`, `get_machine_info`, `get_messages(machine_id, limit=20)`,
  `get_message_types`, `get_commands`, `send_command(machine_id, command)`
- Dataclasses voor Machine, Message, Command, WorkOrder. Het parsen staat op één plek: de API geeft alles als string, `"true"`/`"false"` en `"0000-00-00 00:00:00"` = None.

### coordinator.py
- Eén `DataUpdateCoordinator` per account, met data per machine_id.
- **Snel (standaard 15 min, instelbaar 5–60):** `get_user_machines` + `get_messages(limit=20)` per machine.
- **Traag (elke 6 uur, in dezelfde coordinator met een timestamp):** `get_machine_info`, `get_message_types`, `get_commands`.
- Houdt `last_seen_message_id` per machine bij (**als int vergelijken**: de API geeft strings, en lexicografisch is "999" > "13237434"). Nieuwe berichten gaan naar de event-entiteit.
  - **Allereerste setup** (geen Store-data): alleen de baseline zetten, geen events afvuren.
  - **Herstart mét Store-data:** gemiste berichten wél als event afvuren, met een cap (max ~20 en niet ouder dan 24 u) tegen een stortvloed na lang offline zijn.
  - In `homeassistant.helpers.storage.Store` per machine: `last_seen_message_id` **én de afgeleide paartoestanden + laatste opdrachtwaarden** (zie hieronder waarom).
- Toestand afleiden: per codepaar de **nieuwste** van de twee → aan/uit. Plus de laatste waarde per opdrachtantwoord.
  - ⚠️ Codes als 11141 (lediging, ~jaarlijks) zitten vrijwel nooit in de laatste 20 berichten. Daarom: bij de allereerste
    setup **dieper pagineren** met `start_row` tot elk gemapt paar één keer gezien is (cap, b.v. 200 berichten), en daarna de
    afgeleide toestanden uit de Store herstellen in plaats van ze telkens uit de laatste 20 af te leiden.
  - Severity op één plek mappen: classification_code `47`→critical, `45`→info, `--`/ontbrekend→none.
- Fouten: `UpdateFailed` (entiteiten worden unavailable), `ConfigEntryAuthFailed` bij `BagaAuthError` (start de reauth).

### Opdracht-flow (knop)
1. Druk op de knop → `send_command`
2. De coordinator gaat tijdelijk in **snelle modus**: elke 20 s alleen `get_messages(limit=5)`, maximaal 3 minuten, tot er een bericht met `is_command` en de juiste prefix (`LSA=`/`DPT=`/`FU1=`) binnenkomt.
3. Sensor bijwerken, snelle modus uit. Geen antwoord binnen 3 min → persistent notification of log-warning, en de sensor blijft op de oude waarde.
4. Beveiliging: maximaal 1 openstaande opdracht per machine; knoppen hebben een cooldown van 60 s (HA-buttons hebben
   dat niet ingebouwd, dus zelf afdwingen met een timestamp).
5. Implementatie: de snelle modus is een **losse taak** die om de 20 s `async_request_refresh()` aanroept, niet een
   tijdelijk verlaagd coordinator-interval (dat vecht met de debouncer).

---

## 3. Entiteiten (per machine = één apparaat)

DeviceInfo: `manufacturer="Kingspan BAGA"`, `model=machine_type.name`, `name=address`, `identifiers={(DOMAIN, machine_id)}`,
`serial_number=machine_id`, `configuration_url` = geen (er is geen webportaal).

| Platform | Key | Naam | Bron / logica | Standaard |
|---|---|---|---|---|
| event | `activity` | Gebeurtenis | elk nieuw bericht; attributen: description, severity, data, message_id, created. ⚠️ HA eist dat `event_types` vooraf vaststaat: lijst opbouwen uit `get_message_types` + `command_response` + vangnet `unknown`; onbekende codes op `unknown` mappen met de echte code als attribuut | aan |
| binary_sensor | `power` | Stroom | problem-class; aan bij 13001 als nieuwste, uit bij 13000 | aan |
| binary_sensor | `flocculant_low` | Vlokmiddel laag | problem; 11111 ⬌ 11110; alleen als `has_flocculant` | aan |
| binary_sensor | `tank_filling` | Tank loopt vol | problem; 11140 ⬌ 11141 | aan |
| binary_sensor | `connectivity` | GSM-verbinding | connectivity; aan als er in de laatste X dagen een bericht was. **Standaard X=30**: de eigen data toont 19 dagen stilte als normaal gedrag, en 13590 is een reconnect-melding, geen hartslag | uit (diagnostic) |
| sensor | `last_event` | Laatste gebeurtenis | beschrijving van het nieuwste bericht; attributen: code, severity, tijd | aan |
| sensor | `last_event_time` | Tijd laatste gebeurtenis | timestamp | aan |
| sensor | `last_emptied` | Laatst geleegd | timestamp van de nieuwste 11141 (uit de historie; misschien de eerste keer leeg) | aan |
| sensor | `unread_messages` | Ongelezen meldingen | `unread_messages` | aan |
| sensor | `tank_level` | Tankniveau | mm, `LSA=` | aan |
| sensor | `dosing_pump_runtime` | Looptijd doseerpomp | s, `DPT=` | uit |
| sensor | `fuse_f1` | Zekering F1 | enum/tekst, `FU1=` | uit (diagnostic) |
| sensor | `last_service` | Laatste service | `done_date` van de nieuwste werkorder | aan |
| sensor | `next_service` | Volgende service | uit het `agreements[].services[]`-interval (maand) of `due_date` van een openstaande werkorder | aan |
| button | `request_<cmd>` | "Tankniveau opvragen" enz. | dynamisch uit `get_commands` (`cardinality == read`) | **uit**: elke druk kost een sms |

- `has_entity_name = True`, translation_keys voor alle namen.
- Codes die niet in `CODE_PAIRS` staan, komen **alleen** in event/last_event. Zo werkt het ook voor andere modellen zonder mapping.
- Beschrijvingen komen van de server (`get_message_types`) in de taal van de HA-installatie (`lang` = `hass.config.language`,
  terugvallen op `sv`). ⚠️ Nog testen of `lang=en/nl` echte vertalingen oplevert.

---

## 4. Config flow

1. **user:** e-mail + wachtwoord → `async_login` + `get_user` → `unique_id = user.id` → `_abort_if_unique_id_configured`.
   Titel: e-mail. Alle machines op het account worden apparaten; er is geen keuzestap nodig (eenvoudiger, en de
   gebruiker kan apparaten uitschakelen).
2. **reauth:** vraagt alleen het wachtwoord opnieuw. Wordt gestart door `ConfigEntryAuthFailed`.
3. **reconfigure:** e-mail of wachtwoord wijzigen.
4. **options:** poll-interval (5–60 min), GSM-timeout in dagen, taal van de beschrijvingen (auto/sv/en).
- Fouten in het formulier: `invalid_auth`, `cannot_connect`, `unknown`.
- Credentials staan in `entry.data` (standaard HA-praktijk). Er worden nooit credentials gelogd.

---

## 5. Diagnostics en privacy
- `async_redact_data` op: email, password, key, secret, phone/phonenumber/mobile, address, zip, city, lat/lon,
  name/lastname, customerid*, owner_data, cadastral_reference, created_by.
- Diagnostics bevat: machine_type, message_types, commands, de laatste 20 berichten (codes, data, tijden). Precies wat nodig is
  om de mapping voor nieuwe modellen uit te breiden → de README vraagt gebruikers van andere modellen om dit te delen in een issue.

---

## 6. Kwaliteit, CI en release
- **Tests** (pytest-homeassistant-custom-component): config flow (ok/invalid_auth/cannot_connect/already_configured/reauth),
  coordinator (baseline zonder events, nieuw bericht → event, toestand van de codeparen, opnieuw inloggen na een verlopen key), knop + snelle
  modus, diagnostics-redactie. Fixtures = **geanonimiseerde** responses uit `research/`.
- **CI:** `hassfest`, `hacs/action` (category integration), ruff, pytest.
- **Releases:** GitHub-tags `v0.1.0` enz. met `manifest.json` → version. HACS leest de releases.
- **Brand:** geen Kingspan-logo (handelsmerk). Een generiek icoon of geen icoon.
- **README:** installatie (HACS custom repo + handmatig), configuratie, lijst met entiteiten, voorbeeldautomatiseringen
  (melding bij stroomuitval / vlokmiddel laag), **disclaimer** ("unofficial, not affiliated with Kingspan; uses the
  app's private API which may change"), kostenwaarschuwing bij opdrachten, oproep om diagnostics te delen.

---

## 7. Stappenplan

1. **Skelet + api.py + tests** met fixtures. Alles lokaal, zonder HA.
2. **Entiteiten + config flow + coordinator.** Lokaal testen met pytest.
3. **Eerste echte test op Joeps HA** (na akkoord): via ssh naar `/config/custom_components/kingspan_baga`, herstarten,
   Joep voegt de integratie toe via de UI. Dan controleren:
   - de vorm van een verkeerd wachtwoord in de config flow (§1 ⚠️)
   - verloop/ongeldigheid van de key (key ongeldig maken door opnieuw in te loggen in de app → zien of de oude key blijft werken; dan weten we ook of er één sessie per account geldt)
   - `lang=en/nl` bij de beschrijvingen
   - de semantiek van `start_row`/`limit` (telt het groepen of berichten?) voor de diepe paginering
   - één druk op "Tankniveau opvragen" → snelle modus → sensor
4. **Een paar dagen draaien.** Kijken of events dubbel binnenkomen of gemist worden en of er in de log fouten staan over de rate limit.
5. **Publiceren** (na akkoord): repo `joepherrmann/ha-kingspan-baga` publiek, topics `home-assistant`, `hacs`,
   `home-assistant-custom-component`, release v0.1.0. Eventueel later een PR naar HACS default en `home-assistant/brands`.
6. **Automatiseringen voor het huisje** (apart, in Joeps HA): meldingen bij stroomuitval, vlokmiddel laag en tank vol, plus een
   tegel op `dashboard-tablet` → view `cabin-in-the-woods`.

---

## 8. Openstaande vragen en risico's
- Welke foutvorm geeft de server bij een verkeerde login of een verlopen key? (stap 3)
- Eén sessie per account? De app en de proxy werkten tegelijk met verschillende keys → waarschijnlijk niet, maar check dat.
- Rate limiting: onbekend. Standaard 15 min is ruim.
- Andere modellen (BioTank, BioFicient, BioDisc): andere codes en opdrachten, en `data_variables` kan daar gevuld zijn. De generieke laag vangt dat op, en de mapping groeit via diagnostics van gebruikers.
- Kingspan kan `APP_SECRET`, het pad (`190_13`) of de hele API veranderen. Dan zet de integratie netjes `UpdateFailed` en brengen we een nieuwe release uit.
- Juridisch: onofficiële client voor je eigen gegevens. Geen scraping van andermans data, de gedeelde PDF-login niet gebruiken, geen logo.

### Bijvangst (los van de integratie)
- Op **31-8, 1-9 en 2-9-2026 elke dag rond 15:58 stroomuitval** (13001) en om 16:01 weer stroom (13000), telkens gevolgd
  door "vlokmiddel laag" (11111). Nagaan of een Shelly, een automatisering of een tijdschakelaar bij het huisje die groep schakelt.
- Het vlokmiddel is echt laag: de dunk vervangen.

---

## 9. Onderzoeksmateriaal (`research/`, niet in git)
- `capture1.txt`: eerste opname: login, gebruiker, machines, info, gebeurtenissen, types, opdrachtenlijst
- `capture2.txt`: RLSA-opdracht verstuurd + antwoord
- `capture3.txt`: rondklikken: gebeurtenissen, protocollen, winkel, communicatie-info, gelezen markeren
- Wachtwoord, key, APP_SECRET, PHPSESSID en FCM-token zijn vervangen. **Persoonsgegevens (naam, adres, telefoon)
  staan er nog in**: anonimiseren voordat er iets van als fixture in `tests/` terechtkomt.
- Om `APP_SECRET` opnieuw te vinden: de query van `login.php` in een nieuwe mitmproxy-opname
  (`mitmdump --mode local:baga_app`, en het CA-certificaat tijdelijk vertrouwen). Dat hij ook als string in `main.jsbundle` staat,
  is niet gecontroleerd.
