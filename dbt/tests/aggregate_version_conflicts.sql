select aggregate_id, aggregate_version from {{ ref('stg_events') }}
group by aggregate_id, aggregate_version having count(*) > 1

