# Feature 4: Duplicate customers

## Requirement

| # | Feature | Description |
|---|---|---|
| 4 | Duplicate customers | Finds customers who are probably **the same person**: same phone, similar name, same address, same email with a different phone, same phone with a different email. It outputs a **list of pairs** with the **reason** they matched. **A person** reviews the pairs. |

## Decisions

| Question | Decision |
|---|---|
| Address | `crm.customers` has **no address column**, so **`city`** is used in its place |
| Gold / Power BI | No. The **review app** is enough for now |
| When the reviewer says "same person" | The decision is **recorded only**. Customers are **not merged** |
| PII | Name, email and phone number are shown **as they are** (no hashing, no masking) |

## The big picture

```
Postgres ──► Bronze ──► Quality gate ──► Silver ──► 54 notebook ──► candidates table ──► Review app ──► decision + log
 (Step 1)                                (Step 2)    (Step 3)         (Step 3.4)            (Step 7)
                         Airflow (Step 4) · Verify (Step 5) · Python twin + tests (Step 6) · Docs (Step 8)
```

## Reasons and weights

| Reason | Weight | Rule |
|---|---|---|
| `SAME_PHONE_SAME_EMAIL` | 0.9 | Safety net. The gate rule `CUST_DUPLICATE` should already have rejected these |
| `SAME_PHONE_DIFF_EMAIL` | 0.6 | Same phone; email is different or missing |
| `SAME_EMAIL_DIFF_PHONE` | 0.5 | Same email (case-insensitive); phone is different |
| `SAME_NAME_SAME_CITY` | 0.3 | Same normalized full name and same city |
| `SIMILAR_NAME_SAME_CITY` | 0.2 | Full names 1 or 2 letters apart (Levenshtein ≤ 2) and same city |

**Score** = the sum of the weights of the pair's reasons, at most **1.0**. Example: same phone + similar name = 0.6 + 0.2 = **0.8**.

---

## Step 0: Analysis (no code change)

**Input:** the repo: the contracts, the Postgres schema and the Silver notebooks.
**Output:** the plan, plus two findings:

1. The gate rule `CUST_DUPLICATE` in `contract/crm_customers.yaml` already **rejects** exact duplicates (same phone **and** same email). This feature therefore covers the **partial matches** that rule cannot see.
2. The seed data has 1,000 customers but only about 20 last names and 15 cities. Name + city alone produces **about 150 weak pairs**, plus 105 pairs from the injected `Orphan Crm` rows. That is why a name-only match gets a low weight (0.2 or 0.3).

**Code change:** none.

---

## Step 1: Test data

**File:** `generators/postgres_seed/inject_problems.sql` (**modified**)

**Input:** the customers already in `crm.customers` after the seed load.
**Output:** 15 new customers, each one "similar" to an existing customer:

| Group | What was done | Expected reason |
|---|---|---|
| 220-224 | Same phone, new email | `SAME_PHONE_DIFF_EMAIL` |
| 230-234 | Same email, new phone | `SAME_EMAIL_DIFF_PHONE` |
| 240-244 | Typo in the first name (`Daan` becomes `Daann`), same city, new phone and email | `SIMILAR_NAME_SAME_CITY` |

**Added:**

```sql
-- [UNIQUENESS, duplicate review] probably the same person, but not an exact copy, so the gate lets them through.
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
```

---

## Step 2: Register the table name

**File:** `databricks/notebooks/silver_layer/49_silver_lib.py` (**modified**)

**Input:** none. This is the shared library that every Silver notebook loads with `%run`.
**Output:** the constant `T_CUSTOMER_DUPES`. Every notebook uses the same name, and because it is in `SILVER_TABLES`, the verify notebook (Step 5) checks that the table exists and has rows.

**Change:**

```python
T_PARTNER_USAGE = f"{SILVER}.partner_usage"
+T_CUSTOMER_DUPES = f"{SILVER}.customer_duplicate_candidates"   # built by 54, reviewed in the review app
 SILVER_TABLES = [T_CUSTOMER_HISTORY, T_PLAN_HISTORY, T_XREF, T_ACCOUNT, T_INVOICE, T_INVOICE_LINE, T_PAYMENT,
-                 T_INVOICE_FILE, T_PAYMENT_FILE, T_NETWORK_CDR, T_APP_EVENT, T_PARTNER_USAGE]
+                 T_INVOICE_FILE, T_PAYMENT_FILE, T_NETWORK_CDR, T_APP_EVENT, T_PARTNER_USAGE, T_CUSTOMER_DUPES]
```

---

## Step 3: The new notebook (the core of the feature)

