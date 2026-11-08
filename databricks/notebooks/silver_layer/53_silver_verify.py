# Databricks notebook source
# MAGIC %run ./49_silver_lib

# COMMAND ----------

# VERIFY the Silver layer. Run it after 50, 51, 52 and 54. Nothing here changes data.
checks = []
def check(area, name, ok, detail="", warn=False):
    checks.append((area, name, "PASS" if ok else ("WARN" if warn else "FAIL"), str(detail)))

def q(sql):
    return spark.sql(sql).collect()[0][0]

# COMMAND ----------
for t in SILVER_TABLES:
    ex = spark.catalog.tableExists(t)
    check("tables", f"{t.split('.')[-1]} exists and has rows", ex and spark.table(t).count() > 0,
          spark.table(t).count() if ex else "missing")
old = [t.split('.')[-1] for t in OLD_TABLES if spark.catalog.tableExists(t)]
check("tables", "old dim_* / fact_* tables are gone from Silver (they belong to Gold)", not old, old)

# COMMAND ----------
# 1) SCD2 shape
dc, dp = T_CUSTOMER_HISTORY, T_PLAN_HISTORY
dup_cur = q(f"SELECT count(*) FROM (SELECT customer_id FROM {dc} WHERE is_current GROUP BY 1 HAVING count(*) > 1)")
check("scd2", "customer_history: exactly one current row per customer", dup_cur == 0, f"{dup_cur} customers with 2+ current rows")
overlap = q(f"""SELECT count(*) FROM {dc} a JOIN {dc} b ON a.customer_id = b.customer_id AND a.version < b.version
                AND a.valid_to > b.valid_from""")
check("scd2", "customer_history: versions of a customer never overlap", overlap == 0, overlap)
bad_range = q(f"SELECT count(*) FROM {dc} WHERE valid_from >= valid_to")
check("scd2", "customer_history: valid_from < valid_to", bad_range == 0, bad_range)
dup_ver = q(f"SELECT count(*) FROM (SELECT customer_id, version FROM {dc} GROUP BY 1, 2 HAVING count(*) > 1)")
check("scd2", "customer_history: (customer_id, version) is unique", dup_ver == 0, dup_ver)
dup_plan = q(f"SELECT count(*) FROM (SELECT plan_id FROM {dp} WHERE is_current GROUP BY 1 HAVING count(*) > 1)")
check("scd2", "plan_history: exactly one current row per plan", dup_plan == 0, dup_plan)

# COMMAND ----------
# 2) every customer / plan that passed the gate is in the history
v_cust = validated("crm_customers").filter("_op IN ('r','c','u')").select("customer_id").distinct().count()
d_cust = q(f"SELECT count(DISTINCT customer_id) FROM {dc}")
check("coverage", "customer_history covers every customer that passed the quality gate", v_cust == d_cust, f"validated {v_cust:,}; history {d_cust:,}")
v_plan = validated("crm_plans").filter("_op IN ('r','c','u')").select("plan_id").distinct().count()
d_plan = q(f"SELECT count(DISTINCT plan_id) FROM {dp}")
check("coverage", "plan_history covers every plan that passed the quality gate", v_plan == d_plan, f"validated {v_plan:,}; history {d_plan:,}")

# COMMAND ----------
# 3) phone numbers: present everywhere they are needed to link usage, invoices and accounts to a customer
for t in [T_CUSTOMER_HISTORY, T_NETWORK_CDR, T_PARTNER_USAGE, T_INVOICE_FILE, T_ACCOUNT]:
    bad = q(f"SELECT count(*) FROM {t} WHERE msisdn IS NULL OR msisdn = ''")
    check("phone", f"{t.split('.')[-1]}: every row has a phone number", bad == 0, bad)

# COMMAND ----------
# 4) clean tables: one row per key, row count = distinct keys that passed the gate
def clean_check(table, key, dataset, label, cdc=False):
    t = spark.table(table); n = t.count()
    v = validated(dataset)
    if cdc:
        v = v.filter("_op IN ('r','c','u')")
    expect = v.select(*key).distinct().count()
    check("clean", f"{label}: one row per key", n == t.select(*key).distinct().count(), f"{n:,} rows")
    check("clean", f"{label}: row count = distinct keys that passed the gate", n == expect, f"silver {n:,}; validated {expect:,}")

