"""All PostgreSQL access for PY BANK.

* Schema is identical to the original Streamlit app (accounts / transactions).
* Every statement is parameterised.
* Every money movement runs in ONE transaction and locks the affected
  account rows with SELECT ... FOR UPDATE.
"""
import logging
import os
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from security import MAX_AMOUNT, hash_pin, verify_pin

log = logging.getLogger("pybank.db")

LOCAL_TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Kolkata"))
SCHEMA_LOCK_ID = 748_201  # arbitrary advisory-lock key for start-up migration

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_no TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    pin_salt TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    balance NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id UUID PRIMARY KEY,
    account_no TEXT NOT NULL REFERENCES accounts(account_no),
    transaction_type TEXT NOT NULL
        CHECK (transaction_type IN ('Opening', 'Deposit', 'Withdraw')),
    amount NUMERIC(14, 2) NOT NULL CHECK (amount >= 0),
    previous_balance NUMERIC(14, 2) NOT NULL,
    current_balance NUMERIC(14, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

TYPE_FILTERS = {
    "all": None,
    "Deposit": "Deposit",
    "Withdraw": "Withdraw",
    "Transfer In": "Transfer In",
    "Transfer Out": "Transfer Out",
    "Opening": "Opening",
}
SORTS = {"newest": "DESC", "oldest": "ASC"}
DEPOSIT_TYPES = ("Deposit", "Transfer In")
WITHDRAW_TYPES = ("Withdraw", "Transfer Out")


class BankError(ValueError):
    """A problem the customer can understand and fix."""


# ---------------------------------------------------------------- connection
def get_connection():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")
    return psycopg.connect(url, connect_timeout=10, row_factory=dict_row)


def initialize_database():
    """Create tables if missing and apply the safe migration (idempotent)."""
    migration = (Path(__file__).parent / "migrations.sql").read_text(encoding="utf-8")
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Serialise start-up between several gunicorn workers.
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_ID,))
            cur.execute(BASE_SCHEMA)
            cur.execute(migration)
    log.info("Database schema is ready.")


# ------------------------------------------------------------------ accounts
def create_account(name: str, account_no: str, pin: str, opening_balance: Decimal):
    """Raises psycopg.errors.UniqueViolation if the account number exists."""
    salt, digest = hash_pin(pin)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO accounts (account_no, name, pin_salt, pin_hash, balance)
                   VALUES (%s, %s, %s, %s, %s)""",
                (account_no, name.strip(), salt, digest, opening_balance),
            )
            cur.execute(
                """INSERT INTO transactions
                       (transaction_id, account_no, transaction_type, amount,
                        previous_balance, current_balance)
                   VALUES (%s, %s, 'Opening', %s, 0, %s)""",
                (uuid.uuid4(), account_no, opening_balance, opening_balance),
            )


def authenticate(account_no: str, pin: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT account_no, name, pin_salt, pin_hash FROM accounts WHERE account_no = %s",
                (account_no,),
            )
            row = cur.fetchone()
    if not row:
        # Burn the same CPU time so response time doesn't reveal valid accounts.
        verify_pin(pin, "00" * 16, "0" * 64)
        return None
    if verify_pin(pin, row["pin_salt"], row["pin_hash"]):
        return {"account_no": row["account_no"], "name": row["name"]}
    return None


def get_account(account_no: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT account_no, name, balance, created_at FROM accounts WHERE account_no = %s",
                (account_no,),
            )
            return cur.fetchone()


# -------------------------------------------------------------- money moving
def _insert_tx(cur, account_no, tx_type, amount, previous, current, counterparty=None):
    cur.execute(
        """INSERT INTO transactions
               (transaction_id, account_no, transaction_type, amount,
                previous_balance, current_balance, counterparty_account)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (uuid.uuid4(), account_no, tx_type, amount, previous, current, counterparty),
    )


def move_money(account_no: str, amount: Decimal, transaction_type: str) -> Decimal:
    if transaction_type not in ("Deposit", "Withdraw"):
        raise BankError("Invalid transaction type.")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT balance FROM accounts WHERE account_no = %s FOR UPDATE",
                (account_no,),
            )
            row = cur.fetchone()
            if not row:
                raise BankError("Account was not found.")
            previous = Decimal(row["balance"])
            if transaction_type == "Withdraw":
                if amount > previous:
                    raise BankError("Insufficient balance.")
                current = previous - amount
            else:
                current = previous + amount
                if current > MAX_AMOUNT:
                    raise BankError("This deposit would exceed the maximum balance.")
            cur.execute(
                "UPDATE accounts SET balance = %s WHERE account_no = %s",
                (current, account_no),
            )
            _insert_tx(cur, account_no, transaction_type, amount, previous, current)
    return current


def transfer(sender: str, recipient: str, amount: Decimal) -> Decimal:
    """Atomically move money between two accounts; returns sender's new balance."""
    if sender == recipient:
        raise BankError("You cannot transfer money to your own account.")
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock both rows in a fixed order so two opposite transfers can't deadlock.
            cur.execute(
                """SELECT account_no, balance FROM accounts
                   WHERE account_no IN (%s, %s) ORDER BY account_no FOR UPDATE""",
                (sender, recipient),
            )
            balances = {r["account_no"]: Decimal(r["balance"]) for r in cur.fetchall()}
            if sender not in balances:
                raise BankError("Your account could not be found.")
            if recipient not in balances:
                raise BankError("Recipient account was not found.")
            s_prev, r_prev = balances[sender], balances[recipient]
            if amount > s_prev:
                raise BankError("Insufficient balance.")
            s_new, r_new = s_prev - amount, r_prev + amount
            if r_new > MAX_AMOUNT:
                raise BankError("The recipient's account cannot accept this amount.")
            cur.execute("UPDATE accounts SET balance = %s WHERE account_no = %s", (s_new, sender))
            cur.execute("UPDATE accounts SET balance = %s WHERE account_no = %s", (r_new, recipient))
            _insert_tx(cur, sender, "Transfer Out", amount, s_prev, s_new, recipient)
            _insert_tx(cur, recipient, "Transfer In", amount, r_prev, r_new, sender)
    return s_new


