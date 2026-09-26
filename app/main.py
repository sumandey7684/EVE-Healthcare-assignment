from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
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
