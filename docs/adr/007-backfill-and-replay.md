# Separate retry, replay and backfill

Status: accepted and implemented.

## Context

Restoring delivery attempts and rebuilding historical analytics are different operational jobs.

## Decision

Replay archived original bytes; backfill a validated business-date range and rerun dbt. Spark separately replaces a conservative affected suffix after full predecessor reconstruction.

## Alternatives

Blind append of aggregate rows double-counts. Full-database rebuild for every delivery would discard meaningful incremental behavior.

## Trade-offs

Spark may rebuild more days than --to. Immutable Parquet generations use additional disk and need eventual operator cleanup.

## Consequences

Run metadata records failures; repeated replay/backfill is safe and integration-tested.
