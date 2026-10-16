# Operations runbook

Start with `python -m routeflow.cli metrics` inside the API container. It reports actual outbox
backlog/exhaustion, open DLQ count, failed pipeline runs, RAW freshness, observed lag and local
duplicate-attempt rate. Source pipeline-run and reconciliation tables retain detailed failures.
The local API exposes the same metrics at `/metrics`. Health probes are `/health/live` and
`/health/ready`; readiness checks the source DB, not every downstream dependency.

```bash
docker compose ps
docker compose logs --tail 100 relay consumer
docker compose exec -T api python -m routeflow.cli metrics
docker compose exec -T source psql -U routeflow -d routeflow -c "select pipeline_name,status,records_read,records_written,records_rejected,error_message from pipeline_runs order by created_at desc limit 10"
docker compose exec -T source psql -U routeflow -d routeflow -c "select metric_name,source_value,warehouse_value,difference,status,details from reconciliation_results order by created_at desc limit 10"
```

The relay claims rows with `FOR UPDATE SKIP LOCKED` and a lease. Network publishing happens after
the claiming transaction commits; each publish waits for broker confirmation. The lease is sized
for the selected batch's worst-case confirmation time. A dead relay may delay reclaim until that
lease expires; use smaller `--limit` for faster crash recovery. Exponential retry delay caps at
300 seconds and ten failed claims require explicit `outbox-reset`. Exhausted rows are retained,
not dropped. A successful publish before a marking crash may be duplicated safely.

```bash
docker compose exec -T api python -m routeflow.cli outbox-reset
docker compose exec -T api python -m routeflow.cli relay --limit 10
docker compose exec -T api python -m routeflow.cli dlq-replay --limit 100
```

Transient consumer failures use durable per-input counters. Five failures quarantine the exact
bytes, category, error, schema version, correlation ID and attempts. Invalid contracts quarantine
immediately. Replay resets the explicit retry budget and increments operator replay count. A
still-invalid original remains unresolved. If both archive and control DB fail, the message is
not acknowledged; cloud Pub/Sub eventually forwards it to its native DLQ subscription. Inspect
that subscription after source recovery and re-publish original message bytes with an authorized
operator identity. Native DLQ forwarding is not emulated by local application quarantine.

Reconciliation reads stable operational orders up to `now - grace_seconds` and compares curated
order/payment counts, gross cents, delivered/cancelled history, IDs and current status. Recently
changing orders are excluded. Run after the ingestion barrier and dbt build on a quiescent workload:

```bash
docker compose exec -T api python -m routeflow.cli wait-ingestion
docker compose exec -T api python -m routeflow.cli dbt
docker compose exec -T api python -m routeflow.cli reconcile --grace-seconds 0
```

This is a cutoff-based current-state comparison, not a distributed snapshot across concurrently
changing databases. Pipeline operators should stop generation or use the bounded orchestration
when they need a strict comparison. Mismatches persist before the command exits nonzero.

Structured application JSON logs contain timestamp, level, service, environment, message and
event/correlation/run/trace fields where applicable. No fabricated live dashboard is included.
Spark's JVM logs remain native Spark logs; its final JSON result includes actual counts/timing.
Cloud Monitoring includes a ten-minute unacked-age alert. Configure notification channels in
your GCP account; defaults do not send mail. The source retry/run tables provide the remaining
operational visibility without introducing paid custom metrics.

The daily cloud workflow is compatible with an optional external Spark runner but never creates
a paid cluster. Locally `scripts/local_pipeline.py --spark` orchestrates stream, barrier, Spark,
Parquet load, dbt quality and reconciliation. See [cost/shutdown](CLOUD_COSTS.md).
