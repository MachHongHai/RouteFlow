# Failure probes and recovery

The controlled chaos CLI asserts actual database outcomes. Run locally after generating and
ingesting a workload, and after an initial dbt build for order-state/reconciliation scenarios.
Use a disposable local project for repeated destructive analytical probes.

```bash
docker compose exec -T api python -m routeflow.chaos --scenario duplicate-events
docker compose exec -T api python -m routeflow.chaos --scenario consumer-failure
docker compose exec -T api python -m routeflow.chaos --scenario invalid-schema
docker compose exec -T api python -m routeflow.chaos --scenario missing-required-fields
docker compose exec -T api python -m routeflow.chaos --scenario out-of-order-events
docker compose exec -T api python -m routeflow.chaos --scenario late-events
docker compose exec -T api python -m routeflow.chaos --scenario outbox-retry
docker compose exec -T api python -m routeflow.chaos --scenario reconciliation-mismatch
```

| Failure | Persisted behavior / repair |
|---|---|
| Business transaction rolls back | No order or outbox event commits; integration test injects failure |
| Relay crashes after publish | Lease eventually expires; next relay republishes; logical event counted once |
| Broker unavailable | Pending outbox retained with backoff/error; retry/reset after recovery |
| Consumer crashes after RAW write | Transport redelivers; local PK/upstream identity and dbt protect totals |
| Persistent warehouse failure | Durable retry budget ends in DLQ; replay after repairing dependency |
| Poison / unsupported version | Original bytes preserved in archive and DLQ; no business RAW accepted |
| Event ID reused for changed payload | Identity guard rejects collision before warehouse append |
| Delivered arrives before in-transit | Highest aggregate version controls state, not receipt order |
| Historical event arrives late | New ingestion selects order for reconstruction; explicit old-date backfill handles retention |
| GPS point near midnight arrives late | Spark rebuilds complete predecessor sequence and affected suffix |
| Invalid or impossible GPS | Rejected records or flagged silver segments; excluded estimated movement |
| Reconciliation mismatch | Failure rows identify missing/unexpected/mismatched IDs; command fails |
| Driver dies while publishing Parquet | Incomplete immutable run is not appended; rerun replaces warehouse dates |

For a deterministic `outbox-retry` probe, stop the background relay with `docker compose stop relay`,
run the probe, then `docker compose start relay`. The probe marks one selected event unpublished;
an active background worker could otherwise recover it before the assertion observes the failure.
`reconciliation-mismatch` changes analytical amounts, verifies
the mismatch, then rebuilds dbt in a `finally` block. Its purpose is failure detection, not a
production repair workflow. The deterministic pytest suite additionally checks concurrent relay
claims, retry exhaustion, DLQ recovery, repeated archive replay and repeated backfills.

After a poison probe, `dlq-replay` should leave the invalid original unresolved. Successful exit
means the replay job executed, not that an invalid schema was repaired. Inspect rejected counts
and DLQ rows. Corrected messages must use a new ID so the original audit trail remains immutable.
