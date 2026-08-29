"""Unit test ของ poster_service — ครอบ filter/pagination logic + not-found."""

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PosterHasActiveReservation,
    PosterNotAvailable,
    PosterNotFound,
    PosterNotPublishable,
    PosterSoldReasonRequired,
)
from app.core.media import build_media_url
from app.models.enums import (
    PosterImageKind,
    PosterCondition,
    PosterStatus,
    PosterType,
    ReleaseRegion,
    ReservationStatus,
    RestorationStatus,
    SizeFormat,
)
from app.models.poster import Poster, PosterImage
from app.models.poster_attribute_review import PosterAttributeReview
from app.models.reservation import Reservation
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID
from app.repositories import poster_repository
from app.schemas.poster import PosterFilterParams
from app.services import poster_service

# เวลาคงที่ (ไม่ใช่ now()) เพื่อให้เทสไม่ขึ้นกับนาฬิกา — ค่าที่แน่นอนไม่มีความหมาย
# ต่อกฎ มีแค่ NULL / ไม่ NULL เท่านั้นที่นับ (ADR-0013 D2)
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
# เวลาคงที่ของ sold_at — ต่างจาก PUBLISHED_AT โดยตั้งใจ (ADR-0025 D4: สองค่านี้เป็น
# คนละอันกัน ต้องไม่ยุบเป็นค่าเดียว)
SOLD_AT = datetime(2026, 2, 1, tzinfo=UTC)
# เวลาคงที่ของ verified_at — ต่างจากทั้งสองตัวข้างบนโดยตั้งใจ (ADR-0027 D1) · ย้ายมา
# ไว้ที่นี่ (เดิมประกาศต่ำกว่า `_make_poster` มาก) เพราะตอนนี้เป็น default parameter
# ของ `_make_poster` เอง — ต้องนิยามก่อนถูกใช้ในลายเซ็นฟังก์ชัน
VERIFIED_AT = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)


