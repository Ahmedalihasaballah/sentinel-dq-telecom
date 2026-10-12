
  
    
        create or replace table `data_sentinel`.`gold`.`mart_revenue_assurance_trend`
      
      
    using delta
  
      
      
      
      
      
      
      
      as
      -- Dashboard 2: EUR at risk per check and run, to see if leakage grows or shrinks.
select run_id, run_ts, check_id, check_name, rows_mismatched, amount_at_risk_eur, status
from `data_sentinel`.`monitoring`.`recon_results`
  