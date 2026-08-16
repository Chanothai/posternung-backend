"""DB-level test — BR-06 (ต้องมีรูปก่อน publish) ครอบแถวลูกของเส้นที่ 6 ด้วย (INF-22)

ด่าน `state.image_count == 0` → `blockers` ใน `manual_entry.plan_writes()` มีอยู่แล้ว
ตั้งแต่ INF-11 (ดู `manual_entry.py:762-768`) — งานของ INF-22 ไม่ใช่เขียนด่านใหม่
แต่คือ**พิสูจน์**ว่ากลไกเดิมยังทำงานกับแถวที่เกิดจาก `split_entry.py` ด้วย เพราะแถวลูก
เป็นแถวประเภทใหม่ (สร้างขึ้นตอนรัน ไม่ได้มาจาก `seed_posters.py`) ที่ไม่เคยมีมาก่อน
งานนี้ — ถ้ามันมี attribute หรือ state อะไรที่ต่างจากแถวทั่วไปจนหลุดด่าน ต้องรู้ตอนนี้

ยิงตรงเข้า `_load_state()` + `plan_writes()` ผ่าน `db_session` (ไม่ผ่าน `run()` เต็ม)
เพราะสิ่งที่ต้องพิสูจน์คือ "กลไกที่มีอยู่แล้วยังกันแถวลูกได้จริง" ไม่ใช่พฤติกรรมของ
`split_entry.py` เอง (นั่นคือของ `test_split_entry.py`)
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PosterCondition, PosterImageKind
from app.models.poster import Poster
from scripts.seed.manual_entry import (
    Publish,
    PublishAction,
    _load_state,
    plan_writes,
)
from tests.unit.test_manual_entry import VERIFIED_AT, _row


async def test_a_child_poster_without_photos_is_still_blocked_from_publishing(
    db_session: AsyncSession,
) -> None:
    """แถวลูกที่เพิ่งแตกออกมา (title/price/condition_grade มี แต่ยังไม่มีรูป) —
    ลอง publish=Y ทันที ต้องโดน BR-06 บล็อกเหมือนแถวทั่วไปทุกประการ

    🔴 จำลอง "แถวลูกก่อนถ่ายรูป" โดยไม่ผ่าน `split_entry.py` เลย (สร้าง `Poster`
    ตรง ๆ ผ่าน ORM) — เจตนาคือพิสูจน์ว่า BR-06 อ่านจาก `poster_images` ของแถวนั้น
    ล้วน ๆ ไม่ได้พึ่งพาว่าแถวมาจากไหน (`seed_posters.py` หรือ `split_entry.py`)
    """
    child = Poster(
        title="Child from a split — no photo yet",
        price=Decimal("500"),
        condition_grade=PosterCondition.very_good,
        # ไม่แตะ is_unique/status/needs_review/published_at เลย — ปล่อย server_default
        # ทรงเดียวกับที่ split_entry.py ตั้งใจทำ (D3/D4)
    )
    db_session.add(child)
    await db_session.flush()
    assert child.id is not None

    row = _row(poster_uuid=child.id, values={}, publish=Publish.YES)
    current = await _load_state(db_session, [child.id])

    plans = plan_writes([row], current)

    (plan,) = plans
    assert plan.publish_action is PublishAction.BLOCKED
    assert any("ไม่มีรูปสักรูป" in reason for reason in plan.blockers)


async def test_the_same_child_publishes_once_a_photo_is_attached(
    db_session: AsyncSession,
) -> None:
    """ด้านที่ต้องไม่พัง — เติมรูปให้แถวลูกใบเดียวกันแล้ว publish ต้องผ่าน

    ถ้าไม่มีเทสนี้คู่กัน เทสข้างบนพิสูจน์ได้แค่ว่า "บล็อกได้" ไม่ใช่ว่า "บล็อกเพราะไม่มี
    รูปจริง ๆ" — ด่านที่บล็อกทุกอย่างไม่ว่าจะมีรูปหรือไม่ก็ยังผ่านเทสข้างบนได้เหมือนกัน
    """
    from app.models.poster import PosterImage

    child = Poster(
        title="Child from a split — with photo",
        price=Decimal("500"),
        condition_grade=PosterCondition.very_good,
        # ‹2026-08-16 · ADR-0027 D1› ต้องมีลายเซ็นด้วย ไม่งั้นด่านที่กันคือ NOT_VERIFIED
        # ไม่ใช่ด่านรูป — เทสจะเขียวด้วยเหตุผลที่ไม่ใช่เรื่องที่มันตั้งใจพิสูจน์
        verified_at=VERIFIED_AT,
    )
    db_session.add(child)
    await db_session.flush()

    db_session.add(
        PosterImage(
            poster_id=child.id,
            storage_key=f"posters/public/{child.id}/front.jpg",
            kind=PosterImageKind.FRONT,
            is_primary=True,
        )
    )
    await db_session.flush()

    # `count_actual=1` — ADR-0027 D5 (ไม่ทราบ = ไม่ผ่าน) · แถวที่จะขึ้นร้านจริงต้อง
    # ผ่านทุกด่าน เทสนี้จึงต้องจัดสภาพให้เหลือด่านรูปเป็นตัวแปรเดียว
    row = _row(poster_uuid=child.id, values={}, publish=Publish.YES, count_actual=1)
    current = await _load_state(db_session, [child.id])

    plans = plan_writes([row], current)

    (plan,) = plans
    assert plan.publish_action is PublishAction.APPLY
    assert plan.blockers == ()


async def test_a_poster_with_only_back_and_defect_photos_is_blocked(
    db_session: AsyncSession,
) -> None:
    """🔴 ADR-0026 D8 · INF-27 AC-12 — ด่านอ่าน `kind` จาก DB จริง ไม่ใช่จำนวนรูปรวม

    เดินผ่าน `_load_state()` ตัวจริง (ซึ่งเป็นที่ที่ FILTER ของ `count(...)` อยู่)
    ⇒ ถ้าใครแก้ query ให้กลับไปนับรูปทุกชนิด เทสนี้แดงทันที · การเทสด้วย
    `PosterState` ที่ประกอบเองอย่างเดียวจับจุดนั้นไม่ได้เลย
    """
    from app.models.enums import PosterImageKind
    from app.models.poster import PosterImage

    poster = Poster(
        title="Photographed the damage first",
        price=Decimal("500"),
        condition_grade=PosterCondition.very_good,
    )
    db_session.add(poster)
    await db_session.flush()
    db_session.add(
        PosterImage(
            poster_id=poster.id,
            storage_key=f"posters/public/{poster.id}/10-back.jpg",
            kind=PosterImageKind.BACK,
            sort_order=100,
        )
    )
    db_session.add(
        PosterImage(
            poster_id=poster.id,
            storage_key=f"posters/public/{poster.id}/20-defect.jpg",
            kind=PosterImageKind.DEFECT,
            sort_order=200,
        )
    )
    await db_session.flush()

    current = await _load_state(db_session, [poster.id])
    assert current[poster.id].image_count == 2
    assert current[poster.id].front_image_count == 0

    (plan,) = plan_writes(
        [_row(poster_uuid=poster.id, values={}, publish=Publish.YES)], current
    )

    assert plan.publish_action is PublishAction.BLOCKED
    assert any("kind=FRONT" in reason for reason in plan.blockers)


async def test_the_same_poster_publishes_once_a_front_photo_is_added(
    db_session: AsyncSession,
) -> None:
    """ด้านตรงข้ามคู่กัน — เติมรูป FRONT ให้ใบเดิมแล้วต้องผ่าน"""
    from app.models.enums import PosterImageKind
    from app.models.poster import PosterImage

    poster = Poster(
        title="Damage photos then the front",
        price=Decimal("500"),
        condition_grade=PosterCondition.very_good,
        verified_at=VERIFIED_AT,  # ADR-0027 D1 — ดูคอมเมนต์ในเทสข้างบน
    )
    db_session.add(poster)
    await db_session.flush()
    db_session.add(
        PosterImage(
            poster_id=poster.id,
            storage_key=f"posters/public/{poster.id}/20-defect.jpg",
            kind=PosterImageKind.DEFECT,
            sort_order=200,
        )
    )
    db_session.add(
        PosterImage(
            poster_id=poster.id,
            storage_key=f"posters/public/{poster.id}/00-front.jpg",
            kind=PosterImageKind.FRONT,
            sort_order=0,
        )
    )
    await db_session.flush()

    current = await _load_state(db_session, [poster.id])
    assert current[poster.id].front_image_count == 1

    (plan,) = plan_writes(
        [
            _row(
                poster_uuid=poster.id,
                values={},
                publish=Publish.YES,
                count_actual=1,
            )
        ],
        current,
    )

    assert plan.publish_action is PublishAction.APPLY
    assert not plan.blockers
