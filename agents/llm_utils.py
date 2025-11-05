# Simple async classifier using the OpenAI style chat API.


import os
from typing import Dict, Any
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

INTENT_SYS_PROMPT = """You are an intent classifier for a Romanian e-gov assistant.
You must classify the user's message into ONE of these intents:
- ci          : for carte de identitate / buletin / CI renewals
- social      : for ajutor social, venit minim de incluziune, benefits
- scheduling  : when the user wants to see or pick a slot / programare
- operator    : when the user asks about tasks, cases, backoffice actions
- help        : anything else

Extract useful entities if they appear: cnp, email, slot_id.

Return ONLY JSON with this schema:
{
  "intent": "ci" | "social" | "scheduling" | "operator" | "help",
  "subtype": string | null,
  "entities": {
    "slot_id": string | null,
    "cnp": string | null,
    "email": string | null
  },
  "confidence": float,
  "reason": string
}
If you are not sure, use "help".
"""

# TODO: 1) define the output format more precisely
# 2) add error handling
# 3) add retries / timeouts if needed
# 4) possibly cache results for repeated messages
# 5) History + rag context...eh..
async def classify_intent_with_llm(user_msg: str) -> Dict[str, Any]:
    resp = await client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": INTENT_SYS_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    # resp.choices[0].message.content is JSON
    import json
    return json.loads(resp.choices[0].message.content)
