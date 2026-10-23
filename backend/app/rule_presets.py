"""Suggested import rules for common Swiss shops and services (bank import, part 1).

A new database gets them with the default categories; an existing family adds them with a button in Settings. They
are ordinary rules afterwards, to change or delete. Each names its category by default_key, so a renamed or deleted
default category simply gets no presets.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import auth, database, i18n, import_rules, models
from .seed import DEFAULT_CATEGORIES, seed_categories

router = APIRouter()

# Created by add() when missing, for families that started before they were defaults
NEW_CATEGORIES = ("SPORT", "COMMUNICATION")

GROUPS = {
    "GROCERIES": ["COOP", "DENNER", "ALDI", "LIDL", "MIGROS", "VOLG"],
    "TRANSPORTATION": [
        "SBB",
        "TAMOIL",
        "AVIA",
        "SOCAR",
        "MIGROL",
        "GARAGE BUCHER",
        # Whole words: both spellings
        "GARAGE WINDLIN",
        "GARAGE WINDLING",
    ],
    "COMMUNICATION": ["SWISSCOM", "SUNRISE", "SALT", "WINGO", "YALLO", "SERAFE"],
    "HEALTHCARE": ["HELSANA", "CSS", "SWICA", "SANITAS", "CONCORDIA", "APOTHEKE"],
    "CLOTHING": [
        "ESPRIT",
        "WE FASHION",
        "JACK & JONES",
        "CELINE",
        "H&M",
        "C&A",
        "ZALANDO",
        "S.OLIVER",
        "TOM TAILOR",
        "MARC O'POLO",
        "STREET ONE",
        "CECIL",
        "CHICOREE",
        "BONITA",
        "MODEVA",
        "NEW YORKER",
        "ANOUK",
        "CALIDA",
        "BLACKOUT",
        "BELLA DONNA",
        "ULLA POPKEN",
        "WORLD OF JEANS",
        "DOSENBACH",
        "OCHSNER SHOES",
    ],
    # The longer texts win over DOSENBACH (Clothing)
    "SPORT": [
        "OCHSNER SPORT",
        "DECATHLON",
        "DOSENBACH SPORT",
        "WERUN",
        "INTERSPORT",
        "SPORT XX",
        "BIKE-IMPORT",
        "PROPAIN",
        "ROSE BIKES",
        "VELO LUSSI",
    ],
}

PRESETS: list[tuple[str, str]] = [(text, key) for key, texts in GROUPS.items() for text in texts]


def ensure_category(db: Session, default_key: str) -> bool:
    """The default category with this key exists afterwards; True if one was created."""
    if db.query(models.Category).filter(models.Category.default_key == default_key).first():
        return False
    names = i18n.DEFAULT_NAMES[default_key]
    same_name = db.query(models.Category).filter(models.Category.name.in_(names.values())).first()
    if same_name:
        same_name.default_key = same_name.default_key or default_key
        db.flush()
        return False
    data = next(c for c in DEFAULT_CATEGORIES if c.get("default_key") == default_key)
    db.add(models.Category(**{**data, "name": names[i18n.default_language()]}, is_global=True))
    db.flush()
    return True


def add(db: Session) -> dict:
    """Add the presets the family doesn't have yet (by text, ignoring case). Commits."""
    categories = sum(ensure_category(db, key) for key in NEW_CATEGORIES)
    by_key = {c.default_key: c for c in db.query(models.Category).filter(models.Category.default_key.isnot(None))}
    existing = {import_rules.key(r.text) for r in import_rules.load(db)}
    rules = 0
    for text, key in PRESETS:
        if key in by_key and import_rules.key(text) not in existing:
            db.add(models.ImportRule(text=text, category_id=by_key[key].id))
            existing.add(import_rules.key(text))
            rules += 1
    db.commit()
    return {"rules": rules, "categories": categories}


def seed_new_database(db: Session) -> None:
    """Default categories for an empty database, and the presets with them; later start-ups add no presets."""
    if seed_categories(db) == len(DEFAULT_CATEGORIES):
        add(db)


@router.post("/import/rules/presets")
def add_presets(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    import_rules.require_parent(current_user)
    return add(db)
