"""Presentation helpers for the dashboard.

Turns stored runs into the fields shown on the agent cards, and builds the
HTML for the custom components (top bar, pipeline, decision banner). Every
value that comes from an LLM, the user, or the database is escaped here
before it is placed in HTML.
"""
import base64
import html
import json
import math
from datetime import datetime

from first_ai_agents.signals import parse_sentiment, parse_signal

ADVISOR_COLOR = "#58A6FF"
TRADER_COLOR = "#3DD6C6"
MONITOR_COLOR = "#A371F7"
BUY_COLOR = "#3FB950"
SELL_COLOR = "#F85149"
HOLD_COLOR = "#D29922"
MUTED_COLOR = "#8B98A5"

CSS = """
<style>
:root {
  --aima-surface: #111821; --aima-border: #223041; --aima-text: #E6EDF3; --aima-muted: #8B98A5;
  --aima-buy: #3FB950; --aima-sell: #F85149;
  --aima-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Consolas, monospace;
}
.block-container { padding-top: 1.25rem; max-width: 1280px; }
header[data-testid="stHeader"] { background: transparent; }
.stButton button p, .stFormSubmitButton button p { white-space: nowrap; }
[data-testid="stExpander"] h1, [data-testid="stExpander"] h2 { font-size: 1.2rem; padding-top: .4rem; }
[data-testid="stExpander"] h3, [data-testid="stExpander"] h4 { font-size: 1.02rem; padding-top: .3rem; }

.aima-topbar { display: flex; flex-wrap: wrap; align-items: center; gap: 14px 30px; padding: 14px 20px;
  background: var(--aima-surface); border: 1px solid var(--aima-border); border-radius: 12px; }
.aima-brand { font-weight: 700; font-size: 1.1rem; letter-spacing: .16em; color: var(--aima-text); margin-right: 6px; }
.aima-brand small { display: block; font-weight: 500; font-size: .7rem; letter-spacing: .03em; color: var(--aima-muted); }
.aima-kpi { display: flex; flex-direction: column; gap: 2px; }
.aima-label { font-size: .66rem; font-weight: 600; text-transform: uppercase; letter-spacing: .09em; color: var(--aima-muted); }
.aima-value { font-family: var(--aima-mono); font-size: 1.02rem; color: var(--aima-text); }
.aima-change { font-family: var(--aima-mono); font-size: .78rem; }
.aima-up { color: var(--aima-buy); } .aima-down { color: var(--aima-sell); }
.aima-paper { margin-left: auto; font-size: .66rem; font-weight: 700; letter-spacing: .1em; color: #D29922;
  border: 1px solid #D29922; border-radius: 999px; padding: 3px 10px; }

.aima-pipeline { display: flex; align-items: stretch; gap: 10px; margin: 6px 0 14px; }
.aima-arrow { align-self: center; color: var(--aima-muted); font-size: 1.15rem; }
.aima-card { flex: 1; min-width: 0; background: var(--aima-surface); border: 1px solid var(--aima-border);
  border-top: 3px solid var(--card-accent); border-radius: 12px; padding: 14px 16px; transition: opacity .3s; }
.aima-card.waiting, .aima-card.idle { opacity: .55; }
.aima-card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.aima-card-name { font-weight: 700; font-size: .78rem; letter-spacing: .12em; color: var(--card-accent); }
.aima-card-kind { font-size: .66rem; color: var(--aima-muted); white-space: nowrap; }
.aima-card-role { font-size: .76rem; color: var(--aima-muted); margin-top: 2px; }
.aima-state { display: flex; align-items: center; gap: 7px; font-size: .74rem; color: var(--aima-muted); margin: 10px 0 8px; }
.aima-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--aima-muted); flex: none; }
.aima-state.working .aima-dot { background: var(--card-accent); animation: aima-pulse 1.1s ease-in-out infinite; }
.aima-state.done .aima-dot { background: var(--aima-buy); }
.aima-state.blocked .aima-dot { background: var(--aima-sell); }
@keyframes aima-pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .3; transform: scale(.65); } }
.aima-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; font-size: .84rem; padding: 3px 0; }
.aima-row .k { color: var(--aima-muted); white-space: nowrap; }
.aima-row .v { font-family: var(--aima-mono); color: var(--aima-text); text-align: right; display: flex; align-items: center; gap: 8px; min-width: 0; }
.aima-note { font-size: .8rem; color: var(--aima-muted); line-height: 1.45; }

.aima-decision { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 20px; padding: 18px 22px; margin-bottom: 10px;
  border-radius: 12px; border: 1px solid var(--d-color);
  background: color-mix(in srgb, var(--d-color) 9%, var(--aima-surface)); }
.aima-decision .verb { font-family: var(--aima-mono); font-weight: 700; font-size: 1.55rem; letter-spacing: .05em; color: var(--d-color); }
.aima-decision .what { font-family: var(--aima-mono); font-size: 1.12rem; color: var(--aima-text); }
.aima-decision .meta { margin-left: auto; text-align: right; font-size: .78rem; color: var(--aima-muted); line-height: 1.5; }
.aima-decision .why { flex-basis: 100%; font-size: .86rem; color: var(--aima-muted); }
.aima-decision .question { flex-basis: 100%; font-size: .74rem; color: var(--aima-muted); }

.aima-limits { display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: 10px; margin: 4px 0 8px; }
.aima-limit { background: var(--aima-surface); border: 1px solid var(--aima-border); border-radius: 10px; padding: 12px 14px; }
.aima-limit .aima-value { font-size: 1.25rem; }

@media (max-width: 760px) {
  .aima-pipeline { flex-direction: column; }
  .aima-arrow { transform: rotate(90deg); }
  .aima-paper { margin-left: 0; }
  .aima-decision .meta { margin-left: 0; text-align: left; }
}
</style>
"""


