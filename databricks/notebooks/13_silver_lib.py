# Databricks notebook source
# Shared helpers for the Silver phase. The notebooks load it with:   %run ./13_silver_lib
#
#   PII masking      one salted hash (joinable across tables) plus a masked display value; the raw value is not kept
#   SCD2             version history built from the real change time of the source (Debezium ts_ms), loaded with MERGE
#   watermarks       incremental loading: only events newer than the last run are processed
#   breaker check    a manual run of a Silver notebook refuses to start while a critical incident is open
#   integrity checks every SCD2 table is tested after loading (one current row per key, no gaps, no overlaps)

# COMMAND ----------

# MAGIC %run ./11_dq_lib

# COMMAND ----------

T_WM = f"{CATALOG}.monitoring.silver_watermarks"
HIGH_DATE = "9999-12-31 00:00:00"                      # valid_to of the current version

# raw personal data column -> kind of masking. Raw columns are dropped in Silver.
PII_COLUMNS = {"msisdn": "msisdn", "email": "email", "first_name": "name", "last_name": "name"}
_salt_cache = {}


def pii_salt():
    if "v" not in _salt_cache:
        try:
            _salt_cache["v"] = dbutils.secrets.get("datasentinel", "pii_salt")
        except Exception:
            _salt_cache["v"] = "dev-only-salt"
            print("WARNING: secret datasentinel/pii_salt not found, using a development salt")
    return _salt_cache["v"]


def mask_pii(df, protected=()):
    """Replace raw personal data with <col>_hash / <col>_masked. Columns in `protected` (keys) are left as they are."""
    salt = pii_salt()
    for col in list(df.columns):
        kind = PII_COLUMNS.get(col.lower())
        if not kind or col in protected:
            continue
        v = F.col(col)
        if kind == "msisdn":
            norm = F.regexp_replace(F.trim(v), r"[\s\-()]", "")
            df = (df.withColumn("msisdn_hash", F.sha2(F.concat(F.lit(salt), norm), 256))
                    .withColumn("msisdn_masked", F.when(norm.isNotNull() & (F.length(norm) > 8),
                                F.concat(F.substring(norm, 1, 5), F.lit("****"), F.substring(norm, -3, 3)))))
        elif kind == "email":
            e = F.lower(F.trim(v))
            df = (df.withColumn("email_hash", F.sha2(F.concat(F.lit(salt), e), 256))
                    .withColumn("email_masked", F.when(e.contains("@"),
                                F.concat(F.substring(e, 1, 1), F.lit("***@"), F.split(e, "@").getItem(1)))))
        else:
            df = df.withColumn(f"{col}_initial", F.when(F.length(F.trim(v)) > 0,
                                                        F.concat(F.upper(F.substring(F.trim(v), 1, 1)), F.lit("."))))
        df = df.drop(col)
    return df


# ---------------------------------------------------------------- contracts, columns, breaker

def dataset_key(c):
    """Business key of a dataset: the CDC key, or the keys of its unique rule."""
    s = c["source"]
    if s["kind"] == "cdc":
        return list(s["key"])
    for r in c.get("rules", []):
        if r.get("type") == "unique":
            return list(r["keys"])
    raise ValueError(f"{c['dataset']}: the contract needs a CDC key or a unique rule to build Silver")


def assert_columns(df, needed, where):
    missing = [x for x in needed if x not in df.columns]
    if missing:
        raise Exception(f"{where}: columns not found {missing}. Columns present: {df.columns}")


def assert_breaker_closed(datasets, severities=("critical",)):
    q = (spark.table(T_INCIDENTS).filter("status = 'OPEN'").filter(F.col("severity").isin(list(severities)))
         .filter(F.col("dataset").isin(list(datasets))))
    n = q.count()
    if n:
        display(q.select("opened_at", "dataset", "check_name", "severity", "scope", "description"))
        raise Exception(f"CIRCUIT BREAKER OPEN: {n} blocking incident(s) for {list(datasets)}. Fix them, rerun the gate, then retry.")


# ---------------------------------------------------------------- watermarks (incremental loading)

def get_wm(name):
    spark.sql(f"CREATE TABLE IF NOT EXISTS {T_WM} (name STRING, watermark BIGINT, updated_at TIMESTAMP)")
    r = spark.table(T_WM).filter(F.col("name") == name).first()
    return None if r is None else r["watermark"]


