from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    colour: str
    google_connected: bool = False


class EventCreate(BaseModel):
    title: str
    start: str
    end: Optional[str] = None
    all_day: bool = False
    user_id: Optional[str] = None
    location: Optional[str] = None


class BillCreate(BaseModel):
    name: str
    amount: float
    due_day: int = Field(ge=1, le=31)
    recurrence: str = "monthly"
    category: str = "Other"


class TransactionCreate(BaseModel):
    description: str
    amount: float
    category: str
    account_id: Optional[str] = None
    date: Optional[str] = None


class TaskCreate(BaseModel):
    title: str
    assignee_id: Optional[str] = None
    due: Optional[str] = None
    priority: Literal["high", "medium", "low"] = "medium"


class TaskUpdate(BaseModel):
    done: Optional[bool] = None
    title: Optional[str] = None


class AppointmentCreate(BaseModel):
    title: str
    provider: str
    datetime: str
    user_id: Optional[str] = None
    category: str = "health"
    location: Optional[str] = None
    reminder_days: int = 2


class TripCreate(BaseModel):
    title: str
    status: Literal["idea", "planning", "booked"] = "idea"
    start: Optional[str] = None
    end: Optional[str] = None
    budget: float = 0


class DocumentCreate(BaseModel):
    name: str
    category: str = "other"
    expiry: Optional[str] = ""
    notes: Optional[str] = ""


class HolidayIdeaRequest(BaseModel):
    prompt: str
    model: Optional[str] = None


class AssistantChatRequest(BaseModel):
    message: str

