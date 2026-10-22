# Validation evidence

Results below describe recorded runs. They are not live metrics, production benchmarks,
or evidence of a deployed GCP environment. Reproduction commands are in [Testing](TESTING.md).

## CI baseline

[GitHub Actions run 39768285303](https://github.com/MachHongHai/RouteFlow/actions/runs/39768285303)
passed for commit [`062dffc`](https://github.com/MachHongHai/RouteFlow/commit/062dffceb1973de2d540ede11545e6b2419f28ca)
on 2026-10-22. Its three jobs cover:

| Job | Checks |
|---|---|
| Application | Frontend formatting/syntax, Ruff, mypy, unit/contract tests, PostgreSQL/Pub/Sub integration and E2E, dbt build/compile, portable console HTTP/schema smoke |
| Spark | Numerical and Parquet-loading tests, standalone master/worker pipeline, warehouse loading, dbt and reconciliation |
| Terraform | Formatting, provider initialization without a backend, and schema validation |

The [workflow](../.github/workflows/ci.yml) defines the exact commands.
For later commits, use their own Actions results rather than assuming this baseline applies.

## Local checks

The 2026-10-22 source baseline passed **96 tests**, with **18 infrastructure-dependent tests
skipped** by the default suite. Ruff lint/format, mypy over 33 modules targeting Linux and
Windows, frontend formatting/syntax, base and Windows Compose configurations, PowerShell
parsing, package contents, and relative documentation links also passed.

Infrastructure suites run separately. The original 2026-10-16 local pipeline validation
recorded **25 application/contract/integration/E2E tests** and **10 Spark tests** passing.
These historical totals reflect that source version and are not added to the current unit count.

## Pipeline behavior

Recorded local streaming and distributed Spark runs verified:

- Confirmed outbox publishing, concurrent relay claims, duplicate delivery, consumer crash
  recovery, invalid-schema quarantine, archive replay, and date backfill.
- Event reordering, SCD2 driver history, repeated replay/backfill without duplicate facts,
  and detection of deliberately inconsistent source/mart totals.
- Spark coordinate/timestamp/schema validation, Haversine calculations, previous-point windows,
  anomaly flags, partitioned Parquet, and repeatable transactional summary loading.
- dbt build with **22 models and 33 tests**, plus six source-to-mart reconciliation checks.

One reconciled demonstration snapshot contained **34 source orders = 34 fact orders**,
**562 logical RAW events**, and **264 GPS points** summarized into **9 driver/date rows**.
This is synthetic sample data; counts change as new batches are generated.

## Console behavior

Unit tests and local HTTP/browser checks cover service allowlists, dependency startup,
Host/CSRF checks, job concurrency/timeouts, generation bounds, batch tracing, and idempotent
generation requests. A real two-order batch produced 22 events, all published and ingested;
both orders reached the mart. Repeating its request ID did not create another batch.

Database checks verified schema browsing, SELECT/CTE aggregation, empty results, duplicate column
names, result limits, and SQL timeout cancellation. Writes, writable CTEs, multiple statements,
owner-role escalation, and restricted catalog access were rejected. The reader uses a separate
PostgreSQL role and read-only transactions.

The pipeline diagram and database workspace were checked at 1440px and 390px viewport widths.
The console was also tested without Windows host mounts under the portable Docker-volume policy;
missing metadata under the optional workstation policy blocked controls.

## Restore verification

A 2026-10-16 logical restore drill used disposable, network-isolated PostgreSQL containers.
All row fingerprints matched across **18 source and 17 warehouse base tables**. Archive and
lake extraction recovered **563 and 89 files**, respectively. This verifies that backup snapshot,
not ongoing backup freshness, off-machine resilience, or production RPO/RTO.

See the [recovery runbook](DOCKER_RECOVERY_VI.md) for backup and verification commands.

## Unverified boundaries

GCP plan/apply, runtime IAM, private Pub/Sub push, GCS/BigQuery writes, cloud Spark execution,
and alert delivery have not been verified against a real project. Online preflight behavior
has unit tests with mocked HTTP responses; offline Terraform validation is not a cloud smoke test.

No production throughput, coverage percentage, cloud cost savings, or Spark speedup is claimed.
See [project gaps](PROJECT_GAPS_VI.md) and [cloud deployment](CLOUD_DEPLOYMENT.md).
