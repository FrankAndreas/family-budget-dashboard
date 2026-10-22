"""A booking's items (issue #56): one receipt, one booking, each line with its own category, tags and person.

The booking's amount is minus the items' sum, and its own category is the one with the largest item total, so code
that only knows bookings (lists, the month check, balances) keeps working.
"""

from collections import defaultdict

from sqlalchemy.orm import Session

from . import messages, models, privacy, schemas
from .crud import to_cents


def apply(db: Session, user: models.User, transaction: models.Transaction, items: list[schemas.ItemIn]) -> None:
    """Check the items and put them on the booking (replacing any it had); sets amount, category and member."""
    categories = {
        c.id: c for c in db.query(models.Category).filter(models.Category.id.in_([i.category_id for i in items]))
    }
    tag_ids = {t for i in items for t in i.tag_ids}
    tags = {t.id: t for t in db.query(models.Tag).filter(models.Tag.id.in_(tag_ids))}
    person_ids = {i.person_id for i in items if i.person_id}
    people = {p.id: p for p in db.query(models.User).filter(models.User.id.in_(person_ids))}

    for item in items:
        category = categories.get(item.category_id)
        if not category or category.type != models.CategoryType.EXPENSE:
            raise messages.api_error(400, "items_need_expense_category")
        if any(t not in tags for t in item.tag_ids):
            raise messages.api_error(400, "item_tag_not_found")
        person = people.get(item.person_id) if item.person_id else None
        if item.person_id and (not person or person.is_active is False or not privacy.can_list_user(user, person)):
            raise messages.api_error(400, "item_person_not_found")
    total = to_cents(sum(to_cents(i.amount) for i in items))
    if total <= 0:
        raise messages.api_error(400, "items_sum_positive")

    # The category with the largest item total; on a tie the one that comes first on the receipt
    per_category: dict[str, float] = defaultdict(float)
    for item in items:
        per_category[item.category_id] += to_cents(item.amount)
    first_seen = {c: n for n, c in reversed(list(enumerate(i.category_id for i in items)))}
    main = max(per_category, key=lambda c: (per_category[c], -first_seen[c]))

    transaction.items = [
        models.TransactionItem(
            position=position,
            name=item.name,
            amount=to_cents(item.amount),
            category_id=item.category_id,
            person_id=item.person_id,
            tags=[tags[t] for t in dict.fromkeys(item.tag_ids)],
        )
        for position, item in enumerate(items)
    ]
    transaction.amount = -total
    transaction.category_id = main
    # The person sits on the items
    transaction.member_id = None
