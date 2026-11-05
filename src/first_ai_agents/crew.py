from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, after_kickoff, before_kickoff, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from first_ai_agents.tools.custom_tool import get_stock_data, get_stock_news, execute_paper_trade, get_portfolio
from first_ai_agents.broker import get_alpaca_api
from first_ai_agents.database import log_crew_run, utc_now
from first_ai_agents.monitor import run_checks
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
            tools=[get_stock_data, get_stock_news], 
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
        )

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
        self.run_inputs = dict(inputs or {})
        self.run_started_at = utc_now().isoformat()
        return inputs

    @after_kickoff
    def finish_run(self, result):
        # One hook so the monitor's checks are always recorded inside the run's
        # time window. Neither step may break a run, so failures are printed.
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
                threshold=float(inputs.get("confidence_threshold", 0.0)),
                analysis=tasks_output[0].raw if len(tasks_output) > 0 else "",
                trade_signal=tasks_output[1].raw if len(tasks_output) > 1 else "",
                raw_output=result.raw,
                started_at=getattr(self, "run_started_at", None),
            )
        except Exception as e:
            print(f"Could not log crew run to database: {e}")
        return result
