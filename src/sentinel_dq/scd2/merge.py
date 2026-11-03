"""SCD type 2 history from ordered change events (the logic of customer_history / plan_history in 50_silver_history).

A new version starts only when a tracked attribute changes; the previous version is closed at that moment.
Rebuilding from the same events always gives the same history (idempotent).
"""
from datetime import datetime

OPEN_END = datetime(9999, 12, 31)


def build_history(events: list, key: str, tracked: list, ts_field: str = "ts") -> list:
    """events: dicts with the key, the tracked attributes and an event time. Returns the version rows."""
    out, current = [], {}
    for e in sorted(events, key=lambda x: (x[key], x[ts_field])):
        k, attrs = e[key], tuple(e.get(a) for a in tracked)
        cur = current.get(k)
        if cur is not None and cur["_attrs"] == attrs:
            continue                                     # nothing tracked changed: no new version
        if cur is not None:
            cur["valid_to"], cur["is_current"] = e[ts_field], False
        row = {key: k, **{a: e.get(a) for a in tracked}, "version": (cur["version"] + 1) if cur else 1,
               "valid_from": e[ts_field], "valid_to": OPEN_END, "is_current": True, "_attrs": attrs}
        out.append(row)
        current[k] = row
    for r in out:
        r.pop("_attrs")
    return out


def version_at(history: list, key: str, k, at):
    """The version of entity k valid at time 'at' (valid_from <= at < valid_to), or None: the point-in-time join."""
    for r in history:
        if r[key] == k and r["valid_from"] <= at < r["valid_to"]:
            return r
    return None
