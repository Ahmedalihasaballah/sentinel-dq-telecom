# Databricks notebook source
# SILVER, part 2: facts and events. Every validated dataset that is not an SCD2 dimension becomes silver.<dataset>:
#   typed (done by the gate), deduplicated on its business key, personal data masked, loaded with MERGE.
# The business key comes from the contract: the CDC key, or the keys of the unique rule. Latest version of a key wins.
# MERGE only touches rows that are new or changed (different _row_id), so reruns are safe and cheap.

# COMMAND ----------

# MAGIC %run ./13_silver_lib

# COMMAND ----------

dbutils.widgets.text("datasets", "all")
dbutils.widgets.text("enforce_breaker", "true")
SCD2_DIMS = {"crm_customers", "crm_plans", "billing_accounts"}
contracts = load_contracts()
selected = dbutils.widgets.get("datasets").strip()
todo = [n for n in contracts if n not in SCD2_DIMS and (selected in ("", "all") or n in [x.strip() for x in selected.split(",")])]

if dbutils.widgets.get("enforce_breaker").lower() == "true":
    assert_breaker_closed(todo)

run_id, results, summary = new_run_id(), [], []
for name in todo:
    c = contracts[name]
    keys = dataset_key(c)
    src = spark.table(validated_table(c))
    assert_columns(src, keys + ["_row_id"], validated_table(c))
    target = f"{CATALOG}.silver.{name}"

    names = [x["name"] for x in c["columns"]]
    tech = [x for x in ["_file_name", "_ts_ms", "_offset", "_row_id", "_flags", "_dq_fixed", "_contract_version"] if x in src.columns]
    df = mask_pii(src.select(*names, *tech), protected=keys)

    order = [F.col(x).desc_nulls_last() for x in ["_ts_ms", "_file_name", "_offset"] if x in df.columns] + [F.col("_row_id").desc()]
    w = Window.partitionBy(*keys).orderBy(*order)
    latest = (df.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")
                .withColumn("_silver_loaded_at", F.current_timestamp()))

    rows_in = src.count()
    if not spark.catalog.tableExists(target):
        latest.write.format("delta").saveAsTable(target)
        mode = "created"
    else:
        cond = " AND ".join(f"t.`{k}` = s.`{k}`" for k in keys)
        (DeltaTable.forName(spark, target).alias("t").merge(latest.alias("s"), cond)
            .whenMatchedUpdateAll(condition="t._row_id <> s._row_id")
            .whenNotMatchedInsertAll().execute())
        mode = "merged"

    out = spark.table(target)
    rows_out = out.count()
    distinct_keys = out.select(*keys).distinct().count()
    dups = rows_out - distinct_keys
    removed = rows_in - rows_out
    results.append(result_row(run_id, name, "silver_unique_key", "SILVER_UNIQUE", "uniqueness", "silver", rows_out, dups,
                              "PASS" if dups == 0 else "FAIL", "high" if dups else "info",
                              f"{rows_out:,} rows, {dups} duplicate keys", c["version"]))
    summary.append((name, rows_in, rows_out, removed, dups, mode))
    print(f"{name}: {mode}, {rows_in:,} validated rows -> {rows_out:,} in silver ({removed:,} older versions or duplicates dropped)")

save_results(results)
display(spark.createDataFrame(summary, "dataset string, validated_rows long, silver_rows long, dropped long, duplicate_keys long, outcome string")
        .orderBy("dataset"))
