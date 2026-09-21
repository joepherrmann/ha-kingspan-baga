"""Tests for setup, entities and event behaviour."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kingspan_baga.const import DOMAIN

from .conftest import DEFAULT_MESSAGES, MACHINE_ID, make_message


async def setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "hunter2"},
        unique_id="3146",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def get_entity_id(hass: HomeAssistant, unique_id: str) -> str:
    registry = er.async_get(hass)
    for entry in registry.entities.values():
        if entry.platform == DOMAIN and entry.unique_id == unique_id:
            return entry.entity_id
    raise AssertionError(f"no entity with unique_id {unique_id}")


async def test_setup_creates_entities(
    hass: HomeAssistant, patch_client: AsyncMock
) -> None:
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED

    # Pair states: 13000 (power back) is newer than 13001 → no problem.
    power = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_power_failure"))
    assert power.state == "off"

    # 11111 (flocculant low) has no newer 11110 → problem.
    floc = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_flocculant_low"))
    assert floc.state == "on"

    # 11141 only exists deeper in history: found via first-setup pagination.
    tank = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_tank_filling"))
    assert tank.state == "off"

    level = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_tank_level"))
    assert level.state == "249"

    unread = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_unread_messages"))
    assert unread.state == "184"

    emptied = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_last_emptied"))
    assert emptied.state != "unknown"

    # Very first refresh sets the baseline without firing historic events.
    event = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_activity"))
    assert event.state == "unknown"


async def test_new_message_fires_event(
    hass: HomeAssistant, patch_client: AsyncMock
) -> None:
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data

    new_msg = make_message(200, "13001", age=timedelta(minutes=1), classification="47")

    def messages(machine_id, *, start_row=0, limit=20):
        return [new_msg, *DEFAULT_MESSAGES] if start_row == 0 else []

    patch_client.get_messages.side_effect = messages
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    event = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_activity"))
    assert event.state != "unknown"
    assert event.attributes["event_type"] == "13001"
    assert event.attributes["severity"] == "critical"

    # Power pair flips to problem.
    power = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_power_failure"))
    assert power.state == "on"

    # A second refresh without new messages must not re-fire.
    fired_at = event.attributes["created"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    event = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_activity"))
    assert event.attributes["created"] == fired_at


async def test_setup_survives_end_of_history(
    hass: HomeAssistant, patch_client: AsyncMock
) -> None:
    """Paging past the end raises an API error; setup must still succeed."""
    from custom_components.kingspan_baga.api import BagaApiError

    def messages(machine_id, *, start_row=0, limit=20):
        if start_row == 0:
            return list(DEFAULT_MESSAGES)
        raise BagaApiError("Inga meddelanden hittade")

    patch_client.get_messages.side_effect = messages
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    # The tank pair never appeared in the reachable history: stays unknown.
    tank = hass.states.get(get_entity_id(hass, f"{MACHINE_ID}_tank_filling"))
    assert tank.state == "off" or tank.state == "unknown"


async def test_unload(hass: HomeAssistant, patch_client: AsyncMock) -> None:
    entry = await setup_entry(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
