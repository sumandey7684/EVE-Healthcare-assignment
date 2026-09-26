from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.diagnostic_centre import DiagnosticCentre
    from app.models.diagnostic_test import DiagnosticTest


class CentreTest(Base):
    """Catalogue row: a test offered by a specific centre, with its current price."""

    __tablename__ = "centre_tests"
    __table_args__ = (
        UniqueConstraint("centre_id", "test_id", name="uq_centre_tests_centre_id_test_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    centre_id: Mapped[UUID] = mapped_column(
        ForeignKey("diagnostic_centres.id"),
        nullable=False,
        index=True,
    )
    test_id: Mapped[UUID] = mapped_column(
        ForeignKey("diagnostic_tests.id"),
        nullable=False,
        index=True,
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    centre: Mapped[DiagnosticCentre] = relationship(back_populates="centre_tests")
    test: Mapped[DiagnosticTest] = relationship(back_populates="centre_tests")
