from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class EmailReceiptDraft(BaseModel):
    description: str
    amount: float
    date: Optional[str] = None
    category: Optional[str] = None
    merchant: Optional[str] = None
    message_id: Optional[str] = None
    email_subject: Optional[str] = None


class EmailReceiptImport(BaseModel):
    drafts: List[EmailReceiptDraft]
    account_id: Optional[str] = None


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
    google_account_id: Optional[str] = None  # which connected Google calendar to write to


class EventUpdate(BaseModel):
    title: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    all_day: Optional[bool] = None
    location: Optional[str] = None
    description: Optional[str] = None


class BillCreate(BaseModel):
    name: str
    amount: float
    due_day: int = Field(ge=1, le=31)
    recurrence: str = "monthly"
    category: str = "Other"


class BillUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    due_day: Optional[int] = Field(default=None, ge=1, le=31)
    recurrence: Optional[str] = None
    category: Optional[str] = None


class BillLock(BaseModel):
    subscription_id: Optional[str] = None


class BudgetCreate(BaseModel):
    category: str
    monthly_limit: float = Field(gt=0)


class BudgetUpdate(BaseModel):
    monthly_limit: float = Field(gt=0)


class SavingsGoalCreate(BaseModel):
    name: str
    target: float = Field(gt=0)
    current: float = 0
    colour: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class SavingsGoalUpdate(BaseModel):
    name: Optional[str] = None
    target: Optional[float] = Field(default=None, gt=0)
    current: Optional[float] = Field(default=None, ge=0)
    colour: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class MemoryCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    category: Optional[str] = None
    subject: str = "family"
    pinned: bool = False


class MemoryUpdate(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=500)
    category: Optional[str] = None
    subject: Optional[str] = None
    pinned: Optional[bool] = None


