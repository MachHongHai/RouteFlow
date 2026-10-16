with ranked as (
  select aggregate_id as restaurant_id, payload,
         row_number() over (partition by aggregate_id order by aggregate_version desc) as rank
  from {{ ref('stg_events') }} where event_type = 'RESTAURANT_UPDATED'
)
select restaurant_id, {{ key('restaurant_id') }} as restaurant_key,
       {{ json_value('payload','name') }} as name
from ranked where rank=1
