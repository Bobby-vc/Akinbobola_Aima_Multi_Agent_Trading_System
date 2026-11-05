"""Reads the structured lines the Advisor ends its analysis with:

    SENTIMENT: BULLISH
    TRADE SIGNAL: BUY NVDA | Qty: 5 | Confidence: 0.78

Used by the Risk Monitor to check orders against what the Advisor actually
said, and by the dashboard to fill in the agent cards.
"""
import re

_SIGNAL_RE = re.compile(r"TRADE SIGNAL:\s*(BUY|HOLD|SELL)\b(.*)", re.IGNORECASE)
_SENTIMENT_RE = re.compile(r"SENTIMENT[^\n:]*:\s*(BULLISH|BEARISH|NEUTRAL)", re.IGNORECASE)
_TICKER_RE = re.compile(r"\s*([A-Z][A-Z.\-]{0,9})\b", re.IGNORECASE)
_QTY_RE = re.compile(r"Qty:\s*(\d+)", re.IGNORECASE)
_CONFIDENCE_RE = re.compile(r"Confidence:\s*(\d*\.?\d+)\s*(%?)", re.IGNORECASE)
_LABEL_RE = re.compile(r"Confidence:[^|\n]*?\b(HIGH|MEDIUM|LOW)\b", re.IGNORECASE)


def _strip_markdown(text: str | None) -> str:
    return re.sub(r"[*\[\]]", "", text or "")


def parse_signal(text: str | None) -> dict | None:
    """Reads the last TRADE SIGNAL line.

    Returns action, ticker, qty, confidence (a number from 0 to 1, or None if
    the Advisor gave no number), and label (HIGH/MEDIUM/LOW, used by runs saved
    before confidence became numeric)."""
    matches = list(_SIGNAL_RE.finditer(_strip_markdown(text)))
    if not matches:
        return None
    match = matches[-1]
    rest = match.group(2)

    ticker = _TICKER_RE.match(rest)
    qty = _QTY_RE.search(rest)
    confidence = None
    number = _CONFIDENCE_RE.search(rest)
    if number:
        value = float(number.group(1))
        if number.group(2) or value > 1:  # "78%" or "78" both mean 0.78
            value /= 100
        confidence = min(max(value, 0.0), 1.0)
    label = _LABEL_RE.search(rest)

    return {
        "action": match.group(1).upper(),
        "ticker": ticker.group(1).upper() if ticker and ticker.group(1).upper() != "QTY" else None,
        "qty": int(qty.group(1)) if qty else None,
        "confidence": confidence,
        "label": label.group(1).upper() if label else None,
    }


def parse_sentiment(text: str | None) -> str | None:
    matches = _SENTIMENT_RE.findall(_strip_markdown(text))
    return matches[-1].upper() if matches else None
