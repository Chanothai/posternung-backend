"""OAuth identity table access — thin DB layer (ไม่มี business logic)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OAuthProvider
from app.models.user import OAuthIdentity


async def get_by_provider_user_id(
    session: AsyncSession, *, provider: OAuthProvider, provider_user_id: str
) -> OAuthIdentity | None:
    result = await session.execute(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == provider,
            OAuthIdentity.provider_user_id == provider_user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_any_by_provider_user_id(
    session: AsyncSession, *, provider_user_id: str
) -> OAuthIdentity | None:
    """หา identity ด้วย Firebase uid อย่างเดียว (ข้าม provider).

    Firebase ให้ uid เดียวต่อ 1 บัญชี — ถ้า user link หลาย sign-in method เข้าบัญชี
    เดียวกัน (`linkWithCredential`) ทุก provider จะได้ `sub` เดียวกัน เจอ uid ซ้ำ =
    **Firebase ยืนยันเองว่าเป็นบัญชีเดียวกัน** เป็นสัญญาณจับคู่ที่แข็งแรงกว่า email
    """
    result = await session.execute(
        select(OAuthIdentity)
        .where(OAuthIdentity.provider_user_id == provider_user_id)
        .order_by(OAuthIdentity.created_at)  # deterministic ถ้ามีหลาย provider
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider: OAuthProvider,
    provider_user_id: str,
    email: str | None,
) -> OAuthIdentity:
    identity = OAuthIdentity(
        user_id=user_id,
        provider=provider,
        provider_user_id=provider_user_id,
        email=email,
    )
    session.add(identity)
    await session.flush()
    return identity
