"""Business logic F2 Poster Catalog."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PosterNotFound, PosterNotPublishable
from app.core.media import build_media_url, is_public_storage_key
from app.models.poster import Poster, PosterImage
from app.repositories import poster_repository
from app.schemas.poster import (
    PaginatedPosterList,
    PosterDetailResponse,
    PosterFilterParams,
    PosterImageResponse,
    PosterListItem,
)

logger = logging.getLogger(__name__)


def _public_images(poster: Poster) -> list[PosterImage]:
    """กรองรูปให้เหลือเฉพาะ visibility `public` ก่อนถึงชั้น serializer (ADR-0007)

    ต้องกรองที่นี่ ไม่ใช่ปล่อยให้ `build_media_url()` เป็นด่านสุดท้าย — แถวเดียวที่
    ไม่ public จะทำให้ทั้งโปสเตอร์ตอบ 500 แทนที่จะซ่อนแค่รูปนั้น

    ที่มาของนิยาม visibility คือ ADR-0006 D2 · ADR-0006 วางการกรองนี้ไว้ที่ BLOCK 5.5
    (พร้อมคอลัมน์ `kind`) และห้ามมีแถว internal ก่อนหน้านั้น — **ADR-0007 คือมติที่
    ดึงมาทำก่อนกำหนด** และ **ไม่ได้กลับมติ D5**: `build_media_url()` ยัง raise เหมือนเดิม
    ตัวกรองนี้เป็นด่านหน้า ไม่ใช่การผ่อนปรนด่านหลัง

    ลำดับของรูปที่เหลือคงเดิมตาม `Poster.images.order_by`
    """
    public: list[PosterImage] = []
    skipped: list[uuid.UUID] = []
    for image in poster.images:
        if is_public_storage_key(image.storage_key):
            public.append(image)
        else:
            skipped.append(image.id)

    if skipped:
        # ค่า storage_key ห้ามลง log — ดูสกิล security-baseline §2 และ docstring
        # ของ build_media_url() · ใช้ id อ้างอิงแทนเพื่อไล่หาแถวใน DB ได้
        logger.warning(
            "poster_id=%s: ข้ามรูปที่ visibility ไม่ใช่ public %d/%d รูป image_ids=%s",
            poster.id,
            len(skipped),
            len(poster.images),
            skipped,
        )
    return public


def is_published(poster: Poster) -> bool:
    """มีคนกดเปิดขายใบนี้แล้วหรือยัง — ตัวตัดสินเดียวว่าลูกค้าเห็นใบนี้ได้ไหม

    คู่ Python ของ `poster_repository.published_only()` ซึ่งเป็น predicate เดียวกัน
    ในชั้น SQL — เหตุผลเต็มอยู่ใน docstring ของฟังก์ชันนั้น **ห้ามเขียนซ้ำที่นี่**
    ถ้าแก้ตัวใดตัวหนึ่งต้องแก้อีกตัวด้วย เทส `test_sql_and_python_predicates_agree`
    ล็อกไว้ว่าสองตัวต้องตอบตรงกัน
    """
    return poster.published_at is not None


def is_publishable(poster: Poster) -> bool:
    """ใบนี้ *มีสิทธิ์* ถูก publish ไหม — คนละคำถามกับ `is_published()`

    เป็นเงื่อนไขที่ BR-05 บังคับ (ราคาต้องแสดงคู่สภาพเสมอ จึงไม่มีเกรด = แสดงให้
    ถูกกฎไม่ได้เลย) · **เลิกเป็นตัวกรองหน้าร้านแล้วตั้งแต่ ADR-0013 D2** — ตัวกรอง
    หน้าร้านคือ `is_published()` / `published_only()` เท่านั้น

    ความหมายไม่เปลี่ยนจากเดิม แต่ตอนนี้มี **คู่ระดับ DB** แล้วคือ CHECK
    `ck_posters_published_requires_condition_grade` (ADR-0013 D3) ซึ่งบังคับ
    ความสัมพันธ์เดียวกันกับทุก writer รวมถึงเส้นทางที่ไม่ผ่าน service
    """
    return poster.condition_grade is not None


def assert_publishable(poster: Poster) -> None:
    """guard ก่อนเขียน `published_at` — ห้าม publish ใบที่ยังไม่มีเกรด (BR-05)

    🔴 **วันนี้ยังไม่มี call site** — ADR-0013 D4 ตั้งใจไม่สร้าง writer ของ
    `published_at` เลยในรอบนี้ ฟังก์ชันนี้จึงเป็นด่านที่ **รอ** INF-11 (เส้นทางเปิดขาย)
    มาเรียก ไม่ใช่ด่านที่ทำงานอยู่แล้ว — อย่าอ่านการมีอยู่ของมันว่ากฎถูกบังคับแล้ว

    ต่างจากเดิมตรงที่กฎข้อนี้ **มีคนบังคับให้แล้วที่ระดับ DB** คือ CHECK
    `ck_posters_published_requires_condition_grade` ซึ่งครอบทั้ง INSERT และ UPDATE
    ไม่ว่าใครเขียนด้วยเส้นทางไหน · หน้าที่ที่เหลือของ guard ตัวนี้คือแปลง
    `IntegrityError` ที่จะเกิดอยู่ดี ให้เป็น error ของโดเมนก่อนยิง SQL
    """
    if not is_publishable(poster):
        raise PosterNotPublishable()


def _primary_image_url(images: list[PosterImage]) -> str | None:
    """URL ของรูป primary จาก `images` ที่กรอง visibility มาแล้ว

    ถ้ารูป primary ถูกกรองทิ้งจะคืน `None` (แอปแสดง placeholder) — ตั้งใจไม่ fallback
    ไปรูป public ถัดไป เพราะจะเป็นการประดิษฐ์ "primary" ที่ DB ไม่ได้ทำเครื่องหมายไว้
    """
    for image in images:
        if image.is_primary:
            return build_media_url(image.storage_key)
    return None


def _to_list_item(poster: Poster) -> PosterListItem:
    return PosterListItem(
        id=poster.id,
        title=poster.title,
        price=poster.price,
        status=poster.status,
        condition_grade=poster.condition_grade,
        era_decade=poster.era_decade,
        studio=poster.studio,
        primary_image_url=_primary_image_url(_public_images(poster)),
    )


async def list_posters(
    session: AsyncSession, filters: PosterFilterParams
) -> PaginatedPosterList:
    posters, total = await poster_repository.list_with_filters(
        session,
        era_decade=filters.era_decade,
        condition_grade=filters.condition_grade,
        min_price=filters.min_price,
        max_price=filters.max_price,
        in_stock_only=filters.in_stock_only,
        limit=filters.limit,
        offset=filters.offset,
    )
    return PaginatedPosterList(
        items=[_to_list_item(poster) for poster in posters],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


async def get_poster_detail(
    session: AsyncSession, poster_id: uuid.UUID
) -> PosterDetailResponse:
    poster = await poster_repository.get_by_id(session, poster_id)
    if poster is None:
        raise PosterNotFound()

    if not is_published(poster):
        # ตอบ 404 เหมือนไม่มีแถวนี้ ไม่ใช่ 409 — ใบที่ยังไม่ publish ไม่โผล่ใน list
        # อยู่แล้ว (`published_only()`) การตอบรหัสอื่นจะเป็นการยืนยันว่ามี id นี้อยู่จริง
        # ให้คนเดา id และแอปก็ไม่มีอะไรทำต่อกับ 409 ต่างจาก 404 ที่ SCR-05 AC-6
        # มีหน้าจอรองรับแล้ว
        logger.info(
            "poster_id=%s: ซ่อนจากหน้าร้านเพราะยังไม่ถูกเปิดขาย (published_at เป็น NULL)",
            poster.id,
        )
        raise PosterNotFound()

    images = _public_images(poster)
    return PosterDetailResponse(
        id=poster.id,
        title=poster.title,
        price=poster.price,
        status=poster.status,
        condition_grade=poster.condition_grade,
        era_decade=poster.era_decade,
        studio=poster.studio,
        primary_image_url=_primary_image_url(images),
        tmdb_id=poster.tmdb_id,
        size=poster.size,
        description=poster.description,
        # ADR-0014 D4 — map ตรง ๆ เหมือนเดิม 🔴 ห้ามคำนวณจาก verification_status
        is_authenticated=poster.is_authenticated,
        authenticity_note=poster.authenticity_note,
        provenance=poster.provenance,
        # ADR-0014 D5 · reference_url ไม่ออก API รอบนี้ (D6)
        verification_status=poster.verification_status,
        verification_note=poster.verification_note,
        poster_type=poster.poster_type,
        release_region=poster.release_region,
        release_date_text=poster.release_date_text,
        release_date=poster.release_date,
        copyright_year=poster.copyright_year,
        size_format=poster.size_format,
        year=poster.year,
        restoration_status=poster.restoration_status,
        restoration_note=poster.restoration_note,
        images=[
            PosterImageResponse(
                id=image.id,
                url=build_media_url(image.storage_key),
                is_primary=image.is_primary,
                sort_order=image.sort_order,
            )
            for image in images
        ],
        created_at=poster.created_at,
    )
