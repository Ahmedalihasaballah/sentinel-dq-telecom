
    
    

select
    customer_id as unique_field,
    count(*) as n_records

from `data_sentinel`.`gold`.`mart_customer_360`
where customer_id is not null
group by customer_id
having count(*) > 1


