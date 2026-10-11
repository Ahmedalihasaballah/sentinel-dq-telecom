-- Calendar dimension, one row per day between vars date_start and date_end.
with days as (
    select explode(sequence(to_date('{{ var("date_start") }}'), to_date('{{ var("date_end") }}'), interval 1 day)) as date_day
)

select
    cast(date_format(date_day, 'yyyyMMdd') as int)  as date_key,
    date_day,
    year(date_day)                                  as year,
    quarter(date_day)                               as quarter,
    month(date_day)                                 as month,
    date_format(date_day, 'MMMM')                   as month_name,
    cast(date_format(date_day, 'yyyyMM') as int)    as year_month,
    weekofyear(date_day)                            as week_of_year,
    day(date_day)                                   as day_of_month,
    dayofweek(date_day)                             as day_of_week,      -- 1 = Sunday
    date_format(date_day, 'EEEE')                   as day_name,
    dayofweek(date_day) in (1, 7)                   as is_weekend,
    date_day = last_day(date_day)                   as is_month_end
from days