**File:** `databricks/notebooks/silver_layer/54_silver_customer_duplicates.py` (**new**)

**Input:** `data_sentinel.silver.crm_customers_validated`, the customers that passed the quality gate.
**Output:** `data_sentinel.silver.customer_duplicate_candidates`, one row per pair.

### 3.0 Settings

```python
WEIGHTS = {"SAME_PHONE_SAME_EMAIL": 0.9, "SAME_PHONE_DIFF_EMAIL": 0.6, "SAME_EMAIL_DIFF_PHONE": 0.5,
           "SAME_NAME_SAME_CITY": 0.3, "SIMILAR_NAME_SAME_CITY": 0.2}
MAX_NAME_DISTANCE = 2                     # similar name = at most 2 letters different
ACCENTS, PLAIN = "àáâäèéêëìíîïòóôöùúûüçñ", "aaaaeeeeiiiioooouuuucn"
```

### 3.1 Prepare the customers

**Input:** every CDC event of the customers that passed the gate.
**Output:** a DataFrame `c` with one row per **current** customer, normalized:

| Field | Normalization |
|---|---|
| phone | trimmed |
| email | trimmed and lower case |
| name | lower case, accents removed, extra spaces removed (`"  Zoë  van Dijk"` becomes `"zoe van dijk"`) |
| city | trimmed and lower case |

```python
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
```

### 3.2 Candidate pairs (blocking)

**Input:** `c`
**Output:** `candidates`, containing only `(customer_id_a, customer_id_b)`.

**Why blocking?** Comparing every customer with every other customer would be 1,000 × 1,000 = one million comparisons. Instead, only customers that **share something** are compared: a phone, an email, or a city plus a close name.
**Why `a < b`?** So that each pair appears **once** and a customer is never compared with itself.

```python
a, b = c.alias("a"), c.alias("b")

def pairs_on(cond):
    return (a.join(b, cond & (F.col("a.customer_id") < F.col("b.customer_id")))
             .select(F.col("a.customer_id").alias("customer_id_a"), F.col("b.customer_id").alias("customer_id_b")))

candidates = (pairs_on(F.col("a.msisdn") == F.col("b.msisdn"))                    # same phone
              .union(pairs_on(F.col("a.email") == F.col("b.email")))              # same email
              .union(pairs_on((F.col("a.city_norm") == F.col("b.city_norm"))       # same city + close name
                              & (F.abs(F.length("a.name_norm") - F.length("b.name_norm")) <= MAX_NAME_DISTANCE)
                              & (F.levenshtein("a.name_norm", "b.name_norm") <= MAX_NAME_DISTANCE)))
              .distinct())
```

### 3.3 Reasons and score

**Input:** `candidates`, joined with the data of customer A and customer B.
**Output:** `found`. For each pair: `pair_id`, the reasons, the score, and the name, phone, email and city of both customers.

```python
side_a = c.select([F.col(x).alias(f"{x}_a") for x in c.columns])
side_b = c.select([F.col(x).alias(f"{x}_b") for x in c.columns])
p = candidates.join(side_a, "customer_id_a").join(side_b, "customer_id_b")

same_phone = F.coalesce(F.col("msisdn_a") == F.col("msisdn_b"), F.lit(False))
same_email = F.coalesce(F.col("email_a") == F.col("email_b"), F.lit(False))   # missing email = different
same_city = F.coalesce(F.col("city_norm_a") == F.col("city_norm_b"), F.lit(False))
dist = F.levenshtein("name_norm_a", "name_norm_b")
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
```

### 3.4 Save with MERGE

**Input:** `found` and the existing table, if there is one.
**Output:** the updated `silver.customer_duplicate_candidates` table.

**Why MERGE and not overwrite?** So that **the reviewer's decisions are not lost** every time the pipeline runs.

**Table schema:**

```sql
CREATE TABLE IF NOT EXISTS data_sentinel.silver.customer_duplicate_candidates (
    pair_id STRING, customer_id_a BIGINT, customer_id_b BIGINT, reasons ARRAY<STRING>, score DOUBLE,
    customer_name_a STRING, customer_name_b STRING, msisdn_a STRING, msisdn_b STRING,
    email_a STRING, email_b STRING, city_a STRING, city_b STRING,
    is_active BOOLEAN, first_detected_at TIMESTAMP, last_detected_at TIMESTAMP,
    review_status STRING, reviewed_by STRING, reviewed_at TIMESTAMP, review_note STRING) USING DELTA
```

**The MERGE:**

