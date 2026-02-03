from .base import Agent, AgentState


class HubGovAgent(Agent):
    name = "hubgov"
    async def handle(self, state: AgentState) -> AgentState:
        step = (state.get("steps") or [])[-1] if state.get("steps") else {}
        action = (step.get("hubgov_action") if isinstance(step, dict) else None) or "hubgov_slots"

        # TODO: call services/cei_hub_mock through your http client
        state["reply"] = f"HubGov placeholder: action={action}. (In viitor aici chemam CEI hub.)"
        state["next_agent"] = None
        return state
