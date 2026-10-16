select event_id as location_id, {{ json_value('payload','driver_id') }} as driver_id,
       cast({{ json_value('payload','latitude') }} as {{ dbt.type_float() }}) as latitude,
       cast({{ json_value('payload','longitude') }} as {{ dbt.type_float() }}) as longitude,
       event_time, ingested_at
from {{ ref('stg_events') }} where event_type = 'DRIVER_LOCATION'

