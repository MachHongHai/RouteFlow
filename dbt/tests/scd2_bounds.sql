select driver_id from {{ ref('dim_driver') }}
group by driver_id having sum(case when is_current then 1 else 0 end) <> 1
union all
select driver_id from {{ ref('dim_driver') }} where valid_to < valid_from
