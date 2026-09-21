"""Event entity: fires for every new machine message."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Message
from .const import (
    EVENT_TYPE_COMMAND_RESPONSE,
    EVENT_TYPE_UNKNOWN,
    SEVERITY_MAP,
    SEVERITY_NONE,
)
from .coordinator import BagaConfigEntry, BagaCoordinator
from .entity import BagaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BagaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        BagaEventEntity(coordinator, machine_id) for machine_id in coordinator.data
    )


class BagaEventEntity(BagaEntity, EventEntity):
    """One event entity per machine."""

    _attr_translation_key = "activity"

    def __init__(self, coordinator: BagaCoordinator, machine_id: str) -> None:
        super().__init__(coordinator, machine_id, "activity")
        self._last_fired_id = 0
        # HA requires event_types to be declared up front; build the list
        # from the server's own code list plus fallbacks for anything new.
        known = coordinator.data[machine_id].message_types
        self._attr_event_types = [
            *sorted(known),
            EVENT_TYPE_COMMAND_RESPONSE,
            EVENT_TYPE_UNKNOWN,
        ]

    def _event_type_for(self, message: Message) -> str:
        if message.is_command:
            return EVENT_TYPE_COMMAND_RESPONSE
        if message.code in self.event_types:
            return message.code
        return EVENT_TYPE_UNKNOWN

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.machine_data
        if data is None:
            super()._handle_coordinator_update()
            return
        fired = False
        for message in data.new_messages:  # oldest first
            if message.id <= self._last_fired_id:
                continue
            self._last_fired_id = message.id
            self._trigger_event(
                self._event_type_for(message),
                {
                    "code": message.code,
                    "description": data.message_types.get(
                        message.code, message.description
                    )
                    or message.description,
                    "severity": SEVERITY_MAP.get(
                        message.classification_code, SEVERITY_NONE
                    ),
                    "data": message.data,
                    "message_id": message.id,
                    "created": message.created.isoformat(),
                },
            )
            fired = True
        if fired:
            self.async_write_ha_state()
        else:
            super()._handle_coordinator_update()
