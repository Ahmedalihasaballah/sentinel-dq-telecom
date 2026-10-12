
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`relationships_fact_app_events_75ba3c751cfc7fcd0a75e96c83c14952`
    
      
    ) dbt_internal_test