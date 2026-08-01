"""DB-level constraint test ของ poster_images (ADR-0006) — ยังไม่มี write path ผ่าน API
(BLOCK 5.1 endpoint upload ยังไม่ทำ) จึง insert ตรงผ่าน session เพื่อพิสูจน์ว่า
UNIQUE(storage_key) และ CHECK ทั้งสองตัวถูกบังคับจริงที่ชั้น DB ไม่ใช่แค่คอมเมนต์."""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poster import Poster, PosterImage


async def _make_poster(session: AsyncSession) -> Poster:
    poster = Poster(title="Constraint Test Poster", price=Decimal("100"))
    session.add(poster)
    await session.flush()
    return poster


async def test_duplicate_storage_key_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    poster = await _make_poster(db_session)
    db_session.add(PosterImage(poster_id=poster.id, storage_key="posters/dup/1.jpg"))
    await db_session.flush()
    db_session.add(PosterImage(poster_id=poster.id, storage_key="posters/dup/1.jpg"))

    with pytest.raises(IntegrityError, match="uq_poster_images_storage_key"):
        await db_session.flush()


async def test_non_positive_width_px_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    poster = await _make_poster(db_session)
    db_session.add(
        PosterImage(
            poster_id=poster.id,
            storage_key="posters/bad-width/1.jpg",
            width_px=0,
            height_px=100,
        )
    )

    with pytest.raises(IntegrityError, match="ck_poster_images_dimensions_positive"):
        await db_session.flush()


async def test_width_px_without_height_px_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    poster = await _make_poster(db_session)
    db_session.add(
        PosterImage(
            poster_id=poster.id,
            storage_key="posters/unpaired/1.jpg",
            width_px=100,
            height_px=None,
        )
    )

    with pytest.raises(IntegrityError, match="ck_poster_images_dimensions_paired"):
        await db_session.flush()
