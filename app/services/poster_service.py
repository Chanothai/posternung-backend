"""Business logic F2 Poster Catalog."""

import logging
from enum import Enum
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PosterHasActiveReservation,
    PosterHasPendingCharge,
    PosterNotAvailable,
    PosterNotFound,
    PosterNotPublishable,
    PosterSoldReasonRequired,
)
from app.core.media import build_media_url, is_public_storage_key
from app.models.enums import PosterStatus
from app.models.enums import PosterCondition
from app.models.poster import Poster, PosterImage
from app.models.poster_attribute_review import PosterAttributeReview
from app.repositories import poster_repository, reservation_repository
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


class PublishBlocker(str, Enum):
    """เหตุผลที่ใบหนึ่ง *ยังไม่มีสิทธิ์* ถูก publish — ADR-0026 **D8**

    เป็น **enum ไม่ใช่ข้อความ** โดยตั้งใจ: กฎอยู่ที่นี่ ส่วนถ้อยคำที่คนอ่านอยู่ที่
    `scripts/seed/manual_entry.py` ซึ่งเป็น UI เดียวของ operator · ถ้าเอาข้อความ
    มาไว้ที่นี่ด้วย เราจะได้แหล่งความจริงที่สองของ *ถ้อยคำ* แทนที่จะเป็นของ *กฎ*
    """

    NO_CONDITION_GRADE = "NO_CONDITION_GRADE"
    NO_FRONT_IMAGE = "NO_FRONT_IMAGE"


def publish_blockers(
    *, condition_grade: PosterCondition | None, front_image_count: int
) -> tuple[PublishBlocker, ...]:
    """🔴 **นิยามเดียวของ "ใบนี้มีสิทธิ์ถูก publish ไหม"** — ADR-0026 **D8**

    ว่าง = มีสิทธิ์ · ทุกผู้เรียกต้องผ่านที่นี่ **ห้ามเขียนเงื่อนไขซ้ำที่อื่น**
    กติกานี้เคยกระจายอยู่ 3 ที่ (CHECK ระดับ DB · ฟังก์ชันนี้ · ด่านของ
    `manual_entry.py`) และ `INF-27` AC-12 ห้ามไม่ให้มีที่ที่ 4 เกิดขึ้น

    **ทำไมรับค่าที่นับมาแล้ว ไม่รับ ORM `Poster`** (ADR-0026 D8 §ข้อจำกัด)
    1. `scripts/seed/manual_entry.py` ไม่ได้ทำงานกับ ORM object — มันมี `PosterState`
       ของตัวเองที่ประกอบจากผลลัพธ์ SQL
    2. การแตะ `poster.images` ที่ยังไม่ถูก `selectinload` ในบริบท async คือ
       **`MissingGreenlet`** ไม่ใช่ lazy-load เงียบ ๆ — ผู้เรียกจึงต้องนับมาเอง

    **BR-05** (ราคาต้องแสดงคู่สภาพ ⇒ ไม่มีเกรด = แสดงให้ถูกกฎไม่ได้) มีคู่ระดับ DB
    คือ CHECK `ck_posters_published_requires_condition_grade` (ADR-0013 D3)
    · **BR-06** (ต้องมีรูปของจริงก่อนเปิดขาย) **ไม่มีคู่ระดับ DB และจะไม่มี** —
    "อย่างน้อยหนึ่งแถวในอีกตาราง" เป็นเงื่อนไขข้ามแถวที่ CHECK ทำไม่ได้ ต้องใช้
    trigger ซึ่ง ADR-0026 D8 ตัดสินแล้วว่าไม่ทำ ⇒ **ด่านนี้คือด่านเดียวที่มี**
    """
    blockers: list[PublishBlocker] = []
    if condition_grade is None:
        blockers.append(PublishBlocker.NO_CONDITION_GRADE)
    if front_image_count < 1:
        blockers.append(PublishBlocker.NO_FRONT_IMAGE)
    return tuple(blockers)


