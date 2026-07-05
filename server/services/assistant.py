"""Family Portal AI assistant — OpenRouter tool-calling wired to household data."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from server import database as db
from server.services import openrouter

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_HISTORY = 24
MAX_TOOL_ROUNDS = 8

SYSTEM_PROMPT = """You are the Family Portal assistant for a UK household (two adults: Luke and Partner).
You can read household data and take actions using tools — calendar, tasks, appointments, holidays, bills, and transactions.

Rules:
- Use tools to perform actions; do not pretend something was done without calling a tool.
- Dates/times in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM). Today is provided in context.
- For calendar events, default to the requesting user unless they specify Luke or Partner.
- Amounts are in GBP. Expenses are negative when logging transactions.
- Be concise, warm, and practical. Confirm what you did after using tools.
- If a request is ambiguous, ask one short clarifying question instead of guessing.
- You cannot connect banks or upload files — tell the user to use Finances or Vault tabs."""

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_household_summary",
            "description": "Overview: upcoming events, bills, tasks, holidays, finance snapshot.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_upcoming_events",
            "description": "List calendar events in the next N days.",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "description": "Days ahead", "default": 14}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Add an event to the family calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string", "description": "ISO datetime or date"},
                    "end": {"type": "string"},
                    "all_day": {"type": "boolean"},
                    "location": {"type": "string"},
                    "for_user": {"type": "string", "enum": ["luke", "partner", "both"], "description": "Who the event is for"},
                },
                "required": ["title", "start"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Add a household task / to-do.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "assignee": {"type": "string", "enum": ["luke", "partner", "either"]},
                    "due_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_task_done",
            "description": "Mark a task complete by id or by matching title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "title_contains": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_appointment",
            "description": "Book a medical/dental/other appointment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "provider": {"type": "string"},
                    "datetime": {"type": "string", "description": "ISO datetime"},
                    "category": {"type": "string", "enum": ["health", "dental", "vet", "other"]},
                    "location": {"type": "string"},
                    "for_user": {"type": "string", "enum": ["luke", "partner"]},
                },
                "required": ["title", "provider", "datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_holiday_trip",
            "description": "Start planning a holiday trip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": ["idea", "planning", "booked"]},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "budget": {"type": "number"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_holiday_ideas",
            "description": "AI-generate holiday destination ideas from a prompt (saved to Holidays tab).",
            "parameters": {
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_bill",
            "description": "Add a recurring monthly bill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "amount": {"type": "number"},
                    "due_day": {"type": "integer", "description": "Day of month 1-31"},
                    "category": {"type": "string"},
                },
                "required": ["name", "amount", "due_day"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_transaction",
            "description": "Log an income or expense transaction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "amount": {"type": "number", "description": "Negative for spend, positive for income"},
                    "category": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["description", "amount", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List open or all household tasks.",
            "parameters": {
                "type": "object",
                "properties": {"open_only": {"type": "boolean", "default": True}},
            },
        },
    },
]


def is_configured() -> bool:
    return openrouter.is_configured()


def _resolve_user(for_user: str | None, default_id: str) -> str:
    if not for_user or for_user == "both":
        return default_id
    name_map = {u["name"].lower(): u["id"] for u in db.list_users()}
    return name_map.get(for_user.lower(), for_user if for_user in ("luke", "partner") else default_id)


def _resolve_assignee(name: str | None) -> str | None:
    if not name or name == "either":
        return None
    name_map = {u["name"].lower(): u["id"] for u in db.list_users()}
    return name_map.get(name.lower(), name)


def get_history(user_id: str) -> list[dict]:
    raw = db.get_setting(f"assistant_history_{user_id}", "[]")
    try:
        return json.loads(raw)[-MAX_HISTORY:]
    except json.JSONDecodeError:
        return []


def save_history(user_id: str, messages: list[dict]) -> None:
    db.set_setting(f"assistant_history_{user_id}", json.dumps(messages[-MAX_HISTORY:]))


def clear_history(user_id: str) -> None:
    db.set_setting(f"assistant_history_{user_id}", "[]")


def build_context(user: dict) -> str:
    today = date.today().isoformat()
    users = db.list_users()
    events = db.list_events()
    upcoming = [e for e in events if (e.get("start") or "")[:10] >= today][:8]
    tasks = [t for t in db.list_tasks() if not t.get("done")][:8]
    trips = db.list_trips()
    summary = db.finance_summary()
    return json.dumps(
        {
            "today": today,
            "current_user": user["name"],
            "household": [{"id": u["id"], "name": u["name"]} for u in users],
            "upcoming_events": upcoming,
            "open_tasks": tasks,
            "holiday_trips": trips[:5],
            "finance_summary": summary,
        },
        default=str,
    )


async def execute_tool(name: str, args: dict, user: dict) -> dict:
    uid = user["id"]
    try:
        if name == "get_household_summary":
            return {
                "events": db.list_events()[:10],
                "tasks": db.list_tasks(),
                "bills": db.list_bills(),
                "trips": db.list_trips(),
                "finance": db.finance_summary(),
                "appointments": db.list_appointments()[:10],
            }
        if name == "list_upcoming_events":
            days = int(args.get("days") or 14)
            cutoff = (date.today() + timedelta(days=days)).isoformat()
            today = date.today().isoformat()
            events = [e for e in db.list_events() if today <= (e.get("start") or "")[:10] <= cutoff]
            return {"events": events}
        if name == "create_calendar_event":
            for_user = args.get("for_user")
            owner = _resolve_user(for_user, uid)
            start = args["start"]
            end = args.get("end") or start
            event = db.create_event(
                {
                    "title": args["title"],
                    "start": start,
                    "end": end,
                    "all_day": bool(args.get("all_day") or "T" not in start),
                    "location": args.get("location"),
                    "user_id": owner,
                },
                uid,
            )
            return {"ok": True, "event": event}
        if name == "create_task":
            task = db.create_task(
                {
                    "title": args["title"],
                    "assignee_id": _resolve_assignee(args.get("assignee")),
                    "due": args.get("due_date"),
                    "priority": args.get("priority", "medium"),
                }
            )
            return {"ok": True, "task": task}
        if name == "mark_task_done":
            tasks = db.list_tasks()
            if args.get("task_id"):
                task = db.update_task(args["task_id"], {"done": True})
            else:
                needle = (args.get("title_contains") or "").lower()
                match = next((t for t in tasks if needle in t["title"].lower() and not t["done"]), None)
                task = db.update_task(match["id"], {"done": True}) if match else None
            if not task:
                return {"ok": False, "error": "Task not found"}
            return {"ok": True, "task": task}
        if name == "create_appointment":
            appt = db.create_appointment(
                {
                    "title": args["title"],
                    "provider": args["provider"],
                    "datetime": args["datetime"],
                    "category": args.get("category", "health"),
                    "location": args.get("location"),
                    "user_id": _resolve_user(args.get("for_user"), uid),
                },
                uid,
            )
            return {"ok": True, "appointment": appt}
        if name == "create_holiday_trip":
            trip = db.create_trip(
                {
                    "title": args["title"],
                    "status": args.get("status", "planning"),
                    "start": args.get("start_date"),
                    "end": args.get("end_date"),
                    "budget": float(args.get("budget") or 0),
                }
            )
            return {"ok": True, "trip": trip}
        if name == "generate_holiday_ideas":
            ideas = await openrouter.generate_holiday_ideas(args["prompt"])
            saved = db.create_holiday_ideas(ideas)
            return {"ok": True, "ideas": saved}
        if name == "add_bill":
            bill = db.create_bill(
                {
                    "name": args["name"],
                    "amount": float(args["amount"]),
                    "due_day": int(args["due_day"]),
                    "category": args.get("category", "Other"),
                }
            )
            return {"ok": True, "bill": bill}
        if name == "log_transaction":
            amount = float(args["amount"])
            if amount > 0 and args.get("category", "").lower() != "income":
                amount = -abs(amount)
            elif args.get("category", "").lower() == "income":
                amount = abs(amount)
            else:
                amount = -abs(amount)
            txn = db.create_transaction(
                {
                    "description": args["description"],
                    "amount": amount,
                    "category": args["category"],
                    "date": args.get("date") or date.today().isoformat(),
                    "account_id": "starling",
                }
            )
            return {"ok": True, "transaction": txn}
        if name == "list_tasks":
            tasks = db.list_tasks()
            if args.get("open_only", True):
                tasks = [t for t in tasks if not t.get("done")]
            return {"tasks": tasks}
        return {"ok": False, "error": f"Unknown tool: {name}"}
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return {"ok": False, "error": str(exc)}


async def _call_openrouter(messages: list[dict]) -> dict:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OpenRouter not configured")

    payload = {
        "model": openrouter.default_model(),
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0.4,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("PUBLIC_URL", "http://localhost:8090"),
        "X-Title": "Family Portal Assistant",
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        if resp.status_code >= 400:
            try:
                err = resp.json()
                msg = err.get("error", {}).get("message") or resp.text
            except Exception:
                msg = resp.text
            raise RuntimeError(msg[:300])
        return resp.json()


async def chat(user: dict, message: str) -> dict:
    text = (message or "").strip()
    if not text:
        raise ValueError("Message is required")

    history = get_history(user["id"])
    history.append({"role": "user", "content": text})

    system = f"{SYSTEM_PROMPT}\n\nContext JSON:\n{build_context(user)}"
    messages: list[dict] = [{"role": "system", "content": system}]
    for h in history:
        if h["role"] in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})

    actions: list[dict] = []
    data_changed = False

    for _ in range(MAX_TOOL_ROUNDS):
        data = await _call_openrouter(messages)
        choice = data["choices"][0]["message"]

        if choice.get("tool_calls"):
            messages.append(choice)
            for tc in choice["tool_calls"]:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                try:
                    tool_args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    tool_args = {}
                result = await execute_tool(tool_name, tool_args, user)
                actions.append({"tool": tool_name, "args": tool_args, "result": result})
                if result.get("ok"):
                    data_changed = True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, default=str),
                    }
                )
            continue

        reply = (choice.get("content") or "").strip() or "Done."
        history.append({"role": "assistant", "content": reply})
        save_history(user["id"], history)
        return {"reply": reply, "actions": actions, "data_changed": data_changed}

    reply = "I need to break this into smaller steps — what should we do first?"
    history.append({"role": "assistant", "content": reply})
    save_history(user["id"], history)
    return {"reply": reply, "actions": actions, "data_changed": data_changed}
