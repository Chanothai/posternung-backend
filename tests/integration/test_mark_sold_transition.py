"""Integration test: `mark_sold()` → `GET /posters/{id}` ผ่าน HTTP จริง
(ADR-0025 §Verification ข้อ 3/4 · INF-24 AC-5)

🔴 **ต่างจาก `tests/integration/test_poster_api.py`
(`test_get_poster_detail_sold_but_published_returns_200_with_status_sold`)** ตรงที่
เทสนั้นจัดฉาก `status=sold` **ด้วยมือ** ไม่เคยผ่านโค้ดที่ตัดสิน (`test-quality` §3.1 —
เทสที่ตรวจ input ของตัวเอง) เทสในไฟล์นี้ให้ `poster_service.mark_sold()` เป็นคน
สร้างสถานะเองก่อน แล้วค่อยยิง `GET` จริงผ่าน `client` fixture — โค้ดที่ตัดสินใจ
(`mark_sold()`) จึงอยู่บนเส้นทางระหว่าง action กับ assertion จริง ๆ
"""

from datetime import UTC, datetime
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID
from app.services import poster_service

API = "/api/v1/posters"
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
SOLD_AT = datetime(2026, 2, 1, tzinfo=UTC)
REVIEWED_AT = datetime(2026, 2, 1, 9, 0, tzinfo=UTC)


async def _seed_available_poster(session: AsyncSession) -> Poster:
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title="Mark Sold Target",
        price=Decimal("100"),
        condition_grade=PosterCondition.very_good,
        status=PosterStatus.available,
        published_at=PUBLISHED_AT,
    )
    session.add(poster)
    await session.flush()
    await session.commit()
    return poster


async def test_mark_sold_then_get_detail_returns_200_with_sold_state(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """AC-5 ครึ่งหลัง — `mark_sold()` เป็นคนสร้างสถานะ แล้ว `GET` ต้องตอบ 200 +
    `status: sold` + `sold_at` ตรงกับที่ส่งเข้าไป + `published_at` เท่าเดิม (ไม่ออก
    public API เลย — ADR-0013 D5) โดยไม่มีการจัดฉากค่าใน `posters` ด้วยมือ
    """
    poster = await _seed_available_poster(db_session)

    result = await poster_service.mark_sold(
        db_session,
        poster.id,
        sold_at=SOLD_AT,
        reviewed_by="tester",
        reviewed_at=REVIEWED_AT,
        reason="ทดสอบ integration ของ INF-24",
        source="pytest",
    )
    await db_session.commit()

    assert result.status == PosterStatus.sold
    assert result.sold_at == SOLD_AT
    assert result.published_at == PUBLISHED_AT  # ไม่ถูกแตะ (AC-5)

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == str(poster.id)
    assert body["status"] == "sold"
    assert body["sold_at"] == "2026-02-01T00:00:00Z"
    assert "published_at" not in body  # ADR-0013 D5 — ธงภายใน ห้ามออก public API
