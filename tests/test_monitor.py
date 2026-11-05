from types import SimpleNamespace as NS

import pytest

import first_ai_agents.database as db
import first_ai_agents.monitor as monitor
import first_ai_agents.tools.custom_tool as tools
from conftest import FakeAlpaca, make_position


@pytest.mark.parametrize("label, api, ticker, qty, side, reason", [
    ("bad side", FakeAlpaca(), "AAPL", 5, "short", "Side must be"),
    ("zero quantity", FakeAlpaca(), "AAPL", 0, "buy", "must be positive"),
    ("over per-order limit", FakeAlpaca(), "AAPL", 101, "buy", "per-order limit"),
    ("selling more than held", FakeAlpaca(positions=[make_position("AAPL", 3, 100)]),
     "AAPL", 5, "sell", "short selling"),
    ("buy over share of cash", FakeAlpaca(cash=1_000, price=100), "AAPL", 5, "buy", "of available cash"),
    ("position over portfolio limit",
     FakeAlpaca(cash=1_000_000, value=50_000, positions=[make_position("AAPL", 40, 100)]),
     "AAPL", 20, "buy", "portfolio limit"),
])
def test_blocked_orders(temp_db, label, api, ticker, qty, side, reason):
    allowed, message = monitor.check_order(api, ticker, qty, side)
    assert not allowed
    assert reason in message
    assert db.get_monitor_events()[0]["level"] == "block"


@pytest.mark.parametrize("api, ticker, qty, side", [
    (FakeAlpaca(), "aapl", 5, "buy"),
    (FakeAlpaca(positions=[make_position("AAPL", 10, 100)]), "AAPL", 5, "sell"),
])
def test_allowed_orders(temp_db, api, ticker, qty, side):
    allowed, _ = monitor.check_order(api, ticker, qty, side)
    assert allowed
    assert db.get_monitor_events() == []


def test_daily_trade_limit(temp_db):
    for i in range(5):
        db.log_trade("XYZ", 1, "buy", f"o{i}", "filled")
    allowed, message = monitor.check_order(FakeAlpaca(), "AAPL", 5, "buy")
    assert not allowed
    assert "Daily trade limit" in message


def test_limits_file_overrides_defaults(tmp_path, monkeypatch):
    limits_file = tmp_path / "limits.yaml"
    limits_file.write_text("max_qty_per_order: 7\n")
    monkeypatch.setattr(monitor, "LIMITS_PATH", limits_file)
    limits = monitor.load_limits()
    assert limits["max_qty_per_order"] == 7
    assert limits["max_trades_per_day"] == monitor.DEFAULT_LIMITS["max_trades_per_day"]


def test_tool_never_submits_a_blocked_order(temp_db, monkeypatch):
    api = FakeAlpaca()
    monkeypatch.setattr(tools, "get_alpaca_api", lambda: api)
    result = tools.execute_paper_trade.run(ticker="AAPL", qty=500, side="buy")
    assert "BLOCKED" in result
    assert api.submitted == []
    assert db.get_trades()[0]["status"] == "blocked"


def test_tool_submits_an_allowed_order(temp_db, monkeypatch):
    api = FakeAlpaca()
    monkeypatch.setattr(tools, "get_alpaca_api", lambda: api)
    result = tools.execute_paper_trade.run(ticker="AAPL", qty=5, side="buy")
    assert "submitted successfully" in result
    assert len(api.submitted) == 1
    assert db.get_trades()[0]["order_id"] == "new-order"


def test_tool_records_a_failed_order(temp_db, monkeypatch):
    def alpaca_down():
        raise ConnectionError("Alpaca is down")
    api = FakeAlpaca()
    api.get_account = alpaca_down
    monkeypatch.setattr(tools, "get_alpaca_api", lambda: api)
    result = tools.execute_paper_trade.run(ticker="AAPL", qty=5, side="buy")
    assert "Trade execution failed" in result
    assert db.get_trades()[0]["status"] == "failed"


def test_run_checks(temp_db):
    db.log_trade("AAPL", 5, "buy", "a1", "accepted")
    db.log_trade("TSLA", 5, "buy", "a2", "accepted")
    db.log_trade("NVDA", 5, "buy", "a3", "new")
    db.log_trade("MSFT", 5, "buy", "a4", "filled")  # final, so it must not be looked up
    api = FakeAlpaca(value=100_000, positions=[
        make_position("RIOT", 10, 100, plpc=-0.25),
        make_position("NVDA", 150, 100),
    ], orders={
        "a1": NS(status="filled", filled_avg_price="187.5"),
        "a2": NS(status="rejected", filled_avg_price=None),
        "a3": RuntimeError("network down"),
    })

    findings = monitor.run_checks(api)

    trades = {t["order_id"]: t for t in db.get_trades()}
    assert trades["a1"]["status"] == "filled"
    assert trades["a1"]["filled_avg_price"] == 187.5
    assert trades["a2"]["status"] == "rejected"
    assert trades["a3"]["status"] == "new"
    assert any("RIOT is down 25.0%" in f for f in findings)
    assert any("NVDA is 15.0% of the portfolio" in f for f in findings)
    assert any("Could not look up order a3" in f for f in findings)
    assert len(db.get_portfolio_snapshots()) == 1
    assert db.get_monitor_events()[0]["category"] == "check"
