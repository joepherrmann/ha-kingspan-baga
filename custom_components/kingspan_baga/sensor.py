"""Sensors for Kingspan BAGA."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CMD_PREFIX_FUSE,
    CMD_PREFIX_PUMP_RUNTIME,
    CMD_PREFIX_TANK_LEVEL,
    SEVERITY_MAP,
    SEVERITY_NONE,
)
from .coordinator import BagaConfigEntry, BagaCoordinator, MachineData
from .entity import BagaEntity


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, kw_only=True)
class BagaSensorDescription(SensorEntityDescription):
    """Describes a BAGA sensor."""

    value_fn: Callable[[MachineData], Any]
    attributes_fn: Callable[[MachineData], dict[str, Any] | None] = lambda _: None
    exists_fn: Callable[[MachineData], bool] = lambda _: True


STATUS_OK = "ok"
# Highest-severity active problem wins; the full list is an attribute.
STATUS_PRIORITY = ["power_failure", "tank_filling", "flocculant_low"]


def _status_value(data: MachineData) -> str:
    for key in STATUS_PRIORITY:
        if data.pair_states.get(key):
            return key
    return STATUS_OK


SENSORS = [
    BagaSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[STATUS_OK, *STATUS_PRIORITY],
        value_fn=_status_value,
        attributes_fn=lambda d: {
            "active_problems": [k for k, v in d.pair_states.items() if v]
        },
    ),
    BagaSensorDescription(
        key="last_event",
        translation_key="last_event",
        value_fn=lambda d: (
            d.message_types.get(d.last_message.code, d.last_message.description)
            or d.last_message.description
            or d.last_message.data
        )
        if d.last_message
        else None,
        attributes_fn=lambda d: {
            "code": d.last_message.code,
            "severity": SEVERITY_MAP.get(
                d.last_message.classification_code, SEVERITY_NONE
            ),
            "data": d.last_message.data,
        }
        if d.last_message
        else None,
    ),
    BagaSensorDescription(
        key="last_event_time",
        translation_key="last_event_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_message.created if d.last_message else None,
    ),
    BagaSensorDescription(
        key="last_emptied",
        translation_key="last_emptied",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_emptied,
    ),
    BagaSensorDescription(
        key="unread_messages",
        translation_key="unread_messages",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.machine.unread_messages,
    ),
    BagaSensorDescription(
        key="tank_level",
        translation_key="tank_level",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _int_or_none(d.command_values.get(CMD_PREFIX_TANK_LEVEL)),
        attributes_fn=lambda d: {
            "updated": d.command_updated[CMD_PREFIX_TANK_LEVEL].isoformat()
        }
        if CMD_PREFIX_TANK_LEVEL in d.command_updated
        else None,
    ),
    BagaSensorDescription(
        key="dosing_pump_runtime",
        translation_key="dosing_pump_runtime",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _int_or_none(
            d.command_values.get(CMD_PREFIX_PUMP_RUNTIME)
        ),
    ),
    BagaSensorDescription(
        key="fuse_f1",
        translation_key="fuse_f1",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.command_values.get(CMD_PREFIX_FUSE),
    ),
    BagaSensorDescription(
        key="last_service",
        translation_key="last_service",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_service,
    ),
    BagaSensorDescription(
        key="next_service",
        translation_key="next_service",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.next_service,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BagaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        BagaSensor(coordinator, machine_id, description)
        for machine_id, data in coordinator.data.items()
        for description in SENSORS
        if description.exists_fn(data)
    )


class BagaSensor(BagaEntity, SensorEntity):
    """A sensor backed by a value function on the machine data."""

    entity_description: BagaSensorDescription

    def __init__(
        self,
        coordinator: BagaCoordinator,
        machine_id: str,
        description: BagaSensorDescription,
    ) -> None:
        super().__init__(coordinator, machine_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if (data := self.machine_data) is None:
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if (data := self.machine_data) is None:
            return None
        return self.entity_description.attributes_fn(data)
