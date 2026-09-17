"""Thin controller ของ SCR-07 สไลซ์ A (ADR-0037) — ห้ามมี DB query ตรงนี้ เรียก service ล้วน.

สองเส้นคนละ prefix (`/listings/...` กับ `/orders`) ⇒ router เดียวไม่ตั้ง `prefix`
ใช้ path เต็มตรง ๆ (เหมือนที่ `docs/api/openapi.yaml` ประกาศไว้)
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.limiter import limiter, reserve_rate_limit_key
from app.models.user import User
from app.schemas.order import OrderCreateRequest, OrderResponse, ReservationResponse
from app.services import order_service

router = APIRouter(tags=["Orders"])


@router.post(
    "/listings/{poster_id}/reserve",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    # ADR-0037 A5-D1 — 200 = reservation เดิมของผู้เรียกเอง (idempotent) · 201 = แถวใหม่
    # ประกาศไว้ให้ openapi.json สะท้อนสัญญา (`contract-drift-check` §2) — ตัวตัดสินอยู่ที่
    # `ReserveResult.created` ของ service ไม่ใช่ที่นี่
    responses={
        status.HTTP_200_OK: {
            "model": ReservationResponse,
            "description": "reservation เดิมของคุณเอง — ไม่สร้างแถวใหม่ ไม่ต่ออายุ",
        }
    },
)
# ADR-0037 D6 — คีย์ด้วย user_id ไม่ใช่ IP (`reserve_rate_limit_key` อ่าน
# `request.state.user_id` ที่ `get_current_user()` เขียนไว้ให้) · D3 — error_code
# ของ 429 ต้องมาจาก `error_message=` นี้ ไม่ใช่จากการ if บน path (ดู main.py)
# 🔴 **อัตราอ่านจาก `settings.reserve_rate_limit` ที่เดียว ห้ามเขียนเลขตรงนี้**
# (มติเจ้าของ 2026-09-15 ที่ GATE 3 — สองเพดานราย `user_id` · ตัวเลขอยู่ที่ config เท่านั้น)
# เหตุผลของตัวเลข และคำเตือนว่า **rate limit กัน "รัว" ไม่ได้กัน "ล็อกค้าง"**
# อยู่ที่ `app/core/config.py` ข้างค่าคงที่นั้น — ห้ามก๊อปมาที่นี่
# 🔴 **`scope=` ต้องเป็นค่าคงที่ ห้ามลบ** — `slowapi.Limiter` default `key_style="url"`
# (extension.py:148) ⇒ ถ้าไม่ตั้ง scope เอง limit_scope จะ fallback ไปใช้
# `request["path"]` ซึ่งเป็น **path จริงที่มี poster_id ฝังอยู่** ⇒ โปสเตอร์แต่ละใบ
# จะได้ bucket แยกกันเอง — ผู้ใช้จองคนละใบสลับกันจะไม่มีวันโดน 429 เลยแม้จะยิงรัว
# แค่ไหนก็ตาม (พิสูจน์แล้วจริง 2026-09-15: ยิง 25 ครั้งด้วย poster_id สุ่มทุกครั้ง
# ไม่มี 429 เลยสักครั้ง จนตั้ง scope คงที่แล้วถึงติด) — ค่าคงที่ทำให้ทุก poster_id
# ใช้ bucket เดียวกันตาม user_id ที่ key_func คืนมา ตรงตามเจตนาของ ADR-0037 D6
# `shared_limit()` ไม่ใช่ `limit()` โดยตั้งใจ — เป็นตัวเดียวที่ public API ของ
# slowapi เปิดพารามิเตอร์ `scope` ให้ตั้งค่าคงที่ได้ (`limit()` ไม่รับ `scope` เลย)
@limiter.shared_limit(
    settings.reserve_rate_limit,
    scope="reserve_listing",
    key_func=reserve_rate_limit_key,
    error_message="RESERVE_RATE_LIMITED",
)
async def reserve_listing(
    poster_id: uuid.UUID,
    request: Request,  # ชื่อต้องเป็น "request" เป๊ะ — slowapi บังคับ (extension.py:501)
    response: Response,  # ให้ slowapi inject rate-limit headers เข้า response นี้ (ไม่ใช้ตรงๆ — เหมือน auth.py:30)
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ReservationResponse:
    """BR-B1 — ปุ่ม "ซื้อเลย" คือการจองก่อน ไม่มี request body โดยตั้งใจ (ผู้จองมาจาก
    token · เวลามาจากนาฬิกา server เท่านั้น — security-baseline §4)."""
    reservation, created = await order_service.reserve_listing(
        session, poster_id, buyer_user_id=current_user.id, at=datetime.now(UTC)
    )
    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return reservation


@router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    data: OrderCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> OrderResponse:
    """ADR-0037 D1 — ที่อยู่เดินทาง inline มากับคำขอนี้ ไม่รับยอดเงินจาก client เลย
    สักฟิลด์ (item_price/shipping_fee มาจาก listing · total_amount คำนวณฝั่ง server)."""
    order = await order_service.create_order(
        session,
        data.reservation_id,
        buyer_user_id=current_user.id,
        shipping_address=data.shipping_address,
        at=datetime.now(UTC),
    )
    await session.commit()
    return order
