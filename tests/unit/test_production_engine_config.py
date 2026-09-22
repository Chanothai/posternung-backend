"""INF-44 AC-8 — production engine ต้อง `echo=False` · `hide_parameters=True` เสมอ

`app/core/database.py:engine` เป็น module-level object ที่ freeze `echo=settings.DEBUG`
ตอน import (ดู `tests/unit/test_sql_echo_hides_bound_parameters.py`) — เทสไฟล์นี้จึง
เรียก `engine_kwargs(settings_obj)` ตรง ๆ กับ `Settings` ที่สร้างขึ้นในเทสเอง
(`_env_file=None` — **ห้ามใช้ `.env` จริงของเครื่อง**) แทนที่จะอ่าน `engine` ตัวจริง
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.database import POOL_KWARGS, engine_kwargs

_REQUIRED = dict(
    DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/poster_nung_test",
    JWT_SECRET="not-a-real-secret-test-only",
    MEDIA_BASE_URL="https://media.example.test",
)


def _settings(**overrides: object) -> Settings:
    kwargs = {**_REQUIRED, **overrides}
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def test_production_settings_disable_echo_and_hide_parameters() -> None:
    settings_obj = _settings(ENVIRONMENT="production", DEBUG=False, DOCS_ENABLED=False)
    kwargs = engine_kwargs(settings_obj)
    assert kwargs["echo"] is False
    assert kwargs["hide_parameters"] is True


def test_engine_kwargs_still_carries_pool_kwargs() -> None:
    """🔴 mutation guard — ถ้าใครลบ `**POOL_KWARGS` ออกจาก `engine_kwargs()` เทสนี้ต้องแดง
    (pool_pre_ping คือด่านของ INF-42 — ห้ามหายไปเงียบ ๆ ตอนแยกฟังก์ชันนี้ออกมา)"""
    settings_obj = _settings(ENVIRONMENT="production", DEBUG=False, DOCS_ENABLED=False)
    kwargs = engine_kwargs(settings_obj)
    for key, value in POOL_KWARGS.items():
        assert kwargs[key] == value


def test_sit_settings_may_enable_echo() -> None:
    """dev/sit ไม่ถูกบังคับ — echo ตาม DEBUG ตรงตัว (ไม่ใช่ hardcode False เสมอ)"""
    settings_obj = _settings(ENVIRONMENT="sit", DEBUG=True)
    kwargs = engine_kwargs(settings_obj)
    assert kwargs["echo"] is True
    assert kwargs["hide_parameters"] is True  # ไม่ผ่อนแม้ dev/sit — SCR-07 F1


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"DEBUG": True, "DOCS_ENABLED": False}, id="debug-true"),
        pytest.param({"DEBUG": False, "DOCS_ENABLED": True}, id="docs-enabled-true"),
    ],
)
def test_production_with_debug_or_docs_enabled_refuses_to_boot(overrides: dict) -> None:
    """🔴 mutation guard ของ `_enforce_production_safety()` — ต้องยัง raise แม้หลังแยก
    `engine_kwargs()` ออกมา (INF-44 AC-8: 'DEBUG=True production ไม่ raise → แดง')"""
    with pytest.raises(ValueError):
        _settings(ENVIRONMENT="production", **overrides)
