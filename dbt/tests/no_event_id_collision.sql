select event_id from {{ source('raw','raw_events') }}
group by event_id having count(distinct fingerprint) > 1
