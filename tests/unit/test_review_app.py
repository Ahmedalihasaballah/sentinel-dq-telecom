import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "review_app"))

from logic import SOURCE_GROUPS, allowed_datasets, authenticate, diff_rows, hash_password, load_contracts, safe_name  # noqa: E402


def test_password_hash_and_verify():
    users = {"admin": {**hash_password("correct horse battery"), "role": "admin", "datasets": ["*"]}}
    assert authenticate(users, "admin", "correct horse battery")
    assert authenticate(users, "admin", "wrong") is None
    assert authenticate(users, "nobody", "correct horse battery") is None
    assert "correct" not in str(users)  # only the hash is stored


def test_allowed_datasets():
    all_ds = ["billing_payments", "crm_customers"]
    assert allowed_datasets({"role": "admin", "datasets": ["*"]}, all_ds) == all_ds
    assert allowed_datasets({"role": "owner", "datasets": ["billing_payments"]}, all_ds) == ["billing_payments"]
    assert allowed_datasets({"role": "owner", "datasets": []}, all_ds) == []


def test_diff_rows_returns_full_map_and_changes():
    cols = ["payment_id", "method", "amount"]
    original = [{"_row_id": "a", "payment_id": "1", "method": None, "amount": "35.00"},
                {"_row_id": "b", "payment_id": "2", "method": None, "amount": "48.50"}]
    edited = [{"_row_id": "a", "payment_id": "1", "method": "IDEAL", "amount": "35.00"},
              {"_row_id": "b", "payment_id": "2", "method": float("nan"), "amount": "48.50"}]
    out = diff_rows(original, edited, cols)
    assert len(out) == 1
    assert out[0]["values"] == {"payment_id": "1", "method": "IDEAL", "amount": "35.00"}
    assert out[0]["changes"] == [("method", None, "IDEAL")]


def test_contracts_load_and_names_are_safe():
    contracts = load_contracts(ROOT / "contract")
    assert "billing_payments" in contracts and "method" in contracts["billing_payments"]
    try:
        safe_name("x; DROP TABLE y")
        assert False
    except ValueError:
        pass


def test_every_dataset_belongs_to_exactly_one_source_user():
    datasets = sorted(load_contracts(ROOT / "contract"))
    grouped = sorted(d for ds in SOURCE_GROUPS.values() for d in ds)
    assert grouped == datasets


def test_diff_decisions_keeps_only_changed_valid_decisions():
    from logic import diff_decisions
    original = [{"pair_id": "1-2", "review_status": "PENDING", "review_note": None},
                {"pair_id": "3-4", "review_status": "PENDING", "review_note": None},
                {"pair_id": "5-6", "review_status": "NOT_SAME", "review_note": "checked"},
                {"pair_id": "7-8", "review_status": "PENDING", "review_note": None}]
    edited = [{"pair_id": "1-2", "review_status": "SAME_PERSON", "review_note": "same IBAN"},
              {"pair_id": "3-4", "review_status": "PENDING", "review_note": float("nan")},   # untouched
              {"pair_id": "5-6", "review_status": "NOT_SAME", "review_note": "checked twice"},
              {"pair_id": "7-8", "review_status": "MERGED", "review_note": None}]           # not a valid status
    assert diff_decisions(original, edited) == [
        {"pair_id": "1-2", "old_status": "PENDING", "new_status": "SAME_PERSON", "note": "same IBAN"},
        {"pair_id": "5-6", "old_status": "NOT_SAME", "new_status": "NOT_SAME", "note": "checked twice"},
    ]


def test_only_crm_owners_and_admins_review_duplicates():
    from logic import can_review_duplicates
    assert can_review_duplicates(["crm_customers", "crm_plans"])
    assert not can_review_duplicates(["billing_payments"])


def test_review_app_reasons_match_the_rules():
    from logic import DUPLICATE_REASONS
    from sentinel_dq.quality.duplicates import REASONS
    assert DUPLICATE_REASONS == REASONS