# ------------------------------------------------------------------- queries
_TX_COLUMNS = """transaction_id::text AS transaction_id, transaction_type, amount,
                 previous_balance, current_balance, created_at, counterparty_account"""


def dashboard_data(account_no: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT account_no, name, balance, created_at FROM accounts WHERE account_no = %s",
                (account_no,),
            )
            account = cur.fetchone()
            cur.execute(
                """SELECT
                     COALESCE(SUM(amount) FILTER (WHERE transaction_type = ANY(%s)), 0) AS total_deposits,
                     COALESCE(SUM(amount) FILTER (WHERE transaction_type = ANY(%s)), 0) AS total_withdrawals,
                     COUNT(*) AS total_transactions
                   FROM transactions WHERE account_no = %s""",
                (list(DEPOSIT_TYPES), list(WITHDRAW_TYPES), account_no),
            )
            stats = cur.fetchone()
            cur.execute(
                f"""SELECT {_TX_COLUMNS} FROM transactions
                    WHERE account_no = %s ORDER BY created_at DESC, transaction_id LIMIT 5""",
                (account_no,),
            )
            recent = cur.fetchall()
    return account, stats, recent


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filters(account_no, q, tx_type):
    where, params = ["account_no = %s"], [account_no]
    if q:
        like = f"%{_escape_like(q)}%"
        where.append(
            """(transaction_id::text ILIKE %s OR transaction_type ILIKE %s
                OR amount::text ILIKE %s OR COALESCE(counterparty_account, '') ILIKE %s)"""
        )
        params += [like, like, like, like]
    wanted = TYPE_FILTERS.get(tx_type)
    if wanted:
        where.append("transaction_type = %s")
        params.append(wanted)
    return " AND ".join(where), params


def list_transactions(account_no, q="", sort="newest", tx_type="all", page=1, per_page=15):
    """Return (rows, total, page, pages) for ONE account only."""
    direction = SORTS.get(sort, "DESC")  # whitelisted, never user text
    where, params = _filters(account_no, q, tx_type)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM transactions WHERE {where}", params)
            total = cur.fetchone()["n"]
            pages = max(1, -(-total // per_page))
            page = min(max(1, page), pages)
            cur.execute(
                f"""SELECT {_TX_COLUMNS} FROM transactions WHERE {where}
                    ORDER BY created_at {direction}, transaction_id
                    LIMIT %s OFFSET %s""",
                params + [per_page, (page - 1) * per_page],
            )
            rows = cur.fetchall()
    return rows, total, page, pages


def export_transactions(account_no, q="", sort="newest", tx_type="all"):
    direction = SORTS.get(sort, "DESC")
    where, params = _filters(account_no, q, tx_type)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT {_TX_COLUMNS} FROM transactions WHERE {where}
                    ORDER BY created_at {direction}, transaction_id""",
                params,
            )
            return cur.fetchall()


def balance_history(account_no: str, range_key: str = "7d"):
    """Closing balance per local calendar day, carried forward on quiet days."""
    today = datetime.now(LOCAL_TZ).date()
    days = {"7d": 7, "30d": 30}.get(range_key)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MIN(created_at) AS first_at FROM transactions WHERE account_no = %s",
                (account_no,),
            )
            first_at = cur.fetchone()["first_at"]
            if first_at is None:
                return {"labels": [], "values": []}
            first_day = first_at.astimezone(LOCAL_TZ).date()
            start_day = max(first_day, today - timedelta(days=days - 1)) if days else first_day
            start_dt = datetime.combine(start_day, time.min, tzinfo=LOCAL_TZ)

            cur.execute(
                """SELECT current_balance FROM transactions
                   WHERE account_no = %s AND created_at < %s
                   ORDER BY created_at DESC LIMIT 1""",
                (account_no, start_dt),
            )
            base = cur.fetchone()
            cur.execute(
                """SELECT created_at, current_balance FROM transactions
                   WHERE account_no = %s AND created_at >= %s
                   ORDER BY created_at ASC""",
                (account_no, start_dt),
            )
            rows = cur.fetchall()

    closing = {}
    for r in rows:  # ascending, so the last row of a day wins
        closing[r["created_at"].astimezone(LOCAL_TZ).date()] = r["current_balance"]

    running = base["current_balance"] if base else Decimal(0)
    points, day = [], start_day
    while day <= today:
        running = closing.get(day, running)
        points.append((day, running))
        day += timedelta(days=1)

    if len(points) > 240:  # keep "All time" readable on long histories
        step = -(-len(points) // 240)
        points = points[::step] + ([points[-1]] if (len(points) - 1) % step else [])

    fmt = "%d %b %y" if (today - start_day).days > 300 else "%d %b"
    return {
        "labels": [d.strftime(fmt) for d, _ in points],
        "values": [float(v) for _, v in points],
    }
