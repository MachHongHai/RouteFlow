# Order by business sequence

Status: accepted and implemented.

## Context

Broker arrival order does not match lifecycle order; historical GPS points can also arrive late.

## Decision

Use aggregate versions for order state and timestamp/event-ID windows for GPS. dbt selects new ingestion with an overlap and reconstructs all retained history.

## Alternatives

Last-arrival-wins can turn DELIVERED back into IN_TRANSIT. A simple event-date watermark silently misses late changes.

## Trade-offs

History scans cost more than maintaining specialized state indexes. Expired RAW partitions limit completeness.

## Consequences

Tests reverse delivery order and assert midnight GPS distances. Operators can explicitly extend retention and backfill older data.
