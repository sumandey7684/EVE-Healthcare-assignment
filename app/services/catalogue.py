from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import AppError
from app.models import CentreTest, DiagnosticCentre, DiagnosticTest
from app.schemas.catalogue import (
    CentreCreateRequest,
    CentreTestCreateRequest,
    CentreTestPublic,
    TestCreateRequest,
)


def list_centres(db: Session) -> list[DiagnosticCentre]:
    return list(db.scalars(select(DiagnosticCentre).order_by(DiagnosticCentre.name)).all())


def get_centre(db: Session, centre_id: UUID) -> DiagnosticCentre:
    centre = db.get(DiagnosticCentre, centre_id)
    if centre is None:
        raise AppError(
            status_code=404,
            code="centre_not_found",
            message="Diagnostic centre was not found.",
        )
    return centre


def create_centre(db: Session, payload: CentreCreateRequest) -> DiagnosticCentre:
    centre = DiagnosticCentre(name=payload.name, location=payload.location)
    db.add(centre)
    db.commit()
    db.refresh(centre)
    return centre


def list_tests(db: Session) -> list[DiagnosticTest]:
    return list(db.scalars(select(DiagnosticTest).order_by(DiagnosticTest.name)).all())


def get_test(db: Session, test_id: UUID) -> DiagnosticTest:
    test = db.get(DiagnosticTest, test_id)
    if test is None:
        raise AppError(
            status_code=404,
            code="test_not_found",
            message="Diagnostic test was not found.",
        )
    return test


def create_test(db: Session, payload: TestCreateRequest) -> DiagnosticTest:
    test = DiagnosticTest(name=payload.name, description=payload.description)
    db.add(test)
    db.commit()
    db.refresh(test)
    return test


def list_centre_tests(db: Session, centre_id: UUID) -> list[CentreTestPublic]:
    centre = db.scalar(
        select(DiagnosticCentre)
        .options(selectinload(DiagnosticCentre.centre_tests).selectinload(CentreTest.test))
        .where(DiagnosticCentre.id == centre_id)
    )
    if centre is None:
        raise AppError(
            status_code=404,
            code="centre_not_found",
            message="Diagnostic centre was not found.",
        )
    offerings = sorted(centre.centre_tests, key=lambda item: item.test.name)
    return [
        CentreTestPublic(
            id=item.test.id,
            name=item.test.name,
            description=item.test.description,
            price=item.price,
        )
        for item in offerings
    ]


def add_test_to_centre(
    db: Session,
    centre_id: UUID,
    payload: CentreTestCreateRequest,
) -> CentreTestPublic:
    get_centre(db, centre_id)
    test = get_test(db, payload.test_id)

    offering = CentreTest(
        centre_id=centre_id,
        test_id=payload.test_id,
        price=payload.price,
    )
    db.add(offering)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            status_code=409,
            code="duplicate_centre_test",
            message="This test is already offered at the selected centre.",
        ) from exc

    return CentreTestPublic(
        id=test.id,
        name=test.name,
        description=test.description,
        price=offering.price,
    )
