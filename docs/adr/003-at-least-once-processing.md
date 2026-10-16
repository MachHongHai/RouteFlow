# At-least-once delivery

Status: accepted and implemented.

## Context

GCS, source PostgreSQL, Pub/Sub and analytical storage have independent commits.

## Decision

Acknowledge only after RAW commit or durable DLQ quarantine; preserve archive bytes before validation.

## Alternatives

Distributed two-phase commit is unavailable across this stack. Exactly-once messaging alone would not solve storage side effects.

## Trade-offs

Retries and duplicate RAW attempts are normal. A source control-plane outage can require native broker DLQ recovery.

## Consequences

No end-to-end exactly-once claim is made. The consumer crash test proves that redelivery leaves logical RAW and facts correct.
