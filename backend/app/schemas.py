from pydantic import BaseModel, Field, field_validator
from typing import Annotated, Optional, Literal
from datetime import datetime, timezone
from .models import UserRole, AccountType, CategoryType

# PINs are exactly 4 digits (same rule as the family-chore app)
Pin = Annotated[str, Field(pattern=r"^\d{4}$")]


# User Schemas
class UserBase(BaseModel):
    username: str
    role: UserRole = UserRole.PARENT
    privacy_enabled: bool = False
    has_allowance: bool = True


class UserCreate(BaseModel):
    # A parent, or a child with own allowance; both log in with a PIN
    username: str = Field(min_length=1)
    pin: Pin
    role: UserRole = UserRole.PARENT


class MemberCreate(BaseModel):
    # A dependent child added by a parent: no login, no own accounts
    username: str


class UserLogin(BaseModel):
    username: str
    pin: str


class User(UserBase):
    id: str
    is_active: bool = True

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    username: Optional[str] = None
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
    pass


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

    _amount_not_zero = field_validator("amount")(_reject_zero)


class Transaction(TransactionBase):
    id: str
    account_id: str
    category_id: str
    date: datetime

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


class BudgetUpdate(BaseModel):
    limit: Optional[float] = Field(default=None, gt=0)
    period: Optional[Literal["MONTHLY", "YEARLY"]] = None


class Budget(BudgetBase):
    id: str
    user_id: str

    class Config:
        from_attributes = True
