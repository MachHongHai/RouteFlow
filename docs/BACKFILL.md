# Replay, retry and backfill

Retry is a transport/processing attempt for the same bytes. Archive replay re-ingests preserved
originals. Order backfill replays a validated business-date range and rebuilds affected facts.
dbt full refresh reconstructs all retained models. None of these creates new business orders.

```bash
docker compose exec -T api python -m routeflow.cli replay
docker compose exec -T api python -m routeflow.cli backfill --from 2026-10-15 --to 2026-10-15
docker compose exec -T api python -m routeflow.cli dbt --full-refresh
```

Ranges are inclusive UTC dates, cannot be reversed or in the future, and are limited to 367 days
per invocation. Backfill filters archive envelopes by event time and supplies `backfill_from/to`
to dbt. dbt additionally selects order IDs whose creation date is in the requested range, plus
newly ingested IDs through the normal ingestion watermark. Event history for those IDs is read
in full. A transition outside its order's creation date remains discoverable through the new
ingestion watermark. Local RAW rejects duplicates by primary key; cloud staging deduplicates
append deliveries. Repeated backfills leave the same fact grain and amounts.

Archive layout is `events/year=YYYY/month=MM/day=DD/hour=HH/<sha256>.jsonl`, partitioned by receipt
time. Each immutable JSONL object wraps exact bytes as `original_b64` and `archived_at`; invalid
UTF-8 is preserved. Local writes fsync a temporary file before atomic replacement. GCS writes use
`if_generation_match=0`. Archive replay reads those bytes without writing another archive
generation. Operators can inspect originals even when contract validation fails.

Order incremental processing uses a three-day **ingestion-time** overlap measured from the last
materialized ingestion. It is not a watermark that discards old event timestamps. Late events
newly received after a long gap are still selected. Retention is a separate limitation: BigQuery
RAW defaults to 30 days by event time and GCS archive to 90 days by object age. Restore/extend
RAW retention before old-date replay; otherwise BigQuery may immediately expire old partitions.
For histories already deleted from the archive, recover a backup or reconcile source records;
the application cannot reconstruct lost event history from nothing.

Spark backfill has different effects because a GPS point can change its next neighbor's segment:

```bash
uv run python -m routeflow.cli spark-backfill --from 2026-10-01 --to 2026-10-07
docker compose exec -T api python -m routeflow.cli dbt
```

The host command submits to the Compose standalone cluster. Spark scans historical predecessor
context and replaces summary dates from the requested start through the latest affected suffix.
It intentionally may rebuild dates after `--to`, including a next-day endpoint. The default job
reprocesses three days; explicitly start earlier for GPS arriving outside that window. It does
not append another set of daily aggregates. Immutable Parquet run generations are retained, and
one warehouse transaction replaces all affected summary rows. `latest_run.json` describes the
last accepted range only. Keep older Parquet generations until the warehouse and replay inputs
are backed up; local automatic garbage collection is intentionally not implemented.

Every replay/backfill/dbt run stores its status, timestamps, counts and error in `pipeline_runs`.
A failed backfill can be rerun safely. A warehouse failure rolls back summary replacement; a crash
after commit but before manifest publication can be repaired by rerunning the same range.