async def _make_poster(
    session: AsyncSession,
    *,
    title: str,
    price: str,
    status: PosterStatus = PosterStatus.available,
    # default เป็นเกรดจริง ไม่ใช่ None เพราะใบที่ไม่มีเกรด publish ไม่ได้เลย
    # (CHECK `ck_posters_published_requires_condition_grade` — BR-05) · เทสที่อยากได้
    # ใบไม่มีเกรดต้องส่ง `condition_grade=None` + `published=False` เข้ามาเองให้เห็นชัด
    condition_grade: PosterCondition | None = PosterCondition.very_good,
    # default เป็น True เพราะเทสส่วนใหญ่คือเทสหน้าร้าน ซึ่งเห็นเฉพาะใบที่ publish แล้ว
    # (`poster_repository.published_only()` — ADR-0013 D2) · เทสที่อยากได้ใบที่ยัง
    # ไม่เปิดขายต้องส่ง `published=False` เข้ามาเองให้เห็นชัดว่าตั้งใจ
    published: bool = True,
    era_decade: int | None = None,
    with_primary_image: bool = False,
    # ต้องส่งเองเมื่อ status=PosterStatus.sold — ไม่มี default อัตโนมัติเป็นค่าปัจจุบัน
    # โดยตั้งใจ (ADR-0025 D4: sold_at ต้องมาจากผู้เรียกเสมอ ไม่ใช่ now())
    sold_at: datetime | None = None,
    # default เป็นลายเซ็นจริงเสมอ (ไม่ใช่ None) ด้วยเหตุผลเดียวกับ `condition_grade`
    # ข้างบน — CHECK `ck_posters_published_requires_verified` (ADR-0027 A3-D1) ปฏิเสธ
    # ใบที่ published ∧ ไม่ sold ∧ ไม่มีลายเซ็น · เทสที่อยากได้ใบ published+unverified
    # (เช่นจำลองแถวค้างของ correction_entry) ต้องส่ง `verified_at=None` +
    # `status=PosterStatus.sold` เข้ามาเองให้เห็นชัดว่าตั้งใจ (ข้อยกเว้นเดียวที่ CHECK ยอมรับ)
    verified_at: datetime | None = VERIFIED_AT,
) -> Poster:
    # ล้มให้ดังตรงนี้แทนที่จะปล่อยเป็น IntegrityError ที่อ่านไม่ออกจาก CHECK ระดับ DB
    # (คู่ที่ผิดกฎนี้ถูกทดสอบตรง ๆ ใน tests/unit/test_poster_publication_constraint.py)
    assert not (
        published and condition_grade is None
    ), "ใบที่ไม่มีเกรด publish ไม่ได้ — ส่ง published=False มาด้วยถ้าตั้งใจให้ไม่มีเกรด"
    # เช่นเดียวกัน — ck_posters_sold_requires_sold_at (ADR-0025 D2) ถูกทดสอบตรง ๆ ใน
    # tests/unit/test_poster_sold_at_constraint.py
    assert not (
        status == PosterStatus.sold and sold_at is None
    ), "status=sold ต้องมี sold_at คู่กันเสมอ — ส่ง sold_at= มาด้วย"
    # ck_posters_published_requires_verified (ADR-0027 A3-D1) ถูกทดสอบตรง ๆ ใน
    # tests/unit/test_poster_verified_constraint.py
    assert not (published and status != PosterStatus.sold and verified_at is None), (
        "ใบที่ publish แล้วและยังไม่ sold ต้องมี verified_at คู่กันเสมอ — ส่ง "
        "status=PosterStatus.sold มาด้วยถ้าตั้งใจจำลองข้อยกเว้นนี้ (A3-D1)"
    )
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title=title,
        price=Decimal(price),
        status=status,
        condition_grade=condition_grade,
        published_at=PUBLISHED_AT if published else None,
        era_decade=era_decade,
        sold_at=sold_at,
        verified_at=verified_at,
    )
    session.add(poster)
    await session.flush()

    if with_primary_image:
        session.add(
            PosterImage(
                poster_id=poster.id,
                storage_key=f"posters/public/{poster.id}/01-test.jpg",
                kind=PosterImageKind.FRONT,
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
    kind: PosterImageKind = PosterImageKind.FRONT,
) -> PosterImage:
    image = PosterImage(
        poster_id=poster.id,
        storage_key=storage_key,
        kind=kind,
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
    await _make_poster(
        db_session,
        title="Sold",
        price="100",
        status=PosterStatus.sold,
        sold_at=SOLD_AT,
    )

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
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title="Fully Described",
        price=Decimal("500"),
        # "กรอกครบ" ต้องรวมเกรดด้วย — ไม่มีเกรด = publish ไม่ได้เลย (BR-05)
        condition_grade=PosterCondition.near_mint,
        # ต้อง publish ไม่งั้น detail ตอบ 404 ก่อนถึงการตรวจฟิลด์ (ADR-0013 D2)
        published_at=PUBLISHED_AT,
        # ck_posters_published_requires_verified (ADR-0027 A3-D1) — published ต้องมี
        # ลายเซ็นคู่กันเสมอ (แถวนี้ status default = available ไม่ใช่ sold)
        verified_at=VERIFIED_AT,
        poster_type=PosterType.ADVANCE,
        release_region=ReleaseRegion.JP,
        # ADR-0009 D13 ข้อ 2 — ห้ามกรอก release_date โดยไม่มี release_date_text
        # คู่กัน (writer เดียวคือ parse_release_date_text) ค่านี้ parse ผ่านฟังก์ชัน
        # นั้นแล้วได้ date(1999, 6, 1) ตรงกับ release_date ด้านล่างเป๊ะ ไม่ใช่ค่าคนละที่มา
        release_date_text="June 1, 1999",
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
    assert detail.release_date_text == "June 1, 1999"
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


# ---- ADR-0013: หน้าร้านเสิร์ฟเฉพาะใบที่ publish แล้ว ----
#
# ที่มา: ADR-0013 D2 — `published_at` แทนที่ `graded_only()` เป็นตัวกรองหน้าร้าน
# ตัวเดียว · กฎ BR-05 (ราคาต้องแสดงคู่สภาพ) ย้ายจาก "กรองตอนอ่าน" ไปเป็น invariant
# ตอนเขียนที่ระดับ DB แล้ว (CHECK — ทดสอบใน test_poster_publication_constraint.py)


async def test_list_posters_hides_unpublished_poster(
    db_session: AsyncSession,
) -> None:
    """ใบที่มีเกรดครบแต่ยังไม่มีใครกดเปิดขาย ต้องไม่โผล่บนหน้าร้าน

    นี่คือเคสที่ `graded_only()` เดิมจับไม่ได้เลย — มีเกรดแล้วก็ผ่านตัวกรองเก่าทันที
    """
    await _make_poster(db_session, title="Published", price="100")
    await _make_poster(db_session, title="Unpublished", price="100", published=False)

    result = await poster_service.list_posters(db_session, PosterFilterParams())

    assert [item.title for item in result.items] == ["Published"]


async def test_list_posters_total_excludes_unpublished_poster(
    db_session: AsyncSession,
) -> None:
    """`total` ต้องนับตามที่กรองแล้ว ไม่ใช่จำนวนแถวทั้งตาราง

    ถ้า `published_only()` ถูกใส่แค่ใน list_stmt แล้วลืม count_stmt แอปจะเห็น
    total ที่ใหญ่กว่าของที่มีจริง แล้วขอหน้าถัดไปที่ว่างเปล่าไปเรื่อย ๆ
    """
    await _make_poster(db_session, title="Published", price="100")
    for i in range(3):
        await _make_poster(
            db_session, title=f"Unpublished {i}", price="100", published=False
        )

    result = await poster_service.list_posters(db_session, PosterFilterParams())

    assert result.total == 1


async def test_list_posters_hides_poster_without_condition_grade(
    db_session: AsyncSession,
) -> None:
    """ใบไม่มีเกรดยังคงไม่โผล่ (BR-05) — แต่ตอนนี้เพราะ publish ไม่ได้เลย ไม่ใช่
    เพราะถูกกรองตอนอ่าน (CHECK ของ ADR-0013 D3 ปฏิเสธคู่ ungraded+published)."""
    await _make_poster(db_session, title="Graded", price="100")
    await _make_poster(
        db_session,
        title="Ungraded",
        price="100",
        condition_grade=None,
        published=False,
    )

    result = await poster_service.list_posters(db_session, PosterFilterParams())

    assert [item.title for item in result.items] == ["Graded"]


async def test_get_poster_detail_unpublished_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """404 ไม่ใช่ 409 — ห้ามยืนยันว่า id นี้มีอยู่จริงให้คนไล่เดา id"""
    poster = await _make_poster(
        db_session, title="Unpublished", price="100", published=False
    )

    with pytest.raises(PosterNotFound) as exc_info:
        await poster_service.get_poster_detail(db_session, poster.id)

    assert exc_info.value.error_code == "POSTER_NOT_FOUND"


async def test_get_poster_detail_without_condition_grade_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """ใบไม่มีเกรด = publish ไม่ได้ = 404 เสมอ (ทางอ้อมผ่าน published_at)"""
    poster = await _make_poster(
        db_session,
        title="Ungraded",
        price="100",
        condition_grade=None,
        published=False,
    )

    with pytest.raises(PosterNotFound):
        await poster_service.get_poster_detail(db_session, poster.id)


async def test_get_poster_detail_sold_but_published_returns_200(
    db_session: AsyncSession,
) -> None:
    """ADR-0013 D6 / ADR-0005 D5 / SCR-05 AC-5 — "ถูกซื้อไประหว่างดูอยู่" ต้องเป็น
    หน้าจอคนละอันกับ "ไม่มีโปสเตอร์นี้" (AC-6) · ขายแล้วห้ามล้าง `published_at`
    ไม่งั้น AC-5 พังเงียบ ๆ กลายเป็น 404
    """
    poster = await _make_poster(
        db_session,
        title="Sold Poster",
        price="100",
        status=PosterStatus.sold,
        sold_at=SOLD_AT,
    )

    detail = await poster_service.get_poster_detail(db_session, poster.id)

    assert detail.id == poster.id
    assert detail.status == PosterStatus.sold
    assert detail.sold_at == SOLD_AT


async def test_sql_and_python_predicates_agree(db_session: AsyncSession) -> None:
    """`published_only()` (SQL) กับ `is_published()` (Python) ต้องตอบตรงกันทุกใบ

    กฎเดียวกันถูกเขียนสองภาษาเพราะ list ต้องกรองใน SQL (ไม่งั้น total/LIMIT โกหก)
    ส่วน detail กรองใน Python — เทสนี้คือสิ่งที่กันไม่ให้สองตัวนี้ดริฟต์ออกจากกัน
    """
    published = await _make_poster(db_session, title="Published", price="100")
    unpublished = await _make_poster(
        db_session, title="Unpublished", price="100", published=False
    )

    stmt = poster_repository.published_only(select(Poster.id))
    ids_from_sql = set((await db_session.execute(stmt)).scalars().all())

    assert poster_service.is_published(published) is (published.id in ids_from_sql)
    assert poster_service.is_published(unpublished) is (unpublished.id in ids_from_sql)
    assert ids_from_sql == {published.id}


async def test_assert_publishable_rejects_poster_without_condition_grade(
    db_session: AsyncSession,
) -> None:
    """guard ก่อนเขียน `published_at` — วันนี้ยังไม่มี call site (ADR-0013 D4)
    ดู docstring ของฟังก์ชัน

    ‹2026-08-16 · INF-28› ใบใน DB ยังถูกสร้างไว้เพื่อยืนยันว่า **ใบที่ไม่มีเกรดมีอยู่
    จริงได้ใน DB** (CHECK ห้ามแค่คู่ published+ไม่มีเกรด) — ถ้าไม่มีบรรทัดนี้ เทสจะ
    กลายเป็นการทดสอบ dataclass ล้วน ๆ ที่ไม่แตะฐานข้อมูลเลย
    """
    await _make_poster(
        db_session,
        title="Ungraded",
        price="100",
        condition_grade=None,
        published=False,
    )

    with pytest.raises(PosterNotPublishable):
        poster_service.assert_publishable(_ready(condition_grade=None))


async def test_assert_publishable_accepts_graded_poster(
    db_session: AsyncSession,
) -> None:
    """มีเกรด = *มีสิทธิ์* ถูก publish — คนละเรื่องกับ publish แล้วหรือยัง"""
    poster = await _make_poster(
        db_session, title="Graded", price="100", published=False
    )

    poster_service.assert_publishable(
        _ready(condition_grade=poster.condition_grade)
    )  # ต้องไม่ raise
    assert poster_service.is_published(poster) is False


# --------------------------------------------------------------------------
# ADR-0027 D5 — `PublishReadiness` fail-closed **ต่อ field** (INF-28 AC-4)
# --------------------------------------------------------------------------
#
# 🔴 เงื่อนไขเจ้าของ 2026-08-16 ข้อ 2: "ทุก field ที่ None = ไม่ทราบ = ไม่ผ่าน
# พร้อมเทสยืนยัน**ต่อ field** ไม่ใช่เทสรวม" — เทสรวมตัวเดียวเขียวได้ด้วยการที่
# ฟิลด์เดียวทำงาน แล้วอีกสี่ฟิลด์ไม่เคยถูกแตะเลย (รูปเดียวกับที่ `test-quality` §2
# บันทึกไว้ว่าเคยเกิดจริง 4 ครั้งในโปรเจกต์นี้)
#
# `VERIFIED_AT` ย้ายขึ้นไปประกาศคู่กับ `PUBLISHED_AT`/`SOLD_AT` แล้ว (INF-38)

# สภาพ **ปกติของ production หลัง invariant** — ทุกฟิลด์ครบและผ่าน
# เทสแต่ละตัวข้างล่างเปลี่ยนทีละฟิลด์ให้เป็น None แล้วยืนยันว่าฟิลด์นั้นเองเป็นตัวกัน
_READY_KWARGS: dict[str, object] = {
    "condition_grade": PosterCondition.very_good,
    "verified_at": VERIFIED_AT,
    "is_unique": True,
    "count_actual": 1,
    "front_image_count": 1,
}


def _ready(**over: object) -> poster_service.PublishReadiness:
    return poster_service.PublishReadiness(**{**_READY_KWARGS, **over})  # type: ignore[arg-type]


def test_a_fully_known_poster_is_publishable() -> None:
    """positive control — ถ้าไม่มีตัวนี้ ชุดข้างล่างเขียวได้ด้วยด่านที่ปฏิเสธทุกกรณี"""
    assert poster_service.publish_blockers(_ready()) == ()
    assert poster_service.is_publishable(_ready()) is True


# blocker ที่ **ต้อง** ออกมาเมื่อฟิลด์นั้นเป็น `None` — ไม่ใช่แค่ "blocker อะไรก็ได้"
# 🔴 เหตุผลที่ต้องระบุตัว: mutation ที่ยุบสาขา `is None` ทิ้งแล้วปล่อยให้ `not None`
# ตกไปเข้าสาขา "รู้แล้วว่าไม่ผ่าน" **รอดเทสที่ assert แค่ `blockers != ()`** (ยิงจริง
# 2026-08-16 · รอด 167/167) · แถวนั้นยังถูกบล็อกก็จริง แต่คนได้อ่านข้อความผิดเรื่อง:
# "แถวนี้แทนของหลายชิ้น" ทั้งที่ความจริงคือ "อ่านค่าไม่ได้" ซึ่งพาไปแก้คนละที่
_UNKNOWN_BLOCKER: dict[str, poster_service.PublishBlocker] = {
    "condition_grade": poster_service.PublishBlocker.NO_CONDITION_GRADE,
    "verified_at": poster_service.PublishBlocker.NOT_VERIFIED,
    "is_unique": poster_service.PublishBlocker.UNKNOWN_IS_UNIQUE,
    "count_actual": poster_service.PublishBlocker.UNKNOWN_COUNT,
    "front_image_count": poster_service.PublishBlocker.UNKNOWN_FRONT_IMAGE_COUNT,
}


def test_every_readiness_field_has_a_named_blocker_for_unknown() -> None:
    """closed-world — ฟิลด์ใหม่ต้องมาพร้อมคำตอบว่า "ไม่ทราบ" ของมันหน้าตายังไง"""
    assert set(_UNKNOWN_BLOCKER) == set(_READY_KWARGS)


@pytest.mark.parametrize("field", sorted(_READY_KWARGS))
def test_every_unknown_field_blocks_publish_on_its_own(field: str) -> None:
    """🔴 หนึ่งเทสต่อหนึ่งฟิลด์ — ฟิลด์ที่หกที่เพิ่มวันหน้าถูกลากเข้ามาเองผ่าน
    `_READY_KWARGS` โดยไม่ต้องมีใครนึกได้ว่าต้องมาต่อรายชื่อ"""
    blockers = poster_service.publish_blockers(_ready(**{field: None}))
    assert blockers != (), f"{field} = None แล้วยังผ่านด่าน"
    assert _UNKNOWN_BLOCKER[field] in blockers, f"{field} = None ได้ blocker ผิดตัว"
    assert poster_service.is_publishable(_ready(**{field: None})) is False


def test_the_readiness_fields_are_exactly_the_facts_the_rule_uses() -> None:
    """closed-world ของโครง — ฟิลด์ที่ถูกเพิ่มเข้า dataclass แต่ไม่มีใครใส่ใน
    `_READY_KWARGS` จะทำให้ `_ready()` พังตอน construct ไม่ใช่ผ่านด่านเงียบ ๆ"""
    assert set(_READY_KWARGS) == set(
        poster_service.PublishReadiness.__dataclass_fields__
    )


def test_an_unverified_poster_is_not_publishable() -> None:
    """ADR-0027 D1 — invariant ของหน้าร้าน · แยกจากเคส "ไม่ทราบ" ข้างบน"""
    assert (
        poster_service.PublishBlocker.NOT_VERIFIED
        in poster_service.publish_blockers(_ready(verified_at=None))
    )


def test_a_row_that_claims_many_pieces_is_not_publishable() -> None:
    """ADR-0019 D6 — หลัง D1 `is_unique` ต้องเป็น true ทุกแถว"""
    assert poster_service.PublishBlocker.NOT_UNIQUE in poster_service.publish_blockers(
        _ready(is_unique=False)
    )


def test_a_count_of_zero_is_not_the_same_blocker_as_no_count_at_all() -> None:
    """🔴 "นับแล้วได้ 0" กับ "ยังไม่นับ" คนละเรื่องและคนต้องทำคนละอย่าง —
    ยุบสองอย่างนี้เข้าด้วยกันเมื่อไหร่ คนที่ยังไม่นับจะได้ข้อความว่าของหมด"""
    assert (
        poster_service.PublishBlocker.COUNT_IS_ZERO
        in poster_service.publish_blockers(_ready(count_actual=0))
    )
    assert (
        poster_service.PublishBlocker.UNKNOWN_COUNT
        in poster_service.publish_blockers(_ready(count_actual=None))
    )


@pytest.mark.parametrize(
    "grade", [g for g in PosterCondition if g is not PosterCondition.mint]
)
def test_more_than_one_piece_is_refused_on_every_grade_below_mint(
    grade: PosterCondition,
) -> None:
    """ADR-0019 D1 — parametrize ทุกเกรด ไม่ใช่เกรดเดียว: mutation ที่เขียนเงื่อนไข
    ผิดเป็น `!= near_mint` รอดเทสที่ fix เกรดไว้ตัวเดียว"""
    assert (
        poster_service.PublishBlocker.COUNT_MULTIPLE_ON_NON_MINT
        in poster_service.publish_blockers(
            _ready(condition_grade=grade, count_actual=2)
        )
    )


def test_more_than_one_piece_passes_on_mint() -> None:
    """ประตูของ D1 เปิดอยู่จริงบน mint — ไม่งั้นเทสข้างบนเขียวได้ด้วยด่านที่ห้ามหมด"""
    assert (
        poster_service.publish_blockers(
            _ready(condition_grade=PosterCondition.mint, count_actual=2)
        )
        == ()
    )


async def test_the_python_rule_and_the_db_check_agree_on_the_grade(
    db_session: AsyncSession,
) -> None:
    """🔴 หนี้ของ INF-10 ที่ถูกฝากต่อมา 3 รอบ (INF-10 → INF-11 → INF-17 → INF-28)

    `is_publishable()` (Python) กับ CHECK `ck_posters_published_requires_condition_grade`
    (SQL) พูดกฎเดียวกันคนละภาษา — เทสนี้คือสิ่งที่กันไม่ให้สองตัวดริฟต์ออกจากกัน
    ทรงเดียวกับ `test_sql_and_python_predicates_agree` ที่ล็อกคู่
    `published_only()` ↔ `is_published()` อยู่แล้ว

    🔴 **เทสนี้ล็อกเฉพาะมิติ *เกรด* — ไม่ใช่คู่ Python↔SQL เต็มรูปของ ADR-0027**
    (คู่เต็มอยู่ที่ `tests/unit/test_publish_predicate_agreement.py` — INF-38 AC-6)
    · หลัง `ck_posters_published_requires_verified` (ADR-0027 A3-D1 · INF-38) ลงแล้ว
    แถวข้างล่าง **ละเมิดสอง constraint พร้อมกัน** (ไม่มีเกรด **และ** ไม่มีลายเซ็น)
    — ตั้งใจส่ง `verified_at=None` เข้ามาเองเพื่อให้เห็นชัดว่าไม่ได้พึ่ง default ของ
    `_make_poster` — และ PostgreSQL **ไม่รับประกันว่าจะรายงาน constraint ไหนก่อน**
    ⇒ `match=` ข้างล่างต้องรับได้ทั้งสองชื่อ
    """
    poster = await _make_poster(
        db_session,
        title="Ungraded",
        price="100",
        condition_grade=None,
        published=False,
        verified_at=None,
    )

    # ฝั่ง Python บอกว่าไม่ผ่าน...
    assert poster_service.is_publishable(_ready(condition_grade=None)) is False

    # ...และ DB ก็ปฏิเสธการเขียนแบบเดียวกัน ไม่ใช่แค่ Python ที่รู้
    with pytest.raises(
        IntegrityError,
        match="ck_posters_published_requires_condition_grade"
        "|ck_posters_published_requires_verified",
    ):
        await db_session.execute(
            update(Poster)
            .where(Poster.id == poster.id)
            .values(published_at=datetime(2026, 8, 16, tzinfo=UTC))
        )
        await db_session.flush()
    await db_session.rollback()


# --------------------------------------------------------------------------
# mark_sold() — ADR-0025 · INF-24 AC-1..AC-6
# --------------------------------------------------------------------------

REVIEWED_AT = datetime(2026, 2, 1, 9, 0, tzinfo=UTC)


async def _make_user(session: AsyncSession):
    from app.models.user import User

    user = User()
    session.add(user)
    await session.flush()
    return user


async def _make_active_reservation(
    session: AsyncSession, poster: Poster
) -> Reservation:
    user = await _make_user(session)
    reservation = Reservation(
        poster_id=poster.id,
        user_id=user.id,
        status=ReservationStatus.active,
        expires_at=datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
    )
    session.add(reservation)
    await session.flush()
    return reservation


async def test_mark_sold_writes_status_and_sold_at_together(
    db_session: AsyncSession,
) -> None:
    """AC-1 · AC-2 — เขียนสองคอลัมน์พร้อมกันในทรานแซกชันเดียว และไม่แตะ published_at
    (AC-5)"""
    poster = await _make_poster(db_session, title="Available", price="100")

    result = await poster_service.mark_sold(
        db_session,
        poster.id,
        sold_at=SOLD_AT,
        reviewed_by="tester",
        reviewed_at=REVIEWED_AT,
        reason="ขายผ่าน TikTok",
        source="pytest",
    )

    assert result.status == PosterStatus.sold
    assert result.sold_at == SOLD_AT
    assert result.published_at == PUBLISHED_AT  # ไม่ถูกแตะเลย (AC-5)


async def test_mark_sold_requires_sold_at_argument_explicitly(
    db_session: AsyncSession,
) -> None:
    """AC-3 — ไม่มี default เป็น `now()`: เรียกโดยไม่ส่ง `sold_at` ต้อง raise
    `TypeError` ที่ระดับ Python ก่อนแตะ DB เลยด้วยซ้ำ (ถ้าใครเผลอเติม
    `sold_at: datetime = None`/`datetime.now()` เป็น default เทสนี้ต้องแดง)"""
    poster = await _make_poster(db_session, title="Available", price="100")

    with pytest.raises(TypeError):
        await poster_service.mark_sold(  # type: ignore[call-arg]
            db_session,
            poster.id,
            reviewed_by="tester",
            reviewed_at=REVIEWED_AT,
            reason="ขายผ่าน TikTok",
            source="pytest",
        )


async def test_mark_sold_records_audit_row_with_who_when_why(
    db_session: AsyncSession,
) -> None:
    """AC-4 — บันทึกใคร/เมื่อไหร่/เพราะอะไรลง poster_attribute_reviews ·
    value_before ต้องเป็นค่าเดิมของ status (ไม่ใช่ NULL — status เป็น NOT NULL เสมอ)"""
    poster = await _make_poster(db_session, title="Available", price="100")

    await poster_service.mark_sold(
        db_session,
        poster.id,
        sold_at=SOLD_AT,
        reviewed_by="tester",
        reviewed_at=REVIEWED_AT,
        reason="ขายผ่าน TikTok",
        source="pytest",
    )

    stmt = select(PosterAttributeReview).where(
        PosterAttributeReview.poster_id == poster.id
    )
    rows = (await db_session.execute(stmt)).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.field == "status"
    assert row.value_before == PosterStatus.available.value
    assert row.value_after == PosterStatus.sold.value
    assert row.reviewed_by == "tester"
    assert row.reviewed_at == REVIEWED_AT
    assert row.reason == "ขายผ่าน TikTok"
    assert row.source == "pytest"


async def test_mark_sold_rejects_blank_reason(db_session: AsyncSession) -> None:
    """AC-4 — reason บังคับ ห้ามว่าง (รวมช่องว่างล้วน ๆ)

    🔴 ต้องเป็น `PosterSoldReasonRequired` (subclass ของ `AppError`) ไม่ใช่
    `ValueError` เปล่า ๆ — `ValueError` ไม่ผ่าน `except AppError` ของ CLI (พบจาก
    code-critic รอบ 1 ของ INF-24, Low)
    """
    poster = await _make_poster(db_session, title="Available", price="100")

    with pytest.raises(PosterSoldReasonRequired):
        await poster_service.mark_sold(
            db_session,
            poster.id,
            sold_at=SOLD_AT,
            reviewed_by="tester",
            reviewed_at=REVIEWED_AT,
            reason="   ",
            source="pytest",
        )


async def test_mark_sold_raises_not_found_for_missing_poster(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(PosterNotFound):
        await poster_service.mark_sold(
            db_session,
            uuid.uuid4(),
            sold_at=SOLD_AT,
            reviewed_by="tester",
            reviewed_at=REVIEWED_AT,
            reason="ขายผ่าน TikTok",
            source="pytest",
        )


@pytest.mark.parametrize("status", [PosterStatus.reserved, PosterStatus.sold])
async def test_mark_sold_rejects_poster_not_available(
    db_session: AsyncSession, status: PosterStatus
) -> None:
    """AC-6 — ขายซ้ำ/ขายใบที่ไม่ใช่ available = ปฏิเสธ ไม่ใช่ no-op เงียบ"""
    extra_sold_at = SOLD_AT if status == PosterStatus.sold else None
    poster = await _make_poster(
        db_session,
        title="Not available",
        price="100",
        status=status,
        sold_at=extra_sold_at,
    )

    with pytest.raises(PosterNotAvailable):
        await poster_service.mark_sold(
            db_session,
            poster.id,
            sold_at=SOLD_AT,
            reviewed_by="tester",
            reviewed_at=REVIEWED_AT,
            reason="ขายผ่าน TikTok",
            source="pytest",
        )

    # ปฏิเสธแล้วต้องไม่มีอะไรถูกทับ — status เดิมยังอยู่
    await db_session.refresh(poster)
    assert poster.status == status


async def test_mark_sold_rejects_when_active_reservation_exists(
    db_session: AsyncSession,
) -> None:
    """AC-6 — reservation ที่ยัง active ต้องถูกตัดสิน ไม่ใช่ปล่อยค้าง: ปฏิเสธทั้งรายการ
    พร้อม reservation.id ให้คนไปตัดสินเอง และห้ามแตะ reservations เลยสักคอลัมน์"""
    poster = await _make_poster(db_session, title="Available", price="100")
    reservation = await _make_active_reservation(db_session, poster)

    with pytest.raises(PosterHasActiveReservation) as exc_info:
        await poster_service.mark_sold(
            db_session,
            poster.id,
            sold_at=SOLD_AT,
            reviewed_by="tester",
            reviewed_at=REVIEWED_AT,
            reason="ขายผ่าน TikTok",
            source="pytest",
        )

    assert exc_info.value.details == [{"reservation_id": str(reservation.id)}]

    # ต้องไม่มีอะไรถูกเขียน — ทั้ง posters และ reservations
    await db_session.refresh(poster)
    await db_session.refresh(reservation)
    assert poster.status == PosterStatus.available
    assert poster.sold_at is None
    assert reservation.status == ReservationStatus.active


# --- ADR-0026 D8 · INF-27 AC-12: นิยามเดียวของสิทธิ์ publish ---


def test_publish_blockers_is_empty_only_when_both_conditions_hold() -> None:
    """🔴 นิยามเดียวของ "มีสิทธิ์ publish ไหม" — pure ไม่แตะ DB ไม่แตะ ORM

    รับค่าที่นับมาแล้วโดยตั้งใจ (ADR-0026 D8) เพราะผู้เรียกฝั่งสคริปต์ไม่มี ORM object
    และการแตะ `poster.images` ที่ไม่ได้ selectinload ในบริบท async = MissingGreenlet
    """
    assert poster_service.publish_blockers(_ready()) == ()


def test_publish_blockers_reports_a_missing_grade() -> None:
    assert poster_service.publish_blockers(_ready(condition_grade=None)) == (
        poster_service.PublishBlocker.NO_CONDITION_GRADE,
    )


def test_publish_blockers_reports_a_missing_front_photo() -> None:
    """BR-06 หลัง ADR-0026 — "มีรูป" ไม่พอ ต้องมีรูปหน้าใบ"""
    assert poster_service.publish_blockers(_ready(front_image_count=0)) == (
        poster_service.PublishBlocker.NO_FRONT_IMAGE,
    )


def test_publish_blockers_reports_both_reasons_at_once() -> None:
    """คนกรอกใบงานต้องเห็นทุกเหตุผลในรอบเดียว — ห้าม short-circuit ที่ข้อแรก"""
    assert set(
        poster_service.publish_blockers(
            _ready(condition_grade=None, front_image_count=0)
        )
    ) == {
        poster_service.PublishBlocker.NO_CONDITION_GRADE,
        poster_service.PublishBlocker.NO_FRONT_IMAGE,
    }


def test_is_publishable_agrees_with_publish_blockers_on_every_combination() -> None:
    """closed-world เล็ก ๆ ของสองฟังก์ชันที่ต้องตอบตรงกันเสมอ

    ถ้าใครแก้ตัวใดตัวหนึ่งให้ตัดสินเองแยกจากอีกตัว เทสนี้แดง — นั่นคือรูปของการมี
    "สำเนาที่ 4" ที่ INF-27 AC-12 ห้ามไว้ กลับมาในบ้านเดียวกัน
    """
    for grade in (None, PosterCondition.very_good):
        for front in (0, 1, 5):
            readiness = _ready(condition_grade=grade, front_image_count=front)
            expected = not poster_service.publish_blockers(readiness)
            assert poster_service.is_publishable(readiness) is expected
