select aggregate_id as driver_id, aggregate_version,
       {{ json_value('payload','name') }} as name,
       {{ json_value('payload','zone_id') }} as zone_id,
       event_time, ingested_at
from {{ ref('stg_events') }} where event_type = 'DRIVER_UPDATED'
