"""Guard event identity before cloud append loads, including producer collisions."""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"


def upgrade() -> None:
    sa.Table(
        "event_identities",
        sa.MetaData(),
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
    ).create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.drop_table("event_identities")
