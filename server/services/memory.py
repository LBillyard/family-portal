"""Family memory — a small semantic (RAG) store the assistant considers on every turn.

Durable facts about the household (people, places, preferences, possessions) are
stored with an embedding vector. On each question we embed the query, retrieve the
most relevant facts (plus any the user pinned) and feed them to the assistant so
answers are personalised. Facts are captured automatically from conversations AND
editable by hand on the Memory page.

Embeddings come from OpenRouter's /embeddings endpoint (same key as chat), so no
extra service or vector database is needed — the corpus is family-sized, so a
brute-force cosine scan in Python is instant.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re

import httpx

from server import database as db

logger = logging.getLogger(__name__)

EMBED_URL = "https://openrouter.ai/api/v1/embeddings"
EMBED_MODEL = "openai/text-embedding-3-small"
EMBED_DIMS = 512

CATEGORIES = ["people", "places", "preferences", "possessions"]
# Cosine alone can't reliably tell "same fact" from "distinct but related" for short
# factoids (paraphrases can score 0.66 while two different facts score 0.77). So the
# embedding check is a CONSERVATIVE guard against near-identical re-embeds only; the
# real semantic dedupe is done by the extraction LLM, which is shown what's already known.
DUP_THRESHOLD = 0.93
RETRIEVE_K = 8
RETRIEVE_MIN_SIM = 0.18
CAPTURE_MODEL_FALLBACK = "openai/gpt-4o-mini"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def is_enabled() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def _headers() -> dict:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OpenRouter not configured — set OPENROUTER_API_KEY in .env")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("PUBLIC_URL", "http://localhost:8090"),
        "X-Title": "The Hub",
    }


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed one or more texts. Returns vectors in the same order as the input."""
    if not texts:
        return []
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            EMBED_URL, headers=_headers(),
            json={"model": EMBED_MODEL, "input": texts, "dimensions": EMBED_DIMS},
        )
        resp.raise_for_status()
        data = resp.json()
    items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
    return [it["embedding"] for it in items]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# --- subjects (who a fact is about) ---

def _subject_from_name(name: str | None) -> str:
    """Map an LLM-supplied person token to a stored subject: a real user id or 'family'."""
    if not name:
        return "family"
    n = name.strip().lower()
    if n in ("family", "both", "us", "we", "shared", ""):
        return "family"
    for u in db.list_users():
        if n == u["id"] or n == (u.get("name") or "").lower():
            return u["id"]
    return "family"


def subject_label(subject: str) -> str:
    if not subject or subject == "family":
        return "Family"
    u = db.get_user(subject)
    return (u or {}).get("name") or subject


# --- write path (with dedupe) ---

async def remember(text: str, *, category: str | None = None, subject: str = "family",
                   source: str = "manual", pinned: bool = False) -> dict | None:
    """Store a fact. If a near-identical fact already exists, update it in place
    rather than creating a duplicate. Returns the stored/updated fact (no embedding)."""
    text = (text or "").strip()
    if not text:
        return None
    subject = _subject_from_name(subject)
    if category not in CATEGORIES:
        category = None
    vec = (await embed([text]))[0]

    existing = db.list_memory_facts(include_embedding=True)
    norm = _norm(text)
    best, best_sim = None, 0.0
    for f in existing:
        if _norm(f["text"]) == norm:  # literal repeat (case/punctuation-insensitive)
            best, best_sim = f, 1.0
            break
        ev = f.get("embedding")
        if not ev:
            continue
        sim = _cosine(vec, ev)
        if sim > best_sim:
            best, best_sim = f, sim

    if best and best_sim >= DUP_THRESHOLD:
        # Essentially the same fact already known — refresh embedding/category, keep the
        # pin. Preserve the existing wording on an exact (normalised) repeat.
        keep_text = best["text"] if _norm(best["text"]) == norm else text
        return db.update_memory_fact(best["id"], {
            "text": keep_text,
            "category": category or best["category"],
            "embedding": vec,
        })
    return db.create_memory_fact({
        "text": text, "category": category or "preferences", "subject": subject,
        "source": source, "pinned": pinned, "embedding": vec,
    })


async def add_manual(text: str, category: str | None, subject: str, pinned: bool) -> dict | None:
    return await remember(text, category=category, subject=subject, source="manual", pinned=pinned)


async def edit(fact_id: str, data: dict) -> dict | None:
    """Update a fact from the Memory page. Re-embeds when the text changes so
    retrieval stays accurate."""
    cur = db.get_memory_fact(fact_id)
    if not cur:
        return None
    payload: dict = {}
    for key in ("category", "subject", "pinned"):
        if data.get(key) is not None:
            payload[key] = data[key]
    if payload.get("subject"):
        payload["subject"] = _subject_from_name(payload["subject"])
    if payload.get("category") not in (None, *CATEGORIES):
        payload.pop("category", None)
    new_text = (data.get("text") or "").strip()
    if new_text and new_text != cur["text"]:
        payload["text"] = new_text
        payload["embedding"] = (await embed([new_text]))[0]
    return db.update_memory_fact(fact_id, payload)


