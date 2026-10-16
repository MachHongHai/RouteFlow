# Layered analytics

Status: accepted and implemented.

## Context

Raw transport records do not directly provide stable business grains, history or validated dimensions.

## Decision

Use RAW, staging deduplication, intermediate lifecycle reconstruction and marts. Model driver SCD2 directly from profile events with lead().

## Alternatives

Querying source tables for every dashboard would couple analytics to OLTP. Reproducing all SQL in Spark would duplicate responsibilities.

## Trade-offs

Reference dimensions are rebuilt at demonstration scale. Retention can remove history needed for old facts or SCD2.

## Consequences

Fact grains and keys are documented and tested; full refresh and backfill are actual executable operations.
