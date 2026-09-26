from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_non_blank(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be blank.")
    return cleaned


class CentreCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    location: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        return _require_non_blank(value, "Name")

    @field_validator("location")
    @classmethod
    def location_must_not_be_blank(cls, value: str) -> str:
        return _require_non_blank(value, "Location")


class CentrePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    location: str


class TestCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        return _require_non_blank(value, "Name")

    @field_validator("description")
    @classmethod
    def description_may_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TestPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None


class CentreTestCreateRequest(BaseModel):
    test_id: UUID
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class CentreTestPublic(BaseModel):
    id: UUID
    name: str
    description: str | None
    price: Decimal
