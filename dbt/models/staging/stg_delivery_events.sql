select * from {{ ref('stg_orders') }}
where event_type in ('DRIVER_ASSIGNED','DRIVER_CANCELLED','DRIVER_ARRIVED',
                    'ORDER_PICKED_UP','IN_TRANSIT','DELIVERED')
