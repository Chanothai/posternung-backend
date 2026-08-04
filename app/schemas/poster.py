"""Pydantic v2 schemas สำหรับ F2 Poster Catalog (ตรง docs/openapi.yaml)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    PosterCondition,
    PosterStatus,
    PosterType,
    ReleaseRegion,
    RestorationStatus,
    SizeFormat,
)


# ---- Responses ----
class PosterImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    is_primary: bool
    sort_order: int


class PosterListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    price: Decimal
    status: PosterStatus
    condition_grade: PosterCondition | None
    era_decade: int | None
    studio: str | None
    primary_image_url: str | None = None


class PosterDetailResponse(PosterListItem):
    tmdb_id: int | None
    size: str | None
    description: str | None
    is_authenticated: bool
    authenticity_note: str | None
    provenance: str | None
    # --- ADR-0009: คุณลักษณะเชิงพรรณนา (9 ฟิลด์ — ไม่รวม needs_review ตาม D11
    # รวม release_date_text ที่เพิ่มเข้ามาตาม D13 amendment แล้ว) ---
    poster_type: PosterType | None
    release_region: ReleaseRegion | None
    # ADR-0009 D13 (amendment) — ข้อความวันฉายตามที่พิมพ์บนใบ (observed) ไม่ตีความ
    release_date_text: str | None
    # วันฉายที่ "พิมพ์อยู่บนตัวใบ" ไม่ใช่วันฉายจริงตามประวัติศาสตร์ — ADR-0009 D3
    release_date: date | None
    # ปีใน billing block ของตัวใบ — ไม่ใช่ปีหนัง (year) และไม่ใช่ print_year — ADR-0009 D3
    copyright_year: int | None
    size_format: SizeFormat | None
    # ปีที่หนังฉาย — คนละอย่างกับ era_decade (ทศวรรษ) ที่อยู่ใน PosterListItem — ADR-0009 D3
    year: int | None
    restoration_status: RestorationStatus | None
    restoration_note: str | None
    images: list[PosterImageResponse]
    created_at: datetime


class PaginatedPosterList(BaseModel):
    items: list[PosterListItem]
    total: int
    limit: int
    offset: int


# ---- Requests ----
class PosterFilterParams(BaseModel):
    era_decade: int | None = None
    condition_grade: PosterCondition | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    in_stock_only: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
