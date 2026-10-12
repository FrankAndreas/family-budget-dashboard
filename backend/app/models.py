import uuid
import enum
from sqlalchemy import Column, String, Boolean, Float, ForeignKey, DateTime, Enum, JSON
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime


class UserRole(str, enum.Enum):
    PARENT = "PARENT"
    CHILD = "CHILD"


class AccountType(str, enum.Enum):
    CASH = "CASH"
    BANK = "BANK"
    SAVINGS = "SAVINGS"


class CategoryType(str, enum.Enum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


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

    accounts = relationship("Account", back_populates="user")
    budgets = relationship("Budget", back_populates="user")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    name = Column(String)
    type = Column(Enum(AccountType), default=AccountType.BANK)
    balance = Column(Float, default=0.0)

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

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String, ForeignKey("accounts.id"))
    category_id = Column(String, ForeignKey("categories.id"))
    amount = Column(Float)
    date = Column(DateTime, default=datetime.utcnow)
    description = Column(String, nullable=True)
    # Optional tag: the dependent child this household expense was for
    member_id = Column(String, ForeignKey("users.id"), nullable=True)

    account = relationship("Account", back_populates="transactions")
    category = relationship("Category")


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    category_id = Column(String, ForeignKey("categories.id"))
    limit = Column(Float)
    period = Column(String, default="MONTHLY")

    user = relationship("User", back_populates="budgets")
    category = relationship("Category")
