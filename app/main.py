"""
FastAPI giriş noktası. Çalıştırmak için:
    uvicorn app.main:app --reload
"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app.auth import get_optional_user
from app.config import get_settings
from app.database import init_db
from app.models import User
from app.routers import auth, connect, dashboard, sync
from app.scheduler import start_scheduler

DEV_SECRET_KEY = "gelistirme-ortami-anahtari"

logger = logging.getLogger("creator_pulse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().app_secret_key == DEV_SECRET_KEY:
        logger.warning(
            "APP_SECRET_KEY varsayılan değerde. Oturum çerezleri bu anahtarla imzalanıyor; "
            "yayına almadan önce .env'de rastgele bir değerle değiştir."
        )
    init_db()
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


def build_app(lifespan=None) -> FastAPI:
    """Uygulamayı kurar. Testler lifespan olmadan çağırır, böylece gerçek
    veritabanı ve zamanlayıcı başlamaz."""
    settings = get_settings()
    app = FastAPI(title="Creator Pulse", lifespan=lifespan)
    # Oturum çerezi: imzalı, HttpOnly, SameSite=Lax; HTTPS'te Secure.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret_key,
        session_cookie="creator_pulse_session",
        max_age=settings.session_max_age_days * 24 * 3600,
        same_site="lax",
        https_only=settings.session_cookie_secure,
    )

    app.include_router(auth.router)
    app.include_router(sync.router)
    app.include_router(connect.router)
    app.include_router(dashboard.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def serve_dashboard(user: User | None = Depends(get_optional_user)):
        if user is None:
            return RedirectResponse("/login", status_code=303)
        return FileResponse("templates/dashboard.html")

    return app


app = build_app(lifespan)
