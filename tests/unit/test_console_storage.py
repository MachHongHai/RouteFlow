from typing import Any

import pytest

from routeflow import console_storage as storage


def test_portable_console_does_not_read_workstation_paths(monkeypatch: Any) -> None:
    monkeypatch.setattr(storage, "CONTAINER_MODE", True)
    monkeypatch.setenv("ROUTEFLOW_CONSOLE_STORAGE_POLICY", "docker-volume")
    monkeypatch.setattr(storage, "workstation_storage_summary", lambda: pytest.fail("Host read"))
    result = storage.storage_summary()
    assert result["policy"] == "docker-volume"
    assert result["pinned_to_e"] is None
    assert storage.storage_ready(result)


def test_workstation_policy_fails_closed_when_metadata_is_missing(monkeypatch: Any) -> None:
    monkeypatch.setattr(storage, "CONTAINER_MODE", True)
    monkeypatch.setenv("ROUTEFLOW_CONSOLE_STORAGE_POLICY", "workstation")

    def missing() -> None:
        raise FileNotFoundError("Host snapshot missing")

    monkeypatch.setattr(storage, "workstation_storage_summary", missing)
    result = storage.storage_summary()
    assert result["policy"] == "workstation"
    assert result["pinned_to_e"] is False
    assert not storage.storage_ready(result)


@pytest.mark.parametrize(
    "snapshot,ready",
    [
        ({"pinned_to_e": True}, True),
        ({"pinned_to_e": False}, False),
        ({"controls_allowed": False, "pinned_to_e": True}, False),
        ({"controls_allowed": True, "pinned_to_e": None}, True),
    ],
)
def test_explicit_storage_policy_takes_precedence(snapshot: dict[str, Any], ready: bool) -> None:
    assert storage.storage_ready(snapshot) is ready
