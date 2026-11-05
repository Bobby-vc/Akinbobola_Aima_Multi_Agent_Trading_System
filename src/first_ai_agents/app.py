import contextlib
import json
import math
import threading
import time
from datetime import date, timedelta
from io import StringIO

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from first_ai_agents import performance, ui
from first_ai_agents.database import (
    get_cached_stock, get_crew_run, get_crew_runs, get_monitor_events,
    get_monitor_events_between, get_portfolio_snapshots, get_trades, get_trades_between, utc_now,
)
from first_ai_agents.monitor import DEFAULT_CONFIDENCE_THRESHOLD, load_limits
from first_ai_agents.signals import parse_signal

load_dotenv()

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AIMA · Multi-Agent Trading",
    page_icon=":material/monitoring:",
    layout="wide",
)
st.html(ui.CSS)


@st.cache_data(ttl=3600, show_spinner="Loading price history...")
def cached_closes(tickers: tuple[str, ...], start: date) -> pd.DataFrame:
    return performance.load_daily_closes(list(tickers), start)


def load_run_view(run) -> dict:
    """Gathers the trades and monitor events recorded while a run was in progress."""
    start, end = run["started_at"], run["run_at"]
    trades = get_trades_between(start, end) if start else []
    events = get_monitor_events_between(start, end) if start else []
    stock = get_cached_stock(run["ticker"], max_age_minutes=10**9) if run["ticker"] else None
    return ui.build_run_view(run, trades, events, stock)


def run_crew_live(inputs: dict, slot) -> tuple[Exception | None, str]:
    """Runs the crew in a worker thread and redraws the pipeline as each task finishes."""
    from first_ai_agents.crew import FirstAiAgents

    progress = {"completed": 0, "done": False, "error": None}
    logs = StringIO()
    crew = FirstAiAgents().crew()
    crew.task_callback = lambda output: progress.update(completed=progress["completed"] + 1)

    def work():
        try:
            with contextlib.redirect_stdout(logs):
                crew.kickoff(inputs=inputs)
        except Exception as e:
            progress["error"] = e
        finally:
            progress["done"] = True

    threading.Thread(target=work, daemon=True).start()
    shown = None
    while True:
        if progress["completed"] != shown:
            shown = progress["completed"]
            slot.html(ui.live_pipeline_html(shown, inputs["ticker"]))
        if progress["done"]:
            return progress["error"], logs.getvalue()
        time.sleep(0.3)


# ── Top bar — account ──────────────────────────────────────────────────────────
bar_col, sync_col = st.columns([8, 1], vertical_alignment="center")
with bar_col:
    st.html(ui.topbar_html(get_portfolio_snapshots(limit=2)))
with sync_col:
    if st.button("Sync", icon=":material/sync:", help="Load the latest account data from Alpaca",
                 width="stretch"):
        try:
            from first_ai_agents.broker import get_alpaca_api, record_portfolio_snapshot
            record_portfolio_snapshot(get_alpaca_api())
            st.rerun()
        except Exception as e:
            st.error(f"Could not load the account from Alpaca: {e}")

# ── Question form ──────────────────────────────────────────────────────────────
with st.form("ask", border=False):
    q_col, t_col = st.columns([4, 1])
    question = q_col.text_input("Investment question", placeholder="Is NVDA a good buy right now?")
    ticker = t_col.text_input("Ticker", placeholder="NVDA").upper().strip()
    e_col, c_col, b_col = st.columns([2.6, 2.4, 1.2], vertical_alignment="bottom")
    experience = e_col.segmented_control(
        "Experience level", ["beginner", "intermediate", "advanced"],
        default="beginner", format_func=str.title,
    )
    threshold = c_col.slider(
        "Confidence threshold", min_value=0.0, max_value=1.0, value=DEFAULT_CONFIDENCE_THRESHOLD,
        step=0.05, format="%.2f",
        help="The Advisor rates each signal from 0 to 1. Orders below this are blocked by the Risk Monitor.",
    )
    submitted = b_col.form_submit_button(
        "Run agents", icon=":material/play_arrow:", type="primary", width="stretch",
    )

