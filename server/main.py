import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from server import database as db

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES = Jinja2Templates(directory=str(STATIC_DIR))

ENV = os.environ.get("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"
DEFAULT_SECRETS = {
    "dev-change-me-in-production",
    "dev-family-portal-change-before-deploy",
    "change-me-to-a-long-random-string",
}
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me-in-production")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8090")
# Secure-cookie flag follows the PUBLIC_URL scheme (not ENV) so a production box
# reached over plain http://IP (no domain yet) still keeps sessions. Set
# PUBLIC_URL=https://… once TLS is in front and cookies become Secure automatically.
HTTPS_ONLY = PUBLIC_URL.startswith("https://")

if IS_PRODUCTION and (not SECRET_KEY or SECRET_KEY in DEFAULT_SECRETS):
    logger.error("Refusing to start: set a strong SECRET_KEY in .env for production")
    sys.exit(1)
elif SECRET_KEY in DEFAULT_SECRETS:
    logger.warning("Using default SECRET_KEY — set SECRET_KEY in .env before deploying")


CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "worker-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if HTTPS_ONLY:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    from server.services import documents as doc_files, media as media_files

    db.init_db()
    doc_files.ensure_upload_dir()
    media_files.ensure_media_dir()
    logger.info("Database initialized at %s", db.DB_PATH)
    yield
    logger.info("Shutdown complete")


app = FastAPI(
    title="The Hub",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=60 * 60 * 24 * 14,
    https_only=HTTPS_ONLY,
    same_site="lax",
)

from server.api.routes import router  # noqa: E402

app.include_router(router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return TEMPLATES.TemplateResponse(request, "index.html")


def main():
    import uvicorn

    host = "127.0.0.1" if IS_PRODUCTION else "0.0.0.0"
    reload = not IS_PRODUCTION
    uvicorn.run("server.main:app", host=host, port=8090, reload=reload)


if __name__ == "__main__":
    main()
