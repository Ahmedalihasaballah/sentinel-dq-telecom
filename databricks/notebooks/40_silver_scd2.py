# Databricks notebook source
# SILVER, part 1: slowly changing dimensions (SCD type 2) from the validated CDC tables.
#   dim_customer, dim_plan, dim_billing_account
# Each change of a tracked attribute closes the old row (valid_to) and opens a new one (valid_from = the real change time
# from Debezium, not the time this notebook ran). Loading is incremental: only events newer than the stored watermark are
# read, then MERGEd. Personal data is replaced by hashes and masked values before it is stored.
# Late events older than the watermark are not handled by the incremental path: run with full_rebuild = true (replay).

# COMMAND ----------

# MAGIC %run ./13_silver_lib

# COMMAND ----------

dbutils.widgets.text("full_rebuild", "false")
dbutils.widgets.text("enforce_breaker", "true")
FULL = dbutils.widgets.get("full_rebuild").lower() == "true"

SCD2_DIMS = {"crm_customers": "dim_customer", "crm_plans": "dim_plan", "billing_accounts": "dim_billing_account"}
contracts = load_contracts()
todo = {d: dim for d, dim in SCD2_DIMS.items() if d in contracts}
print("skipping (no contract):", [d for d in SCD2_DIMS if d not in contracts])

if dbutils.widgets.get("enforce_breaker").lower() == "true":
    assert_breaker_closed(todo.keys())

run_id, results, summary = new_run_id(), [], []
for dataset, dim in todo.items():
    c = contracts[dataset]
    keys = dataset_key(c)
    target = f"{CATALOG}.silver.{dim}"
    src = spark.table(validated_table(c))
    assert_columns(src, keys + ["_ts_ms", "_offset", "_row_id"], validated_table(c))

    wm_name = f"silver.{dim}"
    wm = None if FULL else get_wm(wm_name)
    ev = src if wm is None else src.filter(F.col("_ts_ms") > wm)
    n_new = ev.count()
    if n_new == 0 and spark.catalog.tableExists(target) and not FULL:
        print(f"{dim}: no new events")
        summary.append((dim, 0, "no change"))
        continue

    names = [x["name"] for x in c["columns"]]
    ev = mask_pii(ev.select(*names, "_ts_ms", "_offset", "_row_id"), protected=keys)
    tracked = [x for x in ev.columns if x not in set(keys) | {"_ts_ms", "_offset", "_row_id"}]
    new_wm = ev.agg(F.max("_ts_ms")).first()[0]

    mode = scd2_upsert(ev, target, keys, tracked, f"{dim}_sk", full_rebuild=FULL)
    set_wm(wm_name, new_wm)

    d = spark.table(target)
    dup_current, broken = scd2_integrity(d, keys)
    total, current = d.count(), d.filter("is_current").count()
    results.append(result_row(run_id, dataset, "scd2_integrity", "SCD2_ONE_CURRENT", "consistency", dim, current, dup_current,
                              "PASS" if dup_current == 0 else "FAIL", "high" if dup_current else "info",
                              f"{current:,} current rows, {dup_current} keys with more than one current row", c["version"]))
    results.append(result_row(run_id, dataset, "scd2_integrity", "SCD2_NO_GAPS", "consistency", dim, total, broken,
                              "PASS" if broken == 0 else "FAIL", "high" if broken else "info",
                              f"{total:,} versions, {broken} gaps or overlaps", c["version"]))
    summary.append((dim, n_new, f"{mode}: {total:,} versions, {current:,} current"))
    print(f"{dim}: {mode}, {n_new:,} events read, {total:,} versions, {current:,} current, integrity problems {dup_current + broken}")

save_results(results)
display(spark.createDataFrame(summary, "dimension string, events_read long, outcome string"))
