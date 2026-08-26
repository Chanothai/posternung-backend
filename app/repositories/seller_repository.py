"""`seller_profiles` table access — thin DB layer (ไม่มี business logic)

🔴 **ตารางนี้เก็บข้อมูลอ่อนไหวที่สุดในระบบ** (เลขบัญชี · ภาพบัตร) — ห้ามให้แถวที่
อ่านจากที่นี่ไหลออก public API ทั้งดุ้น (ADR-0028 D6 · ADR-0020) ผู้เรียกวันนี้ใช้
แค่ `user_id` (ด่านผู้ซื้อ ≠ ผู้ขาย) กับ `commission_rate_bps` / `is_house_account`
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.seller import SellerProfile


async def get_by_id(
    session: AsyncSession, seller_id: uuid.UUID
) -> SellerProfile | None:
    """โปรไฟล์ผู้ขายจาก `seller_profiles.id` (ค่าที่ `posters.seller_id` ชี้ถึง)

    🔴 ตารางนี้เป็นตัวเดียวที่รู้ `user_id` ของผู้ขาย ⇒ เป็นเหตุผลที่ด่าน
    "ผู้ซื้อ ≠ ผู้ขาย" ต้องโหลดมันมาก่อน — กติกาเต็มอยู่ที่ **ADR-0033 D3**
    """
    return await session.scalar(
        select(SellerProfile).where(SellerProfile.id == seller_id)
    )
