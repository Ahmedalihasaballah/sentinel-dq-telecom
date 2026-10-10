# Databricks notebook source
# SILVER, part 3: customer_xref, the identity map between systems.
#   CRM customer_id  <->  billing account id        (join on the hashed MSISDN, or on customer_id if billing carries it)
# One row per matched pair, plus one row for every customer without an account and every account without a customer.
# These orphan rows feed the reconciliation stage. Rebuilt on every run because it is derived from the current dimensions.

# COMMAND ----------

# MAGIC %run ./13_silver_lib

# COMMAND ----------

dbutils.widgets.text("enforce_breaker", "true")
contracts = load_contracts()
if dbutils.widgets.get("enforce_breaker").lower() == "true":
    assert_breaker_closed(["crm_customers", "billing_accounts"])

cust_key = dataset_key(contracts["crm_customers"])[0]
acc_key = dataset_key(contracts["billing_accounts"])[0]
crm = spark.table(f"{CATALOG}.silver.dim_customer").filter("is_current")
bill = spark.table(f"{CATALOG}.silver.dim_billing_account").filter("is_current")
assert_columns(crm, [cust_key, "msisdn_hash"], "dim_customer")
assert_columns(bill, [acc_key], "dim_billing_account")

crm_s = crm.select(F.col(cust_key).alias("customer_id"), "msisdn_hash")
bill_s = bill.select(F.col(acc_key).alias("billing_account_id"),
                     (F.col("msisdn_hash") if "msisdn_hash" in bill.columns else F.lit(None).cast("string")).alias("msisdn_hash"),
                     (F.col(cust_key).cast("string") if cust_key in bill.columns else F.lit(None).cast("string")).alias("bill_customer_id"))

pairs = []
if cust_key in bill.columns:
    pairs.append(crm_s.join(bill_s, crm_s["customer_id"].cast("string") == bill_s["bill_customer_id"])
                      .select("customer_id", "billing_account_id", F.lit("customer_id").alias("match_method"), F.lit(1.0).alias("confidence")))
if "msisdn_hash" in bill.columns:
    pairs.append(crm_s.join(bill_s, "msisdn_hash")
                      .select("customer_id", "billing_account_id", F.lit("msisdn").alias("match_method"), F.lit(0.9).alias("confidence")))
if not pairs:
    raise Exception("dim_billing_account has neither msisdn_hash nor the CRM key, so there is nothing to match on")

matched = pairs[0]
for p in pairs[1:]:
    matched = matched.unionByName(p)
w = Window.partitionBy("customer_id", "billing_account_id").orderBy(F.col("confidence").desc())
matched = matched.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")

wc = Window.partitionBy("customer_id")
wa = Window.partitionBy("billing_account_id")
matched = (matched.withColumn("is_conflict", (F.approx_count_distinct("billing_account_id").over(wc) > 1) |
                                              (F.approx_count_distinct("customer_id").over(wa) > 1))
                  .withColumn("in_crm", F.lit(True)).withColumn("in_billing", F.lit(True)))

only_crm = (crm_s.join(matched.select("customer_id").distinct(), "customer_id", "left_anti")
                 .select("customer_id", F.lit(None).cast("string").alias("billing_account_id"), F.lit("none").alias("match_method"),
                         F.lit(0.0).alias("confidence"), F.lit(False).alias("is_conflict"), F.lit(True).alias("in_crm"), F.lit(False).alias("in_billing")))
only_bill = (bill_s.join(matched.select("billing_account_id").distinct(), "billing_account_id", "left_anti")
                   .select(F.lit(None).cast("string").alias("customer_id"), "billing_account_id", F.lit("none").alias("match_method"),
                           F.lit(0.0).alias("confidence"), F.lit(False).alias("is_conflict"), F.lit(False).alias("in_crm"), F.lit(True).alias("in_billing")))

cols = ["customer_id", "billing_account_id", "match_method", "confidence", "is_conflict", "in_crm", "in_billing"]
xref = (matched.select(*[F.col(x).cast("string") if x in ("customer_id", "billing_account_id") else F.col(x) for x in cols])
        .unionByName(only_crm.select(*[F.col(x).cast("string") if x in ("customer_id", "billing_account_id") else F.col(x) for x in cols]))
        .unionByName(only_bill.select(*[F.col(x).cast("string") if x in ("customer_id", "billing_account_id") else F.col(x) for x in cols]))
        .withColumn("_built_at", F.current_timestamp()))
xref.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.silver.customer_xref")

# COMMAND ----------

x = spark.table(f"{CATALOG}.silver.customer_xref")
n_crm, n_bill = crm.count(), bill.count()
orphan_crm = x.filter("in_crm AND NOT in_billing").count()
orphan_bill = x.filter("in_billing AND NOT in_crm").count()
conflicts = x.filter("is_conflict").count()
run_id = new_run_id()
v = contracts["crm_customers"]["version"]
save_results([
    result_row(run_id, "customer_xref", "xref_orphans", "XREF_CRM_NO_ACCOUNT", "consistency", "crm", n_crm, orphan_crm,
               "PASS" if orphan_crm == 0 else "WARN", "medium" if orphan_crm else "info", f"{orphan_crm:,} CRM customers without a billing account", v),
    result_row(run_id, "customer_xref", "xref_orphans", "XREF_ACCOUNT_NO_CRM", "consistency", "billing", n_bill, orphan_bill,
               "PASS" if orphan_bill == 0 else "WARN", "medium" if orphan_bill else "info", f"{orphan_bill:,} billing accounts without a CRM customer", v),
    result_row(run_id, "customer_xref", "xref_conflicts", "XREF_CONFLICT", "consistency", "all", n_crm, conflicts,
               "PASS" if conflicts == 0 else "FAIL", "high" if conflicts else "info", f"{conflicts:,} pairs where one side matches several records", v),
])
print(f"matched {x.filter('in_crm AND in_billing').count():,}; customers without account {orphan_crm:,}; accounts without customer {orphan_bill:,}; conflicts {conflicts:,}")
display(x.groupBy("match_method", "in_crm", "in_billing", "is_conflict").count().orderBy("match_method"))
