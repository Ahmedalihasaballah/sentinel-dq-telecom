-- Grain: one row per customer (current version). One place for profile, billing, usage, app and data issues.
-- "Recent" usage means the last 30 days of available CDR data, so a static demo dataset still shows numbers.
with customers as (
    select * from {{ ref('dim_customer') }} where is_current
),

plans as (
    select * from {{ ref('dim_plan') }} where is_current
),

accounts as (
    select customer_id, count(*) as account_count, min(account_ref) as primary_account_ref
    from {{ ref('dim_account') }}
    where is_current and customer_id is not null
    group by customer_id
),

billing as (
    select
        customer_id,
        sum(case when status <> 'CANCELLED' then total_amount else 0 end)  as total_invoiced,
        count(*)                                                            as invoice_count,
        max(issued_at)                                                      as last_invoice_at
    from {{ ref('fact_invoice') }}
    group by customer_id
),

payments as (
    select customer_id, sum(net_collected_amount) as total_collected, max(paid_at) as last_payment_at
    from {{ ref('fact_payment') }}
    group by customer_id
),

balance as (
    select customer_id, sum(greatest(-difference_amount, 0)) as outstanding_amount
    from {{ ref('recon_invoice_vs_payment') }}
    where match_status in ('OPEN', 'UNPAID', 'UNDERPAID', 'PAYMENT_FAILED')
    group by customer_id
),

usage_anchor as (
    select max(event_ts) as max_ts from {{ ref('fact_usage') }}
),

usage as (
    select
        u.customer_id,
        sum(case when u.event_type = 'DATA' then u.data_mb else 0 end) / 1024.0  as data_gb_30d,
        sum(case when u.event_type = 'VOICE' then u.duration_sec else 0 end) / 60.0 as voice_min_30d,
        sum(u.usage_count)                                                         as cdr_count_30d,
        sum(u.dropped_count) / nullif(sum(case when u.event_type = 'VOICE' then 1 else 0 end), 0)
                                                                                   as drop_rate_30d
    from {{ ref('fact_usage') }} u
    cross join usage_anchor x
    where u.event_ts > x.max_ts - interval 30 days
    group by u.customer_id
),

partner as (
    select customer_id, sum(amount) as partner_charges
    from {{ ref('fact_partner_usage') }}
    group by customer_id
),

app as (
    select
        customer_id,
        count(*)                                                        as app_event_count,
        sum(case when event_type = 'crash' then 1 else 0 end)           as app_crash_count,
        max(case when event_type = 'login' then event_ts end)           as last_app_login_at
    from {{ source('silver', 'app_events') }}
    group by customer_id
),

exceptions as (
    select customer_id, count(*) as recon_exception_count
    from {{ ref('recon_results') }}
    where is_exception and customer_id is not null
    group by customer_id
)

select
    c.customer_sk,
    c.customer_id,
    c.first_name_initial,
    c.last_name_initial,
    c.email_masked,
    c.msisdn_masked,
    c.city,
    c.country,
    c.status,
    c.created_at                                    as customer_since,
    c.plan_id,
    p.plan_name,
    p.monthly_fee,
    p.data_gb                                       as plan_data_gb,
    p.voice_minutes                                 as plan_voice_minutes,
    coalesce(a.account_count, 0)                    as account_count,
    a.primary_account_ref,
    coalesce(b.invoice_count, 0)                    as invoice_count,
    coalesce(b.total_invoiced, 0)                   as total_invoiced,
    coalesce(pay.total_collected, 0)                as total_collected,
    coalesce(bal.outstanding_amount, 0)             as outstanding_amount,
    b.last_invoice_at,
    pay.last_payment_at,
    coalesce(u.data_gb_30d, 0)                      as data_gb_30d,
    coalesce(u.voice_min_30d, 0)                    as voice_min_30d,
    coalesce(u.cdr_count_30d, 0)                    as cdr_count_30d,
    u.drop_rate_30d,
    coalesce(pr.partner_charges, 0)                 as partner_charges,
    coalesce(ap.app_event_count, 0)                 as app_event_count,
    coalesce(ap.app_crash_count, 0)                 as app_crash_count,
    ap.last_app_login_at,
    coalesce(e.recon_exception_count, 0)            as recon_exception_count,
    coalesce(bal.outstanding_amount, 0) > 0         as has_open_balance,
    coalesce(a.account_count, 0) = 0                as has_no_billing_account
from customers c
left join plans p           on p.plan_id = c.plan_id
left join accounts a        on a.customer_id = c.customer_id
left join billing b         on b.customer_id = c.customer_id
left join payments pay      on pay.customer_id = c.customer_id
left join balance bal       on bal.customer_id = c.customer_id
left join usage u           on u.customer_id = c.customer_id
left join partner pr        on pr.customer_id = c.customer_id
left join app ap            on ap.customer_id = c.customer_id
left join exceptions e      on e.customer_id = c.customer_id
