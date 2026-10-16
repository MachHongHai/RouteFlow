{% if target.type == 'bigquery' %}
select day as business_date, extract(year from day) as year, extract(month from day) as month,
       extract(day from day) as day_of_month
from unnest(generate_date_array('2020-01-01','2035-12-31')) as day
{% else %}
select cast(day as date) as business_date, extract(year from day) as year,
       extract(month from day) as month, extract(day from day) as day_of_month
from generate_series(date '2020-01-01', date '2035-12-31', interval '1 day') as day
{% endif %}

