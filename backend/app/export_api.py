"""Export for analysis: a ZIP of CSV files plus a README, limited to what the user can see in the app."""

import csv
import io
import zipfile
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from . import auth, database, finance, i18n, models, privacy
from .common_api import asset_out, planned_cost_out, shared_transactions, visible_owner
from .wishes_api import visible_wishes, wish_out

router = APIRouter()

README = Path(__file__).with_name("export_readme.md")


def cell(value) -> str:
    """One CSV field: UTC timestamps with Z, dates as YYYY-MM-DD, empty for no value."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def to_csv(header: list[str], rows: list[list]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows([cell(value) for value in row] for row in rows)
    return out.getvalue()


def build_files(db: Session, user: models.User) -> dict[str, str]:
    users = db.query(models.User).all()
    names = {u.id: u.username for u in users}
    visible_ids = {u.id for u in users if privacy.access_level(db, user, u) is not None}
    categories = {c.id: c for c in db.query(models.Category)}
    splits = {s.id: s for s in db.query(models.Split)}
    is_parent = user.role == models.UserRole.PARENT

    def split_name(split_id):
        return splits[split_id].name if split_id in splits else None

    def category_name(category_id):
        return i18n.category_name(categories[category_id]) if category_id in categories else None

    accounts = db.query(models.Account).filter(models.Account.user_id.in_(visible_ids)).all()
    account_by_id = {a.id: a for a in accounts}
    transactions = (
        db.query(models.Transaction)
        .filter(models.Transaction.account_id.in_(account_by_id))
        .order_by(models.Transaction.date)
        .all()
    )
    assets = [a for a in db.query(models.Asset) if is_parent and visible_owner(db, user, a.owner_id, a.split_id)]
    asset_names = {a.id: a.name for a in db.query(models.Asset)}
    costs = [c for c in db.query(models.PlannedCost) if is_parent and visible_owner(db, user, c.owner_id, c.split_id)]

    files = {
        "members.csv": to_csv(
            ["member_id", "name", "role", "has_allowance", "is_active"],
            [[u.id, u.username, u.role, u.has_allowance, u.is_active] for u in users if privacy.can_list_user(user, u)],
        ),
        "categories.csv": to_csv(
            ["category_id", "name", "type"], [[c.id, i18n.category_name(c), c.type] for c in categories.values()]
        ),
        "accounts.csv": to_csv(
            ["account_id", "name", "type", "iban", "owner_id", "owner", "balance"],
            [[a.id, a.name, a.type, a.iban, a.user_id, names.get(a.user_id), a.balance] for a in accounts],
        ),
    }

    transaction_rows = []
    for t in transactions:
        account = account_by_id[t.account_id]
        category = categories.get(t.category_id)
        transaction_rows.append(
            [
                t.id,
                t.date,
                account.id,
                account.name,
                account.user_id,
                names.get(account.user_id),
                t.category_id,
                i18n.category_name(category) if category else None,
                category.type if category else None,
                t.amount,
                t.description,
                t.member_id,
                names.get(t.member_id) if t.member_id else None,
                t.split_id,
                split_name(t.split_id),
                t.asset_id,
                asset_names.get(t.asset_id) if t.asset_id else None,
                t.reference,
                t.asset_purchase,
            ]
        )
    files["transactions.csv"] = to_csv(
        "transaction_id,date,account_id,account,owner_id,owner,category_id,category,category_type,amount,description,"
        "for_member_id,for_member,split_id,split,investment_id,investment,reference,investment_purchase".split(","),
        transaction_rows,
    )

    bank_rows = (
        db.query(models.BankRow)
        .filter(models.BankRow.account_id.in_(account_by_id))
        .order_by(models.BankRow.booked_on, models.BankRow.imported_at)
        .all()
    )
    files["bank_rows.csv"] = to_csv(
        "bank_row_id,account_id,account,booked_on,valuta_on,text,amount,balance,transaction_id,reference".split(","),
        [
            [r.id, r.account_id, account_by_id[r.account_id].name, r.booked_on, r.valuta_on, r.text, r.amount]
            + [r.balance, r.transaction_id, r.reference]
            for r in bank_rows
        ],
    )

    share_rows = []
    if is_parent:
        for t, payer in reversed(shared_transactions(db)):
            amount = abs(t.amount)
            percents = t.split_shares or {}
            amounts = finance.split_amount(amount, percents)
            for member_id, percent in percents.items():
                share_rows.append(
                    [t.id, t.date, payer, names.get(payer), amount, member_id, names.get(member_id), percent]
                    + [amounts.get(member_id)]
                )
    files["shared_expense_shares.csv"] = to_csv(
        ["transaction_id", "date", "payer_id", "payer", "amount", "member_id", "member", "percent", "share"],
        share_rows,
    )

    settlements = db.query(models.Settlement).order_by(models.Settlement.date).all() if is_parent else []
    files["settlements.csv"] = to_csv(
        ["settlement_id", "date", "from_id", "from", "to_id", "to", "amount"],
        [
            [s.id, s.date, s.from_user_id, names.get(s.from_user_id), s.to_user_id, names.get(s.to_user_id), s.amount]
            for s in settlements
        ],
    )

    tags = {t.id: t for t in db.query(models.Tag)}
    files["tags.csv"] = to_csv(
        ["tag_id", "name", "icon"], [[t.id, t.name, t.icon] for t in sorted(tags.values(), key=lambda t: t.name)]
    )
    item_rows = []
    for t in transactions:
        for item in t.items:
            item_rows.append(
                [
                    item.id,
                    t.id,
                    item.position,
                    item.name,
                    item.amount,
                    item.category_id,
                    category_name(item.category_id),
                    item.person_id,
                    names.get(item.person_id) if item.person_id else None,
                    ";".join(sorted(tag.name for tag in item.tags)),
                ]
            )
    files["items.csv"] = to_csv(
        "item_id,transaction_id,position,name,amount,category_id,category,person_id,person,tags".split(","),
        item_rows,
    )

    budgets = db.query(models.Budget).filter(models.Budget.user_id.in_(visible_ids)).all()
    files["budgets.csv"] = to_csv(
        ["budget_id", "owner_id", "owner", "category_id", "category", "tag_id", "tag", "limit", "period"],
        [
            [
                b.id,
                b.user_id,
                names.get(b.user_id),
                b.category_id,
                category_name(b.category_id),
                b.tag_id,
                tags[b.tag_id].name if b.tag_id in tags else None,
                b.limit,
                b.period,
            ]
            for b in budgets
        ],
    )

    files["splits.csv"] = to_csv(
        ["split_id", "name", "member_id", "member", "percent"],
        [
            [s.id, s.name, member_id, names.get(member_id), percent]
            for s in (splits.values() if is_parent else [])
            for member_id, percent in (s.shares or {}).items()
        ],
    )

    investment_rows = []
    for asset in assets:
        out = asset_out(db, asset)
        investment_rows.append(
            [
                asset.id,
                asset.name,
                asset.owner_id,
                names.get(asset.owner_id) if asset.owner_id else None,
                asset.split_id,
                split_name(asset.split_id),
                asset.price,
                asset.purchase_date,
                asset.lifespan_years,
                out["age_years"],
                out["replacement_due"],
                out["monthly_set_aside"],
                finance.cents(out["total_cost"] - asset.price),
                out["total_cost"],
                out["cost_per_year"],
                asset.notes,
                asset.tag_id,
                tags[asset.tag_id].name if asset.tag_id in tags else None,
                asset.archived_on,
                asset.kind,
                asset.lease_rate,
                asset.lease_months,
                asset.lease_final,
                out["lease_end"],
                out["monthly_load"],
            ]
        )
    files["investments.csv"] = to_csv(
        "investment_id,name,owner_id,owner,split_id,split,price,purchase_date,lifespan_years,age_years,replacement_due,"
        "monthly_set_aside,follow_up_costs,total_cost,cost_per_year,notes,tag_id,tag,archived_on,kind,lease_rate,"
        "lease_months,lease_final,lease_end,monthly_load".split(","),
        investment_rows,
    )

    cost_rows = []
    for cost in costs:
        out = planned_cost_out(db, cost)
        cost_rows.append(
            [
                cost.id,
                cost.name,
                cost.category_id,
                category_name(cost.category_id),
                cost.amount,
                cost.frequency,
                cost.due_month,
                out["next_due"],
                out["monthly"],
                cost.owner_id,
                names.get(cost.owner_id) if cost.owner_id else None,
                cost.split_id,
                split_name(cost.split_id),
                cost.notes,
            ]
        )
    files["planned_costs.csv"] = to_csv(
        "planned_cost_id,name,category_id,category,amount,frequency,due_month,next_due,monthly,"
        "owner_id,owner,split_id,split,notes".split(","),
        cost_rows,
    )

    wish_rows = []
    for wish in sorted(visible_wishes(db, user), key=lambda w: (w.split_id or "", w.owner_id or "", w.position)):
        out = wish_out(db, user, wish)
        wish_rows.append(
            [
                wish.id,
                wish.name,
                wish.owner_id,
                names.get(wish.owner_id) if wish.owner_id else None,
                wish.split_id,
                split_name(wish.split_id),
                wish.estimate,
                wish.best_price,
                wish.best_shop,
                wish.best_url,
                wish.best_checked,
                out["price"],
                wish.position,
                wish.family_position,
                wish.bought_on,
                wish.notes,
            ]
        )
    files["wishes.csv"] = to_csv(
        "wish_id,name,owner_id,owner,split_id,split,estimate,best_price,best_shop,best_url,best_checked,price,"
        "position,family_position,bought_on,notes".split(","),
        wish_rows,
    )

    files["README.md"] = README.read_text(encoding="utf-8").format(user=user.username, date=date.today().isoformat())
    return files


@router.get("/export/analysis.zip")
def export_analysis(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in build_files(db, current_user).items():
            archive.writestr(name, content)
    filename = f"budget-analysis-{date.today().isoformat()}.zip"
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
