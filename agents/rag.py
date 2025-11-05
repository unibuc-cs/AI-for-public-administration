# agents/rag.py
# Minimal Retrieval-Augmented Generation helper:
#  - Loads chunks from JSON in /kb and optionally from a DOCX (if RAG_DOCX_PATH is set)
#  - Embeds chunks + query using OpenAI embeddings when key/model are configured
#  - Falls back to a very naive character-frequency vector when no key is set
#  - Returns top-k chunks with cosine similarity and a tiny "citation" object
#
# This is intentionally simple and file-system based for prototyping.

import os, json, math
from typing import List, Tuple
from openai import OpenAI

# Optional DOCX file path for RAG
DOCX_PATH = os.getenv("RAG_DOCX_PATH")  # e.g. /path/to/procedure.docx
# Directory containing JSON KB files
KB_DIR = os.getenv("RAG_KB_DIR", "kb")
# Embeddings model; can be overridden
EMB_MODEL = os.getenv("OPENAI_EMB_MODEL", "text-embedding-3-small")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Build OpenAI client if key is present; otherwise remain None and use fallback
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def _load_chunks() -> List[Tuple[str,str]]:
    """
    Load text chunks from:
      - Every .json file under KB_DIR (serialized as a single JSON string)
      - Optional .docx file specified by DOCX_PATH (paragraphs concatenated)
    Returns a list of tuples (source, text).
    """
    chunks = []

    # 1) JSON KB files
    if os.path.isdir(KB_DIR):
        for name in os.listdir(KB_DIR):
            if not name.endswith(".json"):
                continue
            p = os.path.join(KB_DIR, name)
            try:
                data = json.load(open(p, "r", encoding="utf-8"))
                chunks.append((p, json.dumps(data, ensure_ascii=False)))
            except Exception:
                # Fail soft if a KB file is broken
                pass

    # 2) Optional DOCX (if provided)
    if DOCX_PATH and os.path.exists(DOCX_PATH):
        try:
            from docx import Document
            doc = Document(DOCX_PATH)
            buf = []
            for p in doc.paragraphs:
                t = (p.text or "").strip()
                if t:
                    buf.append(t)
            text = "\n".join(buf)
            # Split into manageable chunks for embedding similarity
            parts = []
            step = 800
            for i in range(0, len(text), step):
                parts.append(text[i:i+step])
            for idx, part in enumerate(parts):
                chunks.append((f"{DOCX_PATH}#p{idx+1}", part))
        except Exception:
            # If python-docx isn't installed or DOCX can't be parsed, continue gracefully
            pass

    return chunks


def _embed(texts: List[str]) -> List[List[float]]:
    """
    Embed a batch of texts using OpenAI embeddings if available.
    Otherwise, use a simple character-frequency fallback (not good, but works offline).
    """
    if not client:
        # Fallback: naive character-frequency vectorization (ASCII + Romanian diacritics)
        import collections, string
        alphabet = string.ascii_lowercase + "ăîâșț"
        vecs = []
        for t in texts:
            c = collections.Counter([ch for ch in t.lower() if ch in alphabet])
            v = [c.get(ch, 0) / max(1, len(t)) for ch in alphabet]
            vecs.append(v)
        return vecs

    # Real embeddings
    res = client.embeddings.create(model=EMB_MODEL, input=texts)
    return [d.embedding for d in res.data]


def _cos(a, b):
    """
    Cosine similarity between two vectors.
    """
    num = sum(x*y for x, y in zip(a, b))
    da = math.sqrt(sum(x*x for x in a))
    db = math.sqrt(sum(y*y for y in b))
    if da*db == 0:
        return 0.0
    return num / (da * db)


# Cache to avoid recomputing embeddings on each request during the process lifetime
CHUNKS_CACHE = None
VECS_CACHE = None


def search(query: str, k: int = 3):
    """
    Return top-k most similar chunks to the query, with (score, source, text).
    Designed for lightweight inline RAG in the chatbot to provide citations.
    """
    global CHUNKS_CACHE, VECS_CACHE
    if CHUNKS_CACHE is None:
        CHUNKS_CACHE = _load_chunks()
        VECS_CACHE = _embed([c[1] for c in CHUNKS_CACHE])
    qv = _embed([query])[0]
    scored = []
    for (meta, text), v in zip(CHUNKS_CACHE, VECS_CACHE):
        scored.append((_cos(qv, v), meta, text))
    scored.sort(reverse=True, key=lambda x: x[0])
    return [{"score": round(s, 3), "source": meta, "text": txt} for s, meta, txt in scored[:k]]
