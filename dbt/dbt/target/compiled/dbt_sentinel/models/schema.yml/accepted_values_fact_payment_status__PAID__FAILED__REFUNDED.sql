
    
    

with all_values as (

    select
        status as value_field,
        count(*) as n_records

    from `data_sentinel`.`gold`.`fact_payment`
    group by status

)

select *
from all_values
where value_field not in (
    'PAID','FAILED','REFUNDED'
)


