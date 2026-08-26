"""`orders` / `order_status_history` table access — thin DB layer (ไม่มี business logic)

ตัวตัดสินว่า transition ไหนถูกกฎอยู่ที่ `app/core/state_machine.py` และผู้เขียน
`orders.status` มีไฟล์เดียวคือ `app/services/order_service.py` (ADR-0033 D1/D5) —
ไฟล์นี้ทำแค่ **ยิง SQL ให้** ไม่ตัดสินอะไรเลย
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatusHistory

# ADR-0033 D6 · ADR-0032 D5 — `order_no` ใช้ **วันที่ไทย** ไม่ใช่วันที่ UTC
# (ต่างกันจริงช่วง 17:00–23:59 UTC ซึ่งเทสที่รันกลางวันจับไม่ได้)
BANGKOK = ZoneInfo("Asia/Bangkok")

ORDER_NO_PREFIX = "PN"


async def get_for_update(session: AsyncSession, order_id: uuid.UUID) -> Order | None:
    """`SELECT ... FOR UPDATE` แถว `orders`

    🔴 **ต้องถูกเรียก *หลัง* ล็อกแถว `posters` เสมอ** — ลำดับล็อกเดียวทั้งระบบคือ
    `posters → orders` (ADR-0033 D3) การสลับลำดับระหว่างสองเส้นทาง = deadlock

    `populate_existing=True` ด้วยเหตุผลเดียวกับ `poster_repository.get_for_update()`
    (identity map จะคืน object เดิมที่โหลดมา *ก่อน* ล็อก ทำให้ตัดสินด้วยค่าเก่า)
    """
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return await session.scalar(stmt)


async def get_poster_id(session: AsyncSession, order_id: uuid.UUID) -> uuid.UUID | None:
    """อ่านเฉพาะ `poster_id` เพื่อไปล็อกแถว `posters` ก่อน (ADR-0033 D3)

    อ่าน **ไม่ล็อก** โดยตั้งใจ — `poster_id` เขียนครั้งเดียวตอนสร้างออร์เดอร์แล้ว
    ไม่มีใครแก้อีกเลย จึงไม่มี race ให้กัน และการล็อก `orders` ก่อนตรงนี้จะกลับ
    ลำดับล็อกที่ D3 บังคับไว้
    """
    return await session.scalar(select(Order.poster_id).where(Order.id == order_id))


async def next_order_no(session: AsyncSession, *, at: datetime) -> str:
    """`PN-YYMMDD-NNNN` ของ **วันที่ไทย** — สร้างใต้ `pg_advisory_xact_lock` (ADR-0033 D6)

    ทำไมต้องมีล็อก: `orders.order_no` เป็น `unique` ⇒ อ่าน `max()` แล้วเขียนโดยไม่มี
    อะไรคั่นคือ **read-then-write เปล่า ๆ** ที่ `stock-integrity` ห้ามไว้ตรงตัว
    สองคนสั่งซื้อพร้อมกันจะได้ `IntegrityError`

    ล็อกเป็นของ **ทรานแซกชัน** — ปลดเองตอน commit/rollback ไม่มีอะไรให้ลืมปล่อย
    และไม่ต้องมีตารางตัวนับใหม่

    🔴 ตัวเลขรันมาจากการนับของจริงในตาราง ไม่ใช่ตัวนับที่หลุด sync ได้
    (proposal §1 ข้อ 4 — "สถานะเป็นความจริง ตัวนับไม่ใช่")
    """
    local_date = at.astimezone(BANGKOK).date()
    await session.execute(
        select(
            func.pg_advisory_xact_lock(
                cast(func.hashtext(f"order_no:{local_date.isoformat()}"), BigInteger)
            )
        )
    )

    prefix = f"{ORDER_NO_PREFIX}-{local_date:%y%m%d}-"
    # 🔴 **เทียบเป็นตัวเลข ไม่ใช่สตริง** ‹แก้ 2026-08-26 ตาม `code-critic`›
    # `max()` แบบสตริงจะหยุดโตที่ `"9999"` (เพราะ `"10000" < "9999"` ตามลำดับตัวอักษร)
    # ⇒ ใบที่ 10001 ของวันจะได้เลขซ้ำแล้วชน `unique` เงียบ ๆ · วันนี้ไกลจากเพดานนั้นมาก
    # แต่เป็นความพังที่จะเกิดตอนขายดีที่สุด ซึ่งเป็นวันที่แย่ที่สุดที่จะพัง
    highest = await session.scalar(
        select(
            func.max(cast(func.substr(Order.order_no, len(prefix) + 1), Integer))
        ).where(Order.order_no.startswith(prefix))
    )
    running = (highest or 0) + 1
    # `:04d` เป็น **ความกว้างขั้นต่ำ** ไม่ใช่เพดาน — เลข 5 หลักยังพอดี `String(20)`
    return f"{prefix}{running:04d}"


def add_status_history(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    from_status: str | None,
    to_status: str,
    actor_user_id: uuid.UUID | None,
    reason: str | None,
) -> OrderStatusHistory:
    """ร่องรอยหนึ่งแถวต่อหนึ่งจุดเปลี่ยน — ไม่ `flush` (ผู้เรียกคุม transaction)

    `actor_user_id = None` แปลว่า **ระบบเปลี่ยนเอง** ไม่ใช่ "ไม่รู้ว่าใคร"
    (docstring ของ `OrderStatusHistory` เป็นเจ้าของนิยามนี้)
    """
    row = OrderStatusHistory(
        order_id=order_id,
        from_status=from_status,
        to_status=to_status,
        actor_user_id=actor_user_id,
        reason=reason,
    )
    session.add(row)
    return row
