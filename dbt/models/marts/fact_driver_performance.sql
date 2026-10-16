select driver_id, cast(delivered_at as date) as business_date,
       extract(hour from delivered_at) as hour_utc, count(*) as deliveries,
       sum(transit_minutes) as busy_minutes, avg(delivery_minutes) as avg_delivery_minutes
from {{ ref('fact_delivery') }}
group by driver_id, cast(delivered_at as date), extract(hour from delivered_at)

