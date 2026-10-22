# Executed validation — 2026-10-16

## Docker-managed console — 2026-10-22

- Console is now an existing member of the RouteFlow Docker Desktop group, published only
  at `127.0.0.1:58090 → 8080`. The Windows foreground server was stopped. Compose startup
  brought up the console and all eight managed services; init completed with exit code 0.
- Set application and console restart policies to `no`; also updated the three existing
  application containers that previously used `unless-stopped`. Container inspect confirms
  the new policy. Merely opening Docker no longer requests these workloads to restart.
- Added opt-in local dependency waiting for database/schema/subscription readiness. Cloud
  images skip the local wait when the Compose-only mode flag is absent; unit-tested.
- `pytest tests/unit tests/contract -q`: **55 passed**. Ruff passed repository-wide, mypy
  passed 29 source files, JavaScript syntax and PowerShell launcher parsing passed.
- Broker tests cover project/service label checks, target/action/path allowlists, dependency
  ordering and initialization, Docker log framing, null port lists, current E storage guard,
  and startup retry. Web UID 10001 is denied direct access to the Docker socket; the private
  broker owns socket access and publishes no host port. Live overview/table/log reads and
  a real Relay restart through the browser succeeded.
- After startup/control: 34 source orders = 34 fact orders, 562 RAW events, 264 GPS points,
  nine daily GPS rows, pending outbox 0. Existing deliberate DLQ record retained. C had
  about 29.18 GiB free and showed no GiB-scale growth against the pre-build measurement.
- A further stop/start rehearsal of the entire group was rejected by automatic approval
  review (`blocked by policy`); it was not retried through another mechanism. Actual Docker
  Desktop cold group-start was therefore not directly rehearsed. Compose startup and the
  narrower live Relay restart above were verified; no volume deletion/prune was attempted.

## Local operations console — 2026-10-19

- `scripts/dev.ps1 uv run --frozen pytest tests/unit tests/contract -q`: **43 passed**,
  including 14 console cases for localhost/Host/CSRF restrictions, service allowlists,
  bounded commands, job completion/concurrency/timeouts and read-only table pagination.
  Existing upstream Starlette TestClient deprecation warning remains.
- Ruff passed repository-wide; mypy passed all 27 source files; `node --check` passed
  console JavaScript; PowerShell parser accepted `scripts/start-console.ps1`.
- Browser checks: start all eight services; stop/start Relay; restart Relay using the
  keyboard; Escape cancels confirmation; controls disabled while a job runs; service
  search; data page 2; actual API logs; storage/restore-proof display. Narrow 390px
  layout visually checked. Table reads for all seven allowed datasets returned HTTP 200.
- After controls: all eight services running, Spark master/worker ALIVE (two cores),
  source orders = fact orders = 34, RAW events = 562, GPS = 264 points / nine daily rows,
  pending outbox = 0. Deliberate poison DLQ record and historic pipeline failures retained.
- No container image rebuilt/pulled for this console, no new frontend packages, no GCP
  calls/deployment. Console runs on loopback port 58090 with cache/temp on D and guarded
  Docker mutations on E. Business integration/Spark suites below are historical results;
  they were not rerun for this UI change.

## Original pipeline validation

Environment: Windows/PowerShell, Docker Engine 29.8.0, Python 3.12 via uv 0.11.19.
Terraform was not installed on the host; checks used `hashicorp/terraform:1.13.4` in Docker.
No GCP account, cloud credential, billable resource or GitHub-hosted workflow was used.

The table below records the original data-pipeline validation. The later cloud-readiness
follow-up is recorded separately at the end; its additional tests increase the unit test count.

