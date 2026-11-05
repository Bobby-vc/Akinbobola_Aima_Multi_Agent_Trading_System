"""Scores the Advisor's past signals against what prices actually did.

Method:
- Entry is the close of the first trading session that closes after the
  signal (signals before 4 p.m. ET use that day's close; later ones and
  weekends use the next session's). No price from before the signal is used.
- Each signal is scored 1, 5, and 20 trading days after entry, using
  split- and dividend-adjusted closes.
- A BUY hits if the stock rose; a SELL hits if it fell. HOLD signals are
  shown but not scored.
- SPY over the same window is the benchmark. "Excess" is the signal's
  return minus the market's, in the signal's direction.
"""
import math
from bisect import bisect_left
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from first_ai_agents.signals import parse_signal

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_CLOSE = time(16, 0)
BENCHMARK = "SPY"
HORIZONS = (1, 5, 20)
CONFIDENCE_BUCKETS = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]


# --- prices ---

def load_daily_closes(tickers: list[str], start: date) -> pd.DataFrame:
    """Adjusted daily closes from yfinance, one column per ticker, indexed by date.

    Today's row is dropped until the market has closed, because during the
    session yfinance reports the latest price as if it were the close."""
    import yfinance as yf

    symbols = sorted(set(tickers) | {BENCHMARK})
    data = yf.download(symbols, start=start.isoformat(), auto_adjust=True, progress=False)
    closes = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data[["Close"]]
    if not isinstance(data.columns, pd.MultiIndex):
        closes.columns = symbols
    closes.index = pd.to_datetime(closes.index).date
    now = datetime.now(MARKET_TZ)
    if now.time() < MARKET_CLOSE and now.date() in closes.index:
        closes = closes.drop(index=now.date())
    return closes


def entry_session(signal_at_utc: str, sessions: list[date]) -> date | None:
    """The first session whose close comes after the signal, or None if it hasn't happened yet."""
    moment = datetime.fromisoformat(signal_at_utc).replace(tzinfo=timezone.utc).astimezone(MARKET_TZ)
    earliest = moment.date() if moment.time() < MARKET_CLOSE else moment.date() + timedelta(days=1)
    i = bisect_left(sessions, earliest)
    return sessions[i] if i < len(sessions) else None


# --- scoring ---

def score_signals(runs, closes: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    """One row per run with a parseable signal: entry, returns, excess vs SPY, and hits."""
    sessions = list(closes.index)
    benchmark = closes[BENCHMARK] if BENCHMARK in closes else None
    rows = []
    for run in runs:
        signal = parse_signal(run["analysis"]) or parse_signal(run["trade_signal"])
        if not signal:
            continue
        ticker = (run["ticker"] or "").upper()
        confidence = signal["confidence"]
        threshold = run["threshold"]
        row = {
            "run_id": run["id"], "signal_at": run["run_at"], "ticker": ticker,
            "action": signal["action"], "confidence": confidence, "threshold": threshold,
            "cleared": (confidence >= threshold) if confidence is not None and threshold is not None else None,
            "entry_date": None, "entry_price": None, "status": "pending",
        }
        prices = closes[ticker] if ticker in closes else None
        entry = entry_session(run["run_at"], sessions) if sessions else None
        if prices is None or prices.dropna().empty:
            row["status"] = "no price data"
        elif entry is not None and not math.isnan(prices[entry]):
            i = sessions.index(entry)
            row.update(entry_date=entry, entry_price=float(prices[entry]), status="scored")
            direction = {"BUY": 1, "SELL": -1}.get(signal["action"])
            for h in horizons:
                ret = excess = hit = None
                if i + h < len(sessions) and not math.isnan(prices[sessions[i + h]]):
                    ret = float(prices[sessions[i + h]] / prices[entry] - 1)
                    if direction:
                        hit = direction * ret > 0
                        if benchmark is not None:
                            market = float(benchmark[sessions[i + h]] / benchmark[entry] - 1)
                            excess = direction * (ret - market)
                row[f"ret_{h}"], row[f"excess_{h}"], row[f"hit_{h}"] = ret, excess, hit
        for h in horizons:
            row.setdefault(f"ret_{h}", None)
            row.setdefault(f"excess_{h}", None)
            row.setdefault(f"hit_{h}", None)
        rows.append(row)
    return pd.DataFrame(rows)


def wilson_interval(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a hit rate; wide when n is small."""
    if n == 0:
        return (math.nan, math.nan)
    p = hits / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (center - half, center + half)


def _scored(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """BUY/SELL signals whose horizon has passed."""
    if df.empty:
        return df
    return df[df[f"hit_{horizon}"].notna()]


def summarize(df: pd.DataFrame, horizon: int) -> dict:
    scored = _scored(df, horizon)
    n = len(scored)
    hits = int(scored[f"hit_{horizon}"].astype(bool).sum()) if n else 0
    directional = scored["action"].map({"BUY": 1, "SELL": -1}) * scored[f"ret_{horizon}"] if n else pd.Series(dtype=float)
    low, high = wilson_interval(hits, n)
    return {
        "n": n,
        "hits": hits,
        "hit_rate": hits / n if n else math.nan,
        "hit_rate_low": low,
        "hit_rate_high": high,
        "avg_return": float(directional.mean()) if n else math.nan,
        "avg_excess": float(scored[f"excess_{horizon}"].dropna().mean()) if n else math.nan,
        "pending": int(((df["action"] != "HOLD") & df[f"hit_{horizon}"].isna()).sum()) if not df.empty else 0,
    }


def calibration(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Hit rate by confidence bucket. Well calibrated means hit rate rises with confidence."""
    scored = _scored(df, horizon)
    scored = scored[scored["confidence"].notna()] if not scored.empty else scored
    columns = ["bucket", "n", "mean_confidence", "hit_rate", "low", "high"]
    if scored.empty:
        return pd.DataFrame(columns=columns)
    labels = [f"{lo:.2f}–{min(hi, 1):.2f}" if lo else "below 0.50"
              for lo, hi in zip(CONFIDENCE_BUCKETS[:-1], CONFIDENCE_BUCKETS[1:])]
    buckets = pd.cut(scored["confidence"], CONFIDENCE_BUCKETS, right=False, labels=labels)
    rows = []
    for label, group in scored.groupby(buckets, observed=True):
        n, hits = len(group), int(group[f"hit_{horizon}"].astype(bool).sum())
        low, high = wilson_interval(hits, n)
        rows.append({"bucket": label, "n": n, "mean_confidence": float(group["confidence"].mean()),
                     "hit_rate": hits / n, "low": low, "high": high})
    return pd.DataFrame(rows, columns=columns)


def threshold_split(df: pd.DataFrame, horizon: int) -> dict:
    """Did signals that cleared the threshold do better than the ones it filtered out?"""
    scored = _scored(df, horizon)
    result = {}
    for key, cleared in (("cleared", True), ("filtered", False)):
        group = scored[scored["cleared"] == cleared] if not scored.empty else scored
        n = len(group)
        hits = int(group[f"hit_{horizon}"].astype(bool).sum()) if n else 0
        result[key] = {"n": n, "hit_rate": hits / n if n else math.nan}
    return result
