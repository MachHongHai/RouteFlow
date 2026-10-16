# Identity and deduplication

Status: accepted and implemented.

## Context

Publication, acknowledgement and replay can repeat an event, while producer bugs can reuse an ID with changed content.

## Decision

Guard canonical event identity in source PostgreSQL; enforce local RAW event-ID PK; append cloud RAW and deduplicate in stg_events; upsert business-grain facts.

## Alternatives

Best-effort BigQuery insert IDs or in-memory sets cannot provide durable logical deduplication.

## Trade-offs

The control DB is an extra write dependency. Cloud RAW can contain duplicates even after a successful load job.

## Consequences

An identity row is not a completion marker, so a crash before RAW never suppresses retries. Conflicting payloads enter DLQ.
