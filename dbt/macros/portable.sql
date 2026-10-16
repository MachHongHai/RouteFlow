{% macro generate_schema_name(custom_schema_name, node) -%}
  {% if target.type == 'bigquery' %}routeflow_{{ custom_schema_name or 'analytics' }}
  {% else %}{{ custom_schema_name or target.schema }}{% endif %}
{%- endmacro %}

{% macro json_value(column, field) -%}
  {% if target.type == 'bigquery' %}json_value({{ column }}, '$.{{ field }}')
  {% else %}({{ column }}::jsonb ->> '{{ field }}'){% endif %}
{%- endmacro %}

{% macro ago(column, days) -%}
  {% if target.type == 'bigquery' %}timestamp_sub({{ column }}, interval {{ days }} day)
  {% else %}{{ column }} - interval '{{ days }} days'{% endif %}
{%- endmacro %}

{% macro minutes_between(start, finish) -%}
  {% if target.type == 'bigquery' %}timestamp_diff({{ finish }}, {{ start }}, second) / 60.0
  {% else %}extract(epoch from ({{ finish }} - {{ start }})) / 60.0{% endif %}
{%- endmacro %}

{% macro key(column) -%}
  {% if target.type == 'bigquery' %}to_hex(md5(cast({{ column }} as string)))
  {% else %}md5(cast({{ column }} as text)){% endif %}
{%- endmacro %}

