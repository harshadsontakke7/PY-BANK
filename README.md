# PY BANK (Flask edition)

A Flask + Neon PostgreSQL banking demo converted from the original Streamlit app.
Bootstrap 5, Chart.js and Font Awesome are loaded from CDNs; there is no build step.

> Educational project. Not intended for real banking or real funds.
>
> ## Live demo

**https://py-bank-1e97.onrender.com/dashboard**

> The app runs on Render's free plan, so it sleeps after 15 minutes without traffic. The first visit can take about a minute to wake up. Please use test data only, not real PINs or money.

## What was kept from your Streamlit app

| Item | Result |
|---|---|
| Tables `accounts`, `transactions` | Unchanged. Existing rows are never touched. |
| PIN hashing | PBKDF2-HMAC-SHA256, 300,000 iterations, 16-byte random salt, hex-encoded in `pin_salt` / `pin_hash`. Existing accounts log in with their old PIN. |
| Transaction types | `Opening`, `Deposit`, `Withdraw` are written exactly as before. |
| Row locking | `SELECT ... FOR UPDATE` inside one transaction, as in `move_money()`. |
| `DATABASE_URL` | Same variable name. |

## The one schema change (safe, additive)

Transfers need two new transaction types, and your original `CHECK` only allows three. `migrations.sql` (run automatically at start-up, idempotent) does only this:

1. `ALTER TABLE transactions ADD COLUMN IF NOT EXISTS counterparty_account TEXT;` (nullable)
2. Replaces the `transaction_type` check with one that also allows `Transfer In` and `Transfer Out`. It only *widens* the rule, so every existing row stays valid.

Your old Streamlit app keeps working against the migrated database. **Before first run, create a Neon branch as an instant backup** (Neon console → Branches → Create branch).

## Project layout

```
app.py            routes, sessions, CSRF, rate limits, error pages
database.py       all SQL (parameterised, transactional, row-locked)
security.py       PIN hashing + validation (no third-party imports)
migrations.sql    the additive migration above
templates/        Jinja2 pages        static/   css, js, images
tests/            unit tests for hashing/validation
Procfile · gunicorn.conf.py · render.yaml · requirements.txt · .env.example
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then edit DATABASE_URL and SECRET_KEY
python app.py                   # http://127.0.0.1:5000
python -m unittest discover tests
```

Generate a secret key: `python -c "import secrets; print(secrets.token_hex(32))"`

## Neon connection string

Neon console → your project → **Connect** → copy the PostgreSQL string (it ends in `?sslmode=require`) into `DATABASE_URL`. Use the same project your Streamlit app used so your accounts carry over.

## Upload to GitHub

```bash
git init
git add .
git status                      # confirm .env is NOT listed
git commit -m "PY BANK Flask"
git branch -M main
git remote add origin https://github.com/<you>/PY-BANK-FLASK.git
git push -u origin main
```

`.gitignore` already excludes `.env` and `.streamlit/secrets.toml`. If a credential was ever committed, rotate it in Neon (Roles → reset password).

## Deploy on Render

1. Render dashboard → **New → Web Service** → connect the GitHub repo (or **New → Blueprint** to use `render.yaml`).
2. Runtime **Python 3**, build command `pip install -r requirements.txt`, start command `gunicorn app:app -c gunicorn.conf.py`, instance type **Free**.
3. Environment variables: `DATABASE_URL` (your Neon string), `SECRET_KEY` (random), `PYTHON_VERSION` = `3.12.8`.
4. Health check path: `/healthz`.
5. Deploy, open the `onrender.com` URL.

Free-tier limits change, so check Render's current pricing page. At the time of writing, free web services sleep after about 15 minutes idle and take a while to wake, and Neon's free compute also auto-suspends. The first request after idle can be slow; the app uses a 10 s connect timeout and a 60 s worker timeout to cope.

## Security summary

* PINs: salted PBKDF2-SHA256, constant-time compare, never logged or stored in plain text. Unknown accounts burn equal CPU time so response time doesn't reveal which accounts exist.
* Sessions: signed cookie (`SECRET_KEY`), `HttpOnly`, `Secure`, `SameSite=Lax`, 30-minute sliding expiry, `session.clear()` on login (fixation) and logout.
* CSRF tokens on every POST (Flask-WTF). Logout is POST-only.
* Login: 10/min and 40/hour per IP; registration 20/hour; transfers 30/min. Counters are per worker process (in-memory), so treat this as a speed bump rather than a hard lockout.
* Access control: every query is scoped by the account number stored in the server-side session. No URL or form field ever selects whose data to show.
* SQL: all values parameterised; sort order and type filters are whitelisted; `LIKE` wildcards in searches are escaped.
* Transfers lock both rows in a fixed order (no deadlocks) and write both ledger rows in one transaction.
* Headers: CSP, `X-Frame-Options`, `nosniff`, HSTS (production), `Cache-Control: no-store` on logged-in pages. No inline scripts are used.
* Counterparty account numbers are masked (`••••7890`) in history and CSV.

## Behaviour notes (decisions worth knowing)

* **Dashboard "Total Deposits / Withdrawals"** count `Deposit` + `Transfer In` and `Withdraw` + `Transfer Out`. The `Opening` entry is not counted as a deposit but is counted in Total Transactions.
* **New account numbers** must be 6–18 ASCII digits (your original only required digits). Existing accounts with other lengths can still log in.
* PIN and account fields use ASCII `0-9` only (Python's `str.isdigit()` also accepts characters like `²` and Arabic-Indic digits).
* Amounts accept at most 2 decimal places and are rejected rather than silently rounded.
* Times are shown in `Asia/Kolkata` (override with `APP_TIMEZONE`).
* The balance chart shows each day's closing balance, carrying the last balance forward on days with no activity.

## Your 13-point test checklist

Run these against a Neon **branch** first. "Auto" means covered by the checks I ran in development (see below).

| # | Check | How |
|---|---|---|
| 1 | Registration | Register at `/register`; new row in `accounts` + an `Opening` row |
| 2 | Login | Log in with the new account |
| 3 | Wrong PIN rejected | Expect "Invalid account number or PIN." |
| 4 | Balance correct | `/balance` equals `SELECT balance FROM accounts` |
| 5–6 | Deposit / withdraw | Balance and `previous_balance` → `current_balance` chain update |
| 7 | Overdraw rejected | Withdraw more than the balance → "Insufficient balance." |
| 8 | Transfer | Both balances change; one `Transfer Out` and one `Transfer In` row |
| 9 | History | `/transactions` matches the DB; try search, sort, type filter |
| 10 | CSV | "Download CSV" opens in Excel with ₹ amounts intact |
| 11 | Logout | Dashboard then redirects to login |
| 12 | Isolation | Log in as two users in two browsers; each sees only their own rows |
| 13 | Existing data | `SELECT count(*) FROM accounts/transactions` before vs after first start |

Concurrency spot-check: open two terminals and fire two simultaneous withdrawals of the full balance; exactly one must succeed.
