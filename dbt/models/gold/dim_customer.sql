-- Customer dimension (SCD2). History is built in Silver (40_silver_scd2); Gold exposes it with a clean contract.
-- Facts pick the version valid at the event time: event_ts >= valid_from and event_ts < valid_to.
select
    dim_customer_sk     as customer_sk,
    customer_id,
    first_name_initial,
    last_name_initial,
    email_hash,
    email_masked,
    msisdn_hash,
    msisdn_masked,
    city,
    country,
    status,
    plan_id,
    created_at,
    updated_at,
    valid_from,
    valid_to,
    is_current,
    row_number() over (partition by customer_id order by valid_from) = 1 as is_first_version
from {{ source('silver', 'dim_customer') }}
