"""`payments` table access — thin DB layer (ไม่มี business logic)

🔴 **`payments` ยังไม่มีผู้เขียน `status` ก่อน INF-41** (ADR-0033 D5 · closed-world
ของ `tests/unit/test_status_writer_invariant.py`) — ไฟล์นี้คือจุดแรกที่มี
`UPDATE payments SET status = ...` และผู้เขียนตัวเดียวคือ `app/services/order_service.py`
(สไลซ์ A: `verify_payment()` · สไลซ์ B ที่ยังไม่ลง: `reject_payment()`)

**INSERT ของ `payments` ยังไม่มีผู้เขียนในรอบนี้** (ADR-0033 D7 — เส้นแจ้งโอนเป็นของ
`SCR-08`) ⇒ ไฟล์นี้จึงมีแต่ read/UPDATE ไม่มีฟังก์ชันสร้างแถว
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PaymentStatus
from app.models.payment import Payment


async def get_claimed_for_order(
    session: AsyncSession, order_id: uuid.UUID
) -> Payment | None:
    """`SELECT ... FOR UPDATE` แถว `payments` ที่ `status == CLAIMED` ของออร์เดอร์นี้

    คืน `None` ถ้าไม่มีแถวที่ `CLAIMED` ของออร์เดอร์นี้ — ผู้เรียกเดียววันนี้คือ
    `order_service.verify_payment()` ซึ่งแปลเป็น `PaymentNotClaimed` (409)

    🔴 **ตัวแปรที่รับค่ากลับต้องตั้งชื่อ `payment` ที่ call site** — ตัวสแกน AST ของ
    `tests/unit/test_status_writer_invariant.py` จำแนกว่าการเขียน `<expr>.status = ...`
    เป็นของตารางไหนจาก **ชื่อตัวแปร** (`VARIABLE_TABLES["payment"] == "payments"`)
    ไม่ใช่จาก type — ตั้งชื่ออื่นแล้ว closed-world ของตารางนี้จะจำแนกไม่ได้และเทสแดง
    (`test_no_status_write_is_unclassified`)

    `populate_existing=True` เหตุผลเดียวกับ `poster_repository.get_for_update()` /
    `order_repository.get_for_update()` — identity map จะคืน object เดิมที่โหลดมา
    *ก่อน* ล็อก ทำให้ตัดสินด้วยค่าเก่าถ้าไม่บังคับ
    """
    stmt = (
        select(Payment)
        .where(Payment.order_id == order_id, Payment.status == PaymentStatus.CLAIMED)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return await session.scalar(stmt)