```python
(DeltaTable.forName(spark, T_CUSTOMER_DUPES).alias("t")
    .merge(found.alias("s"), "t.pair_id = s.pair_id")
    .whenMatchedUpdate(condition=f"t.review_status <> 'PENDING' AND {reasons_changed}",
                       set={**refresh, "review_status": "'PENDING'", "reviewed_by": "NULL", "reviewed_at": "NULL",
                            "review_note": "concat('reopened, reasons were ', array_join(t.reasons, ', '))"})  # (b)
    .whenMatchedUpdate(set=refresh)                                                                         # (a)
    .whenNotMatchedInsert(values={..., "is_active": "true", "review_status": "'PENDING'"})                  # (c)
    .whenNotMatchedBySourceUpdate(condition="t.is_active", set={"is_active": "false"})                      # (d)
    .execute())
```

| Case | What happens |
|---|---|
| (a) Existing pair, reasons unchanged | The data is refreshed and **the decision is kept** |
| (b) Reviewed pair whose reasons changed | Goes back to `PENDING`, because the evidence changed |
| (c) New pair | Inserted as `PENDING` |
| (d) Pair no longer found | `is_active = false` (not deleted) |

**One-time migration:** if the table still has the old masked columns (`name_masked_a`), the notebook drops it and rebuilds it.

---

## Step 4: Airflow

**File:** `airflow/dags/sentinel_pipeline.py` (**modified**)

**Input:** the existing DAG.
**Output:** a new task, `silver_dupes`, which runs notebook 54 on every run.

**Why a side branch?** Nothing downstream reads its table, so if it fails it **does not block Gold**.

```python
+  silver_dupes      pairs of customers that are probably the same person, for review in the review app.
+                    Side branch after silver_history: nothing downstream reads it, so it never blocks Gold
 ...
     silver_xref = notebook("silver_xref", "52_silver_customer_xref")
+    silver_dupes = notebook("silver_dupes", "54_silver_customer_duplicates")
 ...
+    silver_history >> silver_dupes
     gate >> dbt_build
```

---

## Step 5: Verify checks

**File:** `databricks/notebooks/silver_layer/53_silver_verify.py` (**modified**)

**Input:** `silver.customer_duplicate_candidates`
**Output:** PASS, WARN or FAIL for each check, in the same check table as the rest of Silver.

```python
+# 6) customer duplicate candidates (54)
+dd = T_CUSTOMER_DUPES
+check("dupes", "each pair is stored lowest customer_id first (no self pairs)", bad_order == 0, bad_order)
+check("dupes", "each pair is stored once", dup_pair == 0, dup_pair)
+check("dupes", "every active pair has at least one reason", no_reason == 0, no_reason)
+check("dupes", "review_status is PENDING, SAME_PERSON or NOT_SAME", bad_status == 0, bad_status)
+check("dupes", "same phone / different email pairs are found (injected: 5)", ..., warn=True)
+check("dupes", "same email / different phone pairs are found (injected: 5)", ..., warn=True)
+check("dupes", "similar name / same city pairs are found (injected: 5)", ..., warn=True)
```

---

## Step 6: Python twin and unit tests

**Why?** The Spark code cannot run locally without Databricks. A **pure-Python** twin with the same rules and weights can be tested in under a second.

### 6.1 The twin

**File:** `src/sentinel_dq/quality/duplicates.py` (**new**)

**Input:** a list of dicts, each with `customer_id`, `first_name`, `last_name`, `email`, `msisdn` and `city`.
**Output:** a list of pairs: `pair_id`, `customer_id_a`, `customer_id_b`, `reasons`, `score`.

| Function | What it does |
|---|---|
| `normalize_name(first, last)` | `"  Zoë ", "van  Dijk"` becomes `"zoe van dijk"` |
| `levenshtein(a, b)` | Number of single-letter edits between two strings (same as Spark) |
| `prepare(customer)` | Normalizes the phone, email, name and city |
| `match_reasons(a, b)` | The reasons for one pair |
| `score(reasons)` | Sum of the weights, at most 1.0 |
| `find_pairs(customers)` | Every pair, strongest first |

```python
def match_reasons(a: dict, b: dict) -> list[str]:
    same_phone = a["msisdn"] is not None and a["msisdn"] == b["msisdn"]
    same_email = a["email"] is not None and a["email"] == b["email"]
    same_city = a["city"] is not None and a["city"] == b["city"]
    dist = levenshtein(a["name"], b["name"]) if a["name"] and b["name"] else None
    reasons = []
    if same_phone and same_email:
        reasons.append("SAME_PHONE_SAME_EMAIL")
    if same_phone and not same_email:          # a missing email counts as different
        reasons.append("SAME_PHONE_DIFF_EMAIL")
    if same_email and not same_phone:
        reasons.append("SAME_EMAIL_DIFF_PHONE")
    if same_city and dist == 0:
        reasons.append("SAME_NAME_SAME_CITY")
    if same_city and dist is not None and 0 < dist <= MAX_NAME_DISTANCE:
        reasons.append("SIMILAR_NAME_SAME_CITY")
    return reasons
```

