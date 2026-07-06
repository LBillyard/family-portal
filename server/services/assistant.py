"""Family Portal AI assistant — OpenRouter tool-calling wired to household data."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from server import database as db
from server.services import openrouter
from server.services import activity as activity_log
from server.services import briefing as briefing_svc
from server.services import memory as mem_svc
from server.services import search as search_svc
from server.services import trips as trips_svc

logger = logging.getLogger(__name__)

# Keep references to fire-and-forget capture tasks so they aren't GC'd mid-flight.
_capture_tasks: set = set()


def _schedule_capture(user_text: str, assistant_text: str) -> None:
    """Extract + store durable family facts from this exchange, off the reply path
    (adds no latency). Best-effort — a running event loop is required."""
    if not mem_svc.is_enabled():
        return
    try:
        task = asyncio.create_task(mem_svc.capture_from_exchange(user_text, assistant_text))
        _capture_tasks.add(task)
        task.add_done_callback(_capture_tasks.discard)
    except RuntimeError:
        pass  # no running loop (e.g. a sync test) — skip silently

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_HISTORY = 24
MAX_TOOL_ROUNDS = 8
CONFIRM_TOOLS = {"log_transaction", "add_bill"}

SYSTEM_PROMPT = """You are The Hub, the household assistant for a UK family (two adults: Luke and Laura).
You can read household data and take actions using tools — calendar, tasks, appointments, holidays, bills, and transactions.

Rules:
- Use tools to perform actions; do not pretend something was done without calling a tool.
- Dates/times in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM). Today is provided in context.
- For calendar events and appointments, default to the person messaging you (see current_user in context) unless they name the other person or say "for Laura", "my", "I", etc. Pass who it's for as for_user.
- ALWAYS make clear WHOSE an event/appointment is when you confirm or read it back. Use "you"/"your" when it belongs to the person messaging, otherwise name them — e.g. "You've got a haircut Fri at 2pm" or "Laura has a dentist appointment on Tue 8 Jul at 3pm". The tool result's "for" field (and the "whose" field on events you read) tells you: "you" means the sender, a name means the other person — phrase accordingly.
- Amounts are in GBP. Expenses are negative when logging transactions.
- Be concise, warm, and practical. After using a tool, state plainly what you did so it can be corrected.
- If the user says an entry is wrong or wants to undo/change it, use the update_* or delete_* tools to fix or remove it — prefer the id returned by the previous action, otherwise match by title.
- If a request is ambiguous, ask one short clarifying question instead of guessing.
- You cannot connect banks or upload files — tell the user to use Finances or Vault tabs."""

# Appended when the conversation is happening over WhatsApp (act-then-confirm model).
WHATSAPP_NOTE = """