def set_wm(name, value):
    if value is None:
        return
    spark.sql(f"""MERGE INTO {T_WM} t USING (SELECT '{name}' AS name, CAST({int(value)} AS BIGINT) AS watermark,
                  current_timestamp() AS updated_at) s ON t.name = s.name
                  WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")


# ---------------------------------------------------------------- SCD2

def build_versions(events, existing, keys, tracked, sk_name, ts_col="_ts_ms"):
    """Pure DataFrame logic (no writes). events: change events with keys, tracked, _ts_ms, _offset, _row_id.
    existing: the current SCD2 table or None. All existing versions of the affected keys take part, so the result is
    the same whether an event arrives once or ten times (job retries are safe) and back-dated events slot in correctly.
    Returns the version rows to MERGE: new versions plus existing versions whose valid_to or is_current changed.
    Two different states at exactly the same millisecond: the one loaded first wins."""
    high = F.to_timestamp(F.lit(HIGH_DATE))
    ev = (events.withColumn("valid_from", F.expr(f"timestamp_millis({ts_col})"))
                .withColumn("attr_hash", F.sha2(F.to_json(F.struct(*[F.col(c) for c in tracked])), 256))
                .withColumn("src_row_id", F.col("_row_id")))
    w0 = Window.partitionBy(*keys, "valid_from").orderBy(F.col("_offset").desc_nulls_last(), F.col("_row_id").desc())
    ev = ev.withColumn("_rn", F.row_number().over(w0)).filter("_rn = 1").drop("_rn")
    cols = [*keys, *tracked, "valid_from", "attr_hash", "src_row_id"]
    ev = ev.select(*cols, F.lit(False).alias("_is_seed"))

    if existing is not None:
        seeds = (existing.join(ev.select(*keys).distinct(), keys, "left_semi")
                         .select(*cols, F.lit(True).alias("_is_seed")))
        ev = ev.unionByName(seeds)
        wd = Window.partitionBy(*keys, "valid_from").orderBy(F.col("_is_seed").desc())
        ev = ev.withColumn("_rn", F.row_number().over(wd)).filter("_rn = 1").drop("_rn")

    w = Window.partitionBy(*keys).orderBy("valid_from", F.col("_is_seed").desc())
    kept = (ev.withColumn("_prev", F.lag("attr_hash").over(w))
              .filter(F.col("_prev").isNull() | (F.col("_prev") != F.col("attr_hash"))))
    w2 = Window.partitionBy(*keys).orderBy("valid_from")
    return (kept.withColumn("valid_to", F.coalesce(F.lead("valid_from").over(w2), high))
                .withColumn("is_current", F.col("valid_to") == high)
                .withColumn(sk_name, F.xxhash64(*[F.col(k) for k in keys], F.col("valid_from")))
                .withColumn("_loaded_at", F.current_timestamp())
                .drop("_prev", "_is_seed"))


def scd2_upsert(events, target, keys, tracked, sk_name, full_rebuild=False):
    exists = (not full_rebuild) and spark.catalog.tableExists(target)
    versions = build_versions(events, spark.table(target) if exists else None, keys, tracked, sk_name)
    if not exists:
        versions.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(target)
        return "created" if not full_rebuild else "rebuilt"
    (DeltaTable.forName(spark, target).alias("t")
        .merge(versions.alias("s"), f"t.{sk_name} = s.{sk_name}")
        .whenMatchedUpdate(condition="t.valid_to <> s.valid_to OR t.is_current <> s.is_current",
                           set={"valid_to": "s.valid_to", "is_current": "s.is_current"})
        .whenNotMatchedInsertAll().execute())
    return "merged"


def scd2_integrity(df, keys):
    """Returns (keys with more than one current row, version chains with a gap or overlap). Both must be 0."""
    dup_current = df.filter("is_current").groupBy(*keys).count().filter("count > 1").count()
    w = Window.partitionBy(*keys).orderBy("valid_from")
    broken = (df.withColumn("_prev_to", F.lag("valid_to").over(w))
                .filter(F.col("_prev_to").isNotNull() & (F.col("_prev_to") != F.col("valid_from"))).count())
    return dup_current, broken
