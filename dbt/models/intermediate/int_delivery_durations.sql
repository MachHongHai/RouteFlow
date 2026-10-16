select order_id, {{ minutes_between('created_at','delivered_at') }} as delivery_minutes,
       {{ minutes_between('picked_up_at','delivered_at') }} as transit_minutes
from {{ ref('int_order_lifecycle') }} where delivered_at is not null

