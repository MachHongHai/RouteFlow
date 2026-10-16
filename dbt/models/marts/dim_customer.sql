with ranked as (
  select aggregate_id as customer_id, payload,
         row_number() over (partition by aggregate_id order by aggregate_version desc) as rank
  from {{ ref('stg_events') }} where event_type = 'CUSTOMER_UPDATED'
)
select customer_id, {{ key('customer_id') }} as customer_key,
       {{ json_value('payload','name') }} as name
from ranked where rank=1
