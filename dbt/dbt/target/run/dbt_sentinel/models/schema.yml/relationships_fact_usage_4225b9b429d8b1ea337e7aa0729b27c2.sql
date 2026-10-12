
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`relationships_fact_usage_4225b9b429d8b1ea337e7aa0729b27c2`
    
      
    ) dbt_internal_test