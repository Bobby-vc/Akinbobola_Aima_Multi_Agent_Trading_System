"""Runs the dashboard with Streamlit's test runner and a stand-in crew."""
import time
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import first_ai_agents.crew as crew_module
import first_ai_agents.database as db
from first_ai_agents import auth, performance, ui

APP = str(Path(__file__).parents[1] / "src" / "first_ai_agents" / "app.py")

# Prices for the Performance tab, so the tests never call Yahoo Finance
SESSIONS = list(pd.bdate_range("2026-11-02", "2026-12-18").date)
FAKE_CLOSES = pd.DataFrame({
    "UP": [100 * 1.01 ** i for i in range(len(SESSIONS))],
    "DOWN": [100 * 0.99 ** i for i in range(len(SESSIONS))],
    "SPY": [500.0] * len(SESSIONS),
}, index=SESSIONS)


# The dashboard tests run as a simulated account, so they never need Alpaca keys
ACCOUNT = "sim:test"


@pytest.fixture(autouse=True)
def simulated_account(monkeypatch):
    monkeypatch.setenv("AIMA_ACCOUNT", ACCOUNT)
    # Sign-in stays off unless a test turns it on, even if .streamlit/secrets.toml exists
    monkeypatch.setattr(auth, "auth_configured", lambda: False)


class FakeCrew:
    """Finishes two tasks, then saves a run, the way the real crew's finish hook does."""
    task_callback = None
    error = None

    def __init__(self, broker):
        self.broker = broker

    def kickoff(self, inputs):
        started = db.utc_now().isoformat()
        time.sleep(0.4)
        self.task_callback("advisor output")
        time.sleep(0.4)
        self.task_callback("trader output")
        if FakeCrew.error:
            raise FakeCrew.error
        db.log_crew_run(question=inputs["question"], ticker=inputs["ticker"],
                        experience=inputs["experience_level"], threshold=inputs["confidence_threshold"],
                        analysis="SENTIMENT: BEARISH\nTRADE SIGNAL: SELL AMD | Qty: 5 | Confidence: 0.40",
                        trade_signal="Held: confidence too low.", raw_output="", started_at=started,
                        account=self.broker.account_id)


class FakeAgents:
    def __init__(self, broker=None):
        self.broker = broker

    def crew(self):
        return FakeCrew(self.broker)


@pytest.fixture
def app(temp_db, monkeypatch):
    stages = []
    real_live = ui.live_pipeline_html
    monkeypatch.setattr(ui, "live_pipeline_html", lambda n, ticker: stages.append(n) or real_live(n, ticker))
    monkeypatch.setattr(crew_module, "FirstAiAgents", FakeAgents)
    monkeypatch.setattr(FakeCrew, "error", None)
    monkeypatch.setattr(performance, "load_daily_closes", lambda tickers, start: FAKE_CLOSES)
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    return at, stages


def submit(at, question, ticker):
    at.text_input[0].input(question)
    at.text_input[1].input(ticker)
    next(b for b in at.button if b.label == "Run agents").click()
    return at.run()


def test_empty_database_shows_idle_pipeline(app):
    at, _ = app
    page = " ".join(str(e.proto) for e in at.get("html"))
    assert "Ask a question above to start a run." in page


def test_live_run_is_saved_selected_and_shown(app):
    at, stages = app
    at = submit(at, "Should I sell AMD?", "amd")

    assert not at.exception
    assert stages[:3] == [0, 1, 2]
    run = db.get_crew_runs()[0]
    assert run["ticker"] == "AMD"
    assert at.session_state["selected_run_id"] == run["id"]
    page = " ".join(str(e.proto) for e in at.get("html"))
    assert "HOLD" in page and "confidence 0.40, below the 0.70 threshold" in page
    assert run["threshold"] == 0.7


def test_threshold_slider_reaches_the_run(app):
    at, _ = app
    at.slider[0].set_value(0.35)
    at = submit(at, "Should I sell AMD?", "AMD")

    assert db.get_crew_runs()[0]["threshold"] == 0.35
    page = " ".join(str(e.proto) for e in at.get("html"))
    assert "meets the 0.35 threshold" in page


