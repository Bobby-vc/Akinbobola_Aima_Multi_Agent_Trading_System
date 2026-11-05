import pytest

from first_ai_agents.signals import parse_sentiment, parse_signal


@pytest.mark.parametrize("text, action, ticker, qty, confidence", [
    ("TRADE SIGNAL: BUY NVDA | Qty: 5 | Confidence: 0.78", "BUY", "NVDA", 5, 0.78),
    ("**TRADE SIGNAL:** [SELL] tsla | Qty: 5 | Confidence: [0.6]", "SELL", "TSLA", 5, 0.6),
    ("TRADE SIGNAL: HOLD AAPL | Qty: 5 | Confidence: 78%", "HOLD", "AAPL", 5, 0.78),
    ("TRADE SIGNAL: BUY MSFT | Confidence: 85", "BUY", "MSFT", None, 0.85),
    ("TRADE SIGNAL: BUY X | Confidence: 1.4", "BUY", "X", None, 0.014),
    ("TRADE SIGNAL: BUY | Qty: 5 | Confidence: .9", "BUY", None, 5, 0.9),
    ("TRADE SIGNAL: [BUY/HOLD/SELL] X\nlater\nTRADE SIGNAL: SELL AMD | Qty: 3 | Confidence: 0.55",
     "SELL", "AMD", 3, 0.55),
])
def test_numeric_signals(text, action, ticker, qty, confidence):
    signal = parse_signal(text)
    assert (signal["action"], signal["ticker"], signal["qty"]) == (action, ticker, qty)
    assert signal["confidence"] == pytest.approx(confidence)


def test_label_only_signals_from_older_runs():
    signal = parse_signal("TRADE SIGNAL: BUY NVDA | Qty: 5 | Confidence: MEDIUM")
    assert signal["confidence"] is None
    assert signal["label"] == "MEDIUM"


def test_confidence_with_both_number_and_label():
    signal = parse_signal("TRADE SIGNAL: BUY NVDA | Qty: 5 | Confidence: 0.82 (HIGH)")
    assert signal["confidence"] == pytest.approx(0.82)
    assert signal["label"] == "HIGH"


def test_no_signal():
    assert parse_signal("no signal here") is None
    assert parse_signal(None) is None


@pytest.mark.parametrize("text, expected", [
    ("SENTIMENT: [NEUTRAL]", "NEUTRAL"),
    ("**Sentiment Summary:** Bullish overall", "BULLISH"),
    ("the market is not bullish", None),
])
def test_parse_sentiment(text, expected):
    assert parse_sentiment(text) == expected
