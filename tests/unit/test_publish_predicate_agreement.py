"""`is_publishable()` (Python) ↔ `ck_posters_published_requires_verified` (SQL) —
หนี้ของ INF-10 → INF-11 → INF-17 → INF-28 ที่ถูกฝากต่อมา 4 รอบ (ADR-0027 D5 · AC-6
ของ `INF-38`) ปิดที่ใบนี้

🔴 **สองฝั่ง "ตรงกัน" ไม่ได้ และไม่ควรตรง** — `is_publishable()` ตัดสินจาก 5 มิติ
(`condition_grade` · `verified_at` · `is_unique` · `count_actual` · `front_image_count`)
ส่วน CHECK รู้จักแค่ 3 คอลัมน์ (`published_at` · `verified_at` · `status`) และ
`PublishReadiness` **ไม่มี `status` เลย** (GATE 1 ของ INF-38 Q1 — เจ้าของเคาะว่า
"ไม่เพิ่ม" เพื่อไม่ให้ semantics fail-closed ของ ADR-0027 D5 มีข้อยกเว้น) ⇒ เทสนี้
**ไม่** assert `python_ok == db_ok` (จะแดงตลอดกาลบนเคส `sold` แล้วต้องยกเว้นทีละเคส
จนไม่เหลือความหมาย — นี่คือกับดักที่ทำให้หนี้นี้ถูกเลื่อนมา 4 รอบ) แต่ล็อกความสัมพันธ์
ที่ถูกต้องแทน — ดู `INF-38-gate1.md` §6

รูปที่ล็อก:
(ก) **Python ต้องไม่หลวมกว่า DB** — ทุกเคสที่ `is_publishable() == True` ⇒ DB ต้องรับ
(ข) **เซตของเคสที่ DB รับแต่ Python ปฏิเสธ ต้อง `==` รายการที่ hard-code ไว้พร้อม
    เหตุผลต่อรายการ** (ไม่ใช่ `⊆`) — วันนี้มีรายการเดียว: `(verified_at=None,
    status=sold)` เหตุผล A3-D1
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster
from app.services import poster_service
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID

CONSTRAINT = "ck_posters_published_requires_verified"
# constraint อื่นที่แถวทดสอบต้อง "ผ่านให้ครบ" ก่อนเสมอในทุกเคส — ถ้าชื่อพวกนี้โผล่มา
# ในข้อความ IntegrityError แปลว่าฮาร์เนสตั้งค่าฟิลด์อื่นไม่ครบ ไม่ใช่ผลของเคสที่ตั้งใจ
# ทดสอบ (INF-38-gate1.md §6 ข้อ 3)
_OTHER_CONSTRAINTS = (
    "ck_posters_published_requires_condition_grade",
    "ck_posters_sold_requires_sold_at",
    "ck_posters_sellable_requires_approved_at",
    "ck_posters_rejected_requires_reason",
)

PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
SOLD_AT = datetime(2026, 2, 1, tzinfo=UTC)
REJECTION_REASON = "ทดสอบ harness — ไม่ใช่การปฏิเสธจริง"

# ฟิลด์ทั้ง 4 ตัวที่เหลือของ `PublishReadiness` ถูกตรึงไว้ที่ค่า "ผ่านด่าน" เสมอ —
# เทสนี้จงใจแปรเฉพาะ `verified_at` เท่านั้น (ฟิลด์อื่นมีเทส fail-closed ต่อฟิลด์ของ
# ตัวเองอยู่แล้วใน tests/unit/test_poster_service.py — ห้ามซ้ำที่นี่)
_READY_KWARGS_GOOD: dict[str, object] = {
    "condition_grade": PosterCondition.very_good,
    "is_unique": True,
    "count_actual": 1,
    "front_image_count": 1,
}

# 🔴 (ข) รายการปิด — เซตของเคสที่ DB "รับ" แต่ Python "ปฏิเสธ" ต้อง `==` ตัวนี้เป๊ะ
# (ไม่ใช่ `⊆`) เพิ่มรายการใหม่ต้องมีเหตุผลกำกับเป็นคีย์คู่กันเสมอ ห้ามเงียบ
_EXPECTED_DB_ACCEPTS_PYTHON_REJECTS: dict[tuple[None, PosterStatus], str] = {
    (None, PosterStatus.sold): (
        "A3-D1 — ใบที่ขายไปแล้วได้รับการยกเว้นไม่ต้องมีลายเซ็น เพราะไม่มีใครหยิบขึ้นมา"
        "ตรวจได้อีก (A3-D2 ห้ามเซ็นย้อนหลัง) แต่ `PublishReadiness` ไม่รู้จัก `status` "
        "เลย (Q1 ของ GATE 1 — เจตนา ไม่ใช่ gap) จึงยังฟันธงว่า NOT_VERIFIED เสมอ"
    ),
}


async def _try_write_published_row(
    db_session: AsyncSession,
    poster_id,
    *,
    verified_at: datetime | None,
    status: PosterStatus,
) -> bool:
    """พยายาม UPDATE แถว baseline ให้ published + verified_at/status ตามเคส

    คืน `True` ถ้า DB รับ (ไม่มี IntegrityError เกิดเลย) · `False` ถ้าถูกปฏิเสธด้วย
    `CONSTRAINT` ของเรา — ปฏิเสธด้วย constraint อื่นถือเป็นบั๊กของฮาร์เนส (assert
    ด้านในทำให้เทส error ไม่ใช่คืน False เงียบ ๆ) · ครอบด้วย savepoint แล้ว rollback
    เสมอไม่ว่าผลจะเป็นอย่างไร เพื่อให้แถว baseline ไม่ขยับข้ามเคส
    (INF-38-gate1.md §6 ข้อ 2 — ป้องกัน IntegrityError ตัวแรก abort ทั้งทรานแซกชัน
    แล้วทุกเคสถัดไปพังเหมือนกันหมด = เขียวหลอก)
    """
    sold_at = SOLD_AT if status is PosterStatus.sold else None
    savepoint = await db_session.begin_nested()
    try:
        await db_session.execute(
            update(Poster.__table__)
            .where(Poster.__table__.c.id == poster_id)
            .values(
                published_at=PUBLISHED_AT,
                verified_at=verified_at,
                status=status.value,
                sold_at=sold_at,
            )
        )
        await db_session.flush()
    except IntegrityError as exc:
        await savepoint.rollback()
        message = str(exc.orig)
        for other in _OTHER_CONSTRAINTS:
            assert other not in message, (
                f"เคส verified_at={verified_at!r}, status={status} ควรชนเฉพาะ "
                f"{CONSTRAINT} แต่ข้อความอ้างถึง {other} ด้วย — ฮาร์เนสตั้งค่าฟิลด์อื่น "
                f"ไม่ครบ: {message[:300]}"
            )
        assert CONSTRAINT in message, (
            f"IntegrityError เกิดที่เคส verified_at={verified_at!r}, status={status} "
            f"แต่ข้อความไม่อ้างถึง {CONSTRAINT} เลย: {message[:300]}"
        )
        return False
    else:
        await savepoint.rollback()
        return True


async def test_python_readiness_never_accepts_what_the_db_check_rejects(
    db_session: AsyncSession,
) -> None:
    """AC-6 — ล็อกความสัมพันธ์ (ก)+(ข) ข้างบน บน cross product ของ `verified_at`
    × `status` ทั้ง enum (ไม่ใช่ 2-3 ตัวที่นึกออก — enum member ใหม่วันหน้าถูกลากเข้า
    เทสนี้เองผ่าน `tuple(PosterStatus)`)
    """
    # (6) constraint ต้องมีอยู่จริงใน pg_constraint ณ เวลารัน — ไม่งั้นทั้งเทสนี้
    # เขียวได้ด้วยความว่างเปล่า (ไม่มีอะไรให้ปฏิเสธเลยเพราะ migration ไม่ได้ถูก apply)
    constraint_exists = await db_session.scalar(
        text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
        {"name": CONSTRAINT},
    )
    assert constraint_exists == 1, (
        f"{CONSTRAINT} ไม่มีอยู่จริงใน pg_constraint ของ DB ที่เทสนี้ใช้ — "
        "migration ยังไม่ถูก apply กับ test DB (ลองรีเซ็ต test DB แล้ว `alembic upgrade head`)"
    )

    # แถว baseline — ยังไม่ publish เลย (ผ่านทุก CHECK ทันที) แล้วให้แต่ละเคสข้างล่าง
    # ยิง UPDATE เข้าไปทับใน savepoint ของตัวเอง
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title="Predicate agreement harness",
        price=Decimal("100"),
        condition_grade=PosterCondition.very_good,
        rejection_reason=REJECTION_REASON,
        status=PosterStatus.draft,
        published_at=None,
        verified_at=None,
    )
    db_session.add(poster)
    await db_session.flush()
    poster_id = poster.id

    verified_options: tuple[datetime | None, ...] = (None, VERIFIED_AT)
    statuses = tuple(PosterStatus)

    both_sides_true_seen = False
    db_accepts_python_rejects: set[tuple[datetime | None, PosterStatus]] = set()
    cases = 0

    for verified_at, status in itertools.product(verified_options, statuses):
        cases += 1
        readiness = poster_service.PublishReadiness(
            **{**_READY_KWARGS_GOOD, "verified_at": verified_at}
        )
        python_ok = poster_service.is_publishable(readiness)
        db_ok = await _try_write_published_row(
            db_session, poster_id, verified_at=verified_at, status=status
        )

        if python_ok and db_ok:
            both_sides_true_seen = True

        # (ก) Python ต้องไม่หลวมกว่า DB — นี่คือข้อที่ฆ่า mutation "ถอด NOT_VERIFIED
        # ออกจาก publish_blockers()" ซึ่งวันนี้ยังไม่มีเทสตัวไหนฆ่าที่ระดับ DB ได้เลย
        assert not (python_ok and not db_ok), (
            "is_publishable() ตอบ True แต่ DB ปฏิเสธที่ verified_at="
            f"{verified_at!r}, status={status} — Python หลวมกว่า DB"
        )

        if db_ok and not python_ok:
            db_accepts_python_rejects.add((verified_at, status))

    # positive control — ต้องมีอย่างน้อยหนึ่งเคสที่ทั้งสองฝั่งตอบ True จริง ไม่งั้น
    # assertion (ก) ข้างบนเขียวได้เพราะไม่เคยมีเคสไหนเข้าเงื่อนไขเลยสักครั้ง
    assert cases == len(verified_options) * len(statuses)
    assert cases > 0
    assert (
        both_sides_true_seen
    ), "ไม่มีเคสไหนที่ทั้งสองฝั่งตอบ True เลย — positive control หายไป"

    # (ข) เซตของความต่างต้อง `==` รายการที่ hard-code ไว้ ไม่ใช่ `⊆` — ถอด
    # `OR status = 'sold'` ออกจาก SQL ⇒ เซตนี้จะว่างเปล่าแทน ⇒ แดงตรงนี้ (AC-5)
    # · ถอด constraint ทั้งก้อน ⇒ เซตนี้จะพองใหญ่กว่าเดิมมาก ⇒ แดงตรงนี้เช่นกัน
    assert db_accepts_python_rejects == set(_EXPECTED_DB_ACCEPTS_PYTHON_REJECTS)
