"""Duplicate customer candidates: the pure-Python twin of 54_silver_customer_duplicates (same rules, same weights).

Finds pairs of customers that are probably the same person. Exact duplicates (same phone AND same email) are already
rejected by the gate rule CUST_DUPLICATE; these rules catch the partial matches. A person reviews every pair.
crm.customers has no address column, so the city is used in its place.
"""
from itertools import combinations

# reason -> weight; score of a pair = sum of the weights of its reasons, at most 1.0
WEIGHTS = {
    "SAME_PHONE_SAME_EMAIL": 0.9,   # safety net: the gate should already have rejected these
    "SAME_PHONE_DIFF_EMAIL": 0.6,
    "SAME_EMAIL_DIFF_PHONE": 0.5,
    "SAME_NAME_SAME_CITY": 0.3,
    "SIMILAR_NAME_SAME_CITY": 0.2,
}
REASONS = tuple(WEIGHTS)
MAX_NAME_DISTANCE = 2               # "similar name" = at most 2 letters added, removed or changed
ACCENTS, PLAIN = "àáâäèéêëìíîïòóôöùúûüçñ", "aaaaeeeeiiiioooouuuucn"   # same map as F.translate in the notebook
_ACCENT_MAP = str.maketrans(ACCENTS, PLAIN)


def normalize_name(first_name, last_name):
    """'  Zoë ', 'van  Dijk' -> 'zoe van dijk'; None when there is no name at all."""
    name = " ".join(p.strip() for p in (first_name, last_name) if p and p.strip()).lower().translate(_ACCENT_MAP)
    name = " ".join(name.split())
    return name or None


def normalize_city(city):
    return city.strip().lower() if city and city.strip() else None


def levenshtein(a: str, b: str) -> int:
    """Number of single-letter edits (insert, delete, replace) to turn a into b; same as Spark's levenshtein()."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _clean(value, lower=False):
    v = str(value).strip() if value is not None else ""
    v = v.lower() if lower else v
    return v or None


def prepare(customer: dict) -> dict:
    """Raw CRM row -> the fields the rules compare (phone trimmed, email trimmed and lower case, like Silver)."""
    return {
        "customer_id": customer["customer_id"],
        "msisdn": _clean(customer.get("msisdn")),
        "email": _clean(customer.get("email"), lower=True),
        "name": normalize_name(customer.get("first_name"), customer.get("last_name")),
        "city": normalize_city(customer.get("city")),
    }


def match_reasons(a: dict, b: dict) -> list[str]:
    """Why two prepared customers are probably the same person; [] when they are not a candidate pair."""
    same_phone = a["msisdn"] is not None and a["msisdn"] == b["msisdn"]
    same_email = a["email"] is not None and a["email"] == b["email"]
    same_city = a["city"] is not None and a["city"] == b["city"]
    dist = levenshtein(a["name"], b["name"]) if a["name"] and b["name"] else None
    reasons = []
    if same_phone and same_email:
        reasons.append("SAME_PHONE_SAME_EMAIL")
    if same_phone and not same_email:          # a missing email counts as different
        reasons.append("SAME_PHONE_DIFF_EMAIL")
    if same_email and not same_phone:
        reasons.append("SAME_EMAIL_DIFF_PHONE")
    if same_city and dist == 0:
        reasons.append("SAME_NAME_SAME_CITY")
    if same_city and dist is not None and 0 < dist <= MAX_NAME_DISTANCE:
        reasons.append("SIMILAR_NAME_SAME_CITY")
    return reasons


def score(reasons: list[str]) -> float:
    return min(1.0, round(sum(WEIGHTS[r] for r in reasons), 2))


def find_pairs(customers: list[dict]) -> list[dict]:
    """Every candidate pair, customer_id_a < customer_id_b, strongest first. O(n²): for tests and small samples."""
    prepared = sorted((prepare(c) for c in customers), key=lambda c: c["customer_id"])
    out = []
    for a, b in combinations(prepared, 2):
        reasons = match_reasons(a, b)
        if reasons:
            out.append({"pair_id": f"{a['customer_id']}-{b['customer_id']}", "customer_id_a": a["customer_id"],
                        "customer_id_b": b["customer_id"], "reasons": reasons, "score": score(reasons)})
    return sorted(out, key=lambda p: (-p["score"], p["customer_id_a"], p["customer_id_b"]))
