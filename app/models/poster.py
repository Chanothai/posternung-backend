"""F2 Catalog models — posters, poster_images."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CreatedAtMixin, TimestampMixin, uuid_pk
from app.models.enums import (
    PosterCondition,
    PosterImageKind,
    PosterStatus,
    PosterType,
    ReleaseRegion,
    RestorationStatus,
    SizeFormat,
    VerificationStatus,
)

# create_type=False → จัดการ CREATE/DROP TYPE เองใน migration
poster_status_enum = PgEnum(PosterStatus, name="poster_status", create_type=False)
poster_condition_enum = PgEnum(
    PosterCondition, name="poster_condition", create_type=False
)
# ADR-0009 — enum ใหม่ 4 ตัว (UPPERCASE ตาม poster-database §5)
poster_type_enum = PgEnum(PosterType, name="poster_type", create_type=False)
release_region_enum = PgEnum(ReleaseRegion, name="release_region", create_type=False)
size_format_enum = PgEnum(SizeFormat, name="size_format", create_type=False)
restoration_status_enum = PgEnum(
    RestorationStatus, name="restoration_status", create_type=False
)
# ADR-0014 — ผลการเทียบกับฐานข้อมูลอ้างอิง (UPPERCASE ตาม poster-database §5)
verification_status_enum = PgEnum(
    VerificationStatus, name="verification_status", create_type=False
)
# ADR-0026 D1/D2 — ชนิดของรูป (UPPERCASE ตาม poster-database §5)
poster_image_kind_enum = PgEnum(
    PosterImageKind, name="poster_image_kind", create_type=False
)


class Poster(Base, TimestampMixin):
    __tablename__ = "posters"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_posters_price_non_negative"),
        # ADR-0013 D3 — ห้ามเปิดขายใบที่ยังไม่มีเกรด (BR-05) · ต้องอยู่ระดับ DB
        # เพราะ scripts/seed/seed_posters.py เขียน insert()/update() เข้าตารางตรง ๆ
        # ไม่ผ่าน service · ข้อความต้องตรงกับ migration เป๊ะ
        CheckConstraint(
            "published_at IS NULL OR condition_grade IS NOT NULL",
            name="ck_posters_published_requires_condition_grade",
        ),
        # ADR-0025 D2 — ไม่มีทางได้แถวที่ sold แต่ไม่รู้ว่าเมื่อไหร่ (ขายแล้วไม่รู้เวลา
        # แย่กว่าไม่มีคอลัมน์เลย — A-D3) ต้องอยู่ระดับ DB เพราะ
        # scripts/seed/seed_posters.py --status sold เขียน insert() ตรง ไม่ผ่าน
        # poster_service.mark_sold() เลย · ข้อความต้องตรงกับ migration เป๊ะ
        CheckConstraint(
            "status <> 'sold' OR sold_at IS NOT NULL",
            name="ck_posters_sold_requires_sold_at",
        ),
        Index("ix_posters_status_era_price", "status", "era_decade", "price"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # canonical movie id (TMDB) — future-proof สำหรับ marketplace (ดู database-design.md §8)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[PosterStatus] = mapped_column(
        poster_status_enum,
        nullable=False,
        server_default=PosterStatus.available.value,
    )
    is_unique: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    condition_grade: Mapped[PosterCondition | None] = mapped_column(
        poster_condition_enum, nullable=True
    )
    size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    era_decade: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    studio: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_authenticated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    authenticity_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- ADR-0009: คุณลักษณะเชิงพรรณนา — NULL = ยังไม่มีใครตรวจ, ห้ามตั้ง
    # server_default เป็น UNKNOWN (ADR-0009 D2) ทุกตัวจึงไม่มี server_default
    poster_type: Mapped[PosterType | None] = mapped_column(
        poster_type_enum, nullable=True
    )
    release_region: Mapped[ReleaseRegion | None] = mapped_column(
        release_region_enum, nullable=True
    )
    # ADR-0009 D13 (amendment) — วันฉาย "ตามที่พิมพ์บนใบ" คัดมาตรงตัว ไม่ตีความ
    # (observed) แยกจาก release_date ซึ่งเป็นค่า derived จาก parser เดียว
    # (app.core.release_date.parse_release_date_text) — เขียนเสมอเมื่ออ่านวันฉาย
    # จากใบได้ไม่ว่าจะครบหรือไม่ครบ
    release_date_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # วันฉายที่ "พิมพ์อยู่บนตัวใบ" ไม่ใช่วันฉายจริงตามประวัติศาสตร์ — ADR-0009 D3
    # writer เดียวคือ app.core.release_date.parse_release_date_text (D13 ข้อ 2) —
    # ห้ามกรอกตรงๆ โดยไม่มี release_date_text รองรับ
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # ปีใน billing block ของตัวใบ — ไม่ใช่ปีหนัง และไม่ใช่ print_year — ADR-0009 D3
    copyright_year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # --- ADR-0009 D16: ขนาดที่ **วัดจากใบจริง** หน่วยนิ้ว ---
    # เป็น input ตัวเดียวที่ D16 ยอมรับสำหรับ `size_format` · คอลัมน์ `size`
    # ข้างบนเป็น `size_guess` ที่ D4 ห้ามใช้เป็น input ไปแล้ว (และของจริงเป็น
    # สตริงเดียวกันทั้งแคตตาล็อก จึงไม่มีสารสนเทศต่อใบ) — ดู app/core/size_format.py
    #
    # 🔴 **เก็บตัวเลขไว้แม้ map เป็น `ONE_SHEET` ได้แล้ว** — 27×41 กับ 27×40 ได้
    # `size_format` ตัวเดียวกัน แต่ 27×41 เป็นสัญญาณของงานพิมพ์ยุคเก่า ทิ้งตัวเลข
    # คือทิ้งข้อมูลที่มีค่าที่สุดของใบนั้น (D16)
    #
    # ⚠️ **ตอนที่ wire เข้า API: ประกาศเป็น `float` ใน Pydantic ไม่ใช่ `Decimal`**
    # สัญญาเขียนไว้ว่า `type: [number, "null"]` แต่ Pydantic v2 serialize `Decimal`
    # เป็น JSON **string** เสมอ — เป็น contract drift ตัวเดียวกับที่เคยเกิดกับ
    # `PosterListItem.price` มาแล้ว (skill `poster-database` §3) · วันนี้ยังไม่ drift
    # เพราะทั้งสองฟิลด์ติด `x-status: DRAFT` และยังไม่มีใน `PosterDetailResponse`
    width_in: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    height_in: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    # derived — writer เดียวคือ `app.core.size_format.derive_size_format()` ซึ่งรับ
    # เฉพาะ width_in/height_in ข้างบน (D4: mapping ตัวเดียว · D16: input คือการวัด)
    size_format: Mapped[SizeFormat | None] = mapped_column(
        size_format_enum, nullable=True
    )
    # ปีที่หนังฉาย — คนละอย่างกับ era_decade (ทศวรรษ) — ADR-0009 D3
    year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    restoration_status: Mapped[RestorationStatus | None] = mapped_column(
        restoration_status_enum, nullable=True
    )
    restoration_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ธงงานภายใน (ADR-0009 D6) — ห้ามออก public API (D11)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    # ADR-0013 D1 — แกนที่สองแยกจาก `status`: "ตั้งวางบนชั้นให้ลูกค้าเห็นหรือยัง"
    # NULL = ยังไม่เปิดขาย · ไม่มี server_default (แนวเดียวกับ ADR-0009 D2)
    # ธงงานภายใน ไม่ออก public API (D5 · precedent ADR-0009 D11)
    # 🔴 ยังไม่มี writer เลยโดยตั้งใจ (D4) — ทุกแถววันนี้เป็น NULL
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ADR-0027 D1/D2 (INF-28) — เวลาที่ **คน** หยิบใบจริงขึ้นมาตรวจครบทุกมิติแล้วเซ็นรับ
    # NULL = ยังไม่เคยมีใครตรวจใบนี้ · **ไม่ใช่** "ตรวจแล้วไม่ผ่าน" (ไม่มีสถานะหลัง —
    # ใบที่ตรวจแล้วพบว่าผิดให้แก้ค่าแล้วเซ็น ไม่ใช่ทำเครื่องหมายว่าตก)
    # ไม่มี server_default (แนวเดียวกับ `published_at` ข้างบนและ `sold_at` ข้างล่าง)
    # 🔴 invariant `published_at IS NOT NULL ⇒ verified_at IS NOT NULL` **วันนี้บังคับ
    # แค่ฝั่ง Python** ที่ `poster_service.is_publishable()` — CHECK ระดับ DB ยังไม่ลง
    # เพราะมี 116 แถวที่ละเมิดอยู่ (ADR-0027 D4) **ห้ามอ่านคอลัมน์นี้ว่ามีด่าน DB แล้ว**
    # ธงงานภายใน ไม่ออก public API (D10 · precedent ADR-0013 D5 · ADR-0009 D11)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ADR-0025 D1/D2/D4 (INF-24) — เวลาที่ "คนตัดสินว่าขายไปแล้ว" ไม่ใช่เวลาที่
    # สคริปต์รัน · writer เดียวคือ poster_service.mark_sold() ซึ่งเขียนพร้อม status
    # ในทรานแซกชันเดียว · ไม่มี server_default (แนวเดียวกับ published_at ข้างบน)
    # 🔴 ต่างจาก published_at ตรงที่ฟิลด์นี้ออก public API (PosterDetailResponse
    # เท่านั้น — ADR-0013 Amendment A-D3) เพราะเป็นข้อเท็จจริงของสินค้า ไม่ใช่ธง ops
    sold_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- ADR-0014 D2: บันทึกว่า "เทียบกับอะไรและพบอะไร" ไม่ใช่การรับรองความแท้
    # NULL = ยังไม่มีใครเทียบใบนี้ (D3) จึงไม่มี server_default ทั้งสามตัว
    # 🔴 ยังไม่มี writer เลยโดยตั้งใจ (D7) — ทุกแถววันนี้เป็น NULL · writer คือ INF-13
    # 🔴 ห้าม derive `is_authenticated` จากค่าพวกนี้ (D4) — ฟิลด์นั้นเลิกใช้แล้วและ
    # จะถูกลบใน INF-14 ไม่ใช่ถูกคำนวณต่อ
    verification_status: Mapped[VerificationStatus | None] = mapped_column(
        verification_status_enum, nullable=True
    )
    # เหตุผลตอน "หาไม่เจอ" อย่างเดียว — ไม่ใช่คำบรรยายความต่าง (ADR-0014 D22)
    # 🔴 มีค่าพร้อมกับ reference_url ไม่ได้ = ข้อมูลขัดกันเอง (INF-13 AC-4)
    # ‹เดิมชื่อ verification_note · เปลี่ยนชื่อที่ D22 เพราะชื่อเก่ากว้างกว่าเนื้อหา›
    reference_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # แหล่งอ้างอิงที่เปิดดูแล้วเจอ — ประตู OD-3 เปิดแล้วที่ D24 แต่การ "ขึ้นจอ" ยังติด
    # D5.1/OD-2 ซึ่งเป็นคนละด่าน · มีค่า = REFERENCE_FOUND (D22)
    reference_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    images: Mapped[list["PosterImage"]] = relationship(
        back_populates="poster", order_by="PosterImage.sort_order"
    )


class PosterImage(Base, CreatedAtMixin):
    __tablename__ = "poster_images"
    __table_args__ = (
        Index("ix_poster_images_poster", "poster_id", "sort_order"),
        # กันรูป primary ซ้ำต่อโปสเตอร์ (partial unique)
        Index(
            "uq_poster_images_primary",
            "poster_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        # กันสองแถวชี้ object เดียวกัน (ADR-0006 D2) — ถ้าอนาคตมีเคสรูปเดียวผูกหลาย
        # โปสเตอร์จริง (เช่น COA ชุดเดียว) ต้องถอด constraint นี้ออก
        UniqueConstraint("storage_key", name="uq_poster_images_storage_key"),
        CheckConstraint(
            "(width_px IS NULL OR width_px > 0) AND (height_px IS NULL OR height_px > 0)",
            name="ck_poster_images_dimensions_positive",
        ),
        CheckConstraint(
            "(width_px IS NULL) = (height_px IS NULL)",
            name="ck_poster_images_dimensions_paired",
        ),
        # 🔴 ADR-0026 D3 — `kind` กับ `is_primary` พูดคนละเรื่อง (เนื้อหา vs ตำแหน่งโชว์)
        # และ CHECK ตัวนี้คือ **สิ่งเดียวที่ทำให้ทั้งสองโกหกกันไม่ได้** · แถว
        # is_primary=true บนรูป BACK/DEFECT เขียนลงไม่ได้เลยไม่ว่าผ่านทางไหน ซึ่งเป็น
        # เหตุผลที่ SCR-03 ไม่ต้องเปลี่ยน query เลย (primary_image_url เป็น FRONT เสมอ)
        # **ห้ามถอดโดยอ้างว่าซ้ำซ้อนกับ kind** — ถอดเมื่อไหร่ = หน้า Home โชว์รูปหลังได้เงียบ ๆ
        CheckConstraint(
            "NOT is_primary OR kind = 'FRONT'",
            name="ck_poster_images_primary_is_front",
        ),
        # 🔴 ADR-0026 D5 — แถบตายตัวต่อ kind ทำให้ "เรียงด้วย sort_order อย่างเดียว"
        # ได้ลำดับกลุ่ม FRONT → BACK → DEFECT ถูกเสมอ **ทั้งฝั่ง API และฝั่งแอปที่เรียงเอง
        # อีกชั้น** (poster_detail_image_gallery.dart sort ด้วย (isPrimary, sortOrder)
        # ⇒ ถ้าลำดับอยู่แค่ใน ORDER BY ของ server แอปจะเรียงกลับแล้วการจัดกลุ่มพัง)
        # · เพดาน 100 รูปต่อกลุ่มต่อใบ — ล้นแล้วต้อง **พังดังตอน insert** ไม่ใช่เรียงผิด
        # เงียบ ๆ (รูปที่ 101 ของ FRONT จะไปโผล่กลาง BACK)
        # · kind ที่ 4 วันหน้าได้แถบ 300–399 ต่อท้าย ⇒ ไม่ต้อง renumber แถวเดิม
        CheckConstraint(
            "(kind = 'FRONT' AND sort_order BETWEEN 0 AND 99)"
            " OR (kind = 'BACK' AND sort_order BETWEEN 100 AND 199)"
            " OR (kind = 'DEFECT' AND sort_order BETWEEN 200 AND 299)",
            name="ck_poster_images_sort_order_band",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    poster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posters.id", ondelete="CASCADE"), nullable=False
    )
    # object key สัมพันธ์กับ bucket เช่น "posters/{poster_id}/{uuid4hex}.{ext}" —
    # ประกอบเป็น URL เต็มที่ชั้น service ผ่าน app.core.media.build_media_url เท่านั้น
    # (ADR-0006) ไม่เก็บ URL เต็มในคอลัมน์นี้
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # 🔴 ใหม่ 2026-08-16 (ADR-0026 D1) — "รูปนี้คืออะไร" · **ไม่มี server_default
    # โดยตั้งใจ** (หลักเดียวกับ piece_no ของ ADR-0024 A-D5): ค่า default ทำให้ลืมใส่
    # แล้วผ่านเงียบ ๆ ซึ่งบนตารางที่ผู้ซื้อเห็นผลโดยตรงราคาสูงเกินกว่าความสะดวก
    kind: Mapped[PosterImageKind] = mapped_column(
        poster_image_kind_enum, nullable=False
    )
    # 🔴 คนละเรื่องกับ `kind` — อันนี้คือ "รูปนำในลิสต์" ไม่ใช่เนื้อหาของรูป (ADR-0026 D3)
    # · ผูกกับ kind ด้วย ck_poster_images_primary_is_front ดู __table_args__
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # ⚠️ ADR-0026 D5 — `server_default="0"` ที่มีมาแต่เดิม **ใช้ได้เฉพาะกับ `FRONT`**
    # แล้ว เพราะ 0 อยู่ในแถบของ FRONT เท่านั้น · แถว BACK/DEFECT ที่ insert โดยไม่ระบุ
    # `sort_order` จะชน ck_poster_images_sort_order_band **ซึ่งเป็นพฤติกรรมที่ถูกต้อง**
    # (ผู้เขียนต้องคิดเรื่องลำดับเอง ไม่ใช่ให้ค่า default พาไปอยู่ผิดกลุ่มเงียบ ๆ)
    # · คงค่า default ไว้เพื่อไม่ให้เป็น breaking change กับผู้เขียนเดิมที่ลงแต่ FRONT
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    # หน่วย pixel ของ object ต้นฉบับที่ storage_key ชี้ไป (ไม่ใช่ขนาดที่แสดงผล และไม่ใช่
    # ขนาดกระดาษ — width_in/height_in บน Poster คือขนาดกระดาษ) nullable เพราะยังไม่มี
    # endpoint upload ที่จะอ่านค่านี้อัตโนมัติ (BLOCK 5.1)
    width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)

    poster: Mapped["Poster"] = relationship(back_populates="images")
