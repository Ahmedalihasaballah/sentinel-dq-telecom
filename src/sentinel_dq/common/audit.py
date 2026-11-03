"""Run ids and result rows in the shape the notebooks write to monitoring.dq_results."""
import uuid
from datetime import datetime, timezone


def new_run_id() -> str:
    """yyyymmddHHMMSS-xxxxxx, the same format as new_run_id() in 11_dq_lib."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]


def result_row(run_id, dataset, check, rule_id, dimension, scope, checked, failed, status, severity, detail, version):
    pass_rate = (checked - failed) / checked if checked else 1.0
    return {"run_id": run_id, "dataset": dataset, "check_name": check, "rule_id": rule_id, "dimension": dimension,
            "scope": scope, "rows_checked": checked, "rows_failed": failed, "pass_rate": round(pass_rate, 6),
            "status": status, "severity": severity, "detail": detail, "contract_version": version}
