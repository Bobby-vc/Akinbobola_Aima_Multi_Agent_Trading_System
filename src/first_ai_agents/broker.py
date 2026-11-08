"""Where orders go.

Two kinds of account share one interface (the subset of alpaca_trade_api.REST
the app uses: get_account, list_positions, get_latest_trade, submit_order,
get_order), so the Risk Monitor and the Trader's tools work with either:

- "alpaca": the shared Alpaca paper trading account, which builds AIMA's own
  track record
- "sim:<name>": a simulated practice portfolio kept in the database
  (sim_broker.py), one per learner

AIMA_ACCOUNT in .env picks the account the dashboard and watchlist use.
"""
import os

import alpaca_trade_api as tradeapi
from dotenv import load_dotenv

from first_ai_agents.database import DEFAULT_ACCOUNT, log_portfolio_snapshot

load_dotenv()


def get_alpaca_api() -> tradeapi.REST:
    """Returns an Alpaca client for the paper trading account configured in .env.
    Also used for market data (latest prices, news, the market calendar)."""
    return tradeapi.REST(
        os.getenv("APCA_API_KEY_ID"),
        os.getenv("APCA_API_SECRET_KEY"),
        base_url=os.getenv("APCA_API_BASE_URL"),
    )


class AlpacaBroker:
    """The shared Alpaca paper account."""
    account_id = DEFAULT_ACCOUNT

    def __init__(self, api=None):
        self.api = api or get_alpaca_api()

    def __getattr__(self, name):
        return getattr(self.api, name)


def active_account() -> str:
    return (os.getenv("AIMA_ACCOUNT") or DEFAULT_ACCOUNT).strip()


def get_broker(account: str | None = None):
    account = account or active_account()
    if account == DEFAULT_ACCOUNT:
        return AlpacaBroker()
    if account.startswith("sim:"):
        from first_ai_agents.sim_broker import SimulatedBroker
        return SimulatedBroker(account)
    raise ValueError(f"Unknown account '{account}'. Use 'alpaca' or 'sim:<name>'.")


def record_portfolio_snapshot(broker):
    """Fetches the account and open positions, saves a snapshot, and returns both."""
    account = broker.get_account()
    positions = broker.list_positions()
    log_portfolio_snapshot(
        cash=float(account.cash),
        portfolio_value=float(account.portfolio_value),
        buying_power=float(account.buying_power),
        positions=[
            {
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_entry_price": p.avg_entry_price,
                "current_price": p.current_price,
                "unrealized_pl": p.unrealized_pl,
            }
            for p in positions
        ],
        account=getattr(broker, "account_id", DEFAULT_ACCOUNT),
    )
    return account, positions
