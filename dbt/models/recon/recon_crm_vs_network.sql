-- Grain: one row per MSISDN seen on the network. Does network activity agree with CRM and billing?
--   UNKNOWN_MSISDN            traffic from a number that CRM has never had
--   ACTIVITY_WHILE_INACTIVE   traffic while the customer was SUSPENDED or CHURNED (at the time of the event)
--   NO_BILLING_ACCOUNT        known customer with traffic, but no billing account to charge it to
with cdr_customer as (
    select
        n.cdr_id,
        n.msisdn_hash,
        n.event_ts,
        c.customer_id,
        c.status
    from {{ source('silver', 'network_cdr') }} n
    left join {{ ref('dim_customer') }} c
        on c.msisdn_hash = n.msisdn_hash and {{ as_of('c', 'n.event_ts') }}
    qualify row_number() over (
        partition by n.cdr_id
        order by case when c.status = 'ACTIVE' then 0 else 1 end, c.customer_id desc
    ) = 1
),

per_msisdn as (
    select
        msisdn_hash,
        max_by(customer_id, event_ts)                                           as customer_id,
        max_by(status, event_ts)                                                as status_at_last_event,
        count(*)                                                                as cdr_count,
        sum(case when status in ('SUSPENDED', 'CHURNED') then 1 else 0 end)     as inactive_cdr_count,
        min(event_ts)                                                           as first_event_ts,
        max(event_ts)                                                           as last_event_ts
    from cdr_customer
    group by msisdn_hash
),

accounts as (
    select msisdn_hash, account_id
    from {{ ref('dim_account') }}
    where is_current
    qualify row_number() over (partition by msisdn_hash order by account_id desc) = 1
),

classified as (
    select
        m.*,
        a.account_id,
        case
            when m.customer_id is null      then 'UNKNOWN_MSISDN'
            when m.inactive_cdr_count > 0   then 'ACTIVITY_WHILE_INACTIVE'
            when a.account_id is null       then 'NO_BILLING_ACCOUNT'
            else 'MATCHED'
        end as match_status
    from per_msisdn m
    left join accounts a
        on a.msisdn_hash = m.msisdn_hash
)

select
    'crm_vs_network'                    as check_name,
    msisdn_hash                         as record_id,
    cast(null as bigint)                as invoice_id,
    cast(null as bigint)                as payment_id,
    account_id,
    customer_id,
    msisdn_hash,
    cast(last_event_ts as date)         as recon_date,
    cast(null as decimal(12, 2))        as expected_amount,
    cast(null as decimal(12, 2))        as actual_amount,
    cast(null as decimal(12, 2))        as difference_amount,
    match_status,
    match_status <> 'MATCHED'           as is_exception,
    concat(cdr_count, ' CDRs, ', inactive_cdr_count, ' while inactive, last status ',
           coalesce(status_at_last_event, 'unknown'))   as detail,
    status_at_last_event,
    cdr_count,
    inactive_cdr_count,
    first_event_ts,
    last_event_ts
from classified
