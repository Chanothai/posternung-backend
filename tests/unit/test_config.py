"""Unit test ของ app/core/config.py — MEDIA_BASE_URL validation (ADR-0006).

พิสูจน์ว่า `Settings` fail fast ตอนสร้าง instance เมื่อ MEDIA_BASE_URL ว่างหรือไม่มี
scheme http(s):// — เคสที่ ADR-0006 Alternative 7 ปฏิเสธไว้ (boot ผ่านแล้วส่ง URL
relative/ขยะพังเงียบๆ ออกไปตอน serialize) แก้ code review รอบ 1 ของ
feature/poster-image-storage-key.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings_kwargs(**overrides: str) -> dict:
    """ค่าครบของ field required ทั้งหมดของ Settings ยกเว้นที่ override — ทำให้แต่ละเทส
    โฟกัสเฉพาะ MEDIA_BASE_URL โดยไม่ต้องพึ่ง .env ของเครื่องที่รัน test."""
    kwargs: dict = {
        "ENVIRONMENT": "sit",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/db",
        "JWT_SECRET": "test-secret",
        "MEDIA_BASE_URL": "https://cdn.example.com",
    }
    kwargs.update(overrides)
    return kwargs


def test_empty_media_base_url_fails_to_construct_settings() -> None:
    with pytest.raises(ValidationError, match="MEDIA_BASE_URL"):
        Settings(**_settings_kwargs(MEDIA_BASE_URL=""))


def test_media_base_url_without_scheme_fails_to_construct_settings() -> None:
    with pytest.raises(ValidationError, match="MEDIA_BASE_URL"):
        Settings(**_settings_kwargs(MEDIA_BASE_URL="not a url at all"))


def test_valid_media_base_url_constructs_settings_successfully() -> None:
    s = Settings(**_settings_kwargs(MEDIA_BASE_URL="https://cdn.example.com"))

    assert s.MEDIA_BASE_URL == "https://cdn.example.com"
