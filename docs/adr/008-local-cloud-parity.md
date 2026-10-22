# Shared application and environment adapters

Status: accepted and implemented.

## Context

Local development must work without a cloud account while retaining deployable GCP integrations.

## Decision

Share API, contracts, domain, relay, consumer and operations; adapt PostgreSQL versus BigQuery storage and local files versus GCS. Use adapter-aware dbt SQL.

## Alternatives

Separate local/cloud applications drift. Replacing Pub/Sub with an in-memory mock would not verify broker semantics.

## Trade-offs

Postgres RAW uniqueness differs from BigQuery append loads; local tests do not establish real IAM, GCS connector or BigQuery API behavior.

## Consequences

Validation documents distinguish locally tested behavior from implemented cloud code; deployment stays opt-in.
