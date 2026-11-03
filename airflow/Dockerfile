FROM apache/airflow:2.10.5-python3.10
# Built once, so the container never downloads packages at start-up (a slow network used to crash it).
# Databricks provider goes into Airflow itself (pinned to Airflow 2.10.5 by the official constraints);
# dbt gets its own virtualenv so the two never fight over versions.
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10
RUN pip install --no-cache-dir "apache-airflow==2.10.5" apache-airflow-providers-databricks \
        --constraint https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.10.txt
RUN python -m venv /home/airflow/dbt_venv && /home/airflow/dbt_venv/bin/pip install --no-cache-dir dbt-databricks
