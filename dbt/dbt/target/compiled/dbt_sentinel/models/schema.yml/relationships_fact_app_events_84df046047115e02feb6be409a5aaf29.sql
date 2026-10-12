
    
    

with child as (
    select customer_key as from_field
    from `data_sentinel`.`gold`.`fact_app_events`
    where customer_key is not null
),

parent as (
    select customer_key as to_field
    from `data_sentinel`.`gold`.`dim_customer`
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null


