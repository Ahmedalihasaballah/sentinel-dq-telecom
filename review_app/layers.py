"""'Data layers' page: browse the output tables of every layer, from the source systems to Gold.

Source tables are read from the local Postgres container (docker exec psql, no driver or password needed) and the
local CSV batch files; Bronze, Silver, Quarantine, Gold and Monitoring are read from Databricks (data_sentinel).
Read-only: every query is a SELECT on a table name taken from a fixed list or from information_schema.
"""
import io
import subprocess
from pathlib import Path

import pandas as pd
import streamlit as st

import db
from logic import safe_name

ROOT = Path(__file__).resolve().parent.parent
BATCH_DIR = ROOT / "generators" / "batch" / "batch_data"
PG_CONTAINER, PG_DB = "cdc-postgres", "telecom"
SOURCE_TABLES = ["crm.customers", "crm.plans", "crm.devices", "billing.accounts", "billing.invoices",
                 "billing.invoice_lines", "billing.payments"]

LAYERS = {
    "1 · Source (PostgreSQL + CSV files)": {"kind": "source",
        "about": "The operational systems as they are: CRM and billing in Postgres (captured by Debezium CDC) "
                 "and the CSV files (network, invoice and payment exports, partner usage)."},
    "2 · Bronze (raw, as received)": {"kind": "uc", "schema": "bronze",
        "about": "Every change event and every file row exactly as it arrived. Nothing is fixed or dropped here."},
    "3 · Quality gate → Quarantine": {"kind": "uc", "schema": "quarantine",
        "about": "Rows that failed their data contract, with the reason and status "
                 "(REJECTED, PENDING_FIX, FIXED_PENDING_REVALIDATION, REVALIDATED_OK)."},
    "4 · Silver (validated, clean, history)": {"kind": "uc", "schema": "silver",
        "about": "*_validated = rows that passed the gate; clean tables = newest version per key; "
                 "customer_history / plan_history = SCD2 versions; customer_xref = CRM ↔ billing link."},
    "5 · Gold (dbt: dims, facts, marts)": {"kind": "uc", "schema": "gold",
        "about": "Star schema built by dbt: dim_* and fact_* tables, and the mart_* tables used by Power BI and Genie."},
    "6 · Monitoring (results, incidents, recon)": {"kind": "uc", "schema": "monitoring",
        "about": "Quality-gate results, reconciliation results and mismatches, incidents, alerts and the edit log."},
}

# one row per dataset: where its rows are in each layer (used by the 'Flow' tab)
FLOW = [
    ("crm_customers", "crm.customers", "telecom.crm.customers", "crm_customers_validated", "customer_history", "dim_customer"),
    ("billing_accounts", "billing.accounts", "telecom.billing.accounts", "billing_accounts_validated", "account", None),
    ("billing_invoices", "billing.invoices", "telecom.billing.invoices", "billing_invoices_validated", "invoice", "fact_invoice"),
    ("billing_invoice_lines", "billing.invoice_lines", "telecom.billing.invoice_lines", "billing_invoice_lines_validated", "invoice_line", None),
    ("billing_payments", "billing.payments", "telecom.billing.payments", "billing_payments_validated", "payment", "fact_payment"),
    ("network_cdr", None, "network_cdr_raw", "network_cdr_validated", "network_cdr", "fact_usage"),
    ("invoices_file", None, "billing_invoices_raw", "invoices_file_validated", "invoice_file", None),
    ("payments_file", None, "billing_payments_raw", "payments_file_validated", "payment_file", None),
    ("partner_usage", None, "partner_usage_raw", "partner_usage_validated", "partner_usage", "fact_partner_usage"),
]


# ---------------- source (Postgres container + CSV files) ----------------

def _psql(sql: str) -> pd.DataFrame:
    out = subprocess.run(["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres", "-d", PG_DB, "--csv", "-c", sql],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "psql failed")
    return pd.read_csv(io.StringIO(out.stdout))


@st.cache_data(ttl=300, show_spinner=False)
def source_counts() -> pd.DataFrame:
    union = " UNION ALL ".join(f"SELECT '{t}' AS table_name, count(*) AS row_count FROM {t}" for t in SOURCE_TABLES)
    return _psql(union)


@st.cache_data(ttl=300, show_spinner=False)
def source_preview(table: str, limit: int) -> pd.DataFrame:
    if table not in SOURCE_TABLES:
        raise ValueError(table)
    return _psql(f"SELECT * FROM {table} ORDER BY 1 LIMIT {int(limit)}")


def csv_files() -> pd.DataFrame:
    rows = []
    for f in sorted(BATCH_DIR.glob("*/*.csv")):
        with f.open(encoding="utf-8") as fh:
            n = sum(1 for _ in fh) - 1
        rows.append({"source": f.parent.name, "file": f.name, "rows": n})
    return pd.DataFrame(rows)


# ---------------- Databricks layers ----------------

