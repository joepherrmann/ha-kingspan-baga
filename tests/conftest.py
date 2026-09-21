"""Shared fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.kingspan_baga.api import Command, Machine, Message

MACHINE_ID = "12345"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


def make_machine(**overrides) -> Machine:
    raw = {
        "id": MACHINE_ID,
        "address": "Testvägen 1",
        "city": "Teststad",
        "latitude": "60.0",
        "longitude": "13.0",
        "machine_type": {"id": "12", "name": "Easy Slamavskiljare G4"},
        "unread_messages": "184",
        "has_flocculant": "true",
        "allow_sms_events": "false",
        "agreements": [
            {
                "id": "1",
                "name": "Service",
                "services": [{"id": "242", "type": "Service", "period_months": "12"}],
            }
        ],
    }
    raw.update(overrides)
    return Machine.from_json(raw)


def make_message(
    msg_id: int,
    code: str,
    *,
    age: timedelta = timedelta(hours=1),
    data: str = "",
    is_command: bool = False,
    classification: str = "--",
) -> Message:
    created = datetime.now(tz=UTC) - age
    return Message(
        id=msg_id,
        code=code,
        description=f"description for {code}",
        classification_code=classification,
        data=data,
        is_command=is_command,
        created=created,
    )


DEFAULT_MESSAGES = [
    make_message(104, "--", data="LSA=249", is_command=True),
    make_message(103, "13590", age=timedelta(hours=2), classification="45"),
    make_message(102, "11111", age=timedelta(days=3)),
    make_message(101, "13000", age=timedelta(days=3), classification="45"),
    make_message(100, "13001", age=timedelta(days=3, minutes=3), classification="47"),
]
DEEP_MESSAGES = [
    make_message(50, "11141", age=timedelta(days=200)),
    make_message(49, "11140", age=timedelta(days=201)),
]

MESSAGE_TYPES = {
    "13001": "Avloppsanläggning Strömlös.",
    "13000": "Ström tillbaka! Kontrollera funktion!",
    "11111": "Låg nivå flockningsmedel. Dags att byta dunk.",
    "11110": "Nivå Flockningsmedel OK.",
    "11140": "Slamavskiljaren fylls på.",
    "11141": "Slamavskiljaren tömd.",
    "13590": "GSM Modul har hittat nät! OK.",
}

COMMANDS = [
    Command(
        id="971",
        command="RLSA",
        description="Aktuell nivå i tank (mm).",
        cardinality="read",
    ),
    Command(
        id="1843",
        command="RDPT",
        description="Gångtid doserpump i sekunder, 0=AV",
        cardinality="read",
    ),
    Command(
        id="131185",
        command="RFU1",
        description="Status på säkring F1",
        cardinality="read",
    ),
]

MACHINE_INFO = {
    "Workorders": {
        "DATA": [
            {
                "status": "invoiced",
                "start_date": "2026-06-18 00:00:00",
                "due_date": "2026-07-18 00:00:00",
                "done_date": "2026-07-02 15:46:17",
            }
        ]
    }
}


@pytest.fixture
def mock_client() -> AsyncMock:
    """A BagaClient double with realistic answers."""
    client = AsyncMock()
    client.async_login.return_value = None
    client.get_user.return_value = {"id": "3146"}
    client.get_machines.return_value = [make_machine()]

    def messages(machine_id, *, start_row=0, limit=20):
        if start_row == 0:
            return list(DEFAULT_MESSAGES)
        if start_row == 20:
            return list(DEEP_MESSAGES)
        return []

    client.get_messages.side_effect = messages
    client.get_message_types.return_value = dict(MESSAGE_TYPES)
    client.get_commands.return_value = list(COMMANDS)
    client.get_machine_info.return_value = MACHINE_INFO
    client.send_command.return_value = None
    return client


@pytest.fixture
def patch_client(mock_client: AsyncMock):
    """Patch BagaClient everywhere it is instantiated."""
    with (
        patch(
            "custom_components.kingspan_baga.BagaClient",
            return_value=mock_client,
        ),
        patch(
            "custom_components.kingspan_baga.config_flow.BagaClient",
            return_value=mock_client,
        ),
    ):
        yield mock_client
