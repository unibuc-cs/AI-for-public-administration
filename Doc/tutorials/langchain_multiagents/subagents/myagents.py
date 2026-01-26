from typing import Optional

from langchain.tools import tool
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from agent_tools import *
from agent_supervisor import AgentSupervisor

# ============================================================================
# Step 2: Create specialized sub-agents
# ============================================================================

# --- Initialize Chat Model ---
model = init_chat_model("gpt-4.1")





# --- Calendar Agent and Tools ---
#---------------------------------------------------------------------------------------
CALENDAR_AGENT_PROMPT = (
    "You are a calendar scheduling assistant. "
    "Parse natural language scheduling requests (e.g., 'next Tuesday at 2pm') "
    "into proper ISO datetime formats. "
    "Use get_available_time_slots to check availability when needed. "
    "Use create_calendar_event to schedule events. "
    "Always confirm what was scheduled in your final response."
)

class AgentsManager:
    """
    Manager for specialized sub-agents.
    """
    model : str | BaseChatModel = None
    calendar_agent : Optional[object] = None
    email_agent : Optional[object] = None
    todo_agent : Optional[object] = None
    agent_supervisor : Optional[AgentSupervisor] = None

    def __init__(self, model: str | BaseChatModel = None):
        self.model = model

        if not self.calendar_agent:
            self.calendar_agent = create_agent(
                self.model,
                tools=[create_calendar_event, get_available_time_slots],
                system_prompt=CALENDAR_AGENT_PROMPT,
                middleware=[HumanInTheLoopMiddleware(
                    interrupt_on={"create_calendar_event": True},
                    description_prefix="Calendar event pending confirmation:\n",
                ),
                ],
            )

        if not self.email_agent:
            self.email_agent = create_agent(
                self.model,
                tools=[send_email, read_inbox],
                system_prompt=(
                    "You are an email assistant. "
                    "Use read_inbox to check for new emails. "
                    "Use send_email to compose and send emails as needed."
                ),
                middleware=[HumanInTheLoopMiddleware(
                    interrupt_on={"send_email": True},
                    description_prefix="Email pending confirmation:\n",
                )]
            )

        if not self.todo_agent:
            self.todo_agent = create_agent(
                self.model,
                tools=[add_todo_item, get_todo_list],
                system_prompt=(
                    "You are a to-do list assistant. "
                    "Use add_todo_item to add tasks. "
                    "Use get_todo_list to retrieve current tasks."
                ),
                middleware=[HumanInTheLoopMiddleware(
                    interrupt_on={"add_todo_item": True},
                    description_prefix="To-do item pending confirmation:\n",
                )]
            )

        # Instantiate the Agent Supervisor and register agents
        self.agent_supervisor = AgentSupervisor(model=model)
        self.agent_supervisor.register_agent("calendar_agent", self.calendar_agent)
        self.agent_supervisor.register_agent("email_agent", self.email_agent)
        self.agent_supervisor.register_agent("todo_agent", self.todo_agent)

        # Setup the supervisor with the agents
        self.agent_supervisor.setup()

    def query(self, request: str,
              config: dict) -> str:
        """
        Process a user request via the Agent Supervisor.
        """
        interrupts = []
        for step in self.agent_supervisor.agent.stream(
                {"messages": [{"role": "user", "content": request}]},
                config=config,
        ):
            for update in step.values():
                if isinstance(update, dict):
                    for message in update.get("messages", []):
                        message.pretty_print()
                else:
                    interrupt_ = update[0]
                    interrupts.append(interrupt_)
                    print(f"--- Interrupt: {interrupt_.id} ---")

        resume = {}
        for interrupt_ in interrupts:
            for request in interrupt_.value["action_requests"]:
                print(f"INTERRUPTED: {interrupt_.id}")
                print(f"{request['description']}\n")

                # Example of revising the argument for an interrupted action, in this case email and subject
                if "email" in request['description'].lower():
                    edited_action = request.copy()
                    edited_action['args']['subject'] = "Mockup review reminder"
                    resume[interrupt_.id] = {
                        "decisions": [{"type": "edit", "edited_action": edited_action}]
                    }
                else:
                    resume[interrupt_.id] = {"decisions": [{"type": "approve"}]}

        interrupts = []
        for step in self.agent_supervisor.agent.stream(
            Command(resume=resume),
            config,
        ):
            for update in step.values():
                if isinstance(update, dict):
                    for message in update.get("messages", []):
                        message.pretty_print()
                else:
                    interrupt_ = update[0]
                    interrupts.append(interrupt_)
                    print(f"--- Interrupt: {interrupt_.id} ---")


        return "Request processed."
