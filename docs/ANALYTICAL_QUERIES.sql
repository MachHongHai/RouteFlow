-- Local PostgreSQL; use routeflow_analytics instead of analytics in BigQuery.
-- Mean delivery duration and SLA misses by delivery zone.
select z.name, count(*) as deliveries, avg(d.delivery_minutes) as avg_minutes,
       avg(case when d.missed_sla then 1.0 else 0.0 end) as sla_miss_fraction
from analytics.fact_delivery d join analytics.dim_zone z on d.zone_id=z.zone_id
group by z.name order by avg_minutes desc;

-- Cancellation history survives subsequent refund status.
select z.name, count(*) as orders,
       avg(case when o.cancelled_at is not null then 1.0 else 0.0 end) as cancellation_fraction
from analytics.fact_order o join analytics.dim_zone z on o.zone_id=z.zone_id
group by z.name;

-- Failed payment fraction (one simulated payment per order).
select avg(case when payment_status='FAILED' then 1.0 else 0.0 end) as failure_fraction
from analytics.fact_payment;

-- Demand pattern in UTC. Synthetic lunch/dinner peaks are workload assumptions.
select extract(hour from created_at) as hour_utc, count(*) as orders
from analytics.fact_order group by extract(hour from created_at) order by hour_utc;

-- GPS movement estimates from Spark, with explicit quality context.
select business_date, driver_id, gps_points, estimated_distance_km,
       estimated_average_speed_kmh, anomalous_segments, invalid_points, missing_metadata_points
from analytics.fact_driver_mobility order by estimated_distance_km desc;

-- Event lateness by observed RAW ingestion (logical IDs, no delivery-attempt inflation).
select event_type, count(*) as events,
       avg(case when ingested_at > event_time + interval '15 minutes' then 1.0 else 0.0 end)
       as fraction_later_than_15_minutes
from staging.stg_events group by event_type;

-- Current order state and booked gross cents; gross is not net revenue.
select status, count(*) as orders, sum(amount_cents) as booked_gross_cents
from analytics.fact_order group by status;
