# AI Investment Multi-Agent System (AIMA)

**Akinbobola Akinpelu** & **Aima Ayaz**

ITAI 3378 — Finance in AI


---
Demo: https://drive.google.com/file/d/1VLG0AVz0deRrmIlhUtg4bDtiqcClM9aq/view?usp=drive_link


## Overview

A multi-agent AI system that combines natural language understanding with quantitative analysis to educate users about the stock market and execute paper trades on their behalf. The system bridges the gap between learning platforms and trading apps by doing both in a single pipeline.

- **Agent 1 — The Advisor**: Accepts a user's investment question, fetches live price data and recent news headlines, performs sentiment analysis, and generates a plain-language recommendation tuned to the user's experience level.
- **Agent 2 — The Trader**: Receives the Advisor's trade signal, checks the current portfolio, and executes a paper trade via the Alpaca Markets API if confidence is sufficient.
- **Agent 3 — The Risk Monitor**: A rule-based agent with no LLM. It blocks any order that breaks a hard risk limit before it reaches Alpaca, and after each run it updates order statuses and flags risky positions.

The agents work as a pipeline managed by CrewAI, mirroring how trading firms separate research, execution, and risk (see [Finance Concepts](#finance-concepts)).

---

## Architecture

```
User Input (question, ticker, experience level)
        |
        v
Agent 1: Advisor (GPT-4o)
  - Tools: Get Stock Price Data, Get Stock News (yfinance)
  - Outputs: Sentiment summary, recommendation, TRADE SIGNAL
        |
        v
Agent 2: Trader (GPT-4o)
  - Tools: Check Portfolio, Execute Paper Trade (Alpaca API)
  - Outputs: Order confirmation, HOLD justification, or BLOCKED reason
        |        ^
        |        |  every order is checked first
        |   Agent 3: Risk Monitor (rule-based, no LLM)
        |     - Blocks orders that break the limits in risk_limits.yaml
        v
trade_report.md (saved to project root)
        |
        v
Risk Monitor post-run checks
  - Updates order statuses and fill prices from Alpaca
  - Saves a portfolio snapshot and flags losing or oversized positions
```

### Risk Monitor

The Risk Monitor applies fixed rules instead of model reasoning, so the Trader cannot talk its way past them. Before any order is submitted, it blocks the order if:

- The Advisor's confidence is below the run's confidence threshold
- It does not match the Advisor's signal (the signal was HOLD, or the side or ticker differs)
- It is larger than the per-order share limit
- The daily trade limit has been reached
- It sells more shares than are held (no short selling)
- A buy would use more than the allowed share of available cash
- A buy would grow one position past the allowed share of the portfolio

The confidence check uses the Advisor's own output, not the Trader's reading of it. When the Advisor's task finishes, its `TRADE SIGNAL` line is parsed and stored for the run, and every order the Trader places is compared against it. The Advisor rates its confidence from 0.00 to 1.00 using a rubric in `tasks.yaml` and is never shown the threshold. The threshold defaults to 0.70 and can be set per run.

Blocked orders are returned to the Trader with the reason, recorded with status `blocked`, and logged as monitor events. After each run, the monitor checks every unsettled order with Alpaca, records whether it filled (and at what price), was canceled, or was rejected, and flags any position that has lost more than the alert threshold or grown too large.

The limits live in `src/first_ai_agents/config/risk_limits.yaml`:

| Limit | Default |
|-------|---------|
| `max_qty_per_order` | 100 shares |
| `max_trades_per_day` | 5 |
| `max_order_pct_of_cash` | 25% |
| `max_position_pct_of_portfolio` | 10% |
| `position_loss_alert_pct` | 10% |

---

## Finance Concepts

The project applies several ideas from ITAI 3378 Finance in AI and from how trading firms are organized.

**Separating research, execution, and risk**
Trading firms keep the people who generate trade ideas apart from the people who execute them, and both apart from an independent risk function, so no single desk can act on its own view unchecked. AIMA follows the same structure: the Advisor is the research desk, the Trader is the execution desk, and the Risk Monitor is the risk desk. The Risk Monitor applies fixed rules rather than judgment, so neither LLM agent can talk its way past it.

**Pre-trade risk controls**
In the US, broker-dealers that send orders to the market must check them against risk limits first (the SEC's Market Access Rule, Rule 15c3-5). The Risk Monitor applies the same kinds of checks before any order reaches Alpaca: a maximum order size, a daily order limit, a cap on how much cash one buy can use, a concentration limit that keeps any one stock under 10% of the portfolio, and no short selling. It also blocks any order that does not match the research signal behind it.

**Signals from valuation, momentum, and sentiment**
The Advisor combines three classic inputs: valuation (the P/E ratio), price momentum (recent closes and where the price sits in its 52-week range), and news sentiment. Reading sentiment from news is one of the main uses of AI in finance, because news can change how investors value a company well before it shows up in reported results.

**Confidence thresholds and calibration**
Every signal carries a confidence score from 0 to 1, and only signals at or above the threshold are traded. Raising the threshold means fewer trades that should be more reliable; lowering it means more trades and more noise. That trade-off only works if the scores are calibrated, meaning signals rated 0.8 are right about 80% of the time. The Performance tab measures this directly, and compares the hit rate of signals the threshold let through with the ones it held back.

**Measuring performance honestly**
Signals are scored the way a fund would evaluate a strategy:
- **No look-ahead bias:** each signal is priced at the first market close after it was made, never at an earlier price.
- **Adjusted prices:** split- and dividend-adjusted closes, so corporate actions do not distort returns.
- **Benchmark-relative returns:** every result is compared with the S&P 500 (SPY) over the same days, since gaining 2% while the market gains 3% is not skill.
- **Statistical uncertainty:** hit rates come with 95% confidence intervals. With only 10 signals, a 60% hit rate is still consistent with a coin flip, so the dashboard warns until at least 20 signals have been scored.

**Order lifecycle and reconciliation**
A market order is accepted by the broker, then filled, canceled, or rejected. After each run, the Risk Monitor reconciles the local records with Alpaca, recording each order's final status and fill price, the way a back office matches internal records against the broker's.

**Known limitations**
- Results use closing prices and ignore transaction costs and slippage.
- Every order is a fixed 5 shares; position size does not scale with confidence or volatility.
- The watchlist is a small, hand-picked set of large technology stocks, so results may not generalize to other stocks or market conditions.
- LLM output varies between runs, so the same question can produce a different signal.
- Market data comes from Yahoo Finance through yfinance, which is suitable for education but not licensed for commercial use.

---

## Tech Stack

| Tool | Purpose |
|------|---------|
| CrewAI | Multi-agent orchestration |
| OpenAI GPT-4o | LLM for the Advisor and Trader |
| yfinance | Live stock price data and news headlines |
| Alpaca Markets API | Paper trade execution (simulated, no real money) |
| Streamlit | Web dashboard for running analyses and viewing history |
| SQLite | Local storage for crew runs, trades, and portfolio snapshots |
| Python-dotenv | Secure API key management |

---

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key
- Alpaca Markets paper trading account (free at [alpaca.markets](https://alpaca.markets))

---

## Installation

**1. Clone the repository**
```bash
git clone https://github.com/Bobby-vc/Akinbobola_Aima_Multi_Agent_Trading_System.git
cd Akinbobola_Aima_Multi_Agent_Trading_System
```

**2. Install dependencies**
```bash
uv sync
```

**3. Set up environment variables**

Create a `.env` file in the project root with the following keys:
```
OPENAI_API_KEY=your_openai_key_here
APCA_API_KEY_ID=your_alpaca_key_here
APCA_API_SECRET_KEY=your_alpaca_secret_here
APCA_API_BASE_URL=https://paper-api.alpaca.markets
```

Your Alpaca API keys can be found in your Alpaca dashboard under API Keys. Use the paper trading keys, not live trading.

---

## Running the System

```bash
crewai run
```

The system will prompt you for:
- Your investment question (e.g. "Is NVDA a good buy right now?")
- The stock ticker (e.g. NVDA)
- Your experience level (beginner / intermediate / advanced)
- A confidence threshold from 0 to 1 (press Enter for 0.7)

The Advisor will then fetch live data, analyze it, and pass a trade signal to the Trader. If the signal's confidence meets the threshold, the Trader will execute a paper order on Alpaca; the Risk Monitor blocks the order otherwise. A full trade report is saved to `trade_report.md` after each run.

### Web Dashboard

The same pipeline can be run from a browser using the Streamlit dashboard:

```bash
uv run streamlit run src/first_ai_agents/app.py
```

Run it from the project root so Streamlit picks up the theme in `.streamlit/config.toml`. The dashboard is laid out as an agent control room:

- **Account bar**: portfolio value (with the change since the previous snapshot), cash, buying power, and position count. **Sync** loads the latest figures from Alpaca.
- **Question form**: a question, a ticker, an experience level, and a confidence threshold slider.
- **Agent pipeline**: one card each for the Advisor, Trader, and Risk Monitor. During a run the cards light up as each agent works; afterwards they show the Advisor's sentiment, signal, and 5-day price trend, the Trader's decision and order status, and the Monitor's checks and warnings.
- **Decision banner**: BUY, SELL, HOLD, BLOCKED, or FAILED, with the order details and the reason. It reflects what was actually recorded (orders, blocks, and failures), not the Trader's own description.
- **Advisor analysis and Trader report**: the full text from each agent, plus the agent logs for runs made in the current session.
- **Tabs**: Performance (how past signals turned out; see below), Positions with color-coded P&L, every Trade, a Portfolio value chart, the Risk Monitor's limits and event log, and a Run History that lets you show any past run in the pipeline.

To preview the dashboard against a different database (for example a demo copy), set `AIMA_DB_PATH` to its path before starting Streamlit.

### Signal Performance

The Performance tab scores every past signal against what the market actually did, using daily prices from Yahoo Finance:

- **Entry:** the close of the first trading session after the signal (before 4 p.m. ET: that day's close; after the close or on a weekend: the next session's). No price from before the signal is used.
- **Holding periods:** 1, 5, and 20 trading days after entry, from split- and dividend-adjusted closes.
- **Hit:** a BUY whose stock rose, or a SELL whose stock fell. HOLD signals are listed but not scored.
- **Benchmark:** SPY over the same days. "Vs S&P" is the signal's return minus the market's, in the signal's direction.
- **Uncertainty:** hit rates come with a 95% Wilson confidence interval, and the tab warns when fewer than 20 signals have been scored.

It also shows a calibration chart (do 0.8-confidence signals hit more often than 0.6 ones?) and compares the hit rate of signals that cleared the confidence threshold with those it filtered out.

### Daily Watchlist Runs

To build a track record for the Performance tab, run the agents over a watchlist once per trading day:

```bash
uv run run_watchlist
```

The tickers, experience level, confidence threshold, and question are set in `src/first_ai_agents/config/watchlist.yaml`. Each ticker runs in turn, exactly as from the dashboard, so every run is saved, checked by the Risk Monitor, and later scored. Days the market is closed are skipped (using Alpaca's calendar, so holidays count), as are tickers that already ran today. The console shows one line per ticker; the agents' full output goes to `logs/watchlist-<date>.log`.

- `uv run run_watchlist --tickers NVDA AMD` runs only those tickers
- `uv run run_watchlist --force` runs even when the market is closed

Each run uses OpenAI credit, and signals that clear the threshold place paper orders.

### Running the Tests

The test suite runs against a temporary database and stand-ins for OpenAI and Alpaca, so it never places orders or touches `trading.db`:

```bash
uv run pytest
```

---

## Database

Run history is stored in a local SQLite file, `trading.db`, in the project root. It is created automatically the first time `src/first_ai_agents/database.py` is imported, and is excluded from the repository.

| Table | Contents |
|-------|----------|
| `crew_runs` | Each run's question, ticker, experience level, Advisor analysis, and trade signal |
| `trade_history` | Each paper trade: ticker, quantity, side, Alpaca order ID, status, and fill price (blocked orders included) |
| `portfolio_snapshots` | Cash, portfolio value, buying power, and open positions at a point in time |
| `stock_cache` | Recent yfinance price data per ticker (treated as stale after 15 minutes) |
| `monitor_events` | Every Risk Monitor block, order status change, position alert, and completed check |

To browse the data directly, open `trading.db` with [DB Browser for SQLite](https://sqlitebrowser.org) or the `sqlite3` command-line tool.

---

## Project Structure

```
first_ai_agents/
├── src/first_ai_agents/
│   ├── config/
│   │   ├── agents.yaml        # Agent roles, goals, and backstories
│   │   ├── tasks.yaml         # Task descriptions and agent assignments
│   │   ├── risk_limits.yaml   # Hard limits enforced by the Risk Monitor
│   │   └── watchlist.yaml     # Tickers and settings for daily runs
│   ├── tools/
│   │   └── custom_tool.py     # yfinance and Alpaca tool definitions
│   ├── app.py                 # Streamlit web dashboard (layout)
│   ├── ui.py                  # Dashboard components and theme CSS
│   ├── broker.py              # Shared Alpaca client and portfolio snapshots
│   ├── crew.py                # Crew assembly and agent/task wiring
│   ├── database.py            # SQLite schema and read/write helpers
│   ├── monitor.py             # Rule-based Risk Monitor
│   ├── watchlist.py           # Daily runs over the watchlist (run_watchlist)
│   ├── performance.py         # Scores past signals against market prices
│   ├── signals.py             # Reads the Advisor's TRADE SIGNAL and SENTIMENT lines
│   └── main.py                # Entry point with user input prompts
├── .streamlit/config.toml     # Dashboard theme (colors and fonts)
├── docs/DEVELOPMENT_LOG.md    # History of changes since the submission
├── tests/                     # pytest suite (no real API calls)
├── trade_report.md            # Auto-generated after each run
├── trading.db                 # SQLite database (created on first use, not committed)
├── pyproject.toml
└── .env                       # API keys (not committed to repo)
```

---

## Disclaimer

This system is built for educational purposes only as part of a course project. All trading is simulated using Alpaca's paper trading sandbox. No real money is involved. This is not licensed financial advice.
