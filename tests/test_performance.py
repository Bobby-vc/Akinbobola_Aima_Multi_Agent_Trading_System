import math
from datetime import date, datetime

import pandas as pd
import pytest

import first_ai_agents.performance as perf

# Weekdays from Mon Nov 2 to Fri Dec 18, 2026: 35 sessions
SESSIONS = list(pd.bdate_range("2026-11-02", "2026-12-18").date)


def series(start: float, daily: float) -> list[float]:
    return [start * (1 + daily) ** i for i in range(len(SESSIONS))]


CLOSES = pd.DataFrame({
    "UP": series(100, 0.01),      # rises 1% a day
    "DOWN": series(100, -0.01),   # falls 1% a day
    "SPY": series(500, 0.002),    # the market rises 0.2% a day
}, index=SESSIONS)


def run(run_id, ticker, signal, run_at="2026-11-02T15:00:00", threshold=0.7):
    return {"id": run_id, "ticker": ticker, "run_at": run_at, "threshold": threshold,
            "analysis": f"TRADE SIGNAL: {signal}", "trade_signal": ""}


@pytest.mark.parametrize("signal_at_utc, expected", [
    ("2026-11-02T15:00:00", date(2026, 11, 2)),   # 10:00 ET Monday: that day's close
    ("2026-11-02T22:00:00", date(2026, 11, 3)),   # 17:00 ET Monday: after the close
    ("2026-11-07T15:00:00", date(2026, 11, 9)),   # Saturday: Monday's close
    ("2026-12-19T15:00:00", None),                # after the last known session
])
def test_entry_session(signal_at_utc, expected):
    assert perf.entry_session(signal_at_utc, SESSIONS) == expected


def scored(*runs):
    return perf.score_signals(list(runs), CLOSES).set_index("run_id")


def test_buy_and_sell_hits_and_misses():
    df = scored(
        run(1, "UP", "BUY UP | Confidence: 0.8"),
        run(2, "DOWN", "SELL DOWN | Confidence: 0.8"),
        run(3, "DOWN", "BUY DOWN | Confidence: 0.8"),
    )
    assert df.loc[1, "hit_5"] and df.loc[2, "hit_5"] and not df.loc[3, "hit_5"]
    assert df.loc[1, "ret_5"] == pytest.approx(1.01 ** 5 - 1)
    assert df.loc[1, "entry_price"] == pytest.approx(100)


def test_excess_is_measured_in_the_signal_direction():
    df = scored(run(1, "UP", "BUY UP | Confidence: 0.8"), run(2, "DOWN", "SELL DOWN | Confidence: 0.8"))
    market = 1.002 ** 5 - 1
    assert df.loc[1, "excess_5"] == pytest.approx((1.01 ** 5 - 1) - market)
    assert df.loc[2, "excess_5"] == pytest.approx(-((0.99 ** 5 - 1) - market))


def test_hold_is_priced_but_not_scored():
    row = scored(run(1, "UP", "HOLD UP | Confidence: 0.6")).loc[1]
    assert row["ret_5"] == pytest.approx(1.01 ** 5 - 1)
    assert row["hit_5"] is None and row["excess_5"] is None


def test_horizons_past_the_data_are_pending():
    row = scored(run(1, "UP", "BUY UP | Confidence: 0.8", run_at="2026-12-10T15:00:00")).loc[1]
    assert row["hit_5"] and row["hit_20"] is None
    assert row["status"] == "scored"


def test_unknown_ticker_and_future_signal():
    df = scored(run(1, "NOPE", "BUY NOPE"), run(2, "UP", "BUY UP", run_at="2026-12-20T15:00:00"))
    assert df.loc[1, "status"] == "no price data"
    assert df.loc[2, "status"] == "pending" and df.loc[2, "entry_date"] is None


