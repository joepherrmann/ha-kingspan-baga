"""Data update coordinator for Kingspan BAGA."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BagaApiError,
    BagaAuthError,
    BagaClient,
    BagaConnectionError,
    BagaError,
    Command,
    Machine,
    Message,
    WorkOrder,
)
from .const import (
    CODE_PAIRS,
    CODE_TANK_EMPTIED,
    COMMAND_POLL_INTERVAL,
    COMMAND_POLL_TIMEOUT,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_MIN,
    DOMAIN,
    FIRST_SETUP_MAX_MESSAGES,
    PAGE_SIZE,
    REPLAY_MAX_AGE,
    REPLAY_MAX_EVENTS,
    SLOW_UPDATE_INTERVAL,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

type BagaConfigEntry = ConfigEntry[BagaCoordinator]


@dataclass
class MachineData:
    """Everything the entities need for one machine."""

    machine: Machine
    # pair key -> True (problem code newest) / False / None (never seen)
    pair_states: dict[str, bool | None] = field(default_factory=dict)
    pair_changed: dict[str, datetime | None] = field(default_factory=dict)
    # command-response prefix (LSA/DPT/FU1) -> latest raw value
    command_values: dict[str, str] = field(default_factory=dict)
    command_updated: dict[str, datetime] = field(default_factory=dict)
    last_emptied: datetime | None = None
    last_message: Message | None = None
    last_seen_id: int = 0
    # messages the event entity still has to fire, oldest first
    new_messages: list[Message] = field(default_factory=list)
    # slow data
    message_types: dict[str, str] = field(default_factory=dict)
    commands: list[Command] = field(default_factory=list)
    workorders: list[WorkOrder] = field(default_factory=list)
    last_service: datetime | None = None
    next_service: datetime | None = None


def derive_pair_states(
    messages: list[Message],
    current: dict[str, bool | None],
    changed: dict[str, datetime | None],
) -> None:
    """Update pair states in place from a batch of messages.

    Only messages newer than the stored change timestamp win, so replaying
    old history never regresses the state.
    """
    for key, (on_code, off_code) in CODE_PAIRS.items():
        for msg in messages:  # newest first
            if msg.code not in (on_code, off_code):
                continue
            prev = changed.get(key)
            if prev is None or msg.created > prev:
                current[key] = msg.code == on_code
                changed[key] = msg.created
            break


def compute_next_service(
    workorders: list[WorkOrder], agreements: list[dict[str, Any]]
) -> tuple[datetime | None, datetime | None]:
    """Return (last_service, next_service) from work orders and agreements."""
    last_service: datetime | None = None
    next_service: datetime | None = None

    done = [w.done_date for w in workorders if w.done_date]
    if done:
        last_service = max(done)

    open_orders = [w.due_date for w in workorders if not w.done_date and w.due_date]
    if open_orders:
        next_service = min(open_orders)
    elif last_service:
        # Best-effort estimate: last service + the agreement interval.
        months = 12
        for agreement in agreements:
            for service in agreement.get("services") or []:
                try:
                    months = int(service.get("period_months"))
                except (TypeError, ValueError):
                    continue
                break
        # Naive month addition is fine for an estimate.
        month = last_service.month - 1 + months
        year = last_service.year + month // 12
        next_service = last_service.replace(year=year, month=month % 12 + 1)

    return last_service, next_service


class BagaCoordinator(DataUpdateCoordinator[dict[str, MachineData]]):
    """Coordinator polling the mittBAGA cloud for all machines on an account."""

    config_entry: BagaConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: BagaConfigEntry, client: BagaClient
    ) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MIN)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._stored: dict[str, Any] | None = None
        self._slow_updated: datetime | None = None
        self._pending_commands: set[str] = set()
        self._apply_lock = asyncio.Lock()

    # ------------------------------------------------------------------ store
    async def _load_store(self) -> dict[str, Any]:
        if self._stored is None:
            self._stored = await self._store.async_load() or {}
        return self._stored

    def _save_store(self) -> None:
        assert self._stored is not None
        self._store.async_delay_save(lambda: self._stored, 10)

    @staticmethod
    def _machine_to_stored(data: MachineData) -> dict[str, Any]:
        return {
            "last_seen_id": data.last_seen_id,
            "pair_states": data.pair_states,
            "pair_changed": {
                k: v.isoformat() if v else None for k, v in data.pair_changed.items()
            },
            "command_values": data.command_values,
            "command_updated": {
                k: v.isoformat() for k, v in data.command_updated.items()
            },
            "last_emptied": data.last_emptied.isoformat()
            if data.last_emptied
            else None,
        }

    @staticmethod
    def _stored_to_machine(data: MachineData, stored: dict[str, Any]) -> None:
        data.last_seen_id = stored.get("last_seen_id") or 0
        data.pair_states = dict(stored.get("pair_states") or {})
        data.pair_changed = {
            k: datetime.fromisoformat(v) if v else None
            for k, v in (stored.get("pair_changed") or {}).items()
        }
        data.command_values = dict(stored.get("command_values") or {})
        data.command_updated = {
            k: datetime.fromisoformat(v)
            for k, v in (stored.get("command_updated") or {}).items()
        }
        if stored.get("last_emptied"):
            data.last_emptied = datetime.fromisoformat(stored["last_emptied"])

    # ----------------------------------------------------------------- update
    async def _async_update_data(self) -> dict[str, MachineData]:
        async with self._apply_lock:
            try:
                return await self._update()
            except BagaAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except (BagaConnectionError, BagaApiError) as err:
                raise UpdateFailed(str(err)) from err

    async def _update(self) -> dict[str, MachineData]:
        stored = await self._load_store()
        previous = self.data or {}
        machines = await self.client.get_machines()
        refresh_slow = (
            self._slow_updated is None
            or datetime.now(tz=UTC) - self._slow_updated
            > SLOW_UPDATE_INTERVAL
        )

        result: dict[str, MachineData] = {}
        for machine in machines:
            prev = previous.get(machine.id)
            data = MachineData(machine=machine)
            machine_stored = stored.get(machine.id)
            first_setup = machine_stored is None and prev is None

            if prev is not None:
                # Carry over in-memory state from the previous cycle.
                data.pair_states = dict(prev.pair_states)
                data.pair_changed = dict(prev.pair_changed)
                data.command_values = dict(prev.command_values)
                data.command_updated = dict(prev.command_updated)
                data.last_emptied = prev.last_emptied
                data.last_message = prev.last_message
                data.last_seen_id = prev.last_seen_id
                data.message_types = prev.message_types
                data.commands = prev.commands
                data.workorders = prev.workorders
                data.last_service = prev.last_service
                data.next_service = prev.next_service
            elif machine_stored is not None:
                self._stored_to_machine(data, machine_stored)

            messages = await self._fetch_messages(machine.id, first_setup)
            self._apply_messages(data, messages, replay=not first_setup)

            if refresh_slow:
                await self._refresh_slow(data)

            stored[machine.id] = self._machine_to_stored(data)
            result[machine.id] = data

        if refresh_slow:
            self._slow_updated = datetime.now(tz=UTC)
        self._save_store()
        return result

    async def _fetch_messages(
        self, machine_id: str, first_setup: bool
    ) -> list[Message]:
        """Fetch recent messages; on first setup page deeper into history.

        Codes like a tank emptying happen ~yearly and are almost never in the
        newest 20 messages, so the very first run keeps paging until every
        mapped pair has been seen once (bounded by FIRST_SETUP_MAX_MESSAGES).
        """
        messages = await self.client.get_messages(machine_id, limit=PAGE_SIZE)
        if not first_setup:
            return messages

        def unresolved() -> bool:
            codes = {m.code for m in messages}
            return any(
                not ({on, off} & codes) for on, off in CODE_PAIRS.values()
            )

        start_row = PAGE_SIZE
        while unresolved() and len(messages) < FIRST_SETUP_MAX_MESSAGES:
            page = await self.client.get_messages(
                machine_id, start_row=start_row, limit=PAGE_SIZE
            )
            if not page:
                break
            known = {m.id for m in messages}
            new = [m for m in page if m.id not in known]
            if not new:
                break
            messages.extend(new)
            start_row += PAGE_SIZE
        messages.sort(key=lambda m: m.id, reverse=True)
        return messages

    def _apply_messages(
        self, data: MachineData, messages: list[Message], *, replay: bool
    ) -> None:
        """Fold a batch of messages (newest first) into the machine state."""
        if messages:
            newest = messages[0]
            if data.last_message is None or newest.id > data.last_message.id:
                data.last_message = newest

        new = sorted(
            (m for m in messages if m.id > data.last_seen_id), key=lambda m: m.id
        )
        if replay and new:
            cutoff = datetime.now(tz=UTC) - REPLAY_MAX_AGE
            data.new_messages = [m for m in new if m.created >= cutoff][
                -REPLAY_MAX_EVENTS:
            ]
        else:
            # Very first run: set the baseline without firing a flood of
            # historic events.
            data.new_messages = []
        if new:
            data.last_seen_id = new[-1].id

        derive_pair_states(messages, data.pair_states, data.pair_changed)

        for msg in messages:
            if (parsed := msg.command_value()) is None:
                continue
            prefix, value = parsed
            prev = data.command_updated.get(prefix)
            if prev is None or msg.created > prev:
                data.command_values[prefix] = value
                data.command_updated[prefix] = msg.created

        emptied = [m.created for m in messages if m.code == CODE_TANK_EMPTIED]
        if emptied:
            newest_emptied = max(emptied)
            if data.last_emptied is None or newest_emptied > data.last_emptied:
                data.last_emptied = newest_emptied

    async def _refresh_slow(self, data: MachineData) -> None:
        machine_id = data.machine.id
        data.message_types = await self.client.get_message_types(machine_id)
        data.commands = await self.client.get_commands(machine_id)
        info = await self.client.get_machine_info(machine_id)
        raw_orders = ((info.get("Workorders") or {}).get("DATA")) or []
        data.workorders = [WorkOrder.from_json(w) for w in raw_orders]
        data.last_service, data.next_service = compute_next_service(
            data.workorders, data.machine.agreements
        )

    # --------------------------------------------------------------- commands
    def command_pending(self, machine_id: str) -> bool:
        return machine_id in self._pending_commands

    async def async_send_command(self, machine_id: str, command: Command) -> None:
        """Send a read command and poll until its reply arrives.

        Commands most likely reach the unit by SMS, so at most one command
        per machine may be in flight.
        """
        if machine_id in self._pending_commands:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_pending",
            )
        self._pending_commands.add(machine_id)
        try:
            baseline = datetime.now(tz=UTC)
            await self.client.send_command(machine_id, command.command)
        except BagaError as err:
            self._pending_commands.discard(machine_id)
            raise HomeAssistantError(
                f"Sending {command.command} failed: {err}"
            ) from err
        except Exception:
            self._pending_commands.discard(machine_id)
            raise
        self.config_entry.async_create_background_task(
            self.hass,
            self._poll_command_response(machine_id, command, baseline),
            name=f"{DOMAIN}_command_{machine_id}",
        )

    async def _poll_command_response(
        self, machine_id: str, command: Command, baseline: datetime
    ) -> None:
        prefix = command.response_prefix
        try:
            deadline = (
                datetime.now(tz=UTC)
                + timedelta(seconds=COMMAND_POLL_TIMEOUT)
            )
            while datetime.now(tz=UTC) < deadline:
                await asyncio.sleep(COMMAND_POLL_INTERVAL)
                await self.async_request_refresh()
                data = (self.data or {}).get(machine_id)
                if (
                    data
                    and (updated := data.command_updated.get(prefix))
                    and updated >= baseline
                ):
                    _LOGGER.debug(
                        "Reply to %s arrived: %s=%s",
                        command.command,
                        prefix,
                        data.command_values.get(prefix),
                    )
                    return
            _LOGGER.warning(
                "No reply to %s within %s s; the unit may be offline",
                command.command,
                COMMAND_POLL_TIMEOUT,
            )
        finally:
            self._pending_commands.discard(machine_id)
