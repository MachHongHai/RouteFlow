# Event contracts and time semantics

Canonical versioned JSON Schemas are packaged under `routeflow/schemas/`. `routeflow.contracts`
validates with JSON Schema Draft 2020-12, explicit format checks and additional identity/status
checks. All business APIs validate before inserting an outbox row in the same transaction.

The envelope requires `event_id`, `event_type`, `event_version`, `aggregate_id`,
`aggregate_version`, `event_time`, `produced_at`, `producer`, `correlation_id` and `payload`.
UUID event identifiers are globally unique; aggregate versions increase per business aggregate.
GPS samples each have their own location aggregate ID; their sequence is timestamp + event ID.
Order payloads contain complete analytical snapshots, including money, foreign keys and payment state.

| Timestamp | Meaning |
|---|---|
| `event_time` | Business occurrence time; simulation may create historical events |
| `produced_at` | Envelope construction time |
| `archived_at` | Consumer receipt archived durably, used as Spark ingestion time |
| `ingested_at` | RAW write attempt time; local duplicate attempts are stored separately |
| `processed_at` | Consumer RAW processing timestamp; transformation runs have their own run times |

All include time zones. Spark sessions and dbt's timestamp interpretation use UTC; no inference
from the host's Asia/Saigon timezone is allowed. Delivery status uses `aggregate_version`, never
arrival order. The GPS branch uses window functions over event time, never file or ingestion order.

V2 deliberately adds optional `traceparent` to V1. Consumers explicitly accept versions 1 and 2,
while unsupported versions enter quarantine. Unknown optional properties are tolerated so a
consumer built against V1 can ignore additive fields. The compatibility check asserts no newly
required envelope fields, no removed properties and unchanged existing payload constraints.
It catches the supported additive example; it is not a general mathematical schema-subsumption tool.

Breaking type changes, tighter ranges or new mandatory payload fields require a new contract and
consumer rollout. Replaying a poisoned original cannot magically repair it: preserve the original
DLQ evidence, correct the upstream producer and publish a corrected event with a new event ID.
