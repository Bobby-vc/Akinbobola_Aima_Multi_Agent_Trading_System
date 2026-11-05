import pytest

from first_ai_agents import ui


@pytest.mark.parametrize("text, expected", [
    ("TRADE SIGNAL: BUY NVDA | Qty: 5 | Confidence: MEDIUM", ("BUY", 5, "MEDIUM")),
    ("**TRADE SIGNAL:** [HOLD] AAPL | Qty: 5 | Confidence: [LOW]", ("HOLD", 5, "LOW")),
    ("trade signal: sell tsla", ("SELL", None, None)),
    ("TRADE SIGNAL: [BUY/HOLD/SELL] X\nlater\nTRADE SIGNAL: SELL MSFT | Qty: 3 | Confidence: HIGH",
     ("SELL", 3, "HIGH")),
])
def test_parse_signal(text, expected):
    signal = ui.parse_signal(text)
    assert (signal["action"], signal["qty"], signal["confidence"]) == expected


def test_parse_signal_without_a_signal():
    assert ui.parse_signal("no signal here") is None
    assert ui.parse_signal(None) is None


@pytest.mark.parametrize("text, expected", [
    ("SENTIMENT: [NEUTRAL]", "NEUTRAL"),
    ("**Sentiment Summary:** Bullish overall", "BULLISH"),
    ("the market is not bullish", None),
])
def test_parse_sentiment(text, expected):
    assert ui.parse_sentiment(text) == expected


def make_run(**overrides):
    run = {
        "id": 1, "ticker": "NVDA", "question": "Is NVDA a buy?", "experience": "beginner",
        "run_at": "2026-11-04T12:01:00", "started_at": "2026-11-04T12:00:00",
        "analysis": "SENTIMENT: BULLISH\nTRADE SIGNAL: BUY NVDA | Qty: 5 | Confidence: MEDIUM",
        "trade_signal": "Report",
    }
    run.update(overrides)
    return run


def make_trade(status, side="buy", ticker="NVDA"):
    return {"ticker": ticker, "side": side, "qty": 5, "status": status, "filled_avg_price": None}


@pytest.mark.parametrize("run, trades, events, kind", [
    (make_run(), [make_trade("filled")], [], "buy"),
    (make_run(), [make_trade("accepted", side="sell")], [], "sell"),
    (make_run(), [make_trade("blocked")], [{"level": "block", "category": "order", "message": "Too big"}], "blocked"),
    (make_run(), [make_trade("failed")], [], "failed"),
    (make_run(), [], [], "hold"),
    (make_run(analysis="No signal"), [], [], "none"),
    (make_run(started_at=None), [], [], "buy"),  # older runs fall back to the Advisor's signal
])
def test_decision_kind(run, trades, events, kind):
    view = ui.build_run_view(run, trades, events, stock=None)
    assert view["kind"] == kind


def test_blocked_reason_reaches_the_banner():
    events = [{"level": "block", "category": "order", "message": "Daily trade limit reached"}]
    view = ui.build_run_view(make_run(), [make_trade("blocked")], events, stock=None)
    assert "Daily trade limit reached" in ui.decision_html(view)


def test_agent_and_user_text_is_escaped():
    run = make_run(question="<script>alert(1)</script>", ticker="<b>X</b>")
    events = [{"level": "block", "category": "order", "message": "<img src=x onerror=alert(1)>"}]
    view = ui.build_run_view(run, [make_trade("blocked", ticker="<b>X</b>")], events, stock=None)
    page = ui.run_pipeline_html(view) + ui.decision_html(view)
    for unsafe in ("<script>", "<img src=x", "<b>X</b>"):
        assert unsafe not in page


def test_markdown_safe_escapes_dollar_signs():
    assert ui.markdown_safe("from $95 to $100") == "from \\$95 to \\$100"


def test_sparkline_needs_two_points():
    assert ui.sparkline_svg([1.0]) == ""
    assert ui.sparkline_svg([1.0, 2.0]).startswith('<img src="data:image/svg+xml;base64,')
