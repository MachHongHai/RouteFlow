select order_id from {{ ref('fact_order') }}
where amount_cents <= 0
   or (delivered_at is not null and (driver_id is null or payment_status not in ('CONFIRMED','REFUNDED')))
   or delivered_at < picked_up_at or picked_up_at < assigned_at or assigned_at < paid_at
   or paid_at < created_at or cancelled_at < created_at
   or (cancelled_at is not null and delivered_at is not null)
