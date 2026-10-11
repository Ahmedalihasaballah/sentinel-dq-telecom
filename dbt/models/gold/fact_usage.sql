-- Grain: one row per network usage record (CDR).
-- CDRs only carry the MSISDN, so the customer is found through msisdn_hash (same salted hash in every Silver table),
-- as of the event time. If one number maps to several customers, the ACTIVE one wins, then the newest customer_id.
select
    {{ dbt_utils.generate_surrogate_key(['n.cdr_id']) }} as usage_sk,
    c.customer_sk,
    p.plan_sk,
    cell.cell_sk,
    {{ date_key('n.event_ts') }}                         as date_key,
    n.cdr_id,
    c.customer_id,
    n.msisdn_hash,
    n.cell_id,
    n.event_type,
    n.call_result,
    n.event_ts,
    n.duration_sec,
    n.data_mb,
    1                                                    as usage_count,
    case when n.call_result = 'DROPPED' then 1 else 0 end as dropped_count
from {{ source('silver', 'network_cdr') }} n
left join {{ ref('dim_customer') }} c
    on c.msisdn_hash = n.msisdn_hash and {{ as_of('c', 'n.event_ts') }}
left join {{ ref('dim_plan') }} p
    on p.plan_id = c.plan_id and {{ as_of('p', 'n.event_ts') }}
left join {{ ref('dim_network_cell') }} cell
    on cell.cell_id = n.cell_id
qualify row_number() over (
    partition by n.cdr_id
    order by case when c.status = 'ACTIVE' then 0 else 1 end, c.customer_id desc
) = 1
