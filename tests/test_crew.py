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


def test_run_tracks_the_threshold_and_advisor_signal(temp_db, monkeypatch):
    import first_ai_agents.monitor as monitor
    monkeypatch.setattr(crew_module, "get_alpaca_api", lambda: "api")
    monkeypatch.setattr(crew_module, "run_checks", lambda api: [])
    crew = crew_module.FirstAiAgents().crew()

    for callback in crew.before_kickoff_callbacks:
        callback({"ticker": "NVDA", "confidence_threshold": "0.8"})
    assert monitor._active_run == {"threshold": 0.8, "signal": None}

    advisor_task = crew.tasks[0]
    advisor_task.callback(NS(raw="SENTIMENT: BULLISH\nTRADE SIGNAL: BUY NVDA | Qty: 5 | Confidence: 0.91"))
    assert monitor._active_run["signal"]["confidence"] == 0.91

    for callback in crew.after_kickoff_callbacks:
        callback(NS(raw="final", tasks_output=[]))
    assert monitor._active_run is None
    assert db.get_crew_runs()[0]["threshold"] == 0.8


def test_threshold_defaults_to_0_7():
    import first_ai_agents.monitor as monitor
    crew = crew_module.FirstAiAgents().crew()
    for callback in crew.before_kickoff_callbacks:
        inputs = callback({"ticker": "NVDA"})
    assert inputs["confidence_threshold"] == 0.7
    assert monitor._active_run["threshold"] == 0.7


def test_invalid_threshold_stops_the_run():
    import pytest
    crew = crew_module.FirstAiAgents().crew()
    with pytest.raises(ValueError):
        for callback in crew.before_kickoff_callbacks:
            callback({"ticker": "NVDA", "confidence_threshold": 7})
