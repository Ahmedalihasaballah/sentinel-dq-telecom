"""Load and check the data contracts (contract/*.yaml), with the same rules as load_contracts in 11_dq_lib."""
from pathlib import Path

import yaml

ACTIONS = {"reject", "autofix", "flag"}
RULE_TYPES = {"not_null", "regex", "domain", "range", "not_future", "compare", "expr", "unique"}
FIX_OPS = {"trim", "lower", "upper", "regex_replace"}


def load_contracts(directory) -> dict:
    """dataset -> contract. Files whose name starts with '_' are disabled and skipped (e.g. _app_events.yaml)."""
    out = {}
    for f in sorted(Path(directory).glob("*.y*ml")):
        if f.name.startswith("_"):
            continue
        c = yaml.safe_load(f.read_text(encoding="utf-8"))
        out[c["dataset"]] = c
    return out


def expand_rules(c: dict, include_unique: bool = True) -> list:
    """Contract rules plus one automatic TYPE_<COLUMN> rule per non-string column (as expand_rules in 11_dq_lib)."""
    rules = [dict(id=f"TYPE_{col['name'].upper()}", type="type", column=col["name"], dimension="validity",
                  severity="high", action=c.get("type_action", "reject"))
             for col in c["columns"] if col["type"] != "string"]
    for r in c.get("rules", []):
        rr = dict(r)
        rr.setdefault("severity", "medium")
        rr.setdefault("action", "reject")
        rules.append(rr)
    return rules if include_unique else [r for r in rules if r["type"] != "unique"]


def validate_contract(c: dict) -> list:
    """Problems found in one contract (empty list = valid)."""
    errs = [f"missing key '{k}'" for k in ("dataset", "version", "source", "columns") if k not in c]
    if errs:
        return errs
    names = [col["name"] for col in c["columns"]]
    if len(names) != len(set(names)):
        errs.append("duplicate column names")
    ids = [r.get("id") for r in c.get("rules", [])]
    if len(ids) != len(set(ids)):
        errs.append("duplicate rule ids")
    for r in c.get("rules", []):
        rid = r.get("id", "?")
        if r.get("type") not in RULE_TYPES:
            errs.append(f"{rid}: unknown rule type {r.get('type')!r}")
        if r.get("action", "reject") not in ACTIONS:
            errs.append(f"{rid}: unknown action {r.get('action')!r}")
        for key in ("column", "left", "right"):
            if r.get(key) and r[key] not in names:
                errs.append(f"{rid}: {key} {r[key]!r} is not a contract column")
        for k in r.get("keys", []):
            if k not in names:
                errs.append(f"{rid}: key {k!r} is not a contract column")
    for fx in c.get("fixes", []):
        if fx.get("column") not in names:
            errs.append(f"fix on unknown column {fx.get('column')!r}")
        for s in fx.get("steps", []):
            if s.get("op") not in FIX_OPS:
                errs.append(f"fix on {fx.get('column')}: unknown op {s.get('op')!r}")
    return errs
