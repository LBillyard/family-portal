"""Transaction categorisation — rules first, then learned overrides, then AI.

Design:
- `normalize_merchant()` collapses a raw bank description into a stable key so
  variants ("TESCO STORES 4796", "TESCO STORES 1102") map to one merchant.
- `RULES` are built-in UK-merchant patterns (free, instant).
- Learned overrides (merchant_rules table) win over rules — this is how cryptic
  direct-debit references (council/water) get named once and remembered.
- `ai_suggest()` classifies whatever's left via OpenRouter.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

import httpx

from server.services import openrouter

# The friendly category set the UI works with.
CATEGORIES = [
    "Groceries",
    "Eating out",
    "Transport",
    "Shopping",
    "Subscriptions",
    "Bills & Utilities",
    "Council Tax",
    "Insurance",
    "Health & Fitness",
    "Entertainment",
    "Income",
    "Transfers",
    "Savings",
    "Cash",
    "Crypto",
    "Other",
]

# Categories excluded from the spending breakdown.
NON_SPEND_CATEGORIES = {"Income", "Transfers", "Savings", "Crypto"}
# Categories hidden from the transaction list entirely (user chose to hide crypto).
HIDDEN_CATEGORIES = {"Crypto"}

# Ordered (specific first). First substring hit wins.
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Crypto", ("exchanged to", " btc", " eth", "crypto", "coinbase", "binance", "kraken")),
    ("Subscriptions", (
        "netflix", "spotify", "disney", "amazon prime", "prime video", "apple.com/bill",
        "itunes", "google workspace", "google *cloud", "youtubepremium", "youtube premium",
        "deliveroo plus", "audible", "icloud", "microsoft", "adobe", "now tv", "paramount",
        "britbox", "patreon", "dropbox", "notion", "chatgpt", "openai", "anthropic",
        "linkedin", "nordvpn", "1password", "canva", "strava",
    )),
    ("Council Tax", ("council tax", "council", "-bc", " mbc", " mdc", "borough")),
    ("Bills & Utilities", (
        "octopus", "british gas", "edf", "e.on", "eon energy", "scottish power", "ovo energy",
        "bulb", "utilita", "shell energy", "water", "thames water", "anglian", "severn trent",
        "yorkshire water", "united utilities", "affinity water", "virgin media", "bt broadband",
        "sky digital", "sky uk", "talktalk", "vodafone", "plusnet", "now broadband", "tv licen",
    )),
    ("Insurance", (
        "insurance", "aviva", "admiral", "direct line", "churchill", "hastings", "lv=",
        " axa", "more than", "esure", "confused.com", "compare the", "gocompare", "moneysupermarket",
    )),
    ("Transport", (
        "uber", "lyft", "bolt.eu", "trainline", "tfl", "lul ", " rail", "ryanair", "easyjet",
        "jet2", "british airways", " ba ", "esso", "shell", " bp ", "texaco", "petrol", "fuel",
        "parking", "ringgo", "dvla", "ulez", "dart charge", "national express", "megabus",
    )),
    ("Groceries", (
        "tesco", "sainsbury", "asda", "aldi", "lidl", "morrison", "waitrose", "co-op", "coop",
        "iceland", "spar", "m&s food", "marks spencer", "byram", "ocado", "farmfoods", "costco",
    )),
    ("Eating out", (
        "mcdonald", "greggs", "kfc", "burger king", "nandos", "pizza", "costa", "starbuck",
        "pret", "subway", "just eat", "uber eats", "ubereats", "deliveroo", "domino", "wagamama",
        "five guys", "tgi", "wetherspoon", "spoons", "restaurant", "cafe", "coffee", "grill",
        "kitchen", "takeaway", "chippy", "tortilla", "leon",
    )),
    ("Health & Fitness", (
        "pharmacy", "boots", "superdrug", "nhs", "dentist", "gym", "puregym", "the gym",
        "david lloyd", "holland barrett", "optician", "specsavers", "vision express",
    )),
    ("Entertainment", (
        "cinema", "odeon", "cineworld", "vue ", "theatre", "ticketmaster", "steam", "playstation",
        "xbox", "nintendo", "britbet", "bet365", "paddy power", "sky bet", "ladbrokes", "william hill",
        "epcot", "disney world", "wdw", "dcl ship", "treasure",
    )),
    ("Shopping", (
        "amazon", "amzn", "aliexpress", "ebay", "argos", "currys", "asos", "next retail", "zara",
        "h&m", "zavvi", "whatnot", "shein", "temu", "etsy", "vinted", "john lewis", "ikea",
        "b&q", "wickes", "screwfix", "ryman", "wilko", "aliexpress.com",
    )),
    ("Income", (
        "salary", "wages", "payroll", "hmrc", "stripe payments", "topup from", "payment from",
        "vp ltd", "bonus", "refund", "cashback", "faster payment received",
    )),
    ("Savings", ("family savings", "easy saver", "round up", "round-up", "pot transfer", "savings pot")),
    ("Transfers", ("transfer", "to gbp mb", "to laura", "to luke", "from luke", "from laura", "oba topup")),
    ("Cash", ("cash withdrawal", "atm", "cashpoint", "lnk ", "link atm")),
]


def normalize_merchant(desc: str) -> str:
    """Collapse a raw description to a stable merchant key (variants -> one key)."""
    s = (desc or "").upper()
    s = re.sub(r"HTTPS?://", "", s)
    s = re.sub(r"\*", " ", s)
    # drop number-heavy tokens (store ids, refs) but keep purely-alpha ones
    s = re.sub(r"\b[\d][\w/\-]*\b", " ", s)
    s = re.sub(r"[^A-Z0-9 .&]", " ", s)
    for junk in (" LTD", " LIMITED", " STORES", " STORE", " UK", " GB", " PLC", " INC",
                 " PENDING", " TEMP AUTH HOLD", " SUBS", " PURCHASE"):
        s = s.replace(junk, " ")
    s = re.sub(r"\s+", " ", s).strip()
    key = " ".join(s.split()[:3]).strip()
    if len(key) < 3:
        # cryptic reference (e.g. a bare DD code) — keep the raw form as its own key
        key = re.sub(r"\s+", " ", (desc or "").upper()).strip()[:48]
    return key or "UNKNOWN"


def rule_category(desc: str) -> Optional[str]:
    low = (desc or "").lower()
    for category, needles in RULES:
        for n in needles:
            if n in low:
                return category
    return None


def categorize(desc: str, amount: float, learned: dict[str, str]) -> str:
    """learned: {merchant_key: category}. Returns a category from CATEGORIES."""
    key = normalize_merchant(desc)
    if key in learned:
        return learned[key]
    cat = rule_category(desc)
    if cat:
        return cat
    if amount is not None and amount > 0:
        return "Income"
    return "Other"


async def ai_suggest(merchants: list[str]) -> dict[str, dict]:
    """Classify unknown merchant descriptions via OpenRouter.

    Returns {original_description: {"category": <one of CATEGORIES>, "display_name": <clean name>}}.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key or not merchants:
        return {}
    sample = merchants[:60]
    prompt = (
        "You are categorising UK bank transaction descriptions for a household budgeting app. "
        f"Allowed categories (use EXACTLY one of these): {', '.join(CATEGORIES)}.\n"
        "For each description, return the best category and a short human-friendly merchant name "
        "(e.g. 'TESCO STORES 4796' -> 'Tesco'; '982312107000X' -> keep as-is if unknown). "
        "If you cannot tell, use category 'Other' and keep the name as the original.\n"
        "Return ONLY a JSON object mapping each exact input description to "
        '{"category": "...", "display_name": "..."}.\n\n'
        "Descriptions:\n" + "\n".join(f"- {m}" for m in sample)
    )
    payload = {
        "model": openrouter.default_model(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("PUBLIC_URL", "http://localhost:8090"),
        "X-Title": "Family Portal Categoriser",
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return {}
    out: dict[str, dict] = {}
    valid = set(CATEGORIES)
    for desc, info in (raw.items() if isinstance(raw, dict) else []):
        if not isinstance(info, dict):
            continue
        cat = info.get("category") if info.get("category") in valid else "Other"
        name = (info.get("display_name") or desc).strip()[:60]
        out[desc] = {"category": cat, "display_name": name}
    return out