# ── Agent pipeline ─────────────────────────────────────────────────────────────
pipeline_slot = st.empty()

if submitted:
    if not question or not ticker:
        st.warning("Enter both an investment question and a ticker.")
    else:
        started = utc_now().isoformat()
        error, logs = run_crew_live(
            {
                "question": question,
                "ticker": ticker,
                "experience_level": experience or "beginner",
                "confidence_threshold": threshold,
            },
            pipeline_slot,
        )
        latest = get_crew_runs(limit=1)
        if error or not latest or latest[0]["run_at"] < started:
            st.error(f"The run did not finish: {error or 'it was not saved to the database.'}")
            if logs:
                with st.expander("Agent logs", icon=":material/terminal:"):
                    st.code(logs, language=None)
            st.stop()
        st.session_state.setdefault("run_logs", {})[latest[0]["id"]] = logs
        st.session_state["selected_run_id"] = latest[0]["id"]
        st.rerun()

runs = get_crew_runs(limit=50)
run_ids = [r["id"] for r in runs]
if run_ids and st.session_state.get("selected_run_id") not in run_ids:
    st.session_state["selected_run_id"] = run_ids[0]

if not runs:
    pipeline_slot.html(ui.idle_pipeline_html())
else:
    run = get_crew_run(st.session_state["selected_run_id"])
    view = load_run_view(run)
    pipeline_slot.html(ui.run_pipeline_html(view))
    st.html(ui.decision_html(view))

    a_col, t_col = st.columns(2)
    with a_col.expander("Advisor analysis", icon=":material/insights:"):
        st.markdown(ui.markdown_safe(run["analysis"]) or "_No analysis recorded._")
    with t_col.expander("Trader report", icon=":material/receipt_long:"):
        st.markdown(ui.markdown_safe(run["trade_signal"]) or "_No report recorded._")
    logs = st.session_state.get("run_logs", {}).get(run["id"])
    if logs:
        with st.expander("Agent logs", icon=":material/terminal:"):
            st.code(logs, language=None)

# ── Detail tabs ────────────────────────────────────────────────────────────────
st.write("")
tab_performance, tab_positions, tab_trades, tab_portfolio, tab_monitor, tab_history = st.tabs([
    ":material/query_stats: Performance",
    ":material/account_balance_wallet: Positions",
    ":material/swap_horiz: Trades",
    ":material/show_chart: Portfolio",
    ":material/shield: Risk Monitor",
    ":material/history: Run History",
])

snapshots = get_portfolio_snapshots(limit=200)

