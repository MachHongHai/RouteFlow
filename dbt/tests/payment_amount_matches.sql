select p.payment_id from {{ ref('fact_payment') }} p
join {{ ref('fact_order') }} o on p.order_id=o.order_id
where p.amount_cents <> o.amount_cents or p.payment_status <> o.payment_status