You are replying over WhatsApp text. Keep replies short (1-3 sentences, no markdown).
Act immediately on clear instructions, then confirm what you did in one line, naming whose it is: "Booked your dentist, Tue 8 Jul 3pm" or "Added Laura's dentist appt, Tue 8 Jul 3pm". If they reply that it's wrong, correct or undo it with the update_*/delete_* tools."""

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
                    "for_user": {"type": "string", "enum": ["luke", "laura", "both"], "description": "Who the event is for"},
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
                    "assignee": {"type": "string", "enum": ["luke", "laura", "either"]},
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
                    "for_user": {"type": "string", "enum": ["luke", "laura"]},
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
    {
        "type": "function",
        "function": {
            "name": "get_morning_briefing",
            "description": "Daily briefing: today's events, appointments, tasks, renewals, next trip.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_household",
            "description": "Search events, bills, transactions, tasks, trips, documents, maintenance.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_maintenance_item",
            "description": "Log home maintenance (boiler, gutters, appliances).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string"},
                    "next_due_date": {"type": "string"},
                    "interval_months": {"type": "integer"},
                    "vendor": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_trip_packing_list",
            "description": "Add packing list template to a holiday trip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_title": {"type": "string"},
                    "template": {"type": "string", "enum": ["default", "beach", "city", "weekend"]},
                },
                "required": ["trip_title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_calendar_event",
            "description": "Change an existing calendar event's time, title or location (use to correct one you just created). Identify by event_id (preferred, from a prior result) or title_contains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "title_contains": {"type": "string"},
                    "title": {"type": "string", "description": "New title"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "all_day": {"type": "boolean"},
                    "location": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_calendar_event",
            "description": "Delete/undo/cancel a calendar event by event_id (preferred) or title_contains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "title_contains": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_appointment",
            "description": "Change an existing appointment's time/provider/title/location. Identify by appointment_id (preferred) or title_contains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "title_contains": {"type": "string"},
                    "title": {"type": "string"},
                    "provider": {"type": "string"},
                    "datetime": {"type": "string"},
                    "location": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Cancel/delete/undo an appointment by appointment_id (preferred) or title_contains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "title_contains": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Delete/undo a task by task_id (preferred) or title_contains.",
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
            "name": "delete_transaction",
            "description": "Delete/undo a logged transaction (reverses the balance) by transaction_id (preferred) or description_contains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string"},
                    "description_contains": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_bill",
            "description": "Delete/undo a bill by bill_id (preferred) or name_contains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id": {"type": "string"},
                    "name_contains": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_bill_paid",
            "description": "Mark a bill as paid for this cycle by bill_id (preferred) or name_contains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id": {"type": "string"},
                    "name_contains": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_bill",
            "description": "Change an existing bill's name, amount, due day, recurrence or category. Identify by bill_id (preferred) or name_contains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id": {"type": "string"},
                    "name_contains": {"type": "string"},
                    "name": {"type": "string", "description": "New name"},
                    "amount": {"type": "number"},
                    "due_day": {"type": "integer", "description": "Day of month 1-31"},
                    "recurrence": {"type": "string"},
                    "category": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Change an existing task's title, assignee, due date, priority, reminder or completion. Identify by task_id (preferred) or title_contains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "title_contains": {"type": "string"},
                    "title": {"type": "string", "description": "New title"},
                    "assignee": {"type": "string", "enum": ["luke", "laura", "either"]},
                    "due_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "completed": {"type": "boolean"},
                    "remind_at": {"type": "string", "description": "ISO datetime"},
                },
            },
        },
    },
]


def is_configured() -> bool:
    return openrouter.is_configured()


def _resolve_user(for_user: str | None, default_id: str) -> str:
    if not for_user or for_user == "both":
        return default_id
    fu = for_user.lower()
    users = db.list_users()
    name_map = {u["name"].lower(): u["id"] for u in users}
    if fu in name_map:
        return name_map[fu]
    if fu in {u["id"] for u in users}:
        return fu
    return default_id


def _owner_label(owner_id: str | None, sender_id: str) -> str:
    """How to refer to whose an item is in a reply: 'you' when it belongs to the
    person messaging, otherwise their first name (e.g. 'Laura'). Lets the model
    say 'you have a dentist appointment' vs 'Laura has a dentist appointment'."""
    if not owner_id:
        return "the family"
    if owner_id == sender_id:
        return "you"
    u = db.get_user(owner_id)
    return (u or {}).get("name") or "they"


def _tag_owner(item: dict, sender_id: str) -> dict:
    """Annotate a read-tool event/appointment with a 'whose' label so the model can
    attribute it in replies ('you have…' vs 'Laura has…')."""
    out = dict(item)
    out["whose"] = _owner_label(item.get("user_id"), sender_id)
    return out


