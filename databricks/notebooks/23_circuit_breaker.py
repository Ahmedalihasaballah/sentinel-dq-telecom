# Databricks notebook source
# CIRCUIT BREAKER (Data Quality Fundamentals: stop bad data before it spreads).
# Run after the monitors and before any Silver or Gold task. If a blocking incident is OPEN for the
# datasets this stage reads, the notebook raises, the job fails, and every downstream task is skipped.
# Incidents resolve themselves when the gate or a monitor passes again, which closes the breaker.

# COMMAND ----------

# MAGIC %run ./11_dq_lib

# COMMAND ----------

dbutils.widgets.text("datasets", "all")                  # comma separated dataset names, or all
dbutils.widgets.text("block_severities", "critical")     # e.g. critical or critical,high
selected = dbutils.widgets.get("datasets").strip()
wanted = None if selected in ("", "all") else [x.strip() for x in selected.split(",")]
severities = [x.strip() for x in dbutils.widgets.get("block_severities").split(",") if x.strip()]

q = spark.table(T_INCIDENTS).filter("status = 'OPEN'").filter(F.col("severity").isin(severities))
if wanted:
    q = q.filter(F.col("dataset").isin(wanted))
blocking = q.select("opened_at", "dataset", "check_name", "severity", "scope", "description", "impacted") \
            .orderBy("opened_at").collect()

run_id = new_run_id()
n = len(blocking)
save_results([result_row(run_id, "pipeline", "circuit_breaker", "__BREAKER__", "validity", ",".join(wanted or ["all"]),
                         1, 1 if n else 0, "FAIL" if n else "PASS", "critical" if n else "info",
                         f"{n} blocking incident(s) open" if n else "no blocking incidents", "n/a")])

if n:
    display(spark.createDataFrame(blocking))
    raise Exception(f"CIRCUIT BREAKER OPEN: {n} {'/'.join(severities)} incident(s) must be resolved before Silver runs")
print("circuit breaker closed: downstream tasks may run")
