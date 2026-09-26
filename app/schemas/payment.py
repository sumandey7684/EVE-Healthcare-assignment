from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import PaymentStatus


class PaymentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: UUID
    result: PaymentStatus


class PaymentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    booking_id: UUID
    amount: Decimal
    status: PaymentStatus
