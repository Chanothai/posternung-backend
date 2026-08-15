"""Reservation table access — thin DB layer (ไม่มี business logic).

🔴 **ยังไม่ใช่ F3** — มีฟังก์ชันเดียวที่ `poster_service.mark_sold()` (ADR-0025 · INF-24)
ต้องใช้เพื่อตรวจว่าโปสเตอร์มี active reservation อยู่ไหมก่อนตัดสินว่าขายแล้ว
ไม่มี create/cancel/expire ที่นี่เลย — งานเหล่านั้นเป็นของ F3/SCR-06 ที่ยังไม่เริ่ม
(ADR-0025 §Context: "reservations มีแค่ SQLAlchemy model — ไม่มีอะไรสร้างแถวได้เลย")
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ReservationStatus
from app.models.reservation import Reservation


async def get_active_reservation(
    session: AsyncSession, poster_id: uuid.UUID
) -> Reservation | None:
    """แถว reservation ที่ `status = 'active'` ของโปสเตอร์นี้ ถ้ามี

    คาดว่ามีได้อย่างมาก 1 แถว เพราะ `uq_active_reservation_per_poster` (partial unique
    index บน `reservations`) — `.first()` ไม่ใช่ `.one()` เพื่อไม่ให้ค่าที่ผิดปกติ (ถ้า
    เคยเกิด) ทำให้ `mark_sold()` โยน error ที่อ่านไม่ออกแทนที่จะตัดสินได้ตามปกติ

    ไม่ใช้ `FOR UPDATE` เพราะ `mark_sold()` ไม่เขียนตาราง `reservations` เลยสักคอลัมน์
    (ADR-0025 D3 — ล็อกที่ต้องมีคือของแถว `posters` เท่านั้น)
    """
    stmt = select(Reservation).where(
        Reservation.poster_id == poster_id,
        Reservation.status == ReservationStatus.active,
    )
    result = await session.execute(stmt)
    return result.scalars().first()
