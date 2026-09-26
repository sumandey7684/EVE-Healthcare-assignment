"""add concurrency constraints

Revision ID: b7c2d4e91a10
Revises: 90eacca781c5
Create Date: 2026-09-27 00:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b7c2d4e91a10"
down_revision: Union[str, Sequence[str], None] = "90eacca781c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_payments_booking_id", "payments", ["booking_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_bookings_active_slot
        ON bookings (user_id, centre_id, test_id, appointment_at)
        WHERE status IN ('PENDING', 'CONFIRMED')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_bookings_active_slot")
    op.drop_constraint("uq_payments_booking_id", "payments", type_="unique")