def test_runs_without_a_signal_are_skipped():
    no_signal = {"id": 1, "ticker": "UP", "run_at": "2026-11-02T15:00:00", "threshold": 0.7,
                 "analysis": "nothing", "trade_signal": ""}
    assert perf.score_signals([no_signal], CLOSES).empty


def test_summarize():
    df = perf.score_signals([
        run(1, "UP", "BUY UP | Confidence: 0.8"),
        run(2, "DOWN", "SELL DOWN | Confidence: 0.8"),
        run(3, "DOWN", "BUY DOWN | Confidence: 0.8"),
        run(4, "UP", "HOLD UP | Confidence: 0.5"),
        run(5, "UP", "BUY UP | Confidence: 0.8", run_at="2026-12-17T15:00:00"),
    ], CLOSES)
    summary = perf.summarize(df, 5)
    assert (summary["n"], summary["hits"], summary["pending"]) == (3, 2, 1)
    assert summary["hit_rate"] == pytest.approx(2 / 3)
    assert summary["avg_return"] == pytest.approx(((1.01 ** 5 - 1) - (0.99 ** 5 - 1) + (0.99 ** 5 - 1)) / 3)
    assert summary["hit_rate_low"] < 2 / 3 < summary["hit_rate_high"]


def test_summarize_with_no_signals():
    summary = perf.summarize(perf.score_signals([], CLOSES), 5)
    assert summary["n"] == 0 and math.isnan(summary["hit_rate"])


def test_wilson_interval():
    low, high = perf.wilson_interval(8, 10)
    assert low == pytest.approx(0.4902, abs=1e-4) and high == pytest.approx(0.9433, abs=1e-4)
    assert all(math.isnan(x) for x in perf.wilson_interval(0, 0))


def test_calibration_buckets():
    df = perf.score_signals([
        run(1, "UP", "BUY UP | Confidence: 0.85"),
        run(2, "UP", "BUY UP | Confidence: 0.82"),
        run(3, "DOWN", "BUY DOWN | Confidence: 0.55"),
        run(4, "DOWN", "BUY DOWN | Confidence: MEDIUM"),  # no number: left out
    ], CLOSES)
    cal = perf.calibration(df, 5).set_index("bucket")
    assert list(cal.index) == ["0.50–0.60", "0.80–0.90"]
    assert cal.loc["0.80–0.90", "n"] == 2 and cal.loc["0.80–0.90", "hit_rate"] == 1
    assert cal.loc["0.50–0.60", "hit_rate"] == 0


def test_threshold_split():
    df = perf.score_signals([
        run(1, "UP", "BUY UP | Confidence: 0.85"),
        run(2, "DOWN", "BUY DOWN | Confidence: 0.55"),
        run(3, "UP", "BUY UP | Confidence: 0.60"),
    ], CLOSES)
    split = perf.threshold_split(df, 5)
    assert split["cleared"] == {"n": 1, "hit_rate": 1.0}
    assert split["filtered"]["n"] == 2 and split["filtered"]["hit_rate"] == 0.5


def test_todays_unfinished_close_is_dropped(monkeypatch):
    today = date(2026, 11, 5)
    download = pd.DataFrame(
        {("Close", "SPY"): [500.0, 501.0], ("Close", "UP"): [100.0, 101.0]},
        index=pd.to_datetime([date(2026, 11, 4), today]),
    )
    monkeypatch.setattr("yfinance.download", lambda *a, **k: download)

    class At(datetime):
        moment = None

        @classmethod
        def now(cls, tz=None):
            return cls.moment.replace(tzinfo=tz)

    monkeypatch.setattr(perf, "datetime", At)
    At.moment = datetime(2026, 11, 5, 11, 0)   # 11:00 ET, market open
    assert list(perf.load_daily_closes(["UP"], date(2026, 11, 1)).index) == [date(2026, 11, 4)]
    At.moment = datetime(2026, 11, 5, 16, 30)  # after the close
    assert list(perf.load_daily_closes(["UP"], date(2026, 11, 1)).index) == [date(2026, 11, 4), today]
