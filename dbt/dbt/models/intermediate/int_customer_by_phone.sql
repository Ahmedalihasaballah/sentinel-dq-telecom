-- HELPER: find the customer behind a phone number.
-- Network usage, invoices and partner usage only know the (hashed) phone number, not the customer id.
-- If two customers share one phone number (a duplicate in the CRM), we pick the one with the lowest customer_id,
-- so every phone number points to exactly ONE customer and the facts never get duplicate rows.

select
    c.customer_key,
    c.customer_id,
    c.msisdn_hash,
    c.valid_from,
    c.valid_to
from {{ ref('dim_customer') }} c
join (
    select msisdn_hash, min(customer_id) as customer_id
    from {{ ref('dim_customer') }}
    where customer_key <> -1
    group by msisdn_hash
) chosen
    on  c.msisdn_hash = chosen.msisdn_hash
    and c.customer_id = chosen.customer_id
where c.customer_key <> -1
