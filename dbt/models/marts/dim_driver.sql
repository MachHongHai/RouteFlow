-- Event-sourced SCD2: rebuilding bounds correctly handles a late version in the middle of history.
select {{ key("driver_id || ':' || cast(aggregate_version as " ~ dbt.type_string() ~ ")") }} as driver_key,
       driver_id, name, zone_id, aggregate_version, event_time as valid_from,
       lead(event_time) over (partition by driver_id order by aggregate_version) as valid_to,
       case when lead(event_time) over (partition by driver_id order by aggregate_version) is null
            then true else false end as is_current
from {{ ref('stg_drivers') }}