| Executed command / check | Observed result |
|---|---|
| `uv sync --frozen` | Dependencies resolved/pinned in `uv.lock`; runtime builds succeeded |
| `uv run ruff check .` | Passed |
| `uv run mypy routeflow` | Passed, 25 source files |
| `uv run pytest` | 17 passed / 18 optional infrastructure tests skipped |
| `RUN_INTEGRATION=1 uv run pytest tests/unit tests/contract tests/integration tests/e2e -q` | 25 passed, 50.55 s |
| Spark container `python -m pytest tests/spark -q` with integration enabled | 10 passed, 40.52 s |
| `docker compose config --quiet` | Passed |
| `docker compose up -d --build` | Source, warehouse, emulator, API, relay and consumer started; init exited successfully |
| `alembic upgrade head` | Applied revisions 001 and 002; test suite also rebuilt from frozen migrations |
| `docker compose --profile spark up -d --build spark-master spark-worker` | Master healthy; remote worker registered |
| `uv run python scripts/local_pipeline.py --orders 4 --spark` | Full streaming + standalone Spark + warehouse + dbt + reconciliation succeeded |
| dbt build / full refresh | 55 successful model/test nodes: 22 models and 33 tests |
| `dbt test --project-dir dbt --profiles-dir dbt` | 33 passed |
| `dbt compile --project-dir dbt --profiles-dir dbt` | Passed against local Postgres |
| Reconciliation with zero grace after completed ingestion | All six checks passed |
| Docker Terraform `init -backend=false` / `fmt -check -recursive` / `validate` | Passed; Google provider 7.46.1 locked |
| Chaos duplicate / consumer crash / invalid schema probes | All verified real persisted outcomes |
| Host `spark-backfill` command repeated on unchanged input | Nine rows / 264 points / unchanged per-driver distance totals asserted |
| Docker disk migration C to E | Offline VHD SHA256 matches; image/volume inventories match; warehouse counts retained; core and Spark services restarted |
| Windows storage wrapper | Cache/Python paths on D, Docker/WSL paths on E, Compose config and Ruff passed; see `DISK_STORAGE.md` |

The default suite intentionally skips infrastructure tests. All 35 tests were separately executed
in their required local environments: 25 application/contract/integration/E2E and 10 Spark tests.
One upstream Starlette warning about its future TestClient HTTP client choice remains in the
application suite; it did not cause a test failure. No test coverage percentage was measured.

The E2E suite published real outbox records through a unique Pub/Sub Emulator topic/subscription,
consumed them in reversed batches, built dbt marts and asserted counts/SCD2. It repeated archive
replay and date backfill, checked that facts did not duplicate, injected wrong amounts and asserted
reconciliation failure before repairing the mart. Integration tests also exercised concurrent relay
claims and the publish-before-mark and write-before-ack crash windows.

Observed main demonstration snapshot after the full local pipeline:

- Source orders = fact orders = payments = 34.
- Latest status: 32 delivered, one cancelled and one refunded cancelled order.
- RAW logical events = 562; delivery attempts = 566 after deliberate duplicate/crash probes.
- Spark silver input/valid points = 264; rejected points in this clean workload = 0.
- GPS daily mart = nine driver/date rows, 264 points, approximately 60.6390 estimated km.
- Standalone Spark run `eebb4489-dc7c-41ae-8051-bafd46f9d44e` loaded 66 gold summary rows in
  20.559 seconds, writing `/lake/runs/753d93f9-b819-49c3-9d97-346dc575b5ba`.

These are smoke measurements on this machine, not throughput benchmarks or speedup claims.
The unchanged-input Spark rerun completed in 16.764 seconds; no cold/warm speedup is inferred.
Numerical tests separately cover invalid, anomalous, late and conflicting GPS data. Main DLQ has
one intentionally unsupported-schema original from the chaos probe; replay correctly does not
repair that poison. Historical failed-run metadata from an early timestamp bug is retained as
audit history; the bug was fixed and later reconciliation passed.

Implemented but not cloud-executed: BigQuery append/Parquet load adapters, GCS archive/Parquet path,
private Cloud Run push, native Pub/Sub DLQ forwarding/IAM, Workflows/Scheduler, WIF deployment,
Monitoring/budget resources and query-pruning benchmark execution. Terraform schema validation
is not a substitute for those cloud smoke tests. A distributed cloud Spark runner and its GCS
connector must be supplied by an authorized operator; none is provisioned automatically.

## Cloud-readiness follow-up, 2026-10-16

