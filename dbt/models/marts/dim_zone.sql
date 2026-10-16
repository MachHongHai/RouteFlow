with ranked as (
  select aggregate_id as zone_id, payload,
         row_number() over (partition by aggregate_id order by aggregate_version desc) as rank
  from {{ ref('stg_events') }} where event_type = 'ZONE_UPDATED'
)
select zone_id, {{ key('zone_id') }} as zone_key,
       {{ json_value('payload','name') }} as name
from ranked where rank=1
