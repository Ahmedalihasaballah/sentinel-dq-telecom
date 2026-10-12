
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`not_null_fact_payment_customer_key`
    
      
    ) dbt_internal_test