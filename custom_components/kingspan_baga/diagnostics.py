"""Diagnostics support: enough to extend the code mapping, nothing personal."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import BagaConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BagaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Deliberately built up from scratch (allowlist) instead of redacting the
    raw data, so personal data cannot leak through a missed key.
    """
    coordinator = entry.runtime_data
    machines: dict[str, Any] = {}
    for machine_id, data in (coordinator.data or {}).items():
        machines[machine_id] = {
            "machine_type_id": data.machine.machine_type_id,
            "machine_type_name": data.machine.machine_type_name,
            "has_flocculant": data.machine.has_flocculant,
            "message_types": data.message_types,
            "commands": [
                {
                    "command": c.command,
                    "description": c.description,
                    "cardinality": c.cardinality,
                }
                for c in data.commands
            ],
            "pair_states": data.pair_states,
            "command_values": data.command_values,
            "recent_messages": [
                {
                    "code": m.code,
                    "classification": m.classification_code,
                    "data": m.data,
                    "is_command": m.is_command,
                    "created": m.created.isoformat(),
                }
                for m in ([data.last_message] if data.last_message else [])
            ],
            "last_seen_id": data.last_seen_id,
        }
    return {"machines": machines}
