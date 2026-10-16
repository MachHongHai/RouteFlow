select o.order_id, o.driver_id, d.driver_key, o.zone_id, o.created_at,
       o.picked_up_at, o.delivered_at, t.delivery_minutes, t.transit_minutes,
       case when t.delivery_minutes > 60 then true else false end as missed_sla
from {{ ref('fact_order') }} o
join {{ ref('int_delivery_durations') }} t on o.order_id=t.order_id
left join {{ ref('dim_driver') }} d on o.driver_id=d.driver_id
  and o.assigned_at >= d.valid_from and (o.assigned_at < d.valid_to or d.valid_to is null)

