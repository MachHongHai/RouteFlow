"""Versioned contracts, packaged with the application for identical local/cloud checks."""

import json
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ORDER_EVENTS = [
    "ORDER_CREATED",
    "PAYMENT_CONFIRMED",
    "PAYMENT_FAILED",
    "RESTAURANT_ACCEPTED",
    "DRIVER_ASSIGNED",
    "DRIVER_ARRIVED",
    "ORDER_PICKED_UP",
    "IN_TRANSIT",
    "DELIVERED",
    "ORDER_CANCELLED",
    "DRIVER_CANCELLED",
    "REFUND_CREATED",
]
REFERENCE_EVENTS = ["CUSTOMER_UPDATED", "RESTAURANT_UPDATED", "DRIVER_UPDATED", "ZONE_UPDATED"]
CONTRACT_DIR = Path(__file__).parent / "schemas"


def schema(version: int) -> dict[str, Any]:
    if type(version) is not int or version not in (1, 2):
        raise ValueError(f"Unsupported event version: {version}")
    return json.loads((CONTRACT_DIR / f"event-v{version}.json").read_text())  # type: ignore[no-any-return]


@lru_cache(maxsize=2, typed=True)
def validator(version: int) -> Draft202012Validator:
    return Draft202012Validator(schema(version), format_checker=FormatChecker())


def validate(event: dict[str, Any]) -> None:
    version = event.get("event_version", 0)
    if type(version) is not int:
        raise ValueError("event_version must be an integer")
    validator(version).validate(event)
    for field in ("event_time", "produced_at"):
        value = datetime.fromisoformat(event[field].replace("Z", "+00:00"))
        if value.utcoffset() is None:
            raise ValueError(f"{field} requires timezone")
    payload = event["payload"]
    if event["event_type"] == "DRIVER_LOCATION":
        if not all(math.isfinite(payload[field]) for field in ("latitude", "longitude")):
            raise ValueError("GPS coordinates must be finite JSON numbers")
    if event["event_type"] in ORDER_EVENTS:
        if payload["order_id"] != event["aggregate_id"]:
            raise ValueError("Order identifier differs from aggregate identifier")
        if payload["status"] != event["event_type"]:
            raise ValueError("Order snapshot status differs from event type")


def check_compatibility() -> None:
    old, new = schema(1), schema(2)
    assert set(new["required"]) <= set(old["required"])
    assert set(old["properties"]) <= set(new["properties"])
    for key, value in old["properties"].items():
        if key == "event_version":
            continue
        assert value == new["properties"][key], f"Breaking field change: {key}"
    assert old["allOf"] == new["allOf"]
