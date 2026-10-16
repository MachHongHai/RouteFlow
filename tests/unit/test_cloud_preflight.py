import json
from pathlib import Path
from typing import Any

import pytest

from routeflow.cloud_preflight import REQUIRED_APIS, inspect_config, inspect_remote, report


def configuration() -> dict[str, Any]:
    return {
        "project_id": "routeflow-demo-123",
        "region": "us-central1",
        "image": "us-central1-docker.pkg.dev/routeflow-demo-123/routeflow/app@sha256:" + "a" * 64,
        "source_database_secret": "routeflow-source-url",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id", "routeflow-local"),
        ("project_id", "invalid-"),
        ("image", "us-central1-docker.pkg.dev/another-project/routeflow/app:latest"),
        ("source_database_secret", "postgresql://user:secret@host/db"),
        ("max_instances", True),
        ("scheduler_paused", "false"),
    ],
)
def test_invalid_configuration_is_blocked_without_echoing_values(field: str, value: Any) -> None:
    config = configuration()
    config[field] = value
    checks = inspect_config(config)
    assert any(check.status == "blocked" for check in checks)
    assert "user:secret" not in str(checks)


def test_valid_configuration_does_not_claim_cloud_validation() -> None:
    checks = inspect_config(configuration())
    assert not any(check.status == "blocked" for check in checks)
    assert next(check for check in checks if check.name == "cloud_spark").status == "warning"
    assert next(check for check in checks if check.name == "postgres_tls").status == "unverified"


def test_absent_config_and_credentials_do_not_contact_cloud(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    monkeypatch.setattr(
        "routeflow.cloud_preflight.inspect_online",
        lambda *_: pytest.fail("Must not contact cloud without prerequisites"),
    )
    result = report(tmp_path / "missing.json", online=True)
    assert result["blocked"]
    assert not result["cloud_connection_verified"]
    assert not result["deployment_verified"]


def test_offline_existing_adc_is_unverified(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "adc.json"))
    (tmp_path / "adc.json").write_text('{"refresh_token":"DO_NOT_PRINT_ME"}')
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(configuration()))
    result = report(config_file)
    assert not result["blocked"]
    assert not result["cloud_connection_verified"]
    assert "DO_NOT_PRINT_ME" not in json.dumps(result)


class Response:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self.body = body

    def json(self) -> dict[str, Any]:
        return self.body


class ReadOnlyClient:
    def __init__(self, billing: bool = True, forbidden: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.billing = billing
        self.forbidden = forbidden

    def get(self, url: str, **kwargs: Any) -> Response:
        self.calls.append((url, kwargs))
        if self.forbidden:
            return Response(403, {"error": "SENSITIVE_RESPONSE_BODY"})
        if url.endswith("billingInfo"):
            return Response(200, {"billingEnabled": self.billing})
        if url.endswith("/services"):
            apis = sorted(REQUIRED_APIS)
            second_page = kwargs["params"]["pageToken"] == "page-two"
            return Response(
                200,
                {
                    "services": [
                        {"config": {"name": api}} for api in (apis[5:] if second_page else apis[:5])
                    ],
                    "nextPageToken": "" if second_page else "page-two",
                },
            )
        return Response(200, {"lifecycleState": "ACTIVE", "projectNumber": "1234567890"})


def test_online_reads_all_api_pages_and_detects_disabled_billing() -> None:
    client = ReadOnlyClient(billing=False)
    checks = inspect_remote(client, "routeflow-demo-123")
    assert next(check for check in checks if check.name == "billing_enabled").status == "blocked"
    assert next(check for check in checks if check.name == "enabled_apis").status == "pass"
    assert len(client.calls) == 4
    assert all("/projects/1234567890/" in url for url, _ in client.calls[2:])
    assert all(call[1]["timeout"] == 20 for call in client.calls)


def test_forbidden_online_checks_do_not_leak_response_body() -> None:
    checks = inspect_remote(ReadOnlyClient(forbidden=True), "routeflow-demo-123")
    assert all(check.status == "blocked" for check in checks)
    assert "SENSITIVE_RESPONSE_BODY" not in str(checks)


def test_online_project_checks_never_assert_deployment(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "adc.json"))
    (tmp_path / "adc.json").write_text("{}")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(configuration()))
    monkeypatch.setattr(
        "routeflow.cloud_preflight.inspect_online",
        lambda *_: inspect_remote(ReadOnlyClient(), "routeflow-demo-123"),
    )
    result = report(config_file, online=True)
    assert not result["blocked"]
    assert result["cloud_connection_verified"]
    assert not result["deployment_verified"]
