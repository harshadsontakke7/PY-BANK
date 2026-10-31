"""Pure helpers: PIN hashing, input validation and money formatting.

No third-party imports here, so this module can be unit-tested anywhere.
The PBKDF2 parameters are IDENTICAL to the original Streamlit app, so PINs
of existing accounts keep working.
"""
import hashlib
import hmac
import re
import secrets
from decimal import Decimal, InvalidOperation

PBKDF2_ITERATIONS = 300_000
MAX_AMOUNT = Decimal("999999999999.99")  # NUMERIC(14, 2) upper bound

PIN_RE = re.compile(r"[0-9]{4}")
NEW_ACCOUNT_RE = re.compile(r"[0-9]{6,18}")
RECIPIENT_RE = re.compile(r"[0-9]{1,32}")


def hash_pin(pin: str, salt: bytes | None = None):
    """Return (salt_hex, hash_hex) exactly like the Streamlit app."""
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return salt.hex(), derived.hex()


def verify_pin(pin: str, salt_hex: str, expected_hash: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
    except (ValueError, TypeError):
        return False
    _, actual = hash_pin(pin, salt)
    return hmac.compare_digest(actual, expected_hash or "")


def is_valid_pin(pin: str) -> bool:
    return bool(pin) and PIN_RE.fullmatch(pin) is not None


def parse_amount(value, *, allow_zero: bool = False) -> Decimal:
    """Parse a user supplied amount into a 2-decimal Decimal or raise ValueError."""
    raw = str(value if value is not None else "").strip().replace(",", "")
    if not raw:
        raise ValueError("Enter an amount.")
    try:
        parsed = Decimal(raw)
        if not parsed.is_finite():
            raise InvalidOperation
        amount = parsed.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid amount.")
    if amount != parsed:
        raise ValueError("Amount can have at most 2 decimal places.")
    if amount < 0 or (amount == 0 and not allow_zero):
        raise ValueError("Amount must be greater than ₹0.")
    if amount > MAX_AMOUNT:
        raise ValueError("Amount is too large.")
    return amount


def money(value) -> str:
    return f"₹{Decimal(value):,.2f}"


def mask_account(account_no: str | None) -> str:
    if not account_no:
        return ""
    return "••••" + account_no[-4:] if len(account_no) > 4 else account_no
