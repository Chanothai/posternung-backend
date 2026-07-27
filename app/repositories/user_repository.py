"""User table access — thin DB layer (ไม่มี business logic)."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    email: str | None = None,
    phone: str | None = None,
) -> User:
    # email=None → phone-only user (Firebase Phone Auth) ไม่มี email
    user = User(email=email, phone=phone)
    session.add(user)
    await session.flush()  # ให้ได้ id/created_at กลับมาโดยไม่ commit
    return user


async def set_verified(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(User).where(User.id == user_id).values(is_verified=True)
    )


async def set_phone(session: AsyncSession, user_id: uuid.UUID, phone: str) -> None:
    """เติมเบอร์ให้ user ที่ยังไม่มี — `WHERE phone IS NULL` กันทับเบอร์เดิมถ้ามีอยู่แล้ว."""
    await session.execute(
        update(User).where(User.id == user_id, User.phone.is_(None)).values(phone=phone)
    )