def is_publishable(
    *, condition_grade: PosterCondition | None, front_image_count: int
) -> bool:
    """ใบนี้ *มีสิทธิ์* ถูก publish ไหม — คนละคำถามกับ `is_published()`

    **เลิกเป็นตัวกรองหน้าร้านแล้วตั้งแต่ ADR-0013 D2** — ตัวกรองหน้าร้านคือ
    `is_published()` / `published_only()` เท่านั้น

    🔴 **เปลี่ยน signature 2026-08-16 (ADR-0026 D8)** — เดิมรับ ORM `Poster` แล้วดู
    `condition_grade` อย่างเดียว · เหตุผลที่ต้องเปลี่ยนอยู่ที่ `publish_blockers()`
    """
    return not publish_blockers(
        condition_grade=condition_grade, front_image_count=front_image_count
    )


def assert_publishable(
    *, condition_grade: PosterCondition | None, front_image_count: int
) -> None:
    """guard ก่อนเขียน `published_at` (BR-05 · BR-06)

    🔴 **วันนี้ยังไม่มี call site** — ADR-0013 D4 ตั้งใจไม่สร้าง writer ของ
    `published_at` ในชั้น service เลย ฟังก์ชันนี้จึงเป็นด่านที่ **รอ** อยู่
    ไม่ใช่ด่านที่ทำงานอยู่แล้ว — อย่าอ่านการมีอยู่ของมันว่ากฎถูกบังคับแล้ว
    · ผู้ที่บังคับกฎนี้จริงวันนี้คือ `scripts/seed/manual_entry.py` ซึ่งเรียก
    `publish_blockers()` ตัวเดียวกัน (ADR-0026 D8 · INF-27 AC-12)
    """
    if publish_blockers(
        condition_grade=condition_grade, front_image_count=front_image_count
    ):
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
        # ADR-0014 D5 · reference_url ไม่ออก API รอบนี้ (D24 — ยังไม่มีข้อมูล)
        verification_status=poster.verification_status,
        reference_note=poster.reference_note,
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
                kind=image.kind,
                is_primary=image.is_primary,
                sort_order=image.sort_order,
            )
            for image in images
        ],
        created_at=poster.created_at,
        # ADR-0013 Amendment A-D3 — ต่างจาก published_at ตรงที่ฟิลด์นี้ออก public API
        # จริง (ไม่ใช่ค่าคงที่สำหรับทุกแถวที่ผ่าน published_only() มา — NULL สำหรับของ
        # ที่ยังขายอยู่ มีค่าสำหรับของที่ขายแล้ว) เขียนโดย mark_sold() เท่านั้น
        sold_at=poster.sold_at,
    )


async def _pending_charge_for(
    session: AsyncSession, poster_id: uuid.UUID
) -> None:  # pragma: no cover — ไม่มีทางเป็นจริงวันนี้ ดู docstring ของ mark_sold()
    """จุดต่อสำหรับ charge ที่ยัง `pending` (skill `stock-integrity` ข้อ 7 · ADR-0002)

    วันนี้ไม่มีตาราง `payments` เลย ไม่มีอะไรให้ถาม — คืน `None` เสมอ ตามรูปของ
    `_payment_checker` ในสกิล `stock-integrity` (`คืน "ไม่มี" เสมอได้ แต่ต้องมีจุดต่อไว้
    ตั้งแต่แรก`) เพื่อให้รอบ `SCR-06` เป็นการ *เติมโค้ด* ไม่ใช่ *รื้อ*
    """
    del session, poster_id  # ยังไม่มีอะไรให้ query — เก็บ signature ไว้ให้ SCR-06 เติม
    return None


