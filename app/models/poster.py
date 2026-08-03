"""F2 Catalog models — posters, poster_images."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
    PosterStatus,
    PosterType,
    ReleaseRegion,
    RestorationStatus,
    SizeFormat,
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


class Poster(Base, TimestampMixin):
    __tablename__ = "posters"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_posters_price_non_negative"),
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
    # วันฉายที่ "พิมพ์อยู่บนตัวใบ" ไม่ใช่วันฉายจริงตามประวัติศาสตร์ — ADR-0009 D3
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # ปีใน billing block ของตัวใบ — ไม่ใช่ปีหนัง และไม่ใช่ print_year — ADR-0009 D3
    copyright_year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
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
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    poster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posters.id", ondelete="CASCADE"), nullable=False
    )
    # object key สัมพันธ์กับ bucket เช่น "posters/{poster_id}/{uuid4hex}.{ext}" —
    # ประกอบเป็น URL เต็มที่ชั้น service ผ่าน app.core.media.build_media_url เท่านั้น
    # (ADR-0006) ไม่เก็บ URL เต็มในคอลัมน์นี้
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    # หน่วย pixel ของ object ต้นฉบับที่ storage_key ชี้ไป (ไม่ใช่ขนาดที่แสดงผล และไม่ใช่
    # ขนาดกระดาษ — width_in/height_in บน Poster คือขนาดกระดาษ) nullable เพราะยังไม่มี
    # endpoint upload ที่จะอ่านค่านี้อัตโนมัติ (BLOCK 5.1)
    width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)

    poster: Mapped["Poster"] = relationship(back_populates="images")