def esc(value) -> str:
    return "" if value is None else html.escape(str(value))


def markdown_safe(text: str | None) -> str:
    """Stops dollar amounts in agent output from being rendered as LaTeX math."""
    return (text or "").replace("$", "\\$")


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "—"
    return datetime.fromisoformat(iso).strftime("%b %d, %H:%M UTC")


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def fmt_money(value) -> str:
    return "—" if _missing(value) else f"${float(value):,.2f}"


def fmt_cost(value) -> str:
    """Run costs are cents, so they get more precision than other money."""
    return "—" if _missing(value) else f"${float(value):,.3f}"


def fmt_pct(value, signed: bool = True) -> str:
    """+1.23% (or 61% unsigned, for rates); a dash for missing values."""
    if _missing(value):
        return "—"
    return f"{float(value):+.2%}" if signed else f"{float(value):.0%}"


def fmt_confidence(signal: dict | None) -> str:
    """0.78 for numeric confidence; HIGH/MEDIUM/LOW for runs saved before it was numeric."""
    if not signal:
        return "—"
    if signal["confidence"] is not None:
        return f"{signal['confidence']:.2f}"
    return signal["label"] or "—"


# --- the run view shown on the cards ---

def build_run_view(run, trades, events, stock: dict | None) -> dict:
    """Combines a crew run with the trades and monitor events recorded while it ran.

    The decision comes from what was recorded (an order, a block, a failure),
    not from the Trader's own description of what it did."""
    ticker = (run["ticker"] or "").upper()
    signal = parse_signal(run["analysis"]) or parse_signal(run["trade_signal"])
    recorded = bool(run["started_at"])
    run_trades = [t for t in trades if (t["ticker"] or "").upper() == ticker] or list(trades)
    trade = run_trades[-1] if run_trades else None

    blocks = [e for e in events if e["level"] == "block"]
    warnings = [e for e in events if e["level"] == "warning"]
    checked = any(e["category"] == "check" for e in events)

    if trade and trade["status"] == "blocked":
        kind = "blocked"
    elif trade and trade["status"] == "failed":
        kind = "failed"
    elif trade:
        kind = trade["side"]
    elif signal and recorded:
        kind = "hold"
    elif signal:
        kind = signal["action"].lower()  # older runs only have the Advisor's signal
    else:
        kind = "none"

    return {
        "id": run["id"],
        "ticker": ticker,
        "question": run["question"],
        "experience": run["experience"],
        "run_at": run["run_at"],
        "recorded": recorded,
        "signal": signal,
        "threshold": run["threshold"],
        "sentiment": parse_sentiment(run["analysis"]),
        "price": (stock or {}).get("currentPrice"),
        "closes": (stock or {}).get("closes") or [],
        "trade": trade,
        "kind": kind,
        "block_reason": blocks[-1]["message"] if blocks else None,
        "warnings": [w["message"] for w in warnings],
        "checked": checked,
    }


# --- HTML builders ---