async def notify_task_assignee(task: dict, sender: dict, verb: str = "added a task for you") -> None:
    """If a task is assigned to the *other* household member, ping them on WhatsApp
    so both people have visibility. Best-effort: never breaks task creation/edits, and
    a free-form message only delivers if the assignee has an open 24h window."""
    assignee_id = task.get("assignee")
    if not assignee_id or assignee_id == sender.get("id"):
        return
    try:
        from server.services import whatsapp

        if not whatsapp.is_configured():
            return
        assignee = db.get_user(assignee_id)
        phone = (assignee or {}).get("phone")
        if not phone:
            return
        parts = [f"📋 {sender.get('name', 'Someone')} {verb}: {task['title']}"]
        if task.get("due"):
            parts.append(f"due {task['due']}")
        if task.get("priority") and task["priority"] != "medium":
            parts.append(f"{task['priority']} priority")
        await whatsapp.send_text(phone, " · ".join(parts))
        logger.info("Notified %s — %s (by %s)", assignee_id, verb, sender.get("id"))
    except Exception as exc:
        logger.warning("Task-assignee WhatsApp notify failed: %s", exc)


def _resolve_assignee(name: str | None) -> str | None:
    if not name or name in ("either", "both"):
        return None
    fu = name.lower()
    users = db.list_users()
    name_map = {u["name"].lower(): u["id"] for u in users}
    if fu in name_map:
        return name_map[fu]
    if fu in {u["id"] for u in users}:
        return fu
    return None


def _match_id(items: list[dict], field: str, needle: str | None) -> str | None:
    if not needle:
        return None
    n = needle.lower()
    match = next((it for it in items if n in (it.get(field) or "").lower()), None)
    return match["id"] if match else None


def _hist_key(user_id: str, channel: str) -> str:
    # Web keeps the original key (preserve existing history); other channels namespace separately.
    return f"assistant_history_{user_id}" if channel == "web" else f"assistant_history_{channel}_{user_id}"


def get_history(user_id: str, channel: str = "web") -> list[dict]:
    raw = db.get_setting(_hist_key(user_id, channel), "[]")
    try:
        return json.loads(raw)[-MAX_HISTORY:]
    except json.JSONDecodeError:
        return []


def save_history(user_id: str, messages: list[dict], channel: str = "web") -> None:
    db.set_setting(_hist_key(user_id, channel), json.dumps(messages[-MAX_HISTORY:]))


def clear_history(user_id: str, channel: str = "web") -> None:
    db.set_setting(_hist_key(user_id, channel), "[]")


def build_context(user: dict) -> str:
    today = date.today().isoformat()
    users = db.list_users()
    events = db.list_events()
    upcoming = [_tag_owner(e, user["id"]) for e in events if (e.get("start") or "")[:10] >= today][:8]
    appts = [_tag_owner(a, user["id"]) for a in db.list_appointments() if (a.get("datetime") or "")[:10] >= today][:8]
    tasks = [t for t in db.list_tasks() if not t.get("done")][:8]
    trips = db.list_trips()
    summary = db.finance_summary()
    return json.dumps(
        {
            "today": today,
            "current_user": user["name"],
            "household": [{"id": u["id"], "name": u["name"]} for u in users],
            "upcoming_events": upcoming,
            "upcoming_appointments": appts,
            "open_tasks": tasks,
            "holiday_trips": trips[:5],
            "finance_summary": summary,
        },
        default=str,
    )


