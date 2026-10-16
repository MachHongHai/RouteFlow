# Testing and evidence

`uv.lock` pins the resolved dependencies. Default tests are offline-friendly; PostgreSQL/Pub/Sub
tests require explicit `RUN_INTEGRATION=1`, and Spark tests skip when the optional runtime is absent.
The integration fixture creates separate source/warehouse databases suffixed `_test`. It verifies
that suffix before resetting schemas and runs real frozen Alembic migrations. Main demo databases
are never truncated by the test fixture.

```bash
uv sync --frozen
uv run ruff check .
uv run mypy routeflow
uv run pytest
docker compose config --quiet
```

Enable integration tests (PowerShell):

```powershell
$env:RUN_INTEGRATION = '1'
uv run pytest tests/unit tests/contract tests/integration tests/e2e -q
```

On a POSIX shell use `RUN_INTEGRATION=1 uv run pytest ...`. Start Compose dependencies first.
Tests exercise the actual Pub/Sub Emulator, publisher confirms, consumer archive/RAW, dbt build,
SCD2, order/payment totals and reconciliation. Replays and backfills are repeated and their final
counts asserted. A failing reconciliation is injected and detected, then dbt repairs the mart.
Transient/poison scenarios assert durable retry and DLQ metadata, not just process exits.

Spark tests run in the same pinned Python/Java environment as the cluster:

```bash
docker compose --profile spark up -d --build spark-master spark-worker
docker compose --profile spark run --rm --no-deps -e RUN_INTEGRATION=1 --entrypoint python spark-job -m pytest tests/spark -q -o cache_dir=/tmp/pytest-cache
uv run python scripts/local_pipeline.py --orders 8 --spark
```

Numerical assertions cover known equatorial Haversine distance, speed, previous-point ordering,
duplicate and conflicting IDs, malformed archives, invalid schema/timestamps/coordinates, impossible
movement, missing profiles, midnight boundaries, partitioned Parquet and repeated transactional
warehouse loading. The orchestrated smoke uses the actual standalone worker, not merely local mode.

Terraform can be checked without a locally installed executable:

```powershell
docker run --rm -v "${PWD}/infra/terraform:/workspace" -w /workspace hashicorp/terraform:1.13.4 init -backend=false
docker run --rm -v "${PWD}/infra/terraform:/workspace" -w /workspace hashicorp/terraform:1.13.4 fmt -check -recursive
docker run --rm -v "${PWD}/infra/terraform:/workspace" -w /workspace hashicorp/terraform:1.13.4 validate
```

No credentials are required for these checks. Provider-schema validation does not prove cloud IAM,
regional availability, service-agent creation or real API integration. GitHub CI repeats application,
dbt, Docker, Spark and Terraform checks; its hosted execution has not been claimed locally.
See `VALIDATION.md` for observed command results, and `ENGINEERING_REPORT.md` for acceptance limits.
