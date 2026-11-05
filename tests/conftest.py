import os
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

# Set before any first_ai_agents import: database.py creates its database on
# import, and the tests must never touch the real trading.db. The dummy key
# lets CrewAI build its agents; no test calls OpenAI or Alpaca.
os.environ["AIMA_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "import.db")
os.environ["OPENAI_API_KEY"] = "test-key"

import pytest

import first_ai_agents.database as db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """A fresh, empty database for one test."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def make_position(symbol, qty, price, plpc=0.0):
    return NS(symbol=symbol, qty=str(qty), avg_entry_price=str(price), current_price=str(price),
              unrealized_pl="0", unrealized_plpc=str(plpc), market_value=str(qty * price))


class FakeAlpaca:
    """Stands in for alpaca_trade_api.REST. Records orders instead of sending them."""

    def __init__(self, cash=10_000, value=100_000, positions=(), price=100.0, orders=None):
        self.account = NS(cash=str(cash), portfolio_value=str(value), buying_power=str(cash * 2))
        self.positions = list(positions)
        self.price = price
        self.orders = orders or {}
        self.submitted = []

    def get_account(self):
        return self.account

    def list_positions(self):
        return self.positions

    def get_latest_trade(self, ticker):
        return NS(price=self.price)

    def get_order(self, order_id):
        order = self.orders[order_id]
        if isinstance(order, Exception):
            raise order
        return order

    def submit_order(self, **kwargs):
        self.submitted.append(kwargs)
        return NS(id="new-order", status="accepted")
