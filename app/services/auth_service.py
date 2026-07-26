"""Business logic ของ F1 Authentication — firebase_login (email/password, phone-OTP,
Google ผ่าน Firebase ID token) + refresh_token.

Sign-in ทั้งหมดเกิดที่ Firebase ฝั่ง client — backend มีหน้าที่ verify ID token แล้ว
find-or-create user + ออก JWT ของเราเอง. ไม่มี local password/OTP flow แล้ว
"""

import asyncio
import json
import uuid

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.exceptions import (
    OAuthEmailNotVerified,
    OAuthLoginConflict,
    OAuthProviderNotConfigured,
    OAuthTokenInvalid,
    RefreshTokenInvalid,
)
from app.models.enums import OAuthProvider
from app.models.user import User
from app.repositories import (
    oauth_identity_repository,
    refresh_token_repository,
    user_repository,
)
from app.schemas.auth import (
    FirebaseLoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
)


async def _issue_and_store_tokens(session: AsyncSession, user: User) -> TokenResponse:
    access_token = security.create_access_token(str(user.id))
    refresh_token, expires_at = security.create_refresh_token(str(user.id))
    await refresh_token_repository.store(
        session,
        user_id=user.id,
        token_hash=security.hash_token(refresh_token),
        expires_at=expires_at,
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def refresh_token(session: AsyncSession, data: RefreshRequest) -> TokenResponse:
    try:
        payload = security.decode_token(data.refresh_token)
    except security.JWTError:
        raise RefreshTokenInvalid()

    if payload.get("type") != "refresh":
        raise RefreshTokenInvalid()

    token_hash = security.hash_token(data.refresh_token)
    stored = await refresh_token_repository.get_active(session, token_hash)
    if stored is None:
        raise RefreshTokenInvalid()

    try:
        user_id = uuid.UUID(payload.get("sub"))
    except (TypeError, ValueError):
        raise RefreshTokenInvalid()
    user = await session.get(User, user_id)
    if user is None:
        raise RefreshTokenInvalid()

    # rotate: revoke token เก่า ออกชุดใหม่
    await refresh_token_repository.revoke(session, token_hash)
    return await _issue_and_store_tokens(session, user)


async def logout(session: AsyncSession, data: LogoutRequest) -> None:
    """Revoke refresh token ของ device นี้ — idempotent เสมอ ไม่ raise ไม่ว่า token
    จะถูก revoke ไปแล้ว/ไม่เคยมีจริง/เป็น string มั่ว (RFC 7009 pattern: การถือ token
    คือหลักฐานในตัวเองอยู่แล้ว ไม่ต้อง auth เพิ่ม และไม่ leak ว่า token ไหนมีจริง).

    ไม่ decode/verify JWT — hash ตรงๆ แล้วสั่ง revoke, ถ้าไม่ match ก็เป็น no-op ตาม
    ธรรมชาติของ UPDATE ... WHERE. ไม่แตะ Firebase (access token ที่ยังไม่หมดอายุยังใช้
    ได้จนครบ 30 นาที — เป็นข้อจำกัดของ stateless JWT ไม่ใช่บั๊ก ดู docs/api-contract).
    """
    token_hash = security.hash_token(data.refresh_token)
    await refresh_token_repository.revoke(session, token_hash)


_firebase_initialized = False


def _ensure_firebase_app() -> None:
    """Init firebase-admin ครั้งเดียว (idempotent) ด้วย service account credential.
    เรียกตอนใช้งานจริงเท่านั้น (lazy) — ไม่ init ตอน import module เพื่อไม่ให้แอป boot
    พังถ้ายังไม่ตั้ง credential (เช่น env ที่ไม่ได้เปิด social login)."""
    global _firebase_initialized
    if _firebase_initialized:
        return
    if settings.FIREBASE_SERVICE_ACCOUNT_PATH:
        # best practice (prod): อ่านจากไฟล์ — key ไม่อยู่ใน env. path นี้เป็น path
        # ในคอนเทนเนอร์ (bind-mount read-only จาก host — ดู docker-compose.production.yml)
        cred = firebase_credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
    else:
        # fallback (dev/test/legacy): เนื้อ JSON ทั้งก้อนใน env var
        cred = firebase_credentials.Certificate(
            json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        )
    firebase_admin.initialize_app(cred, {"projectId": settings.FIREBASE_PROJECT_ID})
    _firebase_initialized = True


# map Firebase claim firebase.sign_in_provider -> provider enum ของเรา
_SIGN_IN_PROVIDER_MAP: dict[str, OAuthProvider] = {
    "password": OAuthProvider.password,
    "google.com": OAuthProvider.google,
    "phone": OAuthProvider.phone,
}


async def firebase_login(
    session: AsyncSession, data: FirebaseLoginRequest
) -> TokenResponse:
    """Mobile login ผ่าน Firebase (email/password, phone-OTP, หรือ Google) — client
    sign-in ด้วย Firebase Auth แล้วส่ง ID token มา backend verify + find-or-create user
    + ออก JWT. รองรับทุก sign-in provider ผ่าน endpoint เดียว."""
    if not settings.FIREBASE_PROJECT_ID or not (
        settings.FIREBASE_SERVICE_ACCOUNT_JSON or settings.FIREBASE_SERVICE_ACCOUNT_PATH
    ):
        raise OAuthProviderNotConfigured()

    _ensure_firebase_app()
    try:
        # verify_id_token เป็น blocking call (fetch Google public certs + check_revoked
        # ยิง RPC ไป Firebase) → รันใน thread แยกกัน block event loop หลักของ FastAPI
        # check_revoked=True → reject ถ้า user ถูก disable หรือ token ถูก revoke แล้ว
        payload = await asyncio.to_thread(
            firebase_auth.verify_id_token,
            data.id_token,
            check_revoked=True,
        )
    except (
        firebase_auth.InvalidIdTokenError,
        firebase_auth.ExpiredIdTokenError,
        firebase_auth.RevokedIdTokenError,
        firebase_auth.CertificateFetchError,
        firebase_auth.UserDisabledError,
    ):
        # ครอบคลุม signature ผิด/หมดอายุ/aud-iss ไม่ตรง/revoke/disabled/ดึง cert ไม่ได้
        raise OAuthTokenInvalid()

    sign_in_provider = (payload.get("firebase") or {}).get("sign_in_provider")
    provider = _SIGN_IN_PROVIDER_MAP.get(sign_in_provider)
    if provider is None:
        # sign-in method ที่ backend ยังไม่รองรับ (เช่น apple.com/facebook.com)
        raise OAuthTokenInvalid()

    # sub ของ Firebase token = Firebase uid (stable ต่อ user ใน project) — ใช้เป็น key
    provider_user_id: str = payload["sub"]

    if provider is OAuthProvider.phone:
        # phone: ไม่มี email — SMS OTP verified โดย Firebase แล้ว (ออก token = ยืนยันแล้ว)
        # find-or-create ด้วย uid เท่านั้น (ไม่ auto-link ด้วย email เพราะไม่มี)
        email: str | None = None
        phone: str | None = payload.get("phone_number")
    else:
        # password / google: ต้องมี email + email_verified (กัน email มั่วผูกบัญชีคนอื่น —
        # Google ยืนยันเอง · password ต้อง verify email link ก่อน)
        if not payload.get("email_verified", False):
            raise OAuthEmailNotVerified()
        email = payload["email"]
        phone = None

    identity = await oauth_identity_repository.get_by_provider_user_id(
        session, provider=provider, provider_user_id=provider_user_id
    )
    if identity is not None:
        user = await session.get(User, identity.user_id)
        if user is None:
            # ไม่ควรเกิด (FK CASCADE ลบคู่กันเสมอ) — กันไว้เผื่อ data ผิดปกติ
            raise OAuthLoginConflict()
        return await _issue_and_store_tokens(session, user)

    # ยังไม่เคย link provider นี้มาก่อน — auto-link user เดิมด้วย email (เฉพาะ provider
    # ที่มี email) หรือสร้างใหม่
    try:
        async with session.begin_nested():  # savepoint กันแพ้ race ทำ transaction หลักพัง
            user = None
            if email is not None:
                user = await user_repository.get_by_email(session, email)
            if user is None:
                user = await user_repository.create(session, email=email, phone=phone)
            if not user.is_verified:
                await user_repository.set_verified(session, user.id)
                user.is_verified = True

            await oauth_identity_repository.create(
                session,
                user_id=user.id,
                provider=provider,
                provider_user_id=provider_user_id,
                email=email,
            )
    except IntegrityError:
        # แพ้ race: อีก request login provider/uid เดียวกันพร้อมกัน สร้าง user/identity
        # ไปก่อน — savepoint rollback แล้ว ลองอ่านซ้ำครั้งเดียว
        identity = await oauth_identity_repository.get_by_provider_user_id(
            session, provider=provider, provider_user_id=provider_user_id
        )
        if identity is None:
            raise OAuthLoginConflict()
        user = await session.get(User, identity.user_id)
        if user is None:
            raise OAuthLoginConflict()

    return await _issue_and_store_tokens(session, user)
