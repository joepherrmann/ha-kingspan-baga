"""Base entity for Kingspan BAGA."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import BagaCoordinator, MachineData


class BagaEntity(CoordinatorEntity[BagaCoordinator]):
    """Base class binding an entity to one machine."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BagaCoordinator, machine_id: str, key: str
    ) -> None:
        super().__init__(coordinator)
        self._machine_id = machine_id
        self._attr_unique_id = f"{machine_id}_{key}"
        machine = coordinator.data[machine_id].machine
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, machine_id)},
            manufacturer=MANUFACTURER,
            model=machine.machine_type_name or None,
            name=machine.name,
            serial_number=machine_id,
        )

    @property
    def machine_data(self) -> MachineData | None:
        return (self.coordinator.data or {}).get(self._machine_id)

    @property
    def available(self) -> bool:
        return super().available and self.machine_data is not None
