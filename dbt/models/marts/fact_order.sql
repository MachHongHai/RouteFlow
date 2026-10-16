{{ config(materialized='incremental', unique_key='order_id',
          incremental_strategy='merge' if target.type == 'bigquery' else 'delete+insert',
          partition_by={'field':'created_at','data_type':'timestamp','granularity':'day'} if target.type == 'bigquery' else none,
          cluster_by=['zone_id','status'] if target.type == 'bigquery' else none) }}

with affected as (
  select distinct order_id from {{ ref('stg_orders') }}
  {% if is_incremental() %}
    where ingested_at >= {{ ago('(select coalesce(max(processed_ingestion_at), cast(\'1970-01-01\' as ' ~ dbt.type_timestamp() ~ ')) from ' ~ this ~ ')', var('lookback_days')) }}
    {% if var('backfill_from', none) %}
      or cast(created_at as date) between cast('{{ var("backfill_from") }}' as date)
                                      and cast('{{ var("backfill_to") }}' as date)
    {% endif %}
  {% endif %}
)
select l.*, {{ key('l.customer_id') }} as customer_key,
       {{ key('l.restaurant_id') }} as restaurant_key, {{ key('l.zone_id') }} as zone_key
from {{ ref('int_order_lifecycle') }} l join affected a on l.order_id=a.order_id
