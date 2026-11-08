from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, after_kickoff, before_kickoff, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from first_ai_agents.tools.custom_tool import (
    execute_paper_trade, get_portfolio, get_stock_data, get_stock_news, search_sec_filings,
)
from first_ai_agents.broker import get_alpaca_api
from first_ai_agents.database import log_crew_run, utc_now
from first_ai_agents.monitor import (
    DEFAULT_CONFIDENCE_THRESHOLD, end_run, record_signal, run_checks, start_run,
)
from first_ai_agents.signals import parse_signal
# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

@CrewBase
class FirstAiAgents():
    """FirstAiAgents crew"""

    agents: list[BaseAgent]
    tasks: list[Task]

    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    
    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools

    @agent
    def advisor_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['advisor_agent'], # type: ignore[index]
            tools=[get_stock_data, get_stock_news, search_sec_filings],
            verbose=True
        )

    @agent
    def trader_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['trader_agent'], # type: ignore[index]
            tools=[execute_paper_trade, get_portfolio],
            verbose=True
        )

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    @task
    def analyze_investment_question(self) -> Task:
        return Task(
            config=self.tasks_config['analyze_investment_question'], # type: ignore[index]
            callback=self.record_advisor_signal,
        )

    def record_advisor_signal(self, output):
        # Orders are checked against the Advisor's own output, not the Trader's reading of it
        record_signal(parse_signal(output.raw))

    @task
    def evaluate_trade_signal(self) -> Task:
        return Task(
            config=self.tasks_config['evaluate_trade_signal'],
            output_file='trade_report.md'
        )

    @crew
    def crew(self) -> Crew:
        """Creates the FirstAiAgents crew"""
        # To learn how to add knowledge sources to your crew, check out the documentation:
        # https://docs.crewai.com/concepts/knowledge#what-is-knowledge

        return Crew(
            agents=self.agents, # Automatically created by the @agent decorator
            tasks=self.tasks, # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
            # process=Process.hierarchical, # In case you wanna use that instead https://docs.crewai.com/how-to/Hierarchical/
        )

    @before_kickoff
    def capture_inputs(self, inputs):
        inputs = dict(inputs or {})
        threshold = float(inputs.get("confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD))
        start_run(threshold)  # raises if the threshold is outside 0 to 1
        inputs["confidence_threshold"] = threshold
        self.run_inputs = inputs
        self.run_started_at = utc_now().isoformat()
        return inputs

    @after_kickoff
    def finish_run(self, result):
        # One hook so the monitor's checks are always recorded inside the run's
        # time window. Neither step may break a run, so failures are printed.
        end_run()
        try:
            # The risk monitor is rule-based, not an LLM agent, so it runs as a hook
            for finding in run_checks(get_alpaca_api()):
                print(f"[Risk monitor] {finding}")
        except Exception as e:
            print(f"Risk monitor checks failed: {e}")

        try:
            inputs = getattr(self, "run_inputs", {})
            tasks_output = result.tasks_output or []
            log_crew_run(
                question=inputs.get("question", ""),
                ticker=inputs.get("ticker", ""),
                experience=inputs.get("experience_level", ""),
                threshold=inputs.get("confidence_threshold"),
                analysis=tasks_output[0].raw if len(tasks_output) > 0 else "",
                trade_signal=tasks_output[1].raw if len(tasks_output) > 1 else "",
                raw_output=result.raw,
                started_at=getattr(self, "run_started_at", None),
            )
        except Exception as e:
            print(f"Could not log crew run to database: {e}")
        return result
