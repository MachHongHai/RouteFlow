# Local first and bounded cloud usage

Status: accepted and implemented.

## Context

The user requires a meaningful demo without relying on trial credits or paid always-on services.

## Decision

Keep all functionality local, schedule bounded cloud jobs, use scale-to-zero private services, external PostgreSQL, storage lifecycles and query limits. Do not provision cloud Spark.

## Alternatives

Cloud SQL, continuously polling Cloud Run workers and managed Spark introduce recurring cost.

## Trade-offs

Scheduled outbox draining increases cloud event latency. Dual-adapter images can exceed registry free storage. Budgets are not spending caps.

## Consequences

Current pricing sources and shutdown commands are documented; the scheduler starts paused and no infrastructure is automatically applied.
