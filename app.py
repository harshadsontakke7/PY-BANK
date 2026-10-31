"""PY BANK - Flask edition (Neon PostgreSQL)."""
import csv
import io
import logging
import os
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps

from dotenv import load_dotenv

load_dotenv()

import psycopg  # noqa: E402
from flask import (  # noqa: E402
    Flask, Response, flash, g, jsonify, redirect, render_template, request,
    session, url_for,
)
from flask_limiter import Limiter  # noqa: E402
from flask_limiter.util import get_remote_address  # noqa: E402
from flask_wtf.csrf import CSRFError, CSRFProtect  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

import database as db  # noqa: E402
from security import (  # noqa: E402
    NEW_ACCOUNT_RE, RECIPIENT_RE, is_valid_pin, mask_account, money, parse_amount,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("pybank")

DEBUG = os.getenv("FLASK_DEBUG") == "1"

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

secret_key = os.getenv("SECRET_KEY", "")
if not secret_key:
    if not DEBUG:
        raise RuntimeError("SECRET_KEY is not set. Generate one - see README.md.")
    secret_key = secrets.token_hex(32)
    log.warning("SECRET_KEY missing: using a temporary key (debug mode only).")

app.config.update(
    SECRET_KEY=secret_key,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not DEBUG,
    SESSION_COOKIE_NAME="pybank_session",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    MAX_CONTENT_LENGTH=64 * 1024,
    WTF_CSRF_TIME_LIMIT=None,  # token lives as long as the session
    JSON_SORT_KEYS=False,
)

csrf = CSRFProtect(app)
limiter = Limiter(key_func=get_remote_address, app=app, storage_uri="memory://")

PER_PAGE = 15
_schema_ready = False


# ------------------------------------------------------------------ database
def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    db.initialize_database()
    _schema_ready = True


try:
    if os.getenv("DATABASE_URL"):
        ensure_schema()
    else:
        log.warning("DATABASE_URL is not set.")
except Exception:  # Neon may be waking up; retry lazily on first request
    log.exception("Could not initialise the database at start-up; will retry.")


@app.before_request
def _lazy_schema():
    if not _schema_ready and request.endpoint not in ("healthz", "static"):
        ensure_schema()


# ------------------------------------------------------------ template tools
@app.template_filter("money")
def _money(value):
    return money(value)


@app.template_filter("dt")
def _dt(value, fmt="%d %b %Y, %I:%M %p"):
    return value.astimezone(db.LOCAL_TZ).strftime(fmt) if value else ""


@app.template_filter("short_id")
def _short_id(value):
    return str(value)[:8]


@app.template_filter("mask")
def _mask(value):
    return mask_account(value)


@app.template_filter("tx_class")
def _tx_class(tx_type):
    return {
        "Deposit": "success", "Transfer In": "success",
        "Withdraw": "danger", "Transfer Out": "danger",
    }.get(tx_type, "info")


@app.context_processor
def _inject():
    return {"account": getattr(g, "account", None)}


@app.after_request
def _security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
        "https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
        "img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if not DEBUG:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if session.get("account_no"):
        resp.headers["Cache-Control"] = "no-store"  # never cache banking pages
    return resp


# ---------------------------------------------------------------------- auth
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        account_no = session.get("account_no")
        if not account_no:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        account = db.get_account(account_no)
        if not account:
            session.clear()
            flash("This account could not be found. Please log in again.", "danger")
            return redirect(url_for("login"))
        g.account = account  # ALWAYS the session owner - no ids come from the URL
        return view(*args, **kwargs)
    return wrapped


def greeting():
    hour = datetime.now(db.LOCAL_TZ).hour
    return "Good Morning" if hour < 12 else "Good Afternoon" if hour < 17 else "Good Evening"


# -------------------------------------------------------------------- public
@app.get("/")
def index():
    if session.get("account_no"):
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.get("/healthz")
@csrf.exempt
def healthz():
    return {"status": "ok"}


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("20 per hour", methods=["POST"])
def register():
    if session.get("account_no"):
        return redirect(url_for("dashboard"))
    if request.method == "GET":
        return render_template("register.html", form={})

    form = request.form
    name = " ".join(form.get("name", "").split())
    account_no = form.get("account_no", "").strip()
    pin, confirm = form.get("pin", ""), form.get("confirm_pin", "")
    errors = []

    if not 2 <= len(name) <= 80:
        errors.append("Enter your full name (2 to 80 characters).")
    if not NEW_ACCOUNT_RE.fullmatch(account_no):
        errors.append("Account number must be 6 to 18 digits.")
    if not is_valid_pin(pin):
        errors.append("PIN must be exactly 4 digits.")
    elif pin != confirm:
        errors.append("PINs do not match.")
    try:
        opening = parse_amount(form.get("opening_balance", "0") or "0", allow_zero=True)
    except ValueError as exc:
        errors.append(str(exc).replace("Amount", "Opening balance"))
        opening = None

    if not errors:
        try:
            db.create_account(name, account_no, pin, opening)
        except psycopg.errors.UniqueViolation:
            errors.append("That account number is already registered.")
        else:
            log.info("Account created: %s", mask_account(account_no))
            flash("Account created successfully. You can now log in.", "success")
            return redirect(url_for("login"))

    for e in errors:
        flash(e, "danger")
    return render_template(
        "register.html", form={"name": name, "account_no": account_no,
                               "opening_balance": form.get("opening_balance", "")}
    ), 400


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute;40 per hour", methods=["POST"])
def login():
    if session.get("account_no"):
        return redirect(url_for("dashboard"))
    if request.method == "GET":
        return render_template("login.html", form={})

    account_no = request.form.get("account_no", "").strip()
    pin = request.form.get("pin", "")
    if not RECIPIENT_RE.fullmatch(account_no) or not is_valid_pin(pin):
        flash("Enter a valid account number and 4-digit PIN.", "danger")
        return render_template("login.html", form={"account_no": account_no}), 400

    user = db.authenticate(account_no, pin)
    if not user:
        log.warning("Failed login for %s from %s", mask_account(account_no), get_remote_address())
        flash("Invalid account number or PIN.", "danger")
        return render_template("login.html", form={"account_no": account_no}), 401

    session.clear()  # prevents session fixation
    session["account_no"] = user["account_no"]
    session.permanent = True
    log.info("Login: %s", mask_account(account_no))
    flash(f"Welcome back, {user['name']}!", "success")
    return redirect(url_for("dashboard"))


@app.post("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ----------------------------------------------------------------- dashboard
@app.get("/dashboard")
@login_required
def dashboard():
    account, stats, recent = db.dashboard_data(g.account["account_no"])
    return render_template(
        "dashboard.html", account=account, stats=stats, recent=recent, greeting=greeting()
    )


@app.get("/api/balance-history")
@login_required
def balance_history():
    range_key = request.args.get("range", "7d")
    if range_key not in ("7d", "30d", "all"):
        range_key = "7d"
    return jsonify(db.balance_history(g.account["account_no"], range_key))


@app.get("/balance")
@login_required
def balance():
    return render_template("balance.html")


@app.get("/profile")
@login_required
def profile():
    _, stats, _ = db.dashboard_data(g.account["account_no"])
    return render_template("profile.html", stats=stats)


# ----------------------------------------------------------- money movements
def _money_view(kind, template, endpoint, verb):
    if request.method == "GET":
        return render_template(template, form={})
    try:
        amount = parse_amount(request.form.get("amount"))
        new_balance = db.move_money(g.account["account_no"], amount, kind)
    except ValueError as exc:  # includes BankError
        flash(str(exc), "danger")
        return render_template(template, form=request.form), 400
    log.info("%s %s by %s", kind, amount, mask_account(g.account["account_no"]))
    flash(f"{verb} of {money(amount)} successful. New balance: {money(new_balance)}", "success")
    return redirect(url_for(endpoint))


@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    return _money_view("Deposit", "deposit.html", "deposit", "Deposit")


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    return _money_view("Withdraw", "withdraw.html", "withdraw", "Withdrawal")


@app.route("/transfer", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per minute", methods=["POST"])
def transfer():
    if request.method == "GET":
        return render_template("transfer.html", form={})
    recipient = request.form.get("recipient", "").strip()
    try:
        if not RECIPIENT_RE.fullmatch(recipient):
            raise ValueError("Enter the recipient's account number (digits only).")
        amount = parse_amount(request.form.get("amount"))
        new_balance = db.transfer(g.account["account_no"], recipient, amount)
    except ValueError as exc:
        flash(str(exc), "danger")
        return render_template("transfer.html", form=request.form), 400
    log.info("Transfer %s from %s to %s", amount,
             mask_account(g.account["account_no"]), mask_account(recipient))
    flash(f"Transferred {money(amount)} to account {mask_account(recipient)}. "
          f"New balance: {money(new_balance)}", "success")
    return redirect(url_for("transfer"))


# ------------------------------------------------------------------- history
def _history_args():
    q = request.args.get("q", "").strip()[:60]
    sort = request.args.get("sort", "newest")
    tx_type = request.args.get("type", "all")
    sort = sort if sort in db.SORTS else "newest"
    tx_type = tx_type if tx_type in db.TYPE_FILTERS else "all"
    return q, sort, tx_type


@app.get("/transactions")
@login_required
def transactions():
    q, sort, tx_type = _history_args()
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    rows, total, page, pages = db.list_transactions(
        g.account["account_no"], q, sort, tx_type, page, PER_PAGE
    )
    return render_template(
        "transactions.html", rows=rows, total=total, page=page, pages=pages,
        q=q, sort=sort, tx_type=tx_type, type_options=list(db.TYPE_FILTERS),
    )


@app.get("/transactions/export.csv")
@login_required
def export_csv():
    q, sort, tx_type = _history_args()
    rows = db.export_transactions(g.account["account_no"], q, sort, tx_type)
    buf = io.StringIO()
    buf.write("\ufeff")  # lets Excel open the rupee data as UTF-8
    writer = csv.writer(buf)
    writer.writerow(["Transaction ID", "Type", "Amount", "Previous Balance",
                     "Current Balance", "Other Account", "Date & Time"])
    for r in rows:
        writer.writerow([
            r["transaction_id"], r["transaction_type"], f"{r['amount']:.2f}",
            f"{r['previous_balance']:.2f}", f"{r['current_balance']:.2f}",
            mask_account(r["counterparty_account"]),
            r["created_at"].astimezone(db.LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        ])
    filename = f"transactions_{g.account['account_no']}.csv"
    return Response(
        buf.getvalue(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# -------------------------------------------------------------------- errors
ERROR_TEXT = {
    400: ("Request could not be processed", "Something about that request was invalid. Go back and try again."),
    403: ("Access denied", "You do not have permission to view this page."),
    404: ("Page not found", "The page you are looking for does not exist."),
    405: ("Action not allowed", "That action is not allowed on this page."),
    413: ("Request too large", "The data you sent was too large."),
    429: ("Too many attempts", "You have made too many requests. Please wait a minute and try again."),
    503: ("Service unavailable", "We could not reach the database. Please try again in a moment."),
}


@app.errorhandler(Exception)
def handle_error(exc):
    if isinstance(exc, CSRFError):
        code, title, text = 400, "Session expired", "Your form expired or was invalid. Refresh the page and try again."
    elif isinstance(exc, HTTPException):
        code = exc.code or 500
        title, text = ERROR_TEXT.get(code, ("Something went wrong", "Please try again."))
    elif isinstance(exc, (psycopg.OperationalError, RuntimeError)):
        log.exception("Database unavailable")
        code = 503
        title, text = ERROR_TEXT[503]
    else:
        log.exception("Unhandled error")
        code, title, text = 500, "Something went wrong", "An unexpected error occurred. Your money was not moved unless a success message was shown."
    if request.path.startswith("/api/"):
        return jsonify(error=title), code
    return render_template("error.html", code=code, title=title, text=text), code


if __name__ == "__main__":
    app.run(debug=DEBUG, port=int(os.getenv("PORT", 5000)))
