# Spark for historical GPS

Status: accepted and implemented.

## Context

Per-driver historical windows, distance estimation and data-lake Parquet are a coherent distributed batch responsibility.

## Decision

Use a pinned standalone Master/Worker profile with a separate client-mode driver; read real archived GPS and transactionally load gold summaries for dbt.

## Alternatives

Using Spark for all order lifecycle SQL adds duplication; paid managed Spark would undermine the local/free demonstration.

## Trade-offs

The correctness-first reader scans RAW history. Broadcast reference data is a current snapshot; road matching and historical shift calendars are not implemented.

## Consequences

Spark numerical tests and actual worker execution are verified. An optional external cloud runner can feed GCS/BigQuery without treating distributed Spark as a Cloud Run Job.
