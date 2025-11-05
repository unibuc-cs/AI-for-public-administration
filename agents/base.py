# A tiny shared protocol + state type.
from __future__ import annotations
from typing import Any, Dict, Optional, List, TypedDict


class AgentState(TypedDict, total=False):
    session_id: str
    message: str
    person: Dict[str, Any]
    app: Dict[str, Any]
    steps: List[Dict[str, Any]]
    intent: str
    next_agent: Optional[str]
    reply: str


class Agent:
    name: str = "base"

    async def handle(self, state: AgentState) -> AgentState:
        raise NotImplementedError