def sparkline_svg(values: list[float], width: int = 84, height: int = 22) -> str:
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = width / (len(values) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - 2 - (v - low) / span * (height - 4):.1f}" for i, v in enumerate(values)
    )
    color = BUY_COLOR if values[-1] >= values[0] else SELL_COLOR
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}"><polyline points="{points}" fill="none" stroke="{color}" '
           f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>')
    # st.html strips inline <svg>, so the sparkline is embedded as an image
    encoded = base64.b64encode(svg.encode()).decode()
    return (f'<img src="data:image/svg+xml;base64,{encoded}" width="{width}" height="{height}" '
            f'alt="5-day price trend">')


def account_label(account: str) -> str:
    return "PRACTICE PORTFOLIO" if account.startswith("sim:") else "PAPER TRADING"


def topbar_html(snapshots, account: str = "alpaca") -> str:
    parts = ['<div class="aima-topbar">',
             '<div class="aima-brand">AIMA<small>Multi-Agent Trading System</small></div>']
    if not snapshots:
        parts.append('<div class="aima-note">No account data yet. Click <b>Sync</b> to load it from Alpaca.</div>')
    else:
        latest = snapshots[0]
        value = float(latest["portfolio_value"])
        change = ""
        if len(snapshots) > 1 and float(snapshots[1]["portfolio_value"]):
            previous = float(snapshots[1]["portfolio_value"])
            diff = value - previous
            css, arrow = ("aima-up", "▲") if diff >= 0 else ("aima-down", "▼")
            change = f' <span class="aima-change {css}">{arrow} {diff:+,.2f} ({diff / previous:+.2%})</span>'
        positions = len(json.loads(latest["positions_json"] or "[]"))
        for label, body in (
            ("Portfolio value", f"{fmt_money(value)}{change}"),
            ("Cash", fmt_money(latest["cash"])),
            ("Buying power", fmt_money(latest["buying_power"])),
            ("Positions", str(positions)),
            ("Synced", esc(fmt_time(latest["snapped_at"]))),
        ):
            parts.append(f'<div class="aima-kpi"><span class="aima-label">{label}</span>'
                         f'<span class="aima-value">{body}</span></div>')
    parts.append(f'<span class="aima-paper">{account_label(account)}</span></div>')
    return "".join(parts)


_STATE_LABELS = {
    "idle": "Ready", "waiting": "Waiting", "working": "Working…", "done": "Done", "blocked": "Blocked an order",
}


def card_html(name: str, kind: str, role: str, color: str, state: str,
              rows=(), note: str = "") -> str:
    """rows are (label, value_html) pairs; value_html must already be escaped."""
    body = "".join(f'<div class="aima-row"><span class="k">{esc(k)}</span><span class="v">{v}</span></div>'
                   for k, v in rows)
    if note:
        body += f'<div class="aima-note">{note}</div>'
    return (f'<div class="aima-card {state}" style="--card-accent:{color}">'
            f'<div class="aima-card-head"><span class="aima-card-name">{name}</span>'
            f'<span class="aima-card-kind">{kind}</span></div>'
            f'<div class="aima-card-role">{role}</div>'
            f'<div class="aima-state {state}"><span class="aima-dot"></span>{_STATE_LABELS[state]}</div>'
            f'{body}</div>')


def pipeline_html(cards: list[str]) -> str:
    arrow = '<div class="aima-arrow" aria-hidden="true">→</div>'
    return f'<div class="aima-pipeline">{arrow.join(cards)}</div>'


_ADVISOR = ("ADVISOR", "LLM agent", "Reads price data and news, then issues a signal")
_TRADER = ("TRADER", "LLM agent", "Checks the portfolio and decides whether to trade")
_MONITOR = ("MONITOR", "Rule-based", "Enforces risk limits on every order")


def idle_pipeline_html() -> str:
    note = "Ask a question above to start a run."
    return pipeline_html([
        card_html(*_ADVISOR, ADVISOR_COLOR, "idle", note=note),
        card_html(*_TRADER, TRADER_COLOR, "idle"),
        card_html(*_MONITOR, MONITOR_COLOR, "idle"),
    ])


