select order_id, driver_id, event_time as assigned_at, aggregate_version
from {{ ref('stg_delivery_events') }} where event_type='DRIVER_ASSIGNED'

