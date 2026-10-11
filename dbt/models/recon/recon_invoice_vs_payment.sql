-- Grain: one row per invoice, plus one row per payment that points to an invoice billing does not know.
-- Compares what was invoiced (expected) with what was collected (actual = PAID - REFUNDED).
-- difference_amount = actual - expected: negative means under-collected.
with invoices as (
    select
        invoice_id,
        account_id,
        total_amount,
        status,
        coalesce(cast(issued_at as date), period_end) as recon_date
    from {{ source('silver', 'billing_invoices') }}
),

payments as (
    select payment_id, invoice_id, amount, status, paid_at
    from {{ source('silver', 'billing_payments') }}
),

collected as (
    select
        invoice_id,
        count(*)                                                        as payment_count,
        sum(case when status = 'PAID' then amount else 0 end)
          - sum(case when status = 'REFUNDED' then amount else 0 end)   as collected_amount,
        sum(case when status = 'FAILED' then 1 else 0 end)              as failed_count,
        max(paid_at)                                                    as last_paid_at
    from payments
    group by invoice_id
),

accounts as (
    select account_id, customer_id, msisdn_hash
    from {{ ref('dim_account') }}
    where is_current
),

classified as (
    select
        i.*,
        coalesce(c.payment_count, 0)    as payment_count,
        coalesce(c.collected_amount, 0) as collected_amount,
        c.last_paid_at,
        case
            when i.status = 'CANCELLED' and coalesce(c.collected_amount, 0) > 0         then 'PAID_CANCELLED'
            when i.status = 'CANCELLED'                                                 then 'CANCELLED'
            when abs(i.total_amount - coalesce(c.collected_amount, 0)) <= {{ var('recon_tolerance') }} then 'MATCHED'
            when coalesce(c.collected_amount, 0) = 0 and i.status = 'ISSUED'            then 'OPEN'
            when coalesce(c.collected_amount, 0) = 0 and coalesce(c.failed_count, 0) > 0 then 'PAYMENT_FAILED'
            when coalesce(c.collected_amount, 0) = 0                                    then 'UNPAID'
            when c.collected_amount < i.total_amount                                    then 'UNDERPAID'
            else 'OVERPAID'
        end as match_status
    from invoices i
    left join collected c
        on c.invoice_id = i.invoice_id
)

select
    'invoice_vs_payment'                        as check_name,
    cast(k.invoice_id as string)                as record_id,
    k.invoice_id,
    cast(null as bigint)                        as payment_id,
    k.account_id,
    a.customer_id,
    a.msisdn_hash,
    k.recon_date,
    k.total_amount                              as expected_amount,
    k.collected_amount                          as actual_amount,
    k.collected_amount - k.total_amount         as difference_amount,
    k.match_status,
    k.match_status not in ('MATCHED', 'CANCELLED', 'OPEN') as is_exception,
    k.status                                    as invoice_status,
    k.payment_count,
    k.last_paid_at,
    concat('invoice status ', k.status, ', ', k.payment_count, ' payment(s)') as detail
from classified k
left join accounts a
    on a.account_id = k.account_id

union all

select
    'invoice_vs_payment',
    concat('PAY-', p.payment_id),
    p.invoice_id,
    p.payment_id,
    cast(null as bigint),
    cast(null as bigint),
    cast(null as string),
    cast(p.paid_at as date),
    0,
    p.amount,
    p.amount,
    'ORPHAN_PAYMENT',
    true,
    cast(null as string),
    1,
    p.paid_at,
    concat('payment ', p.status, ' for invoice ', p.invoice_id, ' which is not in billing')
from payments p
left anti join invoices i
    on i.invoice_id = p.invoice_id
