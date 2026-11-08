# Databricks notebook source
# MAGIC %run ./49_silver_lib

# COMMAND ----------

# CUSTOMER DUPLICATE CANDIDATES: pairs of customers that are probably the same person. A person reviews every pair
# in the review app (page "Duplicate customers"); the decision is recorded only, customers are never merged.
# Exact duplicates (same phone AND same email) are already rejected by the gate rule CUST_DUPLICATE; this notebook
# finds the partial matches that rule cannot see. crm.customers has no address, so the city is used in its place.
#
#   reason                   weight   rule
#   SAME_PHONE_SAME_EMAIL     0.9     safety net, the gate should already have rejected these
#   SAME_PHONE_DIFF_EMAIL     0.6     same phone, email different or missing
#   SAME_EMAIL_DIFF_PHONE     0.5     same email (ignoring case), phone different
#   SAME_NAME_SAME_CITY       0.3     same normalized full name (lower case, no accents) and same city
#   SIMILAR_NAME_SAME_CITY    0.2     full names 1 or 2 letters apart (levenshtein) and same city
#   score = sum of the weights of the pair's reasons, at most 1.0
#
# Input : silver.crm_customers_validated, newest version of each customer
# Output: silver.customer_duplicate_candidates, one row per pair (customer_id_a < customer_id_b), with real names,
#         phone numbers and emails so the reviewer can compare them
# Rerun : MERGE on pair_id, so a reviewer's decision is kept. A pair no longer found gets is_active = false.
#         A reviewed pair whose reasons change goes back to PENDING (the evidence changed).
# Same rules as src/sentinel_dq/quality/duplicates.py (unit-tested twin). Run after 50.

# COMMAND ----------
WEIGHTS = {"SAME_PHONE_SAME_EMAIL": 0.9, "SAME_PHONE_DIFF_EMAIL": 0.6, "SAME_EMAIL_DIFF_PHONE": 0.5,
           "SAME_NAME_SAME_CITY": 0.3, "SIMILAR_NAME_SAME_CITY": 0.2}
MAX_NAME_DISTANCE = 2
ACCENTS, PLAIN = "àáâäèéêëìíîïòóôöùúûüçñ", "aaaaeeeeiiiioooouuuucn"

# COMMAND ----------
# 1) current customers: newest event per customer, deleted customers left out
cust = latest_per_key(validated("crm_customers"), ["customer_id"]).filter("_op IN ('r', 'c', 'u')")
name = F.regexp_replace(F.translate(F.lower(F.trim(F.concat_ws(" ", "first_name", "last_name"))), ACCENTS, PLAIN),
                        r"\s+", " ")
city = F.lower(F.trim("city"))
c = cust.select(
    F.col("customer_id").cast("bigint").alias("customer_id"),
    F.trim("msisdn").alias("msisdn"),
    F.lower(F.trim("email")).alias("email"),
    F.when(F.length(name) > 0, name).alias("name_norm"),           # for the comparison only, not saved
    F.when(F.length(city) > 0, city).alias("city_norm"),
    F.concat_ws(" ", "first_name", "last_name").alias("customer_name"),
    "city").cache()

# COMMAND ----------
# 2) candidate pairs: only customers that share a phone, an email, or a city with a close name are compared
a, b = c.alias("a"), c.alias("b")


def pairs_on(cond):
    return (a.join(b, cond & (F.col("a.customer_id") < F.col("b.customer_id")))
             .select(F.col("a.customer_id").alias("customer_id_a"), F.col("b.customer_id").alias("customer_id_b")))


candidates = (pairs_on(F.col("a.msisdn") == F.col("b.msisdn"))
              .union(pairs_on(F.col("a.email") == F.col("b.email")))
              .union(pairs_on((F.col("a.city_norm") == F.col("b.city_norm"))
                              & (F.abs(F.length("a.name_norm") - F.length("b.name_norm")) <= MAX_NAME_DISTANCE)
                              & (F.levenshtein("a.name_norm", "b.name_norm") <= MAX_NAME_DISTANCE)))
              .distinct())

# COMMAND ----------
# 3) reasons and score for each pair
side_a = c.select([F.col(x).alias(f"{x}_a") for x in c.columns])
side_b = c.select([F.col(x).alias(f"{x}_b") for x in c.columns])
p = candidates.join(side_a, "customer_id_a").join(side_b, "customer_id_b")

