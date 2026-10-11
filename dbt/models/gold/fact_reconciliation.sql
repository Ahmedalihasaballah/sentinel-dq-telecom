-- Grain: one row per reconciliation record (every check, matched or not). Filter is_exception for the work list.
-- Account and customer point to their current version: a reconciliation result is about today's state.
select
    {{ dbt_utils.generate_surrogate_key(['r.check_name', 'r.record_id']) }} as recon_fact_sk,
    fi.invoice_sk,
    fp.payment_sk,
    a.account_sk,
    c.customer_sk,
    {{ date_key('r.recon_date') }}                                          as date_key,
    r.check_name,
    r.record_id,
    r.invoice_id,
    r.payment_id,
    r.account_id,
    r.customer_id,
    r.match_status,
    r.is_exception,
    r.expected_amount,
    r.actual_amount,
    r.difference_amount,
    r.detail,
    1                                                                       as record_count
from {{ ref('recon_results') }} r
left join {{ ref('fact_invoice') }} fi
    on fi.invoice_id = r.invoice_id
left join {{ ref('fact_payment') }} fp
    on fp.payment_id = r.payment_id
left join {{ ref('dim_account') }} a
    on a.account_id = r.account_id and a.is_current
left join {{ ref('dim_customer') }} c
    on c.customer_id = r.customer_id and c.is_current
