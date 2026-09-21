"""Async client for the Kingspan BAGA (mittBAGA) cloud API.

This module is deliberately free of Home Assistant imports so it can be
split off into a standalone PyPI package later.

The API was reverse-engineered from the mittBAGA app (com.baga.app 1.3).
All responses share the envelope::

    {"HEAD": {"action": ..., "status": "SUCCESS", "message"?: ...},
     "DATA": ..., "COUNT"?: n}

Authentication: ``login.php`` with the credentials in the ``x-login`` /
``x-password`` headers returns a session ``key`` that stays valid for
seven days. There is no refresh endpoint; the app simply logs in again.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://kingspanservice.se/applications/190_13/api"
# Fixed application secret shipped inside the mittBAGA app bundle. It is not
# user-specific; Kingspan may rotate it with an app update.
APP_SECRET = "e1beb1312df2863efb9a65dcad66262a"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
# The key is valid for 7 days; renew it a day early.
KEY_LIFETIME = timedelta(days=6)
# The backend reports timestamps in Swedish local time.
SERVER_TZ = ZoneInfo("Europe/Stockholm")


class BagaError(Exception):
    """Base error for the BAGA API."""


class BagaConnectionError(BagaError):
    """Network problem, timeout or unexpected HTTP status."""


class BagaAuthError(BagaError):
    """The credentials were rejected."""


class BagaApiError(BagaError):
    """The API answered with a non-SUCCESS status."""


def _to_bool(value: Any) -> bool:
    return str(value).lower() == "true"


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_server_dt(value: Any) -> datetime | None:
    """Parse a server-local ``YYYY-MM-DD HH:MM:SS`` string to aware UTC."""
    if not value or str(value).startswith("0000-00-00"):
        return None
    try:
        naive = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=SERVER_TZ).astimezone(UTC)


@dataclass(slots=True)
class Message:
    """One machine message (event or command response)."""

    id: int
    code: str
    description: str
    classification_code: str
    data: str
    is_command: bool
    created: datetime

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Message:
        info = raw.get("info_code") or {}
        epoch = raw.get("created_date_strtotime")
        if epoch:
            created = datetime.fromtimestamp(int(epoch), tz=UTC)
        else:
            created = parse_server_dt(raw.get("created_date")) or datetime.now(
                tz=UTC
            )
        return cls(
            id=_to_int(raw.get("id")),
            code=str(info.get("info_code") or "--"),
            description=(info.get("description") or "").strip(),
            classification_code=str(info.get("classification_code") or "--"),
            data=(raw.get("data") or "").strip(),
            is_command=bool(raw.get("is_command")),
            created=created,
        )

    def command_value(self) -> tuple[str, str] | None:
        """Return ``(prefix, value)`` for a command response like ``LSA=249``."""
        if not self.is_command or "=" not in self.data:
            return None
        prefix, _, value = self.data.partition("=")
        prefix = prefix.strip()
        value = value.strip()
        if not prefix or not value:
            return None
        return prefix, value


@dataclass(slots=True)
class Command:
    """A command the machine supports (e.g. RLSA = read tank level)."""

    id: str
    command: str
    description: str
    cardinality: str

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Command:
        return cls(
            id=str(raw.get("id") or ""),
            command=str(raw.get("command") or ""),
            description=(raw.get("description") or "").strip(),
            cardinality=str(raw.get("cardinality") or ""),
        )

    @property
    def response_prefix(self) -> str:
        """RLSA responses arrive as ``LSA=<value>``: the command minus its R."""
        return self.command[1:] if self.command.startswith("R") else self.command


@dataclass(slots=True)
class WorkOrder:
    """A service work order."""

    status: str
    start_date: datetime | None
    due_date: datetime | None
    done_date: datetime | None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> WorkOrder:
        return cls(
            status=str(raw.get("status") or ""),
            start_date=parse_server_dt(raw.get("start_date")),
            due_date=parse_server_dt(raw.get("due_date")),
            done_date=parse_server_dt(raw.get("done_date")),
        )


@dataclass(slots=True)
class Machine:
    """One BAGA installation on the account."""

    id: str
    address: str
    city: str
    latitude: float | None
    longitude: float | None
    machine_type_id: str
    machine_type_name: str
    unread_messages: int
    has_flocculant: bool
    allow_sms_events: bool
    agreements: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Machine:
        mtype = raw.get("machine_type") or {}
        return cls(
            id=str(raw.get("id")),
            address=str(raw.get("address") or "").strip(),
            city=str(raw.get("city") or "").strip(),
            latitude=_to_float(raw.get("latitude")),
            longitude=_to_float(raw.get("longitude")),
            machine_type_id=str(mtype.get("id") or ""),
            machine_type_name=str(mtype.get("name") or "").strip(),
            unread_messages=_to_int(raw.get("unread_messages")),
            has_flocculant=_to_bool(raw.get("has_flocculant")),
            allow_sms_events=_to_bool(raw.get("allow_sms_events")),
            agreements=list(raw.get("agreements") or []),
        )

    @property
    def name(self) -> str:
        return self.address or f"BAGA {self.id}"


class BagaClient:
    """Minimal async client for the mittBAGA backend."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        lang: str = "sv",
        *,
        base_url: str = BASE_URL,
        secret: str = APP_SECRET,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self.lang = lang
        self._base_url = base_url
        self._secret = secret
        self._key: str | None = None
        self._key_expires: datetime | None = None
        self._login_lock = asyncio.Lock()

    # ------------------------------------------------------------------ auth
    async def async_login(self) -> None:
        """Log in and store the session key (valid for 7 days)."""
        headers = {"x-login": self._email, "x-password": self._password}
        try:
            data = await self._raw_request(
                "GET", "login.php", headers=headers, auth=False
            )
        except BagaApiError as err:
            # TODO(step 3): verify what a wrong password actually returns; for
            # now any non-SUCCESS on login.php is treated as bad credentials.
            raise BagaAuthError(str(err)) from err
        key = (data or {}).get("key")
        if not key:
            raise BagaAuthError("login.php returned no session key")
        self._key = key
        self._key_expires = datetime.now(tz=UTC) + KEY_LIFETIME
        _LOGGER.debug("Logged in; key valid until %s", data.get("due_date"))

    def _key_valid(self) -> bool:
        return bool(
            self._key
            and self._key_expires
            and datetime.now(tz=UTC) < self._key_expires
        )

    async def _ensure_key(self) -> None:
        if self._key_valid():
            return
        async with self._login_lock:
            if not self._key_valid():
                await self.async_login()

    # ------------------------------------------------------------- transport
    async def _raw_request(
        self,
        method: str,
        script: str,
        *,
        params: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: bool = True,
    ) -> Any:
        if auth:
            await self._ensure_key()
        common = {"secret": self._secret, "lang": self.lang}
        if auth:
            common["key"] = self._key

        url = f"{self._base_url}/{method}/{script}"
        query: dict[str, Any] | None = None
        body: aiohttp.FormData | None = None
        if method == "GET":
            query = {**(params or {}), **common}
        else:
            body = aiohttp.FormData()
            for k, v in {**(form or {}), **common}.items():
                body.add_field(k, str(v))

        try:
            async with self._session.request(
                method,
                url,
                params=query,
                data=body,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise BagaConnectionError(f"Error talking to BAGA API: {err}") from err
        except ValueError as err:
            raise BagaConnectionError("BAGA API returned invalid JSON") from err

        head = (payload or {}).get("HEAD") or {}
        if head.get("status") != "SUCCESS":
            raise BagaApiError(
                head.get("message") or head.get("status") or "unknown API error"
            )
        return (payload or {}).get("DATA")

    async def _request(
        self,
        method: str,
        script: str,
        *,
        params: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> Any:
        """Authenticated request; retries once with a fresh key on failure.

        The error shape of an expired key is not yet known (see PLAN.md), so
        any non-SUCCESS answer triggers one re-login + retry before failing.
        """
        try:
            return await self._raw_request(method, script, params=params, form=form)
        except BagaApiError:
            _LOGGER.debug("Retrying %s after re-login", script)
            async with self._login_lock:
                await self.async_login()
            return await self._raw_request(method, script, params=params, form=form)

    # ------------------------------------------------------------- endpoints
    async def get_user(self) -> dict[str, Any]:
        return await self._request("GET", "get_user_info.php") or {}

    async def get_machines(self) -> list[Machine]:
        data = await self._request("GET", "get_user_machines.php") or {}
        return [Machine.from_json(m) for m in data.get("Machines") or []]

    async def get_machine_info(self, machine_id: str) -> dict[str, Any]:
        return (
            await self._request(
                "GET", "get_machine_info.php", params={"machine_id": machine_id}
            )
            or {}
        )

    async def get_messages(
        self, machine_id: str, *, start_row: int = 0, limit: int = 20
    ) -> list[Message]:
        """Fetch messages, flattened out of their per-hour groups, newest first."""
        data = (
            await self._request(
                "GET",
                "get_machine_messages.php",
                params={
                    "machine_id": machine_id,
                    "start_row": start_row,
                    "limit": limit,
                },
            )
            or []
        )
        seen: set[int] = set()
        messages: list[Message] = []
        for group in data:
            for raw in group.get("message_list") or []:
                msg = Message.from_json(raw)
                if msg.id in seen:
                    continue
                seen.add(msg.id)
                messages.append(msg)
        messages.sort(key=lambda m: m.id, reverse=True)
        return messages

    async def get_message_types(self, machine_id: str) -> dict[str, str]:
        data = (
            await self._request(
                "GET",
                "get_machine_message_types.php",
                params={"machine_id": machine_id},
            )
            or []
        )
        return {
            str(item.get("type")): (item.get("description") or "").strip()
            for item in data
        }

    async def get_commands(self, machine_id: str) -> list[Command]:
        data = (
            await self._request(
                "GET",
                "get_machine_communication_commands.php",
                params={"machine_id": machine_id},
            )
            or []
        )
        return [Command.from_json(c) for c in data]

    async def send_command(self, machine_id: str, command: str) -> None:
        """Send a read command; the reply arrives later as a machine message.

        Commands are most likely relayed to the unit by SMS: use sparingly.
        """
        await self._request(
            "POST",
            "send_machine_communication_command.php",
            form={"machine_id": machine_id, "command": command},
        )
