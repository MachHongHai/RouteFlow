with ranked as (
  select *, row_number() over (partition by payment_id order by aggregate_version desc) as rank
  from {{ ref('stg_payments') }} where payment_id is not null
)
select payment_id, order_id, payment_status, amount_cents, event_time
from ranked where rank=1