### 6.2 The tests

**File:** `tests/unit/test_duplicates.py` (**new**, 10 tests)

**Input:** customers built by hand inside each test.
**Output:** pass or fail.

| Test | What it checks |
|---|---|
| `test_levenshtein` | `sophie` and `sofie` are 2 edits apart |
| `test_normalize_name` | Accents and extra spaces |
| `test_same_phone_different_email` | `SAME_PHONE_DIFF_EMAIL` |
| `test_same_phone_missing_email_counts_as_different` | A missing email counts as "different" |
| `test_same_email_different_phone_ignores_case_and_spaces` | `" SOPHIE@example.nl "` = `"sophie@example.nl"` |
| `test_similar_name_needs_the_same_city` | A different city means no pair |
| `test_accents_and_case_give_the_same_name` | `Zoë` = `ZOE` |
| `test_different_people_are_not_a_pair` | No false pair |
| `test_reasons_combine_and_score_is_capped` | 0.6 + 0.2 = 0.8, and the score never exceeds 1.0 |
| `test_find_pairs_lists_each_pair_once_lowest_id_first_strongest_first` | Order, and no repeated pair |

```python
def test_similar_name_needs_the_same_city():
    assert reasons_of(cust(1, first="Sophie"), cust(2, first="Sofie")) == ["SIMILAR_NAME_SAME_CITY"]
    assert reasons_of(cust(1, first="Sophie"), cust(2, first="Sofie", city="Breda")) == []
```

---

## Step 7: The review app (where the reviewer decides)

### 7.1 `review_app/logic.py` (**modified**): logic without UI, so it can be unit tested

**Input:** the rows before and after the reviewer's edits.
**Output:** a list of the decisions that changed.

```python
+DUPLICATE_REASONS = ("SAME_PHONE_SAME_EMAIL", "SAME_PHONE_DIFF_EMAIL", "SAME_EMAIL_DIFF_PHONE",
+                     "SAME_NAME_SAME_CITY", "SIMILAR_NAME_SAME_CITY")
+REVIEW_STATUSES = ("PENDING", "SAME_PERSON", "NOT_SAME")
+DUPLICATES_DATASET = "crm_customers"   # who may review: admins and users that own this dataset
+
+def can_review_duplicates(datasets: list[str]) -> bool:
+    return DUPLICATES_DATASET in datasets
+
+def diff_decisions(original: list[dict], edited: list[dict]) -> list[dict]:
+    """[{pair_id, old_status, new_status, note}] for pairs whose decision or note changed."""
```

### 7.2 `review_app/db.py` (**modified**): talking to Databricks

**Input:** the filters the reviewer picked, and the decisions.
**Output:** the pairs are read; the decisions are written to the table and to the log.

| Function | What it does |
|---|---|
| `duplicates_table_exists(conn)` | Has notebook 54 run yet? |
| `duplicate_counts(conn)` | Number of active pairs per status |
| `fetch_duplicate_pairs(conn, statuses, reasons, min_score, limit)` | Filtered pairs, strongest first |
| `save_duplicate_decisions(conn, decisions, reviewer)` | UPDATE the pair and INSERT into the log |
| `recent_duplicate_reviews(conn)` | The latest decisions |

```python
+T_DUPES = f"{CATALOG}.silver.customer_duplicate_candidates"
+T_DUPE_REVIEWS = f"{CATALOG}.monitoring.duplicate_reviews"
+
+def save_duplicate_decisions(conn, decisions, reviewer):
+    ... CREATE TABLE IF NOT EXISTS {T_DUPE_REVIEWS} (reviewed_at TIMESTAMP, reviewer STRING,
+                        pair_id STRING, old_status STRING, new_status STRING, note STRING)
+    for d in decisions:
+        UPDATE {T_DUPES} SET review_status = :st, review_note = :note, reviewed_by = :by,
+                             reviewed_at = current_timestamp() WHERE pair_id = :pid
+        INSERT INTO {T_DUPE_REVIEWS} VALUES (current_timestamp(), :by, :pid, :old, :st, :note)
```

### 7.3 `review_app/app.py` (**modified**): the page itself

**Input:** the signed-in user (admin or crm).
**Output:** the **"Duplicate customers"** page.

