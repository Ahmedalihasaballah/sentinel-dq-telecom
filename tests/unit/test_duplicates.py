from sentinel_dq.quality.duplicates import (WEIGHTS, find_pairs, levenshtein, match_reasons, normalize_name, prepare,
                                            score)


def cust(cid, first="Sophie", last="Bakker", email=None, msisdn=None, city="Utrecht"):
    return {"customer_id": cid, "first_name": first, "last_name": last, "city": city,
            "email": email or f"c{cid}@example.nl", "msisdn": msisdn or f"+316{cid:08d}"}


def reasons_of(a, b):
    return match_reasons(prepare(a), prepare(b))


def test_levenshtein():
    assert levenshtein("sophie", "sofie") == 2
    assert levenshtein("finn", "finn") == 0
    assert levenshtein("", "abc") == 3


def test_normalize_name():
    assert normalize_name("  Zoë ", "van  Dijk") == "zoe van dijk"
    assert normalize_name(None, " ") is None


def test_same_phone_different_email():
    a = cust(1, msisdn="+31611111111", email="a@example.nl", city="Breda")
    b = cust(2, first="Daan", last="Smit", msisdn="+31611111111", email="b@example.nl", city="Delft")
    assert reasons_of(a, b) == ["SAME_PHONE_DIFF_EMAIL"]


def test_same_phone_missing_email_counts_as_different():
    a = cust(1, msisdn="+31611111111", city="Breda")
    b = {**cust(2, first="Daan", msisdn="+31611111111", city="Delft"), "email": None}
    assert reasons_of(a, b) == ["SAME_PHONE_DIFF_EMAIL"]


def test_same_email_different_phone_ignores_case_and_spaces():
    a = cust(1, email="sophie@example.nl", city="Breda")
    b = cust(2, first="Daan", email=" SOPHIE@example.nl ", city="Delft")
    assert reasons_of(a, b) == ["SAME_EMAIL_DIFF_PHONE"]


def test_similar_name_needs_the_same_city():
    assert reasons_of(cust(1, first="Sophie"), cust(2, first="Sofie")) == ["SIMILAR_NAME_SAME_CITY"]
    assert reasons_of(cust(1, first="Sophie"), cust(2, first="Sofie", city="Breda")) == []


def test_accents_and_case_give_the_same_name():
    assert reasons_of(cust(1, first="Zoë"), cust(2, first="ZOE", city=" utrecht ")) == ["SAME_NAME_SAME_CITY"]


def test_different_people_are_not_a_pair():
    assert reasons_of(cust(1, first="Sophie", last="Bakker"), cust(2, first="Daan", last="de Jong")) == []


def test_reasons_combine_and_score_is_capped():
    a = cust(1, msisdn="+31611111111")
    b = cust(2, first="Sofie", msisdn="+31611111111")
    assert reasons_of(a, b) == ["SAME_PHONE_DIFF_EMAIL", "SIMILAR_NAME_SAME_CITY"]
    assert score(["SAME_PHONE_DIFF_EMAIL", "SIMILAR_NAME_SAME_CITY"]) == 0.8
    exact = reasons_of(cust(1, msisdn="+31611111111", email="x@example.nl"),
                       cust(2, msisdn="+31611111111", email="x@example.nl"))
    assert exact == ["SAME_PHONE_SAME_EMAIL", "SAME_NAME_SAME_CITY"]
    assert score(exact) == 1.0
    assert all(0 < w <= 1 for w in WEIGHTS.values())


def test_find_pairs_lists_each_pair_once_lowest_id_first_strongest_first():
    customers = [cust(3, first="Sofie", msisdn="+31611111111"),          # phone of 1, similar name, same city
                 cust(1, first="Sophie", msisdn="+31611111111"),
                 cust(2, first="Daan", last="Smit", email="c1@example.nl", city="Breda"),   # email of 1
                 cust(4, first="Lucas", last="Visser", city="Delft")]                       # nobody
    pairs = find_pairs(customers)
    assert [(p["pair_id"], p["reasons"], p["score"]) for p in pairs] == [
        ("1-3", ["SAME_PHONE_DIFF_EMAIL", "SIMILAR_NAME_SAME_CITY"], 0.8),
        ("1-2", ["SAME_EMAIL_DIFF_PHONE"], 0.5),
    ]
    assert all(p["customer_id_a"] < p["customer_id_b"] for p in pairs)
