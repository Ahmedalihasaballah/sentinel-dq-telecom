-- Grain: one row per incident (data quality and reconciliation), dated by when it was opened.
select
    {{ dbt_utils.generate_surrogate_key(['incident_source', 'incident_id']) }} as incident_sk,
    {{ date_key('opened_at') }}                                                as date_key,
    case
        when incident_source = 'reconciliation'                             then 'Reconciliation'
        when dataset like 'crm%'                                            then 'CRM'
        when dataset like 'billing%' or dataset in ('invoices_file', 'payments_file') then 'Billing'
        when dataset like 'network%'                                        then 'Network'
        when dataset like 'partner%'                                        then 'Partner'
        when dataset like 'app%'                                            then 'App'
        else 'Other'
    end                                                                        as source_system,
    incident_id,
    incident_source,
    dataset,
    check_name,
    pillar,
    severity,
    status,
    status = 'OPEN'                                                            as is_open,
    opened_at,
    closed_at,
    round((unix_timestamp(coalesce(closed_at, current_timestamp())) - unix_timestamp(opened_at)) / 3600.0, 1)
                                                                               as hours_open,
    description,
    affected_records,
    amount_at_risk,
    1                                                                          as incident_count
from {{ ref('incidents') }}
