from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

SUPERVISOR_PROMPT = (
    "You are a helpful personal assistant. "
    "You can schedule calendar events, send emails and manage todo lists via specialized sub-agents. "
    "Break down user requests into appropriate tool calls and coordinate the results. "
    "When a request involves multiple actions, use multiple tools in sequence."
)

class AgentSupervisor:
    def __init__(self, model=None,
                    agents: dict[str, object] = None):
        self.agents = agents
        self.model = model

        self.agents : dict[str, object] = agents if agents is not None else {}
        self.tool_descriptions : list[object] = []

        self.agent : object = None

    def get_agent(self, agent_name: str) -> object | None:
        return self.agents.get(agent_name)

    def register_agent(self, agent_name: str, agent: object) -> None:
        self.agents[agent_name] = agent


    def schedule_event(self, request: str) -> str:
        """Schedule calendar events using natural language.

        Use this when the user wants to create, modify, or check calendar appointments.
        Handles date/time parsing, availability checking, and event creation.

        Input: Natural language scheduling request (e.g., 'meeting with design team
        next Tuesday at 2pm')
        """
        calendar_agent = self.get_agent("calendar_agent")
        result = calendar_agent.invoke({
            "messages": [{"role": "user", "content": request}]
        })
        return result["messages"][-1].text

    def manage_email(self, request: str) -> str:
        """Send emails using natural language.

        Use this when the user wants to send notifications, reminders, or any email
        communication. Handles recipient extraction, subject generation, and email
        composition.

        Input: Natural language email request (e.g., 'send them a reminder about
        the meeting')
        """
        email_agent = self.get_agent("email_agent")
        result = email_agent.invoke({
            "messages": [{"role": "user", "content": request}]
        })
        return result["messages"][-1].text

    def todo_function(self, request: str) -> str:
        """Manage to-do items using natural language.

        Use this when the user wants to add, view, or modify tasks in their to-do list.
        Handles task extraction, due date parsing, and task management.

        Input: Natural language to-do request (e.g., 'add a task to review the report
        by Friday')
        """
        todo_agent = self.get_agent("todo_agent")
        result = todo_agent.invoke({
            "messages": [{"role": "user", "content": request}]
        })
        return result["messages"][-1].text

    # Setup from manager only after registering agents
    def setup(self) -> None:
        toolwrap_schedule_event = StructuredTool.from_function(
            func=self.schedule_event,
            name="schedule_event",
            description=self.schedule_event.__doc__,)
        toolwrap_manage_email = StructuredTool.from_function(
            func=self.manage_email,
            name="manage_email",
            description=self.manage_email.__doc__,)

        toolwrap_todo_event = StructuredTool.from_function(
            func=self.todo_function,
            name="todo_function",
            description=self.todo_function.__doc__,
        )

        # Create the tool descriptions for the supervisor
        self.tool_descriptions = [
            toolwrap_schedule_event,
            toolwrap_manage_email,
            toolwrap_todo_event,
            ]


        self.agent = create_agent(
            self.model,
            tools=self.tool_descriptions,
            system_prompt=SUPERVISOR_PROMPT,
            checkpointer=InMemorySaver(),)
