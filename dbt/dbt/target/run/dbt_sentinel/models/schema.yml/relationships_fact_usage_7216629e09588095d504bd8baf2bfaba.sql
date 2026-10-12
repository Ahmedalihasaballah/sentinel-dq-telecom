
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`relationships_fact_usage_7216629e09588095d504bd8baf2bfaba`
    
      
    ) dbt_internal_test