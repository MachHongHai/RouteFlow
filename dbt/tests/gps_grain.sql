select business_date, driver_id from {{ ref('fact_driver_mobility') }}
group by business_date, driver_id having count(*) > 1
