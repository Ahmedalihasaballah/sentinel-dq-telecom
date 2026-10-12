
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`accepted_values_dim_customer_455d0059ed1afe8410815d29d0f7b77d`
    
      
    ) dbt_internal_test