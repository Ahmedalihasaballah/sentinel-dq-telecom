
    
    

select
    cdr_id as unique_field,
    count(*) as n_records

from `data_sentinel`.`gold`.`fact_usage`
where cdr_id is not null
group by cdr_id
having count(*) > 1


