
    
    

select
    partner_record_id as unique_field,
    count(*) as n_records

from `data_sentinel`.`gold`.`fact_partner_usage`
where partner_record_id is not null
group by partner_record_id
having count(*) > 1


