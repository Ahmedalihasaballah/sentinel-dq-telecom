
    
    

with child as (
    select plan_key as from_field
    from `data_sentinel`.`gold`.`dim_customer`
    where plan_key is not null
),

parent as (
    select plan_key as to_field
    from `data_sentinel`.`gold`.`dim_plan`
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null


