# agents/history.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List
import time

CONTROL_MARKERS = {
    "__phase1_done__",
    "__phase2_done__",
    "__upload__",
    "__ping__",
}

# A single turn in the conversation history containing role, text, and timestamp.
@dataclass
class Turn:
    role: str   # "user" | "assistant" | "system"
    text: str
    ts: float

class HistoryStore:
    """
    In-memory history, per session. Prototype only.
    """
    def __init__(self, max_turns: int = 30):
        self.max_turns = max_turns

        # Store structure: {session_id: [Turn, Turn, ...]}
        self._store: Dict[str, List[Turn]] = {}

    # Add a new turn to the history for a given session ID.
    def add(self, sid: str, role: str, text: str) -> None:
        if not sid:
            return
        turns = self._store.setdefault(sid, [])
        turns.append(Turn(role=role, text=text or "", ts=time.time()))
        if len(turns) > self.max_turns:
            self._store[sid] = turns[-self.max_turns :]

    # Retrieve the raw history for a given session ID.
    def raw(self, sid: str) -> List[Dict[str, Any]]:
        turns = self._store.get(sid, [])
        return [{"role": t.role, "text": t.text, "ts": t.ts} for t in turns]

    def filtered_for_llm(self, sid: str) -> List[Dict[str, str]]:
        """
        Returns messages safe for LLM:
        - drop control markers
        - keep normal system hints
        """
        out: List[Dict[str, str]] = []
        for t in self._store.get(sid, []):
            txt = (t.text or "").strip()
            if t.role == "system" and txt in CONTROL_MARKERS:
                continue
            # also drop if user accidentally sees/sends those markers
            if txt in CONTROL_MARKERS:
                continue
            out.append({"role": t.role, "content": txt})
        return out
