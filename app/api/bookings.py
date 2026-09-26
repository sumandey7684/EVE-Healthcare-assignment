from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models import Booking, User
from app.schemas.booking import BookingCreateRequest, BookingPublic
from app.services.booking import cancel_booking, create_booking, get_owned_booking, list_bookings

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("", response_model=BookingPublic, status_code=201)
def create_new_booking(
    payload: BookingCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Booking:
    return create_booking(db, current_user, payload)


@router.get("", response_model=list[BookingPublic])
def read_bookings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Booking]:
    return list_bookings(db, current_user)


@router.get("/{booking_id}", response_model=BookingPublic)
def read_booking(
    booking_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Booking:
    return get_owned_booking(db, current_user, booking_id)


@router.post("/{booking_id}/cancel", response_model=BookingPublic)
def cancel_owned_booking(
    booking_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Booking:
    return cancel_booking(db, current_user, booking_id)
