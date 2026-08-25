"""FastAPI entrypoint — wiring router, exception handlers, rate-limit middleware.

Behavior ต่าง env ได้เฉพาะจาก config (12-Factor) — docs/CORS มาจาก settings เท่านั้น
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.posters import router as posters_router
from app.core.config import settings
from app.core.database import async_session_maker
from app.core.exceptions import AppError
from app.core.limiter import limiter

# docs เปิด/ปิดจาก config — production (DOCS_ENABLED=false) จะได้ 404 ทุก docs path
_docs_url = "/docs" if settings.DOCS_ENABLED else None
_redoc_url = "/redoc" if settings.DOCS_ENABLED else None
_openapi_url = "/openapi.json" if settings.DOCS_ENABLED else None

app = FastAPI(
    title="Poster Nung API",
    version="0.1.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router, prefix="/api/v1")
app.include_router(posters_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")


@app.get("/health", tags=["Ops"])
async def health() -> dict[str, str]:
    """Liveness — process ยังอยู่ไหม (ไม่แตะ dependency ใดๆ)."""
    return {"status": "ok"}


@app.get("/ready", tags=["Ops"])
async def ready() -> JSONResponse:
    """Readiness — พร้อมรับ traffic ไหม (เช็ค DB ผ่าน SELECT 1)."""
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "checks": {"database": "down"}},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ready", "checks": {"database": "up"}},
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {"field": ".".join(str(p) for p in err["loc"][1:]), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "ข้อมูลที่ส่งมาไม่ถูกต้อง",
            "details": details,
        },
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # เหลือ endpoint เดียวที่ rate-limit แล้ว (/auth/firebase) — ดู api-contract §5
    response = JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error_code": "LOGIN_RATE_LIMITED",
            "message": "พยายามเข้าสู่ระบบบ่อยเกินไป กรุณาลองใหม่ภายหลัง",
            "details": None,
        },
    )
    return limiter._inject_headers(response, request.state.view_rate_limit)
