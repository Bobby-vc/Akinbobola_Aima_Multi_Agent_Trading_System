from types import SimpleNamespace as NS

import first_ai_agents.crew as crew_module
import first_ai_agents.database as db


def run_hooks(inputs, result):
    crew = crew_module.FirstAiAgents().crew()
    for callback in crew.before_kickoff_callbacks:
        inputs = callback(inputs)
    for callback in crew.after_kickoff_callbacks:
        callback(result)


def test_finish_hook_runs_monitor_then_saves_run(temp_db, monkeypatch):
    order = []
    monkeypatch.setattr(crew_module, "get_alpaca_api", lambda: "api")
    monkeypatch.setattr(crew_module, "run_checks", lambda api: order.append("monitor") or [])
    real_log = crew_module.log_crew_run
    monkeypatch.setattr(crew_module, "log_crew_run", lambda **kw: order.append("log") or real_log(**kw))

    run_hooks(
        {"question": "Is NVDA a buy?", "ticker": "NVDA", "experience_level": "beginner",
         "confidence_threshold": 0.7},
        NS(raw="final", tasks_output=[NS(raw="analysis"), NS(raw="HOLD")]),
    )

    assert order == ["monitor", "log"]
    run = db.get_crew_runs()[0]
    assert (run["ticker"], run["experience"], run["threshold"]) == ("NVDA", "beginner", 0.7)
    assert (run["analysis"], run["trade_signal"]) == ("analysis", "HOLD")
    assert run["started_at"] and run["started_at"] <= run["run_at"]


def test_run_is_saved_even_if_monitor_fails(temp_db, monkeypatch):
    def alpaca_down():
        raise ConnectionError("Alpaca is down")
    monkeypatch.setattr(crew_module, "get_alpaca_api", alpaca_down)

    run_hooks({"ticker": "AMD"}, NS(raw="final", tasks_output=[]))

    assert db.get_crew_runs()[0]["ticker"] == "AMD"
