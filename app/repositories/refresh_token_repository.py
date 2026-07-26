"""Refresh token table access — thin DB layer."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import RefreshToken


async def store(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
) -> RefreshToken:
    rt = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    session.add(rt)
    await session.flush()
    return rt


async def get_active(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    """refresh token ที่ยังไม่ revoke และยังไม่หมดอายุ."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def revoke(session: AsyncSession, token_hash: str) -> None:
    """Revoke ถ้ายังไม่เคย revoke — idempotent (เรียกซ้ำไม่ทับ revoked_at เดิม,
    audit trail ยังชี้เวลาที่ revoke ครั้งแรกจริง). ไม่มี match ก็เป็น no-op เงียบๆ."""
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
