"""Buttons that send read commands to the unit.

Disabled by default: every press most likely triggers an SMS to the unit.
"""

from __future__ import annotations

import time

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Command
from .const import COMMAND_COOLDOWN, DOMAIN
from .coordinator import BagaConfigEntry, BagaCoordinator
from .entity import BagaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BagaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        BagaCommandButton(coordinator, machine_id, command)
        for machine_id, data in coordinator.data.items()
        for command in data.commands
        if command.cardinality == "read"
        # New commands appearing later require a reload to show up.
    )


class BagaCommandButton(BagaEntity, ButtonEntity):
    """Sends one read command (e.g. RLSA = request tank level)."""

    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: BagaCoordinator, machine_id: str, command: Command
    ) -> None:
        super().__init__(coordinator, machine_id, f"request_{command.command}")
        self._command = command
        # Server-provided description; no translation key for dynamic names.
        self._attr_name = command.description or command.command
        self._last_press = 0.0

    async def async_press(self) -> None:
        # HA buttons have no built-in cooldown; enforce one ourselves since
        # every press likely costs an SMS.
        now = time.monotonic()
        if now - self._last_press < COMMAND_COOLDOWN:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_cooldown",
            )
        self._last_press = now
        await self.coordinator.async_send_command(self._machine_id, self._command)
