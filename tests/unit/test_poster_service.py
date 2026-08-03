"""Unit test ของ poster_service — ครอบ filter/pagination logic + not-found."""

import logging
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PosterNotFound
from app.core.media import build_media_url
from app.models.enums import (
    PosterCondition,
    PosterStatus,
    PosterType,
    ReleaseRegion,
    RestorationStatus,
    SizeFormat,
)
from app.models.poster import Poster, PosterImage
from app.schemas.poster import PosterFilterParams
from app.services import poster_service


async def _make_poster(
    session: AsyncSession,
    *,
    title: str,
    price: str,
    status: PosterStatus = PosterStatus.available,
    condition_grade: PosterCondition | None = None,
    era_decade: int | None = None,
    with_primary_image: bool = False,
) -> Poster:
    poster = Poster(
        title=title,
        price=Decimal(price),
        status=status,
        condition_grade=condition_grade,
        era_decade=era_decade,
    )
    session.add(poster)
    await session.flush()

    if with_primary_image:
        session.add(
            PosterImage(
                poster_id=poster.id,
                storage_key=f"posters/public/{poster.id}/01-test.jpg",
                is_primary=True,
            )
        )
        await session.flush()
        await session.refresh(poster, attribute_names=["images"])

    return poster


async def _add_image(
    session: AsyncSession,
    poster: Poster,
    *,
    storage_key: str,
    is_primary: bool = False,
    sort_order: int = 0,
) -> PosterImage:
    image = PosterImage(
        poster_id=poster.id,
        storage_key=storage_key,
        is_primary=is_primary,
        sort_order=sort_order,
    )
    session.add(image)
    await session.flush()
    await session.refresh(poster, attribute_names=["images"])
    return image


async def test_list_posters_filters_by_era_decade(db_session: AsyncSession) -> None:
    await _make_poster(db_session, title="Poster 1980s", price="100", era_decade=1980)
    await _make_poster(db_session, title="Poster 1990s", price="100", era_decade=1990)

    result = await poster_service.list_posters(
        db_session, PosterFilterParams(era_decade=1980)
    )

    assert result.total == 1
    assert result.items[0].title == "Poster 1980s"


async def test_list_posters_filters_by_price_range(db_session: AsyncSession) -> None:
    await _make_poster(db_session, title="Cheap", price="50")
    await _make_poster(db_session, title="Mid", price="150")
    await _make_poster(db_session, title="Expensive", price="500")

    result = await poster_service.list_posters(
        db_session,
        PosterFilterParams(min_price=Decimal("100"), max_price=Decimal("200")),
    )

    assert result.total == 1
    assert result.items[0].title == "Mid"


async def test_list_posters_in_stock_only(db_session: AsyncSession) -> None:
    await _make_poster(db_session, title="Available", price="100")
    await _make_poster(
        db_session, title="Reserved", price="100", status=PosterStatus.reserved
    )
    await _make_poster(db_session, title="Sold", price="100", status=PosterStatus.sold)

    result = await poster_service.list_posters(
        db_session, PosterFilterParams(in_stock_only=True)
    )

    assert result.total == 1
    assert result.items[0].title == "Available"


async def test_list_posters_pagination_total_independent_of_limit(
    db_session: AsyncSession,
) -> None:
    for i in range(5):
        await _make_poster(db_session, title=f"Poster {i}", price="100")

    result = await poster_service.list_posters(
        db_session, PosterFilterParams(limit=2, offset=0)
    )

    assert result.total == 5
    assert len(result.items) == 2
    assert result.limit == 2
    assert result.offset == 0


async def test_list_posters_primary_image_url(db_session: AsyncSession) -> None:
    poster = await _make_poster(
        db_session, title="With Image", price="100", with_primary_image=True
    )

    result = await poster_service.list_posters(db_session, PosterFilterParams())

    item = next(i for i in result.items if i.id == poster.id)
    assert item.primary_image_url is not None
    assert item.primary_image_url == build_media_url(
        f"posters/public/{poster.id}/01-test.jpg"
    )


