"""Integration tests (HTTP-level) ของ F2 poster catalog."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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

API = "/api/v1/posters"

# เวลาคงที่ (ไม่ใช่ now()) — ค่าที่แน่นอนไม่มีความหมายต่อกฎ มีแค่ NULL / ไม่ NULL
# เท่านั้นที่นับ (ADR-0013 D2)
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _storage_key(poster_id) -> str:
    return f"posters/public/{poster_id}/01-test.jpg"


async def _seed_poster(
    session: AsyncSession,
    *,
    title: str = "Test Poster",
    price: str = "100",
    # ต้องมีเกรดเสมอ ไม่งั้นใบนี้ publish ไม่ได้เลย (BR-05 — CHECK
    # `ck_posters_published_requires_condition_grade`) · ส่ง `condition_grade=None`
    # คู่กับ `published=False` เมื่อกำลังเทสพฤติกรรมการซ่อนโดยตรงเท่านั้น
    condition_grade: PosterCondition | None = PosterCondition.very_good,
    # default publish แล้ว เพราะเทสส่วนใหญ่คือเทสหน้าร้าน — ใบที่ยังไม่ publish
    # ไม่ออก public API เลย (ADR-0013 D2) · ส่ง `published=False` ให้เห็นชัดว่าตั้งใจ
    published: bool = True,
    status: PosterStatus = PosterStatus.available,
) -> Poster:
    assert not (
        published and condition_grade is None
    ), "ใบที่ไม่มีเกรด publish ไม่ได้ — ส่ง published=False มาด้วยถ้าตั้งใจให้ไม่มีเกรด"
    poster = Poster(
        title=title,
        price=Decimal(price),
        condition_grade=condition_grade,
        status=status,
        published_at=PUBLISHED_AT if published else None,
    )
    session.add(poster)
    await session.flush()
    session.add(
        PosterImage(
            poster_id=poster.id,
            storage_key=_storage_key(poster.id),
            is_primary=True,
        )
    )
    await session.commit()
    return poster


async def test_list_posters_empty_returns_200_with_empty_items(
    client: AsyncClient,
) -> None:
    res = await client.get(API)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_list_posters_returns_seeded_poster(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster(db_session, title="Seeded Poster")

    res = await client.get(API)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Seeded Poster"
    assert body["items"][0]["primary_image_url"] == build_media_url(
        _storage_key(poster.id)
    )


async def test_list_posters_limit_zero_is_422(client: AsyncClient) -> None:
    res = await client.get(API, params={"limit": 0})
    assert res.status_code == 422
    assert res.json()["error_code"] == "VALIDATION_ERROR"


async def test_list_posters_limit_over_100_is_422(client: AsyncClient) -> None:
    res = await client.get(API, params={"limit": 101})
    assert res.status_code == 422


async def test_list_posters_negative_min_price_is_422(client: AsyncClient) -> None:
    res = await client.get(API, params={"min_price": -1})
    assert res.status_code == 422


async def test_get_poster_detail_returns_images(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster(db_session, title="Detail Poster")

    res = await client.get(f"{API}/{poster.id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "Detail Poster"
    assert len(body["images"]) == 1
    assert body["images"][0]["is_primary"] is True
    assert body["images"][0]["url"] == build_media_url(_storage_key(poster.id))


async def test_get_poster_detail_not_found_404(client: AsyncClient) -> None:
    res = await client.get(f"{API}/{uuid.uuid4()}")
    assert res.status_code == 404
    assert res.json()["error_code"] == "POSTER_NOT_FOUND"


async def test_get_poster_detail_invalid_uuid_422(client: AsyncClient) -> None:
    res = await client.get(f"{API}/not-a-uuid")
    assert res.status_code == 422


# --- visibility filtering (ADR-0006 D2/D5 — G6) ---


async def _seed_poster_with_images(
    session: AsyncSession, *, title: str, images: list[tuple[str, bool, int]]
) -> Poster:
    """images = [(storage_key_suffix, is_primary, sort_order), ...]

    suffix ถูกต่อท้าย `posters/` ตรง ๆ เพื่อให้ระบุ visibility segment ได้ในเทส
    """
    # ต้องมีเกรด + publish แล้ว ไม่งั้นใบนี้ถูกซ่อนก่อนถึงขั้นตรวจ visibility ของรูป
    poster = Poster(
        title=title,
        price=Decimal("100"),
        condition_grade=PosterCondition.very_good,
        published_at=PUBLISHED_AT,
    )
    session.add(poster)
    await session.flush()
    for suffix, is_primary, sort_order in images:
        session.add(
            PosterImage(
                poster_id=poster.id,
                storage_key=f"posters/{suffix.format(poster_id=poster.id)}",
                is_primary=is_primary,
                sort_order=sort_order,
            )
        )
    await session.commit()
    return poster


async def test_list_posters_with_internal_image_returns_200_not_500(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster_with_images(
        db_session,
        title="Internal Primary",
        images=[
            ("internal/{poster_id}/01-uv.jpg", True, 0),
            ("public/{poster_id}/02-front.jpg", False, 1),
        ],
    )

    res = await client.get(API)

    assert res.status_code == 200, res.text
    item = next(i for i in res.json()["items"] if i["id"] == str(poster.id))
    assert item["primary_image_url"] is None


async def test_get_poster_detail_filters_internal_images(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster_with_images(
        db_session,
        title="Mixed Images",
        images=[
            ("public/{poster_id}/01-front.jpg", True, 0),
            ("internal/{poster_id}/02-uv.jpg", False, 1),
            ("public/{poster_id}/03-back.jpg", False, 2),
        ],
    )

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert [image["url"] for image in body["images"]] == [
        build_media_url(f"posters/public/{poster.id}/01-front.jpg"),
        build_media_url(f"posters/public/{poster.id}/03-back.jpg"),
    ]
    assert body["primary_image_url"] == build_media_url(
        f"posters/public/{poster.id}/01-front.jpg"
    )


async def test_get_poster_detail_all_internal_images_returns_200_empty_images(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster_with_images(
        db_session,
        title="All Internal",
        images=[
            ("internal/{poster_id}/01-uv.jpg", True, 0),
            ("internal/{poster_id}/02-raking.jpg", False, 1),
        ],
    )

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["images"] == []
    assert body["primary_image_url"] is None


async def test_get_poster_detail_without_images_returns_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster_with_images(db_session, title="No Images", images=[])

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["images"] == []
    assert body["primary_image_url"] is None


# --- ADR-0009: คุณลักษณะเชิงพรรณนา ---

# ฟิลด์เดิมของ PosterDetailResponse ก่อนรอบ ADR-0009 — ใช้ยืนยันว่าไม่มีตัวไหนหายไป
# (US-01 ห้าม regress) แยกจากชุด 8 ฟิลด์ใหม่ที่ต้องมีเพิ่มเข้ามาพอดี
PRE_ADR0009_DETAIL_FIELDS = {
    "id",
    "title",
    "price",
    "status",
    "condition_grade",
    "era_decade",
    "studio",
    "primary_image_url",
    "tmdb_id",
    "size",
    "description",
    "is_authenticated",
    "authenticity_note",
    "provenance",
    "images",
    "created_at",
}
ADR0009_NEW_DETAIL_FIELDS = {
    "poster_type",
    "release_region",
    # release_date_text (observed) เพิ่มตาม ADR-0009 D13 amendment — คู่กับ
    # release_date (derived) ที่มีอยู่แล้ว
    "release_date_text",
    "release_date",
    "copyright_year",
    "size_format",
    "year",
    "restoration_status",
    "restoration_note",
}


async def test_get_poster_detail_adr0009_fields_present_and_old_fields_intact(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster(db_session, title="Attributes Poster")

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert PRE_ADR0009_DETAIL_FIELDS <= body.keys(), (
        "ฟิลด์เดิมหายไปบางตัว (US-01 regress): "
        f"{PRE_ADR0009_DETAIL_FIELDS - body.keys()}"
    )
    assert (
        ADR0009_NEW_DETAIL_FIELDS <= body.keys()
    ), f"ฟิลด์ใหม่ของ ADR-0009 หายไป: {ADR0009_NEW_DETAIL_FIELDS - body.keys()}"
    # แถวใหม่ยังไม่มีใครตรวจ — ต้องเป็น NULL ทั้งหมด (ADR-0009 D2)
    for field in ADR0009_NEW_DETAIL_FIELDS:
        assert body[field] is None, f"{field} ควรเป็น NULL แต่ได้ {body[field]!r}"


async def test_get_poster_detail_adr0009_fields_serialize_when_present(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = Poster(
        title="Fully Described",
        price=Decimal("500"),
        # "กรอกครบ" ต้องรวมเกรดด้วย — ไม่มีเกรด = publish ไม่ได้เลย (BR-05)
        condition_grade=PosterCondition.near_mint,
        # ต้อง publish ไม่งั้น detail ตอบ 404 ก่อนถึงการตรวจฟิลด์ (ADR-0013 D2)
        published_at=PUBLISHED_AT,
        poster_type=PosterType.THEATRICAL,
        release_region=ReleaseRegion.TH,
        release_date_text="25 ธันวาคม 2544",
        release_date=date(2001, 12, 25),
        copyright_year=2001,
        size_format=SizeFormat.HALF_SHEET,
        year=2001,
        restoration_status=RestorationStatus.RESTORED,
        restoration_note="รีทัชสีจาง ปี 2022",
        needs_review=False,
    )
    db_session.add(poster)
    await db_session.commit()

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["poster_type"] == "THEATRICAL"
    assert body["release_region"] == "TH"
    assert body["release_date_text"] == "25 ธันวาคม 2544"
    assert body["release_date"] == "2001-12-25"
    assert body["copyright_year"] == 2001
    assert body["size_format"] == "HALF_SHEET"
    assert body["year"] == 2001
    assert body["restoration_status"] == "RESTORED"
    assert body["restoration_note"] == "รีทัชสีจาง ปี 2022"


async def test_get_poster_detail_never_exposes_needs_review(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ADR-0009 D11 — needs_review เป็นธงงานภายใน ห้ามหลุดออก public API เด็ดขาด."""
    poster = await _seed_poster(db_session, title="Review Flagged")

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    assert "needs_review" not in res.json()


