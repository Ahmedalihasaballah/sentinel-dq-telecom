"""Store the Slack incoming-webhook URL as the Databricks secret the incident notebook reads (scope sentinel, key slack_webhook).

    .venv\\Scripts\\python scripts\\set_slack_webhook.py          paste the webhook when asked (hidden), then a test message is sent

Get the URL in Slack: api.slack.com/apps -> Create New App -> From scratch -> Incoming Webhooks -> On ->
Add New Webhook to Workspace -> pick a channel (e.g. #data-alerts) -> copy https://hooks.slack.com/services/...
Uses DATABRICKS_TOKEN from .env / airflow/.env. The webhook is never printed or written to disk.
"""
import getpass
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
HOST = "https://dbc-21b8c56c-c07d.cloud.databricks.com"
SCOPE, KEY = "sentinel", "slack_webhook"


def main():
    env = {**dotenv_values(ROOT / "airflow" / ".env"), **{k: v for k, v in dotenv_values(ROOT / ".env").items() if v}}
    token = (env.get("DATABRICKS_TOKEN") or "").strip()
    if not token:
        sys.exit("DATABRICKS_TOKEN missing in .env / airflow/.env")
    h = {"Authorization": f"Bearer {token}"}

    url = getpass.getpass("Slack webhook URL (hidden): ").strip()
    if not url.startswith("https://hooks.slack.com/"):
        sys.exit("That does not look like a Slack incoming-webhook URL (https://hooks.slack.com/...).")

    scopes = [s["name"] for s in requests.get(f"{HOST}/api/2.0/secrets/scopes/list", headers=h, timeout=60).json().get("scopes", [])]
    if SCOPE not in scopes:
        r = requests.post(f"{HOST}/api/2.0/secrets/scopes/create", headers=h, json={"scope": SCOPE}, timeout=60)
        r.raise_for_status()
        print(f"created secret scope '{SCOPE}'")
    r = requests.post(f"{HOST}/api/2.0/secrets/put", headers=h, json={"scope": SCOPE, "key": KEY, "string_value": url}, timeout=60)
    r.raise_for_status()
    print(f"stored secret {SCOPE}/{KEY} in Databricks")

    t = requests.post(url, json={"text": ":white_check_mark: DataSentinel is connected. New P1/P2 incidents will be posted here."}, timeout=30)
    print("test message sent to Slack" if t.ok else f"Slack refused the test message: HTTP {t.status_code}")


if __name__ == "__main__":
    main()
