"""Rule-based risk monitor.

Unlike the Advisor and Trader, the monitor uses no LLM. It applies the fixed
rules in config/risk_limits.yaml to block unsafe orders before they reach
Alpaca, blocks orders that do not match the Advisor's signal or fall below
the run's confidence threshold, and after each run checks on submitted
orders and open positions.
"""
from pathlib import Path

import yaml

from first_ai_agents.broker import record_portfolio_snapshot
from first_ai_agents.database import (
    count_trades_today, get_unsettled_trades, log_monitor_event, update_trade_status,
)

LIMITS_PATH = Path(__file__).parent / "config" / "risk_limits.yaml"

DEFAULT_LIMITS = {
    "max_qty_per_order": 100,
    "max_trades_per_day": 5,
    "max_order_pct_of_cash": 0.25,
    "max_position_pct_of_portfolio": 0.10,
    "position_loss_alert_pct": 0.10,
}


def load_limits() -> dict:
    limits = dict(DEFAULT_LIMITS)
    if LIMITS_PATH.exists():
        with open(LIMITS_PATH) as f:
            limits.update(yaml.safe_load(f) or {})
    return limits


# --- the run in progress ---
# The crew records the Advisor's parsed signal here when the Advisor finishes,
# so orders are checked against what the Advisor actually said rather than
# what the Trader reports. This assumes one crew run at a time.

DEFAULT_CONFIDENCE_THRESHOLD = 0.7
_active_run: dict | None = None


def start_run(confidence_threshold: float):
    global _active_run
    if not 0 <= confidence_threshold <= 1:
        raise ValueError(f"confidence_threshold must be between 0 and 1, got {confidence_threshold}.")
    _active_run = {"threshold": confidence_threshold, "signal": None}


def record_signal(signal: dict | None):
    if _active_run is not None:
        _active_run["signal"] = signal


def end_run():
    global _active_run
    _active_run = None


def _signal_violation(ticker: str, side: str) -> str | None:
    """Checks an order against the Advisor's signal and the run's confidence threshold."""
    if _active_run is None:
        return None  # not inside a crew run, e.g. a manual tool call
    signal, threshold = _active_run["signal"], _active_run["threshold"]
    if not signal:
        return "No TRADE SIGNAL was found in the Advisor's analysis."
    if signal["action"] == "HOLD":
        return "The Advisor's signal was HOLD, so no order is allowed."
    if signal["action"].lower() != side:
        return f"This is a {side} order, but the Advisor's signal was {signal['action']}."
    if signal["ticker"] and signal["ticker"] != ticker:
        return f"This order is for {ticker}, but the Advisor's signal was for {signal['ticker']}."
    if signal["confidence"] is None:
        return "The Advisor's signal has no numeric confidence, so the threshold cannot be checked."
    if signal["confidence"] < threshold:
        return (f"The Advisor's confidence ({signal['confidence']:.2f}) is below "
                f"the confidence threshold ({threshold:.2f}).")
    return None


# --- before an order ---

def check_order(api, ticker: str, qty: int, side: str) -> tuple[bool, str]:
    """Returns (allowed, reason). Blocked orders are logged as monitor events."""
    ticker = ticker.upper()
    reason = _order_violation(api, ticker, qty, side, load_limits())
    if reason:
        log_monitor_event("block", "order", reason, ticker)
        return False, reason
    return True, "Order passed all risk checks."


def _order_violation(api, ticker: str, qty: int, side: str, limits: dict) -> str | None:
    if side not in ("buy", "sell"):
        return f"Side must be 'buy' or 'sell', got '{side}'."
    if qty <= 0:
        return f"Quantity must be positive, got {qty}."
    if qty > limits["max_qty_per_order"]:
        return f"{qty} shares exceeds the per-order limit of {limits['max_qty_per_order']}."

    signal_problem = _signal_violation(ticker, side)
    if signal_problem:
        return signal_problem

    trades_today = count_trades_today()
    if trades_today >= limits["max_trades_per_day"]:
        return f"Daily trade limit reached ({trades_today} of {limits['max_trades_per_day']})."

    account = api.get_account()
    position = next((p for p in api.list_positions() if p.symbol == ticker), None)
    held_qty = float(position.qty) if position else 0.0

    if side == "sell":
        if qty > held_qty:
            return (f"Cannot sell {qty} shares of {ticker}: only {held_qty:g} held, "
                    f"and short selling is not allowed.")
        return None

    price = float(api.get_latest_trade(ticker).price)
    order_value = price * qty

    max_order_value = float(account.cash) * limits["max_order_pct_of_cash"]
    if order_value > max_order_value:
        return (f"Order value ${order_value:,.2f} exceeds {limits['max_order_pct_of_cash']:.0%} "
                f"of available cash (${max_order_value:,.2f}).")

    position_value = held_qty * price + order_value
    max_position_value = float(account.portfolio_value) * limits["max_position_pct_of_portfolio"]
    if position_value > max_position_value:
        return (f"{ticker} position would grow to ${position_value:,.2f}, over the "
                f"{limits['max_position_pct_of_portfolio']:.0%} portfolio limit "
                f"(${max_position_value:,.2f}).")
    return None


# --- after a run ---

def run_checks(api) -> list[str]:
    """Updates submitted orders from Alpaca, saves a portfolio snapshot, and
    flags risky positions. Returns one line per finding."""
    limits = load_limits()
    findings = []

    for trade in get_unsettled_trades():
        try:
            order = api.get_order(trade["order_id"])
        except Exception as e:
            message = f"Could not look up order {trade['order_id']}: {e}"
            log_monitor_event("warning", "order", message, trade["ticker"])
            findings.append(message)
            continue
        if order.status == trade["status"]:
            continue
        filled_price = float(order.filled_avg_price) if order.filled_avg_price else None
        update_trade_status(trade["order_id"], order.status, filled_price)
        message = f"{trade['side'].upper()} {trade['qty']} {trade['ticker']} is now {order.status}."
        level = "warning" if order.status in ("canceled", "expired", "rejected") else "info"
        log_monitor_event(level, "order", message, trade["ticker"])
        findings.append(message)

    account, positions = record_portfolio_snapshot(api)
    portfolio_value = float(account.portfolio_value)
    for p in positions:
        change = float(p.unrealized_plpc)
        if change <= -limits["position_loss_alert_pct"]:
            message = f"{p.symbol} is down {abs(change):.1%} from its average entry price."
            log_monitor_event("warning", "position", message, p.symbol)
            findings.append(message)
        weight = abs(float(p.market_value)) / portfolio_value if portfolio_value else 0.0
        if weight > limits["max_position_pct_of_portfolio"]:
            message = (f"{p.symbol} is {weight:.1%} of the portfolio, over the "
                       f"{limits['max_position_pct_of_portfolio']:.0%} limit.")
            log_monitor_event("warning", "position", message, p.symbol)
            findings.append(message)

    log_monitor_event("info", "check", f"Checks complete: {len(findings)} finding(s).")
    return findings
