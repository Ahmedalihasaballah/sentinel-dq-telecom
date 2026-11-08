"""Quarantine review app: sign in with a password, view quarantined rows, correct them, send them to recheck.

    streamlit run review_app/app.py

Corrected rows get status FIXED_PENDING_REVALIDATION; the next pipeline run (22_revalidate) applies the
contract rules again: rows that pass go to Silver, rows that still fail go back to REJECTED.
"""
import time
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import db
from logic import (ALL_STATUSES, DUPLICATE_REASONS, EDITABLE_STATUSES, REVIEW_STATUSES, allowed_datasets,
                   authenticate, can_review_duplicates, diff_decisions, diff_rows, load_contracts, load_users)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
USERS_FILE = HERE / "users.json"
MAX_ATTEMPTS, LOCK_SECONDS, IDLE_LOGOUT_SECONDS = 5, 300, 1800

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "airflow" / ".env")  # DATABRICKS_TOKEN / DATABRICKS_HTTP_PATH already live here

st.set_page_config(page_title="DataSentinel · Quarantine review", page_icon="🛡️", layout="wide")
ss = st.session_state


def login_screen():
    st.title("🛡️ Quarantine review")
    st.caption("Authorized users only. Sign in to view and correct quarantined rows.")
    users = load_users(USERS_FILE)
    if not users:
        st.error("No users configured. Create one with:  python review_app/manage_users.py add <name> --role admin")
        st.stop()
    locked_until = ss.get("locked_until", 0)
    if time.time() < locked_until:
        st.error(f"Too many failed attempts. Try again in {int(locked_until - time.time())} s.")
        st.stop()
    with st.form("login"):
        username = st.text_input("User")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary"):
            user = authenticate(users, username.strip(), password)
            if user:
                ss.update(user=username.strip(), role=user.get("role", "owner"), datasets=user.get("datasets", []),
                          failed=0, last_seen=time.time())
                st.rerun()
            ss["failed"] = ss.get("failed", 0) + 1
            if ss["failed"] >= MAX_ATTEMPTS:
                ss["locked_until"], ss["failed"] = time.time() + LOCK_SECONDS, 0
            st.error("Wrong user or password.")
    st.stop()


@st.cache_resource
def get_conn():
    return db.connect()


if "user" not in ss or time.time() - ss.get("last_seen", 0) > IDLE_LOGOUT_SECONDS:
    ss.pop("user", None)
    login_screen()
ss["last_seen"] = time.time()

contracts = load_contracts(ROOT / "contract")
datasets = allowed_datasets({"role": ss["role"], "datasets": ss["datasets"]}, sorted(contracts))

with st.sidebar:
    st.markdown(f"**{ss['user']}** · {ss['role']}")
    if st.button("Sign out"):
        ss.clear()
        st.rerun()
    if not datasets:
        st.warning("Your account has no datasets assigned.")
        st.stop()
    pages = (["Quarantine review", "Alerts"]
             + (["Duplicate customers"] if can_review_duplicates(datasets) else [])   # admins and the crm user
             + (["Data layers"] if ss["role"] == "admin" else []))                    # raw PII in Source/Bronze
    page = st.radio("Page", pages, index=len(pages) - 1 if ss["role"] == "admin" else 0)  # admin opens on Data layers
    if page == "Quarantine review":
        dataset = st.selectbox("Dataset", datasets)
        statuses = st.multiselect("Status", ALL_STATUSES, default=list(EDITABLE_STATUSES))
        limit = st.slider("Max rows", 50, 1000, 200, step=50)
    if page == "Duplicate customers":
        dup_statuses = st.multiselect("Review status", REVIEW_STATUSES, default=["PENDING"])
        dup_reasons = st.multiselect("Reason", DUPLICATE_REASONS, default=list(DUPLICATE_REASONS))
        min_score = st.slider("Min score", 0.0, 1.0, 0.0, step=0.1)
        limit = st.slider("Max pairs", 50, 1000, 200, step=50)

try:
    conn = get_conn()
except Exception as e:  # missing env vars or warehouse not reachable
    st.error(f"Cannot connect to Databricks: {e}")
    st.stop()

if page == "Data layers":
    import layers
    layers.render(conn)
    st.stop()

