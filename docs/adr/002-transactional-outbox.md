# Transactional outbox

Status: accepted and implemented.

## Context

Business records and external broker publication cannot share one database transaction.

## Decision

Insert validated envelopes in the same SQLAlchemy transaction as source mutations. Relay claims with SKIP LOCKED and leases, then awaits broker confirmation before marking.

## Alternatives

Direct publish before commit can emit rolled-back orders; publish after commit can lose events on crash. CDC would add infrastructure without a current need.

## Trade-offs

A publish/mark crash produces duplicates. Batch-sized leases may delay recovery; ten unsuccessful claims require explicit reset.

## Consequences

Committed business mutations retain durable publication intent. Integration tests cover rollback, duplicate publication and concurrent workers.
