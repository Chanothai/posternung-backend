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
    VerificationStatus,
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
# ADR-0014 D5 — สองฟิลด์ที่ต้องอยู่ใน PosterDetailResponse (และเฉพาะที่นั่น)
# 🔴 `reference_url` ไม่อยู่ในชุดนี้โดยตั้งใจ — ยังไม่ออก API จนกว่า OD-3 จะปิด (D6)
ADR0014_NEW_DETAIL_FIELDS = {
    "verification_status",
    "reference_note",
}
# ชื่อเก่าก่อน D22 — ต้องไม่หลุดออก response อีก (ไม่ใช่แค่ "ไม่ได้เช็ค")
ADR0014_RENAMED_AWAY_FIELDS = {"verification_note"}
# เก็บลง DB ได้ แต่ห้ามหลุดออก response ทั้งสองเส้นรอบนี้ (ADR-0014 D6 / OD-3)
ADR0014_DB_ONLY_FIELDS = {"reference_url"}
# ADR-0009 D16 — ขนาดที่วัดจากใบจริง · สัญญามีแล้วแต่ติด `x-status: DRAFT`
# 🔴 **การเห็นฟิลด์ในสัญญาไม่ใช่ใบอนุญาตให้ส่งออก** — กฎเดียวกับ path ที่ติด DRAFT
# (`workspace/CLAUDE.md` §1) · เมื่อรอบที่ wire มาถึง เทสนี้คือจุดที่ต้องแก้พร้อมกัน
# และต้องแก้ชนิดใน Pydantic เป็น `float` ด้วย ไม่ใช่ `Decimal` — สัญญาเขียนว่า
# `type: [number, "null"]` แต่ Pydantic v2 ส่ง `Decimal` ออกเป็น JSON **string**
# (drift ตัวเดียวกับที่เคยเกิดกับ `PosterListItem.price` — skill `poster-database` §3)
ADR0009_D16_DRAFT_FIELDS = {"width_in", "height_in"}


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


# ---- ADR-0014: ผลการเทียบกับฐานข้อมูลอ้างอิง (ระดับ HTTP) ----


async def test_get_poster_detail_verification_fields_null_when_unchecked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ADR-0014 D3 — ทุกแถววันนี้ยังไม่มีใครเทียบ ต้องตอบ `null` ไม่ใช่หายไปเฉย ๆ

    ฟิลด์ต้อง *มีอยู่* ใน response ด้วย เพราะรอบ UI ต้องแยก `NULL` (= `NOT_CHECKED`
    ตาม D21) ออกจากค่าที่คนกรอกแล้วได้ — D9 ข้อ 6 · **การหายไปเฉย ๆ ให้ผลเหมือน
    การอ้างว่าตรวจแล้ว** ซึ่งคือสิ่งที่ OD-4 ห้าม
    """
    poster = await _seed_poster(db_session, title="Unverified")

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert (
        ADR0014_NEW_DETAIL_FIELDS <= body.keys()
    ), f"ฟิลด์ใหม่ของ ADR-0014 หายไป: {ADR0014_NEW_DETAIL_FIELDS - body.keys()}"
    for field in ADR0014_NEW_DETAIL_FIELDS:
        assert body[field] is None, f"{field} ควรเป็น NULL แต่ได้ {body[field]!r}"
    assert not (
        ADR0014_RENAMED_AWAY_FIELDS & body.keys()
    ), "ชื่อฟิลด์ก่อน D22 หลุดกลับเข้า response"
    # ฟิลด์เดิมยังอยู่ครบ — ADR-0014 D4 ไม่ลบอะไรในรอบนี้
    assert body["is_authenticated"] is False


async def test_get_poster_detail_verification_fields_serialize_when_present(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ค่าที่คนกรอกไว้ต้องออกมาถูกตัว (เซ็ตในเทสเอง — ไม่มี writer ในระบบ ADR-0014 D7)

    เลือก `NO_REFERENCE_FOUND` เป็นเคสหลักเพราะเป็น**ค่าเดียวที่มากับข้อความ**:
    `reference_note` มีความหมายเดียวคือ *เหตุผลตอนหาไม่เจอ* (D22) เคสนี้จึงพิสูจน์
    ทั้งสองฟิลด์พร้อมกัน · เคส `REFERENCE_FOUND` อยู่ในเทสถัดไปซึ่งพิสูจน์คนละเรื่อง
    (URL ต้องไม่หลุดออก response)

    ‹เดิมเคสหลักคือ `DISCREPANCY_FOUND` — **D21 ตัดค่านั้นออกจาก enum แล้ว**›
    """
    poster = Poster(
        title="Thai Poster With Original Artwork",
        price=Decimal("500"),
        condition_grade=PosterCondition.near_mint,
        published_at=PUBLISHED_AT,
        verification_status=VerificationStatus.NO_REFERENCE_FOUND,
        reference_note="ใบไทยวาดอาร์ตเวิร์กใหม่ทั้งใบ — ไม่มีแบบให้เทียบใน IMP Awards",
    )
    db_session.add(poster)
    await db_session.commit()

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["verification_status"] == "NO_REFERENCE_FOUND"
    assert (
        body["reference_note"]
        == "ใบไทยวาดอาร์ตเวิร์กใหม่ทั้งใบ — ไม่มีแบบให้เทียบใน IMP Awards"
    )
    # 🔴 D4 — ห้าม derive: ไม่ว่าผลการหาแหล่งอ้างอิงเป็นอย่างไร ค่านี้ก็ไม่ขยับ
    assert body["is_authenticated"] is False


