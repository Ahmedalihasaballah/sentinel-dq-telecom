-- Grain: one row per partner usage record (roaming / international calls charged by partner networks).
-- Customer found through msisdn_hash as of the start of the partner period.
with partner as (
    select *, cast(period_start as timestamp) as period_ts
    from {{ source('silver', 'partner_usage') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['u.partner_record_id']) }} as partner_usage_sk,
    c.customer_sk,
    {{ date_key('u.period_start') }}                                as date_key,
    u.partner_record_id,
    c.customer_id,
    u.msisdn_hash,
    u.service,
    u.currency,
    u.period_start,
    u.amount,
    1                                                               as usage_count
from partner u
left join {{ ref('dim_customer') }} c
    on c.msisdn_hash = u.msisdn_hash and {{ as_of('c', 'u.period_ts') }}
qualify row_number() over (
    partition by u.partner_record_id
    order by case when c.status = 'ACTIVE' then 0 else 1 end, c.customer_id desc
) = 1
