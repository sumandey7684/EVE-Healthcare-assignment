from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models import DiagnosticCentre, User
from app.schemas.catalogue import (
    CentreCreateRequest,
    CentrePublic,
    CentreTestCreateRequest,
    CentreTestPublic,
)
from app.services.catalogue import (
    add_test_to_centre,
    create_centre,
    get_centre,
    list_centre_tests,
    list_centres,
)

router = APIRouter(prefix="/centres", tags=["centres"])


@router.get("", response_model=list[CentrePublic])
def read_centres(db: Session = Depends(get_db)) -> list[DiagnosticCentre]:
    return list_centres(db)


@router.post("", response_model=CentrePublic, status_code=201)
def create_new_centre(
    payload: CentreCreateRequest,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiagnosticCentre:
    return create_centre(db, payload)


@router.get("/{centre_id}", response_model=CentrePublic)
def read_centre(centre_id: UUID, db: Session = Depends(get_db)) -> DiagnosticCentre:
    return get_centre(db, centre_id)


@router.get("/{centre_id}/tests", response_model=list[CentreTestPublic])
def read_centre_tests(
    centre_id: UUID,
    db: Session = Depends(get_db),
) -> list[CentreTestPublic]:
    return list_centre_tests(db, centre_id)


@router.post("/{centre_id}/tests", response_model=CentreTestPublic, status_code=201)
def create_centre_test(
    centre_id: UUID,
    payload: CentreTestCreateRequest,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CentreTestPublic:
    return add_test_to_centre(db, centre_id, payload)
