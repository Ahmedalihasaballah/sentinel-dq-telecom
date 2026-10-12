
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
        select *
        from `data_sentinel`.`gold_tests`.`relationships_fact_partner_usa_ad8e2ec9c3852b2ec50b5280140254bf`
    
      
    ) dbt_internal_test