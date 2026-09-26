from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.bookings import router as bookings_router
from app.api.centres import router as centres_router
from app.api.health import router as health_router
from app.api.payments import router as payments_router
from app.api.tests import router as tests_router
from app.config import settings
from app.errors import register_error_handlers

app = FastAPI(
    title=settings.app_name,
    description="Diagnostic test booking and simulated payment backend.",
    debug=settings.debug,
)

register_error_handlers(app)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(centres_router)
app.include_router(tests_router)
app.include_router(bookings_router)
app.include_router(payments_router)
