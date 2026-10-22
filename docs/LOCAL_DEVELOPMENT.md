# Local development

For a fresh checkout on Linux, macOS, or Windows with Linux containers:

```bash
docker compose --profile console up -d --build
```

Open the [console](http://127.0.0.1:58090) to generate sample data, trace ingestion, and query
the databases. Console builds its application base through a declared Compose build dependency;
no pre-existing `routeflow-app:local` image or Windows host mounts are required.
See [the console guide](LOCAL_CONSOLE_VI.md) for controls and access restrictions.

For the optional D/E Windows storage policy, use `scripts/start-console.ps1 -Build` and
`scripts/dev.ps1` instead. The wrapper selects `docker-compose.windows.yml`, checks Docker/WSL
placement on E, and sets host caches/temp on D. After creating containers, Docker Desktop's
Start button on the `routeflow` group starts the console too.

Prerequisites: Docker Engine with Compose 2.17+, at least approximately 8 GiB Docker memory for the
optional Spark branch, and Python 3.12+ / uv for host tests. No cloud credentials are required.
All published service ports bind only to loopback. Default database passwords are local demo values.

```bash
uv sync --frozen
docker compose up -d --build
docker compose exec -T api python -m routeflow.cli seed
docker compose exec -T api python -m routeflow.generator --orders 20 --seed 42
docker compose exec -T api python -m routeflow.cli wait-ingestion
docker compose exec -T api python -m routeflow.cli dbt
docker compose exec -T api python -m routeflow.cli reconcile --grace-seconds 0
docker compose exec -T api python -m routeflow.cli metrics
```

The init container applies Alembic migrations, creates warehouse RAW/GPS tables and provisions
emulator topics/subscriptions. It exits after success. The API, relay and consumer then start.
Inspect [interactive API documentation](http://127.0.0.1:58000/docs) and
[readiness](http://127.0.0.1:58000/health/ready). SQL ports are 55432 (source) and 55433 (warehouse);
the emulator is 58085. `.env.example` describes host execution; copy it to `.env` if needed.
Compose supplies its own internal DNS names. Do not replace container hostnames with loopback.

```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T warehouse psql -U routeflow -d warehouse -c "select status,count(*) from analytics.fact_order group by status"
docker compose exec -T source psql -U routeflow -d routeflow -c "select status,count(*) from pipeline_runs group by status"
```

Enable distributed Spark explicitly:

```bash
docker compose --profile spark up -d --build spark-master spark-worker
uv run python scripts/local_pipeline.py --orders 20 --spark
```

Spark's Master UI is [localhost:58080](http://127.0.0.1:58080). `spark-job` is an ephemeral client-mode
driver, and `--use-aliases` makes its advertised hostname resolvable by workers. Both executors and
driver run Python 3.12, Spark 4.0.2 and Java 17. The worker has two cores and a bounded memory pool.

```bash
docker compose exec -T api python -m routeflow.gps_workload --points 1000 --seed 42
docker compose exec -T api python -m routeflow.cli wait-ingestion
uv run python -m routeflow.cli spark-backfill --from 2026-10-15 --to 2026-10-15 --explain
docker compose exec -T api python -m routeflow.cli dbt
```

Replace the sample dates with the generated UTC business date, which defaults to yesterday.
The `gps_workload` command creates actual domain GPS samples and outbox records; it does not bypass
the streaming consumer. Use low volumes in cloud mode: the BigQuery demonstration adapter loads
one message per load job and is not intended for a high-frequency cloud GPS stream.

Stop without deleting data:

```bash
docker compose --profile spark down
```

Volumes persist source, warehouse, archive, Parquet runs and dbt artifacts. The Makefile wraps these
commands on systems with make; all commands above also work directly from PowerShell.