def test_failed_run_shows_the_error(app, monkeypatch):
    at, _ = app
    monkeypatch.setattr(FakeCrew, "error", RuntimeError("OpenAI rate limit"))
    at = submit(at, "Should I sell AMD?", "AMD")

    assert any("OpenAI rate limit" in e.value for e in at.error)
    assert db.get_crew_runs() == []


def test_empty_form_shows_a_warning(app):
    at, _ = app
    next(b for b in at.button if b.label == "Run agents").click()
    at.run()
    assert any("Enter both" in w.value for w in at.warning)


def test_performance_tab_scores_past_signals(temp_db, monkeypatch):
    monkeypatch.setattr(performance, "load_daily_closes", lambda tickers, start: FAKE_CLOSES)
    st.cache_data.clear()
    with db.get_conn() as conn:
        for ticker, signal in (("UP", "BUY UP | Confidence: 0.85"), ("DOWN", "SELL DOWN | Confidence: 0.80"),
                               ("DOWN", "BUY DOWN | Confidence: 0.55")):
            conn.execute(
                "INSERT INTO crew_runs (run_at, started_at, question, ticker, experience, threshold, analysis, "
                "trade_signal, raw_output, account) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("2026-11-02T15:00:00", "2026-11-02T14:59:00", "q", ticker, "beginner", 0.7,
                 f"TRADE SIGNAL: {signal}", "", "", ACCOUNT),
            )

    at = AppTest.from_file(APP, default_timeout=60).run()

    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Signals scored"] == "3"
    assert metrics["Hit rate"] == "67%"
    # The 0.85 BUY and 0.80 SELL cleared the 0.7 threshold and hit; the 0.55 BUY was filtered and missed
    assert metrics["Cleared threshold"] == "100%" and metrics["Filtered out"] == "0%"
    assert any("mostly noise" in w.value for w in at.warning)


def test_performance_tab_survives_a_price_outage(temp_db, monkeypatch):
    def yahoo_down(tickers, start):
        raise ConnectionError("Yahoo is down")
    monkeypatch.setattr(performance, "load_daily_closes", yahoo_down)
    st.cache_data.clear()
    db.log_crew_run(question="q", ticker="UP", experience="beginner", threshold=0.7,
                    analysis="TRADE SIGNAL: BUY UP | Confidence: 0.9", trade_signal="", raw_output="",
                    account=ACCOUNT)

    at = AppTest.from_file(APP, default_timeout=60).run()

    assert not at.exception
    assert any("Yahoo is down" in e.value for e in at.error)


def test_dashboard_shows_only_the_active_account(temp_db, monkeypatch):
    monkeypatch.setattr(performance, "load_daily_closes", lambda tickers, start: FAKE_CLOSES)
    st.cache_data.clear()
    for ticker, account in (("TSLA", "alpaca"), ("AMD", ACCOUNT), ("NVDA", "sim:someone-else")):
        db.log_crew_run(question=f"About {ticker}?", ticker=ticker, experience="beginner", threshold=0.7,
                        analysis=f"TRADE SIGNAL: HOLD {ticker} | Confidence: 0.5", trade_signal="",
                        raw_output="", started_at=db.utc_now().isoformat(), account=account,
                        usage={"model": "openai/gpt-4o", "cost_usd": 0.0421})

    at = AppTest.from_file(APP, default_timeout=60).run()

    assert not at.exception
    page = " ".join(str(e.proto) for e in at.get("html"))
    assert "About AMD?" in page and "PRACTICE PORTFOLIO" in page
    assert "About TSLA?" not in page and "About NVDA?" not in page
    assert any("average $0.042 per run" in c.value for c in at.caption)


# ── Sign-in ────────────────────────────────────────────────────────────────────

GOOGLE = "https://accounts.google.com"


def google_identity(sub="1001", email="lee@example.com", name="Lee Learner", verified=True):
    return {"iss": GOOGLE, "sub": sub, "email": email, "name": name, "email_verified": verified,
            "is_logged_in": True}


