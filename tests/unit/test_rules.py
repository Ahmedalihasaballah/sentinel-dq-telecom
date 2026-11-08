from datetime import datetime, timezone
from pathlib import Path

from sentinel_dq.quality.contract_loader import load_contracts, validate_contract
from sentinel_dq.quality.rules import apply_fix_steps, evaluate, fix_row, try_cast

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = load_contracts(ROOT / "contract")
NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def customer(**over):
    row = {"customer_id": "1", "first_name": "Anna", "last_name": "Visser", "email": "anna.1@example.nl",
           "msisdn": "+31612345678", "city": "Utrecht", "country": "NL", "status": "ACTIVE", "plan_id": "3",
           "created_at": "2026-09-01T08:00:00.000000Z", "updated_at": "2026-09-01T08:00:00.000000Z"}
    row.update(over)
    return row


def verdict(rows, dataset="crm_customers"):
    return evaluate(rows, CONTRACTS[dataset], now=NOW)["results"]


def test_all_contracts_valid_and_disabled_ones_skipped(tmp_path):
    assert "app_events" in CONTRACTS              # streamed app events are part of the pipeline again
    for name, c in CONTRACTS.items():
        assert validate_contract(c) == [], name
    (tmp_path / "_off.yaml").write_text("dataset: off\n", encoding="utf-8")   # files starting with "_" are disabled
    assert load_contracts(tmp_path) == {}


def test_app_event_rules():
    good = {"event_id": "EVT-1", "customer_id": "7", "event_type": "login", "app_version": "6.0",
            "event_ts": "2026-10-12T10:00:00Z"}
    assert verdict([good], "app_events")[0]["status"] == "PASS"
    bad_type = verdict([dict(good, event_type="unknown_evt")], "app_events")[0]
    assert bad_type["status"] == "REJECT" and "APP_EVENT_TYPE_DOMAIN" in bad_type["failed_rules"]
    no_customer = verdict([dict(good, customer_id=None)], "app_events")[0]
    assert "APP_CUSTOMER_PRESENT" in no_customer["failed_rules"]
    odd_version = verdict([dict(good, app_version="v6")], "app_events")[0]
    assert odd_version["status"] == "PASS" and "APP_VERSION_FORMAT" in odd_version["flags"]


def test_clean_customer_passes():
    assert verdict([customer()])[0]["status"] == "PASS"


def test_local_phone_format_goes_to_autofix_and_fix_makes_it_pass():
    bad = customer(msisdn="0612345678")
    assert verdict([bad])[0] == {"status": "AUTOFIX", "failed_rules": ["CUST_MSISDN_FORMAT"], "flags": []}
    fixed = fix_row(bad, CONTRACTS["crm_customers"])
    assert fixed["msisdn"] == "+31612345678"
    assert verdict([fixed])[0]["status"] == "PASS"


def test_unfixable_phone_stays_wrong_after_fix():
    for value in ("ABC", "0612345", "+316773092"):
        fixed = fix_row(customer(msisdn=value), CONTRACTS["crm_customers"])
        assert verdict([fixed])[0]["status"] != "PASS", value


def test_domain_and_future_date_are_rejected():
    v = verdict([customer(status="UNKNOWN"), customer(customer_id="2", created_at="2026-11-30T00:00:00Z")])
    assert v[0]["status"] == "REJECT" and "CUST_STATUS_DOMAIN" in v[0]["failed_rules"]
    assert v[1]["status"] == "REJECT" and "CUST_CREATED_NOT_FUTURE" in v[1]["failed_rules"]


def test_negative_payment_is_flagged_not_rejected():
    row = {"payment_id": "1", "invoice_id": "1", "amount": "-6.22", "method": "SEPA", "status": "PAID",
           "paid_at": "2026-08-31T12:00:00Z"}
    r = verdict([row], "billing_payments")[0]
    assert r["status"] == "PASS" and "PAY_AMOUNT_NON_NEGATIVE" in r["flags"]


def test_text_in_numeric_column_fails_type_rule():
    row = {"cdr_id": "CDR-1", "msisdn": "+31612345678", "event_type": "VOICE", "event_ts": "2026-10-05 10:00:00",
           "duration_sec": "abc", "data_mb": "0", "cell_id": "CELL-001", "call_result": "COMPLETED"}
    r = verdict([row], "network_cdr")[0]
    assert r["status"] == "REJECT" and "TYPE_DURATION_SEC" in r["failed_rules"]


def test_try_cast():
    assert try_cast("42", "bigint") == 42 and try_cast("4.2", "bigint") is None
    assert str(try_cast("51.56", "decimal(10,2)")) == "51.56"
    assert try_cast("", "int") is None and try_cast("x", "date") is None


def test_every_fix_example_in_the_contracts_works():
    for c in CONTRACTS.values():
        for fx in c.get("fixes", []):
            for raw, expected in fx.get("examples", []):
                assert apply_fix_steps(raw, fx["steps"]) == expected, (c["dataset"], raw)

