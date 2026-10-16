import json
from datetime import timedelta
from typing import Any

import pytest

from routeflow.contracts import check_compatibility, validate
from routeflow.domain import TRANSITIONS
from routeflow.models import now
from routeflow.operations import validate_range
from routeflow.relay import backoff


def test_terminal_states() -> None:
    assert "DELIVERED" not in TRANSITIONS.get("ORDER_CANCELLED", set())
    assert "ORDER_CANCELLED" not in TRANSITIONS.get("IN_TRANSIT", set())
    assert "REFUND_CREATED" in TRANSITIONS["DELIVERED"]


@pytest.mark.parametrize("attempt,expected", [(1, 2), (2, 4), (8, 256), (9, 300), (100, 300)])
def test_backoff(attempt: int, expected: int) -> None:
    assert backoff(attempt) == expected


def test_date_range() -> None:
    today = now().date()
    validate_range(today - timedelta(days=7), today)
    for start, end in [
        (today, today - timedelta(days=1)),
        (today, today + timedelta(days=1)),
        (today - timedelta(days=400), today),
    ]:
        with pytest.raises(ValueError):
            validate_range(start, end)


def test_archive_round_trip(tmp_path: Any, monkeypatch: Any) -> None:
    from routeflow.config import settings
    from routeflow.storage import Archive

    monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path))
    settings.cache_clear()
    data = b"\x00not json\xff"
    archive = Archive()
    assert archive.write(data) == archive.write(data)
    assert list(archive.read()) == [data]
    settings.cache_clear()


def test_schema_evolution(event: dict[str, Any]) -> None:
    check_compatibility()
    validate(event)
    event["event_version"] = 2
    event["traceparent"] = "00-test"
    validate(event)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "version", "boolean_version", "object_version", "coordinates", "nan", "time"],
)
def test_invalid_contracts(event: dict[str, Any], mutation: str) -> None:
    if mutation == "missing":
        del event["event_id"]
    elif mutation == "version":
        event["event_version"] = 99
    elif mutation == "boolean_version":
        event["event_version"] = True
    elif mutation == "object_version":
        event["event_version"] = {}
    elif mutation == "coordinates":
        event["payload"]["latitude"] = 100
    elif mutation == "nan":
        event["payload"]["latitude"] = float("nan")
    else:
        event["event_time"] = "2026-01-01T01:00:00"
    with pytest.raises((ValueError, __import__("jsonschema").ValidationError)):
        validate(event)
    assert json.dumps(event)
