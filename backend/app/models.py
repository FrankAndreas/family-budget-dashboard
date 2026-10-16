import uuid
import enum
from sqlalchemy import (
    Column,
    String,
    Boolean,
    ForeignKey,
    DateTime,
    Date,
    Enum,
    Index,
    Integer,
    JSON,
    func,
    select,
    type_coerce,
)
from sqlalchemy.orm import column_property, relationship
from .database import Base
from .money import Money
from datetime import datetime


class UserRole(str, enum.Enum):
    PARENT = "PARENT"
    CHILD = "CHILD"


class AccountType(str, enum.Enum):
    CASH = "CASH"
    BANK = "BANK"
    SAVINGS = "SAVINGS"
    # Money in by transfer, out by receipts; should be 0 at the end of each month (month check)
    CLEARING = "CLEARING"


class CategoryType(str, enum.Enum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    # Money moved between parents (settling up): changes balances, counts in neither income nor expenses
    TRANSFER = "TRANSFER"


class ShareLevel(str, enum.Enum):
    # NONE is only stored for children, whose finances parents may view by default
    NONE = "NONE"
    VIEW = "VIEW"
    EDIT = "EDIT"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, index=True)
    # None for children added by a parent without their own login
    pin_hash = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.PARENT)
    # Children only: True = own allowance (Jugendlohn) with separate accounts and budgets,
    # False = dependent child whose costs are household expenses tagged with them
    has_allowance = Column(Boolean, default=True)
    # If privacy_enabled is True, other parents cannot see this user's details (mainly for children feature)
    privacy_enabled = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    settings = Column(JSON, default={})
    # Wrong PINs in a row, and until when logins are refused after too many (see auth.MAX_WRONG_PINS)
    failed_logins = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)

    accounts = relationship("Account", back_populates="user")
    budgets = relationship("Budget", back_populates="user")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    name = Column(String)
    type = Column(Enum(AccountType), default=AccountType.BANK)
    user = relationship("User", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account")


class Category(Base):
    __tablename__ = "categories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True)
    type = Column(Enum(CategoryType))
    icon = Column(String, nullable=True)
    is_global = Column(Boolean, default=True)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_account_date", "account_id", "date"),
        Index("ix_transactions_reference", "reference"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String, ForeignKey("accounts.id"))
    category_id = Column(String, ForeignKey("categories.id"))
    amount = Column(Money)
    date = Column(DateTime, default=datetime.utcnow)
    description = Column(String, nullable=True)
    # Optional tag: the dependent child this household expense was for
    member_id = Column(String, ForeignKey("users.id"), nullable=True)
    # Shared with the other parent(s): the split used, and its percents at booking time
    # (so editing the split later doesn't change past balances)
    split_id = Column(String, ForeignKey("splits.id"), nullable=True)
    split_shares = Column(JSON, nullable=True)
    # The investment this follow-up cost belongs to (repair, service, ...)
    asset_id = Column(String, ForeignKey("assets.id"), nullable=True)
    # The importing tool's own ID for the source (receipt file, hash, ...); recognises repeated imports
    reference = Column(String, nullable=True)

    account = relationship("Account", back_populates="transactions")
    category = relationship("Category")


# An account's balance is the sum of its transactions, calculated on every read, so it can't drift
Account.balance = column_property(
    # Summed in cents (exact); the Money type turns the result back into francs
    select(type_coerce(func.coalesce(func.sum(Transaction.amount), 0), Money))
    .where(Transaction.account_id == Account.id)
    .correlate_except(Transaction)
    .scalar_subquery()
)


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    category_id = Column(String, ForeignKey("categories.id"))
    limit = Column(Money)
    period = Column(String, default="MONTHLY")

    user = relationship("User", back_populates="budgets")
    category = relationship("Category")


class Share(Base):
    """Someone shares their own finances with a parent: read only (VIEW) or managing them (EDIT)."""

    __tablename__ = "shares"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(String, ForeignKey("users.id"))
    grantee_id = Column(String, ForeignKey("users.id"))
    level = Column(Enum(ShareLevel))


class Split(Base):
    """A preset ratio for dividing common costs between the parents, e.g. "By income" 70/30."""

    __tablename__ = "splits"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True)
    # {parent user id: whole percent}; sums to 100
    shares = Column(JSON, default={})


class Asset(Base):
    """A long-lived purchase (TV, fridge, car, bike): planned for replacement, with its follow-up costs."""

    __tablename__ = "assets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    price = Column(Money)
    purchase_date = Column(Date)
    lifespan_years = Column(Integer)
    # Exactly one of: a family member (personal) or a split (common)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    split_id = Column(String, ForeignKey("splits.id"), nullable=True)
    notes = Column(String, nullable=True)


class Settlement(Base):
    """One parent paid another to settle the common budget; booked as two transfer transactions."""

    __tablename__ = "settlements"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    from_user_id = Column(String, ForeignKey("users.id"))
    to_user_id = Column(String, ForeignKey("users.id"))
    amount = Column(Money)
    date = Column(DateTime, default=datetime.utcnow)
    from_transaction_id = Column(String, ForeignKey("transactions.id"))
    to_transaction_id = Column(String, ForeignKey("transactions.id"))


class Frequency(str, enum.Enum):
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class PlannedCost(Base):
    """A recurring cost planned ahead: a yearly bill (personal or common) or a common monthly cost."""

    __tablename__ = "planned_costs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    category_id = Column(String, ForeignKey("categories.id"))
    amount = Column(Money)
    frequency = Column(Enum(Frequency))
    due_month = Column(Integer, nullable=True)
    # Exactly one of: a family member (personal) or a split (common)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    split_id = Column(String, ForeignKey("splits.id"), nullable=True)
    notes = Column(String, nullable=True)


class Wish(Base):
    """Something to buy: in its owner's list (ordered by position) and, if planned together, the family plan."""

    __tablename__ = "wishes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    estimate = Column(Money, nullable=True)
    notes = Column(String, nullable=True)
    # Exactly one of: a family member (personal) or a split (common)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    split_id = Column(String, ForeignKey("splits.id"), nullable=True)
    # The best offer found (typed in after using the search links)
    best_price = Column(Money, nullable=True)
    best_shop = Column(String, nullable=True)
    best_url = Column(String, nullable=True)
    best_checked = Column(Date, nullable=True)
    # Order in the owner's list and in the family plan (smaller = higher); family_position None = not in the plan
    position = Column(Integer, default=0)
    family_position = Column(Integer, nullable=True)
    bought_on = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ImportRule(Base):
    """Text in an imported row's description → category; learnt in the import preview, also used by the converter."""

    __tablename__ = "import_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Matched ignoring case, anywhere in the description
    text = Column(String)
    category_id = Column(String, ForeignKey("categories.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    category = relationship("Category")
