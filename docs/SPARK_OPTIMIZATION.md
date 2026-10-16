# Spark optimization and reproducible measurement

The job uses explicit JSON schemas and projects only GPS columns. Native trigonometric expressions
avoid Python UDF serialization. The small driver lookup is broadcast, while per-driver windows and
date/driver/hour aggregates incur intentional shuffles. Adaptive Query Execution is enabled and
the demonstration uses four SQL shuffle partitions. This is configuration, not a measured speedup.

Sequence calculations must see predecessor history. The RAW wrappers are partitioned by receipt
time, so pruning them by event date could silently omit late points. The current correctness-first
reader recursively scans them; it does **not** claim RAW predicate pushdown. The final suffix filter
is applied after windows. Silver Parquet is partitioned by event date; ad-hoc Parquet consumers can
prune date partitions. Inspect an actual `explain('formatted')` plan for `PartitionFilters` when
reading that Parquet with a date filter. JSON `from_json` itself does not provide Parquet-style
column pruning of encoded payloads.

Silver output uses `repartition(2,'business_date')`, deliberately shuffling to bound small-file
counts. Tiny gold summaries use `coalesce(1)`, which reduces partitions without a full repartition
shuffle. This choice is inappropriate for large outputs: increase partition counts / target file
sizes before scaling up. `maxRecordsPerFile` bounds records per output file. Points and cleaned
sequences are cached because multiple gold outputs reuse them, and are unpersisted after loading.

A prolific driver can skew the window partition. Random salting is unsafe because it breaks
predecessor continuity. At larger scale, split driver histories by date with boundary carry-in,
track next affected partitions, compact RAW receipt files, and maintain a durable ingestion
watermark plus late-data index. None of those optimizations is falsely claimed as implemented.

Reproducible local workload:

```bash
docker compose exec -T api python -m routeflow.gps_workload --points 10000 --seed 42
docker compose exec -T api python -m routeflow.cli wait-ingestion
uv run python -m routeflow.cli spark-backfill --from 2026-10-15 --to 2026-10-15 --explain
```

Use the actual generated UTC date. The generator persists real GPS/outbox records, so generation
and streaming ingestion are measured separately from Spark. The job prints actual elapsed seconds,
input/rejected/clean counts, output path and warehouse rows. Save the output, Spark UI stage metrics,
image digest, CPU/memory limits, data volume, cache state and execution plan for comparisons. Run
multiple iterations on unchanged input and compare identical resulting summary totals. Avoid
claiming cold/warm or differently sized smoke runs as an optimization benchmark.

Observed development smoke runs are recorded in `VALIDATION.md`; no production throughput or
relative speedup is claimed. Cloud Spark benchmarks were not executed. BigQuery pruning benchmarks
have a separate dry-run-by-default script, `scripts/bigquery_benchmark.py`.
