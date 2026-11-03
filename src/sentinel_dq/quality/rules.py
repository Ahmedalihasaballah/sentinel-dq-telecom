"""Row-level quality rules: the Python twin of rule_fail / apply_rules / fix_expression in 11_dq_lib.

evaluate(rows, contract) returns, per row, the same verdict the quality gate gives:
  REJECT  if a reject rule fails, AUTOFIX if only autofix rules fail, PASS otherwise; flag rules only add _flags.
Rules of type 'expr' are Spark SQL expressions and are not evaluated here (listed in 'not_checked').
"""
import operator
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from .contract_loader import expand_rules

_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "=": operator.eq, "==": operator.eq,
        "!=": operator.ne, "<>": operator.ne}


def _blank(v) -> bool:
    return v is None or str(v).strip() == ""


def try_cast(value, typ: str):
    """Spark-like try_cast of a raw (string) value; None when it does not convert."""
    if _blank(value):
        return None
    v = str(value).strip()
    try:
        if typ in ("bigint", "int", "long", "integer"):
            if not re.fullmatch(r"[+-]?\d+", v):
                return None
            return int(v)
        if typ == "double":
            return float(v)
        if typ.startswith("decimal"):
            return Decimal(v)
        if typ == "boolean":
            return {"true": True, "false": False}.get(v.lower())
        if typ == "date":
            return date.fromisoformat(v[:10])
        if typ == "date_days":                          # Debezium DATE = days since 1970-01-01
            return date(1970, 1, 1) + timedelta(days=int(v))
        if typ == "timestamp":
            ts = datetime.fromisoformat(v.replace("Z", "+00:00").replace(" ", "T", 1))
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except (ValueError, InvalidOperation, OverflowError):
        return None
    return v                                            # string


def _fails(rule, row, typed, now) -> bool:
    t, col = rule["type"], rule.get("column")
    if t == "not_null":
        return _blank(row.get(col))
    if t == "type":
        return not _blank(row.get(col)) and typed.get(col) is None
    if t == "regex":
        return not _blank(row.get(col)) and re.search(rule["pattern"], str(row[col])) is None
    if t == "domain":
        return not _blank(row.get(col)) and str(row[col]).strip() not in rule["values"]
    if t == "range":
        v = typed.get(col)
        if v is None:
            return False
        lo, hi = rule.get("min"), rule.get("max")
        num = float(v)
        return (lo is not None and num < lo) or (hi is not None and num > hi)
    if t == "not_future":
        v = typed.get(col)
        if v is None:
            return False
        tol = timedelta(days=int(rule.get("tolerance_days", 1)))
        limit = now + tol
        return (v > limit.date()) if isinstance(v, date) and not isinstance(v, datetime) else v > limit
    if t == "compare":
        a, b = typed.get(rule["left"]), typed.get(rule["right"])
        return a is not None and b is not None and not _OPS[rule["op"]](a, b)
    return False


def evaluate(rows: list, contract: dict, include_unique: bool = True, now: datetime = None) -> dict:
    """Verdict per row: {'results': [{'status', 'failed_rules', 'flags'}...], 'not_checked': [rule ids]}."""
    now = now or datetime.now(timezone.utc)
    rules = expand_rules(contract, include_unique)
    types = {c["name"]: c["type"] for c in contract["columns"]}
    checked = [r for r in rules if r["type"] != "expr"]
    not_checked = [r["id"] for r in rules if r["type"] == "expr"]

    fails = [set() for _ in rows]
    typed_rows = [{n: try_cast(row.get(n), types[n]) for n in types} for row in rows]
    for i, row in enumerate(rows):
        for r in checked:
            if r["type"] != "unique" and _fails(r, row, typed_rows[i], now):
                fails[i].add(r["id"])
    for r in (x for x in checked if x["type"] == "unique"):    # first row per key passes, later repeats fail
        seen = set()
        for i, row in enumerate(rows):
            if any(_blank(row.get(k)) for k in r["keys"]):
                continue
            key = tuple(str(row[k]).strip() for k in r["keys"])
            if key in seen:
                fails[i].add(r["id"])
            seen.add(key)

    by_action = {a: {r["id"] for r in rules if r["action"] == a} for a in ("reject", "autofix", "flag")}
    results = []
    for f in fails:
        status = "REJECT" if f & by_action["reject"] else "AUTOFIX" if f & by_action["autofix"] else "PASS"
        results.append({"status": status,
                        "failed_rules": sorted(f & (by_action["reject"] | by_action["autofix"])),
                        "flags": sorted(f & by_action["flag"])})
    return {"results": results, "not_checked": not_checked}


def apply_fix_steps(value, steps):
    """Same as apply_fix_steps_py in 11_dq_lib (Spark '$1' back-references become Python '\\1')."""
    if value is None:
        return None
    for s in steps:
        op = s["op"]
        if op == "trim":
            value = value.strip()
        elif op == "lower":
            value = value.lower()
        elif op == "upper":
            value = value.upper()
        elif op == "regex_replace":
            value = re.sub(s["pattern"], re.sub(r"\$(\d)", r"\\\1", s["replacement"]), value)
    return value


def fix_row(row: dict, contract: dict) -> dict:
    """Row with the contract's fixes applied: what 21_quarantine_autofix writes to _fixed."""
    steps = {fx["column"]: fx["steps"] for fx in contract.get("fixes", [])}
    return {k: (apply_fix_steps(v, steps[k]) if k in steps else v) for k, v in row.items()}
