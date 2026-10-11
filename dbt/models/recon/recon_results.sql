-- Grain: one row per checked record per reconciliation check. The common shape of every recon_* model,
-- so Gold (fact_reconciliation) and the incident list read one table.
{% set recon_models = ['recon_invoice_vs_payment', 'recon_batch_vs_cdc', 'recon_usage_vs_billing', 'recon_crm_vs_network'] %}

{% for m in recon_models %}
select
    cast(check_name as string)              as check_name,
    cast(record_id as string)               as record_id,
    cast(invoice_id as bigint)              as invoice_id,
    cast(payment_id as bigint)              as payment_id,
    cast(account_id as bigint)              as account_id,
    cast(customer_id as bigint)             as customer_id,
    cast(msisdn_hash as string)             as msisdn_hash,
    cast(recon_date as date)                as recon_date,
    cast(expected_amount as decimal(12, 2)) as expected_amount,
    cast(actual_amount as decimal(12, 2))   as actual_amount,
    cast(difference_amount as decimal(12, 2)) as difference_amount,
    cast(match_status as string)            as match_status,
    cast(is_exception as boolean)           as is_exception,
    cast(detail as string)                  as detail
from {{ ref(m) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
