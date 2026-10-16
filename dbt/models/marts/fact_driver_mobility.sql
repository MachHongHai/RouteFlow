-- One row per driver and UTC business date. Daily GPS estimates are owned by Spark.
select g.business_date, g.driver_id, d.driver_key as current_driver_key,
       g.gps_points, g.estimated_distance_km, g.estimated_active_seconds,
       g.estimated_average_speed_kmh, g.anomalous_segments,
       coalesce(q.invalid_points,0) as invalid_points,
       coalesce(q.missing_metadata_points,0) as missing_metadata_points
from {{ ref('stg_driver_gps_daily') }} g
left join {{ ref('dim_driver') }} d on g.driver_id=d.driver_id and d.is_current
left join {{ source('raw','spark_driver_gps_quality_metrics') }} q
  on g.driver_id=q.driver_id and g.business_date=q.business_date
