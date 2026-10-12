
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`relationships_fact_app_events_84df046047115e02feb6be409a5aaf29`
    
      
    ) dbt_internal_test