"""The Kingspan BAGA integration.

Unofficial integration for Kingspan BAGA wastewater installations, using the
private cloud API of the mittBAGA app. Not affiliated with Kingspan.
"""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BagaAuthError, BagaClient, BagaError
from .const import CONF_LANG
from .coordinator import BagaConfigEntry, BagaCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.SENSOR,
]


def _resolve_lang(hass: HomeAssistant, entry: BagaConfigEntry) -> str:
    lang = entry.options.get(CONF_LANG, "auto")
    if lang != "auto":
        return lang
    # The backend serves at least Swedish; other languages are untested.
    return (hass.config.language or "sv").split("-")[0]


async def async_setup_entry(hass: HomeAssistant, entry: BagaConfigEntry) -> bool:
    """Set up Kingspan BAGA from a config entry."""
    client = BagaClient(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        lang=_resolve_lang(hass, entry),
    )
    try:
        await client.async_login()
    except BagaAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except BagaError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = BagaCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: BagaConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BagaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
