
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`assert_customer_versions_do_not_overlap`
    
      
    ) dbt_internal_test