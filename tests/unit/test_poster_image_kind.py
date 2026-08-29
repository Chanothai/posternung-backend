"""`poster_images.kind` — ด่านระดับ DB และลำดับกลุ่มของ gallery (ADR-0026 · INF-27)

สามเรื่องที่ล็อกไว้ที่นี่ ทั้งหมดยิงตรงเข้า `db_session` **ไม่ผ่าน service** เพราะกฎ
พวกนี้ต้องกันได้แม้มีคนเขียนเข้าตารางตรง ๆ (หลักเดียวกับ `test_poster_split_constraints.py`
· `scripts/seed/` เขียน `insert()` เข้าตารางตรงจริง ๆ ไม่ผ่าน service เลย):

1. **`ck_poster_images_primary_is_front`** (D3) — `is_primary` บนรูปที่ไม่ใช่ `FRONT`
   เขียนลงไม่ได้ · **นี่คือสิ่งเดียวที่ทำให้ SCR-03 ไม่ต้องเปลี่ยน query** เพราะมันแปลว่า
   `primary_image_url` เป็น `FRONT` เสมอโดยโครงสร้าง ไม่ใช่โดยความบังเอิญ
2. **`ck_poster_images_sort_order_band`** (D5) — เลขนอกแถบของ kind ตัวเองเขียนลงไม่ได้
3. **ลำดับ `FRONT` → `BACK` → `DEFECT` คงที่ไม่ว่าจะ insert ลำดับไหน** — พิสูจน์ด้วย
   **ทุก permutation** ไม่ใช่การสุ่มครั้งเดียว (AC-4)

🔴 **ทำไมต้องมีเทสพวกนี้ทั้งที่มี CHECK อยู่แล้ว** — "constraint ถูกประกาศไว้" กับ
"constraint ถูกบังคับจริงบน DB ที่เทสใช้" เป็นคนละเรื่อง และรอบ INF-25 G1 พิสูจน์แล้วว่า
ช่องว่างนั้นเคยกว้างพอให้ mutation สองตัวรอดมาได้ · เทสที่นี่ยิงของจริงเข้าตาราง
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PosterCondition, PosterImageKind
from app.models.poster import Poster, PosterImage
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID
from app.services.poster_service import get_poster_detail

# ต้อง publish แล้วเท่านั้น `get_poster_detail()` ถึงจะคืนใบนี้ (ADR-0013 D2 —
# `published_only()` คือตัวกรองหน้าร้านตัวเดียว) · เกรดต้องมีคู่กันตาม
# ck_posters_published_requires_condition_grade
PUBLISHED_AT = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
# ck_posters_published_requires_verified (ADR-0027 A3-D1 · INF-38) — ต่างจาก
# PUBLISHED_AT โดยตั้งใจ
VERIFIED_AT = datetime(2026, 8, 16, 6, 0, tzinfo=UTC)


async def _make_poster(session: AsyncSession, title: str = "BLADE RUNNER") -> Poster:
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title=title,
        price=Decimal("500"),
        condition_grade=PosterCondition.very_good,
        published_at=PUBLISHED_AT,
        verified_at=VERIFIED_AT,
    )
    session.add(poster)
    await session.flush()
    return poster


def _image(
    poster: Poster, kind: PosterImageKind, sort_order: int, **over
) -> PosterImage:
    return PosterImage(
        poster_id=poster.id,
        storage_key=f"posters/public/{poster.id}/{uuid.uuid4().hex}.jpg",
        kind=kind,
        sort_order=sort_order,
        **over,
    )


# --- 1. is_primary ต้องเป็น FRONT เท่านั้น (D3 · AC-14 ก) ---


@pytest.mark.parametrize("kind", [PosterImageKind.BACK, PosterImageKind.DEFECT])
async def test_primary_on_a_non_front_image_is_rejected_by_the_database(
    db_session: AsyncSession, kind: PosterImageKind
) -> None:
    """🔴 ตัวฆ่า mutation หลักของ D3 — DROP CHECK ตัวนี้แล้วเทสนี้ต้องแดง

    ยิงตรงเข้า session ไม่ผ่าน service เพราะถ้ากันได้แค่ที่ service แปลว่าสคริปต์ที่เขียน
    `insert()` ตรงเข้าตาราง (ซึ่งมีอยู่จริงหลายตัวใน `scripts/seed/`) ยังทำให้หน้า Home
    โชว์รูปด้านหลังได้เงียบ ๆ
    """
    poster = await _make_poster(db_session)
    band = 100 if kind is PosterImageKind.BACK else 200
    db_session.add(_image(poster, kind, band, is_primary=True))

    with pytest.raises(IntegrityError, match="ck_poster_images_primary_is_front"):
        await db_session.flush()


async def test_primary_on_a_front_image_is_accepted(db_session: AsyncSession) -> None:
    """assertion เชิงบวกคู่กัน — ถ้า CHECK เขียนกลับด้าน เทสข้างบนยังเขียวแต่ตัวนี้แดง"""
    poster = await _make_poster(db_session)
    db_session.add(_image(poster, PosterImageKind.FRONT, 0, is_primary=True))

    await db_session.flush()  # ต้องไม่ raise


async def test_a_non_primary_image_of_any_kind_is_accepted(
    db_session: AsyncSession,
) -> None:
    """CHECK ต้องกันเฉพาะ `is_primary` — ห้ามเผลอกัน `BACK`/`DEFECT` ทั้งหมด"""
    poster = await _make_poster(db_session)
    db_session.add(_image(poster, PosterImageKind.BACK, 100))
    db_session.add(_image(poster, PosterImageKind.DEFECT, 200))

    await db_session.flush()


# --- 2. แถบของ sort_order (D5 · AC-3) ---


@pytest.mark.parametrize(
    ("kind", "sort_order"),
    [
        (PosterImageKind.FRONT, 100),  # ไปอยู่แถบ BACK
        (PosterImageKind.FRONT, 250),  # ไปอยู่แถบ DEFECT
        (PosterImageKind.BACK, 0),  # ไปอยู่แถบ FRONT
        (PosterImageKind.BACK, 200),  # ไปอยู่แถบ DEFECT
        (PosterImageKind.DEFECT, 0),  # ไปอยู่แถบ FRONT
        (PosterImageKind.DEFECT, 150),  # ไปอยู่แถบ BACK
        (PosterImageKind.FRONT, 300),  # เกินทุกแถบที่นิยามไว้
    ],
)
async def test_sort_order_outside_the_band_of_its_kind_is_rejected(
    db_session: AsyncSession, kind: PosterImageKind, sort_order: int
) -> None:
    """🔴 ตัวฆ่า mutation ของ D5 — ถอด CHECK นี้แล้วเทสนี้ต้องแดง

    เคสที่อันตรายที่สุดคือ `(FRONT, 100)`: ถ้าหลุด รูปหน้าใบจะไปโผล่**หลัง**รูปด้านหลัง
    บน SCR-05 โดยไม่มีอะไรฟ้อง เพราะทั้งสองฝั่งเรียงด้วย `sort_order` ล้วน ๆ
    """
    poster = await _make_poster(db_session)
    db_session.add(_image(poster, kind, sort_order))

    with pytest.raises(IntegrityError, match="ck_poster_images_sort_order_band"):
        await db_session.flush()


@pytest.mark.parametrize(
    ("kind", "sort_order"),
    [
        (PosterImageKind.FRONT, 0),
        (PosterImageKind.FRONT, 99),
        (PosterImageKind.BACK, 100),
        (PosterImageKind.BACK, 199),
        (PosterImageKind.DEFECT, 200),
        (PosterImageKind.DEFECT, 299),
    ],
)
async def test_the_edges_of_every_band_are_accepted(
    db_session: AsyncSession, kind: PosterImageKind, sort_order: int
) -> None:
    """ขอบทั้งสองด้านของทุกแถบ — `BETWEEN` ที่เขียนผิดเป็น `<`/`>` จะแดงที่นี่"""
    poster = await _make_poster(db_session)
    db_session.add(_image(poster, kind, sort_order))

    await db_session.flush()


# --- 3. kind บังคับกรอก (D1) ---


async def test_an_image_without_a_kind_is_rejected(db_session: AsyncSession) -> None:
    """ADR-0026 D1 — ไม่มี `server_default` โดยตั้งใจ ลืมใส่ต้องพังตอน insert

    ถ้าวันหนึ่งมีคนเติม `server_default='FRONT'` เข้ามา เทสนี้จะแดง ซึ่งถูกแล้ว:
    ค่า default จะทำให้รูปตำหนิที่ลืมระบุชนิดกลายเป็นรูปหน้าใบเงียบ ๆ
    """
    poster = await _make_poster(db_session)
    db_session.add(
        PosterImage(
            poster_id=poster.id,
            storage_key=f"posters/public/{poster.id}/no-kind.jpg",
            sort_order=0,
        )
    )

    with pytest.raises(IntegrityError, match="kind"):
        await db_session.flush()


# --- 4. ลำดับกลุ่มคงที่ทุก permutation ของการ insert (AC-4) ---


async def test_gallery_order_is_front_then_back_then_defect_for_every_insert_order(
    db_session: AsyncSession,
) -> None:
    """🔴 AC-4 — พิสูจน์ด้วย **ทุก permutation** ไม่ใช่สุ่มครั้งเดียว

    การสุ่มครั้งเดียวจะเขียวได้แม้ตรรกะพังกับลำดับอื่น · 4 รูป = 24 ลำดับ ครบทุกทาง
    · สิ่งที่ทดสอบคือ **ลำดับที่ API คืนจริง** (ผ่าน `get_poster_detail()` ซึ่งเรียงตาม
    `Poster.images.order_by = sort_order`) ไม่ใช่ค่าที่เพิ่งเขียนลงไปเอง
    · ฝั่งแอปเรียงซ้ำด้วย `(isPrimary, sortOrder)` — ผลจึงเหมือนกันเพราะแถบทำให้
    `sort_order` เป็นตัวจัดกลุ่มอยู่แล้ว (นั่นคือเหตุผลที่ D5 เลือกแถบแทน ORDER BY)
    """
    plan = [
        (PosterImageKind.FRONT, 0),
        (PosterImageKind.FRONT, 1),
        (PosterImageKind.BACK, 100),
        (PosterImageKind.DEFECT, 200),
    ]
    expected = [kind for kind, _ in plan]

    for order in itertools.permutations(range(len(plan))):
        poster = await _make_poster(db_session, title=f"ORDER {order}")
        for index in order:
            kind, sort_order = plan[index]
            db_session.add(_image(poster, kind, sort_order))
        await db_session.flush()

        detail = await get_poster_detail(db_session, poster.id)

        assert [image.kind for image in detail.images] == expected, (
            f"ลำดับ insert {order} ให้ผลต่างจากลำดับอื่น — "
            "แถบ sort_order ไม่ได้ทำหน้าที่จัดกลุ่มแล้ว"
        )
        assert [image.sort_order for image in detail.images] == [0, 1, 100, 200]
