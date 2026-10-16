select event_id, aggregate_id as order_id, aggregate_version, event_type,
       event_time, ingested_at,
       {{ json_value('payload','customer_id') }} as customer_id,
       {{ json_value('payload','restaurant_id') }} as restaurant_id,
       {{ json_value('payload','zone_id') }} as zone_id,
       {{ json_value('payload','driver_id') }} as driver_id,
       {{ json_value('payload','payment_id') }} as payment_id,
       {{ json_value('payload','status') }} as status,
       {{ json_value('payload','payment_status') }} as payment_status,
       cast({{ json_value('payload','amount_cents') }} as {{ dbt.type_bigint() }}) as amount_cents,
       cast({{ json_value('payload','distance_km') }} as {{ dbt.type_int() }}) as distance_km,
       cast({{ json_value('payload','created_at') }} as {{ 'timestamp' if target.type == 'bigquery' else 'timestamptz' }}) as created_at
from {{ ref('stg_events') }}
where event_type in ('ORDER_CREATED','PAYMENT_CONFIRMED','PAYMENT_FAILED',
  'RESTAURANT_ACCEPTED','DRIVER_ASSIGNED','DRIVER_ARRIVED','ORDER_PICKED_UP','IN_TRANSIT',
  'DELIVERED','ORDER_CANCELLED','DRIVER_CANCELLED','REFUND_CREATED')
