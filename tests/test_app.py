"""Runs the dashboard with Streamlit's test runner and a stand-in crew."""
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import first_ai_agents.crew as crew_module
import first_ai_agents.database as db
from first_ai_agents import ui

APP = str(Path(__file__).parents[1] / "src" / "first_ai_agents" / "app.py")


class FakeCrew:
    """Finishes two tasks, then saves a run, the way the real crew's finish hook does."""
    task_callback = None
    error = None

    def kickoff(self, inputs):
        started = db.utc_now().isoformat()
        time.sleep(0.4)
        self.task_callback("advisor output")
        time.sleep(0.4)
        self.task_callback("trader output")
        if FakeCrew.error:
            raise FakeCrew.error
        db.log_crew_run(question=inputs["question"], ticker=inputs["ticker"],
                        experience=inputs["experience_level"], threshold=0.7,
                        analysis="SENTIMENT: BEARISH\nTRADE SIGNAL: SELL AMD | Qty: 5 | Confidence: LOW",
                        trade_signal="Held: confidence too low.", raw_output="", started_at=started)


@pytest.fixture
def app(temp_db, monkeypatch):
    stages = []
    real_live = ui.live_pipeline_html
    monkeypatch.setattr(ui, "live_pipeline_html", lambda n, ticker: stages.append(n) or real_live(n, ticker))
    monkeypatch.setattr(crew_module, "FirstAiAgents", type("FakeAgents", (), {"crew": lambda self: FakeCrew()}))
    monkeypatch.setattr(FakeCrew, "error", None)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    return at, stages


def submit(at, question, ticker):
    at.text_input[0].input(question)
    at.text_input[1].input(ticker)
    next(b for b in at.button if b.label == "Run agents").click()
    return at.run()


def test_empty_database_shows_idle_pipeline(app):
    at, _ = app
    page = " ".join(str(e.proto) for e in at.get("html"))
    assert "Ask a question above to start a run." in page


def test_live_run_is_saved_selected_and_shown(app):
    at, stages = app
    at = submit(at, "Should I sell AMD?", "amd")

    assert not at.exception
    assert stages[:3] == [0, 1, 2]
    run = db.get_crew_runs()[0]
    assert run["ticker"] == "AMD"
    assert at.session_state["selected_run_id"] == run["id"]
    page = " ".join(str(e.proto) for e in at.get("html"))
    assert "HOLD" in page and "SELL with LOW confidence" in page


def test_failed_run_shows_the_error(app, monkeypatch):
    at, _ = app
    monkeypatch.setattr(FakeCrew, "error", RuntimeError("OpenAI rate limit"))
    at = submit(at, "Should I sell AMD?", "AMD")

    assert any("OpenAI rate limit" in e.value for e in at.error)
    assert db.get_crew_runs() == []


def test_empty_form_shows_a_warning(app):
    at, _ = app
    next(b for b in at.button if b.label == "Run agents").click()
    at.run()
    assert any("Enter both" in w.value for w in at.warning)
