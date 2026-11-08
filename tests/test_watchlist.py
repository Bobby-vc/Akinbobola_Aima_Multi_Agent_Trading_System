import pytest

import first_ai_agents.database as db
import first_ai_agents.watchlist as watchlist


class FakeCalendarAPI:
    def __init__(self, open_today=True):
        self.open_today = open_today

    def get_calendar(self, start, end):
        return [object()] if self.open_today else []


class FakeCrew:
    """Saves a run (and optionally an order) the way the real crew's hooks do."""
    signals = {}   # ticker -> TRADE SIGNAL text
    orders = {}    # ticker -> (side, status)
    failing = set()
    calls = []

    def kickoff(self, inputs):
        ticker = inputs["ticker"]
        FakeCrew.calls.append(inputs)
        print(f"agent output for {ticker}")
        if ticker in FakeCrew.failing:
            raise RuntimeError("OpenAI timed out")
        started = db.utc_now().isoformat()
        if ticker in FakeCrew.orders:
            side, status = FakeCrew.orders[ticker]
            db.log_trade(ticker, 5, side, None if status == "blocked" else "o1", status)
        db.log_crew_run(question=inputs["question"], ticker=ticker, experience=inputs["experience_level"],
                        threshold=inputs["confidence_threshold"],
                        analysis=f"TRADE SIGNAL: {FakeCrew.signals.get(ticker, 'HOLD ' + ticker)}",
                        trade_signal="", raw_output="", started_at=started)


@pytest.fixture
def setup(temp_db, tmp_path, monkeypatch):
    config = tmp_path / "watchlist.yaml"
    config.write_text("tickers: [nvda, AAPL, ' msft ']\nexperience_level: advanced\n"
                      "confidence_threshold: 0.8\nquestion: 'Should I trade {ticker}?'\n")
    monkeypatch.setattr(watchlist, "WATCHLIST_PATH", config)
    monkeypatch.setattr(watchlist, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(FakeCrew, "signals", {})
    monkeypatch.setattr(FakeCrew, "orders", {})
    monkeypatch.setattr(FakeCrew, "failing", set())
    monkeypatch.setattr(FakeCrew, "calls", [])
    return tmp_path


def run(**kwargs):
    kwargs.setdefault("api", FakeCalendarAPI())
    return watchlist.run_watchlist(crew_factory=FakeCrew, **kwargs)


def test_load_watchlist(setup):
    config = watchlist.load_watchlist()
    assert config["tickers"] == ["NVDA", "AAPL", "MSFT"]
    assert config["experience_level"] == "advanced"
    assert config["confidence_threshold"] == 0.8


def test_runs_every_ticker_with_the_configured_inputs(setup):
    results = run()
    assert list(results) == ["NVDA", "AAPL", "MSFT"]
    assert len(db.get_crew_runs()) == 3
    first = FakeCrew.calls[0]
    assert first == {"question": "Should I trade NVDA?", "ticker": "NVDA",
                     "experience_level": "advanced", "confidence_threshold": 0.8}


def test_results_describe_signal_and_outcome(setup):
    FakeCrew.signals = {"NVDA": "BUY NVDA | Confidence: 0.86", "AAPL": "BUY AAPL | Confidence: 0.91",
                        "MSFT": "SELL MSFT | Confidence: 0.55"}
    FakeCrew.orders = {"NVDA": ("buy", "accepted"), "AAPL": ("buy", "blocked")}
    results = run()
    assert results["NVDA"] == "BUY 0.86 -> buy 5 accepted"
    assert results["AAPL"] == "BUY 0.91 -> blocked by Risk Monitor"
    assert results["MSFT"] == "SELL 0.55 -> no order"


def test_skips_non_trading_days(setup):
    assert run(api=FakeCalendarAPI(open_today=False)) == {}
    assert FakeCrew.calls == []


def test_force_runs_on_a_non_trading_day(setup):
    results = run(api=FakeCalendarAPI(open_today=False), force=True, tickers=["nvda"])
    assert list(results) == ["NVDA"]


def test_tickers_already_run_today_are_skipped(setup):
    run(tickers=["NVDA"])
    results = run()
    assert results["NVDA"] == "skipped: already ran today"
    assert [c["ticker"] for c in FakeCrew.calls] == ["NVDA", "AAPL", "MSFT"]


def test_one_failure_does_not_stop_the_rest(setup):
    FakeCrew.failing = {"AAPL"}
    results = run()
    assert results["AAPL"] == "error: OpenAI timed out"
    assert "error" not in results["MSFT"]
    assert len(db.get_crew_runs()) == 2


def test_agent_output_goes_to_the_log(setup, capsys):
    run(tickers=["NVDA"])
    printed = capsys.readouterr().out
    assert "agent output" not in printed and "NVDA" in printed
    log = next((setup / "logs").glob("watchlist-*.log")).read_text(encoding="utf-8")
    assert "agent output for NVDA" in log


def test_empty_watchlist(setup):
    watchlist.WATCHLIST_PATH.write_text("tickers: []\n")
    assert run() == {}
