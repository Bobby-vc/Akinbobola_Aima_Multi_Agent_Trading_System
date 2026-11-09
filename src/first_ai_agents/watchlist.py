"""Runs the agents over a watchlist, one ticker at a time.

Meant to be scheduled once per trading day to build the track record shown
on the dashboard's Performance tab:

    uv run run_watchlist                  # every ticker in config/watchlist.yaml
    uv run run_watchlist --tickers NVDA   # just these tickers
    uv run run_watchlist --force          # run even on a non-trading day

Days the market is closed are skipped (using Alpaca's calendar, so holidays
count), as are tickers that already ran today. The agents' detailed output
goes to logs/watchlist-<date>.log; the console shows one line per ticker.
"""
import argparse
import contextlib
from datetime import datetime, time, timezone
from pathlib import Path

import yaml

from first_ai_agents.broker import get_alpaca_api
from first_ai_agents.database import get_crew_runs, get_trades_between, utc_now
from first_ai_agents.monitor import DEFAULT_CONFIDENCE_THRESHOLD
from first_ai_agents.performance import MARKET_TZ
from first_ai_agents.signals import parse_signal

WATCHLIST_PATH = Path(__file__).parent / "config" / "watchlist.yaml"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"

DEFAULTS = {
    "tickers": [],
    "experience_level": "intermediate",
    "confidence_threshold": DEFAULT_CONFIDENCE_THRESHOLD,
    "question": "Is {ticker} a good trade right now?",
}


def load_watchlist() -> dict:
    watchlist = dict(DEFAULTS)
    if WATCHLIST_PATH.exists():
        with open(WATCHLIST_PATH) as f:
            watchlist.update(yaml.safe_load(f) or {})
    watchlist["tickers"] = [t.strip().upper() for t in watchlist["tickers"] if t and t.strip()]
    return watchlist


def is_trading_day(api, day) -> bool:
    return bool(api.get_calendar(start=day.isoformat(), end=day.isoformat()))


def start_of_market_day(day) -> str:
    """Midnight in New York on `day`, in the naive UTC format stored in the database."""
    midnight = datetime.combine(day, time(0), MARKET_TZ)
    return midnight.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def tickers_already_run(since: str) -> set[str]:
    return {(r["ticker"] or "").upper() for r in get_crew_runs(limit=5000) if r["run_at"] >= since}


def describe_run(run, trades) -> str:
    """One line: the Advisor's signal and what happened to it."""
    signal = parse_signal(run["analysis"]) or parse_signal(run["trade_signal"])
    if not signal:
        said = "no signal"
    elif signal["confidence"] is not None:
        said = f"{signal['action']} {signal['confidence']:.2f}"
    else:
        said = f"{signal['action']} {signal['label'] or ''}".strip()
    trade = trades[-1] if trades else None
    if trade is None:
        outcome = "no order"
    elif trade["status"] == "blocked":
        outcome = "blocked by Risk Monitor"
    elif trade["status"] == "failed":
        outcome = "order failed"
    else:
        outcome = f"{trade['side']} {trade['qty']} {trade['status']}"
    return f"{said} -> {outcome}"


def run_watchlist(tickers: list[str] | None = None, force: bool = False, api=None, crew_factory=None) -> dict:
    """Runs each ticker and returns {ticker: one-line result}."""
    watchlist = load_watchlist()
    tickers = [t.upper() for t in tickers] if tickers else watchlist["tickers"]
    if not tickers:
        print("The watchlist is empty. Add tickers to config/watchlist.yaml.")
        return {}

    today = datetime.now(MARKET_TZ).date()
    api = api or get_alpaca_api()
    if not force and not is_trading_day(api, today):
        print(f"{today} is not a trading day; nothing to do. Use --force to run anyway.")
        return {}

    if crew_factory is None:
        from first_ai_agents.crew import FirstAiAgents
        crew_factory = lambda: FirstAiAgents().crew()

    done_today = tickers_already_run(start_of_market_day(today))
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"watchlist-{today}.log"
    results = {}
    for ticker in tickers:
        if ticker in done_today:
            results[ticker] = "skipped: already ran today"
            print(f"{ticker:6} {results[ticker]}")
            continue
        started = utc_now().isoformat()
        inputs = {
            "question": watchlist["question"].format(ticker=ticker),
            "ticker": ticker,
            "experience_level": watchlist["experience_level"],
            "confidence_threshold": float(watchlist["confidence_threshold"]),
        }
        try:
            with open(log_path, "a", encoding="utf-8") as log, contextlib.redirect_stdout(log):
                print(f"\n===== {ticker} at {started} UTC =====")
                crew_factory().kickoff(inputs=inputs)
            latest = get_crew_runs(limit=1)
            if not latest or latest[0]["run_at"] < started:
                results[ticker] = "error: the run finished but was not saved"
            else:
                run = latest[0]
                results[ticker] = describe_run(run, get_trades_between(run["started_at"] or started, run["run_at"]))
        except Exception as e:
            results[ticker] = f"error: {e}"
        print(f"{ticker:6} {results[ticker]}")

    print(f"Agent output: {log_path}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Run the trading agents over the watchlist.")
    parser.add_argument("--tickers", nargs="+", help="run these tickers instead of the watchlist")
    parser.add_argument("--force", action="store_true", help="run even if the market is closed today")
    args = parser.parse_args()
    run_watchlist(tickers=args.tickers, force=args.force)


if __name__ == "__main__":
    main()