@pytest.fixture
def signed_in(temp_db, monkeypatch):
    """Turns sign-in on; set_identity(None) means nobody is signed in."""
    monkeypatch.setattr(auth, "auth_configured", lambda: True)
    monkeypatch.setattr(crew_module, "FirstAiAgents", FakeAgents)
    monkeypatch.setattr(FakeCrew, "error", None)
    monkeypatch.setattr(performance, "load_daily_closes", lambda tickers, start: FAKE_CLOSES)
    monkeypatch.delenv("AIMA_ADMIN_EMAILS", raising=False)
    st.cache_data.clear()
    current = {"identity": google_identity()}
    monkeypatch.setattr(auth, "current_identity", lambda: current["identity"])
    return lambda identity: current.update(identity=identity)


def page_text(at):
    return " ".join(str(e.proto) for e in at.get("html"))


def log_run(ticker, account):
    db.log_crew_run(question=f"About {ticker}?", ticker=ticker, experience="beginner", threshold=0.7,
                    analysis=f"TRADE SIGNAL: HOLD {ticker} | Confidence: 0.5", trade_signal="",
                    raw_output="", started_at=db.utc_now().isoformat(), account=account)


def test_signed_out_visitors_see_only_the_sign_in_page(signed_in):
    signed_in(None)
    log_run("TSLA", "alpaca")
    at = AppTest.from_file(APP, default_timeout=60).run()

    assert not at.exception
    assert "Learn investing by watching AI analysts work." in page_text(at)
    assert [b.label for b in at.button] == ["Sign in with Google"]
    assert "About TSLA?" not in page_text(at) and not at.text_input


def test_first_sign_in_creates_a_practice_portfolio(signed_in):
    log_run("TSLA", "alpaca")
    at = AppTest.from_file(APP, default_timeout=60).run()

    assert not at.exception
    with db.get_conn() as conn:
        users = [dict(r) for r in conn.execute("SELECT * FROM users")]
    assert len(users) == 1
    assert users[0]["account"] == "sim:user-1" and users[0]["email"] == "lee@example.com"
    page = page_text(at)
    assert "PRACTICE PORTFOLIO" in page and "$100,000.00" in page
    assert "About TSLA?" not in page
    assert not at.radio  # learners have one account, so there is nothing to switch
    assert "Sign out" in [b.label for b in at.button]


def test_runs_are_saved_to_the_signed_in_users_portfolio(signed_in):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at = submit(at, "Should I sell AMD?", "AMD")

    assert not at.exception
    assert db.get_crew_runs()[0]["account"] == "sim:user-1"


def test_each_user_sees_only_their_own_runs(signed_in):
    signed_in(google_identity(sub="1001", email="lee@example.com"))
    AppTest.from_file(APP, default_timeout=60).run()
    signed_in(google_identity(sub="2002", email="sam@example.com", name="Sam"))
    AppTest.from_file(APP, default_timeout=60).run()
    log_run("AMD", "sim:user-1")
    log_run("NVDA", "sim:user-2")

    at = AppTest.from_file(APP, default_timeout=60).run()

    assert "About NVDA?" in page_text(at) and "About AMD?" not in page_text(at)


def test_admins_can_switch_to_the_alpaca_account(signed_in, monkeypatch):
    monkeypatch.setenv("AIMA_ADMIN_EMAILS", "owner@example.com")
    signed_in(google_identity(email="Owner@example.com"))
    log_run("TSLA", "alpaca")
    at = AppTest.from_file(APP, default_timeout=60).run()

    assert at.radio[0].options == ["My practice portfolio", "AIMA track record (Alpaca)"]
    assert "About TSLA?" not in page_text(at)
    at.radio[0].set_value("alpaca").run()
    assert not at.exception
    assert "About TSLA?" in page_text(at) and "PAPER TRADING" in page_text(at)


def test_an_unverified_admin_email_is_not_trusted(signed_in, monkeypatch):
    monkeypatch.setenv("AIMA_ADMIN_EMAILS", "owner@example.com")
    signed_in(google_identity(email="owner@example.com", verified=False))
    at = AppTest.from_file(APP, default_timeout=60).run()

    assert not at.exception and not at.radio
