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
from .doc_ocr_agent import DocOCRAgent
from .scheduling_agent import SchedulingAgent
from .case_agent import CaseAgent
from .operator_agent import OperatorAgent
from .router_agent import RouterAgent
from .LegalGov import LegalGovAgent
from .HubGovAgent import HubGovAgent



# registry of all agents
AGENTS = {
    "router": RouterAgent(),
    "entry": EntryAgent(),
    "carte_identitate": CIAgent(),
    "social": SocialAgent(),
    "doc_intake": DocIntakeAgent(),
    "doc_ocr": DocOCRAgent(),
    "scheduling": SchedulingAgent(),
    "case": CaseAgent(),
    "operator": OperatorAgent(),
    "legalgov": LegalGovAgent(),
    "hubgov": HubGovAgent(),
}


async def run_agent_graph(initial_state: AgentState) -> AgentState:
    """
    Very small A2A loop:
    - start from 'entry'
    - each agent may set state["next_agent"]
    - stop when there's no next_agent
    """
    state = initial_state
    current = "router"

    while current:
        agent = AGENTS[current]

        # Clear next_agent before each step so stale values can't loop
        state.pop("next_agent", None)

        # Handle current state and agent
        state = await agent.handle(state)

        # go to next specified agent
        current = state.get("next_agent")

    return state