def live_pipeline_html(completed_tasks: int, ticker: str) -> str:
    """Pipeline while a run is in progress. completed_tasks counts finished crew tasks."""
    t = esc(ticker)
    if completed_tasks == 0:
        states = ("working", "waiting", "waiting")
        notes = (f"Fetching price data and news for {t}…", "Waiting for the Advisor's signal.",
                 "Standing by to check any order.")
    elif completed_tasks == 1:
        states = ("done", "working", "working")
        notes = ("Signal sent to the Trader.", "Reviewing the signal and portfolio…",
                 "Checking any order against the risk limits.")
    else:
        states = ("done", "done", "working")
        notes = ("Signal sent to the Trader.", "Decision made.",
                 "Updating order statuses and checking positions…")
    return pipeline_html([
        card_html(*_ADVISOR, ADVISOR_COLOR, states[0], note=notes[0]),
        card_html(*_TRADER, TRADER_COLOR, states[1], note=notes[1]),
        card_html(*_MONITOR, MONITOR_COLOR, states[2], note=notes[2]),
    ])


def _colored(text: str, color: str) -> str:
    return f'<span style="color:{color}">{esc(text)}</span>'


_SENTIMENT_COLORS = {"BULLISH": BUY_COLOR, "BEARISH": SELL_COLOR, "NEUTRAL": HOLD_COLOR}
_ACTION_COLORS = {"BUY": BUY_COLOR, "SELL": SELL_COLOR, "HOLD": HOLD_COLOR}


def _confidence_html(signal: dict, threshold: float | None) -> str:
    """Green when the confidence meets the threshold, amber when it falls short."""
    confidence = signal.get("confidence")
    if confidence is None or threshold is None:
        return esc(fmt_confidence(signal or None))
    return _colored(fmt_confidence(signal), BUY_COLOR if confidence >= threshold else HOLD_COLOR)


def run_pipeline_html(view: dict) -> str:
    signal = view["signal"] or {}
    action = signal.get("action")

    advisor_rows = [
        ("Sentiment", _colored(view["sentiment"].title(), _SENTIMENT_COLORS[view["sentiment"]])
         if view["sentiment"] else "—"),
        ("Signal", _colored(f"{action} {view['ticker']}", _ACTION_COLORS[action]) if action else "—"),
        ("Confidence", _confidence_html(signal, view["threshold"])),
        ("Threshold", f"{view['threshold']:.2f}" if view["threshold"] is not None else "—"),
        ("Price", f"{sparkline_svg(view['closes'])}{fmt_money(view['price'])}"),
    ]
    advisor = card_html(*_ADVISOR, ADVISOR_COLOR, "done", advisor_rows)

    trade, kind = view["trade"], view["kind"]
    if not view["recorded"]:
        trader = card_html(*_TRADER, TRADER_COLOR, "done",
                           note="Order details were not recorded for runs before the Risk Monitor was added.")
        monitor = card_html(*_MONITOR, MONITOR_COLOR, "done", note="Not recorded for this run.")
        return pipeline_html([advisor, trader, monitor])

    if trade:
        order = f"{trade['side'].upper()} {trade['qty']} {trade['ticker']}"
        trader_rows = [
            ("Decision", _colored("BLOCKED" if kind == "blocked" else "FAILED" if kind == "failed" else "EXECUTE",
                                  MONITOR_COLOR if kind == "blocked" else SELL_COLOR if kind == "failed" else BUY_COLOR)),
            ("Order", esc(order)),
            ("Status", esc(trade["status"])),
            ("Fill price", fmt_money(trade["filled_avg_price"])),
        ]
    else:
        trader_rows = [("Decision", _colored("HOLD", HOLD_COLOR)), ("Order", "None placed")]
    trader = card_html(*_TRADER, TRADER_COLOR, "done", trader_rows)

    if kind == "blocked":
        monitor = card_html(*_MONITOR, MONITOR_COLOR, "blocked", note=esc(view["block_reason"] or "Order blocked."))
    else:
        pre_trade = "Passed" if trade else "No order"
        warnings = len(view["warnings"])
        monitor_rows = [
            ("Pre-trade check", _colored(pre_trade, BUY_COLOR) if trade else pre_trade),
            ("Post-run checks", "Done" if view["checked"] else "Did not run"),
            ("Warnings", _colored(str(warnings), HOLD_COLOR) if warnings else "0"),
        ]
        note = "<br>".join(esc(w) for w in view["warnings"][:3])
        monitor = card_html(*_MONITOR, MONITOR_COLOR, "done", monitor_rows, note=note)
    return pipeline_html([advisor, trader, monitor])


