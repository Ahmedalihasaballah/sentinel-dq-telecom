-- Plan dimension (SCD2): price and allowances per version.
select
    dim_plan_sk         as plan_sk,
    plan_id,
    plan_name,
    monthly_fee,
    data_gb,
    voice_minutes,
    valid_from,
    valid_to,
    is_current,
    row_number() over (partition by plan_id order by valid_from) = 1 as is_first_version
from {{ source('silver', 'dim_plan') }}