same_phone = F.coalesce(F.col("msisdn_a") == F.col("msisdn_b"), F.lit(False))
same_email = F.coalesce(F.col("email_a") == F.col("email_b"), F.lit(False))   # missing email = different
same_city = F.coalesce(F.col("city_norm_a") == F.col("city_norm_b"), F.lit(False))
dist = F.levenshtein("name_norm_a", "name_norm_b")                                     # null when a name is missing
reasons = F.filter(F.array(
    F.when(same_phone & same_email, F.lit("SAME_PHONE_SAME_EMAIL")),
    F.when(same_phone & ~same_email, F.lit("SAME_PHONE_DIFF_EMAIL")),
    F.when(same_email & ~same_phone, F.lit("SAME_EMAIL_DIFF_PHONE")),
    F.when(same_city & (dist == 0), F.lit("SAME_NAME_SAME_CITY")),
    F.when(same_city & (dist > 0) & (dist <= MAX_NAME_DISTANCE), F.lit("SIMILAR_NAME_SAME_CITY")),
), lambda r: r.isNotNull())
weight = F.create_map(*[x for k, v in WEIGHTS.items() for x in (F.lit(k), F.lit(float(v)))])
score = F.least(F.lit(1.0), F.round(F.aggregate(F.transform("reasons", lambda r: weight[r]), F.lit(0.0),
                                                lambda acc, x: acc + x), 2))

found = (p.withColumn("reasons", reasons)
          .filter(F.size("reasons") > 0)
          .withColumn("score", score)
          .select(F.concat_ws("-", "customer_id_a", "customer_id_b").alias("pair_id"),
                  "customer_id_a", "customer_id_b", "reasons", "score",
                  "customer_name_a", "customer_name_b", "msisdn_a", "msisdn_b",
                  "email_a", "email_b", "city_a", "city_b",
                  F.current_timestamp().alias("detected_at")))

# COMMAND ----------
# 4) MERGE into the candidates table, keeping the review decisions
# one-time migration: an older version of this table stored masked columns; rebuild it with the real values
if spark.catalog.tableExists(T_CUSTOMER_DUPES) and "name_masked_a" in spark.table(T_CUSTOMER_DUPES).columns:
    spark.sql(f"DROP TABLE {T_CUSTOMER_DUPES}")
    print("dropped the old masked version of", T_CUSTOMER_DUPES)
spark.sql(f"""CREATE TABLE IF NOT EXISTS {T_CUSTOMER_DUPES} (
    pair_id STRING, customer_id_a BIGINT, customer_id_b BIGINT, reasons ARRAY<STRING>, score DOUBLE,
    customer_name_a STRING, customer_name_b STRING, msisdn_a STRING, msisdn_b STRING,
    email_a STRING, email_b STRING, city_a STRING, city_b STRING,
    is_active BOOLEAN, first_detected_at TIMESTAMP, last_detected_at TIMESTAMP,
    review_status STRING, reviewed_by STRING, reviewed_at TIMESTAMP, review_note STRING) USING DELTA""")

info = ["reasons", "score", "customer_name_a", "customer_name_b", "msisdn_a", "msisdn_b",
        "email_a", "email_b", "city_a", "city_b"]
refresh = {**{x: f"s.{x}" for x in info}, "is_active": "true", "last_detected_at": "s.detected_at"}
reasons_changed = "NOT (array_sort(t.reasons) <=> array_sort(s.reasons))"
(DeltaTable.forName(spark, T_CUSTOMER_DUPES).alias("t")
    .merge(found.alias("s"), "t.pair_id = s.pair_id")
    .whenMatchedUpdate(condition=f"t.review_status <> 'PENDING' AND {reasons_changed}",
                       set={**refresh, "review_status": "'PENDING'", "reviewed_by": "NULL", "reviewed_at": "NULL",
                            "review_note": "concat('reopened, reasons were ', array_join(t.reasons, ', '))"})
    .whenMatchedUpdate(set=refresh)
    .whenNotMatchedInsert(values={**{x: f"s.{x}" for x in info}, "pair_id": "s.pair_id",
                                  "customer_id_a": "s.customer_id_a", "customer_id_b": "s.customer_id_b",
                                  "is_active": "true", "first_detected_at": "s.detected_at",
                                  "last_detected_at": "s.detected_at", "review_status": "'PENDING'"})
    .whenNotMatchedBySourceUpdate(condition="t.is_active", set={"is_active": "false"})
    .execute())
c.unpersist()

# COMMAND ----------
d = spark.table(T_CUSTOMER_DUPES)
print(f"{T_CUSTOMER_DUPES}: {d.filter('is_active').count():,} active pairs, {d.count():,} rows in total")
display(d.filter("is_active").select(F.explode("reasons").alias("reason")).groupBy("reason").count().orderBy("reason"))
display(d.filter("is_active").groupBy("review_status").count().orderBy("review_status"))
display(d.filter("is_active").orderBy(F.col("score").desc(), "customer_id_a").limit(20))
