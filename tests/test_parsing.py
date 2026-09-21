"""Tests for the HA-free parsing and derivation logic."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from custom_components.kingspan_baga.api import (
    Command,
    Machine,
    Message,
    WorkOrder,
    parse_server_dt,
)
from custom_components.kingspan_baga.coordinator import (
    compute_next_service,
    derive_pair_states,
)

from .conftest import make_message

FIXTURES = Path(__file__).parent / "fixtures"


def test_message_from_real_response() -> None:
    payload = json.loads((FIXTURES / "messages.json").read_text())
    groups = payload["DATA"]
    heartbeat = Message.from_json(groups[0]["message_list"][0])
    assert heartbeat.id == 13237434
    assert heartbeat.code == "13590"
    assert heartbeat.classification_code == "45"
    assert not heartbeat.is_command
    # 11:32:46 Stockholm (CEST) == 09:32:46 UTC
    assert heartbeat.created == datetime(2026, 9, 21, 9, 32, 46, tzinfo=UTC)

    reply = Message.from_json(groups[1]["message_list"][0])
    assert reply.is_command
    assert reply.command_value() == ("LSA", "249")


def test_command_value_edge_cases() -> None:
    assert make_message(1, "13590").command_value() is None
    assert make_message(1, "--", data="FU1=OK", is_command=True).command_value() == (
        "FU1",
        "OK",
    )
    assert make_message(1, "--", data="broken", is_command=True).command_value() is None


def test_command_response_prefix() -> None:
    rlsa = Command(id="1", command="RLSA", description="", cardinality="read")
    xyz = Command(id="1", command="XYZ", description="", cardinality="read")
    assert rlsa.response_prefix == "LSA"
    assert xyz.response_prefix == "XYZ"


def test_machine_parsing() -> None:
    machine = Machine.from_json(
        {
            "id": "10319",
            "address": "Testvägen 1",
            "city": "Teststad",
            "latitude": "60.72967",
            "longitude": "13.83394",
            "machine_type": {"id": "12", "name": "Easy Slamavskiljare G4"},
            "unread_messages": "184",
            "has_flocculant": "true",
            "allow_sms_events": "false",
        }
    )
    assert machine.id == "10319"
    assert machine.has_flocculant is True
    assert machine.allow_sms_events is False
    assert machine.unread_messages == 184
    assert machine.name == "Testvägen 1"


def test_parse_server_dt() -> None:
    assert parse_server_dt("0000-00-00 00:00:00") is None
    assert parse_server_dt(None) is None
    parsed = parse_server_dt("2026-07-02 15:46:17")
    assert parsed is not None and parsed.tzinfo is not None


def test_derive_pair_states_newest_wins() -> None:
    messages = [  # newest first
        make_message(103, "13000", age=timedelta(hours=1)),
        make_message(102, "13001", age=timedelta(hours=2)),
        make_message(101, "11111", age=timedelta(hours=3)),
    ]
    states: dict[str, bool | None] = {}
    changed: dict[str, datetime | None] = {}
    derive_pair_states(messages, states, changed)
    assert states["power_failure"] is False  # 13000 is newest
    assert states["flocculant_low"] is True
    assert "tank_filling" not in states  # never seen


def test_derive_pair_states_never_regresses() -> None:
    states: dict[str, bool | None] = {}
    changed: dict[str, datetime | None] = {}
    recent = [make_message(10, "13001", age=timedelta(hours=1))]
    derive_pair_states(recent, states, changed)
    assert states["power_failure"] is True
    # Replaying older history must not overwrite the newer state.
    old = [make_message(5, "13000", age=timedelta(days=2))]
    derive_pair_states(old, states, changed)
    assert states["power_failure"] is True


def test_compute_next_service() -> None:
    done = WorkOrder(
        status="invoiced",
        start_date=None,
        due_date=None,
        done_date=datetime(2026, 7, 2, 13, 46, tzinfo=UTC),
    )
    agreements = [{"services": [{"period_months": "12"}]}]
    last, nxt = compute_next_service([done], agreements)
    assert last == done.done_date
    assert nxt is not None and nxt.year == 2027 and nxt.month == 7

    open_order = WorkOrder(
        status="open",
        start_date=None,
        due_date=datetime(2026, 10, 1, tzinfo=UTC),
        done_date=None,
    )
    _, nxt = compute_next_service([done, open_order], agreements)
    assert nxt == open_order.due_date
