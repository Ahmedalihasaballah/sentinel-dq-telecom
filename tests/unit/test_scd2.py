from datetime import datetime

from sentinel_dq.scd2.merge import OPEN_END, build_history, version_at

T = [datetime(2026, 9, 1), datetime(2026, 9, 15), datetime(2026, 10, 1), datetime(2026, 10, 9)]
EVENTS = [
    {"customer_id": 1, "plan_id": 3, "city": "Utrecht", "ts": T[0]},
    {"customer_id": 1, "plan_id": 3, "city": "Utrecht", "ts": T[1]},   # nothing tracked changed
    {"customer_id": 1, "plan_id": 5, "city": "Utrecht", "ts": T[2]},   # plan change -> new version
    {"customer_id": 2, "plan_id": 1, "city": "Breda", "ts": T[0]},
]


def test_new_version_only_when_a_tracked_attribute_changes():
    h = build_history(EVENTS, "customer_id", ["plan_id", "city"])
    c1 = [r for r in h if r["customer_id"] == 1]
    assert [r["version"] for r in c1] == [1, 2]
    assert c1[0]["valid_to"] == T[2] and not c1[0]["is_current"]
    assert c1[1]["valid_to"] == OPEN_END and c1[1]["is_current"]


def test_exactly_one_current_version_and_no_overlap():
    h = build_history(EVENTS, "customer_id", ["plan_id", "city"])
    for k in (1, 2):
        versions = sorted((r for r in h if r["customer_id"] == k), key=lambda r: r["valid_from"])
        assert sum(r["is_current"] for r in versions) == 1
        assert all(a["valid_to"] <= b["valid_from"] for a, b in zip(versions, versions[1:]))


def test_rebuild_is_idempotent_and_order_independent():
    assert build_history(EVENTS, "customer_id", ["plan_id"]) == build_history(list(reversed(EVENTS)), "customer_id", ["plan_id"])


def test_point_in_time_lookup():
    h = build_history(EVENTS, "customer_id", ["plan_id", "city"])
    assert version_at(h, "customer_id", 1, datetime(2026, 9, 20))["plan_id"] == 3
    assert version_at(h, "customer_id", 1, datetime(2026, 10, 5))["plan_id"] == 5
    assert version_at(h, "customer_id", 1, datetime(2026, 8, 1)) is None   # before the first version