with tab_performance:
    st.caption(
        "How the Advisor's signals turned out. Each signal is priced at the first market close after it "
        "was made, then scored after 1, 5, and 20 trading days against the S&P 500 (SPY). A BUY counts as "
        "a hit if the stock rose; a SELL if it fell. HOLD signals are not scored."
    )
    all_runs = get_crew_runs(limit=5000)
    if not all_runs:
        st.info("No runs yet. Each signal is scored here once enough trading days have passed.")
    else:
        tickers = tuple(sorted({(r["ticker"] or "").upper() for r in all_runs if r["ticker"]}))
        start = min(date.fromisoformat(r["run_at"][:10]) for r in all_runs) - timedelta(days=7)
        try:
            closes = cached_closes(tickers, start)
        except Exception as e:
            closes = None
            st.error(f"Could not load price history from Yahoo Finance: {e}")

        if closes is not None:
            scores = performance.score_signals(all_runs, closes)
            horizon = st.segmented_control(
                "Holding period", performance.HORIZONS, default=5, key="perf_horizon",
                format_func=lambda h: f"{h} trading day" + ("s" if h > 1 else ""),
            ) or 5
            summary = performance.summarize(scores, horizon)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Signals scored", summary["n"],
                      help=f"{summary['pending']} more BUY/SELL signals are waiting for {horizon} trading days to pass.")
            c2.metric("Hit rate", ui.fmt_pct(summary["hit_rate"], signed=False),
                      help="95% confidence range: "
                           f"{ui.fmt_pct(summary['hit_rate_low'], signed=False)} to "
                           f"{ui.fmt_pct(summary['hit_rate_high'], signed=False)}")
            c3.metric("Avg return per signal", ui.fmt_pct(summary["avg_return"]),
                      help="In the signal's direction: a SELL earns when the stock falls.")
            c4.metric("Avg vs S&P 500", ui.fmt_pct(summary["avg_excess"]),
                      help="The signal's return minus SPY's over the same days.")
            if not summary["n"]:
                st.info(f"No signals have reached {horizon} trading days yet. Check back once they have.")
            elif summary["n"] < 20:
                st.warning(
                    f"Only {summary['n']} signal(s) scored at {horizon} days. With fewer than about 20, "
                    "these numbers are mostly noise: the hit rate's 95% range is "
                    f"{ui.fmt_pct(summary['hit_rate_low'], signed=False)} to "
                    f"{ui.fmt_pct(summary['hit_rate_high'], signed=False)}."
                )

            cal_col, split_col = st.columns([3, 2])
            with cal_col:
                st.markdown("**Calibration:** do higher-confidence signals hit more often?")
                cal = performance.calibration(scores, horizon)
                if cal.empty:
                    st.caption("Appears once signals with a numeric confidence have been scored.")
                else:
                    # Start the confidence axis just below the lowest bucket so the points spread out
                    x_low = min(0.4, math.floor(cal["mean_confidence"].min() * 10) / 10)
                    domain = alt.Scale(domain=[0, 1])
                    base = alt.Chart(cal).encode(
                        x=alt.X("mean_confidence:Q", title="Advisor confidence",
                                scale=alt.Scale(domain=[x_low, 1]), axis=alt.Axis(format=".1f")),
                    )
                    ideal = alt.Chart(pd.DataFrame({"x": [x_low, 1], "y": [x_low, 1]})).mark_line(
                        strokeDash=[4, 4], color=ui.MUTED_COLOR,
                    ).encode(x="x:Q", y="y:Q")
                    bars = base.mark_rule(color=ui.ADVISOR_COLOR, opacity=0.5).encode(
                        y=alt.Y("low:Q", title="Hit rate", scale=domain, axis=alt.Axis(format=".0%")),
                        y2="high:Q",
                    )
                    points = base.mark_circle(color=ui.ADVISOR_COLOR, opacity=0.9).encode(
                        y="hit_rate:Q",
                        size=alt.Size("n:Q", legend=None, scale=alt.Scale(range=[60, 400])),
                        tooltip=[
                            alt.Tooltip("bucket:N", title="Confidence"),
                            alt.Tooltip("n:Q", title="Signals"),
                            alt.Tooltip("hit_rate:Q", title="Hit rate", format=".0%"),
                            alt.Tooltip("low:Q", title="95% low", format=".0%"),
                            alt.Tooltip("high:Q", title="95% high", format=".0%"),
                        ],
                    )
                    st.altair_chart(
                        (ideal + bars + points).properties(height=260).configure_view(strokeWidth=0),
                        width="stretch",
                    )
                    st.caption("Dashed line: a perfectly calibrated Advisor, whose 0.7 signals hit 70% "
                               "of the time. Bars show each bucket's 95% range.")
            with split_col:
                st.markdown("**Is the threshold helping?**")
                split = performance.threshold_split(scores, horizon)
                s1, s2 = st.columns(2)
                s1.metric("Cleared threshold", ui.fmt_pct(split["cleared"]["hit_rate"], signed=False),
                          help=f"{split['cleared']['n']} scored signals at or above their run's threshold")
                s2.metric("Filtered out", ui.fmt_pct(split["filtered"]["hit_rate"], signed=False),
                          help=f"{split['filtered']['n']} scored signals below their run's threshold")
                st.caption(
                    "Hit rates of signals the threshold let through versus the ones it held back. If the "
                    "filtered-out signals hit just as often, the threshold isn't adding value."
                )

            if not scores.empty:
                table = scores.copy()
                direction = table["action"].map({"BUY": 1, "SELL": -1})
                for h in performance.HORIZONS:
                    table[f"sig_{h}"] = direction * pd.to_numeric(table[f"ret_{h}"])
                table = table.sort_values("signal_at", ascending=False)
                table["signal_at"] = table["signal_at"].map(ui.fmt_time)
                table["confidence"] = table["confidence"].map(lambda c: "—" if pd.isna(c) else f"{c:.2f}")
                table["entry_date"] = table["entry_date"].map(lambda d: d.isoformat() if d else "—")
                table = table[[
                    "signal_at", "ticker", "action", "confidence", "entry_date", "entry_price",
                    "sig_1", "sig_5", "sig_20", f"excess_{horizon}", "status",
                ]].rename(columns={
                    "signal_at": "Signal", "ticker": "Ticker", "action": "Action", "confidence": "Confidence",
                    "entry_date": "Entry", "entry_price": "Entry close", "sig_1": "1 day", "sig_5": "5 days",
                    "sig_20": "20 days", f"excess_{horizon}": f"vs S&P ({horizon}d)", "status": "Status",
                })
                returns = ["1 day", "5 days", "20 days", f"vs S&P ({horizon}d)"]
                # Streamlit draws empty cells as "None" whatever their format, so values are
                # turned into text first and the colors are worked out from the numbers
                numbers = table[returns].apply(pd.to_numeric)
                colors = numbers.map(ui.pnl_style)
                table[returns] = numbers.map(ui.fmt_pct)
                table["Entry close"] = table["Entry close"].map(ui.fmt_money)
                st.dataframe(
                    table.style.apply(lambda _: colors, axis=None, subset=returns)
                         .map(ui.label_style, subset=["Action"]),
                    hide_index=True, width="stretch",
                )
                st.caption("Returns are in the signal's direction, from adjusted closes. "
                           "A dash means that many trading days haven't passed yet.")

