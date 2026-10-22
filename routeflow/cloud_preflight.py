"""Read-only deployment checks. Offline results never assert a working GCP deployment."""

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REQUIRED_APIS = {
    "run.googleapis.com",
    "pubsub.googleapis.com",
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "workflows.googleapis.com",
    "workflowexecutions.googleapis.com",
    "cloudscheduler.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def inspect_config(config: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []

    def require(name: str, valid: bool, detail: str) -> None:
        checks.append(Check(name, "pass" if valid else "blocked", detail))

    project = config.get("project_id", "")
    require(
        "project_id",
        isinstance(project, str)
        and bool(re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project))
        and project not in {"your-gcp-project", "routeflow-local"},
        "Use a real GCP project ID.",
    )
    region = config.get("region", "us-central1")
    require(
        "region",
        isinstance(region, str) and bool(re.fullmatch(r"[a-z]+-[a-z]+[0-9]", region)),
        "Use a single region shared by Cloud Run, GCS and BigQuery.",
    )
    image = config.get("image", "")
    expected = re.escape(f"{region}-docker.pkg.dev/{project}/routeflow/app@sha256:")
    require(
        "image",
        isinstance(image, str) and bool(re.fullmatch(expected + r"[a-f0-9]{64}", image)),
        "Use the built Artifact Registry app digest for this project and region.",
    )
    secret = config.get("source_database_secret", "")
    require(
        "source_database_secret",
        isinstance(secret, str) and bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,255}", secret)),
        "Use a Secret Manager secret name, never a database URL or password.",
    )
    environment = config.get("environment", "portfolio")
    require(
        "environment",
        isinstance(environment, str) and bool(re.fullmatch(r"[a-z][a-z0-9-]{0,10}", environment)),
        "Environment must fit the Terraform service-account naming rules.",
    )
    maximum = config.get("max_instances", 1)
    require(
        "max_instances",
        type(maximum) is int and maximum >= 1,
        "Set a positive integer instance limit; the default is one.",
    )
    paused = config.get("scheduler_paused", True)
    require("scheduler_type", type(paused) is bool, "scheduler_paused must be a JSON boolean.")
    checks.append(
        Check(
            "scheduler",
            "pass" if paused is True else "warning",
            "Keep Scheduler paused until cloud smoke tests pass.",
        )
    )
    email = config.get("notification_email", "")
    require(
        "notification_email_format",
        isinstance(email, str)
        and (not email or bool(re.fullmatch(r"[^ @]+@[^ @]+\.[^ @]+", email))),
        "Supply an email address or leave it empty.",
    )
    for name, configured, detail in [
        ("alert_recipient", bool(email), "Backlog alert delivery needs an email and a real test."),
        (
            "budget",
            bool(config.get("billing_account")),
            "Configure a console budget or Terraform billing account; budgets do not cap spending.",
        ),
        (
            "github_wif",
            bool(config.get("github_repository")),
            "GitHub remote, gcp environment and WIF are separate from local validation.",
        ),
        (
            "cloud_spark",
            bool(config.get("spark_runner_url")),
            "Cloud Spark needs an external authorized runner and a pinned GCS connector.",
        ),
    ]:
        checks.append(Check(name, "unverified" if configured else "warning", detail))
    checks.append(
        Check(
            "postgres_tls",
            "unverified",
            "Secret payload, PostgreSQL connectivity and TLS need deployment smoke tests.",
        )
    )
    return checks


def adc_path() -> Path:
    explicit = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if explicit:
        return Path(explicit)
    config = os.environ.get("CLOUDSDK_CONFIG")
    if config:
        return Path(config) / "application_default_credentials.json"
    root = Path(os.environ.get("APPDATA", str(Path.home() / ".config")))
    return root / "gcloud" / "application_default_credentials.json"


def inspect_online(project: str, credentials_file: Path) -> list[Check]:
    from google.auth import load_credentials_from_file
    from google.auth.transport.requests import AuthorizedSession

    try:
        credentials, _ = load_credentials_from_file(
            str(credentials_file),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
            quota_project_id=project,
        )
        with AuthorizedSession(credentials) as client:
            return inspect_remote(client, project)
    except Exception as error:
        # Never echo HTTP bodies, credential contents, access tokens or exception messages.
        return [
            Check(
                "cloud_access",
                "blocked",
                f"Authentication/transport failed ({type(error).__name__}).",
            )
        ]


