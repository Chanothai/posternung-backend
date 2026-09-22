"""SCR-07 สไลซ์ A · A3/A7 — 429 ต้องมี `error_code` ของตัวเองรายเส้น (ADR-0037 D3)

🔴 error_code ต้องมาจาก `error_message=` ที่ตั้งไว้ตอน decorate แต่ละเส้น
(`app/main.py` `rate_limit_handler`) — **ไม่ใช่จากการ `if` บน path string** ซึ่งจะ
เน่าเงียบตอนเพิ่มเส้นที่สาม · ไฟล์นี้ยืนยันทั้งสองเส้นแยกกัน (assertion เชิงลบ:
`/auth/firebase` ต้องยังเป็น `LOGIN_RATE_LIMITED` ไม่ใช่ `RESERVE_RATE_LIMITED`)
พร้อม mutation ที่ต้องตาย: สลับ `error_message=` ของสองเส้นกัน → แดงทั้งสองข้าง

ทั้งสองเทสต้องเปิด rate limiter จริง ⇒ ใช้ fixture `real_client` (`client` ปิด
limiter ไว้เสมอ — ดู docstring ของมันใน conftest.py)
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core import security
from app.core.config import settings
from app.models.user import User
from app.services import auth_service
from tests.conftest import TEST_DATABASE_URL

EMAIL_MARKER = "rate-limit-%@example.test"


@pytest.fixture(autouse=True)
def _firebase_configured():
    """ตั้ง Firebase config ชั่วคราว (แบบเดียวกับ test_auth_api.py) — ไม่ให้เส้น
    `/auth/firebase` ตอบ 503 `OAUTH_PROVIDER_NOT_CONFIGURED` ก่อนถึงจุดนับ rate
    limit จริง ๆ (แม้ 503 ก็ยังถูกนับเหมือนกัน แต่เทสนี้อยากให้พฤติกรรมสมจริง)"""
    orig_pid = settings.FIREBASE_PROJECT_ID
    orig_sa = settings.FIREBASE_SERVICE_ACCOUNT_JSON
    settings.FIREBASE_PROJECT_ID = "posternung"
    settings.FIREBASE_SERVICE_ACCOUNT_JSON = '{"type":"service_account"}'
    with patch("app.services.auth_service._ensure_firebase_app"):
        yield
    settings.FIREBASE_PROJECT_ID = orig_pid
    settings.FIREBASE_SERVICE_ACCOUNT_JSON = orig_sa


async def _cleanup(engine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(delete(User).where(User.email.like(EMAIL_MARKER)))
        await session.commit()


async def _seed_user(engine) -> uuid.UUID:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(
            email=f"rate-limit-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
        )
        session.add(user)
        await session.flush()
        await session.commit()
        return user.id


async def test_reserve_endpoint_429_is_reserve_rate_limited_with_retry_after(
    real_client: AsyncClient,
) -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        await _cleanup(engine)
        user_id = await _seed_user(engine)
        token = security.create_access_token(str(user_id))
        headers = {"Authorization": f"Bearer {token}"}

        statuses = []
        last = None
        # 🔴 อ่านเพดานจาก `settings` ที่เดียว ห้ามเขียนเลขตรงนี้ (มติเจ้าของ 2026-09-15)
        # ยิงเกินเพดานรายนาทีไป 1 ครั้ง ⇒ ครั้งสุดท้ายต้อง 429
        for _ in range(settings.RESERVE_RATE_LIMIT_PER_MINUTE + 1):
            # 🔴 poster_id สุ่มใหม่ทุกครั้งโดยตั้งใจ — พิสูจน์ว่าโควตานับรวมกันข้าม
            # ใบ ไม่ใช่แยก bucket ตาม path จริง (ADR-0037 D6 · scope="reserve_listing"
            # ใน orders.py กันเรื่องนี้ไว้แล้ว — เคยพลาดมาแล้วจริงตอนพัฒนาใบนี้:
            # ไม่ตั้ง scope คงที่ ยิง 25 ครั้งด้วย poster_id สุ่มไม่ติด 429 เลยสักครั้ง)
            url = f"/api/v1/listings/{uuid.uuid4()}/reserve"
            last = await real_client.post(url, headers=headers)
            statuses.append(last.status_code)

        assert 429 in statuses, statuses
        assert last.status_code == 429, (statuses, last.text)
        body = last.json()
        assert body["error_code"] == "RESERVE_RATE_LIMITED"
        assert body["details"] is None
        assert "Retry-After" in last.headers
        int(last.headers["Retry-After"])  # ต้องเป็นเลขที่ parse ได้
    finally:
        await _cleanup(engine)
        await engine.dispose()


async def test_auth_firebase_429_is_still_login_rate_limited(
    real_client: AsyncClient,
) -> None:
    """🔴 assertion เชิงลบ — เส้นนี้ต้อง **ไม่ใช่** `RESERVE_RATE_LIMITED` แม้จะมี
    เส้น reserve เพิ่มเข้ามาในสัญญาเดียวกันแล้ว (ADR-0037 D3) — พิสูจน์ว่า error_code
    ยึดกับ route/limit ของตัวเอง ไม่ได้ปนกัน"""
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        side_effect=auth_service.firebase_auth.InvalidIdTokenError("bad token"),
    ):
        last = None
        for _ in range(6):  # limit ของเส้นนี้คือ 5/minute (app/api/v1/auth.py)
            last = await real_client.post(
                "/api/v1/auth/firebase", json={"id_token": "garbage"}
            )

    assert last.status_code == 429, last.text
    body = last.json()
    assert body["error_code"] == "LOGIN_RATE_LIMITED"
    assert body["error_code"] != "RESERVE_RATE_LIMITED"
    assert "Retry-After" in last.headers
