"""Reservation table access — thin DB layer (ไม่มี business logic).

‹แก้ 2026-08-26 · INF-33 สไลซ์ A› **มีเส้นทางสร้างแถวแล้ว** — ถ้อยคำเดิมที่ว่า
*"ไม่มี create/cancel/expire ที่นี่เลย · งานเหล่านั้นเป็นของ F3/SCR-06 ที่ยังไม่เริ่ม"*
เป็นจริงจนถึงวันที่ ADR-0033 เปิดเส้นทางจอง · ผู้เขียน `reservations.status` มีไฟล์เดียว
คือ `app/services/order_service.py` (closed-world ที่ `tests/unit/test_status_writer_invariant.py`)

🔴 **ไฟล์นี้ไม่ตัดสินอะไรเลย** — เงื่อนไข "จองได้ไหม" (สถานะ listing · เพดานต่อผู้ใช้ ·
ผู้ซื้อ ≠ ผู้ขาย · BR-P9 ห้ามพลิกเป็น `expired` ถ้าแจ้งโอนแล้ว) อยู่ที่ชั้น service ทั้งหมด
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
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


async def get_by_id(
    session: AsyncSession, reservation_id: uuid.UUID
) -> Reservation | None:
    """อ่านแถวเดียวด้วย id — ไม่ล็อก

    ไม่ต้องล็อกเพราะผู้เรียก (`order_service.create_order()`) ล็อกแถว `posters`
    ซึ่งเป็น **สมอเดียวของทั้งระบบ** ไปแล้ว (ADR-0033 D3) และทุกเส้นทางที่เขียน
    `reservations` ของโปสเตอร์ใบนั้นต้องผ่านสมอตัวเดียวกัน
    """
    return await session.scalar(
        select(Reservation).where(Reservation.id == reservation_id)
    )


async def list_active_for_poster(
    session: AsyncSession, poster_id: uuid.UUID
) -> Sequence[Reservation]:
    """แถวที่ยัง `active` ทั้งหมดของโปสเตอร์ใบนี้

    ปกติมีได้อย่างมาก 1 แถว (`uq_active_reservation_per_poster`) แต่คืนเป็นลิสต์
    เพื่อให้เส้นทาง lazy-expire (ADR-0033 D4) จัดการได้ครบแม้ข้อมูลผิดปกติ
    แทนที่จะเงียบไปหนึ่งแถว
    """
    result = await session.execute(
        select(Reservation).where(
            Reservation.poster_id == poster_id,
            Reservation.status == ReservationStatus.active,
        )
    )
    return result.scalars().all()


async def count_active_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, at: datetime
) -> int:
    """จำนวน reservation ที่ **ยังจับของอยู่จริง ณ เวลา `at`** ของผู้ใช้คนนี้
    — ใช้กับเพดานของ ADR-0033 OD-3

    🔴 **ต้องกรอง `expires_at > at` ด้วย ไม่ใช่ดูแค่ `status = 'active'`**
    ‹แก้ 2026-08-26 หลัง `code-critic` รีโปรได้จริง — H1› แถวที่หมดเวลาแล้วแต่ยังไม่มี
    ใครพลิกเป็น `expired` **ยังเป็น `active` อยู่ในตาราง** เพราะ lazy-expire
    (ADR-0033 D4) พลิกให้เฉพาะโปสเตอร์ **ใบที่กำลังถูกจอง** เท่านั้น
    ⇒ ถ้านับด้วย `status` อย่างเดียว ผู้ใช้ที่ปล่อยจองหลุดครบเพดาน
    **จะจองอะไรไม่ได้อีกเลยตลอดกาล**

    🔴 **และจะอ้างว่า "scheduler เก็บที่เหลือ" ไม่ได้** — scheduler เป็นของ INF-33
    **AC-7** ซึ่งยังไม่มีอยู่จริง · เพดานที่ยิงผิดโดยไม่มีเจ้าของแย่กว่าไม่มีเพดาน

    `at` เป็นพารามิเตอร์ **repository ห้ามอ่านนาฬิกาเอง** (ADR-0033 D2 ข้อ 3)
    """
    return await session.scalar(
        select(func.count(Reservation.id)).where(
            Reservation.user_id == user_id,
            Reservation.status == ReservationStatus.active,
            Reservation.expires_at > at,
        )
    )


def create(
    session: AsyncSession,
    *,
    poster_id: uuid.UUID,
    user_id: uuid.UUID,
    expires_at: datetime,
) -> Reservation:
    """สร้างแถวจองใหม่ — ไม่ `flush` ไม่ `commit` (ผู้เรียกคุม transaction)

    `expires_at` เป็นพารามิเตอร์ **ห้ามคำนวณจากนาฬิกาในนี้** (ADR-0025 D4 ·
    ADR-0010 D5) — TTL อ่านจาก `platform_settings.reservation_ttl_minutes`
    ที่ชั้น service (ADR-0030 D3 ห้าม hardcode)
    """
    reservation = Reservation(
        poster_id=poster_id,
        user_id=user_id,
        status=ReservationStatus.active,
        expires_at=expires_at,
    )
    session.add(reservation)
    return reservation
