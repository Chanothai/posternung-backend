"""`platform_settings` table access — thin DB layer (ไม่มี business logic)

ค่าที่ BUSINESS_RULES บังคับว่า **ต้องแก้ได้โดยไม่ต้อง deploy** อยู่ในตารางนี้
(BR-L7 `commission_rate_bps` · ADR-0030 D3 `reservation_ttl_minutes` ·
ADR-0033 OD-3 `max_active_reservations_per_user` · …)

🔴 **ไม่มีพารามิเตอร์ `default`** โดยตั้งใจ — คีย์ที่หายไปต้องล้มเสียงดัง
ไม่ใช่ตกไปใช้เลขในโค้ดซึ่งจะทำให้ *แหล่งความจริงมีสองที่* และการแก้ config
จะไม่มีผลโดยไม่มีใครรู้
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PlatformSettingMissing
from app.models.platform import PlatformSetting


async def get_int(session: AsyncSession, key: str) -> int:
    """อ่านค่าคีย์หนึ่งเป็นจำนวนเต็ม — ไม่มีแถว/แปลงไม่ได้ = `PlatformSettingMissing`"""
    raw = await session.scalar(
        select(PlatformSetting.value).where(PlatformSetting.key == key)
    )
    if raw is None:
        raise PlatformSettingMissing(details=[{"key": key}])
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise PlatformSettingMissing(details=[{"key": key}]) from exc