async def mark_sold(
    session: AsyncSession,
    poster_id: uuid.UUID,
    *,
    sold_at: datetime,
    reviewed_by: str,
    reviewed_at: datetime,
    reason: str,
    source: str,
) -> Poster:
    """บันทึกว่าโปสเตอร์นี้ถูกขายไปแล้วนอกระบบ — **writer เดียวของ `posters.status`**
    ในทั้งระบบ (ADR-0025 D1 · A-D2 · `poster-database` §3)

    ลำดับในทรานแซกชันเดียว (ADR-0025 D3 — ห้ามเปลี่ยนลำดับ):

    1. ล็อกแถว `posters` ด้วย `FOR UPDATE` (`stock-integrity` §มติที่ตัดสินแล้ว —
       จุดตัดสต็อกมีจุดเดียว)
    2. เจอ reservation ที่ยัง `active` บนใบนี้ → **ปฏิเสธทั้งรายการ** ห้ามพลิกเป็น
       `expired` ห้ามลบ ห้ามเขียนอะไรลง `reservations` เลยสักคอลัมน์ — มีลูกค้าค้าง
       กลางทางจ่ายเงินที่ระบบคืนเงินให้ไม่ได้ (ADR-0002) ให้คนไปตัดสินเอง
    3. จุดต่อสำหรับ charge ที่ยัง pending (ข้อ 7) — วันนี้ตรวจไม่ได้เพราะไม่มีตาราง
       `payments` (ดู `_pending_charge_for()`)
    4. `status` เดิมต้องเป็น `available` เท่านั้น — ขายซ้ำ/ขายใบที่กำลังจองอยู่
       (ซึ่งข้อ 2 ควรจับไปแล้ว) = ปฏิเสธ ไม่ใช่ no-op เงียบ
    5. เขียน `status = sold` **และ `sold_at` พร้อมกัน** (AC-2 — ไม่มีทางได้แถวที่
       `sold` แต่ `sold_at` เป็น `NULL`; มี CHECK `ck_posters_sold_requires_sold_at`
       เป็นชั้นที่สองระดับ DB)
    6. บันทึก **ใคร (`reviewed_by`) · เมื่อไหร่ (`reviewed_at`) · เพราะอะไร (`reason`)**
       ลง `poster_attribute_reviews` ในทรานแซกชันเดียวกัน — ประกอบแถว audit ในตัว
       service เอง ไม่ใช่ในลูปของ CLI (ADR-0025 D1 ข้อ 2)

    🔴 **ห้ามแตะ `published_at` เลยสักบรรทัด** (AC-5 · ADR-0013 D6 · A-D1) —
    `published_at` ตอบ "อยู่บนร้านไหม" ส่วนฟังก์ชันนี้ตอบ "ซื้อได้ไหม" คนละแกนกัน

    `sold_at` / `reviewed_at` เป็นพารามิเตอร์บังคับ **ไม่มี default เป็น `now()`**
    (ADR-0025 D4 · ADR-0010 D5) — ด่านปฏิเสธเวลาอนาคตอยู่ที่ `main()` ของ CLI ผู้เรียก
    (`assert_not_in_the_future()` ของ `scripts/seed/_shared.py`) **ไม่ใช่ที่นี่**
    เพราะฟังก์ชันนี้ต้องไม่อ่านนาฬิกาเอง (`app/` ไม่ import `scripts/`)

    ไม่ commit — ผู้เรียก (CLI วันนี้) เป็นคนคุม transaction boundary เอง เหมือนที่
    ทุกฟังก์ชันอื่นของ `poster_service` รับ `session` เข้ามาแทนที่จะเปิดเอง
    """
    if not reason or not reason.strip():
        # AppError subclass ไม่ใช่ ValueError เปล่า ๆ — ValueError ไม่ผ่าน
        # `except AppError` ของ CLI และจะกลายเป็น 500 ดิบตอน SCR-06 ต่อ HTTP
        # (พบจาก code-critic รอบ 1 ของ INF-24, Low)
        raise PosterSoldReasonRequired()

    poster = await poster_repository.get_for_update(session, poster_id)
    if poster is None:
        raise PosterNotFound()

    active_reservation = await reservation_repository.get_active_reservation(
        session, poster_id
    )
    if active_reservation is not None:
        raise PosterHasActiveReservation(
            details=[{"reservation_id": str(active_reservation.id)}]
        )

    pending_charge = await _pending_charge_for(session, poster_id)
    if pending_charge is not None:  # pragma: no cover — ไม่มีทางเป็นจริงวันนี้
        # error ของตัวเอง ไม่ใช่ PosterNotAvailable — "charge ค้าง" กับ "status ไม่ใช่
        # available" เป็นคนละสาเหตุกัน (พบจาก code-critic รอบ 1 ของ INF-24, Low)
        raise PosterHasPendingCharge()

    if poster.status != PosterStatus.available:
        raise PosterNotAvailable()

    value_before = poster.status.value
    poster.status = PosterStatus.sold
    poster.sold_at = sold_at

    session.add(
        PosterAttributeReview(
            poster_id=poster.id,
            field="status",
            value_before=value_before,
            value_after=PosterStatus.sold.value,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            source=source,
            reason=reason,
        )
    )
    await session.flush()
    return poster
