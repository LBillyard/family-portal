"""OpenRouter AI — holiday idea generation."""

import json
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

ALLOWED_MODELS = {
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "anthropic/claude-3-haiku",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-flash-1.5",
}


def is_configured() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def default_model() -> str:
    # Trust the operator's env value — OpenRouter validates model ids server-side.
    # ALLOWED_MODELS only gates user-facing picker input (resolve_model).
    return os.environ.get("OPENROUTER_DEFAULT_MODEL", "").strip() or "openai/gpt-4o-mini"


def resolve_model(requested: str | None) -> str:
    if requested:
        if requested in ALLOWED_MODELS:
            return requested
        logger.warning("Requested model %r not in allowlist — falling back to %s", requested, default_model())
    return default_model()


async def generate_holiday_ideas(prompt: str, model: str | None = None) -> list[dict]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OpenRouter not configured — set OPENROUTER_API_KEY in .env")

    model = resolve_model(model)
    system = (
        "You suggest UK couple holiday destinations. Respond with ONLY valid JSON — no markdown. "
        "Schema: {\"ideas\":[{\"destination\":str,\"summary\":str,\"budget_estimate\":number,\"tags\":[str]}]}. "
        "Give 3 ideas. Budgets in GBP. Be practical about travel from the UK."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("PUBLIC_URL", "http://localhost:8090"),
        "X-Title": "The Hub",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    parsed = _parse_json(content)
    ideas = parsed.get("ideas", [])
    if not ideas:
        raise ValueError("AI returned no ideas — try a different prompt")
    return ideas[:5]


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)
