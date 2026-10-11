{#
  Point-in-time join to an SCD2 dimension: picks the version that was valid at `ts`.
  Events older than the first version (e.g. invoices issued before the Debezium snapshot) fall back to the first
  version, so history is not lost just because CDC started later than the business did.
  Usage:  left join {{ ref('dim_customer') }} c on c.customer_id = f.customer_id and {{ as_of('c', 'f.event_ts') }}
#}
{% macro as_of(dim, ts) -%}
    ({{ dim }}.valid_to > {{ ts }} and ({{ dim }}.valid_from <= {{ ts }} or {{ dim }}.is_first_version))
{%- endmacro %}


{# yyyymmdd integer key into dim_date from a date or timestamp expression. #}
{% macro date_key(expr) -%}
    cast(date_format({{ expr }}, 'yyyyMMdd') as int)
{%- endmacro %}
