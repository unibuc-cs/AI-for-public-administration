from .base import Agent, AgentState


class LegalGovAgent(Agent):
    name = "legal_gov"

    async def handle(self, state: AgentState) -> AgentState:
        # Placeholder implementation for LegalGovAgent
        state["reply"] = (
            "Pot raspunde la intrebari procedurale. "
            "Spune-mi exact pentru ce: CI (tip, motiv), ajutor social, sau ce nelamurire de procedura ai."
        )

        state["next_agent"] = None
        return state

