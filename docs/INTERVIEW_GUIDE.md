# Interview guide grounded in this repository

**Why the outbox?** Creating an order and publishing directly to a broker are separate commits.
If the application crashes between them, a paid order could lack an event. RouteFlow inserts the
business mutation and JSON envelope in the same PostgreSQL transaction. The relay can publish
later without losing the durable intent. The rollback test proves both disappear together.

**Why at-least-once?** A relay can publish successfully then crash before marking its row. A consumer
can commit RAW then crash before acknowledgement. No distributed transaction joins PostgreSQL,
Pub/Sub, GCS and BigQuery, so duplicates are an expected recovery mechanism. Claiming exactly-once
would be wrong. Tests inject both crash windows.

**What happens if the consumer crashes?** Pub/Sub retains or redelivers the message. The next attempt
archives safely, checks immutable event identity and writes RAW again. Local event-ID constraints
prevent another logical row; cloud RAW may append another delivery, while dbt ranks event IDs.
Acknowledgement occurs after persistence, not after merely receiving the message.

**Why separate business versions from event IDs?** IDs deduplicate the same event. Versions order
different lifecycle events for one order. `DELIVERED` arriving before `IN_TRANSIT` must not roll back
the state. `int_order_lifecycle` ranks aggregate versions and reconstructs timestamps from history.

**How does schema evolution work?** V2 adds optional trace context while retaining V1's required
fields and constraints. Both versions validate; unsupported schemas are preserved in DLQ. The
compatibility test is intentionally bounded to additive changes and is not a general theorem prover.

**How do late events affect dbt?** Newly ingested IDs are selected using the last materialized
ingestion plus a three-day overlap. Their entire retained event history is reconsidered. An old
business timestamp is not ignored just because it falls outside a recent event-time window.
Warehouse/archive retention still limits how far back complete history remains available.

**How does Spark handle a late GPS point?** A point changes both its own segment and the next point's
predecessor. Spark computes windows before date filtering and conservatively replaces the suffix
from the requested start. A midnight test asserts numerical changes on the next date. Reprocessing
deletes/replaces all affected gold summary rows in one warehouse transaction.

**Why Spark for GPS and dbt for orders?** GPS requires historical per-driver windows, Haversine
expressions, validation and partitioned Parquet. Spark distributes that sequence/aggregation work.
dbt owns warehouse relationships, dimensions and business tests. Using Spark to recreate the order
status SQL would duplicate responsibility without a technical benefit.

**What is estimated about GPS metrics?** Straight-line Haversine segments approximate movement.
Thresholds exclude impossible speed, large gaps and zero-time jumps. They do not perform road
matching or infer paid working hours. Driver hourly busy minutes are not a measured utilization
rate against a real shift roster. Generator runs are simulations, not real fleet scheduling data.

**Where is SCD2 implemented?** `dim_driver.sql` derives half-open validity intervals from versioned
driver profile events. Its surrogate key includes profile version. A late profile causes interval
reconstruction, and delivery facts join the driver version at assignment time. Daily mobility facts
use an explicitly named current profile key instead of pretending to have historical shift detail.

**Why partition BigQuery?** An event-time date predicate can eliminate unrelated partitions.
Clustering by event type and aggregate ID may help filters within partitions. The benchmark script
compares a JSON-derived date with a native partition-column predicate and reports actual bytes;
it defaults to a dry run and imposes a bytes-billed limit. No cloud performance numbers were invented.

**How does reconciliation work?** Operational orders/payment rows and lifecycle history provide
source metrics. Curated facts provide matching warehouse metrics. IDs/status/amounts identify
missing, unexpected or inconsistent records. A cutoff and quiescent batch boundary reduce normal
ingestion-delay noise. Results persist before a mismatch raises an error. It is not a cross-database
snapshot guarantee while writes continue concurrently.

**What are the important limitations?** Cloud adapters/IAM need real account smoke testing. Per-message
BigQuery batch loads are low-volume only. The cloud relay is scheduled, not continuously running.
Spark's correctness-first backfill scans history and can rebuild more days than requested. The source
control plane is a single availability dependency. Archive/RAW retention bounds replay. There is no
real payment gateway, road matching, production load benchmark or guaranteed zero-dollar cloud bill.
