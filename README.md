# Kingspan BAGA for Home Assistant

Unofficial Home Assistant integration for **Kingspan BAGA** wastewater
installations (minireningsverk / slamavskiljare) that are connected to the
**mittBAGA** app.

> **Disclaimer:** this project is not affiliated with, endorsed by, or
> supported by Kingspan. It uses the private cloud API of the mittBAGA app,
> which may change or break at any time.

## What you get

One device per installation on your account, with:

| Entity | Notes |
|---|---|
| Event *Event* | fires for every new machine message (power loss, flocculant low, tank emptied, command replies, …) with `code`, `description`, `severity` attributes |
| Binary sensor *Power* | on = mains present, derived from codes 13001 / 13000 |
| Binary sensor *Flocculant low* | codes 11111 / 11110 (only when the unit doses flocculant) |
| Binary sensor *Tank filling up* | codes 11140 / 11141 |
| Binary sensor *GSM connection* | disabled by default; the unit can be silent for weeks, window configurable |
| Sensor *Last event* + *Last event time* | newest message |
| Sensor *Last emptied* | newest tank-emptied message |
| Sensor *Unread messages* | as counted by the app |
| Sensor *Tank level* (mm), *Dosing pump runtime* (s), *Fuse F1* | updated after you press the matching request button |
| Buttons *Request …* | **disabled by default** — each press is relayed to the unit, most likely by SMS, so use them sparingly and don't automate them on a tight schedule |

The known code pairs are model-specific (developed against an *Easy
Slamavskiljare G4*). Messages with unknown codes still show up in the event
entity and the *Last event* sensor, so other models work out of the box with
reduced detail — see [Other models](#other-models).

## Installation

### HACS (recommended)

1. HACS → three-dot menu → **Custom repositories**
2. Add `https://github.com/joepherrmann/ha-kingspan-baga` as an *Integration*
3. Install **Kingspan BAGA** and restart Home Assistant

### Manual

Copy `custom_components/kingspan_baga` into your `config/custom_components`
folder and restart.

## Configuration

*Settings → Devices & services → Add integration → Kingspan BAGA* and sign in
with your mittBAGA account. Options (polling interval, connectivity window,
description language) are available on the integration afterwards. Polling runs
hourly by default (configurable from 5 minutes up to 24 hours) — lower it if
you want faster power-failure alerts.

## Example automation

```yaml
automation:
  - alias: "Septic tank power failure"
    triggers:
      - trigger: state
        entity_id: binary_sensor.septic_tank_power
        to: "off"
    actions:
      - action: notify.mobile_app_phone
        data:
          title: "Septic tank"
          message: "Power failure at the wastewater unit!"
```

## Other models

BioTank, BioFicient and BioDisc units use different message codes. If some
binary sensors stay unknown for your model, please open an issue and attach
the integration's **diagnostics** file (Settings → Devices & services →
Kingspan BAGA → three-dot menu → Download diagnostics). It contains your
model's code list and no personal data, and lets us extend the mapping.

## Nederlands / Svenska

**NL:** Onofficiële integratie voor Kingspan BAGA-afvalwaterinstallaties via
het mittBAGA-account. Installeer via HACS (custom repository), log in met je
mittBAGA-gegevens. De opdracht-knoppen staan standaard uit omdat elke druk
vermoedelijk een sms naar de unit stuurt.

**SV:** Inofficiell integration för Kingspan BAGA-avloppsanläggningar via
mittBAGA-kontot. Installera via HACS (custom repository) och logga in med
dina mittBAGA-uppgifter. Kommandoknapparna är avstängda som standard eftersom
varje tryck troligen skickar ett SMS till anläggningen.
