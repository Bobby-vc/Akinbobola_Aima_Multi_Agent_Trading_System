# Development Log

A record of how the AI Investment Multi-Agent System (AIMA) has changed since the original course submission: what was built, why, and where it lives. For setup and usage, see the [README](../README.md).

## Summary

| Date | Change | Commit |
|------|--------|--------|
| May 2026 | Original two-agent system submitted for ITAI 2376 | `531561b` to `5b8b528` |
| Jun 13, 2026 | SQLite database and Streamlit dashboard | `7b70dbe` |
| Oct 26, 2026 | README restored after a merge mistake | `13298c0` |
| Oct 26, 2026 | Dashboard and database documented; `.gitignore` repaired | `b4d7e7b` |
| Oct 26, 2026 | Agents write to the database | `92fe723` |
| Nov 4, 2026 | GitHub repository renamed | (no commit) |
| Nov 4, 2026 | Rule-based Risk Monitor added as a third agent | `1642959` |
| Nov 4, 2026 | Dashboard redesigned as an agent control room | `50b9740` |
| Nov 4, 2026 | Risk Monitor added to Deep Learning Connections | `80595b3` |
| Nov 4, 2026 | Development log added | `8bb96c9` |
| Nov 4, 2026 | Test suite added; leftover files removed | `db9559a` |
| Nov 4, 2026 | Deprecated `datetime.utcnow()` replaced | `24acc9b` |
| Nov 4, 2026 | Confidence threshold enforced | (this change) |

---

## Starting point (May 2026)

The original submission was a two-agent CrewAI system:

- **Advisor** (GPT-4o): fetches live prices and news headlines with yfinance and produces a recommendation and a `TRADE SIGNAL` line.
- **Trader** (GPT-4o): checks the Alpaca paper portfolio and places a paper order when the signal's confidence is high enough.

It ran from the terminal and wrote its result to `trade_report.md`. The repository also had the README, an architecture diagram, a demo video link, and `REFLECTION.md`. The reflection named two things for future work: a UI, and ChromaDB for retrieval-augmented generation. The UI has since been built (below); ChromaDB has not.

---

## 1. Database and first dashboard (June 13, 2026)

**Why:** Each run's analysis and trades were lost once the terminal closed, and there was no way to view results outside the terminal.

**What changed:**
- `src/first_ai_agents/database.py`: a SQLite database (`trading.db`) with four tables: `crew_runs`, `trade_history`, `portfolio_snapshots`, and `stock_cache`.
- `src/first_ai_agents/app.py`: a Streamlit dashboard with a run form, a live Alpaca portfolio sidebar, the trade report, and Trade History and Portfolio Snapshots tabs.
- `streamlit` added to `pyproject.toml`; a pinned `requirements.txt` was proposed.

**Note:** An earlier version of this dashboard also existed as a root-level `app.py`. It was removed in step 9.

---

## 2. README restored after a merge mistake (October 26, 2026)

**What happened:** Pushing the June commit required rebasing onto changes already on GitHub. Two files conflicted, and the conflict in `README.md` was resolved toward the wrong side. During a rebase, Git's "ours" and "theirs" labels are reversed, so the project README (author, course, demo link, architecture) was replaced with CrewAI's template README.

**Fix:** The README was restored exactly from the commit before the mistake (`ef3aa2d`). By the same reversal, `requirements.txt` kept the shorter five-package list already on GitHub rather than the pinned one.

---

## 3. Documentation and `.gitignore` cleanup (October 26, 2026)

- **README:** added Streamlit and SQLite to the tech stack, a Web Dashboard section, a Database section describing each table, and the new files in the project structure.
- **`.gitignore`:** removed conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) left over from an earlier merge, kept the rules from both sides, and added `trading.db` so the local database is never committed.

---

## 4. Agents write to the database (October 26, 2026)

**Why:** The tables existed, but no code wrote to them, so the dashboard's Trade History and Portfolio Snapshots tabs were always empty.

**What changed:**
- `crew.py`: captures each run's inputs and saves the finished run to `crew_runs`.
- `tools/custom_tool.py`: saves every paper trade and every portfolio check, and caches yfinance price data for 15 minutes.
- `app.py`: the sidebar's refresh button also saves a portfolio snapshot.

---

## 5. Repository renamed (November 4, 2026)

The GitHub repository was renamed from `Akinbobola_Akinpelu_Solo_ITAI2376` to `Akinbobola_Aima_Multi_Agent_Trading_System`. The local `origin` remote was updated to the new URL, and the README's clone instructions were updated in the next commit (they previously said `YOUR_USERNAME/YOUR_REPO_NAME`).

