
  
    
        create or replace table `data_sentinel`.`gold`.`mart_dq_trend`
      
      
    using delta
  
      
      
      
      
      
      
      
      
      as
      -- Dashboard 1: pass rate per day, dataset and quality dimension (gate rules only).
select
    to_date(run_ts) as run_date,
    dataset,
    dimension,
    sum(rows_checked) as rows_checked,
    sum(rows_failed) as rows_failed,
    1 - sum(rows_failed) / nullif(sum(rows_checked), 0) as pass_rate
from `data_sentinel`.`monitoring`.`dq_results`
where check_name = 'gate_rule'
group by to_date(run_ts), dataset, dimension
  