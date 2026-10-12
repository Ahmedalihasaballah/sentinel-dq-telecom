
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`accepted_values_fact_payment_status__paid__failed__refunded`
    
      
    ) dbt_internal_test