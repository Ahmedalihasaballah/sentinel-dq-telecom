-- Grain: one row per invoice line. Dimension keys are inherited from the invoice it belongs to.
select
    {{ dbt_utils.generate_surrogate_key(['l.line_id']) }} as line_sk,
    f.invoice_sk,
    f.customer_sk,
    f.account_sk,
    f.plan_sk,
    f.date_key,
    l.line_id,
    l.invoice_id,
    f.period_start,
    l.line_type,
    l.description,
    l.amount,
    1 as line_count
from {{ source('silver', 'billing_invoice_lines') }} l
left join {{ ref('fact_invoice') }} f
    on f.invoice_id = l.invoice_id