---

## 6. Risk Monitor, a third agent (November 4, 2026)

**Why:** Two gaps in the trading path.
1. The Trader LLM chose order sizes and `execute_paper_trade` submitted them with no hard limits.
2. An order's status was saved when it was submitted (usually `accepted`) and never updated, so the database never showed whether it filled.

**Design decision:** The monitor uses no LLM. CrewAI agents always run on a language model, so the monitor is plain Python called from the trading tool and from the crew's finish hook. Fixed rules give the same answer every time, cost nothing to run, and cannot be talked around by the model they are checking.

**What changed:**
- `monitor.py`:
  - **Before an order:** blocks it if it exceeds the per-order share limit or the daily trade limit, sells more shares than are held, uses too much of available cash, or would grow one position past its share of the portfolio.
  - **After a run:** looks up every unsettled order with Alpaca and records its status and fill price, saves a portfolio snapshot, and flags positions that are down past the alert threshold or oversized.
- `config/risk_limits.yaml`: the limits in one editable file. Defaults are 100 shares per order, 5 trades per day, 25% of cash per buy, 10% of the portfolio per position, and a 10% loss alert.
- `broker.py`: one shared Alpaca client and portfolio-snapshot function, replacing three copies of the same code.
- `database.py`: a `monitor_events` table; `filled_avg_price` and `updated_at` columns on `trade_history`. Existing databases get the new columns automatically on startup.
- `tools/custom_tool.py` and `config/tasks.yaml`: every order is checked first. A blocked order is recorded with status `blocked`, and the Trader is told to report it as BLOCKED instead of retrying.
- `app.py`: a Risk Monitor tab, plus a blocked count and fill prices in Trade History.

---

## 7. Dashboard redesign (November 4, 2026)

**Why:** The dashboard used Streamlit's default look, used emojis as icons, and showed the result as one block of text. Nothing on screen showed three agents working together. Results also vanished on the next click, because they were only drawn while the run was in progress.

**Direction chosen:** an "agent control room": a dark theme with the three-agent pipeline as the centerpiece. This was chosen over a dense trading-terminal style and a light consumer-finance style because it shows off the multi-agent design.

