
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`accepted_values_fact_invoice_source__billing_db__billing_file`
    
      
    ) dbt_internal_test