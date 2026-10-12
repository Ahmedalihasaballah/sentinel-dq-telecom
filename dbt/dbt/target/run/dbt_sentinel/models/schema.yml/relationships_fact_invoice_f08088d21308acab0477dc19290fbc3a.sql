
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`relationships_fact_invoice_f08088d21308acab0477dc19290fbc3a`
    
      
    ) dbt_internal_test