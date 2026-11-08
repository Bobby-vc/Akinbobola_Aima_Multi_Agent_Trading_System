# Product Plan: AIMA as a Subscription Education Tool

Working plan for turning AIMA into a paid learning product. Decisions so far (November 8, 2026):

| Decision | Choice | Why |
|----------|--------|-----|
| Customer | Beginner investors | Matches the original idea of learning by watching AI agents reason; individuals can sign up on their own |
| Platform | Extend the Streamlit app first | Weeks rather than months to a version people can pay for, so demand can be tested before a rebuild |
| Practice portfolios | Simulated inside the app | No broker accounts or per-user API keys, and a clear "education, not brokerage" position |

## The product in one sentence

Beginners ask about a stock, watch three AI desks (research, execution, and risk) work through it with real prices, news, and SEC filings, practice with a simulated portfolio, and learn from a plain-language lesson after every run.

## What already exists

- Advisor and Trader agents, with an enforced confidence threshold
- Rule-based Risk Monitor
- SEC filings search (ChromaDB), Alpaca news, Yahoo Finance prices
- Performance tracking: hit rate, calibration, and comparison with the S&P 500
- Streamlit dashboard and a daily watchlist that builds AIMA's own public track record

## What a paid product needs

### Phase 1: Multi-user foundation
- **Sign-in:** Streamlit's built-in `st.login` with Google sign-in (needs the `Authlib` package and an OAuth client).
- **Per-user data:** a `user_id` on runs, trades, snapshots, and events, and every query filtered by it.
- **Simulated portfolios:** each user starts with virtual cash (for example $100,000). Orders fill at the current market price, and positions and cash live in the database. A broker interface lets the Risk Monitor and Trader work with either the simulated broker (subscribers) or Alpaca (AIMA's own track record).
- **Concurrent runs:** the Risk Monitor currently tracks one run at a time in memory, which must become per-run state before several users can run at once.
- **Cost per run:** record OpenAI token usage for every run. This sets the price.

### Phase 2: Education layer
- **Lesson after every run:** generated from the run's own data (what the P/E means for this company, which risk factors the 10-K highlights, why the threshold held or allowed the trade), at the user's experience level.
- **Glossary on hover:** P/E, 52-week range, confidence, threshold, calibration, benchmark.
- **Learning path:** short lessons that unlock as users complete runs, such as reading a risk factor, what a HOLD means, and why diversification limits exist.
- **Track record page:** AIMA's own Performance tab, public, so users can see how the signals have actually done, including when they were wrong.

### Phase 3: Subscriptions
- **Stripe Checkout and Customer Portal,** with a webhook that records each user's plan.
- **Tiers (to be priced from Phase 1 cost data):**
  - Free: a few runs a week, lessons, and a simulated portfolio.
  - Paid: daily runs, a personal watchlist, full filings search, and progress history.
- **Usage limits:** enforced per plan, because every run costs OpenAI credit.

### Phase 4: Hosting
- Move off the local PC to a host such as Render, Railway, or Fly.io.
- Replace SQLite with Postgres for many users.
- Keep ChromaDB on a persistent volume.
- Run scheduled jobs in the cloud and keep secrets in the host's settings.

### Phase 5: Before charging money
- **Legal review:** a securities lawyer should confirm the education framing, disclaimers, terms of service, and privacy policy. Personalized buy/sell advice for pay can require registration as an investment adviser, so the product should teach and simulate, not advise.
- **Licensed data:** replace yfinance (not licensed for commercial use) with a licensed source such as Alpaca market data or Polygon. Use a company email for SEC EDGAR access.
- **Accounts and payments:** a business entity, a Stripe account, and a domain.

## Open questions

- Product name: keep AIMA?
- Price points: decide after measuring cost per run in Phase 1.
- How much of the system's internals to show beginners, versus a simpler "learning mode" view.
- Whether the AIMA track record is strong enough to show publicly; the Performance tab will answer this over the coming weeks.
