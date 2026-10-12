-- Dashboard 1: rows in quarantine by dataset and status (REJECTED, PENDING_FIX, FIXED_PENDING_REVALIDATION, ...).
with q as (
    




    
        
        
            
        
    
        
        
            
        
    
        
        
            
        
    
        
        
            
        
    
        
        
            
        
    
        
        
            
        
    
        
        
            
        
    
        
        
            
        
    
        
        
            
        
    
        
        
            
        
    
        
        
            
        
    



    select 'crm_customers' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`crm_customers` union all select 'crm_plans' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`crm_plans` union all select 'billing_accounts' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`billing_accounts` union all select 'billing_invoices' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`billing_invoices` union all select 'billing_invoice_lines' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`billing_invoice_lines` union all select 'billing_payments' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`billing_payments` union all select 'invoices_file' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`invoices_file` union all select 'payments_file' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`payments_file` union all select 'network_cdr' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`network_cdr` union all select 'app_events' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`app_events` union all select 'partner_usage' as dataset, _quarantine_status as quarantine_status, _quarantined_at as quarantined_at, _failure_reasons as failure_reasons from `data_sentinel`.`quarantine`.`partner_usage`



)
select dataset, quarantine_status, count(*) as rows, min(quarantined_at) as oldest_quarantined_at
from q
group by dataset, quarantine_status