**What changed:**
- `.streamlit/config.toml`: dark theme with the Inter and JetBrains Mono fonts. Each agent has its own color: blue for the Advisor, teal for the Trader, purple for the Monitor.
- `ui.py` (new): the custom components. It also turns stored runs into the values shown on the cards, and escapes all agent and user text before it is placed in HTML.
- `app.py` (rewritten):
  - **Account bar:** portfolio value with its change since the previous snapshot, cash, buying power, positions, and a **Sync** button.
  - **Pipeline cards:** update live as each agent finishes (using CrewAI's `task_callback`), then show each agent's result.
  - **Decision banner:** BUY, SELL, HOLD, BLOCKED, or FAILED. It is built from recorded orders and monitor events, not from the Trader's own description of what it did.
  - **Tabs:** Positions, Trades, Portfolio (chart), Risk Monitor, and Run History. Any past run can be shown in the pipeline.
- Supporting changes:
  - `crew_runs.started_at` links each run to the trades and monitor events recorded during it.
  - The crew's two finish hooks were merged into one, so the monitor always finishes before the run is saved.
  - Orders that fail to submit are recorded with status `failed`.
  - The Advisor now ends with a `SENTIMENT:` line for its card.
  - `AIMA_DB_PATH` lets the dashboard run against a different database, such as a demo copy.

---

## 8. Deep Learning Connections (November 4, 2026)

Added a "Rule-Based Guardrails Around a Probabilistic Model" subsection to the README. It explains the Risk Monitor as a simple reflex agent, and why hard limits are enforced in code around an LLM whose output is sampled and not guaranteed to follow its prompt. The Transformers subsection now says that GPT-4o powers the two LLM agents, not all three.

---

## 9. Test suite and cleanup (November 4, 2026)

**Why:** The checks run during development lived only in temporary scripts, so later changes could not be checked the same way.

**What changed:**
- `tests/`: a pytest suite (47 tests) covering the database, the Risk Monitor, the crew's hooks, the dashboard components, and the dashboard itself through Streamlit's test runner. `tests/conftest.py` points the app at a temporary database before anything is imported and replaces Alpaca with a fake account, so the suite never places orders or touches `trading.db`.
- `pyproject.toml`: pytest added as a development dependency. Run the suite with `uv run pytest`.
- Removed the root-level `app.py` (the old dashboard) and `src/first_ai_agents/.env.example`, an exact copy of the `.env.example` in the project root.

---

## 10. Deprecated `datetime.utcnow()` replaced (November 4, 2026)

**Why:** `datetime.utcnow()` is deprecated in recent Python versions, and the test suite printed about 50 warnings about it.

**What changed:** `database.py` has a `utc_now()` helper that `crew.py`, `app.py`, and the tests now use instead. It does not simply switch to `datetime.now(timezone.utc)`, because that adds a `+00:00` suffix that existing rows in `trading.db` do not have. Mixing the two formats would break the text comparisons that match trades to runs, and cache-age arithmetic would fail when subtracting an old timestamp from a new one. `utc_now()` takes the current UTC time and drops the timezone, so new timestamps match the stored format. A new test checks this.

---

## 11. Confidence threshold enforced (November 4, 2026)

**Why:** Every run passed `confidence_threshold: 0.7`, but nothing used it. The Advisor rated confidence as HIGH, MEDIUM, or LOW, and the Trader's prompt said to trade on HIGH or MEDIUM, so there was no number to compare with the threshold. Even a correct prompt would only be a request to the model.

**What changed:**
- `config/tasks.yaml`: the Advisor ends with `Confidence: 0.00` to `1.00`, scored with a rubric (0.80 or higher when price, valuation, and news agree; 0.50 to 0.79 when mixed; below 0.50 when weak). It is not told the threshold, so it cannot aim just above it. The Trader is told to trade only at or above the threshold.
- `signals.py` (new): reads the Advisor's `TRADE SIGNAL` and `SENTIMENT` lines, including numeric confidence (`0.78` or `78%`) and the older HIGH/MEDIUM/LOW labels. Moved out of `ui.py` because the Risk Monitor now uses it too.
- `crew.py`: starts each run with its threshold (0.7 if none is given; values outside 0 to 1 stop the run), records the Advisor's parsed signal from its task callback as soon as the Advisor finishes, and clears it when the run ends.
- `monitor.py`: `check_order` now also blocks an order when there is no signal, the signal was HOLD, the side or ticker does not match the signal, the confidence is missing, or the confidence is below the threshold. These checks apply only during a crew run.
- Dashboard: a threshold slider in the question form; the Advisor card shows the confidence (green if it meets the threshold, amber if not) and the threshold; the decision banner explains a HOLD by comparing the two; Run History shows both.
- `main.py`: the terminal version asks for a threshold (Enter for 0.7).
- Tests: 30 new tests for parsing, the new monitor checks, the crew's run tracking, and the slider (78 in total).

---

## How the changes were tested

The checks below are now part of the test suite in `tests/` (see step 9).

- **Database logging:** a run, a trade, a portfolio snapshot, and the price cache were saved and read back from a temporary database.
- **Risk Monitor:** 16 checks against a fake Alpaca account. These covered every blocking rule, an allowed order, a blocked order never reaching `submit_order`, status and fill-price updates, a failed order lookup, position alerts, the crew's finish hook, and upgrading a database created with the old schema.
- **Dashboard:** a live run with a stand-in crew, using Streamlit's test runner. It confirmed the cards advance stage by stage, the new run is saved and selected, a crash shows an error, and an empty form shows a warning. Signal and sentiment parsing was tested against several output formats.
- **Visual review:** every card state (filled buy, blocked order, hold) and every tab was checked in a browser against a demo database, at desktop and phone widths.
- **Real run:** the redesigned dashboard was run against the real Alpaca paper account: an account sync and an NVDA analysis completed successfully.

---

## Known limitations and possible next steps

- **ChromaDB / RAG** from the original blueprint is still not built.
- **Older runs show less detail.** Runs saved before November 4, 2026 have no start time, so their trades and monitor events cannot be matched to them, and their Trader and Monitor cards say "not recorded".
- **Agent logs are not saved.** The dashboard keeps them only for runs made since the page was opened.
- **Order size is fixed** at 5 shares in `tasks.yaml`; it does not scale with confidence.
- **One run at a time.** The Advisor's signal for the run in progress is held in memory in `monitor.py`, so two runs started at the same moment (for example from two browser tabs) would share it.
- **Position warnings repeat.** A position that stays over a limit is flagged again after every run.
- **The daily trade limit uses UTC days,** not the market's trading day.
- **The OneDrive copy** at `Documents\CrewAI 101\first_ai_agents` is a separate local folder that is not linked to this repository and has diverged from it.
