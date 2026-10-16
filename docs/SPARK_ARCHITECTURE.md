# Spark GPS branch

Spark 4.0.2 with Python 3.12 and Java 17 runs on a local standalone Master/Worker profile.
`routeflow/spark/reader.py` reads the same immutable wrappers the consumer archives. It decodes
original bytes with explicit envelope/payload schemas, selects GPS events and preserves malformed
inputs for validation. `archived_at` is used as the receipt timestamp. No static CSV is involved.

Validation assigns explicit reasons for missing IDs, unsupported versions, invalid coordinates
and null timestamps. Reusing one ID for conflicting valid coordinates rejects all conflicting
variants rather than arbitrarily selecting a position. Identical redeliveries are deduplicated
using event ID with deterministic ingestion/content ordering.

`transformations.py` partitions by driver, orders by `event_time,event_id`, and applies `lag` to
the previous valid point. Haversine uses native SQL expressions and an earth radius of 6371.0088 km.
Segments are attributed to the UTC date/hour of the **endpoint**, including midnight crossings.
Thresholds default to 120 km/h and 1800 seconds. Speed jumps, zero-time movement, large gaps and
identical coordinates are flagged; flagged segments contribute zero estimated distance/active time.
Coordinates themselves are retained in silver for investigation. GPS distance is an estimate,
not road distance or a guarantee of actual driving time.

Driver name and fallback zone are broadcast from a source snapshot taken at job start. GPS payload
zone takes precedence; missing profiles remain with an explicit flag and UNKNOWN fallback zone.
This reference is current, not a historical shift roster. Historical assignment joins remain in
the order/dbt branch rather than being duplicated inside Spark.

Outputs under `DATA_LAKE_PATH/runs/<uuid>`:

| Layer / dataset | Grain |
|---|---|
| `silver/cleaned_driver_locations` | Deduplicated GPS event |
| `gold/rejected_driver_locations` | Rejected archived observation with reason/original JSON |
| `gold/driver_daily_distance` | Driver / UTC date |
| `gold/driver_hourly_activity` | Driver / UTC date / hour |
| `gold/zone_hourly_driver_activity` | Zone / UTC date / hour |
| `gold/driver_gps_quality_metrics` | Driver / UTC date |

All are Parquet partitioned by `business_date`. Each run writes an immutable generation. Local
loading reads Parquet in Arrow batches and transactionally deletes/replaces affected warehouse
dates across all four gold datasets. Cloud loading stages GCS Parquet in BigQuery then applies a
multi-statement replacement transaction. It removes staging tables after success; failed staging
tables inherit dataset expiration. Empty affected partitions are cleared too.

`latest_run.json` points to the last accepted **range** generation; it is not a full table snapshot.
The warehouse is authoritative for combining historical partitions. Previous Parquet generations
are retained for audit/recovery; they are not all appended to warehouse tables. Rerunning a range
does not double-count. Local source session advisory locking serializes materializations. The
warehouse transaction remains idempotent even if the driver crashes before publishing its manifest.

For correctness, RAW JSON is scanned for historical context before the date filter. A point arriving
late can alter the next segment even several days later. Therefore backfill rebuilds the suffix
from `--from` through the greatest of requested end, latest GPS date and relevant rejected date.
This conservative strategy also preserves the predecessor before midnight. The default starting
range is three UTC days. Events older than that require explicit `spark-backfill --from`.
This is bounded demo-scale correctness, not a claim of optimal billion-point incremental execution.

The loader feeds `fact_driver_mobility` and `fact_zone_mobility` in dbt. Warehouse tests compare
daily and hourly point counts and distances and validate the business grain. Spark checks unique
silver event IDs, nonnegative durations/distance and summary consistency before publication.
See [backfill](BACKFILL.md), [optimization](SPARK_OPTIMIZATION.md), and [testing](TESTING.md).
