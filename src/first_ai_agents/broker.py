import os

import alpaca_trade_api as tradeapi
from dotenv import load_dotenv

from first_ai_agents.database import log_portfolio_snapshot

load_dotenv()


def get_alpaca_api() -> tradeapi.REST:
    """Returns an Alpaca client for the paper trading account configured in .env."""
    return tradeapi.REST(
        os.getenv("APCA_API_KEY_ID"),
        os.getenv("APCA_API_SECRET_KEY"),
        base_url=os.getenv("APCA_API_BASE_URL"),
    )


def record_portfolio_snapshot(api: tradeapi.REST):
    """Fetches the account and open positions, saves a snapshot, and returns both."""
    account = api.get_account()
    positions = api.list_positions()
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
    )
    return account, positions