def inspect_remote(client: Any, project: str) -> list[Check]:
    checks: list[Check] = []
    project_number = ""
    endpoints = [
        (
            "project_access",
            f"https://cloudresourcemanager.googleapis.com/v1/projects/{project}",
            "lifecycleState",
            "ACTIVE",
        ),
        (
            "billing_enabled",
            f"https://cloudbilling.googleapis.com/v1/projects/{project}/billingInfo",
            "billingEnabled",
            True,
        ),
    ]
    for name, url, field, expected in endpoints:
        response = client.get(url, timeout=20)
        body = response.json() if response.status_code == 200 else {}
        okay = response.status_code == 200 and body.get(field) == expected
        if name == "project_access" and okay:
            project_number = str(body.get("projectNumber", ""))
        checks.append(
            Check(
                name,
                "pass" if okay else "blocked",
                f"Read-only {name} check: HTTP {response.status_code}.",
            )
        )
    if not project_number.isdecimal():
        return checks + [Check("enabled_apis", "blocked", "Cannot resolve the GCP project number.")]
    enabled: set[str] = set()
    page_token = ""
    for _ in range(20):
        response = client.get(
            f"https://serviceusage.googleapis.com/v1/projects/{project_number}/services",
            params={"filter": "state:ENABLED", "pageSize": 200, "pageToken": page_token},
            timeout=20,
        )
        if response.status_code != 200:
            checks.append(
                Check(
                    "enabled_apis", "blocked", f"Unable to list APIs: HTTP {response.status_code}."
                )
            )
            return checks
        body = response.json()
        enabled.update(service["config"]["name"] for service in body.get("services", []))
        page_token = body.get("nextPageToken", "")
        if not page_token:
            break
    else:
        return checks + [Check("enabled_apis", "blocked", "API pagination exceeded the limit.")]
    missing = sorted(REQUIRED_APIS - enabled)
    checks.append(
        Check(
            "enabled_apis",
            "blocked" if missing else "pass",
            "Missing: " + ", ".join(missing) if missing else "Required APIs are enabled.",
        )
    )
    return checks


def report(config_file: Path, online: bool = False) -> dict[str, Any]:
    checks: list[Check] = []
    config: dict[str, Any] = {}
    try:
        loaded = json.loads(config_file.read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, dict):
            raise ValueError("Expected an object")
        config = loaded
        checks.extend(inspect_config(config))
    except (OSError, ValueError):
        checks.append(
            Check(
                "configuration",
                "blocked",
                "Create a valid cloud.auto.tfvars.json from the example; fill real values.",
            )
        )
    credentials = adc_path()
    checks.append(
        Check(
            "adc_file",
            "unverified" if credentials.is_file() else "blocked",
            "ADC file exists; not authenticated yet."
            if credentials.is_file()
            else "Run gcloud auth application-default login with config on D.",
        )
    )
    remote_checks: list[Check] = []
    if online and not any(check.status == "blocked" for check in checks):
        remote_checks = inspect_online(config["project_id"], credentials)
        checks.extend(remote_checks)
    online_passed = bool(remote_checks) and all(check.status == "pass" for check in remote_checks)
    return {
        "mode": "online_read_only" if online else "offline",
        "blocked": any(check.status == "blocked" for check in checks),
        "cloud_connection_verified": online_passed,
        "deployment_verified": False,
        "checks": [asdict(check) for check in checks],
        "limits": "Does not test secret payloads, PostgreSQL, image availability, runtime IAM, "
        "BigQuery/GCS writes, Pub/Sub delivery, alerts or Spark. Does not deploy resources.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("infra/terraform/cloud.auto.tfvars.json")
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="Read project, billing and enabled APIs with existing ADC.",
    )
    args = parser.parse_args()
    result = report(args.config, args.online)
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result["blocked"] else 0)


if __name__ == "__main__":
    main()