with tab_positions:
    positions = json.loads(snapshots[0]["positions_json"]) if snapshots else []
    if not positions:
        st.info("No open positions in the latest snapshot. Click **Sync** to refresh.")
    else:
        df = pd.DataFrame(positions)
        for column in ("qty", "avg_entry_price", "current_price", "unrealized_pl"):
            df[column] = pd.to_numeric(df[column])
        df["pl_pct"] = df["current_price"] / df["avg_entry_price"] - 1
        df = df.rename(columns={
            "symbol": "Symbol", "qty": "Shares", "avg_entry_price": "Avg Price",
            "current_price": "Price", "unrealized_pl": "P&L", "pl_pct": "P&L %",
        })
        st.dataframe(
            df.style.format({
                "Shares": "{:,.0f}", "Avg Price": "${:,.2f}", "Price": "${:,.2f}",
                "P&L": lambda v: f"{'+' if v >= 0 else '-'}${abs(v):,.2f}", "P&L %": "{:+.2%}",
            }).map(ui.pnl_style, subset=["P&L", "P&L %"]),
            hide_index=True, width="stretch",
        )
        st.caption(f"As of {ui.fmt_time(snapshots[0]['snapped_at'])}")

with tab_trades:
    trades = get_trades(limit=200)
    if not trades:
        st.info("No trades recorded yet. Run the agents to generate one.")
    else:
        df = pd.DataFrame([dict(t) for t in trades])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", len(df))
        c2.metric("Buys", int((df["side"] == "buy").sum()))
        c3.metric("Sells", int((df["side"] == "sell").sum()))
        c4.metric("Blocked", int((df["status"] == "blocked").sum()))
        df["traded_at"] = df["traded_at"].map(ui.fmt_time)
        df = df[["traded_at", "ticker", "side", "qty", "status", "filled_avg_price", "order_id"]].rename(columns={
            "traded_at": "Time", "ticker": "Ticker", "side": "Side", "qty": "Shares",
            "status": "Status", "filled_avg_price": "Fill Price", "order_id": "Order ID",
        })
        # Text, not numbers: Streamlit shows empty cells as "None" whatever their format
        df["Fill Price"] = df["Fill Price"].map(ui.fmt_money)
        df["Order ID"] = df["Order ID"].fillna("—")
        st.dataframe(
            df.style.map(ui.label_style, subset=["Side", "Status"]),
            hide_index=True, width="stretch",
        )

