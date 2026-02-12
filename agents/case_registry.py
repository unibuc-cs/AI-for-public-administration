from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict

@dataclass(frozen=True)
class CaseConfig:
    intent: str
    program: str
    agent_name: str
    ui_path: Optional[str]
    title: str

CASE_REGISTRY: Dict[str, CaseConfig] = {
    "carte_identitate": CaseConfig(
        intent="carte_identitate",
        program="CI",
        agent_name="ci",
        ui_path="/user-carte_identitate",
        title="Carte de identitate",
    ),
    "social": CaseConfig(
        intent="social",
        program="AS",
        agent_name="social",
        ui_path="/user-social",
        title="Ajutor social",
    ),
    "taxe": CaseConfig(
        intent="taxe",
        program="TAXE",
        agent_name="taxe",
        ui_path="/user-taxe",
        title="Taxe si impozite",
    ),
}

def get_case_config(intent: str) -> Optional[CaseConfig]:
    return CASE_REGISTRY.get((intent or "").strip().lower())