| Executed check | Observed result |
|---|---|
| `scripts/gcloud.ps1 --version` | Existing pinned image runs Google Cloud SDK 589.0.0 without a host SDK install |
| `gcloud auth list` using the D-mounted config | No authenticated account; no login was attempted |
| Python Google Auth ADC path lookup via `scripts/dev.ps1` | `D:\DevCache\gcloud\application_default_credentials.json` |
| `uv run python -m routeflow.cloud_preflight` | Exit 1, blocked for missing real config and ADC; cloud/deployment flags false; no GCP request |
| `uv run pytest tests/unit tests/contract -q` | 29 passed, including 12 cloud preflight cases; online HTTP behavior mocked |
| `uv run ruff check .` / `uv run mypy routeflow` | Passed; 26 source files checked by mypy |
| Terraform Docker `fmt -check -recursive` / `validate` | Passed after job dependency and email-channel changes |
| Deploy configuration gate under Bash | Syntax passed; missing variables rejected, valid variables accepted, invalid environment rejected |
| PowerShell parser checks / Compose config / API readiness | Passed; existing local API returned ready |

The follow-up did not rerun the existing Spark numerical/Parquet suite or full streaming E2E
suite because their implementation did not change. Earlier results remain historical evidence,
not a claim that a new full suite was run. Terraform plan/apply, GCP project/API reads with ADC,
runtime IAM, cloud writes, alert delivery and GitHub Actions execution remain unverified.
See [project gaps](PROJECT_GAPS_VI.md) and [first GCP setup](GCP_GETTING_STARTED_VI.md).

## Docker update recovery, 2026-10-16

Docker Desktop 4.95.0 / Engine 29.8.2 initially exposed an empty default-C store. The existing
33.687-GiB E disk was preserved and copied with a full SHA256 match before switching storage.
The correct WSL setting, `CustomWslDistroDir`, now pins the direct E path. The old Desktop-root
junction was retired; host sockets/logs use a normal Windows directory. See
[incident and recovery](DOCKER_RECOVERY_VI.md).

- All 17 previous containers, 9 volumes and image/tag inventory reappeared; ecommerce stays stopped.
- Source orders = facts = 34, RAW = 562, GPS daily rows = 9, points = 264, km = 60.639007624322296.
- `scripts/backup_local.py backup` created two custom-format PG dumps and archive/lake tar files on D.
- `verify` restored into disposable network-isolated PostgreSQL: 18 source and 17 warehouse base
  tables matched all row fingerprints. Safe extraction recovered 563 archive and 89 lake files.
- A full Desktop stop/start via the helper was executed; inventory and business counts persisted.
- API readiness returned ready, Spark worker ALIVE; all six source/mart reconciliation checks passed.
- Ruff and mypy checks cover the added backup tool; this incident did not rerun the Spark job suite.

The logical restore drill applies to RouteFlow, not the ecommerce applications. The full disk
snapshot and their existing volumes were retained. No factory reset, volume prune or business
data regeneration was used to make the old counts reappear.

## Console generation and flow tracking, 2026-10-22

- Unit/contract suite: **78 passed**. New cases cover strict bounds, CSRF, service/storage
  readiness, request idempotency, persisted interruption, exact trace queries, context
  isolation, partial generation, DLQ, ingestion timeout, mart completion and fixed dbt exec.
- Ruff, mypy (31 modules), both JavaScript syntax checks and Compose configuration passed.
- Rebuilt only `routeflow-console:local`, retaining the existing application/Spark images
  and data volumes. Console runs within its 256-MiB limit; observed usage about 90 MiB.
- Real API smoke submitted **2 orders**, seed 42, UTC business date 2026-10-21, with dbt
  enabled. The batch produced **22 events / 4 GPS points**. All 22 were published and
  ingested; both orders appeared in `analytics.fact_order`; trace-specific DLQ stayed 0.
  Resubmitting the same request ID returned the original run without adding orders.
- Resulting totals: **36 source orders = 36 facts; 584 RAW events; 268 RAW GPS points**.
  Spark was not rerun: its existing 264-point summary is correctly shown separately.
- Generation metadata uses the new `routeflow_console-state` volume on the existing E
  Docker disk. During implementation/build/smoke, C free space rose from 31,658,684,416
  to 31,663,927,296 bytes (about 5 MiB); no bulk C growth was observed.
- Functional verification used the local APIs. Browser visual verification was unavailable
  because the browser tool had rejected access to its existing non-HTTP tab; no alternate
  browser-control workaround was used. No screenshot or visual-QA pass is claimed.
