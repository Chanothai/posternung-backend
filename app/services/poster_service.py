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


def is_publishable(poster: Poster) -> bool:
    """โปสเตอร์ใบนี้แสดงบนหน้าร้านได้ถูกกฎ BR-05 ไหม

    คู่ Python ของ `poster_repository.graded_only()` ซึ่งเป็น predicate เดียวกันในชั้น SQL
    — เหตุผลเต็มอยู่ใน docstring ของฟังก์ชันนั้น **ห้ามเขียนซ้ำที่นี่**
    ถ้าแก้ตัวใดตัวหนึ่งต้องแก้อีกตัวด้วย เทส `test_sql_and_python_predicates_agree`
    ล็อกไว้ว่าสองตัวต้องตอบตรงกัน
    """
    return poster.condition_grade is not None


def assert_publishable(poster: Poster) -> None:
    """guard ที่ ADR-0003 §ช่องโหว่ที่ต้องปิด สั่งไว้ — เรียกก่อนตั้ง `status` เป็น `available`

    🔴 **วันนี้ยังไม่มี call site** — Phase 1 ไม่มีเส้นทางเปลี่ยน `status` เลยสักเส้น
    (ยืนยันด้วย grep: ไม่มีโค้ดที่ไหนเขียน `Poster.status`) ฟังก์ชันนี้จึงเป็นด่านที่
    **รอ** BLOCK 5.1 / admin write endpoint มาเรียก ไม่ใช่ด่านที่ทำงานอยู่แล้ว
    — อย่าอ่านการมีอยู่ของมันว่ากฎถูกบังคับแล้ว

    ตัวที่ปกป้องลูกค้าจริงวันนี้คือ `poster_repository.graded_only()` ที่กันไม่ให้
    ใบที่ไม่มีเกรดออกสู่ public API เลย · guard ตัวนี้กันอีกทางคือกันไม่ให้ *เกิด*
    แถวแบบนั้นเพิ่มเมื่อมีคนเขียน status ได้แล้ว
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

    if not is_publishable(poster):
        # ตอบ 404 เหมือนไม่มีแถวนี้ ไม่ใช่ 409 — ใบที่ไม่มีเกรดไม่โผล่ใน list อยู่แล้ว
        # (`graded_only()`) การตอบรหัสอื่นจะเป็นการยืนยันว่ามี id นี้อยู่จริงให้คนเดา id
        # และแอปก็ไม่มีอะไรทำต่อกับ 409 ต่างจาก 404 ที่ SCR-05 AC-6 มีหน้าจอรองรับแล้ว
        logger.info(
            "poster_id=%s: ซ่อนจากหน้าร้านเพราะยังไม่มี condition_grade (BR-05)",
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
        is_authenticated=poster.is_authenticated,
        authenticity_note=poster.authenticity_note,
        provenance=poster.provenance,
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
