select * from {{ source('raw','spark_driver_daily_distance') }}
