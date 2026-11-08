-- Problems injected into Postgres, grouped by quality dimension (Data Quality Fundamentals).
-- Run once, after the clean seed load. Debezium captures every UPDATE/INSERT as a CDC event.
-- Column names assumed from the seed script; adjust if \d shows different names.
BEGIN;

-- [VALIDITY, auto-fixable] local phone format 06xxxxxxxx -> gate fails, quarantine fixes to +316xxxxxxxx, revalidate passes (20 rows)
UPDATE crm.customers SET msisdn = '06' || substr(msisdn, 5)
WHERE customer_id IN (SELECT customer_id FROM crm.customers WHERE msisdn ~ '^\+316\d{8}$' ORDER BY customer_id LIMIT 20);

-- [VALIDITY, auto-fixable] email in uppercase with trailing space -> trim + lower (20 rows)
UPDATE crm.customers SET email = upper(email) || ' '
WHERE customer_id IN (SELECT customer_id FROM crm.customers WHERE email IS NOT NULL ORDER BY customer_id OFFSET 100 LIMIT 20);

-- [DOMAIN VALUES, reject] status outside ACTIVE/SUSPENDED/CHURNED (10 rows)
UPDATE crm.customers SET status = 'UNKNOWN'
WHERE customer_id IN (SELECT customer_id FROM crm.customers ORDER BY customer_id OFFSET 300 LIMIT 10);

-- [TIMELINESS] created_at in the future (10 rows)
UPDATE crm.customers SET created_at = now() + interval '30 days'
WHERE customer_id IN (SELECT customer_id FROM crm.customers ORDER BY customer_id OFFSET 400 LIMIT 10);

-- [UNIQUENESS] same person inserted twice, same msisdn and email (15 rows)
INSERT INTO crm.customers (first_name,last_name,email,msisdn,city,country,status,plan_id)
SELECT first_name,last_name,email,msisdn,city,country,status,plan_id
FROM crm.customers WHERE customer_id BETWEEN 200 AND 214;

-- [UNIQUENESS, duplicate review] probably the same person, but not an exact copy, so the gate lets them through.
-- 54_silver_customer_duplicates lists them as pairs and a person reviews them in the review app.
-- same phone, different email (5 rows)
INSERT INTO crm.customers (first_name,last_name,email,msisdn,city,country,status,plan_id)
SELECT first_name,last_name,'dup.phone.'||customer_id||'@example.nl',msisdn,city,country,status,plan_id
FROM crm.customers WHERE customer_id BETWEEN 220 AND 224;

-- same email, different phone (5 rows)
INSERT INTO crm.customers (first_name,last_name,email,msisdn,city,country,status,plan_id)
SELECT first_name,last_name,email,'+3161'||lpad(customer_id::text,7,'0'),city,country,status,plan_id
FROM crm.customers WHERE customer_id BETWEEN 230 AND 234;

-- similar name (a typo: last letter of the first name doubled), same city, new phone and email (5 rows)
INSERT INTO crm.customers (first_name,last_name,email,msisdn,city,country,status,plan_id)
SELECT first_name||right(first_name,1),last_name,'dup.name.'||customer_id||'@example.nl',
       '+3162'||lpad(customer_id::text,7,'0'),city,country,status,plan_id
FROM crm.customers WHERE customer_id BETWEEN 240 AND 244;

-- [CONSISTENCY, recon] CRM customers with no billing account (15 rows)
INSERT INTO crm.customers (first_name,last_name,email,msisdn,city,country,status,plan_id)
SELECT 'Orphan','Crm','orphan'||g||'@example.nl','+3160'||lpad(g::text,7,'0'),'Utrecht','NL','ACTIVE',1
FROM generate_series(1,15) g;

-- [CONSISTENCY, recon] billing accounts with no CRM customer (10 rows)
INSERT INTO billing.accounts (msisdn, account_ref)
SELECT '+3169'||lpad(g::text,7,'0'), 'ACC-X'||g FROM generate_series(1,10) g;

-- [ACCURACY, recon] invoice total differs from the sum of its lines (30 rows)
UPDATE billing.invoices SET total_amount = total_amount + 3
WHERE invoice_id IN (SELECT invoice_id FROM billing.invoices ORDER BY invoice_id OFFSET 500 LIMIT 30);

-- [ACCURACY, recon] payment amount differs from invoice total (25 rows)
UPDATE billing.payments SET amount = amount - 2
WHERE payment_id IN (SELECT payment_id FROM billing.payments ORDER BY payment_id OFFSET 800 LIMIT 25);

-- [ACCURACY, recon] billed plan fee differs from the CRM plan price (20 rows)
UPDATE billing.invoice_lines SET amount = amount + 5
WHERE line_id IN (SELECT line_id FROM billing.invoice_lines WHERE line_type = 'PLAN_FEE' ORDER BY line_id OFFSET 1500 LIMIT 20);

-- [DISTRIBUTION] extreme invoice totals, about 100x the normal range (10 rows)
UPDATE billing.invoices SET total_amount = 4500 + (invoice_id % 7)
WHERE invoice_id IN (SELECT invoice_id FROM billing.invoices ORDER BY invoice_id OFFSET 1200 LIMIT 10);

-- [COMPLETENESS] payments with no method (10 rows)
UPDATE billing.payments SET method = NULL
WHERE payment_id IN (SELECT payment_id FROM billing.payments ORDER BY payment_id OFFSET 1500 LIMIT 10);

COMMIT;
