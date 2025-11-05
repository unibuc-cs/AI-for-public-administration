# A2A architecture
# This is the part that actually chains agents together. It’s simple: start at entry, then follow next_agent until there is none.
# This is a classic A2A pattern: each agent knows the next agent; the coordinator just loops.
from __future__ import annotations
from typing import Dict, Any
from .base import AgentState
from .entry_agent import EntryAgent
from .ci_agent import CIAgent
from .social_agent import SocialAgent
from .doc_intake_agent import DocIntakeAgent
from .scheduling_agent import SchedulingAgent
from .case_agent import CaseAgent
from .operator_agent import OperatorAgent


# registry of all agents
AGENTS = {
    "entry": EntryAgent(),
    "ci": CIAgent(),
    "social": SocialAgent(),
    "doc_intake": DocIntakeAgent(),
    "scheduling": SchedulingAgent(),
    "case": CaseAgent(),
    "operator": OperatorAgent(),
}


async def run_agent_graph(initial_state: AgentState) -> AgentState:
    """
    Very small A2A loop:
    - start from 'entry'
    - each agent may set state["next_agent"]
    - stop when there's no next_agent
    """
    state = initial_state
    current = "entry"

    while current:
        agent = AGENTS[current]
        state = await agent.handle(state)
        current = state.get("next_agent")

    return state