if page == "Alerts":
    # admins see every incident; a source user sees only incidents of its own datasets (plus recon for admins)
    scope = None if ss["role"] == "admin" else datasets
    st.title("Alerts & incidents")
    st.caption("Alerts are written by the pipeline (71_incident_manage). Channel 'log' = saved here, 'slack' = also sent to Slack.")
    k = db.incident_kpis(conn, scope)
    for col, (label, key) in zip(st.columns(5), [("Open", "open_incidents"), ("Open P1", "open_p1"), ("Open P2", "open_p2"),
                                                 ("SLA breached", "open_sla_breached"), ("Waiting for ack", "waiting_for_ack")]):
        col.metric(label, k.get(key) or 0)
    st.subheader("Open incidents")
    inc = db.open_incidents(conn, scope)
    if inc:
        st.dataframe(pd.DataFrame(inc), hide_index=True, use_container_width=True)
    else:
        st.success("No open incidents.")
    st.subheader("Alert log")
    al = db.alert_log(conn, scope)
    if al:
        st.dataframe(pd.DataFrame(al), hide_index=True, use_container_width=True)
    else:
        st.write("No alerts yet.")
    st.stop()

if page == "Duplicate customers":
    st.title("Duplicate customers")
    st.caption("Pairs of customers that are probably the same person, found by 54_silver_customer_duplicates. "
               "Set **review_status** to SAME_PERSON or NOT_SAME (and a note if useful), then press **Save decisions**. "
               "The decision is only recorded; customers are not merged. Score = sum of the reason weights "
               "(phone 0.6, email 0.5, same name + city 0.3, similar name + city 0.2), at most 1.0.")
    if not db.duplicates_table_exists(conn):
        st.info("No duplicate candidates yet: run the notebook 54_silver_customer_duplicates (task silver_dupes).")
        st.stop()
    dc = db.duplicate_counts(conn)
    for col, s in zip(st.columns(len(REVIEW_STATUSES)), REVIEW_STATUSES):
        col.metric(s.replace("_", " ").title(), dc.get(s, 0))
    pairs = db.fetch_duplicate_pairs(conn, dup_statuses, dup_reasons, min_score, limit)
    if not pairs:
        st.success("No pairs with the selected filters.")
    else:
        original = pd.DataFrame(pairs)
        edited = st.data_editor(
            original, hide_index=True, use_container_width=True, key="editor_duplicates",
            disabled=[c for c in original.columns if c not in ("review_status", "review_note")],
            column_config={"review_status": st.column_config.SelectboxColumn("review_status", options=list(REVIEW_STATUSES),
                                                                             required=True),
                           "review_note": st.column_config.TextColumn("review_note", max_chars=500),
                           "score": st.column_config.NumberColumn("score", format="%.2f")})
        decisions = diff_decisions(pairs, edited.to_dict("records"))
        st.write(f"**{len(decisions)}** pair(s) changed.")
        if st.button("Save decisions", type="primary", disabled=not decisions):
            n = db.save_duplicate_decisions(conn, decisions, ss["user"])
            st.success(f"{n} decision(s) saved.")
            time.sleep(1)
            st.rerun()
    with st.expander("Review history"):
        hist = db.recent_duplicate_reviews(conn)
        if hist:
            st.dataframe(pd.DataFrame(hist), hide_index=True, use_container_width=True)
        else:
            st.write("No decisions yet.")
    st.stop()

st.title(f"Quarantine · `{dataset}`")
if not db.table_exists(conn, dataset):
    st.info("No quarantine table for this dataset yet (the quality gate has not quarantined anything).")
    st.stop()

counts = db.status_counts(conn, dataset)
for col, s in zip(st.columns(len(ALL_STATUSES)), ALL_STATUSES):
    col.metric(s.replace("_", " ").title(), counts.get(s, 0))

columns = contracts[dataset]
rows = db.fetch_rows(conn, dataset, columns, statuses, limit)
if not rows:
    st.success("No rows with the selected status.")
    st.stop()

st.caption("Edit the values, then press **Save & send to recheck**. Rows with status REVALIDATED_OK are read-only. "
           "The next pipeline run rechecks the corrected rows with the contract rules.")
original = pd.DataFrame(rows)
locked_cols = [c for c in original.columns if c not in columns]
edited = st.data_editor(original, disabled=locked_cols, hide_index=True, use_container_width=True,
                        key=f"editor_{dataset}")

editable_ids = {r["_row_id"] for r in rows if r["_quarantine_status"] in EDITABLE_STATUSES}
changes = [e for e in diff_rows(rows, edited.to_dict("records"), columns) if e["row_id"] in editable_ids]
st.write(f"**{len(changes)}** row(s) changed.")
if st.button("Save & send to recheck", type="primary", disabled=not changes):
    n = db.save_fixes(conn, dataset, changes, ss["user"])
    st.success(f"{n} row(s) saved and marked FIXED_PENDING_REVALIDATION. They will be rechecked on the next run.")
    time.sleep(1)
    st.rerun()

with st.expander("Edit history"):
    hist = db.recent_edits(conn, dataset)
    if hist:
        st.dataframe(pd.DataFrame(hist), hide_index=True, use_container_width=True)
    else:
        st.write("No edits yet.")
