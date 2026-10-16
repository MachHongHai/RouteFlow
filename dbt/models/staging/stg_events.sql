with ranked as (
  select *, row_number() over (partition by event_id order by ingested_at, fingerprint) as dedup_rank
  from {{ source('raw', 'raw_events') }}
)
select event_id, event_type, event_version, aggregate_id, aggregate_version,
       event_time, produced_at, ingested_at, processed_at, payload, fingerprint
from ranked where dedup_rank = 1
