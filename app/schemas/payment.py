from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class WebhookEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=255)
    booking_id: UUID
    status: PaymentStatus
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    payment_id: UUID | None = None

    @field_validator("event_id")
    @classmethod
    def event_id_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("event_id cannot be blank.")
        return cleaned


class WebhookEventResponse(BaseModel):
    status: Literal["processed", "already_processed"]
