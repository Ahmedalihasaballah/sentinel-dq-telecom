
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`relationships_dim_customer_plan_key__plan_key__ref_dim_plan_`
    
      
    ) dbt_internal_test