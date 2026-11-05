# AI Investment Multi-Agent System

**Akinbobola Akinpelu**

ITAI 2376 — Professor McManus

---
Demo: https://drive.google.com/file/d/1VLG0AVz0deRrmIlhUtg4bDtiqcClM9aq/view?usp=drive_link

Changes since the original submission are recorded in the [Development Log](docs/DEVELOPMENT_LOG.md).

## Overview

A multi-agent AI system that combines natural language understanding with quantitative analysis to educate users about the stock market and execute paper trades on their behalf. The system bridges the gap between learning platforms and trading apps by doing both in a single pipeline.

- **Agent 1 — The Advisor**: Accepts a user's investment question, fetches live price data and recent news headlines, performs sentiment analysis, and generates a plain-language recommendation tuned to the user's experience level.
- **Agent 2 — The Trader**: Receives the Advisor's trade signal, checks the current portfolio, and executes a paper trade via the Alpaca Markets API if confidence is sufficient.
- **Agent 3 — The Risk Monitor**: A rule-based agent with no LLM. It blocks any order that breaks a hard risk limit before it reaches Alpaca, and after each run it updates order statuses and flags risky positions.

The two agents communicate through a shared task pipeline managed by CrewAI, mirroring how real financial firms separate research and execution desks.

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

- It is larger than the per-order share limit
- The daily trade limit has been reached
- It sells more shares than are held (no short selling)
- A buy would use more than the allowed share of available cash
- A buy would grow one position past the allowed share of the portfolio

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

## Deep Learning Connections

This project directly applies several deep learning concepts from ITAI 2376:

**Transformers & Self-Attention**
Both LLM agents, the Advisor and the Trader, are powered by GPT-4o, a large language model built on the Transformer architecture. The self-attention mechanism allows the model to weigh relationships across the entire context window, connecting a user's question, live price data, and news headlines simultaneously to generate a coherent, context-aware response. This is the core of why the Advisor can calibrate its recommendation to a beginner vs. an advanced investor using the same underlying data.

**LLM Reasoning Loop (Plan → Act → Observe → Respond)**
The agents follow the ReAct (Reasoning + Acting) pattern, which maps directly to the reasoning loop covered in the course. For each query, the Advisor plans what data it needs, acts by calling the yfinance tools, observes the returned prices and headlines, and then responds with a structured recommendation and trade signal. The Trader repeats the same loop; checking the portfolio, deciding whether confidence is high enough, and acting on or holding the signal. CrewAI's task pipeline enforces this loop explicitly.

**Prompt Engineering as Model Steering**
Agent behavior is defined through carefully structured system prompts in `agents.yaml`. This is applied prompt engineering, using natural language instructions to constrain the model's role, tone, and output format without any weight updates. The Advisor is steered to produce a sentiment summary, a plain-language recommendation, and a structured trade signal in a single response. This reflects how Transformer models are guided through instruction-following rather than fine-tuning for every use case.

**Embeddings & Semantic Understanding**
Internally, GPT-4o converts all inputs: user questions, news headlines, and price summaries, into high-dimensional embeddings before processing. This enables the model to recognize semantic similarity across different phrasings of the same intent, such as treating "Is NVDA worth buying?" and "Should I invest in Nvidia?" as equivalent queries. While embeddings are not explicitly exposed in this project (no ChromaDB or vector store), they are the mechanism behind the model's language understanding at every step.

**Rule-Based Guardrails Around a Probabilistic Model**
The Risk Monitor is the one agent in the system with no neural network. It is a simple reflex agent: it observes the proposed order and the current portfolio, then applies fixed condition-action rules from `risk_limits.yaml`, such as blocking any buy that would grow one position past 10% of the portfolio. This design responds to a core property of LLMs: they generate output by sampling from a probability distribution over tokens, so the same input can produce different answers, and prompt engineering steers the model's behavior without guaranteeing it. A Trader that has been told to buy 5 shares could still request 500. Instead of trusting the model to follow its instructions, the system enforces the limits in code that runs before any order reaches Alpaca, and the same order always gets the same decision. Pairing a flexible learned model with a small set of hard symbolic rules is a common pattern for deploying LLM agents where mistakes have a real cost, and it mirrors how trading firms separate the strategy desk from independent risk controls.

---

## Tech Stack

| Tool | Purpose |
|------|---------|
| CrewAI | Multi-agent orchestration |
| OpenAI GPT-4o | Core LLM for both agents |
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

The Advisor will then fetch live data, analyze it, and pass a trade signal to the Trader. If the signal meets the confidence threshold, the Trader will execute a paper order on Alpaca. A full trade report is saved to `trade_report.md` after each run.

### Web Dashboard

The same pipeline can be run from a browser using the Streamlit dashboard:

```bash
uv run streamlit run src/first_ai_agents/app.py
```

Run it from the project root so Streamlit picks up the theme in `.streamlit/config.toml`. The dashboard is laid out as an agent control room:

- **Account bar**: portfolio value (with the change since the previous snapshot), cash, buying power, and position count. **Sync** loads the latest figures from Alpaca.
- **Question form**: a question, a ticker, and an experience level.
- **Agent pipeline**: one card each for the Advisor, Trader, and Risk Monitor. During a run the cards light up as each agent works; afterwards they show the Advisor's sentiment, signal, and 5-day price trend, the Trader's decision and order status, and the Monitor's checks and warnings.
- **Decision banner**: BUY, SELL, HOLD, BLOCKED, or FAILED, with the order details and the reason. It reflects what was actually recorded (orders, blocks, and failures), not the Trader's own description.
- **Advisor analysis and Trader report**: the full text from each agent, plus the agent logs for runs made in the current session.
- **Tabs**: Positions with color-coded P&L, every Trade, a Portfolio value chart, the Risk Monitor's limits and event log, and a Run History that lets you show any past run in the pipeline.

To preview the dashboard against a different database (for example a demo copy), set `AIMA_DB_PATH` to its path before starting Streamlit.

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
│   │   └── risk_limits.yaml   # Hard limits enforced by the Risk Monitor
│   ├── tools/
│   │   └── custom_tool.py     # yfinance and Alpaca tool definitions
│   ├── app.py                 # Streamlit web dashboard (layout)
│   ├── ui.py                  # Dashboard components and theme CSS
│   ├── broker.py              # Shared Alpaca client and portfolio snapshots
│   ├── crew.py                # Crew assembly and agent/task wiring
│   ├── database.py            # SQLite schema and read/write helpers
│   ├── monitor.py             # Rule-based Risk Monitor
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
