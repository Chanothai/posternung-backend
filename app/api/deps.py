"""Shared FastAPI dependencies — auth (get_current_user) ฯลฯ.

get_current_user เป็นกลไกกลางสำหรับ protect endpoint ทุกเส้นที่ต้อง login
(F2+ ใช้ต่อ) — ผูก bearerAuth scheme เข้า OpenAPI /docs อัตโนมัติ
"""

import uuid

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.database import get_db
from app.core.exceptions import AdminRequired, Unauthorized
from app.models.user import User

# auto_error=False → จัดการเคสไม่มี token เองเป็น envelope (ไม่ใช่ 403 default ของ FastAPI)
_bearer = HTTPBearer(auto_error=False, description="JWT access token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    session: AsyncSession = Depends(get_db),
) -> User:
    """ตรวจ access token → คืน User; fail ใด ๆ → 401 UNAUTHORIZED (envelope เดียวกัน)."""
    if credentials is None:
        raise Unauthorized()

    try:
        payload = security.decode_token(credentials.credentials)
    except security.JWTError:
        raise Unauthorized()

    # ต้องเป็น access token เท่านั้น — refresh token ใช้แทนไม่ได้
    if payload.get("type") != "access":
        raise Unauthorized()

    try:
        user_id = uuid.UUID(payload.get("sub"))
    except (TypeError, ValueError):
        raise Unauthorized()

    user = await session.get(User, user_id)
    if user is None:
        raise Unauthorized()

    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """สิทธิ์แอดมิน — ผูกที่ระดับ APIRouter ไม่ใช่รายเส้น (ADR-0031 D2).

    ต่อยอดจาก get_current_user เสมอ ห้าม decode token เอง: ประตู auth ต้องมีบานเดียว
    เส้นทางที่สองจะพลาดเรื่อง type == "access" แน่นอน

    fail-closed ทั้งชุด (ADR-0031 D3/D4) — สิทธิ์อ่านจากแถวใน DB ที่ผูกกับ sub ของ
    token เท่านั้น ห้ามอ่านจาก header/query/body/claim ที่ client ส่งมาได้
    ค่าที่ไม่ใช่ True แท้ ๆ (False, None, ไม่มี attribute) = ไม่ใช่แอดมิน
    """
    if getattr(current_user, "is_admin", None) is not True:
        raise AdminRequired()
    return current_user