class MemoryImportItem(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    category: Optional[str] = None
    subject: str = "family"


class MemoryImport(BaseModel):
    facts: List[MemoryImportItem]


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
    remind_at: Optional[str] = None


class TaskUpdate(BaseModel):
    done: Optional[bool] = None
    title: Optional[str] = None
    assignee_id: Optional[str] = None
    due: Optional[str] = None
    priority: Optional[Literal["high", "medium", "low"]] = None
    remind_at: Optional[str] = None
    notify: Optional[bool] = None


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
    destination: Optional[str] = None


class TripUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[Literal["idea", "planning", "booked"]] = None
    start: Optional[str] = None
    end: Optional[str] = None
    budget: Optional[float] = None
    spent: Optional[float] = None
    destination: Optional[str] = None


class MemberUpdate(BaseModel):
    name: Optional[str] = None
    colour: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    phone: Optional[str] = None


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
    expiry_date: Optional[str] = None
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


class ChecklistToggleRequest(BaseModel):
    item_id: Optional[str] = None  # checklist row id, or the item's label
    label: Optional[str] = None
    item_type: Literal["checklist", "packing"] = "checklist"


class NotificationPrefsUpdate(BaseModel):
    master_enabled: Optional[bool] = None
    morning_digest: Optional[bool] = None
    evening_digest: Optional[bool] = None
    appointment_reminders: Optional[bool] = None
    bill_reminders: Optional[bool] = None
    renewal_reminders: Optional[bool] = None
    document_expiry_reminders: Optional[bool] = None
    reminder_lead_days: Optional[int] = Field(default=None, ge=0, le=30)
    large_transaction_alerts: Optional[bool] = None
    large_transaction_threshold: Optional[int] = None
    weekly_finance_summary: Optional[bool] = None
    budget_alerts: Optional[bool] = None


class TradespersonCreate(BaseModel):
    name: str = Field(min_length=1)
    trade: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class TradespersonUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    trade: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class PushSubscribe(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


class InboxImportItem(BaseModel):
    kind: Literal["trip", "appointment", "document"]
    title: str
    provider: Optional[str] = None
    datetime: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    destination: Optional[str] = None
    category: Optional[str] = None
    expiry_date: Optional[str] = None
    user_id: Optional[str] = None
    notes: Optional[str] = None
    source_subject: Optional[str] = None


class InboxImport(BaseModel):
    items: List[InboxImportItem]


class ShoppingItemCreate(BaseModel):
    text: str


class AssetCreate(BaseModel):
    name: str
    type: str = "other"
    value: float = 0
    notes: Optional[str] = None


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    value: Optional[float] = None
    notes: Optional[str] = None


class MealPlanUpsert(BaseModel):
    date: str
    title: str
    ingredients: Optional[str] = ""


class ChoreCreate(BaseModel):
    title: str
    cadence: str = "weekly"
    assignee_id: Optional[str] = None
    rotate: bool = True
    next_due: Optional[str] = None


class ChoreUpdate(BaseModel):
    title: Optional[str] = None
    cadence: Optional[str] = None
    assignee_id: Optional[str] = None
    rotate: Optional[bool] = None
    next_due: Optional[str] = None
    last_done: Optional[str] = None


class OccasionCreate(BaseModel):
    title: str
    kind: str = "birthday"
    date: str
    person: Optional[str] = None
    notes: Optional[str] = ""


class OccasionUpdate(BaseModel):
    title: Optional[str] = None
    kind: Optional[str] = None
    date: Optional[str] = None
    person: Optional[str] = None
    notes: Optional[str] = None


class InventoryCreate(BaseModel):
    name: str
    category: str = "other"
    brand: Optional[str] = None
    model: Optional[str] = None
    serial: Optional[str] = None
    purchase_date: Optional[str] = None
    price: Optional[float] = None
    warranty_expiry: Optional[str] = None
    notes: Optional[str] = ""


class InventoryUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    serial: Optional[str] = None
    purchase_date: Optional[str] = None
    price: Optional[float] = None
    warranty_expiry: Optional[str] = None
    notes: Optional[str] = None


class RecipeCreate(BaseModel):
    title: str
    ingredients: Optional[str] = ""
    method: Optional[str] = ""
    tags: Optional[str] = ""
    serves: Optional[int] = None


class RecipeUpdate(BaseModel):
    title: Optional[str] = None
    ingredients: Optional[str] = None
    method: Optional[str] = None
    tags: Optional[str] = None
    serves: Optional[int] = None


class DependentCreate(BaseModel):
    name: str
    kind: str = "child"
    dob: Optional[str] = None
    breed: Optional[str] = None
    notes: Optional[str] = ""


class DependentUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    dob: Optional[str] = None
    breed: Optional[str] = None
    notes: Optional[str] = None


class CareItemCreate(BaseModel):
    dependent_id: str
    title: str
    category: str = "other"
    due_date: Optional[str] = None
    done: Optional[bool] = False
    notes: Optional[str] = ""


class CareItemUpdate(BaseModel):
    dependent_id: Optional[str] = None
    title: Optional[str] = None
    category: Optional[str] = None
    due_date: Optional[str] = None
    done: Optional[bool] = None
    notes: Optional[str] = None


class WishlistCreate(BaseModel):
    title: str
    person: Optional[str] = None
    url: Optional[str] = None
    price: Optional[float] = None
    notes: Optional[str] = ""
    purchased: Optional[bool] = False


class WishlistUpdate(BaseModel):
    title: Optional[str] = None
    person: Optional[str] = None
    url: Optional[str] = None
    price: Optional[float] = None
    notes: Optional[str] = None
    purchased: Optional[bool] = None


class VehicleCreate(BaseModel):
    name: str
    reg: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    mot_due: Optional[str] = None
    tax_due: Optional[str] = None
    insurance_due: Optional[str] = None
    service_due: Optional[str] = None
    notes: Optional[str] = ""


class VehicleUpdate(BaseModel):
    name: Optional[str] = None
    reg: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    mot_due: Optional[str] = None
    tax_due: Optional[str] = None
    insurance_due: Optional[str] = None
    service_due: Optional[str] = None
    notes: Optional[str] = None