# --- read path (retrieval) ---

async def search(query: str, k: int = RETRIEVE_K) -> list[dict]:
    """Most-relevant facts for a query, plus all pinned facts. Facts include no embedding."""
    facts = db.list_memory_facts(include_embedding=True)
    if not facts:
        return []
    qv = (await embed([query]))[0]
    scored = [(_cosine(qv, f.get("embedding") or []), f) for f in facts]
    scored.sort(key=lambda x: -x[0])
    chosen = [f for sim, f in scored if sim >= RETRIEVE_MIN_SIM][:k]
    seen = {f["id"] for f in chosen}
    for f in facts:  # pinned facts are always considered, even below threshold
        if f.get("pinned") and f["id"] not in seen:
            chosen.append(f)
            seen.add(f["id"])
    for f in chosen:
        f.pop("embedding", None)
    return chosen


async def recall_block(query: str) -> str:
    """A compact text block of relevant memory to inject into the assistant prompt.
    Empty string when memory is disabled/empty or nothing relevant is found."""
    if not is_enabled():
        return ""
    try:
        facts = await search(query)
    except Exception as exc:  # never let memory break a reply
        logger.warning("Memory recall failed: %s", exc)
        return ""
    if not facts:
        return ""
    db.touch_memory_facts([f["id"] for f in facts])
    lines = []
    for f in facts:
        who = f.get("subject", "family")
        prefix = "" if who == "family" else f"{subject_label(who)}: "
        lines.append(f"- {prefix}{f['text']}")
    return (
        "What you know about this household (long-term memory — weave in when relevant, "
        "don't list it back):\n" + "\n".join(lines)
    )


# --- auto-capture (extract durable facts from a conversation exchange) ---

_EXTRACT_SYSTEM = """You maintain a household's long-term memory. From the conversation snippet, extract any DURABLE, NEW facts worth remembering about the family.

Return ONLY JSON, no markdown: {"facts":[{"text": str, "category": "people|places|preferences|possessions", "subject": "family|luke|laura"}]}

Rules:
- Keep ONLY lasting facts: relationships, where people live, preferences/likes/dislikes, allergies, possessions (cars, pets, home, devices), places been or want to go.
- EXCLUDE anything transient: today's plans, a single task/appointment, a one-off question, small talk, or things already phrased as a reminder.
- Each fact is a short standalone sentence, e.g. "Laura is vegetarian", "They have a dog called Bella", "Luke's mum lives in Leeds", "They drive a Tesla Model 3".
- subject = who it's about: "luke", "laura", or "family" for shared/household.
- DO NOT repeat anything already in ALREADY KNOWN, even reworded. Only return genuinely new information or a meaningful change (e.g. they moved, sold the car).
- Be conservative — if there's nothing new and durable, return {"facts":[]}. Never invent facts."""


async def extract_facts(exchange: str, known: list[str] | None = None) -> list[dict]:
    """Ask the model to pull durable, NEW facts from a user⇄assistant exchange.
    `known` is the existing memory so the model can skip anything already stored."""
    model = os.environ.get("OPENROUTER_DEFAULT_MODEL", "").strip() or CAPTURE_MODEL_FALLBACK
    user_content = exchange[:4000]
    if known:
        known_block = "\n".join(f"- {k}" for k in known[:150])
        user_content = f"ALREADY KNOWN (do not repeat these):\n{known_block}\n\nCONVERSATION:\n{exchange[:4000]}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions", headers=_headers(), json=payload
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        parsed = json.loads(content)
    except ValueError:
        return []
    facts = parsed.get("facts", [])
    return [f for f in facts if isinstance(f, dict) and (f.get("text") or "").strip()]


async def capture_from_exchange(user_text: str, assistant_text: str) -> list[dict]:
    """Extract + store durable facts from one exchange. Silent + best-effort — never
    raises into the chat flow. Returns the facts that were newly stored/updated."""
    if not is_enabled():
        return []
    exchange = f"User: {user_text}\nAssistant: {assistant_text}"
    stored: list[dict] = []
    try:
        known = [f["text"] for f in db.list_memory_facts(include_embedding=False)]
        for f in await extract_facts(exchange, known=known):
            saved = await remember(
                f["text"], category=f.get("category"),
                subject=_subject_from_name(f.get("subject")), source="auto",
            )
            if saved:
                stored.append(saved)
    except Exception as exc:
        logger.warning("Memory auto-capture failed: %s", exc)
    if stored:
        logger.info("Memory: captured %d fact(s)", len(stored))
    return stored
