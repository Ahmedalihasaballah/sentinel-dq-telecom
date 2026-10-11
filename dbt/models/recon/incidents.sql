-- Grain: one row per incident.
--   data_quality     incidents opened/resolved by the quality notebooks (monitoring.incidents)
--   reconciliation   one open incident per check x exception type, with the records and EUR it affects
with dq as (
    select
        incident_id,
        'data_quality'                  as incident_source,
        dataset,
        check_name,
        pillar,
        severity,
        status,
        opened_at,
        closed_at,
        description,
        cast(null as bigint)            as affected_records,
        cast(null as decimal(14, 2))    as amount_at_risk
    from {{ source('monitoring', 'incidents') }}
),

recon as (
    select
        check_name,
        match_status,
        count(*)                                    as affected_records,
        sum(abs(coalesce(difference_amount, 0)))    as amount_at_risk,
        min(recon_date)                             as first_recon_date
    from {{ ref('recon_results') }}
    where is_exception
    group by check_name, match_status
)

select * from dq

union all

select
    {{ dbt_utils.generate_surrogate_key(['check_name', 'match_status']) }},
    'reconciliation',
    check_name,
    match_status,
    'reconciliation',
    case
        when amount_at_risk >= {{ var('recon_high_amount') }} then 'high'
        when amount_at_risk > 0 then 'medium'
        else 'low'
    end,
    'OPEN',
    cast(first_recon_date as timestamp),
    cast(null as timestamp),
    concat(affected_records, ' record(s) ', match_status, ' in ', check_name,
           ', ', round(amount_at_risk, 2), ' EUR difference'),
    affected_records,
    cast(amount_at_risk as decimal(14, 2))
from recon
