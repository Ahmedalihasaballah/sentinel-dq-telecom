"""PII hashing and masking, identical to hash_pii / mask_msisdn / mask_email in 49_silver_lib."""
import hashlib

from .config import PII_SALT


def hash_pii(value, lower: bool = False, salt: str = PII_SALT):
    """sha256(salt + trimmed value) as hex; None stays None. Same hash = same person, without storing the raw value."""
    if value is None:
        return None
    v = str(value).strip()
    v = v.lower() if lower else v
    return hashlib.sha256((salt + v).encode("utf-8")).hexdigest()


def mask_msisdn(value):
    """+31612345678 -> +316****78 (first 4 and last 2 characters kept)."""
    if value is None:
        return None
    v = str(value)
    return v[:4] + "****" + v[-2:]


def mask_email(value):
    """luuk.200@example.nl -> l***@example.nl."""
    if value is None:
        return None
    v = str(value)
    return v[:1] + "***@" + v.split("@")[-1]