with tab_portfolio:
    if not snapshots:
        st.info("No portfolio snapshots yet. Click **Sync** to take one.")
    else:
        df = pd.DataFrame([dict(s) for s in snapshots])
        df["snapped_at"] = pd.to_datetime(df["snapped_at"])
        low, high = df["portfolio_value"].min(), df["portfolio_value"].max()
        pad = max((high - low) * 0.15, high * 0.001)
        base = alt.Chart(df).encode(
            x=alt.X("snapped_at:T", title=None, axis=alt.Axis(grid=False)),
            # An area fills down to zero unless the axis range is set explicitly
            y=alt.Y("portfolio_value:Q", title=None, scale=alt.Scale(domain=[low - pad, high + pad]),
                    axis=alt.Axis(format="$,.0f")),
            tooltip=[
                alt.Tooltip("snapped_at:T", title="Time", format="%b %d %H:%M"),
                alt.Tooltip("portfolio_value:Q", title="Portfolio value", format="$,.2f"),
                alt.Tooltip("cash:Q", title="Cash", format="$,.2f"),
            ],
        )
        chart = (
            base.mark_area(color=ui.TRADER_COLOR, opacity=0.12, clip=True)
            + base.mark_line(color=ui.TRADER_COLOR, strokeWidth=2)
            + base.mark_circle(color=ui.TRADER_COLOR, size=28)
        ).properties(height=280).configure_view(strokeWidth=0)
        st.altair_chart(chart, width="stretch")
        st.caption(f"{len(df)} snapshots · taken on every Sync and whenever the Trader checks the portfolio")

with tab_monitor:
    st.caption(
        "The Risk Monitor is rule-based and uses no LLM. It blocks any order that breaks these "
        "limits, and after each run it updates order statuses and flags risky positions."
    )
    st.html(ui.limits_html(load_limits()))
    l_col, r_col = st.columns([3, 1], vertical_alignment="center")
    l_col.caption("Change the limits in `src/first_ai_agents/config/risk_limits.yaml`.")
    if r_col.button("Run checks now", icon=":material/policy:", width="stretch"):
        with st.spinner("Checking orders and positions..."):
            try:
                from first_ai_agents.broker import get_alpaca_api
                from first_ai_agents.monitor import run_checks
                findings = run_checks(get_alpaca_api())
                if findings:
                    for finding in findings:
                        st.warning(finding)
                else:
                    st.success("All checks passed.")
            except Exception as e:
                st.error(f"Checks failed: {e}")

    events = get_monitor_events(limit=200)
    if not events:
        st.info("No monitor events yet. They appear after a run or when you click **Run checks now**.")
    else:
        df = pd.DataFrame([dict(e) for e in events])
        df["created_at"] = df["created_at"].map(ui.fmt_time)
        df = df[["created_at", "level", "category", "ticker", "message"]].rename(columns={
            "created_at": "Time", "level": "Level", "category": "Type",
            "ticker": "Ticker", "message": "Message",
        })
        df["Ticker"] = df["Ticker"].fillna("—")
        st.dataframe(
            df.style.map(ui.label_style, subset=["Level"]),
            hide_index=True, width="stretch",
        )

with tab_history:
    if not runs:
        st.info("No runs yet.")
    else:
        by_id = {r["id"]: r for r in runs}
        st.selectbox(
            "Show a run at the top of the page",
            run_ids,
            format_func=lambda i: f"{ui.fmt_time(by_id[i]['run_at'])} · {by_id[i]['ticker']} · {by_id[i]['question']}",
            key="selected_run_id",
        )
        rows = []
        for r in runs:
            signal = parse_signal(r["analysis"]) or parse_signal(r["trade_signal"])
            rows.append({
                "Time": ui.fmt_time(r["run_at"]), "Ticker": r["ticker"], "Question": r["question"],
                "Experience": (r["experience"] or "").title(),
                "Signal": signal["action"] if signal else "—", "Confidence": ui.fmt_confidence(signal),
                "Threshold": f"{r['threshold']:.2f}" if r["threshold"] is not None else "—",
            })
        st.dataframe(
            pd.DataFrame(rows).style.map(ui.label_style, subset=["Signal"]),
            hide_index=True, width="stretch",
        )

st.caption("Paper trading through Alpaca's sandbox. No real money is involved. This is not financial advice.")
