select payment_id, order_id, payment_status, amount_cents, event_time as updated_at
from {{ ref('int_payment_state') }}
