"""Application settings — อ่านค่าจาก .env / environment variables ผ่าน pydantic-settings.

12-Factor: config มาจาก environment เท่านั้น — build ครั้งเดียว deploy ได้ทุก env
ห้ามใส่ค่า default ที่ดูใช้งานได้จริงสำหรับ secret (JWT_SECRET ฯลฯ) — ต้องมาจาก env
"""

from typing import Annotated, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Environment (required — fail fast ถ้าขาด/ผิดค่า) ----
    ENVIRONMENT: Literal["sit", "uat", "production"]

    # ---- Database ----
    DATABASE_URL: str

    # ---- JWT / Auth ----
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_EXPIRE_DAYS: int = 7

    # ---- Reservation (F3 — ยังไม่มี consumer, เตรียม config ไว้) ----
    RESERVE_TTL_MINUTES: int = 15

    # ---- Media (ADR-0006) ----
    # CDN/โดเมนสำหรับประกอบ URL รูปจาก poster_images.storage_key (ดู app/core/media.py)
    # ไม่ใช่ secret แต่ required — misconfig ต้อง fail fast ตอน boot ไม่ใช่ส่ง URL พังเงียบๆ
    MEDIA_BASE_URL: str

    # ---- Firebase / Social login ----
    # Firebase project id ที่ mobile ใช้ (project เดียวทุก env) — เป็น audience ของ
    # Firebase ID token ที่ verify. ไม่ใช่ secret (public) แต่ต้องตั้งให้ตรง; ว่าง →
    # endpoint คืน 503 ชัดเจนแทนที่จะข้าม audience check เงียบๆ (ดู auth_service.google_login)
    FIREBASE_PROJECT_ID: str = ""

    # Firebase service account credential (เนื้อ JSON ทั้งก้อนเป็น string) — **secret**
    # ได้จาก Firebase console → Project settings → Service accounts → Generate new
    # private key. firebase-admin ใช้ init app เพื่อ verify_id_token (+ check_revoked)
    # ว่าง → firebase_login คืน 503 OAUTH_PROVIDER_NOT_CONFIGURED (เหมือน FIREBASE_PROJECT_ID)
    # ใช้เป็น fallback สำหรับ dev/test เป็นหลัก — prod แนะนำ ..._PATH ข้างล่างแทน
    FIREBASE_SERVICE_ACCOUNT_JSON: str = ""

    # Path ไปยังไฟล์ service account JSON (best practice ฝั่ง prod) — key ไม่อยู่ใน env
    # จึงไม่โผล่ใน `docker inspect .Config.Env`/env dump. ตั้งค่านี้คู่กับ read-only
    # bind-mount ไฟล์เข้า container (ดู docker-compose.production.yml). ถ้าตั้ง PATH นี้
    # จะถูกใช้ก่อน ..._JSON เสมอ (ดู auth_service._ensure_firebase_app)
    FIREBASE_SERVICE_ACCOUNT_PATH: str = ""

    # ---- CORS ----
    # NoDecode = ข้าม JSON-decode ของ pydantic-settings ให้ raw string ถึง validator
    # (env var เป็น comma-separated ไม่ใช่ JSON)
    CORS_ORIGINS: Annotated[list[str], NoDecode] = []

    # ---- App ----
    DEBUG: bool = False
    DOCS_ENABLED: bool = True

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        """รองรับค่าจาก env เป็น comma-separated string (pydantic-settings default
        บังคับ JSON สำหรับ list ซึ่งไม่สะดวกกับ env var)."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """Guardrail รวมศูนย์ที่ config layer (ไม่ใช่ if env==production กระจายใน
        business logic): production ห้ามเปิด debug/docs — misconfig ต้อง fail fast
        ตอน boot ไม่ใช่หลุดขึ้น production เงียบๆ."""
        if self.ENVIRONMENT == "production":
            if self.DEBUG:
                raise ValueError("DEBUG ต้องเป็น false ใน production")
            if self.DOCS_ENABLED:
                raise ValueError("DOCS_ENABLED ต้องเป็น false ใน production")
        return self


settings = Settings()
