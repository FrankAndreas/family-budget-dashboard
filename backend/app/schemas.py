from pydantic import BaseModel, Field, StringConstraints, computed_field, field_validator, model_validator
from typing import Annotated, Optional, Literal
from datetime import date, datetime, timezone
from .models import UserRole, AccountType, CategoryType, ShareLevel
from . import i18n

# PINs are exactly 4 digits (same rule as the family-chore app)
Pin = Annotated[str, Field(pattern=r"^\d{4}$")]

# Names people log in with: surrounding spaces are dropped, and they can't be empty
Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


# User Schemas
class UserBase(BaseModel):
    username: str
    role: UserRole = UserRole.PARENT
    privacy_enabled: bool = False
    has_allowance: bool = True


class UserCreate(BaseModel):
    # A parent, or a child with own allowance; both log in with a PIN
    username: Username
    pin: Pin
    role: UserRole = UserRole.PARENT


class MemberCreate(BaseModel):
    # A dependent child added by a parent: no login, no own accounts
    username: Username


class UserLogin(BaseModel):
    username: str
    pin: str


class User(UserBase):
    id: str
    is_active: bool = True
    # Stored in users.settings; the default language if none was chosen (models.User.language)
    language: str = "de"

    class Config:
        from_attributes = True


class LanguageUpdate(BaseModel):
    language: Literal["de", "en"]


class UserUpdate(BaseModel):
    username: Optional[Username] = None
    role: Optional[UserRole] = None
    privacy_enabled: Optional[bool] = None
    pin: Optional[Pin] = None
    is_active: Optional[bool] = None
    has_allowance: Optional[bool] = None


class Token(BaseModel):
    access_token: str
    token_type: str
    # Wrong PINs entered for this name since the last login
    wrong_pins: int = 0


class TokenData(BaseModel):
    user_id: Optional[str] = None


# Account Schemas
class AccountBase(BaseModel):
    name: str
    type: AccountType = AccountType.BANK
    # Compact on the way out; any spacing on the way in, "" removes it
    iban: Optional[str] = None


class AccountCreate(AccountBase):
    # Set to create the account for someone who shared their finances with EDIT
    user_id: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[AccountType] = None
    iban: Optional[str] = None


class Account(AccountBase):
    id: str
    user_id: str
    balance: float
    # Reconciliation (reconcile.summary): open bookings and bank lines, and the sum of the unconfirmed bookings
    open_points: int = 0
    not_confirmed: float = 0

    class Config:
        from_attributes = True


# Category Schemas
class CategoryBase(BaseModel):
    name: str
    type: CategoryType
    icon: Optional[str] = None


CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class CategoryCreate(CategoryBase):
    name: CategoryName
    icon: Optional[str] = Field(default=None, max_length=8)


class CategoryUpdate(BaseModel):
    name: Optional[CategoryName] = None
    type: Optional[CategoryType] = None
    icon: Optional[str] = Field(default=None, max_length=8)


class TagCreate(BaseModel):
    name: CategoryName
    icon: Optional[str] = Field(default=None, max_length=8)


class TagUpdate(BaseModel):
    name: Optional[CategoryName] = None
    icon: Optional[str] = Field(default=None, max_length=8)


class EmailCreate(BaseModel):
    address: str = Field(max_length=254)


class Email(BaseModel):
    id: str
    user_id: str
    address: str

    class Config:
        from_attributes = True


class Tag(BaseModel):
    id: str
    name: str
    icon: Optional[str] = None

    class Config:
        from_attributes = True


class Category(CategoryBase):
    id: str
    is_global: bool = True
    # Fixed key of a category the app needs (TRANSFER, SETTLE_UP, ...); None for ordinary ones
    system_key: Optional[str] = None
    # Set while a default category (GROCERIES, ...) still has its default name
    default_key: Optional[str] = None

    @model_validator(mode="after")
    def name_in_language(self) -> "Category":
        # The app's own and the untouched default categories are shown in the request's language
        self.name = i18n.system_name(self.system_key or self.default_key, self.name)
        return self

    class Config:
        from_attributes = True


