import uuid
import enum
from typing import Any, Optional

from sqlalchemy import (
    String,
    Boolean,
    ForeignKey,
    DateTime,
    Date,
    Enum,
    Index,
    Integer,
    JSON,
    false,
    func,
    select,
    type_coerce,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship
from .database import Base
from .money import Money
from datetime import date, datetime


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

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=True)
    # None for children added by a parent without their own login
    pin_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.PARENT, nullable=True)
    # Children only: True = own allowance (Jugendlohn) with separate accounts and budgets,
    # False = dependent child whose costs are household expenses tagged with them
    has_allowance: Mapped[bool] = mapped_column(Boolean, default=True, nullable=True)
    # If privacy_enabled is True, other parents cannot see this user's details (mainly for children feature)
    privacy_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=True)
    settings: Mapped[Any] = mapped_column(JSON, default={}, nullable=True)
    # Wrong PINs in a row, and until when logins are refused after too many (see auth.MAX_WRONG_PINS)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Part of every login token; raising it ends all of the user's logins ("log out everywhere", new PIN)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=True)

    accounts: Mapped[list["Account"]] = relationship("Account", back_populates="user")
    budgets: Mapped[list["Budget"]] = relationship("Budget", back_populates="user")

    @property
    def language(self) -> str:
        """Stored in settings; the default language if none was chosen."""
        from . import i18n

        return i18n.user_language(self)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, unique=True, nullable=True)
    type: Mapped[CategoryType] = mapped_column(Enum(CategoryType), nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_global: Mapped[bool] = mapped_column(Boolean, default=True, nullable=True)
    # Fixed key of a category the code needs (seed.TRANSFER, SETTLE_UP, ...); None for ordinary categories
    system_key: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
    # An untouched default category (GROCERIES, ...): shown in each person's language until a parent renames it
    default_key: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_account_date", "account_id", "date"),
        Index("ix_transactions_reference", "reference"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.id"), nullable=True)
    category_id: Mapped[str] = mapped_column(String, ForeignKey("categories.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Money, nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Optional tag: the dependent child this household expense was for
    member_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    # Shared with the other parent(s): the split used, and its percents at booking time
    # (so editing the split later doesn't change past balances)
    split_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("splits.id"), nullable=True)
    split_shares: Mapped[Any] = mapped_column(JSON, nullable=True)
    # The investment this follow-up cost belongs to (repair, service, ...)
    asset_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("assets.id"), nullable=True)
    # The importing tool's own ID for the source (receipt file, hash, ...); recognises repeated imports
    reference: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Reconciliation (bank import, part 2): a receipt is expected (from the import rule that booked it); the bank
    # amount minus the receipt's total when the items were fitted to the bank, and whether a parent accepted it
    receipt_expected: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    difference: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    difference_accepted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    account: Mapped["Account"] = relationship("Account", back_populates="transactions")
    category: Mapped["Category"] = relationship("Category")
    # A receipt's items (issue #56); empty for a plain booking
    items: Mapped[list["TransactionItem"]] = relationship(
        "TransactionItem", order_by="TransactionItem.position", cascade="all, delete-orphan", passive_deletes=True
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment", cascade="all, delete-orphan", passive_deletes=True
    )
    # The bank statement lines that paid it; they stay when the booking is deleted (the database unlinks them)
    bank_rows: Mapped[list["BankRow"]] = relationship(
        "BankRow", back_populates="transaction", order_by="BankRow.booked_on", passive_deletes=True
    )


class BankRow(Base):
    """A line of an imported bank statement (bank import, part 2): the proof that money moved, linked to the booking
    it created or confirmed. Its reference recognises the line when the statement is uploaded again."""

    __tablename__ = "bank_rows"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.id"), index=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    booked_on: Mapped[date] = mapped_column(Date)
    valuta_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # The cleaned booking text (no card numbers or IBANs)
    text: Mapped[str] = mapped_column(String)
    # Signed: negative is money out
    amount: Mapped[float] = mapped_column(Money)
    balance: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    reference: Mapped[str] = mapped_column(String, unique=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction", back_populates="bank_rows")


class Tag(Base):
    """What an item is for (Velo, Garten, ...), across categories; family-wide like categories."""

    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, unique=True)
    icon: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class TransactionItemTag(Base):
    __tablename__ = "transaction_item_tags"

    item_id: Mapped[str] = mapped_column(
        String, ForeignKey("transaction_items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(String, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class TransactionItem(Base):
    """One line of a receipt: what it is (category), what for (tags) and for whom (person)."""

    __tablename__ = "transaction_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id: Mapped[str] = mapped_column(String, ForeignKey("transactions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String)
    # Positive = cost, negative = discount or deposit refund
    amount: Mapped[float] = mapped_column(Money)
    category_id: Mapped[str] = mapped_column(String, ForeignKey("categories.id"))
    person_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    category: Mapped["Category"] = relationship("Category")
    tags: Mapped[list["Tag"]] = relationship("Tag", secondary="transaction_item_tags", order_by="Tag.name")


class Attachment(Base):
    """A stored receipt (photo, PDF, e-mail); pending (no booking yet) until the receipt is booked."""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Who uploaded it; a pending attachment can only be booked by them. Removing that person keeps the receipts
    # on other people's bookings (their own bookings go with them anyway).
    owner_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserEmail(Base):
    """An address a person forwards receipt mails from (issue #57); unique, stored lowercased."""

    __tablename__ = "user_emails"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    address: Mapped[str] = mapped_column(String, unique=True)


class InboxMail(Base):
    """A forwarded receipt mail waiting for a parent to release it (issue #57). Only its headers were read; the raw
    mail is a file in the inbox folder. Booked entries stay (without the file) so the same mail isn't taken twice."""

    __tablename__ = "inbox_mails"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Who forwarded it; removing that person keeps the entry for the other parents
    person_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    from_addr: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    message_id: Mapped[str] = mapped_column(String, unique=True)
    attachment_names: Mapped[Any] = mapped_column(JSON, default=list)
    size: Mapped[int] = mapped_column(Integer)
    # Booking any release of the mail (an attachment with the same content) marks the entry booked
    sha256: Mapped[str] = mapped_column(String, index=True)
    booked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ReceiptRead(Base):
    """One reading of a receipt by the AI, for the hourly limit; rows older than an hour are removed."""

    __tablename__ = "receipt_reads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=True)
    type: Mapped[AccountType] = mapped_column(Enum(AccountType), default=AccountType.BANK, nullable=True)
    # Compact and uppercase (ibans.py); a bank statement's lines find their account by it
    iban: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
    user: Mapped["User"] = relationship("User", back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="account")
    # The sum of its transactions, calculated on every read so it can't drift; summed in cents (exact), and the Money
    # type turns the result back into francs
    balance: Mapped[float] = column_property(
        select(type_coerce(func.coalesce(func.sum(Transaction.amount), 0), Money))
        .where(Transaction.account_id == id)
        .correlate_except(Transaction)
        .scalar_subquery()
    )


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    category_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("categories.id"), nullable=True)
    # A budget is for a category or for a tag (issue #56)
    tag_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("tags.id"), nullable=True)
    limit: Mapped[float] = mapped_column(Money, nullable=True)
    period: Mapped[str] = mapped_column(String, default="MONTHLY", nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="budgets")
    category: Mapped["Category"] = relationship("Category")


class Share(Base):
    """Someone shares their own finances with a parent: read only (VIEW) or managing them (EDIT)."""

    __tablename__ = "shares"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    grantee_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    level: Mapped[ShareLevel] = mapped_column(Enum(ShareLevel), nullable=True)


class Split(Base):
    """A preset ratio for dividing common costs between the parents, e.g. "By income" 70/30."""

    __tablename__ = "splits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, unique=True, nullable=True)
    # {parent user id: whole percent}; sums to 100
    shares: Mapped[Any] = mapped_column(JSON, default={}, nullable=True)


class Asset(Base):
    """A long-lived purchase (TV, fridge, car, bike): planned for replacement, with its follow-up costs."""

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=True)
    price: Mapped[float] = mapped_column(Money, nullable=True)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=True)
    lifespan_years: Mapped[int] = mapped_column(Integer, nullable=True)
    # Exactly one of: a family member (personal) or a split (common)
    owner_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    split_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("splits.id"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class Settlement(Base):
    """One parent paid another to settle the common budget; booked as two transfer transactions."""

    __tablename__ = "settlements"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    from_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    to_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Money, nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    from_transaction_id: Mapped[str] = mapped_column(String, ForeignKey("transactions.id"), nullable=True)
    to_transaction_id: Mapped[str] = mapped_column(String, ForeignKey("transactions.id"), nullable=True)


class Frequency(str, enum.Enum):
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class PlannedCost(Base):
    """A recurring cost planned ahead: a yearly bill (personal or common) or a common monthly cost."""

    __tablename__ = "planned_costs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=True)
    category_id: Mapped[str] = mapped_column(String, ForeignKey("categories.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Money, nullable=True)
    frequency: Mapped[Frequency] = mapped_column(Enum(Frequency), nullable=True)
    due_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Exactly one of: a family member (personal) or a split (common)
    owner_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    split_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("splits.id"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class Wish(Base):
    """Something to buy: in its owner's list (ordered by position) and, if planned together, the family plan."""

    __tablename__ = "wishes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=True)
    estimate: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Exactly one of: a family member (personal) or a split (common)
    owner_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    split_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("splits.id"), nullable=True)
    # The best offer found (typed in after using the search links)
    best_price: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    best_shop: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    best_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    best_checked: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Order in the owner's list and in the family plan (smaller = higher); family_position None = not in the plan
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    family_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bought_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)


class ImportRule(Base):
    """Text in an imported row's description → category; learnt in the import preview, also used by the converter."""

    __tablename__ = "import_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Matched ignoring case, anywhere in the description
    text: Mapped[str] = mapped_column(String, nullable=True)
    category_id: Mapped[str] = mapped_column(String, ForeignKey("categories.id"), nullable=True)
    # Bookings by this rule expect a receipt (matched to bank rows later)
    receipt_expected: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)

    category: Mapped["Category"] = relationship("Category")
