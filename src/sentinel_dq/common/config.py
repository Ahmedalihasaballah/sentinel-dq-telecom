"""Names shared by the notebooks, dbt and the apps (catalog, schemas, table naming)."""
import os

CATALOG = os.getenv("SENTINEL_CATALOG", "data_sentinel")
SCHEMAS = ("bronze", "silver", "quarantine", "monitoring", "gold")
CONTRACT_VOLUME = f"/Volumes/{CATALOG}/monitoring/contracts"
# Same fallback as 49_silver_lib when the Databricks secret sentinel/pii_salt is missing; set it in production.
PII_SALT = os.getenv("SENTINEL_PII_SALT", "dev-salt-change-me")


def validated_table(dataset: str) -> str:
    return f"{CATALOG}.silver.{dataset}_validated"


def quarantine_table(dataset: str) -> str:
    return f"{CATALOG}.quarantine.{dataset}"
