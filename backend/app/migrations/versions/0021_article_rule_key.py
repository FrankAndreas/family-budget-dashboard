"""One article rule per article name in the database too: article_rules.name_key (the name stripped, ignoring case)."""

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("article_rules") as batch:
        batch.add_column(sa.Column("name_key", sa.String(), nullable=True))
    conn = op.get_bind()
    seen: set[str] = set()
    rows = conn.execute(sa.text("SELECT id, name FROM article_rules ORDER BY created_at, id")).all()
    for rule_id, name in rows:
        key = (name or "").strip().casefold()
        if key in seen:
            # Made twice by two imports at the same moment: the first one stays
            conn.execute(sa.text("DELETE FROM article_rule_tags WHERE rule_id = :id"), {"id": rule_id})
            conn.execute(sa.text("DELETE FROM article_rules WHERE id = :id"), {"id": rule_id})
            continue
        seen.add(key)
        conn.execute(sa.text("UPDATE article_rules SET name_key = :key WHERE id = :id"), {"key": key, "id": rule_id})
    with op.batch_alter_table("article_rules") as batch:
        batch.alter_column("name_key", existing_type=sa.String(), nullable=False)
        batch.create_unique_constraint("uq_article_rules_name_key", ["name_key"])


def downgrade() -> None:
    with op.batch_alter_table("article_rules") as batch:
        batch.drop_constraint("uq_article_rules_name_key", type_="unique")
        batch.drop_column("name_key")
