"""`scripts/_actor.py::resolve_admin_actor()` — INF-44 A3-D3 ① (ผู้สั่งการต้องเป็นแอดมิน)

ทรงเดียวกับ `tests/unit/test_grant_admin.py::_make_user` — user ที่ล็อกอินได้จริงต้องมี
แถวใน `oauth_identities` เสมอ ค่าเริ่มต้นเป็น `google` เพื่อให้ทดสอบด่าน google-only ได้
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OAuthProvider
from app.models.user import OAuthIdentity, User
from scripts._actor import (
    ActorNotAdmin,
    ActorNotFound,
    ActorNotGoogleOnly,
    resolve_admin_actor,
)


async def _make_user(
    session: AsyncSession,
    email: str,
    *,
    is_admin: bool = False,
    providers: tuple[OAuthProvider, ...] = (OAuthProvider.google,),
) -> User:
    user = User(email=email, is_verified=True, is_admin=is_admin)
    session.add(user)
    await session.flush()
    for provider in providers:
        session.add(
            OAuthIdentity(
                user_id=user.id,
                provider=provider,
                provider_user_id=f"{provider.value}-uid-{user.id}",
                email=email,
            )
        )
    await session.flush()
    return user


async def test_unknown_email_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(ActorNotFound):
        await resolve_admin_actor(db_session, "nobody@example.test")


async def test_non_admin_account_is_refused(db_session: AsyncSession) -> None:
    await _make_user(db_session, "notadmin@example.test", is_admin=False)
    with pytest.raises(ActorNotAdmin):
        await resolve_admin_actor(db_session, "notadmin@example.test")


@pytest.mark.parametrize(
    "providers",
    [
        (OAuthProvider.password,),
        (OAuthProvider.google, OAuthProvider.password),
    ],
)
async def test_admin_without_google_only_is_refused_when_required(
    db_session: AsyncSession, providers
) -> None:
    email = f"mixed-{len(providers)}@example.test"
    await _make_user(db_session, email, is_admin=True, providers=providers)
    with pytest.raises(ActorNotGoogleOnly):
        await resolve_admin_actor(db_session, email, require_google_only=True)


async def test_google_only_admin_passes(db_session: AsyncSession) -> None:
    email = "googleadmin@example.test"
    await _make_user(
        db_session, email, is_admin=True, providers=(OAuthProvider.google,)
    )
    actor = await resolve_admin_actor(db_session, email, require_google_only=True)
    assert actor.email == email


async def test_require_google_only_false_lets_non_google_admin_through(
    db_session: AsyncSession,
) -> None:
    """OD-3 (INF-41) — dev/sit ไม่บังคับ google-only ต่างจาก production"""
    email = "sitadmin@example.test"
    await _make_user(
        db_session, email, is_admin=True, providers=(OAuthProvider.password,)
    )
    actor = await resolve_admin_actor(db_session, email, require_google_only=False)
    assert actor.email == email


async def test_default_requires_google_only() -> None:
    """🔴 mutation guard — default ต้องเป็น True (production เรียกโดยไม่ระบุ kwarg
    ต้องยังปลอดภัย ถ้าใครลืมส่ง require_google_only=True ชัดเจน)"""
    import inspect

    sig = inspect.signature(resolve_admin_actor)
    assert sig.parameters["require_google_only"].default is True
