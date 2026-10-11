-- Grain: one row per payment (billing CDC). Dated by paid_at; account and customer come from the paid invoice.
-- net_collected_amount: PAID counts in, REFUNDED counts out, FAILED counts nothing.
select
    {{ dbt_utils.generate_surrogate_key(['p.payment_id']) }} as payment_sk,
    f.invoice_sk,
    f.account_sk,
    f.customer_sk,
    {{ date_key('p.paid_at') }}                              as date_key,
    p.payment_id,
    p.invoice_id,
    f.account_id,
    f.customer_id,
    p.method,
    p.status,
    p.paid_at,
    p.amount,
    case p.status
        when 'PAID' then p.amount
        when 'REFUNDED' then -p.amount
        else 0
    end                                                      as net_collected_amount,
    1                                                        as payment_count
from {{ source('silver', 'billing_payments') }} p
left join {{ ref('fact_invoice') }} f
    on f.invoice_id = p.invoice_id