def _hold_reason(signal: dict, threshold: float | None) -> str:
    action, confidence = esc(signal["action"]), signal["confidence"]
    if signal["action"] == "HOLD":
        return f"The Advisor's signal was HOLD (confidence {esc(fmt_confidence(signal))}), so no order was placed."
    if confidence is None or threshold is None:
        return (f"The Advisor signaled {action} with confidence {esc(fmt_confidence(signal))}, "
                f"and the Trader did not place an order.")
    if confidence < threshold:
        return (f"The Advisor signaled {action} with confidence {confidence:.2f}, below the "
                f"{threshold:.2f} threshold, so no order was placed.")
    return (f"The Advisor signaled {action} with confidence {confidence:.2f}, which meets the "
            f"{threshold:.2f} threshold, but the Trader did not place an order. See the Trader report.")


_DECISION_STYLE = {
    "buy": ("BUY", BUY_COLOR), "sell": ("SELL", SELL_COLOR), "hold": ("HOLD", HOLD_COLOR),
    "blocked": ("BLOCKED", MONITOR_COLOR), "failed": ("FAILED", SELL_COLOR), "none": ("NO SIGNAL", MUTED_COLOR),
}


def decision_html(view: dict) -> str:
    verb, color = _DECISION_STYLE[view["kind"]]
    signal, trade, ticker = view["signal"] or {}, view["trade"], esc(view["ticker"])

    if trade:
        price = trade["filled_avg_price"] or view["price"]
        price_label = "fill" if trade["filled_avg_price"] else "last"
        what = f"{esc(trade['qty'])} × {esc(trade['ticker'])} @ {fmt_money(price)} <small>{price_label}</small>"
    else:
        what = f"{ticker} @ {fmt_money(view['price'])} <small>last</small>"

    meta = []
    if signal:
        threshold = f" · threshold {view['threshold']:.2f}" if view["threshold"] is not None else ""
        meta.append(f"Confidence {esc(fmt_confidence(signal))}{threshold}")
    if trade and view["kind"] in ("buy", "sell"):
        meta.append(f"Order {esc(trade['status'])}")

    if view["kind"] == "blocked":
        why = f"The Risk Monitor stopped this order: {esc(view['block_reason'])}"
    elif view["kind"] == "failed":
        why = "The order could not be submitted to Alpaca. See the Trader report for the error."
    elif view["kind"] == "hold" and signal:
        why = _hold_reason(signal, view["threshold"])
    elif view["kind"] == "none":
        why = "No trade signal was found in the Advisor's analysis."
    elif not view["recorded"]:
        why = "This is the Advisor's signal. Order details were not recorded for this run."
    else:
        why = ""

    return (f'<div class="aima-decision" style="--d-color:{color}">'
            f'<span class="verb">{verb}</span><span class="what">{what}</span>'
            f'<span class="meta">{"<br>".join(meta)}</span>'
            + (f'<span class="why">{why}</span>' if why else "")
            + f'<span class="question">“{esc(view["question"])}” · {esc((view["experience"] or "").title())} · '
              f'{esc(fmt_time(view["run_at"]))}</span></div>')


def limits_html(limits: dict) -> str:
    items = (
        (f"{limits['max_qty_per_order']}", "Max shares per order"),
        (f"{limits['max_trades_per_day']}", "Max trades per day"),
        (f"{limits['max_order_pct_of_cash']:.0%}", "Max buy, share of cash"),
        (f"{limits['max_position_pct_of_portfolio']:.0%}", "Max position size"),
        (f"{limits['position_loss_alert_pct']:.0%}", "Loss alert threshold"),
    )
    return '<div class="aima-limits">' + "".join(
        f'<div class="aima-limit"><div class="aima-value">{esc(v)}</div><div class="aima-label">{esc(k)}</div></div>'
        for v, k in items) + "</div>"


# --- table cell styles (pandas Styler) ---

def pnl_style(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"color: {BUY_COLOR}" if number > 0 else f"color: {SELL_COLOR}" if number < 0 else ""


_STATUS_COLORS = {
    "filled": BUY_COLOR, "blocked": MONITOR_COLOR, "failed": SELL_COLOR, "rejected": SELL_COLOR,
    "canceled": MUTED_COLOR, "expired": MUTED_COLOR, "buy": BUY_COLOR, "sell": SELL_COLOR, "hold": HOLD_COLOR,
    "block": MONITOR_COLOR, "warning": HOLD_COLOR, "info": MUTED_COLOR,
}


def label_style(value) -> str:
    color = _STATUS_COLORS.get(str(value).lower())
    return f"color: {color}; font-weight: 600" if color else ""
