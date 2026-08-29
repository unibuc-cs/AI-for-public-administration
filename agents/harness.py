# agents/harness.py
# The v2 agent harness: one main agent, many skills.
#
# Replaces the v1 multi-agent graph (graph.py + router_agent.py + per-domain agent
# classes). The harness is deliberately small and inspectable — it is the invariant
# core `H` of Doc/absorption-framework-plan.md, Def. 1.
#
# Responsibilities:
#   1. assemble context: base prompt + skill index + permitted tool schemas + history
#   2. select/load skills (LLM-chosen, or by declared triggers when no LLM is available)
#   3. execute tool calls through agents/toolkit.py (permissions + audit live there)
#   4. return a reply plus an observable trace of what was called
#
# Routing keywords are NOT code here: they are declared in each skill's frontmatter.
# Adding a domain means adding skills/<name>/SKILL.md, not editing this file.

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .settings import LLM_MODEL, LLM_USE
from .toolkit import execute_tool, openai_schema, tools_for_actor

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
MAX_TOOL_ROUNDS = int(os.getenv("HARNESS_MAX_ROUNDS", "6"))
MAX_SKILLS_PER_TURN = int(os.getenv("HARNESS_MAX_SKILLS", "3"))


# --------------------------------------------------------------------------
# Skill loading
# --------------------------------------------------------------------------

@dataclass
class Skill:
    name: str
    description: str
    body: str
    domain: Optional[str] = None          # compat value surfaced as state.current_domain
    language: str = "ro"
    triggers: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    sets_domain: bool = True              # advisory skills (e.g. legal) leave domain alone
    fallback_reply: str = ""
    fallback_tool: Optional[str] = None
    fallback_args: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0


def _parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Minimal YAML-subset frontmatter parser.

    Supports `key: value`, `key: [a, b]` and `key: true|false|<int>`. That is all the
    skill format needs, and it keeps the harness dependency-free (no pyyaml).
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")

    meta: Dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        if line[0] in " \t":      # nested keys are not part of the format
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            items = [v.strip().strip("'\"") for v in val[1:-1].split(",")]
            meta[key] = [v for v in items if v]
        elif val.lower() in {"true", "false"}:
            meta[key] = val.lower() == "true"
        elif re.fullmatch(r"-?\d+", val):
            meta[key] = int(val)
        else:
            meta[key] = val.strip("'\"")
    return meta, body


def _load_skills() -> Dict[str, Skill]:
    skills: Dict[str, Skill] = {}
    if not SKILLS_DIR.is_dir():
        return skills
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        try:
            meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        name = meta.get("name") or path.parent.name
        args: Dict[str, Any] = {}
        if isinstance(meta.get("fallback_args"), str) and meta["fallback_args"]:
            try:
                args = json.loads(meta["fallback_args"])
            except Exception:
                args = {}
        skills[name] = Skill(
            name=name,
            description=meta.get("description", ""),
            body=body,
            domain=meta.get("domain"),
            language=meta.get("language", "ro"),
            triggers=[t.lower() for t in (meta.get("triggers") or [])],
            tools=meta.get("tools") or [],
            sets_domain=bool(meta.get("sets_domain", True)),
            fallback_reply=meta.get("fallback_reply", ""),
            fallback_tool=meta.get("fallback_tool") or None,
            fallback_args=args,
            priority=int(meta.get("priority", 0) or 0),
        )
    return skills


_SKILL_CACHE: Dict[str, Skill] = {}


def get_skills(refresh: bool = False) -> Dict[str, Skill]:
    global _SKILL_CACHE
    if refresh or not _SKILL_CACHE:
        _SKILL_CACHE = _load_skills()
    return _SKILL_CACHE


# --------------------------------------------------------------------------
# Session state (per-session, in-memory — prototype only)
# --------------------------------------------------------------------------

SESSION_STATE: Dict[str, Dict[str, Any]] = {}


def session_state(sid: str) -> Dict[str, Any]:
    return SESSION_STATE.setdefault(sid or "anon", {
        "language": "ro",
        "current_domain": None,
        "current_skill": None,
        "loaded_skills": [],
        "case_ids": [],
    })


def reset_session(sid: str) -> bool:
    return SESSION_STATE.pop(sid, None) is not None


# --------------------------------------------------------------------------
# Deterministic skill selection (no LLM required)
# --------------------------------------------------------------------------

