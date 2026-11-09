import sqlite3

import first_ai_agents.database as db


def test_crew_run_round_trip(temp_db):
    run_id = db.log_crew_run(question="Is NVDA a buy?", ticker="NVDA", experience="beginner",
                             threshold=0.7, analysis="analysis", trade_signal="HOLD",
                             raw_output="raw", started_at="2026-01-01T00:00:00")
    run = db.get_crew_run(run_id)
    assert run["ticker"] == "NVDA"
    assert run["started_at"] == "2026-01-01T00:00:00"
    assert db.get_crew_runs()[0]["id"] == run_id


def test_stock_cache_is_case_insensitive(temp_db):
    db.cache_stock_data("nvda", {"formatted": "x", "currentPrice": 187.5})
    assert db.get_cached_stock("NVDA")["currentPrice"] == 187.5


def test_stock_cache_expires(temp_db):
    db.cache_stock_data("NVDA", {"formatted": "x"})
    assert db.get_cached_stock("NVDA", max_age_minutes=-1) is None


def test_daily_count_skips_orders_that_never_reached_alpaca(temp_db):
    db.log_trade("AAPL", 5, "buy", "o1", "accepted")
    db.log_trade("AAPL", 5, "buy", None, "blocked")
    db.log_trade("AAPL", 5, "buy", None, "failed")
    assert db.count_trades_today() == 1


def test_unsettled_trades_exclude_final_and_unsubmitted(temp_db):
    db.log_trade("AAPL", 5, "buy", "open", "accepted")
    db.log_trade("MSFT", 5, "buy", "done", "filled")
    db.log_trade("TSLA", 5, "buy", None, "blocked")
    assert [t["order_id"] for t in db.get_unsettled_trades()] == ["open"]


def test_update_trade_status(temp_db):
    db.log_trade("AAPL", 5, "buy", "o1", "accepted")
    db.update_trade_status("o1", "filled", 187.5)
    trade = db.get_trades()[0]
    assert trade["status"] == "filled"
    assert trade["filled_avg_price"] == 187.5
    assert trade["updated_at"]


def test_events_and_trades_between(temp_db):
    db.log_trade("AAPL", 5, "buy", "o1", "accepted")
    db.log_monitor_event("info", "check", "done")
    assert len(db.get_trades_between("2000-01-01", "2999-01-01")) == 1
    assert len(db.get_monitor_events_between("2000-01-01", "2999-01-01")) == 1
    assert db.get_trades_between("2000-01-01", "2000-01-02") == []


def test_old_databases_gain_new_columns(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE trade_history (id INTEGER PRIMARY KEY AUTOINCREMENT,
            traded_at TEXT NOT NULL, ticker TEXT NOT NULL, qty INTEGER NOT NULL, side TEXT NOT NULL,
            order_id TEXT, status TEXT, crew_run_id INTEGER)""")
        conn.execute("""CREATE TABLE crew_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TEXT NOT NULL,
            question TEXT, ticker TEXT, experience TEXT, threshold REAL, analysis TEXT,
            trade_signal TEXT, raw_output TEXT)""")
        conn.execute("INSERT INTO trade_history (traded_at, ticker, qty, side, order_id, status) "
                     "VALUES ('2026-01-01T00:00:00', 'MSFT', 5, 'buy', 'old-1', 'accepted')")
        conn.execute("INSERT INTO crew_runs (run_at, ticker) VALUES ('2026-01-01T00:00:00', 'MSFT')")

    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    db.init_db()  # running it again must change nothing

    assert db.get_trades()[0]["order_id"] == "old-1"
    assert db.get_trades()[0]["filled_avg_price"] is None
    assert db.get_crew_runs()[0]["started_at"] is None
    # Rows from before accounts existed belong to the Alpaca account
    assert db.get_trades(account="alpaca")[0]["order_id"] == "old-1"
    assert db.get_crew_runs(account="alpaca")[0]["ticker"] == "MSFT"
    assert db.get_crew_runs()[0]["cost_usd"] is None


def test_timestamps_keep_the_stored_format(temp_db):
    # Rows saved before utc_now() existed have no timezone suffix; new rows must match
    # so that text comparisons and cache-age arithmetic keep working on old data.
    assert db.utc_now().tzinfo is None
    db.log_trade("AAPL", 5, "buy", "o1", "accepted")
    assert "+" not in db.get_trades()[0]["traded_at"]

    with db.get_conn() as conn:
        conn.execute("INSERT INTO stock_cache (ticker, cached_at, data_json) VALUES (?,?,?)",
                     ("OLD", "2026-01-01T00:00:00.000001", '{"formatted": "x"}'))
    assert db.get_cached_stock("OLD") is None  # expired, and no naive/aware TypeError


def test_sign_in_creates_each_user_once_with_their_own_account(temp_db):
    first = db.sign_in_user("https://accounts.google.com", "1001", "lee@example.com", "Lee")
    again = db.sign_in_user("https://accounts.google.com", "1001", "lee.new@example.com", "Lee L")
    other = db.sign_in_user("https://accounts.google.com", "2002", "sam@example.com", "Sam")

    assert first["account"] == again["account"] == "sim:user-1"
    assert again["email"] == "lee.new@example.com" and again["name"] == "Lee L"
    assert other["account"] == "sim:user-2"


def test_the_same_id_from_another_provider_is_another_user(temp_db):
    a = db.sign_in_user("https://accounts.google.com", "1001")
    b = db.sign_in_user("https://login.example.com", "1001")
    assert a["account"] != b["account"]