# Transaction Schemas
class TransactionBase(BaseModel):
    amount: float
    description: Optional[str] = None
    date: Optional[datetime] = None
    member_id: Optional[str] = None
    split_id: Optional[str] = None
    asset_id: Optional[str] = None
    reference: Optional[str] = Field(default=None, max_length=200)


def _reject_zero(value: Optional[float]) -> Optional[float]:
    # The sign comes from the category, so any sign is accepted (old exports store expenses as negative)
    if value == 0:
        raise ValueError("Amount must not be zero")
    return value


# A receipt's line (issue #56): what it is (category), what for (tags), for whom (person)
ItemName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
MAX_ITEMS = 100


class ItemIn(BaseModel):
    name: ItemName
    # Positive = cost, 0 = free, negative = discount or deposit refund; only the receipt's total must be above 0
    amount: float
    category_id: str
    person_id: Optional[str] = None
    tag_ids: list[str] = []


class ItemOut(BaseModel):
    id: str
    position: int
    name: str
    amount: float
    category_id: str
    person_id: Optional[str] = None
    tags: list[Tag] = Field(default=[], exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tag_ids(self) -> list[str]:
        return [t.id for t in self.tags]

    class Config:
        from_attributes = True


class AttachmentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size: int

    class Config:
        from_attributes = True


class TransactionCreate(TransactionBase):
    account_id: str
    # The person's own pending uploads (e.g. the receipt just read) to keep with the booking
    attachment_ids: list[str] = []
    # Required for a plain booking; with items, both come from the items
    amount: Optional[float] = None  # type: ignore[assignment]
    category_id: Optional[str] = None
    items: Optional[list[ItemIn]] = Field(default=None, max_length=MAX_ITEMS)

    _amount_not_zero = field_validator("amount")(_reject_zero)

    @model_validator(mode="after")
    def plain_needs_amount_and_category(self) -> "TransactionCreate":
        if self.items is None and (self.amount is None or self.category_id is None):
            raise ValueError("amount and category_id are required without items")
        return self


class TransactionUpdate(BaseModel):
    # Reconciliation flags; can change on any booking
    receipt_expected: Optional[bool] = None
    difference_accepted: Optional[bool] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    date: Optional[datetime] = None
    category_id: Optional[str] = None
    # Send null to remove the tag
    member_id: Optional[str] = None
    # Send null to stop sharing / unlink
    split_id: Optional[str] = None
    asset_id: Optional[str] = None
    # Replaces the items; [] turns a receipt back into a plain booking (then amount and category_id are needed)
    items: Optional[list[ItemIn]] = Field(default=None, max_length=MAX_ITEMS)
    # More of the person's pending uploads to keep with the booking
    attachment_ids: list[str] = []

    _amount_not_zero = field_validator("amount")(_reject_zero)


class BankRowOut(BaseModel):
    id: str
    booked_on: date
    valuta_on: Optional[date] = None
    text: str
    amount: float

    class Config:
        from_attributes = True


class Transaction(TransactionBase):
    id: str
    account_id: str
    category_id: str
    date: datetime
    split_shares: Optional[dict[str, int]] = None
    items: list[ItemOut] = []
    attachments: list[AttachmentOut] = []
    # Reconciliation (bank import, part 2): the statement lines that paid it, and its state (reconcile.state)
    bank_rows: list[BankRowOut] = []
    receipt_expected: bool = False
    difference: Optional[float] = None
    difference_accepted: bool = False
    state: Optional[dict] = None

    # Dates are stored as naive UTC; mark them as UTC so clients convert to local time correctly
    @field_validator("date")
    @classmethod
    def mark_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    class Config:
        from_attributes = True


# Budget Schemas
class BudgetBase(BaseModel):
    # A budget is for a category or for a tag (issue #56): exactly one of the two
    category_id: Optional[str] = None
    tag_id: Optional[str] = None
    limit: float
    period: str = "MONTHLY"


class BudgetCreate(BudgetBase):
    limit: float = Field(gt=0)
    period: Literal["MONTHLY", "YEARLY"] = "MONTHLY"
    # Set to create the budget for someone who shared their finances with EDIT
    user_id: Optional[str] = None

    @model_validator(mode="after")
    def category_or_tag(self) -> "BudgetCreate":
        if (self.category_id is None) == (self.tag_id is None):
            raise ValueError("a budget is for either a category or a tag")
        return self


class BudgetUpdate(BaseModel):
    limit: Optional[float] = Field(default=None, gt=0)
    period: Optional[Literal["MONTHLY", "YEARLY"]] = None


class Budget(BudgetBase):
    id: str
    user_id: str
    # Spent in the current Swiss month (MONTHLY) or year (YEARLY), and as a percentage of the limit
    spent: float = 0.0
    percentage: float = 0.0

    class Config:
        from_attributes = True


# Share Schemas
class ShareSet(BaseModel):
    level: Literal["NONE", "VIEW", "EDIT"]


class Share(BaseModel):
    owner_id: str
    grantee_id: str
    level: ShareLevel

    class Config:
        from_attributes = True


# Split Schemas
Percent = Annotated[int, Field(ge=0, le=100)]


class SplitIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    shares: dict[str, Percent]


class Split(SplitIn):
    id: str

    class Config:
        from_attributes = True


class Balance(BaseModel):
    user_id: str
    # Positive: the other parents owe this parent; negative: this parent owes
    amount: float


class SharedExpense(BaseModel):
    transaction_id: str
    date: datetime
    description: Optional[str]
    amount: float
    payer_id: str
    split_name: Optional[str]
    shares: dict[str, float]


class SettlementCreate(BaseModel):
    from_user_id: str
    to_user_id: str
    amount: float = Field(gt=0)
    from_account_id: str
    to_account_id: str
    date: Optional[datetime] = None


class Settlement(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    amount: float
    date: datetime

    class Config:
        from_attributes = True


# Planned cost Schemas
class PlannedCostIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    category_id: str
    amount: float = Field(gt=0)
    frequency: Literal["MONTHLY", "YEARLY"]
    due_month: Optional[int] = Field(default=None, ge=1, le=12)
    owner_id: Optional[str] = None
    split_id: Optional[str] = None
    notes: Optional[str] = None


class PlannedCost(PlannedCostIn):
    id: str
    monthly: float
    next_due: Optional[date]
    due_soon: bool
    # Monthly amount per person
    shares: dict[str, float]


class OverviewItem(BaseModel):
    kind: Literal["planned", "asset"]
    id: str
    name: str
    monthly: float
    shares: dict[str, float]


class Overview(BaseModel):
    items: list[OverviewItem]
    totals: dict[str, float]


# Asset Schemas
class AssetIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    price: float = Field(gt=0)
    purchase_date: date
    lifespan_years: int = Field(ge=1, le=100)
    owner_id: Optional[str] = None
    split_id: Optional[str] = None
    notes: Optional[str] = None


class Asset(AssetIn):
    id: str
    age_years: float
    # Purchase date in the future: not bought yet
    planned: bool = False
    replacement_due: date
    is_due: bool
    monthly_set_aside: float
    total_cost: float
    cost_per_year: float
    # Monthly set-aside per person
    shares: dict[str, float]


class AssetDetail(Asset):
    expenses: list[Transaction]


# Removing a family member: where each of their investments and bills goes
class OwnedItem(BaseModel):
    kind: Literal["asset", "planned"]
    id: str
    name: str


class ItemDecision(BaseModel):
    kind: Literal["asset", "planned"]
    id: str
    # "owner:<user id>", "split:<split id>" or "delete"
    to: str


class MemberRemoval(BaseModel):
    items: list[ItemDecision] = []


# Wish Schemas
class WishIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    estimate: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = Field(default=None, max_length=1000)
    owner_id: Optional[str] = None
    split_id: Optional[str] = None
    best_price: Optional[float] = Field(default=None, ge=0)
    best_shop: Optional[str] = Field(default=None, max_length=120)
    best_url: Optional[str] = Field(default=None, max_length=1000, pattern=r"^https?://")
    best_checked: Optional[date] = None


class Wish(WishIn):
    id: str
    position: int
    family_position: Optional[int]
    bought_on: Optional[date]
    # best_price, else estimate
    price: Optional[float]
    can_edit: bool
    in_family_plan: bool


class FamilyPlanRow(Wish):
    running_total: float


class WishMove(BaseModel):
    list: Literal["own", "family"]
    direction: Literal["up", "down"]


class WishBought(BaseModel):
    bought_on: Optional[date] = None
