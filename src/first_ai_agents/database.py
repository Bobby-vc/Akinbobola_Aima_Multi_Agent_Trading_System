import os
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

# AIMA_DB_PATH points the app at a different database, e.g. a demo or test copy
DB_PATH = Path(os.getenv("AIMA_DB_PATH") or Path(__file__).parent.parent.parent / "trading.db")

# Records belong to an account: "alpaca" for the shared Alpaca paper account,
# or "sim:<name>" for a simulated portfolio. Rows saved before accounts existed
# are Alpaca's.
DEFAULT_ACCOUNT = "alpaca"


def utc_now() -> datetime:
    """The current UTC time without a timezone attached, matching the timestamps
    already stored (datetime.utcnow() is deprecated)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS crew_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at      TEXT NOT NULL,
                question    TEXT,
                ticker      TEXT,
                experience  TEXT,
                threshold   REAL,
                analysis    TEXT,
                trade_signal TEXT,
                raw_output  TEXT
            );

            CREATE TABLE IF NOT EXISTS trade_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                traded_at   TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                qty         INTEGER NOT NULL,
                side        TEXT NOT NULL,
                order_id    TEXT,
                status      TEXT,
                crew_run_id INTEGER REFERENCES crew_runs(id)
            );

            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                snapped_at      TEXT NOT NULL,
                cash            REAL,
                portfolio_value REAL,
                buying_power    REAL,
                positions_json  TEXT
            );

            CREATE TABLE IF NOT EXISTS stock_cache (
                ticker      TEXT NOT NULL,
                cached_at   TEXT NOT NULL,
                data_json   TEXT NOT NULL,
                PRIMARY KEY (ticker)
            );

            CREATE TABLE IF NOT EXISTS monitor_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL,
                level       TEXT NOT NULL,
                category    TEXT NOT NULL,
                ticker      TEXT,
                message     TEXT NOT NULL
            );

            -- Simulated portfolios (sim_broker.py)
            CREATE TABLE IF NOT EXISTS sim_accounts (
                id              TEXT PRIMARY KEY,
                cash            REAL NOT NULL,
                starting_cash   REAL NOT NULL,
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sim_positions (
                account_id  TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                qty         REAL NOT NULL,
                avg_price   REAL NOT NULL,
                PRIMARY KEY (account_id, symbol)
            );

            CREATE TABLE IF NOT EXISTS sim_orders (
                id                  TEXT PRIMARY KEY,
                account_id          TEXT NOT NULL,
                symbol              TEXT NOT NULL,
                qty                 REAL NOT NULL,
                side                TEXT NOT NULL,
                status              TEXT NOT NULL,
                filled_avg_price    REAL,
                submitted_at        TEXT NOT NULL
            );

            -- People who sign in (auth.py). Each gets a practice portfolio, "sim:user-<id>".
            -- issuer and subject are the sign-in provider and its permanent id for the
            -- person, which stays the same even if their email changes.
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer          TEXT NOT NULL,
                subject         TEXT NOT NULL,
                email           TEXT,
                name            TEXT,
                account         TEXT UNIQUE,
                created_at      TEXT NOT NULL,
                last_login_at   TEXT,
                UNIQUE (issuer, subject)
            );
        """)
        # Columns added after the first release; existing databases need them too
        _add_missing_columns(conn, "trade_history", (("filled_avg_price", "REAL"), ("updated_at", "TEXT")))
        _add_missing_columns(conn, "crew_runs", (
            ("started_at", "TEXT"), ("model", "TEXT"), ("prompt_tokens", "INTEGER"),
            ("cached_tokens", "INTEGER"), ("completion_tokens", "INTEGER"),
            ("llm_requests", "INTEGER"), ("cost_usd", "REAL"),
        ))
        for table in ("crew_runs", "trade_history", "portfolio_snapshots", "monitor_events"):
            _add_missing_columns(conn, table, (("account", "TEXT"),))
            conn.execute(f"UPDATE {table} SET account=? WHERE account IS NULL", (DEFAULT_ACCOUNT,))


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column, col_type in columns:
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def _account_filter(account: str | None) -> tuple[str, tuple]:
    """A WHERE clause fragment limiting rows to one account, or nothing for all accounts."""
    return (" AND account=?", (account,)) if account else ("", ())


# --- crew runs ---

def log_crew_run(question: str, ticker: str, experience: str, threshold: float,
                 analysis: str, trade_signal: str, raw_output: str,
                 started_at: str | None = None, account: str = DEFAULT_ACCOUNT,
                 usage: dict | None = None) -> int:
    """usage: model, prompt_tokens, cached_tokens, completion_tokens, llm_requests, cost_usd."""
    usage = usage or {}
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO crew_runs (run_at, started_at, question, ticker, experience, threshold,
               analysis, trade_signal, raw_output, account, model, prompt_tokens, cached_tokens,
               completion_tokens, llm_requests, cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (utc_now().isoformat(), started_at, question, ticker, experience,
             threshold, analysis, trade_signal, raw_output, account,
             usage.get("model"), usage.get("prompt_tokens"), usage.get("cached_tokens"),
             usage.get("completion_tokens"), usage.get("llm_requests"), usage.get("cost_usd")),
        )
        return cur.lastrowid


def get_crew_runs(limit: int = 50, account: str | None = None):
    where, args = _account_filter(account)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM crew_runs WHERE 1=1{where} ORDER BY run_at DESC LIMIT ?", (*args, limit)
        ).fetchall()


