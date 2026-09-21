"""Constants for the Kingspan BAGA integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "kingspan_baga"
MANUFACTURER = "Kingspan BAGA"

CONF_LANG = "lang"
CONF_CONNECTIVITY_DAYS = "connectivity_days"
CONF_SCAN_INTERVAL = "scan_interval"

# Polling is in minutes; configurable 5 min - 24 h.
DEFAULT_SCAN_INTERVAL_MIN = 60
MIN_SCAN_INTERVAL_MIN = 5
MAX_SCAN_INTERVAL_MIN = 1440
# The unit can be silent for weeks (19-day gaps observed); 30 days default.
DEFAULT_CONNECTIVITY_DAYS = 30

SLOW_UPDATE_INTERVAL = timedelta(hours=6)

# After sending a command, poll for the reply every 20 s for up to 3 min.
COMMAND_POLL_INTERVAL = 20
COMMAND_POLL_TIMEOUT = 180
# Manual cooldown between button presses (each press likely costs an SMS).
COMMAND_COOLDOWN = 60

# Known info-code pairs (on_code, off_code) → binary sensor state.
# Codes are model-specific; unknown codes still flow through the event entity.
CODE_PAIRS: dict[str, tuple[str, str]] = {
    "power_failure": ("13001", "13000"),
    "flocculant_low": ("11111", "11110"),
    "tank_filling": ("11140", "11141"),
}

CODE_TANK_EMPTIED = "11141"

# classification_code → severity for event/last_event attributes.
SEVERITY_MAP = {"47": "critical", "45": "info"}
SEVERITY_NONE = "none"

EVENT_TYPE_COMMAND_RESPONSE = "command_response"
EVENT_TYPE_UNKNOWN = "unknown"

# Command-response prefixes with known semantics (Easy SA G4).
CMD_PREFIX_TANK_LEVEL = "LSA"  # mm
CMD_PREFIX_PUMP_RUNTIME = "DPT"  # seconds
CMD_PREFIX_FUSE = "FU1"  # OK / ...

# Deep pagination on first setup: keep fetching history until every mapped
# pair has been seen once, up to this many messages.
FIRST_SETUP_MAX_MESSAGES = 200
PAGE_SIZE = 20

# Cap on missed events replayed after a restart.
REPLAY_MAX_EVENTS = 20
REPLAY_MAX_AGE = timedelta(hours=24)

STORAGE_VERSION = 1
