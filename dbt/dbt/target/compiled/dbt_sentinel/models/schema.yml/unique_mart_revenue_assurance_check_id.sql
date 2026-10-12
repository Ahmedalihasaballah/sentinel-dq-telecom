
    
    

select
    check_id as unique_field,
    count(*) as n_records

from `data_sentinel`.`gold`.`mart_revenue_assurance`
where check_id is not null
group by check_id
having count(*) > 1


