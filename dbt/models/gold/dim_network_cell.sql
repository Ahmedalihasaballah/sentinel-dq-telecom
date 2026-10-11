-- Network cell dimension. The CDRs only carry cell_id (no location/region source yet), so this is a type 1 list of
-- the cells seen on the network. Becomes SCD2 once a cell reference feed exists.
select
    {{ dbt_utils.generate_surrogate_key(['cell_id']) }} as cell_sk,
    cell_id,
    min(event_ts)   as first_seen_at,
    max(event_ts)   as last_seen_at,
    count(*)        as cdr_count
from {{ source('silver', 'network_cdr') }}
group by cell_id
