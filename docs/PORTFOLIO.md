# Portfolio notes

Repository: [MachHongHai/RouteFlow](https://github.com/MachHongHai/RouteFlow).

## Suggested CV bullets

- Built a logistics analytics pipeline using PostgreSQL transactional outbox, Pub/Sub,
  idempotent ingestion, contract validation, dead-letter handling, and source-to-mart reconciliation.
- Implemented distributed PySpark GPS processing with native window/Haversine expressions,
  anomaly checks, partitioned Parquet, and repeatable warehouse backfills.
- Developed 22 dbt models and 33 data tests, including incremental order facts and an event-derived
  SCD2 driver dimension; tested duplicate delivery, crash recovery, and late/out-of-order events.

Describe the verified deployment as local Docker Compose with Pub/Sub Emulator. Terraform,
BigQuery/GCS adapters, private Cloud Run configuration, and WIF deployment are implemented,
but a real GCP deployment has not been verified. See [validation](VALIDATION.md) and
[current gaps](PROJECT_GAPS_VI.md) for the exact scope.

## Five-minute walkthrough

1. Use the README architecture diagram to explain the streaming path and separate GPS batch branch.
2. Generate a small batch in the console and show actual Outbox/RAW/Mart progress.
3. Open a table from the diagram; use the SQL Editor to inspect business events and the final fact.
4. Explain one failure window: relay publish-before-mark or consumer write-before-ack.
5. Show the model grain, one relevant test, and a concrete replay/backfill design decision.

The [interview guide](INTERVIEW_GUIDE.md) links the technical reasoning to the implemented behavior.
Avoid throughput, coverage, cloud-cost, or production-availability claims that have not been measured.
