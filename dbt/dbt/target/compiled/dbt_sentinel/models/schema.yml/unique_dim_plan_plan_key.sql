
    
    

select
    plan_key as unique_field,
    count(*) as n_records

from `data_sentinel`.`gold`.`dim_plan`
where plan_key is not null
group by plan_key
having count(*) > 1