async def test_get_poster_detail_never_exposes_reference_url(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ADR-0014 D6 / OD-3 — `reference_url` เก็บลง DB ได้ แต่ยังไม่ออก API

    กันไว้เพราะ *เวลา* (ยังไม่ได้ตรวจเงื่อนไขการใช้งานของเว็บต้นทาง) ไม่ใช่เพราะ
    เป็นข้อมูลภายใน — เมื่อ OD-3 ปิดว่าเปิดได้ เทสนี้คือจุดที่ต้องแก้พร้อมสัญญา
    """
    poster = Poster(
        title="Has Reference URL",
        price=Decimal("500"),
        condition_grade=PosterCondition.near_mint,
        published_at=PUBLISHED_AT,
        verification_status=VerificationStatus.REFERENCE_FOUND,
        reference_url="https://example.invalid/reference/secret",
    )
    db_session.add(poster)
    await db_session.commit()

    detail = await client.get(f"{API}/{poster.id}")
    listing = await client.get(API)

    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert not (ADR0014_DB_ONLY_FIELDS & detail_body.keys())
    assert "example.invalid" not in detail.text
    assert not (ADR0014_DB_ONLY_FIELDS & listing.json()["items"][0].keys())
    assert "example.invalid" not in listing.text


async def test_poster_endpoints_never_expose_draft_measurement_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ADR-0009 D16 — `width_in`/`height_in` เก็บลง DB ได้ แต่ยัง `x-status: DRAFT`

    ใช้ค่าที่ **หาเจอในข้อความดิบ** (`27.00`/`41.00`) เพิ่มจากการเช็ค key เพราะ
    การเช็ค key อย่างเดียวปล่อยผ่านกรณีที่มีคนส่งมันออกไปใต้ชื่ออื่น (เช่นยัดรวมใน
    สตริง `size` หรือตั้งชื่อ alias) ซึ่งเป็นทางที่ไม่มีใครตั้งใจแต่เกิดได้จริง
    """
    poster = Poster(
        title="Measured Poster",
        price=Decimal("500"),
        condition_grade=PosterCondition.near_mint,
        published_at=PUBLISHED_AT,
        width_in=Decimal("27.00"),
        height_in=Decimal("41.00"),
        size_format=SizeFormat.ONE_SHEET,
    )
    db_session.add(poster)
    await db_session.commit()

    detail = await client.get(f"{API}/{poster.id}")
    listing = await client.get(API)

    assert detail.status_code == 200, detail.text
    assert not (ADR0009_D16_DRAFT_FIELDS & detail.json().keys())
    assert not (ADR0009_D16_DRAFT_FIELDS & listing.json()["items"][0].keys())
    assert "41.00" not in detail.text
    assert "41.00" not in listing.text
    # 🔴 assertion เชิงบวกคู่กัน — `size_format` ที่ derive มาจากสองฟิลด์นั้น
    # **ต้องออก** ตามสัญญา · ถ้าไม่มีบรรทัดนี้ การลบ `size_format` ออกจาก response
    # ทั้งดุ้นก็ทำให้เทสข้างบนเขียวขึ้นกว่าเดิม ซึ่งตรงข้ามกับเจตนา
    assert detail.json()["size_format"] == SizeFormat.ONE_SHEET.value


async def test_list_posters_never_exposes_adr0014_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ADR-0014 D5 — สัญญาของ list ไม่ขยาย (แนวเดียวกับ ADR-0009 D11)"""
    poster = Poster(
        title="List Item With Verification",
        price=Decimal("500"),
        condition_grade=PosterCondition.near_mint,
        published_at=PUBLISHED_AT,
        # 🔴 ต้องมีค่าจริง ไม่ใช่ NULL — แถวที่ทุกฟิลด์ว่างพิสูจน์ไม่ได้ว่าสัญญาไม่ขยาย
        # · ใช้คู่ที่ D22 อนุญาต (ไม่มี URL + มี note) ไม่ใช่คู่ที่ขัดกันเอง
        verification_status=VerificationStatus.NO_REFERENCE_FOUND,
        reference_note="ใบไทย ไม่มีแบบให้เทียบ",
    )
    db_session.add(poster)
    await db_session.commit()

    res = await client.get(API)

    assert res.status_code == 200, res.text
    item = res.json()["items"][0]
    leaked = (ADR0014_NEW_DETAIL_FIELDS | ADR0014_DB_ONLY_FIELDS) & item.keys()
    assert not leaked, f"PosterListItem มีฟิลด์ที่ไม่ควรมี: {leaked}"
