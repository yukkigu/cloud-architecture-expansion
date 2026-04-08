"""initial_schema

Revision ID: 3b51b11cd38e
Revises: 
Create Date: 2026-03-15 23:43:07.157723

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b51b11cd38e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "items",
        sa.Column("item_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("value", sa.Integer, nullable=False),
    )
    # Create an index on the name column for faster lookups
    # Unique index to prevent duplicate item names
    op.create_index("ix_items_name", "items", ["name"], unique=True)

    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(length=36), primary_key=True),
        sa.Column("customer_id", sa.String(length=255), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, unique=True),
    )

    op.create_table(
        "ledger",
        sa.Column("ledger_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.order_id"), nullable=False),
        sa.Column("customer_id", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "idempotency_records",
        sa.Column("idempotency_key", sa.String(length=255), primary_key=True),
        sa.Column("request_body_hash", sa.String(length=255), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("idempotency_records")
    op.drop_table("ledger")
    op.drop_table("orders")
    op.drop_index("ix_items_name", table_name="items")
    op.drop_table("items")
