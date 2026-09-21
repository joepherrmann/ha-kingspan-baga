"""Binary sensors derived from info-code pairs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_CONNECTIVITY_DAYS,
    DEFAULT_CONNECTIVITY_DAYS,
)
from .coordinator import BagaConfigEntry, BagaCoordinator, MachineData
from .entity import BagaEntity


@dataclass(frozen=True, kw_only=True)
class BagaBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a BAGA binary sensor."""

    exists_fn: Callable[[MachineData], bool] = lambda _: True


PAIR_SENSORS = [
    BagaBinarySensorDescription(
        key="power_failure",
        translation_key="power_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    BagaBinarySensorDescription(
        key="flocculant_low",
        translation_key="flocculant_low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        exists_fn=lambda data: data.machine.has_flocculant,
    ),
    BagaBinarySensorDescription(
        key="tank_filling",
        translation_key="tank_filling",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BagaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for machine_id, data in coordinator.data.items():
        entities.extend(
            BagaPairBinarySensor(coordinator, machine_id, description)
            for description in PAIR_SENSORS
            if description.exists_fn(data)
        )
        entities.append(BagaConnectivitySensor(coordinator, machine_id, entry))
    async_add_entities(entities)


class BagaPairBinarySensor(BagaEntity, BinarySensorEntity):
    """State of one info-code pair (newest of the two codes wins)."""

    entity_description: BagaBinarySensorDescription

    def __init__(
        self,
        coordinator: BagaCoordinator,
        machine_id: str,
        description: BagaBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, machine_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        if (data := self.machine_data) is None:
            return None
        return data.pair_states.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        if (data := self.machine_data) is None:
            return None
        changed = data.pair_changed.get(self.entity_description.key)
        return {"changed": changed.isoformat()} if changed else None


class BagaConnectivitySensor(BagaEntity, BinarySensorEntity):
    """Whether the unit has phoned home recently.

    The unit can legitimately stay silent for weeks (a 19-day gap was seen in
    normal operation), hence the large, configurable window.
    """

    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: BagaCoordinator,
        machine_id: str,
        entry: BagaConfigEntry,
    ) -> None:
        super().__init__(coordinator, machine_id, "connectivity")
        self._days = entry.options.get(
            CONF_CONNECTIVITY_DAYS, DEFAULT_CONNECTIVITY_DAYS
        )

    @property
    def is_on(self) -> bool | None:
        if (data := self.machine_data) is None or data.last_message is None:
            return None
        age = datetime.now(tz=UTC) - data.last_message.created
        return age <= timedelta(days=self._days)
