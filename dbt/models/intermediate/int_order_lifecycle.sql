with ranked as (
  select *, row_number() over (partition by order_id order by aggregate_version desc) as state_rank
  from {{ ref('stg_orders') }}
), times as (
  select order_id,
    min(case when event_type = 'DRIVER_ASSIGNED' then event_time end) as assigned_at,
    min(case when event_type = 'ORDER_PICKED_UP' then event_time end) as picked_up_at,
    min(case when event_type = 'DELIVERED' then event_time end) as delivered_at,
    min(case when event_type = 'ORDER_CANCELLED' then event_time end) as cancelled_at,
    min(case when event_type = 'PAYMENT_CONFIRMED' then event_time end) as paid_at,
    max(ingested_at) as processed_ingestion_at
  from {{ ref('stg_orders') }} group by order_id
)
select r.order_id, r.customer_id, r.restaurant_id, r.zone_id, r.driver_id, r.payment_id,
       r.status, r.payment_status, r.amount_cents, r.distance_km, r.created_at,
       r.aggregate_version, r.event_time as last_event_time,
       t.assigned_at, t.picked_up_at, t.delivered_at, t.cancelled_at, t.paid_at,
       t.processed_ingestion_at
from ranked r join times t on r.order_id=t.order_id where r.state_rank=1
