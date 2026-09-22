"""SCR-07 สไลซ์ A · A4 — `RESERVE_RATE_LIMITED` คีย์ด้วย `user_id` ไม่ใช่ IP
(ADR-0037 D6)

ทั้งสองเทสต้องพิสูจน์ว่าคีย์คือ user จริง ๆ ไม่ใช่ IP:
1. สองผู้ใช้บน IP เดียวกัน — **ไม่กินโควตาของกัน**
2. ผู้ใช้เดียวกันข้าม IP — **ยังโดนนับรวมกัน** (โควตาไม่รีเซ็ตตาม IP)

ใช้ `real_client` (เปิด limiter จริง) เป็นฐาน แต่สร้าง `AsyncClient` เพิ่มที่ชี้
`app` ตัวเดียวกันด้วย `ASGITransport(client=(ip, port))` คนละ IP เพื่อจำลองผู้ใช้
จากเครือข่ายต่างกัน — `httpx.ASGITransport` fix ค่า `client` ไว้ตอนสร้าง transport
เท่านั้น (ไม่มีช่องต่อ request) จึงต้องสร้าง transport ใหม่ต่อ "IP" หนึ่งตัว
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core import security
from app.core.config import settings
from app.main import app
from app.models.user import User
from tests.conftest import TEST_DATABASE_URL

EMAIL_MARKER = "rate-key-%@example.test"
# 🔴 อ่านจาก `settings` ที่เดียว ห้ามเขียนเลขตรงนี้ — รอบแรกของ SCR-07 เลขถูกก๊อปไว้
# 3 ที่ และ code-critic จับได้ว่าถ้าปรับอัตราวันหน้า เทสนี้จะเขียวหลอก/แดงเงียบ
LIMIT = settings.RESERVE_RATE_LIMIT_PER_MINUTE


async def _cleanup(engine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(delete(User).where(User.email.like(EMAIL_MARKER)))
        await session.commit()


async def _seed_two_users(engine) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        a = User(
            email=f"rate-key-a-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
        )
        b = User(
            email=f"rate-key-b-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
        )
        session.add_all([a, b])
        await session.flush()
        await session.commit()
        return a.id, b.id


def _client_for_ip(ip: str) -> AsyncClient:
    transport = ASGITransport(app=app, client=(ip, 12345))
    return AsyncClient(transport=transport, base_url="http://test")


async def test_two_different_users_on_the_same_ip_do_not_share_a_quota(
    real_client,
) -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        await _cleanup(engine)
        user_a, user_b = await _seed_two_users(engine)
        headers_a = {
            "Authorization": f"Bearer {security.create_access_token(str(user_a))}"
        }
        headers_b = {
            "Authorization": f"Bearer {security.create_access_token(str(user_b))}"
        }

        # ทั้งคู่ยิงผ่าน real_client ตัวเดียวกัน (IP เดียวกันเป๊ะ — ASGITransport
        # default = 127.0.0.1 คงที่) คนละ token — ยิงคนละ LIMIT ครั้งพอดี ต้องไม่มี
        # ใครโดน 429 เลยสักครั้ง ถ้าคีย์เป็น IP สองคนนี้จะแย่งโควตาเดียวกันแน่ ๆ
        for _ in range(LIMIT):
            res = await real_client.post(
                f"/api/v1/listings/{uuid.uuid4()}/reserve", headers=headers_a
            )
            assert res.status_code != 429, res.text
        for _ in range(LIMIT):
            res = await real_client.post(
                f"/api/v1/listings/{uuid.uuid4()}/reserve", headers=headers_b
            )
            assert res.status_code != 429, res.text
    finally:
        await _cleanup(engine)
        await engine.dispose()


async def test_the_same_user_across_different_ips_still_shares_one_quota(
    real_client,
) -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    client_ip_1 = _client_for_ip("10.0.0.1")
    client_ip_2 = _client_for_ip("10.0.0.2")
    try:
        await _cleanup(engine)
        user_id, _unused = await _seed_two_users(engine)
        headers = {
            "Authorization": f"Bearer {security.create_access_token(str(user_id))}"
        }

        # ครึ่งแรกจาก "IP" หนึ่ง ครึ่งหลัง (เกินโควตา) จาก "IP" อีกอัน — ถ้าคีย์เป็น
        # user_id จริง โควตาต้องรวมกันข้าม IP แล้วต้องโดน 429 ก่อนครบ LIMIT + ครึ่งหลัง
        statuses = []
        for _ in range(LIMIT // 2):
            res = await client_ip_1.post(
                f"/api/v1/listings/{uuid.uuid4()}/reserve", headers=headers
            )
            statuses.append(res.status_code)
        for _ in range(LIMIT):  # เกินโควตาที่เหลือแน่นอนถ้านับรวมกันจริง
            res = await client_ip_2.post(
                f"/api/v1/listings/{uuid.uuid4()}/reserve", headers=headers
            )
            statuses.append(res.status_code)

        assert 429 in statuses, statuses
    finally:
        await client_ip_1.aclose()
        await client_ip_2.aclose()
        await _cleanup(engine)
        await engine.dispose()
