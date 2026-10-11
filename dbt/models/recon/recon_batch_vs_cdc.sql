-- Grain: one row per invoice id and per payment id seen in the monthly batch files or in billing CDC.
-- CDC is the system of record (expected); the file is what was exported (actual).
-- CDC records outside the period the files cover are left out, so a missing month of files is not reported per record.
with f_inv as (
    select invoice_id, account_ref, msisdn_hash, period_start, total_amount, status
    from {{ source('silver', 'invoices_file') }}
),

c_inv as (
    select i.invoice_id, i.account_id, i.period_start, i.total_amount, i.status,
           a.account_ref, a.customer_id, a.msisdn_hash
    from {{ source('silver', 'billing_invoices') }} i
    left join {{ ref('dim_account') }} a
        on a.account_id = i.account_id and a.is_current
),

inv_cover as (
    select min(period_start) as lo, max(period_start) as hi from f_inv
),

invoices as (
    select
        'batch_vs_cdc_invoice'                              as check_name,
        cast(coalesce(f.invoice_id, c.invoice_id) as string) as record_id,
        coalesce(f.invoice_id, c.invoice_id)                as invoice_id,
        cast(null as bigint)                                as payment_id,
        c.account_id,
        c.customer_id,
        coalesce(c.msisdn_hash, f.msisdn_hash)              as msisdn_hash,
        coalesce(f.period_start, c.period_start)            as recon_date,
        c.total_amount                                      as expected_amount,
        f.total_amount                                      as actual_amount,
        f.total_amount - c.total_amount                     as difference_amount,
        case
            when c.invoice_id is null                                              then 'MISSING_IN_CDC'
            when f.invoice_id is null                                              then 'MISSING_IN_FILE'
            when abs(c.total_amount - f.total_amount) > {{ var('recon_tolerance') }} then 'AMOUNT_MISMATCH'
            when c.account_ref <> f.account_ref                                    then 'ACCOUNT_MISMATCH'
            when c.status <> f.status                                              then 'STATUS_MISMATCH'
            else 'MATCHED'
        end                                                 as match_status,
        concat_ws('; ',
            concat('cdc account ', c.account_ref),
            concat('file account ', f.account_ref),
            concat('cdc status ', c.status),
            concat('file status ', f.status))               as detail
    from f_inv f
    full outer join c_inv c
        on c.invoice_id = f.invoice_id
    cross join inv_cover
    where f.invoice_id is not null
       or c.period_start between inv_cover.lo and inv_cover.hi
),

f_pay as (
    select payment_id, invoice_id, amount, status, paid_at
    from {{ source('silver', 'payments_file') }}
),

c_pay as (
    select p.payment_id, p.invoice_id, p.amount, p.status, p.paid_at,
           i.account_id, i.customer_id, i.msisdn_hash
    from {{ source('silver', 'billing_payments') }} p
    left join c_inv i
        on i.invoice_id = p.invoice_id
),

pay_cover as (
    select cast(min(paid_at) as date) as lo, cast(max(paid_at) as date) as hi from f_pay
),

payments as (
    select
        'batch_vs_cdc_payment'                              as check_name,
        cast(coalesce(f.payment_id, c.payment_id) as string) as record_id,
        coalesce(c.invoice_id, f.invoice_id)                as invoice_id,
        coalesce(f.payment_id, c.payment_id)                as payment_id,
        c.account_id,
        c.customer_id,
        c.msisdn_hash,
        cast(coalesce(f.paid_at, c.paid_at) as date)        as recon_date,
        c.amount                                            as expected_amount,
        f.amount                                            as actual_amount,
        f.amount - c.amount                                 as difference_amount,
        case
            when c.payment_id is null                                  then 'MISSING_IN_CDC'
            when f.payment_id is null                                  then 'MISSING_IN_FILE'
            when abs(c.amount - f.amount) > {{ var('recon_tolerance') }} then 'AMOUNT_MISMATCH'
            when c.invoice_id <> f.invoice_id                          then 'INVOICE_MISMATCH'
            when c.status <> f.status                                  then 'STATUS_MISMATCH'
            else 'MATCHED'
        end                                                 as match_status,
        concat_ws('; ',
            concat('cdc invoice ', c.invoice_id),
            concat('file invoice ', f.invoice_id),
            concat('cdc status ', c.status),
            concat('file status ', f.status))               as detail
    from f_pay f
    full outer join c_pay c
        on c.payment_id = f.payment_id
    cross join pay_cover
    where f.payment_id is not null
       or cast(c.paid_at as date) between pay_cover.lo and pay_cover.hi
)

-- STATUS_MISMATCH alone is not an exception: the file is a month-end snapshot and CDC has moved on since.
select *, match_status not in ('MATCHED', 'STATUS_MISMATCH') as is_exception from invoices
union all
select *, match_status not in ('MATCHED', 'STATUS_MISMATCH') as is_exception from payments
