from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


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


class AppointmentUpdate(BaseModel):
    title: Optional[str] = None
    provider: Optional[str] = None
    datetime: Optional[str] = None
    user_id: Optional[str] = None
    category: Optional[str] = None
    location: Optional[str] = None
    reminder_days: Optional[int] = None
    status: Optional[Literal["upcoming", "completed", "cancelled"]] = None


class TripCreate(BaseModel):
    title: str
    status: Literal["idea", "planning", "booked"] = "idea"
    start: Optional[str] = None
    end: Optional[str] = None
    budget: float = 0


class TripUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[Literal["idea", "planning", "booked"]] = None
    start: Optional[str] = None
    end: Optional[str] = None
    budget: Optional[float] = None
    spent: Optional[float] = None


class MemberUpdate(BaseModel):
    name: Optional[str] = None
    colour: Optional[str] = None


class TransferCreate(BaseModel):
    from_account: str
    to_account: str
    amount: float = Field(gt=0)
    date: Optional[str] = None
    note: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    hidden: Optional[bool] = None


class TransactionCategoryUpdate(BaseModel):
    category: str
    learn: bool = True


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


class MediaUpdate(BaseModel):
    title: Optional[str] = None
    caption: Optional[str] = None
    trip_id: Optional[str] = None
    taken_at: Optional[str] = None


class SubscriptionUpdate(BaseModel):
    status: Optional[Literal["detected", "confirmed", "ignored"]] = None
    display_name: Optional[str] = None
    notes: Optional[str] = None
    category: Optional[str] = None


class MaintenanceCreate(BaseModel):
    title: str
    category: str = "general"
    last_service_date: Optional[str] = ""
    next_due_date: Optional[str] = ""
    interval_months: int = 12
    vendor: Optional[str] = ""
    notes: Optional[str] = ""
    warranty_expiry: Optional[str] = ""


class MaintenanceUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    last_service_date: Optional[str] = None
    next_due_date: Optional[str] = None
    interval_months: Optional[int] = None
    vendor: Optional[str] = None
    notes: Optional[str] = None
    warranty_expiry: Optional[str] = None


class SearchQuery(BaseModel):
    query: str


class TripPackingRequest(BaseModel):
    template: Literal["default", "beach", "city", "weekend"] = "default"

