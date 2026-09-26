"""Create a small development catalogue. Safe to run more than once."""

from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import CentreTest, DiagnosticCentre, DiagnosticTest

CENTRES = (
    {"name": "City Diagnostics", "location": "Bengaluru"},
    {"name": "Metro Health Lab", "location": "Hyderabad"},
)

TESTS = (
    {"name": "CBC", "description": "Complete Blood Count"},
    {"name": "Lipid Panel", "description": "Cholesterol and triglycerides"},
    {"name": "Thyroid Profile", "description": "TSH, T3 and T4"},
)

OFFERINGS = (
    ("City Diagnostics", "CBC", Decimal("450.00")),
    ("City Diagnostics", "Lipid Panel", Decimal("899.00")),
    ("Metro Health Lab", "CBC", Decimal("399.00")),
    ("Metro Health Lab", "Thyroid Profile", Decimal("650.00")),
)


def _get_or_create_centre(db, name: str, location: str) -> DiagnosticCentre:
    centre = db.scalar(select(DiagnosticCentre).where(DiagnosticCentre.name == name))
    if centre is None:
        centre = DiagnosticCentre(name=name, location=location)
        db.add(centre)
        db.flush()
    return centre


def _get_or_create_test(db, name: str, description: str) -> DiagnosticTest:
    test = db.scalar(select(DiagnosticTest).where(DiagnosticTest.name == name))
    if test is None:
        test = DiagnosticTest(name=name, description=description)
        db.add(test)
        db.flush()
    return test


def seed() -> None:
    db = SessionLocal()
    try:
        centres = {
            item["name"]: _get_or_create_centre(db, item["name"], item["location"])
            for item in CENTRES
        }
        tests = {
            item["name"]: _get_or_create_test(db, item["name"], item["description"])
            for item in TESTS
        }

        for centre_name, test_name, price in OFFERINGS:
            exists = db.scalar(
                select(CentreTest).where(
                    CentreTest.centre_id == centres[centre_name].id,
                    CentreTest.test_id == tests[test_name].id,
                )
            )
            if exists is None:
                db.add(
                    CentreTest(
                        centre_id=centres[centre_name].id,
                        test_id=tests[test_name].id,
                        price=price,
                    )
                )

        db.commit()
        print("Seeded 2 centres, 3 tests, and centre-specific prices.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