@st.cache_data(ttl=300, show_spinner=False)
def uc_counts(_conn, schema: str) -> pd.DataFrame:
    schema = safe_name(schema)
    tables = db._rows(_conn, f"""SELECT table_name, table_type FROM {db.CATALOG}.information_schema.tables
                                 WHERE table_schema = '{schema}' ORDER BY table_name""")
    if not tables:
        return pd.DataFrame(columns=["table_name", "type", "row_count"])
    union = " UNION ALL ".join(f"SELECT '{t['table_name']}' AS table_name, count(*) AS row_count "
                               f"FROM {db.CATALOG}.{schema}.`{t['table_name']}`" for t in tables)
    counts = {r["table_name"]: r["row_count"] for r in db._rows(_conn, union)}
    return pd.DataFrame([{"table_name": t["table_name"], "type": t["table_type"].lower(), "row_count": counts.get(t["table_name"])}
                         for t in tables])


@st.cache_data(ttl=300, show_spinner=False)
def uc_preview(_conn, schema: str, table: str, limit: int) -> pd.DataFrame:
    known = set(uc_counts(_conn, schema)["table_name"])
    if table not in known:
        raise ValueError(table)
    return pd.DataFrame(db._rows(_conn, f"SELECT * FROM {db.CATALOG}.{safe_name(schema)}.`{table}` LIMIT {int(limit)}"))


@st.cache_data(ttl=300, show_spinner=False)
def flow_table(_conn) -> pd.DataFrame:
    try:
        src = dict(zip(source_counts()["table_name"], source_counts()["row_count"]))
    except Exception:
        src = {}
    bronze = dict(zip(uc_counts(_conn, "bronze")["table_name"], uc_counts(_conn, "bronze")["row_count"]))
    silver = dict(zip(uc_counts(_conn, "silver")["table_name"], uc_counts(_conn, "silver")["row_count"]))
    quar = dict(zip(uc_counts(_conn, "quarantine")["table_name"], uc_counts(_conn, "quarantine")["row_count"]))
    gold = dict(zip(uc_counts(_conn, "gold")["table_name"], uc_counts(_conn, "gold")["row_count"]))
    topic_counts = {r["topic"]: r["n"] for r in db._rows(_conn, f"SELECT topic, count(*) AS n FROM {db.CATALOG}.bronze.cdc_events GROUP BY topic")}
    out = []
    for ds, src_t, bronze_t, val_t, clean_t, gold_t in FLOW:
        out.append({
            "dataset": ds,
            "source rows": src.get(src_t) if src_t else "CSV files",
            "bronze rows": topic_counts.get(bronze_t) if bronze_t.startswith("telecom.") else bronze.get(bronze_t),
            "passed gate (silver *_validated)": silver.get(val_t),
            "quarantine": quar.get(ds, 0),
            "silver clean / history": silver.get(clean_t),
            "gold table": f"{gold_t}: {gold.get(gold_t):,}" if gold_t and gold.get(gold_t) is not None else "",
        })
    return pd.DataFrame(out)


# ---------------- page ----------------

def render(conn):
    st.title("Data layers")
    st.caption("Output tables of every layer, from the source systems to Gold. Counts refresh every 5 minutes "
               "(press **Refresh** for now). Source and Bronze hold raw personal data: admins only.")
    if st.button("Refresh"):
        st.cache_data.clear()

    tab_flow, tab_browse = st.tabs(["Flow per dataset", "Browse a layer"])

    with tab_flow:
        st.markdown("Each dataset from source to Gold. **Bronze = passed gate + quarantine** (CDC sources can have an "
                    "extra event per update); Silver clean keeps the newest version per key.")
        try:
            st.dataframe(flow_table(conn), hide_index=True, use_container_width=True)
        except Exception as e:
            st.error(f"Could not build the flow table: {e}")

    with tab_browse:
        layer = st.radio("Layer", list(LAYERS), horizontal=False)
        meta = LAYERS[layer]
        st.info(meta["about"])
        limit = st.slider("Rows to show", 10, 1000, 100, step=10)

        if meta["kind"] == "source":
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("PostgreSQL (database telecom)")
                try:
                    counts = source_counts()
                    st.dataframe(counts, hide_index=True, use_container_width=True)
                    table = st.selectbox("Postgres table", SOURCE_TABLES)
                except Exception as e:
                    st.error(f"Postgres container not reachable ({e}). Start it with: docker compose up -d postgres")
                    table = None
            with c2:
                st.subheader("CSV batch files")
                files = csv_files()
                st.dataframe(files, hide_index=True, use_container_width=True)
            if table:
                st.subheader(f"`{table}` (first {limit} rows)")
                st.dataframe(source_preview(table, limit), hide_index=True, use_container_width=True)
            if len(files):
                pick = st.selectbox("CSV file", [f"{r.source}/{r.file}" for r in files.itertuples()])
                st.dataframe(pd.read_csv(BATCH_DIR / pick, nrows=limit, dtype=str), hide_index=True, use_container_width=True)
        else:
            schema = meta["schema"]
            counts = uc_counts(conn, schema)
            st.subheader(f"`{db.CATALOG}.{schema}`: {len(counts)} tables")
            st.dataframe(counts, hide_index=True, use_container_width=True)
            if len(counts):
                table = st.selectbox("Table", list(counts["table_name"]))
                df = uc_preview(conn, schema, table, limit)
                st.subheader(f"`{schema}.{table}` (first {limit} rows of {int(counts.set_index('table_name').loc[table, 'row_count'] or 0):,})")
                st.dataframe(df, hide_index=True, use_container_width=True)
                st.download_button("Download these rows (CSV)", df.to_csv(index=False).encode("utf-8"),
                                   file_name=f"{schema}.{table}.csv", mime="text/csv")
