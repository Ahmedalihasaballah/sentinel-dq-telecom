
    
    

with all_values as (

    select
        source as value_field,
        count(*) as n_records

    from `data_sentinel`.`gold`.`fact_invoice`
    group by source

)

select *
from all_values
where value_field not in (
    'billing_db','billing_file'
)


