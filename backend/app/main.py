import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import actions, auth, connections, dashboard, findings, scans, settings
from app.config import get_settings
from app.core.errors import install_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER, CSRF_VALUE = "x-requested-with", "ec2opt"


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="EC2 Optimizer API", version="1.0.0",
                  docs_url=None if s.is_production else "/docs",
                  openapi_url=None if s.is_production else "/openapi.json")
    install_error_handlers(app)

    @app.middleware("http")
    async def csrf_and_headers(request: Request, call_next):
        # CSRF: state-changing API calls must carry X-Requested-With: ec2opt (a cross-site form can't set it)
        if (request.method not in SAFE_METHODS and request.url.path.startswith("/api/")
                and request.headers.get(CSRF_HEADER) != CSRF_VALUE):
            return JSONResponse({"error": {"code": "CSRF", "message": "Missing X-Requested-With header"}},
                                status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if not request.url.path.startswith("/docs"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return response

    app.add_middleware(CORSMiddleware, allow_origins=[s.frontend_origin], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["Content-Type", "X-Requested-With"])

    for r in (auth.router, connections.router, scans.router, findings.router, actions.router, dashboard.router,
              settings.router):
        app.include_router(r, prefix="/api/v1")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