def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def select_skill_by_triggers(message: str) -> Tuple[Optional[Skill], int]:
    """Pick the skill whose declared trigger matches most specifically.

    Longest matching trigger wins, so a specific phrase ("baza legala") beats a
    generic token ("buletin") that happens to appear in the same sentence.
    Triggers live in skill frontmatter — this function has no domain knowledge.
    """
    text = _normalize(message)
    best: Optional[Skill] = None
    best_score = 0
    for skill in get_skills().values():
        for trig in skill.triggers:
            t = _normalize(trig)
            if t and t in text:
                score = len(t) * 10 + skill.priority
                if score > best_score:
                    best, best_score = skill, score
    return best, best_score


# --------------------------------------------------------------------------
# Prompt assembly
# --------------------------------------------------------------------------

BASE_PROMPT = """Esti asistentul digital al administratiei publice din Romania.
Ajuti cetatenii cu proceduri administrative si raspunzi implicit in limba romana
(comuta pe engleza doar daca utilizatorul scrie in engleza).

Reguli:
- Nu inventa niciodata cerinte, acte, taxe sau termene. Ele vin DOAR din tool-uri.
- Inainte sa spui ce documente sunt necesare, apeleaza `get_checklist`.
- Pentru intrebari juridice sau de procedura, apeleaza `kb_search` si citeaza sursa.
- Foloseste `load_skill` ca sa incarci procedura potrivita inainte sa ghidezi pas cu pas.
- Nu promite ca un dosar a fost depus decat daca `create_case` a returnat created=true.
- Daca un tool refuza ceva, explica motivul; nu ocoli refuzul.
- Raspunde scurt si concret.
"""

LOAD_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": ("Load the full procedure for a domain before guiding the citizen. "
                        "Call this first when the request matches one of the known skills."),
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
}


def skill_index() -> str:
    lines = []
    for s in get_skills().values():
        lines.append(f"- {s.name}: {s.description}")
    return "\n".join(lines)


def build_system_prompt(loaded: List[Skill]) -> str:
    parts = [BASE_PROMPT, "\n## Skill-uri disponibile\n" + skill_index()]
    for s in loaded:
        parts.append(f"\n## Procedura incarcata: {s.name}\n{s.body}")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------

def _llm_available() -> bool:
    return bool(LLM_USE and os.getenv("OPENAI_API_KEY"))


async def _run_fallback(skill: Optional[Skill], st: Dict[str, Any], actor: dict,
                        sid: str, trace: List[Dict[str, Any]]) -> str:
    """Deterministic path used when no LLM is configured.

    Still goes through the tool layer where the skill declares a fallback tool, so
    the enforcement guarantees and the audit trail hold in this mode too.
    """
    if skill is None:
        names = [s.description for s in get_skills().values() if s.sets_domain and s.domain]
        listing = "\n".join(f"- {d}" for d in names)
        return ("Te rog alege serviciul dorit:\n" + listing) if listing else \
               "Te rog alege serviciul dorit."

    reply = skill.fallback_reply or f"Procedura: {skill.description}"

    if skill.fallback_tool:
        args = dict(skill.fallback_args or {})
        if "session_id" in (args or {}):
            args["session_id"] = sid
        result = await execute_tool(skill.fallback_tool, args, actor, sid)
        trace.append({"tool": skill.fallback_tool, "args": args, "result": result})
        cards = result.get("required_cards") or result.get("missing_cards") or []
        if cards:
            listing = "\n".join(f"- {c.get('label', c.get('id'))}" for c in cards)
            reply = f"{reply}\n{listing}"
        elif result.get("error"):
            reply = f"{reply}\n(Serviciul nu a putut fi contactat momentan.)"
    return reply


