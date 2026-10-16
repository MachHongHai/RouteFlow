select g.*, z.zone_key
from {{ source('raw','spark_zone_hourly_driver_activity') }} g
left join {{ ref('dim_zone') }} z on g.zone_id=z.zone_id