clean_check(T_ACCOUNT, ["account_id"], "billing_accounts", "account", True)
clean_check(T_INVOICE, ["invoice_id"], "billing_invoices", "invoice", True)
clean_check(T_INVOICE_LINE, ["line_id"], "billing_invoice_lines", "invoice_line", True)
clean_check(T_PAYMENT, ["payment_id"], "billing_payments", "payment", True)
clean_check(T_INVOICE_FILE, ["invoice_id"], "invoices_file", "invoice_file")
clean_check(T_PAYMENT_FILE, ["payment_id"], "payments_file", "payment_file")
clean_check(T_NETWORK_CDR, ["cdr_id"], "network_cdr", "network_cdr")
clean_check(T_APP_EVENT, ["event_id"], "app_events", "app_event")
clean_check(T_PARTNER_USAGE, ["partner_record_id"], "partner_usage", "partner_usage")

# COMMAND ----------
# 5) customer_xref
x = {r[0]: r[1] for r in spark.sql(f"SELECT match_status, count(*) FROM {T_XREF} GROUP BY 1").collect()}
check("xref", "xref has MATCHED rows", x.get("MATCHED", 0) > 0, x)
check("xref", "customers without a billing account are visible (CRM_ONLY, injected: 15)", x.get("CRM_ONLY", 0) > 0, x.get("CRM_ONLY", 0), warn=True)
check("xref", "accounts without a customer are visible (BILLING_ONLY, injected: 10)", x.get("BILLING_ONLY", 0) > 0, x.get("BILLING_ONLY", 0), warn=True)
dup_c = q(f"SELECT count(*) FROM (SELECT customer_id FROM {T_XREF} WHERE customer_id IS NOT NULL GROUP BY 1 HAVING count(*) > 1)")
check("xref", "a customer appears once in the xref", dup_c == 0, dup_c, warn=True)

# COMMAND ----------
# 6) customer duplicate candidates (54)
dd = T_CUSTOMER_DUPES
bad_order = q(f"SELECT count(*) FROM {dd} WHERE customer_id_a >= customer_id_b")
check("dupes", "each pair is stored lowest customer_id first (no self pairs)", bad_order == 0, bad_order)
dup_pair = q(f"SELECT count(*) FROM (SELECT customer_id_a, customer_id_b FROM {dd} GROUP BY 1, 2 HAVING count(*) > 1)")
check("dupes", "each pair is stored once", dup_pair == 0, dup_pair)
no_reason = q(f"SELECT count(*) FROM {dd} WHERE is_active AND (reasons IS NULL OR size(reasons) = 0)")
check("dupes", "every active pair has at least one reason", no_reason == 0, no_reason)
bad_status = q(f"SELECT count(*) FROM {dd} WHERE review_status NOT IN ('PENDING', 'SAME_PERSON', 'NOT_SAME')")
check("dupes", "review_status is PENDING, SAME_PERSON or NOT_SAME", bad_status == 0, bad_status)
r = {row[0]: row[1] for row in spark.sql(f"SELECT reason, count(*) FROM {dd} LATERAL VIEW explode(reasons) e AS reason WHERE is_active GROUP BY 1").collect()}
check("dupes", "same phone / different email pairs are found (injected: 5)", r.get("SAME_PHONE_DIFF_EMAIL", 0) > 0, r, warn=True)
check("dupes", "same email / different phone pairs are found (injected: 5)", r.get("SAME_EMAIL_DIFF_PHONE", 0) > 0, r, warn=True)
check("dupes", "similar name / same city pairs are found (injected: 5)", r.get("SIMILAR_NAME_SAME_CITY", 0) > 0, r, warn=True)

# COMMAND ----------
out = spark.createDataFrame(checks, "area string, `check` string, status string, detail string")
display(out.orderBy(F.when(F.col("status") == "FAIL", 0).when(F.col("status") == "WARN", 1).otherwise(2), "area"))
n_fail = sum(1 for c in checks if c[2] == "FAIL"); n_warn = sum(1 for c in checks if c[2] == "WARN")
print(f"\n{len(checks)} checks: {len(checks) - n_fail - n_warn} PASS, {n_warn} WARN, {n_fail} FAIL")
print("SILVER OK" if n_fail == 0 else "SILVER HAS FAILURES - fix the FAIL rows above")