async def run_turn(session_id: str, message: str, actor: Optional[dict] = None,
                   history: Optional[List[Dict[str, str]]] = None,
                   person: Optional[dict] = None,
                   app: Optional[dict] = None) -> Dict[str, Any]:
    """Run one conversational turn. Returns {reply, state, steps, halted}."""
    actor = actor or {"sub": "anonymous", "role": "citizen", "scopes": []}
    st = session_state(session_id)
    trace: List[Dict[str, Any]] = []
    steps: List[Dict[str, Any]] = []

    # UI pages can pin the domain (e.g. the CI wizard page) before any message.
    ui_ctx = (app or {}).get("ui_context")
    pinned = None
    if ui_ctx:
        for s in get_skills().values():
            if s.name == ui_ctx or s.domain == ui_ctx:
                pinned = s
                break

    skill, score = select_skill_by_triggers(message)
    if pinned and not skill:
        skill = pinned

    if skill:
        st["current_skill"] = skill.name
        if skill.sets_domain and skill.domain:
            st["current_domain"] = skill.domain
        if skill.name not in st["loaded_skills"]:
            st["loaded_skills"].append(skill.name)
        st["last_agent"] = skill.domain or skill.name

    if not _llm_available():
        reply = await _run_fallback(skill, st, actor, session_id, trace)
        return _envelope(reply, st, steps, trace, mode="deterministic")

    # ---- LLM path -------------------------------------------------------
    loaded: List[Skill] = [skill] if skill else []
    permitted = tools_for_actor(actor)
    tool_schemas = [openai_schema(s) for s in permitted] + [LOAD_SKILL_TOOL]

    msgs: List[Dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(loaded)}
    ]
    for h in (history or [])[-12:]:
        role = (h.get("role") or "").lower()
        content = (h.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": message or ""})

    from .llm_utils import client as llm_client

    reply = ""
    halted = False
    for _round in range(MAX_TOOL_ROUNDS):
        try:
            resp = await llm_client.chat.completions.create(
                model=LLM_MODEL,
                messages=msgs,
                tools=tool_schemas,
                temperature=0,
            )
        except Exception:
            # Degrade to the deterministic path rather than failing the request.
            reply = await _run_fallback(skill, st, actor, session_id, trace)
            return _envelope(reply, st, steps, trace, mode="deterministic-fallback")

        choice = resp.choices[0].message
        calls = getattr(choice, "tool_calls", None) or []
        if not calls:
            reply = (choice.content or "").strip()
            break

        msgs.append({
            "role": "assistant",
            "content": choice.content or "",
            "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in calls
            ],
        })

        for c in calls:
            name = c.function.name
            try:
                args = json.loads(c.function.arguments or "{}")
            except Exception:
                args = {}

            if name == "load_skill":
                want = (args.get("name") or "").strip()
                sk = get_skills().get(want)
                if sk and len(loaded) < MAX_SKILLS_PER_TURN:
                    loaded.append(sk)
                    st["current_skill"] = sk.name
                    if sk.sets_domain and sk.domain:
                        st["current_domain"] = sk.domain
                    if sk.name not in st["loaded_skills"]:
                        st["loaded_skills"].append(sk.name)
                    st["last_agent"] = sk.domain or sk.name
                    msgs[0] = {"role": "system", "content": build_system_prompt(loaded)}
                    out = {"loaded": sk.name}
                else:
                    out = {"error": "unknown_skill", "available": list(get_skills().keys())}
            else:
                if name == "list_uploaded_documents":
                    args.setdefault("session_id", session_id)
                out = await execute_tool(name, args, actor, session_id)
                if name == "create_case" and out.get("created"):
                    cid = out.get("case_id")
                    if cid and cid not in st["case_ids"]:
                        st["case_ids"].append(cid)

            trace.append({"tool": name, "args": args, "result": out})
            msgs.append({"role": "tool", "tool_call_id": c.id,
                         "content": json.dumps(out, ensure_ascii=False, default=str)})
    else:
        halted = True
        reply = reply or "Am nevoie de mai multe informatii ca sa continui."

    if not reply:
        reply = await _run_fallback(skill, st, actor, session_id, trace)

    return _envelope(reply, st, steps, trace, mode="llm", halted=halted)


def _envelope(reply: str, st: Dict[str, Any], steps: List[Dict[str, Any]],
              trace: List[Dict[str, Any]], mode: str, halted: bool = False) -> Dict[str, Any]:
    return {
        "reply": reply,
        "steps": steps,
        "halted": True if not halted else True,
        "state": {
            "language": st.get("language", "ro"),
            "current_domain": st.get("current_domain"),
            "current_skill": st.get("current_skill"),
            "last_agent": st.get("last_agent"),
            "loaded_skills": list(st.get("loaded_skills") or []),
            "case_ids": list(st.get("case_ids") or []),
            "mode": mode,
            "tool_calls": [{"tool": t["tool"], "result": t["result"]} for t in trace],
        },
    }
