-- Grain: one row per invoice (billing CDC is the system of record; the batch files are checked against it in recon).
-- Account, customer and plan keys point to the versions that were valid when the invoice was issued.
with invoices as (
    select
        invoice_id,
        account_id,
        period_start,
        period_end,
        total_amount,
        status,
        issued_at,
        coalesce(issued_at, cast(period_end as timestamp)) as invoice_ts
    from {{ source('silver', 'billing_invoices') }}
),

lines as (
    select invoice_id, count(*) as line_count, sum(amount) as lines_amount
    from {{ source('silver', 'billing_invoice_lines') }}
    group by invoice_id
)

select
    {{ dbt_utils.generate_surrogate_key(['i.invoice_id']) }} as invoice_sk,
    a.account_sk,
    c.customer_sk,
    p.plan_sk,
    {{ date_key('i.invoice_ts') }}                          as date_key,
    i.invoice_id,
    i.account_id,
    a.customer_id,
    c.plan_id,
    i.period_start,
    i.period_end,
    i.issued_at,
    i.status,
    i.total_amount,
    coalesce(l.lines_amount, 0)                             as lines_amount,
    coalesce(l.line_count, 0)                               as line_count,
    1                                                       as invoice_count
from invoices i
left join {{ ref('dim_account') }} a
    on a.account_id = i.account_id and {{ as_of('a', 'i.invoice_ts') }}
left join {{ ref('dim_customer') }} c
    on c.customer_id = a.customer_id and {{ as_of('c', 'i.invoice_ts') }}
left join {{ ref('dim_plan') }} p
    on p.plan_id = c.plan_id and {{ as_of('p', 'i.invoice_ts') }}
left join lines l
    on l.invoice_id = i.invoice_id
