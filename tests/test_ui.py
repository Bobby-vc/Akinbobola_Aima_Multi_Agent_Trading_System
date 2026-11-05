import pytest

from first_ai_agents import ui
from first_ai_agents.signals import parse_signal


def make_run(**overrides):
    run = {
        "id": 1, "ticker": "NVDA", "question": "Is NVDA a buy?", "experience": "beginner",
        "run_at": "2026-11-04T12:01:00", "started_at": "2026-11-04T12:00:00", "threshold": 0.7,
        "analysis": "SENTIMENT: BULLISH\nTRADE SIGNAL: BUY NVDA | Qty: 5 | Confidence: 0.78",
        "trade_signal": "Report",
    }
    run.update(overrides)
    return run


def make_trade(status, side="buy", ticker="NVDA"):
    return {"ticker": ticker, "side": side, "qty": 5, "status": status, "filled_avg_price": None}


def view_for(run=None, trades=(), events=()):
    return ui.build_run_view(run or make_run(), list(trades), list(events), stock=None)


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
    assert view_for(run, trades, events)["kind"] == kind


@pytest.mark.parametrize("analysis, expected", [
    ("TRADE SIGNAL: BUY NVDA | Confidence: 0.62", "confidence 0.62, below the 0.70 threshold"),
    ("TRADE SIGNAL: BUY NVDA | Confidence: 0.82", "meets the 0.70 threshold, but the Trader did not place an order"),
    ("TRADE SIGNAL: HOLD NVDA | Confidence: 0.55", "The Advisor's signal was HOLD (confidence 0.55)"),
    ("TRADE SIGNAL: BUY NVDA | Confidence: LOW", "with confidence LOW, and the Trader did not place an order"),
])
def test_hold_explains_the_threshold(analysis, expected):
    assert expected in ui.decision_html(view_for(make_run(analysis=analysis)))


def test_banner_shows_confidence_and_threshold():
    html = ui.decision_html(view_for(trades=[make_trade("filled")]))
    assert "Confidence 0.78 · threshold 0.70" in html


def test_confidence_color_reflects_the_threshold():
    above = ui.run_pipeline_html(view_for(make_run(threshold=0.7)))
    below = ui.run_pipeline_html(view_for(make_run(threshold=0.9)))
    assert f'color:{ui.BUY_COLOR}">0.78' in above
    assert f'color:{ui.HOLD_COLOR}">0.78' in below


@pytest.mark.parametrize("text, expected", [
    ("TRADE SIGNAL: BUY X | Confidence: 0.6", "0.60"),
    ("TRADE SIGNAL: BUY X | Confidence: MEDIUM", "MEDIUM"),
    ("TRADE SIGNAL: BUY X", "—"),
])
def test_fmt_confidence(text, expected):
    assert ui.fmt_confidence(parse_signal(text)) == expected
    assert ui.fmt_confidence(None) == "—"


def test_blocked_reason_reaches_the_banner():
    events = [{"level": "block", "category": "order", "message": "Daily trade limit reached"}]
    assert "Daily trade limit reached" in ui.decision_html(view_for(trades=[make_trade("blocked")], events=events))


def test_agent_and_user_text_is_escaped():
    run = make_run(question="<script>alert(1)</script>", ticker="<b>X</b>")
    events = [{"level": "block", "category": "order", "message": "<img src=x onerror=alert(1)>"}]
    view = view_for(run, [make_trade("blocked", ticker="<b>X</b>")], events)
    page = ui.run_pipeline_html(view) + ui.decision_html(view)
    for unsafe in ("<script>", "<img src=x", "<b>X</b>"):
        assert unsafe not in page


def test_markdown_safe_escapes_dollar_signs():
    assert ui.markdown_safe("from $95 to $100") == "from \\$95 to \\$100"


def test_sparkline_needs_two_points():
    assert ui.sparkline_svg([1.0]) == ""
    assert ui.sparkline_svg([1.0, 2.0]).startswith('<img src="data:image/svg+xml;base64,')
