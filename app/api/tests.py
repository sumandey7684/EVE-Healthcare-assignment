from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models import DiagnosticTest, User
from app.schemas.catalogue import TestCreateRequest, TestPublic
from app.services.catalogue import create_test, get_test, list_tests

router = APIRouter(prefix="/tests", tags=["tests"])


@router.get("", response_model=list[TestPublic])
def read_tests(db: Session = Depends(get_db)) -> list[DiagnosticTest]:
    return list_tests(db)


@router.post("", response_model=TestPublic, status_code=201)
def create_new_test(
    payload: TestCreateRequest,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiagnosticTest:
    return create_test(db, payload)


@router.get("/{test_id}", response_model=TestPublic)
def read_test(test_id: UUID, db: Session = Depends(get_db)) -> DiagnosticTest:
    return get_test(db, test_id)
