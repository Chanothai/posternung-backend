"""Integration tests (HTTP-level) ของ F2 poster catalog."""

import uuid
from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.media import build_media_url
from app.models.enums import (
    PosterType,
    ReleaseRegion,
    RestorationStatus,
    SizeFormat,
)
from app.models.poster import Poster, PosterImage

API = "/api/v1/posters"


def _storage_key(poster_id) -> str:
    return f"posters/public/{poster_id}/01-test.jpg"


async def _seed_poster(
    session: AsyncSession, *, title: str = "Test Poster", price: str = "100"
) -> Poster:
    poster = Poster(title=title, price=Decimal(price))
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
    poster = Poster(title=title, price=Decimal("100"))
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