async def execute_tool(name: str, args: dict, user: dict, *, confirmed: bool = False) -> dict:
    uid = user["id"]
    if name in CONFIRM_TOOLS and not confirmed:
        summary = _confirm_summary(name, args)
        pending = db.create_pending_action(
            {
                "user_id": uid,
                "tool_name": name,
                "args_json": json.dumps(args),
                "summary": summary,
            }
        )
        return {
            "ok": False,
            "needs_confirmation": True,
            "pending_id": pending["id"],
            "summary": summary,
        }
    try:
        if name == "get_household_summary":
            return {
                "events": [_tag_owner(e, uid) for e in db.list_events()[:10]],
                "tasks": db.list_tasks(),
                "bills": db.list_bills(),
                "trips": db.list_trips(),
                "finance": db.finance_summary(),
                "appointments": [_tag_owner(a, uid) for a in db.list_appointments()[:10]],
            }
        if name == "list_upcoming_events":
            days = int(args.get("days") or 14)
            cutoff = (date.today() + timedelta(days=days)).isoformat()
            today = date.today().isoformat()
            events = [_tag_owner(e, uid) for e in db.list_events() if today <= (e.get("start") or "")[:10] <= cutoff]
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
            try:
                from server.services import google_calendar

                if google_calendar.is_configured():
                    gid = google_calendar.push_event_to_google(owner, {**event, "all_day": bool(args.get("all_day") or "T" not in start)})
                    if gid:
                        # Remember what we pushed so the next Google sync doesn't re-import it as a duplicate.
                        db.set_event_google_written(event["id"], gid)
            except Exception:
                pass
            activity_log.log(user, "created", "event", f"Added event: {args['title']}", entity_id=event["id"])
            return {"ok": True, "event": event, "for": _owner_label(owner, uid)}
        if name == "create_task":
            task = db.create_task(
                {
                    "title": args["title"],
                    "assignee_id": _resolve_assignee(args.get("assignee")),
                    "due": args.get("due_date"),
                    "priority": args.get("priority", "medium"),
                }
            )
            await notify_task_assignee(task, user)
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
            owner = _resolve_user(args.get("for_user"), uid)
            appt = db.create_appointment(
                {
                    "title": args["title"],
                    "provider": args["provider"],
                    "datetime": args["datetime"],
                    "category": args.get("category", "health"),
                    "location": args.get("location"),
                    "user_id": owner,
                },
                uid,
            )
            return {"ok": True, "appointment": appt, "for": _owner_label(owner, uid)}
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
            activity_log.log(user, "created", "bill", f"Added bill: {args['name']}", entity_id=bill["id"])
            return {"ok": True, "bill": bill}
        if name == "log_transaction":
            amount = float(args["amount"])
            if amount > 0 and args.get("category", "").lower() != "income":
                amount = -abs(amount)
            elif args.get("category", "").lower() == "income":
                amount = abs(amount)
            else:
                amount = -abs(amount)
            account_id = db.resolve_account_id()
            if not account_id:
                return {"ok": False, "error": "No account to log against yet — connect a bank first."}
            txn = db.create_transaction(
                {
                    "description": args["description"],
                    "amount": amount,
                    "category": args["category"],
                    "date": args.get("date") or date.today().isoformat(),
                    "account_id": account_id,
                }
            )
            activity_log.log(user, "created", "transaction", f"Logged: {args['description']} £{amount:.2f}", entity_id=txn["id"])
            return {"ok": True, "transaction": txn}
        if name == "list_tasks":
            tasks = db.list_tasks()
            if args.get("open_only", True):
                tasks = [t for t in tasks if not t.get("done")]
            return {"tasks": tasks}
        if name == "get_morning_briefing":
            return briefing_svc.build_briefing(user)
        if name == "search_household":
            return search_svc.search(args.get("query", ""))
        if name == "create_maintenance_item":
            item = db.create_maintenance(
                {
                    "title": args["title"],
                    "category": args.get("category", "general"),
                    "next_due_date": args.get("next_due_date", ""),
                    "interval_months": args.get("interval_months", 12),
                    "vendor": args.get("vendor", ""),
                    "user_id": uid,
                }
            )
            activity_log.log(user, "created", "maintenance", f"Added maintenance: {args['title']}", entity_id=item["id"])
            return {"ok": True, "maintenance": item}
        if name == "add_trip_packing_list":
            trips = db.list_trips()
            needle = (args.get("trip_title") or "").lower()
            trip = next((t for t in trips if needle in t["title"].lower()), None)
            if not trip:
                return {"ok": False, "error": "Trip not found"}
            packing = trips_svc.add_packing_list(trip["id"], args.get("template", "default"))
            return {"ok": True, "trip_id": trip["id"], "packing": packing}
        if name == "update_calendar_event":
            eid = args.get("event_id") or _match_id(db.list_events(), "title", args.get("title_contains"))
            if not eid:
                return {"ok": False, "error": "Event not found"}
            patch = {k: args[k] for k in ("title", "start", "end", "location") if args.get(k) is not None}
            if args.get("all_day") is not None:
                patch["all_day"] = bool(args["all_day"])
            event = db.update_event(eid, patch)
            if event:
                activity_log.log(user, "updated", "event", f"Updated event: {event['title']}", entity_id=eid)
                return {"ok": True, "event": event}
            return {"ok": False, "error": "Event not found"}
        if name == "delete_calendar_event":
            eid = args.get("event_id") or _match_id(db.list_events(), "title", args.get("title_contains"))
            ok = db.delete_event(eid) if eid else False
            if ok:
                activity_log.log(user, "deleted", "event", "Removed calendar event", entity_id=eid)
            return {"ok": ok} if ok else {"ok": False, "error": "Event not found"}
        if name == "update_appointment":
            aid = args.get("appointment_id") or _match_id(db.list_appointments(), "title", args.get("title_contains"))
            if not aid:
                return {"ok": False, "error": "Appointment not found"}
            patch = {k: args[k] for k in ("title", "provider", "datetime", "location") if args.get(k) is not None}
            appt = db.update_appointment(aid, patch)
            if appt:
                activity_log.log(user, "updated", "appointment", f"Updated appointment: {appt['title']}", entity_id=aid)
                return {"ok": True, "appointment": appt}
            return {"ok": False, "error": "Appointment not found"}
        if name == "cancel_appointment":
            aid = args.get("appointment_id") or _match_id(db.list_appointments(), "title", args.get("title_contains"))
            ok = db.delete_appointment(aid) if aid else False
            if ok:
                activity_log.log(user, "deleted", "appointment", "Cancelled appointment", entity_id=aid)
            return {"ok": ok} if ok else {"ok": False, "error": "Appointment not found"}
        if name == "delete_task":
            tid = args.get("task_id") or _match_id(db.list_tasks(), "title", args.get("title_contains"))
            ok = db.delete_task(tid) if tid else False
            return {"ok": ok} if ok else {"ok": False, "error": "Task not found"}
        if name == "delete_transaction":
            txn_id = args.get("transaction_id") or _match_id(db.list_transactions(), "description", args.get("description_contains"))
            ok = db.delete_transaction(txn_id) if txn_id else False
            if ok:
                activity_log.log(user, "deleted", "transaction", "Removed transaction", entity_id=txn_id)
            return {"ok": ok} if ok else {"ok": False, "error": "Transaction not found"}
        if name == "delete_bill":
            bid = args.get("bill_id") or _match_id(db.list_bills(), "name", args.get("name_contains"))
            ok = db.delete_bill(bid) if bid else False
            if ok:
                activity_log.log(user, "deleted", "bill", "Removed bill", entity_id=bid)
            return {"ok": ok} if ok else {"ok": False, "error": "Bill not found"}
        if name == "mark_bill_paid":
            bid = args.get("bill_id") or _match_id(db.list_bills(), "name", args.get("name_contains"))
            bill = db.mark_bill_paid(bid) if bid else None
            if not bill:
                return {"ok": False, "error": "Bill not found"}
            activity_log.log(user, "updated", "bill", f"Marked bill paid: {bill['name']}", entity_id=bid)
            return {"ok": True, "bill": bill}
        if name == "update_bill":
            bid = args.get("bill_id") or _match_id(db.list_bills(), "name", args.get("name_contains"))
            if not bid:
                return {"ok": False, "error": "Bill not found"}
            patch = {k: args[k] for k in ("name", "amount", "due_day", "recurrence", "category") if args.get(k) is not None}
            bill = db.update_bill(bid, patch)
            if bill:
                activity_log.log(user, "updated", "bill", f"Updated bill: {bill['name']}", entity_id=bid)
                return {"ok": True, "bill": bill}
            return {"ok": False, "error": "Bill not found"}
        if name == "update_task":
            tid = args.get("task_id") or _match_id(db.list_tasks(), "title", args.get("title_contains"))
            if not tid:
                return {"ok": False, "error": "Task not found"}
            patch: dict = {k: args[k] for k in ("title", "priority", "remind_at") if args.get(k) is not None}
            if args.get("assignee") is not None:
                patch["assignee_id"] = _resolve_assignee(args["assignee"])
            if args.get("due_date") is not None:
                patch["due"] = args["due_date"]
            if args.get("completed") is not None:
                patch["done"] = bool(args["completed"])
            task = db.update_task(tid, patch)
            if not task:
                return {"ok": False, "error": "Task not found"}
            activity_log.log(user, "updated", "task", f"Updated task: {task['title']}", entity_id=tid)
            if "assignee_id" in patch:
                await notify_task_assignee(task, user, verb="reassigned a task to you")
            return {"ok": True, "task": task}
        return {"ok": False, "error": f"Unknown tool: {name}"}
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return {"ok": False, "error": str(exc)}