async def test_list_posters_never_exposes_adr0009_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """PosterListItem ไม่ขยายตาม ADR-0009 D11 — สัญญาของ list ต้องเหมือนเดิมเป๊ะ."""
    await _seed_poster(db_session, title="List Item")

    res = await client.get(API)

    assert res.status_code == 200, res.text
    item = res.json()["items"][0]
    leaked = (ADR0009_NEW_DETAIL_FIELDS | {"needs_review"}) & item.keys()
    assert not leaked, f"PosterListItem มีฟิลด์ที่ไม่ควรมี: {leaked}"


# ---- ADR-0013: หน้าร้านเสิร์ฟเฉพาะใบที่ publish แล้ว (ระดับ HTTP) ----


async def test_list_posters_hides_unpublished_poster(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ใบที่มีเกรดครบแต่ยังไม่เปิดขาย ต้องไม่โผล่ และต้องไม่ถูกนับใน `total`"""
    await _seed_poster(db_session, title="Published")
    await _seed_poster(db_session, title="Unpublished", published=False)

    res = await client.get(API)

    assert res.status_code == 200, res.text
    body = res.json()
    assert [item["title"] for item in body["items"]] == ["Published"]
    assert body["total"] == 1


async def test_list_posters_hides_poster_without_condition_grade(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ใบไม่มีเกรดยังคงไม่โผล่ (BR-05) — publish ไม่ได้เลยตาม CHECK ของ ADR-0013 D3"""
    await _seed_poster(db_session, title="Graded")
    await _seed_poster(
        db_session, title="Ungraded", condition_grade=None, published=False
    )

    res = await client.get(API)

    assert res.status_code == 200, res.text
    body = res.json()
    assert [item["title"] for item in body["items"]] == ["Graded"]
    assert body["total"] == 1


async def test_get_poster_detail_unpublished_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """404 POSTER_NOT_FOUND — รหัสเดียวกับใบที่ไม่มีอยู่จริง ไม่ใช่ 409

    SCR-05 AC-6 มีหน้าจอรองรับ 404 อยู่แล้ว และการตอบรหัสอื่นจะเป็นการยืนยัน
    ให้คนไล่เดา id ว่าแถวนี้มีอยู่จริง
    """
    poster = await _seed_poster(db_session, title="Unpublished", published=False)

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 404, res.text
    assert res.json()["error_code"] == "POSTER_NOT_FOUND"


async def test_get_poster_detail_without_condition_grade_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster(
        db_session, title="Ungraded", condition_grade=None, published=False
    )

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 404, res.text
    assert res.json()["error_code"] == "POSTER_NOT_FOUND"


async def test_get_poster_detail_sold_but_published_returns_200_with_status_sold(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ADR-0013 D6 / ADR-0005 D5 / SCR-05 AC-5 — ใบที่ขายไปแล้วต้องยังเปิดดูได้
    พร้อม `status: sold` ("ถูกซื้อไประหว่างดูอยู่" เป็นคนละหน้าจอกับ 404 ของ AC-6)
    """
    poster = await _seed_poster(
        db_session, title="Sold Poster", status=PosterStatus.sold
    )

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == str(poster.id)
    assert body["status"] == "sold"


async def test_poster_detail_never_exposes_published_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ADR-0013 D5 — `published_at` เป็นธงงานภายใน ห้ามออก public API
    (precedent เดียวกับ `needs_review` — ADR-0009 D11) · contract ไม่เปลี่ยน
    """
    poster = await _seed_poster(db_session, title="Published")

    detail = await client.get(f"{API}/{poster.id}")
    listing = await client.get(API)

    assert "published_at" not in detail.json()
    assert "published_at" not in listing.json()["items"][0]
