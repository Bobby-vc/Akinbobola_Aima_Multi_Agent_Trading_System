import streamlit as st
import sys
import os
import json
import contextlib
from io import StringIO
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Trading Advisor",
    page_icon="📈",
    layout="wide",
)

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    .report-box {
        background: #0e1117;
        border: 1px solid #21262d;
        border-radius: 10px;
        padding: 1.5rem;
        margin-top: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────────────────────
st.title("📈 AI Trading Advisor")
st.caption("Multi-Agent Investment Analysis System — powered by CrewAI & GPT-4o")
st.divider()

# ── Sidebar — Portfolio ────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📊 Portfolio")
    if st.button("🔄 Refresh Portfolio", use_container_width=True):
        with st.spinner("Fetching portfolio..."):
            try:
                from first_ai_agents.broker import get_alpaca_api, record_portfolio_snapshot
                account, positions = record_portfolio_snapshot(get_alpaca_api())

                st.metric("💵 Cash", f"${float(account.cash):,.2f}")
                st.metric("📦 Portfolio Value", f"${float(account.portfolio_value):,.2f}")
                st.metric("⚡ Buying Power", f"${float(account.buying_power):,.2f}")

                st.subheader("Open Positions")
                if positions:
                    for p in positions:
                        pnl = float(p.unrealized_pl)
                        color = "🟢" if pnl >= 0 else "🔴"
                        st.markdown(
                            f"{color} **{p.symbol}** — {p.qty} shares  \n"
                            f"Avg: ${float(p.avg_entry_price):.2f} | "
                            f"Now: ${float(p.current_price):.2f} | "
                            f"P&L: ${pnl:.2f}"
                        )
                else:
                    st.info("No open positions.")
            except Exception as e:
                st.error(f"Could not load portfolio: {e}")

    st.divider()
    st.caption("All trades use Alpaca paper trading — no real money.")

# ── Main — Input Form ──────────────────────────────────────────────────────────
col1, col2 = st.columns([3, 1])
with col1:
    question = st.text_input(
        "💬 Investment Question",
        placeholder="Is NVDA a good buy right now?",
    )
with col2:
    ticker = st.text_input("📌 Ticker", placeholder="NVDA").upper().strip()

experience = st.radio(
    "🎓 Experience Level",
    ["beginner", "intermediate", "advanced"],
    horizontal=True,
)

run_btn = st.button("🚀 Run Analysis", type="primary", use_container_width=True)

# ── Run the Crew ───────────────────────────────────────────────────────────────
if run_btn:
    if not question:
        st.warning("Please enter an investment question.")
    elif not ticker:
        st.warning("Please enter a stock ticker.")
    else:
        log_output = StringIO()
        status = st.status("🤖 Agents are working...", expanded=True)

        try:
            # Add src to path so the package resolves correctly
            src_path = os.path.join(os.path.dirname(__file__), "src")
            if src_path not in sys.path:
                sys.path.insert(0, src_path)

            from first_ai_agents.crew import FirstAiAgents

            inputs = {
                "question": question,
                "ticker": ticker,
                "experience_level": experience,
                "confidence_threshold": 0.7,
            }

            with status:
                st.write("**Stock Analyst** — fetching live data & news...")
                with contextlib.redirect_stdout(log_output):
                    FirstAiAgents().crew().kickoff(inputs=inputs)
                st.write("**Trading Advisor** — evaluating signal & executing...")

            status.update(label="✅ Analysis complete!", state="complete", expanded=False)

            # ── Trade Report ───────────────────────────────────────────────────
            report_path = os.path.join(os.path.dirname(__file__), "trade_report.md")
            if os.path.exists(report_path):
                with open(report_path, "r") as f:
                    report = f.read()
                st.markdown("## 📋 Trade Report")
                st.markdown(f'<div class="report-box">{report}</div>', unsafe_allow_html=True)
            else:
                st.info("No trade report generated.")

            # ── Agent Logs (collapsible) ───────────────────────────────────────
            logs = log_output.getvalue()
            if logs:
                with st.expander("🔍 View Agent Logs"):
                    st.code(logs, language=None)

        except Exception as e:
            status.update(label="❌ Error", state="error", expanded=True)
            st.error(f"Something went wrong: {e}")
            logs = log_output.getvalue()
            if logs:
                with st.expander("Logs"):
                    st.code(logs, language=None)

# ── History Tabs ───────────────────────────────────────────────────────────────
st.divider()
src_path = os.path.join(os.path.dirname(__file__), "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from first_ai_agents.database import get_trades, get_portfolio_snapshots, get_monitor_events
from first_ai_agents.monitor import load_limits

tab_trades, tab_portfolio, tab_monitor = st.tabs(
    ["📋 Trade History", "📊 Portfolio Snapshots", "🛡️ Risk Monitor"]
)

with tab_trades:
    trades = get_trades(limit=200)
    if not trades:
        st.info("No trades recorded yet. Run an analysis to generate trades.")
    else:
        df = pd.DataFrame([dict(t) for t in trades])
        df["traded_at"] = pd.to_datetime(df["traded_at"])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Trades", len(df))
        c2.metric("Buys", int((df["side"] == "buy").sum()))
        c3.metric("Sells", int((df["side"] == "sell").sum()))
        c4.metric("Blocked", int((df["status"] == "blocked").sum()))

        st.dataframe(
            df[["traded_at", "ticker", "side", "qty", "status", "filled_avg_price", "order_id"]].rename(columns={
                "traded_at": "Time", "ticker": "Ticker", "side": "Side", "qty": "Qty",
                "status": "Status", "filled_avg_price": "Fill Price", "order_id": "Order ID",
            }),
            use_container_width=True,
        )

with tab_portfolio:
    snapshots = get_portfolio_snapshots(limit=200)
    if not snapshots:
        st.info("No portfolio snapshots yet. Click 'Refresh Portfolio' in the sidebar.")
    else:
        latest = snapshots[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Portfolio Value", f"${float(latest['portfolio_value']):,.2f}")
        c2.metric("Cash", f"${float(latest['cash']):,.2f}")
        c3.metric("Buying Power", f"${float(latest['buying_power']):,.2f}")

        df = pd.DataFrame([dict(s) for s in snapshots])
        df["snapped_at"] = pd.to_datetime(df["snapped_at"])
        df = df.sort_values("snapped_at")

        st.subheader("Portfolio Value Over Time")
        st.line_chart(df.set_index("snapped_at")[["portfolio_value", "cash"]])

        positions = json.loads(latest["positions_json"])
        if positions:
            st.subheader("Open Positions (latest snapshot)")
            st.dataframe(pd.DataFrame(positions), use_container_width=True)

with tab_monitor:
    st.caption(
        "The risk monitor is rule-based and uses no LLM. It blocks orders that break the "
        "limits below, and after each run it updates order statuses and flags risky positions."
    )

    if st.button("🛡️ Run checks now"):
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

    limits = load_limits()
    st.subheader("Active Limits")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Max Shares / Order", limits["max_qty_per_order"])
    c2.metric("Max Trades / Day", limits["max_trades_per_day"])
    c3.metric("Max Buy (of Cash)", f"{limits['max_order_pct_of_cash']:.0%}")
    c4.metric("Max Position Size", f"{limits['max_position_pct_of_portfolio']:.0%}")
    c5.metric("Loss Alert", f"{limits['position_loss_alert_pct']:.0%}")
    st.caption("Edit `src/first_ai_agents/config/risk_limits.yaml` to change these.")

    st.subheader("Monitor Events")
    events = get_monitor_events(limit=200)
    if not events:
        st.info("No monitor events yet. They appear after a run or when you click 'Run checks now'.")
    else:
        df = pd.DataFrame([dict(e) for e in events])
        df["created_at"] = pd.to_datetime(df["created_at"])
        st.dataframe(
            df[["created_at", "level", "category", "ticker", "message"]].rename(columns={
                "created_at": "Time", "level": "Level", "category": "Type",
                "ticker": "Ticker", "message": "Message",
            }),
            use_container_width=True,
        )