"""Sentinel pipeline: Bronze -> quality gate -> Silver -> reconciliation -> incidents -> Gold (dbt).

Airflow only orchestrates. The work stays in the Databricks notebooks and in dbt.
Order of the tasks and why:
  bronze_*          load new CDC events, app events and batch files into Bronze (in parallel)
  gate              contract + rules: pass -> validated table, fail -> quarantine
  autofix           deterministic repairs on quarantined rows
  revalidate        same rules again on the fixed rows
  monitors          the five observability pillars
  circuit_breaker   stops Silver and Gold while a critical incident is OPEN (23_circuit_breaker raises on purpose)
  silver_*          SCD2 history, clean tables, customer_xref
  recon             cross-system checks (only reads Silver)
  incidents         assign owner/priority, alert, escalate, record resolved (after gate, monitors and recon);
                    runs even when the breaker stopped Silver, so the blocking incident is still alerted
  dbt_build         Gold dims, facts, marts and tests (after incidents, because mart_incidents reads them);
                    skipped while the breaker is open
"""
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.databricks.operators.databricks import DatabricksSubmitRunOperator

NB_DIR = os.environ.get("SENTINEL_NOTEBOOK_DIR", "/Workspace/Users/REPLACE/sentinel").rstrip("/")
CLUSTER_ID = os.environ.get("SENTINEL_CLUSTER_ID", "").strip()
SCHEDULE = os.environ.get("SENTINEL_SCHEDULE", "*/30 * * * *")
SLA_SCALE = os.environ.get("SENTINEL_SLA_SCALE", "1")


def notebook(task_id, name, params=None, **operator_args):
    # Multi-task format (a "tasks" array): required by Databricks for serverless runs, also valid with a cluster.
    task = {"task_key": task_id,
            "notebook_task": {"notebook_path": f"{NB_DIR}/{name}", "source": "WORKSPACE",
                              "base_parameters": params or {}}}
    if CLUSTER_ID:
        task["existing_cluster_id"] = CLUSTER_ID      # no cluster given = serverless compute
    spec = {"run_name": f"sentinel-{task_id}", "tasks": [task]}
    return DatabricksSubmitRunOperator(task_id=task_id, databricks_conn_id="databricks_default", json=spec,
                                       **operator_args)


default_args = {"owner": "data-platform", "retries": 1, "retry_delay": timedelta(minutes=2)}

with DAG(
    dag_id="sentinel_pipeline",
    description="Bronze to Gold with the quality gate, reconciliation and incident management",
    start_date=datetime(2026, 10, 1),
    schedule=SCHEDULE,
    catchup=False,
    max_active_runs=1,          # a run must finish before the next one starts (the gate is not safe to overlap)
    default_args=default_args,
    tags=["sentinel", "data-quality"],
) as dag:

    # Notebook names match databricks/notebooks/ in the repo. The CDC Bronze notebook (01_bronze) is not in the
    # repo yet, so its task is left out; add it back here and in the bronze list below once the notebook exists:
    #   bronze_cdc = notebook("bronze_cdc", "01_bronze")
    bronze_app = notebook("bronze_app_events", "03_bronze_app_events")
    bronze_files = notebook("bronze_batch_files", "02.1_bronze_batch_files")

    gate = notebook("gate", "20_quality_gate")
    autofix = notebook("autofix", "21_quarantine_autofix")
    revalidate = notebook("revalidate", "22_revalidate")
    monitors = notebook("monitors", "30_observability_monitors")
    # A tripped breaker is a deliberate stop, not a glitch: no retry.
    breaker = notebook("circuit_breaker", "23_circuit_breaker", {"datasets": "all", "block_severities": "critical"},
                       retries=0)

    silver_history = notebook("silver_history", "50_silver_history")
    silver_clean = notebook("silver_clean", "51_silver_clean")
    silver_xref = notebook("silver_xref", "52_silver_customer_xref")

    recon = notebook("recon", "60_recon")
    incidents = notebook("incidents", "71_incident_manage", {"sla_scale": SLA_SCALE},
                         trigger_rule="all_done")   # also after a tripped breaker

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command="cd /opt/airflow/dbt_simple && /home/airflow/dbt_venv/bin/dbt build --profiles-dir /opt/airflow/dbt_profiles",
    )

    [bronze_app, bronze_files] >> gate >> autofix >> revalidate >> monitors
    monitors >> breaker >> silver_history >> silver_clean >> silver_xref >> recon >> incidents >> dbt_build
    breaker >> dbt_build          # Gold is not rebuilt while the breaker is open
