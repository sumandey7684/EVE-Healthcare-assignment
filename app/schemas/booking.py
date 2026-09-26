from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.models import BookingStatus


class BookingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    centre_id: UUID
    test_id: UUID
    appointment_at: datetime

    @field_validator("appointment_at")
    @classmethod
    def appointment_must_be_aware_and_future(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("appointment_at must include a timezone.")
        if value <= datetime.now(timezone.utc):
            raise ValueError("appointment_at must be in the future.")
        return value


class BookingPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    centre_id: UUID
    test_id: UUID
    appointment_at: datetime
    amount: Decimal
    status: BookingStatus
