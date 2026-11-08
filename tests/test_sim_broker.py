import threading
from types import SimpleNamespace as NS

import pytest

import first_ai_agents.database as db
from first_ai_agents.broker import get_broker, record_portfolio_snapshot
from first_ai_agents.sim_broker import STARTING_CASH, SimulatedBroker
from first_ai_agents.usage import estimate_cost, summarize_usage


class Prices:
    def __init__(self, **prices):
        self.prices = prices

    def __call__(self, symbol):
        return self.prices[symbol]


@pytest.fixture
def prices():
    return Prices(NVDA=100.0, AAPL=200.0)


def broker(prices, name="learner"):
    return SimulatedBroker(f"sim:{name}", price_source=prices)


def test_new_account_starts_with_cash(temp_db, prices):
    account = broker(prices).get_account()
    assert (account.cash, account.portfolio_value, account.buying_power) == (STARTING_CASH,) * 3


def test_buy_fills_at_the_latest_price(temp_db, prices):
    b = broker(prices)
    order = b.submit_order(symbol="nvda", qty=10, side="buy")
    assert (order.status, order.filled_avg_price) == ("filled", 100.0)
    assert b.get_account().cash == STARTING_CASH - 1_000
    assert b.get_order(order.id).status == "filled"


def test_average_cost_and_profit(temp_db, prices):
    b = broker(prices)
    b.submit_order(symbol="NVDA", qty=10, side="buy")
    prices.prices["NVDA"] = 130.0
    b.submit_order(symbol="NVDA", qty=10, side="buy")
    prices.prices["NVDA"] = 150.0
    position = b.list_positions()[0]
    assert position.avg_entry_price == pytest.approx(115.0)
    assert position.unrealized_pl == pytest.approx((150 - 115) * 20)
    assert position.unrealized_plpc == pytest.approx(150 / 115 - 1)
    assert b.get_account().portfolio_value == pytest.approx(STARTING_CASH - 1_000 - 1_300 + 3_000)


def test_selling_returns_cash_and_closes_the_position(temp_db, prices):
    b = broker(prices)
    b.submit_order(symbol="NVDA", qty=10, side="buy")
    prices.prices["NVDA"] = 120.0
    b.submit_order(symbol="NVDA", qty=4, side="sell")
    assert b.list_positions()[0].qty == 6
    b.submit_order(symbol="NVDA", qty=6, side="sell")
    assert b.list_positions() == []
    assert b.get_account().cash == pytest.approx(STARTING_CASH + 10 * 20)


@pytest.mark.parametrize("side, qty", [("buy", 1_001), ("sell", 1)])
def test_unaffordable_buys_and_short_sales_are_rejected(temp_db, prices, side, qty):
    b = broker(prices)
    order = b.submit_order(symbol="NVDA", qty=qty, side=side)  # 1,001 x $100 is more than the cash
    assert order.status == "rejected" and order.filled_avg_price is None
    assert b.get_account().cash == STARTING_CASH and b.list_positions() == []


def test_accounts_are_separate(temp_db, prices):
    alice, bob = broker(prices, "alice"), broker(prices, "bob")
    order = alice.submit_order(symbol="AAPL", qty=5, side="buy")
    assert bob.list_positions() == [] and bob.get_account().cash == STARTING_CASH
    with pytest.raises(KeyError):
        bob.get_order(order.id)


def test_simultaneous_buys_cannot_spend_the_same_cash(temp_db, prices):
    b = broker(prices)
    results = []
    # Each buy costs $60,000 of the $100,000, so only one can fill
    threads = [threading.Thread(target=lambda: results.append(b.submit_order(symbol="NVDA", qty=600, side="buy")))
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(o.status for o in results) == ["filled", "rejected"]
    assert b.get_account().cash == STARTING_CASH - 60_000


def test_invalid_account_ids(temp_db):
    for bad in ("learner", "sim:"):
        with pytest.raises(ValueError):
            SimulatedBroker(bad)
    with pytest.raises(ValueError):
        get_broker("robinhood")


def test_snapshots_are_tagged_with_the_account(temp_db, prices):
    b = broker(prices)
    b.submit_order(symbol="NVDA", qty=10, side="buy")
    record_portfolio_snapshot(b)
    snapshot = db.get_portfolio_snapshots(account="sim:learner")[0]
    assert snapshot["portfolio_value"] == pytest.approx(STARTING_CASH)
    assert db.get_portfolio_snapshots(account="alpaca") == []


# --- run costs ---

def test_unknown_models_have_no_cost_estimate():
    assert estimate_cost("openai/some-new-model", 1_000, 0, 1_000) is None


def test_missing_usage_is_recorded_as_zero():
    usage = summarize_usage(None, "openai/gpt-4o")
    assert (usage["prompt_tokens"], usage["completion_tokens"], usage["cost_usd"]) == (0, 0, 0.0)


def test_cached_tokens_are_cheaper():
    full = estimate_cost("openai/gpt-4o", 10_000, 0, 0)
    cached = estimate_cost("openai/gpt-4o", 10_000, 10_000, 0)
    assert cached == pytest.approx(full / 2)
    assert summarize_usage(NS(prompt_tokens=10_000, cached_prompt_tokens=0, completion_tokens=0,
                              successful_requests=1), "openai/gpt-4o")["cost_usd"] == pytest.approx(full)
