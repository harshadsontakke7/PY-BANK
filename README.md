# 🏦 PY BANK

A modern digital banking web app built with **Flask** and **Neon PostgreSQL**. Open an account, deposit, withdraw, send money to other accounts, and watch your balance history on a live chart.

### 🔗 Live demo: **https://py-bank-1e97.onrender.com/dashboard**

> The demo runs on free hosting, so it sleeps after 15 minutes of inactivity. The first visit can take up to a minute to wake up. Please use **test data only**, never real PINs or money.

*Created by Harshad & Dnyanesh.*
*Educational project. Not intended for real banking or real funds.*

---

## ✨ Features

| | |
|---|---|
| **Accounts** | Register with name, account number, 4-digit PIN and opening balance. Duplicate account numbers are blocked. |
| **Secure login** | Account number + PIN, signed sessions, 30-minute inactivity timeout. |
| **Dashboard** | Welcome banner, balance, total deposits, total withdrawals, transaction count, and recent transactions, all from your own records. |
| **Balance chart** | Interactive Chart.js line graph with 7-day, 30-day and all-time ranges. |
| **Deposit / Withdraw** | Validated amounts, overdraft protection, instant balance update. |
| **Transfer money** | Send to any account number. Both balances update together, or not at all. |
| **Transaction history** | Search, sort by date, filter by type, coloured type labels, pagination. |
| **CSV export** | Download your history (respects the current search and filters). |
| **Profile & balance** | Account details with a show/hide balance toggle. |
| **Responsive UI** | Desktop, tablet and mobile with a collapsible sidebar. |

## 🧰 Tech stack

- **Backend:** Python, Flask, Gunicorn
- **Database:** Neon PostgreSQL via `psycopg` 3
- **Frontend:** HTML5, CSS3, JavaScript, Bootstrap 5, Chart.js, Font Awesome
- **Security:** Flask-WTF (CSRF), Flask-Limiter (rate limits)
- **Hosting:** Render (app) + Neon (database)

## 📁 Project structure

```
PY-BANK-FLASK/
├── app.py              Routes, sessions, CSRF, rate limits, error pages
├── database.py         All SQL: parameterised, transactional, row-locked
├── security.py         PIN hashing and input validation (no third-party imports)
├── migrations.sql      Safe, additive schema migration
├── requirements.txt
├── Procfile · gunicorn.conf.py · render.yaml
├── .env.example        Template for local settings (never commit .env)
├── templates/          Jinja2 pages
├── static/             CSS, JS, images
└── tests/              Unit tests for hashing and validation
```

## 🚀 Run locally

Requires **Python 3.10+** (3.12 recommended).

```bash
# 1. Install dependencies
python -m pip install -r requirements.txt

# 2. Create your settings file
cp .env.example .env          # Windows: copy .env.example .env

# 3. Edit .env and fill in DATABASE_URL and SECRET_KEY

# 4. Start the app
python app.py                 # http://127.0.0.1:5000
```

Generate a secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Run the unit tests (no database needed):

```bash
python -m unittest discover tests
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | Neon connection string, ending in `?sslmode=require` |
| `SECRET_KEY` | Yes | Long random string used to sign sessions |
| `FLASK_DEBUG` | Local only | Set to `1` for development. **Leave unset in production.** |
| `APP_TIMEZONE` | No | Display timezone (default `Asia/Kolkata`) |
| `LOG_LEVEL` | No | Default `INFO` |

> Never commit your `.env` file or paste credentials into the repo.

## ☁️ Deploy

**Database (Neon):** create a project, open **Connect**, and copy the PostgreSQL connection string.

**App (Render):**

1. Push this repo to GitHub.
2. Render → **New → Web Service** → select the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app -c gunicorn.conf.py`
5. Environment variables: `DATABASE_URL`, `SECRET_KEY`, `PYTHON_VERSION=3.12.8`
6. Health check path: `/healthz`

Free-plan limits change over time, so check Render's and Neon's pricing pages.

## 🗄️ Database

The app uses two tables, created automatically if they don't exist.

**`accounts`**: `account_no` (PK), `name`, `pin_salt`, `pin_hash`, `balance`, `created_at`

**`transactions`**: `transaction_id` (UUID, PK), `account_no` (FK), `transaction_type`, `amount`, `previous_balance`, `current_balance`, `created_at`, `counterparty_account`

Transaction types: `Opening`, `Deposit`, `Withdraw`, `Transfer In`, `Transfer Out`.

### Migration from the original Streamlit version

`migrations.sql` runs automatically at start-up and is safe to repeat. It only **adds** a nullable `counterparty_account` column and **widens** the transaction-type check to allow transfers. Existing accounts, PINs and transactions are untouched. Back up first by creating a Neon branch.

## 🔒 Security

- **PIN hashing:** PBKDF2-HMAC-SHA256, 300,000 iterations, random 16-byte salt, constant-time comparison. No plain-text PINs anywhere.
- **Sessions:** `HttpOnly`, `Secure`, `SameSite=Lax` cookies; session cleared on login and logout.
- **CSRF protection** on every form; logout is POST-only.
- **Rate limiting** on login, registration and transfers (per server process).
- **Access control:** every query is scoped to the logged-in account. No URL or form field chooses whose data is shown.
- **SQL injection:** all values parameterised; sorting and filters are whitelisted.
- **Concurrency:** `SELECT … FOR UPDATE` row locks inside a single transaction; transfers lock both accounts in a fixed order to avoid deadlocks.
- **Headers:** Content-Security-Policy, `X-Frame-Options`, `nosniff`, HSTS, and `no-store` caching on logged-in pages.
- **Privacy:** other parties' account numbers are masked (`••••7890`) in history and CSV.

## 📝 Notes

- Dashboard **Total Deposits** = `Deposit` + `Transfer In`; **Total Withdrawals** = `Withdraw` + `Transfer Out`. The `Opening` entry counts toward Total Transactions only.
- New account numbers must be 6 to 18 digits. Existing accounts of any length can still log in.
- Amounts accept at most two decimal places.
- Login rate limits are in-memory per worker, so they slow guessing but don't permanently lock accounts.

## 🧪 Manual test checklist

1. Register an account
2. Log in (and confirm a wrong PIN is rejected)
3. Deposit and withdraw; check the balance and history
4. Try withdrawing more than the balance (should be rejected)
5. Transfer between two accounts; confirm both balances and both history rows
6. Search, sort and filter the history; download the CSV
7. Log in as two different users and confirm each sees only their own data
8. Log out and confirm the dashboard is no longer accessible

## 📄 License & disclaimer

This is an educational demo. It is not a real bank and must not be used to store real funds or personal financial data.
