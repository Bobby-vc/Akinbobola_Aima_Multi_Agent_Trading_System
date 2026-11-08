from types import SimpleNamespace as NS

import pytest

import first_ai_agents.crew as crew_module
import first_ai_agents.database as db
from first_ai_agents.sim_broker import SimulatedBroker

SIGNAL = "SENTIMENT: BULLISH\nTRADE SIGNAL: BUY NVDA | Qty: 5 | Confidence: 0.91"


def sim(name="learner", price=100.0):
    return SimulatedBroker(f"sim:{name}", price_source=lambda symbol: price)


def make_crew(broker=None):
    agents = crew_module.FirstAiAgents(broker=broker or sim())
    return agents, agents.crew()


def start(crew, inputs):
    for callback in crew.before_kickoff_callbacks:
        inputs = callback(inputs)
    return inputs


def finish(crew, result):
    for callback in crew.after_kickoff_callbacks:
        callback(result)


def test_finish_hook_runs_monitor_then_saves_run_with_account_and_cost(temp_db, monkeypatch):
    order = []
    monkeypatch.setattr(crew_module, "run_checks", lambda broker: order.append("monitor") or [])
    real_log = crew_module.log_crew_run
    monkeypatch.setattr(crew_module, "log_crew_run", lambda **kw: order.append("log") or real_log(**kw))
    _, crew = make_crew()

    start(crew, {"question": "Is NVDA a buy?", "ticker": "NVDA", "experience_level": "beginner",
                 "confidence_threshold": 0.7})
    usage = NS(prompt_tokens=10_000, cached_prompt_tokens=2_000, completion_tokens=1_000, successful_requests=6)
    finish(crew, NS(raw="final", tasks_output=[NS(raw="analysis"), NS(raw="HOLD")], token_usage=usage))

    assert order == ["monitor", "log"]
    run = db.get_crew_runs()[0]
    assert (run["ticker"], run["experience"], run["threshold"]) == ("NVDA", "beginner", 0.7)
    assert (run["analysis"], run["trade_signal"]) == ("analysis", "HOLD")
    assert run["started_at"] and run["started_at"] <= run["run_at"]
    assert run["account"] == "sim:learner"
    assert (run["model"], run["prompt_tokens"], run["cached_tokens"], run["completion_tokens"], run["llm_requests"]) \
        == ("openai/gpt-4o", 10_000, 2_000, 1_000, 6)
    # 8,000 uncached at $2.50/M + 2,000 cached at $1.25/M + 1,000 output at $10/M
    assert run["cost_usd"] == pytest.approx(0.0325)


def test_run_is_saved_even_if_monitor_fails(temp_db):
    broker = sim()

    def broker_down():
        raise ConnectionError("broker is down")
    broker.get_account = broker_down
    _, crew = make_crew(broker)

    start(crew, {"ticker": "AMD"})
    finish(crew, NS(raw="final", tasks_output=[]))

    assert db.get_crew_runs()[0]["ticker"] == "AMD"


def test_run_tracks_the_threshold_and_advisor_signal(temp_db):
    agents, crew = make_crew()
    start(crew, {"ticker": "NVDA", "confidence_threshold": "0.8"})
    assert agents.run.threshold == 0.8 and agents.run.signal is None

    crew.tasks[0].callback(NS(raw=SIGNAL))
    assert agents.run.signal["confidence"] == 0.91

    finish(crew, NS(raw="final", tasks_output=[]))
    assert db.get_crew_runs()[0]["threshold"] == 0.8


def test_threshold_defaults_to_0_7(temp_db):
    agents, crew = make_crew()
    inputs = start(crew, {"ticker": "NVDA"})
    assert inputs["confidence_threshold"] == 0.7
    assert agents.run.threshold == 0.7


def test_invalid_threshold_stops_the_run(temp_db):
    _, crew = make_crew()
    with pytest.raises(ValueError):
        start(crew, {"ticker": "NVDA", "confidence_threshold": 7})


def trader_tool(crew, name):
    return next(t for t in crew.agents[1].tools if t.name == name)


def test_order_flows_through_the_monitor_into_a_simulated_fill(temp_db):
    agents, crew = make_crew(sim(price=100.0))
    start(crew, {"ticker": "NVDA"})
    crew.tasks[0].callback(NS(raw=SIGNAL))

    result = trader_tool(crew, "Execute Paper Trade").run(ticker="NVDA", qty=5, side="buy")

    assert "submitted successfully" in result and "Status: filled" in result
    trade = db.get_trades(account="sim:learner")[0]
    assert (trade["ticker"], trade["status"], trade["filled_avg_price"]) == ("NVDA", "filled", 100.0)
    position = agents.run.broker.list_positions()[0]
    assert (position.symbol, position.qty) == ("NVDA", 5)


def test_crews_running_at_once_keep_separate_signals_and_portfolios(temp_db):
    _, crew_a = make_crew(sim("alice"))
    _, crew_b = make_crew(sim("bob"))
    start(crew_a, {"ticker": "NVDA"})
    start(crew_b, {"ticker": "NVDA"})
    crew_a.tasks[0].callback(NS(raw=SIGNAL))  # confident BUY
    crew_b.tasks[0].callback(NS(raw="TRADE SIGNAL: BUY NVDA | Qty: 5 | Confidence: 0.40"))

    result_a = trader_tool(crew_a, "Execute Paper Trade").run(ticker="NVDA", qty=5, side="buy")
    result_b = trader_tool(crew_b, "Execute Paper Trade").run(ticker="NVDA", qty=5, side="buy")

    assert "filled" in result_a
    assert "BLOCKED" in result_b and "0.40" in result_b
    assert [t["status"] for t in db.get_trades(account="sim:alice")] == ["filled"]
    assert [t["status"] for t in db.get_trades(account="sim:bob")] == ["blocked"]
    assert db.get_trades(account="alpaca") == []