async def test_get_poster_detail_not_found_raises(db_session: AsyncSession) -> None:
    with pytest.raises(PosterNotFound) as exc_info:
        await poster_service.get_poster_detail(db_session, uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "POSTER_NOT_FOUND"


async def test_get_poster_detail_includes_images(db_session: AsyncSession) -> None:
    poster = await _make_poster(
        db_session, title="Detail Poster", price="250", with_primary_image=True
    )

    detail = await poster_service.get_poster_detail(db_session, poster.id)

    assert detail.id == poster.id
    assert len(detail.images) == 1
    assert detail.images[0].is_primary is True


# --- visibility filtering (ADR-0006 D2/D5 — G6) ---


async def test_list_posters_internal_primary_image_is_none_not_raise(
    db_session: AsyncSession,
) -> None:
    """รูป primary เป็น internal → primary_image_url เป็น None และต้องไม่ raise
    (ไม่ fallback ไปรูป public ถัดไป — ดู _primary_image_url)."""
    poster = await _make_poster(db_session, title="Internal Primary", price="100")
    await _add_image(
        db_session,
        poster,
        storage_key=f"posters/internal/{poster.id}/01-uv.jpg",
        is_primary=True,
        sort_order=0,
    )
    await _add_image(
        db_session,
        poster,
        storage_key=f"posters/public/{poster.id}/02-front.jpg",
        sort_order=1,
    )

    result = await poster_service.list_posters(db_session, PosterFilterParams())

    item = next(i for i in result.items if i.id == poster.id)
    assert item.primary_image_url is None


async def test_get_poster_detail_excludes_internal_images(
    db_session: AsyncSession,
) -> None:
    poster = await _make_poster(db_session, title="Mixed Images", price="100")
    first = await _add_image(
        db_session,
        poster,
        storage_key=f"posters/public/{poster.id}/01-front.jpg",
        is_primary=True,
        sort_order=0,
    )
    await _add_image(
        db_session,
        poster,
        storage_key=f"posters/internal/{poster.id}/02-uv.jpg",
        sort_order=1,
    )
    third = await _add_image(
        db_session,
        poster,
        storage_key=f"posters/public/{poster.id}/03-back.jpg",
        sort_order=2,
    )

    detail = await poster_service.get_poster_detail(db_session, poster.id)

    # แถว public เหลือครบและเรียงตาม sort_order เหมือนเดิม
    assert [image.id for image in detail.images] == [first.id, third.id]
    assert detail.primary_image_url == build_media_url(
        f"posters/public/{poster.id}/01-front.jpg"
    )


async def test_get_poster_detail_all_internal_images_returns_empty_list(
    db_session: AsyncSession,
) -> None:
    poster = await _make_poster(db_session, title="All Internal", price="100")
    await _add_image(
        db_session,
        poster,
        storage_key=f"posters/internal/{poster.id}/01-uv.jpg",
        is_primary=True,
        sort_order=0,
    )
    await _add_image(
        db_session,
        poster,
        storage_key=f"posters/internal/{poster.id}/02-raking.jpg",
        sort_order=1,
    )

    detail = await poster_service.get_poster_detail(db_session, poster.id)

    assert detail.images == []
    assert detail.primary_image_url is None


async def test_get_poster_detail_without_images_returns_empty_list(
    db_session: AsyncSession,
) -> None:
    """Regression เดิม — โปสเตอร์ที่ไม่มีรูปเลยต้องไม่พัง."""
    poster = await _make_poster(db_session, title="No Images", price="100")

    detail = await poster_service.get_poster_detail(db_session, poster.id)

    assert detail.images == []
    assert detail.primary_image_url is None


async def test_skipped_image_is_logged_without_leaking_storage_key(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """ข้ามรูปแล้วต้อง log ให้รู้ว่ามีข้อมูลผิดปกติ แต่ห้ามมีค่า storage_key ใน log
    (สกิล security-baseline §2 — คู่กับ test_media.py ที่คุมข้อความของ exception)."""
    poster = await _make_poster(db_session, title="Logged", price="100")
    secret_key = f"posters/internal/{poster.id}/01-uv-scan.jpg"
    internal = await _add_image(
        db_session, poster, storage_key=secret_key, is_primary=True, sort_order=0
    )

    with caplog.at_level(logging.WARNING, logger="app.services.poster_service"):
        detail = await poster_service.get_poster_detail(db_session, poster.id)

    assert detail.images == []
    # ต้องมี log เตือน ไม่ใช่กลืนเงียบ
    assert caplog.records, "ข้ามรูปแล้วต้องมี log WARNING"
    assert str(poster.id) in caplog.text
    assert str(internal.id) in caplog.text
    # แต่ห้ามมี path ของรูป internal หลุดเข้า log
    assert secret_key not in caplog.text
    assert "posters/internal/" not in caplog.text
    assert "01-uv-scan.jpg" not in caplog.text


# --- ADR-0009: คุณลักษณะเชิงพรรณนา ---


async def test_get_poster_detail_adr0009_fields_default_null(
    db_session: AsyncSession,
) -> None:
    """แถวใหม่ (ยังไม่มีใครกรอก) ต้องเห็น 8 ฟิลด์ใหม่เป็น NULL ทั้งหมดใน detail
    (needs_review server_default เป็น true แต่ไม่ออก response — ดูเทสแยกด้านล่าง)."""
    poster = await _make_poster(db_session, title="Blank Attributes", price="100")

    detail = await poster_service.get_poster_detail(db_session, poster.id)

    assert detail.poster_type is None
    assert detail.release_region is None
    assert detail.release_date is None
    assert detail.copyright_year is None
    assert detail.size_format is None
    assert detail.year is None
    assert detail.restoration_status is None
    assert detail.restoration_note is None
    assert not hasattr(detail, "needs_review")


async def test_get_poster_detail_adr0009_fields_are_mapped_when_present(
    db_session: AsyncSession,
) -> None:
    """แถวที่คนตรวจแล้วกรอกครบ — ทุกฟิลด์ต้องออกมาตรงค่าที่เก็บใน DB ไม่ถูกปัดทิ้ง
    หรือแปลงผิด (โดยเฉพาะ enum ที่ต้องคง type เดิม ไม่ใช่ .value string เปล่า)."""
    poster = Poster(
        title="Fully Described",
        price=Decimal("500"),
        poster_type=PosterType.ADVANCE,
        release_region=ReleaseRegion.JP,
        release_date=date(1999, 6, 1),
        copyright_year=1998,
        size_format=SizeFormat.ONE_SHEET,
        year=1999,
        restoration_status=RestorationStatus.LINEN_BACKED,
        restoration_note="Mounted บนผ้าลินิน ปี 2020",
        needs_review=False,
    )
    db_session.add(poster)
    await db_session.flush()

    detail = await poster_service.get_poster_detail(db_session, poster.id)

    assert detail.poster_type == PosterType.ADVANCE
    assert detail.release_region == ReleaseRegion.JP
    assert detail.release_date == date(1999, 6, 1)
    assert detail.copyright_year == 1998
    assert detail.size_format == SizeFormat.ONE_SHEET
    assert detail.year == 1999
    assert detail.restoration_status == RestorationStatus.LINEN_BACKED
    assert detail.restoration_note == "Mounted บนผ้าลินิน ปี 2020"


async def test_get_poster_detail_never_exposes_needs_review(
    db_session: AsyncSession,
) -> None:
    """ADR-0009 D11 — needs_review เป็นธงงานภายใน ห้ามออก public API แม้ในเคส
    ที่แถวติดธงอยู่จริง (needs_review=True คือค่า server_default ของทุกแถวใหม่)."""
    poster = await _make_poster(db_session, title="Needs Review", price="100")
    assert poster.needs_review is True  # sanity: server_default ตามที่คาด

    detail = await poster_service.get_poster_detail(db_session, poster.id)

    assert "needs_review" not in detail.model_dump()


async def test_list_posters_does_not_expose_adr0009_fields(
    db_session: AsyncSession,
) -> None:
    """PosterListItem ต้องไม่ขยายตาม ADR-0009 D11 — sanity check ว่า list ยังเป็น
    field set เดิม ไม่มีฟิลด์ใหม่หลุดเข้ามา."""
    await _make_poster(db_session, title="List Item", price="100")

    result = await poster_service.list_posters(db_session, PosterFilterParams())

    item_fields = set(result.items[0].model_dump().keys())
    assert item_fields == {
        "id",
        "title",
        "price",
        "status",
        "condition_grade",
        "era_decade",
        "studio",
        "primary_image_url",
    }
