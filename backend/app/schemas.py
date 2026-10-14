from pydantic import BaseModel, Field, StringConstraints, field_validator
from typing import Annotated, Optional, Literal
from datetime import date, datetime, timezone
from .models import UserRole, AccountType, CategoryType, ShareLevel

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

    class Config:
        from_attributes = True


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


class TokenData(BaseModel):
    user_id: Optional[str] = None


# Account Schemas
class AccountBase(BaseModel):
    name: str
    type: AccountType = AccountType.BANK


class AccountCreate(AccountBase):
    # Set to create the account for someone who shared their finances with EDIT
    user_id: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[AccountType] = None


class Account(AccountBase):
    id: str
    user_id: str
    balance: float

    class Config:
        from_attributes = True


# Category Schemas
class CategoryBase(BaseModel):
    name: str
    type: CategoryType
    icon: Optional[str] = None


class CategoryCreate(CategoryBase):
    pass


class Category(CategoryBase):
    id: str
    is_global: bool = True

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


def _reject_zero(value: Optional[float]) -> Optional[float]:
    # The sign comes from the category, so any sign is accepted (old exports store expenses as negative)
    if value == 0:
        raise ValueError("Amount must not be zero")
    return value


class TransactionCreate(TransactionBase):
    account_id: str
    category_id: str

    _amount_not_zero = field_validator("amount")(_reject_zero)


class TransactionUpdate(BaseModel):
    amount: Optional[float] = None
    description: Optional[str] = None
    date: Optional[datetime] = None
    category_id: Optional[str] = None
    # Send null to remove the tag
    member_id: Optional[str] = None
    # Send null to stop sharing / unlink
    split_id: Optional[str] = None
    asset_id: Optional[str] = None

    _amount_not_zero = field_validator("amount")(_reject_zero)


class Transaction(TransactionBase):
    id: str
    account_id: str
    category_id: str
    date: datetime
    split_shares: Optional[dict[str, int]] = None

    # Dates are stored as naive UTC; mark them as UTC so clients convert to local time correctly
    @field_validator("date")
    @classmethod
    def mark_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    class Config:
        from_attributes = True


# Budget Schemas
class BudgetBase(BaseModel):
    category_id: str
    limit: float
    period: str = "MONTHLY"


class BudgetCreate(BudgetBase):
    limit: float = Field(gt=0)
    period: Literal["MONTHLY", "YEARLY"] = "MONTHLY"
    # Set to create the budget for someone who shared their finances with EDIT
    user_id: Optional[str] = None


class BudgetUpdate(BaseModel):
    limit: Optional[float] = Field(default=None, gt=0)
    period: Optional[Literal["MONTHLY", "YEARLY"]] = None


class Budget(BudgetBase):
    id: str
    user_id: str

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
