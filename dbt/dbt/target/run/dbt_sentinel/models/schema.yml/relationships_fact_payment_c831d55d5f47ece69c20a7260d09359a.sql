
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`relationships_fact_payment_c831d55d5f47ece69c20a7260d09359a`
    
      
    ) dbt_internal_test