```python
+    pages = (["Quarantine review", "Alerts"]
+             + (["Duplicate customers"] if can_review_duplicates(datasets) else [])   # admins and the crm user
+             + (["Data layers"] if ss["role"] == "admin" else []))
 ...
+    if page == "Duplicate customers":
+        dup_statuses = st.multiselect("Review status", REVIEW_STATUSES, default=["PENDING"])
+        dup_reasons = st.multiselect("Reason", DUPLICATE_REASONS, default=list(DUPLICATE_REASONS))
+        min_score = st.slider("Min score", 0.0, 1.0, 0.0, step=0.1)
+        limit = st.slider("Max pairs", 50, 1000, 200, step=50)
 ...
+        edited = st.data_editor(original, ...,
+            disabled=[c for c in original.columns if c not in ("review_status", "review_note")],
+            column_config={"review_status": st.column_config.SelectboxColumn(options=list(REVIEW_STATUSES))})
+        decisions = diff_decisions(pairs, edited.to_dict("records"))
+        if st.button("Save decisions", type="primary", disabled=not decisions):
+            db.save_duplicate_decisions(conn, decisions, ss["user"])
```

**What the page looks like** (the numbers and names are only an example):

```
┌ Duplicate customers ──────────────────────────────────────────────────────────────────┐
│ Pending: 260        Same Person: 0        Not Same: 0                                 │
│ pair_id  │ reasons                 │ score │ name_a      │ name_b      │ review_status ▾│
│ 220-1016 │ SAME_PHONE_DIFF_EMAIL   │ 0.60  │ Sara Bakker │ Sara Bakker │ PENDING        │
│ 240-1026 │ SIMILAR_NAME_SAME_CITY  │ 0.20  │ Daan Smit   │ Daann Smit  │ PENDING        │
│ [Save decisions]                       ▸ Review history                               │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

### 7.4 `tests/unit/test_review_app.py` (**modified**, 3 tests)

```python
+def test_diff_decisions_keeps_only_changed_valid_decisions(): ...   # ignores untouched rows and bad statuses
+def test_only_crm_owners_and_admins_review_duplicates(): ...
+def test_review_app_reasons_match_the_rules(): ...                  # app list == twin list
```

---

## Step 8: Documentation

**File:** `review_app/README.md` (**modified**)

**Input:** none.
**Output:** a new section, "Duplicate customers page": who can see it, the steps, the weight table, and a note about the noise in the seed data.

---

## Summary

### Files

| File | New / modified |
|---|---|
| `databricks/notebooks/silver_layer/54_silver_customer_duplicates.py` | **New** |
| `src/sentinel_dq/quality/duplicates.py` | **New** |
| `tests/unit/test_duplicates.py` | **New** |
| `databricks/notebooks/silver_layer/49_silver_lib.py` | Modified |
| `databricks/notebooks/silver_layer/53_silver_verify.py` | Modified |
| `airflow/dags/sentinel_pipeline.py` | Modified |
| `generators/postgres_seed/inject_problems.sql` | Modified |
| `review_app/logic.py` | Modified |
| `review_app/db.py` | Modified |
| `review_app/app.py` | Modified |
| `review_app/README.md` | Modified |
| `tests/unit/test_review_app.py` | Modified |

### Input and output

| | |
|---|---|
| **Input** | `data_sentinel.silver.crm_customers_validated` |
| **Output 1** | `data_sentinel.silver.customer_duplicate_candidates`: one row per pair, with the reasons, the score, both customers' data and the decision |
| **Output 2** | `data_sentinel.monitoring.duplicate_reviews`: a log of every decision (who, when, old status, new status, note) |
| **Tests** | 13 new tests. The whole suite passes: **32/32** |

### How to run it

1. Run `inject_problems.sql` once, after the seed load.
2. Upload notebook 54 and the new version of 49 to Databricks.
3. Run the pipeline from Airflow (task `silver_dupes`), or run notebook 54 by hand.
4. (Optional) Run `53_silver_verify` and look at the `dupes` section.
5. Run `streamlit run review_app\app.py`, sign in as `admin` or `crm`, and open **Duplicate customers**.
6. Set `SAME_PERSON` or `NOT_SAME` for each pair and press **Save decisions**.

### Unit tests

```powershell
.venv\Scripts\python -m pytest tests/unit/test_duplicates.py tests/unit/test_review_app.py -q
```

### Notes

- The Spark notebook and the review app page **have not been run on a real Databricks workspace**. Only the unit tests have been run.
- `whenNotMatchedBySourceUpdate` needs Databricks Runtime 12.2 or later (serverless is fine).
- The decision is **recorded only**. Customers are never merged.
- Data is shown **without masking**. Anyone with access to `silver` or to the review app sees real names, phone numbers and emails.
