select d.business_date, d.driver_id
from {{ ref('fact_driver_mobility') }} d
left join (
  select business_date, driver_id, sum(gps_points) as hourly_points,
         sum(estimated_distance_km) as hourly_km
  from {{ source('raw','spark_driver_hourly_activity') }} group by business_date, driver_id
) h on d.driver_id=h.driver_id and d.business_date=h.business_date
where d.gps_points <> h.hourly_points or h.hourly_points is null
   or abs(d.estimated_distance_km-h.hourly_km) > 0.000001
   or d.estimated_distance_km < 0 or d.estimated_active_seconds < 0
   or d.estimated_average_speed_kmh > 120
