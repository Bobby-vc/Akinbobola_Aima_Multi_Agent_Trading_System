"""Draws the AIMA architecture diagram (architecture_diagram.png).

matplotlib is not a project dependency, so run it with a temporary install:

    uv run --no-project --with matplotlib python docs/draw_architecture.py architecture_diagram.png
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

BG = "#0B0F14"
SURFACE = "#111821"
BORDER = "#223041"
TEXT = "#E6EDF3"
MUTED = "#8B98A5"
ADVISOR = "#58A6FF"
TRADER = "#3DD6C6"
MONITOR = "#A371F7"
DATA = "#D29922"
GREEN = "#3FB950"

fig, ax = plt.subplots(figsize=(16, 11), dpi=150)
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 100)
ax.set_ylim(0, 70)
ax.axis("off")


def box(x, y, w, h, color, title, lines=(), kind=None, title_size=13, fill=SURFACE, top_bar=True):
    """A rounded card centered on (x, y) with a colored top edge, like the dashboard cards."""
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0,rounding_size=1.2",
                                facecolor=fill, edgecolor=BORDER, linewidth=1.4, zorder=2))
    if top_bar:
        ax.add_patch(FancyBboxPatch((x - w / 2, y + h / 2 - 0.55), w, 0.55,
                                    boxstyle="round,pad=0,rounding_size=0.25",
                                    facecolor=color, edgecolor="none", zorder=3))
    top = y + h / 2 - 1.9
    if kind:
        ax.text(x - w / 2 + 1.4, top, kind, color=color, fontsize=8.5, fontweight="bold",
                ha="left", va="center", zorder=4)
        top -= 1.9
    ax.text(x - w / 2 + 1.4, top, title, color=TEXT, fontsize=title_size, fontweight="bold",
            ha="left", va="center", zorder=4)
    for i, line in enumerate(lines):
        ax.text(x - w / 2 + 1.4, top - 2.0 - i * 1.65, line, color=MUTED, fontsize=9.5,
                ha="left", va="center", zorder=4)


def arrow(start, end, color=MUTED, label=None, label_at=None, dashed=False, rad=0.0, ha="center"):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=16, linewidth=1.8,
                                 color=color, linestyle=(0, (5, 4)) if dashed else "solid",
                                 connectionstyle=f"arc3,rad={rad}", zorder=1, shrinkA=0, shrinkB=0))
    if label:
        lx, ly = label_at or ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        ax.text(lx, ly, label, color=color, fontsize=9, ha=ha, va="center", style="italic", zorder=5,
                bbox=dict(facecolor=BG, edgecolor="none", pad=1.5))


# Title
ax.text(50, 67.6, "AIMA — Multi-Agent Trading System", color=TEXT, fontsize=19, fontweight="bold", ha="center")
ax.text(50, 65.4, "Research, execution, and risk kept on separate desks, as at a trading firm",
        color=MUTED, fontsize=11, ha="center")

# Inputs
box(30, 58.6, 36, 7.4, MUTED, "Streamlit dashboard", ["Question · ticker · experience level · confidence threshold"],
    kind="RUN ON DEMAND", title_size=11.5)
box(70, 58.6, 36, 7.4, MUTED, "Daily watchlist  (run_watchlist)", ["Each ticker once per trading day; holidays skipped"],
    kind="RUN ON SCHEDULE", title_size=11.5)
arrow((30, 54.9), (42, 51.5))
arrow((70, 54.9), (58, 51.5))

# Orchestrator
box(50, 49.5, 64, 4.0, MUTED, "CrewAI orchestrator  ·  runs the desks in order and saves every run",
    title_size=11, top_bar=False)

# Desks
box(16, 35, 28, 16, ADVISOR, "Advisor", [
    "LLM agent · equity research analyst",
    "Weighs valuation, price momentum,",
    "and news sentiment",
    "Ends every analysis with:",
    "SENTIMENT: BULLISH",
    "TRADE SIGNAL: BUY NVDA | 0.78",
], kind="RESEARCH DESK")
box(50, 35, 28, 16, TRADER, "Trader", [
    "LLM agent · execution trader",
    "Checks the portfolio, then trades",
    "only if confidence ≥ threshold",
    "Reports EXECUTE, HOLD, or BLOCKED",
    "Makes no forecasts of its own",
], kind="EXECUTION DESK")
box(84, 35, 28, 16, MONITOR, "Risk Monitor", [
    "Rule-based · no LLM · cannot be overruled",
    "Blocks orders below the threshold, or that",
    "differ from the Advisor's signal, exceed size,",
    "daily, cash, or 10% position limits, or sell short",
    "After each run: reconciles fills with Alpaca",
    "and flags losing or oversized positions",
], kind="RISK DESK")

arrow((40, 47.5), (17, 43.0), label="task 1", label_at=(27.5, 45.9))
arrow((50, 47.5), (50, 43.0), label="task 2", label_at=(51.2, 45.25), ha="left")
arrow((60, 47.5), (83, 43.0), dashed=True, label="after each run", label_at=(72.5, 45.9))
arrow((30, 35), (36, 35), color=ADVISOR, label="signal +\nconfidence", label_at=(33, 38.2))
arrow((64, 35), (70, 35), color=TRADER, label="every order\nchecked", label_at=(67, 38.2))

# Data, records, and broker
box(16, 16, 28, 10.6, DATA, "Market data & news", [
    "Yahoo Finance: price, 52-week range, P/E",
    "Alpaca news feed: stock-tagged headlines",
    "Daily closes for scoring against SPY",
], kind="INPUTS", title_size=11.5)
box(50, 16, 28, 10.6, GREEN, "SQLite  ·  trading.db", [
    "Runs and their signals",
    "Orders, fills, portfolio snapshots",
    "Risk Monitor events · price cache",
], kind="RECORDS", title_size=11.5)
box(84, 16, 28, 10.6, MONITOR, "Alpaca paper trading", [
    "Orders, fills, account, positions",
    "Market calendar",
    "Simulated money only",
], kind="BROKER", title_size=11.5)

arrow((16, 21.3), (16, 27.0), color=DATA, label="tools", label_at=(17.2, 24.15), ha="left")
arrow((50, 27.0), (50, 21.3), color=GREEN, label="results saved", label_at=(51.2, 24.15), ha="left")
arrow((57, 27.0), (75, 21.3), color=TRADER, label="portfolio check", label_at=(66.5, 24.9))
arrow((84, 27.0), (84, 21.3), color=MONITOR, label="approved orders only", label_at=(85.2, 24.15), ha="left")

# Dashboard views
box(50, 4.8, 92, 6.2, MUTED,
    "Agent pipeline  ·  decision banner  ·  Performance: hit rate, calibration, vs S&P 500  ·  positions  ·  trades  ·  risk events",
    kind="DASHBOARD VIEWS", title_size=10.5, top_bar=False)
arrow((50, 10.7), (50, 7.9), color=GREEN)
arrow((16, 10.7), (22, 7.9), color=DATA)

ax.text(99, 0.2, "Stack: CrewAI · OpenAI GPT-4o · yfinance · Alpaca · Streamlit · SQLite · Python",
        color=MUTED, fontsize=8.5, ha="right", va="bottom")

fig.savefig(sys.argv[1], facecolor=BG, bbox_inches="tight", pad_inches=0.3)
print("saved", sys.argv[1])
