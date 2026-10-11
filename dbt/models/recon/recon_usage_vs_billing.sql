-- Grain: one row per MSISDN x month x check. Revenue assurance: is the usage we carried actually billed?
--   usage_vs_billing_data     network data used above the plan allowance vs DATA_OVERAGE lines billed
--   usage_vs_billing_roaming  partner ROAMING charges vs ROAMING lines billed (assumes roaming is re-billed at cost)
-- CDR files may cover only part of a month. "Billed but no overage seen" is only an exception for fully covered months.
with usage as (
    select
        msisdn_hash,
        cast(date_trunc('month', event_ts) as date)                            as usage_month,
        sum(case when event_type = 'DATA' then data_mb else 0 end) / 1024.0    as data_gb_used,
        count(*)                                                               as cdr_count
    from {{ source('silver', 'network_cdr') }}
    group by 1, 2
),

cdr_cover as (
    select
        cast(date_trunc('month', event_ts) as date)    as usage_month,
        count(distinct cast(event_ts as date))         as days_covered
    from {{ source('silver', 'network_cdr') }}
    group by 1
),

partner as (
    select
        msisdn_hash,
        cast(date_trunc('month', period_start) as date)                        as usage_month,
        sum(case when service = 'ROAMING' then amount else 0 end)              as partner_roaming_amount
    from {{ source('silver', 'partner_usage') }}
    group by 1, 2
),

billed as (
    select
        a.msisdn_hash,
        cast(date_trunc('month', l.period_start) as date)                      as usage_month,
        sum(case when l.line_type = 'DATA_OVERAGE' then l.amount else 0 end)   as billed_data_overage,
        sum(case when l.line_type = 'ROAMING' then l.amount else 0 end)        as billed_roaming
    from {{ ref('fact_invoice_line') }} l
    join {{ ref('dim_account') }} a
        on a.account_sk = l.account_sk
    group by 1, 2
),

spine as (
    select msisdn_hash, usage_month from usage
    union
    select msisdn_hash, usage_month from partner
    union
    select msisdn_hash, usage_month from billed
),

joined as (
    select
        s.msisdn_hash,
        s.usage_month,
        cast(last_day(s.usage_month) as timestamp)                     as month_end_ts,
        u.data_gb_used,
        u.cdr_count,
        coalesce(cc.days_covered, 0) >= day(last_day(s.usage_month))   as full_month_cdr,
        coalesce(p.partner_roaming_amount, 0)                          as partner_roaming_amount,
        coalesce(b.billed_data_overage, 0)                             as billed_data_overage,
        coalesce(b.billed_roaming, 0)                                  as billed_roaming
    from spine s
    left join usage u     on u.msisdn_hash = s.msisdn_hash and u.usage_month = s.usage_month
    left join partner p   on p.msisdn_hash = s.msisdn_hash and p.usage_month = s.usage_month
    left join billed b    on b.msisdn_hash = s.msisdn_hash and b.usage_month = s.usage_month
    left join cdr_cover cc on cc.usage_month = s.usage_month
),

with_plan as (
    select
        j.*,
        c.customer_id,
        pl.data_gb as data_gb_allowance           -- null = unlimited
    from joined j
    left join {{ ref('dim_customer') }} c
        on c.msisdn_hash = j.msisdn_hash and {{ as_of('c', 'j.month_end_ts') }}
    left join {{ ref('dim_plan') }} pl
        on pl.plan_id = c.plan_id and {{ as_of('pl', 'j.month_end_ts') }}
    qualify row_number() over (
        partition by j.msisdn_hash, j.usage_month
        order by case when c.status = 'ACTIVE' then 0 else 1 end, c.customer_id desc
    ) = 1
),

accounts as (
    select msisdn_hash, account_id
    from {{ ref('dim_account') }}
    where is_current
    qualify row_number() over (partition by msisdn_hash order by account_id desc) = 1
),

data_check as (
    select
        'usage_vs_billing_data'                         as check_name,
        w.*,
        cast(null as decimal(12, 2))                    as expected_amount,
        w.billed_data_overage                           as actual_amount,
        cast(null as decimal(12, 2))                    as difference_amount,
        case
            when w.customer_id is null                                      then 'UNKNOWN_CUSTOMER'
            when w.data_gb_used is null                                     then 'NO_USAGE_DATA'
            when w.data_gb_used > coalesce(w.data_gb_allowance, 1e9)
                 and w.billed_data_overage = 0                              then 'UNBILLED_OVERAGE'
            when w.data_gb_used > coalesce(w.data_gb_allowance, 1e9)        then 'OVERAGE_BILLED'
            when w.billed_data_overage > 0 and not w.full_month_cdr         then 'PARTIAL_USAGE_DATA'
            when w.billed_data_overage > 0                                  then 'BILLED_WITHOUT_OVERAGE'
            else 'NO_OVERAGE'
        end                                             as match_status,
        concat('used ', round(w.data_gb_used, 2), ' GB of ',
               coalesce(cast(w.data_gb_allowance as string), 'unlimited'), ' GB') as detail
    from with_plan w
    where w.data_gb_used is not null or w.billed_data_overage > 0
),

roaming_check as (
    select
        'usage_vs_billing_roaming'                      as check_name,
        w.*,
        w.partner_roaming_amount                        as expected_amount,
        w.billed_roaming                                as actual_amount,
        w.billed_roaming - w.partner_roaming_amount     as difference_amount,
        case
            when w.partner_roaming_amount = 0                                                     then 'BILLED_WITHOUT_PARTNER_RECORD'
            when w.billed_roaming = 0                                                             then 'NOT_BILLED'
            when abs(w.billed_roaming - w.partner_roaming_amount) <= {{ var('recon_tolerance') }} then 'MATCHED'
            when w.billed_roaming < w.partner_roaming_amount                                      then 'UNDER_BILLED'
            else 'OVER_BILLED'
        end                                             as match_status,
        concat('partner ', w.partner_roaming_amount, ' EUR, billed ', w.billed_roaming, ' EUR') as detail
    from with_plan w
    where w.partner_roaming_amount > 0 or w.billed_roaming > 0
),

checks as (
    select check_name, msisdn_hash, usage_month, customer_id, data_gb_used, data_gb_allowance, cdr_count,
           full_month_cdr, expected_amount, actual_amount, difference_amount, match_status, detail
    from data_check
    union all
    select check_name, msisdn_hash, usage_month, customer_id, data_gb_used, data_gb_allowance, cdr_count,
           full_month_cdr, expected_amount, actual_amount, difference_amount, match_status, detail
    from roaming_check
)

select
    k.check_name,
    concat(k.msisdn_hash, '|', k.usage_month)   as record_id,
    cast(null as bigint)                        as invoice_id,
    cast(null as bigint)                        as payment_id,
    a.account_id,
    k.customer_id,
    k.msisdn_hash,
    k.usage_month                               as recon_date,
    k.expected_amount,
    k.actual_amount,
    k.difference_amount,
    k.match_status,
    k.match_status in ('UNBILLED_OVERAGE', 'BILLED_WITHOUT_OVERAGE', 'NOT_BILLED', 'UNDER_BILLED',
                       'OVER_BILLED', 'BILLED_WITHOUT_PARTNER_RECORD') as is_exception,
    k.detail,
    k.usage_month,
    k.data_gb_used,
    k.data_gb_allowance,
    k.cdr_count,
    k.full_month_cdr
from checks k
left join accounts a
    on a.msisdn_hash = k.msisdn_hash
