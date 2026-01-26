import os
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from dotenv import load_dotenv
from pathlib import Path
import os
load_dotenv()  # looks for .env in the current working directory (or parents)
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))
from myagents import *
from agent_supervisor import AgentSupervisor


# ============================================================================

# Init chat model
model = init_chat_model("gpt-4.1")

# instantiate the agents manager
agents_manager = AgentsManager(model=model)

config = {"configurable" : {"thread_id" : "6"}}

agents_manager.query( "Schedule a meeting with the design team next Tuesday at 2pm for 1 hour, "
    "and send them an email reminder about reviewing the new mockups.",
                      config=config)

