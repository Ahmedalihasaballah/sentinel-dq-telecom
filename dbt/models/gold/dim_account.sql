-- Billing account dimension (SCD2), with the CRM customer it belongs to (from customer_xref).
-- If an account matches more than one customer (is_conflict), the highest-confidence, non-conflicting match wins;
-- the conflict itself is reported by the recon models, not hidden here.
with best_match as (
    select
        cast(billing_account_id as bigint)  as account_id,
        cast(customer_id as bigint)         as customer_id,
        match_method,
        confidence,
        is_conflict,
        row_number() over (
            partition by billing_account_id
            order by is_conflict asc, confidence desc, customer_id
        ) as rn
    from {{ source('silver', 'customer_xref') }}
    where in_crm and in_billing
)

select
    a.dim_billing_account_sk            as account_sk,
    a.account_id,
    a.account_ref,
    m.customer_id,
    coalesce(m.match_method, 'none')    as customer_match_method,
    coalesce(m.confidence, 0.0)         as customer_match_confidence,
    coalesce(m.is_conflict, false)      as customer_match_conflict,
    a.msisdn_hash,
    a.msisdn_masked,
    a.status,
    a.created_at,
    a.updated_at,
    a.valid_from,
    a.valid_to,
    a.is_current,
    row_number() over (partition by a.account_id order by a.valid_from) = 1 as is_first_version
from {{ source('silver', 'dim_billing_account') }} a
left join best_match m
    on m.account_id = a.account_id
   and m.rn = 1