def get_crew_run(run_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM crew_runs WHERE id=?", (run_id,)).fetchone()


# --- trades ---

def log_trade(ticker: str, qty: int, side: str, order_id: str,
              status: str, crew_run_id: int | None = None, account: str = DEFAULT_ACCOUNT,
              filled_avg_price: float | None = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO trade_history (traded_at, ticker, qty, side, order_id, status, crew_run_id,
               account, filled_avg_price) VALUES (?,?,?,?,?,?,?,?,?)""",
            (utc_now().isoformat(), ticker, qty, side, order_id, status, crew_run_id,
             account, filled_avg_price),
        )


def get_trades(limit: int = 100, account: str | None = None):
    where, args = _account_filter(account)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM trade_history WHERE 1=1{where} ORDER BY traded_at DESC LIMIT ?", (*args, limit)
        ).fetchall()


def get_trades_between(start: str, end: str, account: str | None = None):
    where, args = _account_filter(account)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM trade_history WHERE traded_at BETWEEN ? AND ?{where} ORDER BY traded_at",
            (start, end, *args),
        ).fetchall()


# Order statuses that will not change again, so the monitor stops checking them.
# "blocked" and "failed" are set locally for orders that never reached a broker.
FINAL_ORDER_STATUSES = ("filled", "canceled", "expired", "rejected", "replaced", "blocked", "failed")
NOT_SUBMITTED_STATUSES = ("blocked", "failed")


def get_unsettled_trades(account: str | None = None):
    placeholders = ",".join("?" * len(FINAL_ORDER_STATUSES))
    where, args = _account_filter(account)
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT * FROM trade_history
                WHERE order_id IS NOT NULL AND COALESCE(status, '') NOT IN ({placeholders}){where}""",
            (*FINAL_ORDER_STATUSES, *args),
        ).fetchall()


def update_trade_status(order_id: str, status: str, filled_avg_price: float | None):
    with get_conn() as conn:
        conn.execute(
            """UPDATE trade_history SET status=?, filled_avg_price=?, updated_at=?
               WHERE order_id=?""",
            (status, filled_avg_price, utc_now().isoformat(), order_id),
        )


def count_trades_today(account: str | None = None) -> int:
    """Counts today's (UTC) trades, not including orders that never reached a broker."""
    where, args = _account_filter(account)
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT COUNT(*) FROM trade_history
                WHERE traded_at >= date('now') AND COALESCE(status, '') NOT IN (?, ?){where}""",
            (*NOT_SUBMITTED_STATUSES, *args),
        ).fetchone()[0]


# --- portfolio snapshots ---

def log_portfolio_snapshot(cash: float, portfolio_value: float,
                           buying_power: float, positions: list[dict], account: str = DEFAULT_ACCOUNT):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO portfolio_snapshots (snapped_at, cash, portfolio_value, buying_power,
               positions_json, account) VALUES (?,?,?,?,?,?)""",
            (utc_now().isoformat(), cash, portfolio_value,
             buying_power, json.dumps(positions), account),
        )


def get_portfolio_snapshots(limit: int = 100, account: str | None = None):
    where, args = _account_filter(account)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM portfolio_snapshots WHERE 1=1{where} ORDER BY snapped_at DESC LIMIT ?",
            (*args, limit),
        ).fetchall()


# --- stock cache ---

def cache_stock_data(ticker: str, data: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO stock_cache (ticker, cached_at, data_json)
               VALUES (?,?,?)
               ON CONFLICT(ticker) DO UPDATE SET cached_at=excluded.cached_at, data_json=excluded.data_json""",
            (ticker.upper(), utc_now().isoformat(), json.dumps(data)),
        )


def get_cached_stock(ticker: str, max_age_minutes: int = 15) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM stock_cache WHERE ticker=?", (ticker.upper(),)
        ).fetchone()
    if not row:
        return None
    cached_at = datetime.fromisoformat(row["cached_at"])
    age = (utc_now() - cached_at).total_seconds() / 60
    if age > max_age_minutes:
        return None
    return json.loads(row["data_json"])


# --- monitor events ---

def log_monitor_event(level: str, category: str, message: str, ticker: str | None = None,
                      account: str = DEFAULT_ACCOUNT):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO monitor_events (created_at, level, category, ticker, message, account)
               VALUES (?,?,?,?,?,?)""",
            (utc_now().isoformat(), level, category, ticker, message, account),
        )


def get_monitor_events(limit: int = 100, account: str | None = None):
    where, args = _account_filter(account)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM monitor_events WHERE 1=1{where} ORDER BY created_at DESC LIMIT ?",
            (*args, limit),
        ).fetchall()


def get_monitor_events_between(start: str, end: str, account: str | None = None):
    where, args = _account_filter(account)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM monitor_events WHERE created_at BETWEEN ? AND ?{where} ORDER BY created_at",
            (start, end, *args),
        ).fetchall()


# --- users ---

def sign_in_user(issuer: str, subject: str, email: str | None = None, name: str | None = None) -> dict:
    """Finds the user with this sign-in identity, or creates them with their own
    practice portfolio account, and records the sign-in."""
    now = utc_now().isoformat()
    with get_conn() as conn:
        # Take the write lock first, so two tabs signing in at once cannot both create the user
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id FROM users WHERE issuer=? AND subject=?", (issuer, subject)).fetchone()
        if row is None:
            user_id = conn.execute(
                "INSERT INTO users (issuer, subject, email, name, created_at, last_login_at) VALUES (?,?,?,?,?,?)",
                (issuer, subject, email, name, now, now),
            ).lastrowid
            conn.execute("UPDATE users SET account=? WHERE id=?", (f"sim:user-{user_id}", user_id))
        else:
            user_id = row["id"]
            conn.execute("UPDATE users SET email=?, name=?, last_login_at=? WHERE id=?",
                         (email, name, now, user_id))
        return dict(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


init_db()