def _confirm_summary(tool_name: str, args: dict) -> str:
    if tool_name == "log_transaction":
        return f"Log transaction: {args.get('description')} — £{float(args.get('amount', 0)):.2f} ({args.get('category', 'Other')})"
    if tool_name == "add_bill":
        return f"Add bill: {args.get('name')} — £{float(args.get('amount', 0)):.2f} due day {args.get('due_day')}"
    return f"Confirm {tool_name}"


async def confirm_action(action_id: str, user: dict) -> dict:
    pending = db.get_pending_action(action_id)
    if not pending or pending["user_id"] != user["id"]:
        return {"ok": False, "error": "Confirmation expired or not found"}
    try:
        # Stored by create_pending_action as an aware UTC isoformat string.
        expired = datetime.fromisoformat(pending["expires_at"]) < datetime.now(timezone.utc)
    except (KeyError, TypeError, ValueError):
        expired = False
    if expired:
        db.delete_pending_action(action_id)
        return {"ok": False, "error": "Confirmation expired or not found"}
    db.delete_pending_action(action_id)
    result = await execute_tool(pending["tool_name"], pending["args"], user, confirmed=True)
    return {"ok": True, "result": result, "summary": pending["summary"]}


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
        "X-Title": "The Hub Assistant",
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


async def chat(user: dict, message: str, channel: str = "web") -> dict:
    text = (message or "").strip()
    if not text:
        raise ValueError("Message is required")

    # Off-web channels (WhatsApp) act immediately and rely on undo, rather than
    # parking money tools behind an in-app Confirm button the user can't reach.
    auto_confirm = channel != "web"

    history = get_history(user["id"], channel)
    history.append({"role": "user", "content": text})

    # Pull the most relevant long-term memory for this question (empty if none).
    memory_block = await mem_svc.recall_block(text)

    base = f"{SYSTEM_PROMPT}{WHATSAPP_NOTE}" if channel == "whatsapp" else SYSTEM_PROMPT
    sections = [base]
    if memory_block:
        sections.append(memory_block)
    sections.append(f"Context JSON:\n{build_context(user)}")
    system = "\n\n".join(sections)
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
                result = await execute_tool(tool_name, tool_args, user, confirmed=auto_confirm)
                actions.append({"tool": tool_name, "args": tool_args, "result": result})
                if result.get("needs_confirmation"):
                    reply = f"I need your confirmation: {result['summary']}. Open the assistant or use Confirm in the app."
                    history.append({"role": "assistant", "content": reply})
                    save_history(user["id"], history, channel)
                    return {
                        "reply": reply,
                        "actions": actions,
                        "data_changed": False,
                        "pending_confirmation": result,
                    }
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
        save_history(user["id"], history, channel)
        _schedule_capture(text, reply)
        return {"reply": reply, "actions": actions, "data_changed": data_changed}

    reply = "I need to break this into smaller steps — what should we do first?"
    history.append({"role": "assistant", "content": reply})
    save_history(user["id"], history, channel)
    return {"reply": reply, "actions": actions, "data_changed": data_changed}
