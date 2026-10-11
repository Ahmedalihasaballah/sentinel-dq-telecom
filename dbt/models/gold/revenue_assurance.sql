-- Grain: one row per month. Billed vs collected, and the money the reconciliation checks put at risk.
--   collection_gap   invoiced but not (fully) collected        (invoice_vs_payment)
--   revenue_leakage  usage charged to us but not billed out    (usage_vs_billing_roaming)
with invoiced as (
    select
        cast(date_format(period_start, 'yyyyMM') as int)                    as year_month,
        sum(case when status <> 'CANCELLED' then total_amount else 0 end)   as invoiced_amount,
        sum(invoice_count)                                                  as invoice_count
    from {{ ref('fact_invoice') }}
    group by 1
),

collected as (
    select cast(date_format(paid_at, 'yyyyMM') as int) as year_month, sum(net_collected_amount) as collected_amount
    from {{ ref('fact_payment') }}
    group by 1
),

partner as (
    select cast(date_format(period_start, 'yyyyMM') as int) as year_month, sum(amount) as partner_charges
    from {{ ref('fact_partner_usage') }}
    group by 1
),

recon as (
    select
        cast(date_format(recon_date, 'yyyyMM') as int)                                         as year_month,
        sum(case when check_name = 'invoice_vs_payment' and match_status in ('UNPAID', 'UNDERPAID', 'PAYMENT_FAILED')
                 then greatest(-difference_amount, 0) else 0 end)                              as collection_gap_amount,
        sum(case when check_name = 'invoice_vs_payment' and match_status = 'OVERPAID'
                 then difference_amount else 0 end)                                            as overpaid_amount,
        sum(case when check_name = 'invoice_vs_payment' and match_status = 'ORPHAN_PAYMENT'
                 then actual_amount else 0 end)                                                as orphan_payment_amount,
        sum(case when check_name = 'usage_vs_billing_roaming' and match_status in ('NOT_BILLED', 'UNDER_BILLED')
                 then -difference_amount else 0 end)                                           as revenue_leakage_amount,
        sum(case when check_name = 'usage_vs_billing_data' and match_status = 'UNBILLED_OVERAGE'
                 then 1 else 0 end)                                                            as unbilled_overage_count,
        sum(case when check_name like 'batch_vs_cdc%' and is_exception then 1 else 0 end)      as batch_mismatch_count,
        sum(case when is_exception then 1 else 0 end)                                          as exception_count,
        count(*)                                                                               as records_checked
    from {{ ref('recon_results') }}
    group by 1
),

months as (
    select year_month from invoiced
    union select year_month from collected
    union select year_month from partner
    union select year_month from recon
)

select
    m.year_month,
    coalesce(i.invoice_count, 0)                as invoice_count,
    coalesce(i.invoiced_amount, 0)              as invoiced_amount,
    coalesce(c.collected_amount, 0)             as collected_amount,
    coalesce(i.invoiced_amount, 0) - coalesce(c.collected_amount, 0) as billed_minus_collected,
    coalesce(p.partner_charges, 0)              as partner_charges,
    coalesce(r.collection_gap_amount, 0)        as collection_gap_amount,
    coalesce(r.overpaid_amount, 0)              as overpaid_amount,
    coalesce(r.orphan_payment_amount, 0)        as orphan_payment_amount,
    coalesce(r.revenue_leakage_amount, 0)       as revenue_leakage_amount,
    coalesce(r.unbilled_overage_count, 0)       as unbilled_overage_count,
    coalesce(r.batch_mismatch_count, 0)         as batch_mismatch_count,
    coalesce(r.exception_count, 0)              as exception_count,
    coalesce(r.records_checked, 0)              as records_checked,
    coalesce(r.exception_count, 0) / nullif(r.records_checked, 0) as exception_rate
from months m
left join invoiced i    on i.year_month = m.year_month
left join collected c   on c.year_month = m.year_month
left join partner p     on p.year_month = m.year_month
left join recon r       on r.year_month = m.year_month
where m.year_month is not null
