select * from {{ ref('stg_orders') }}
where event_type in ('PAYMENT_CONFIRMED','PAYMENT_FAILED','REFUND_CREATED')

