"""Unit test ของ auth_service.firebase_login — mock firebase_auth.verify_id_token
เพื่อไม่ต้องพึ่ง Firebase/Google server จริง + ไม่ต้องมี service account credential ตอน test.

ครอบทั้ง 3 sign-in provider ที่รองรับ (google.com / password / phone) ผ่าน endpoint เดียว
"""

from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    OAuthEmailNotVerified,
    OAuthProviderNotConfigured,
    OAuthTokenInvalid,
)
from app.models.enums import OAuthProvider
from app.repositories import oauth_identity_repository, user_repository
from app.schemas.auth import FirebaseLoginRequest
from app.services import auth_service


def _firebase_payload(
    *, sub: str = "firebase-uid-123", email: str = "gtest@test.example", verified=True
) -> dict:
    """claim แบบ Firebase ID token (sub = Firebase uid)."""
    return {
        "iss": "https://securetoken.google.com/posternung",
        "aud": "posternung",
        "sub": sub,
        "email": email,
        "email_verified": verified,
        "firebase": {
            "identities": {"google.com": ["google-sub-x"], "email": [email]},
            "sign_in_provider": "google.com",
        },
    }


def _password_payload(
    *, sub: str = "firebase-pw-uid", email: str = "pwtest@test.example", verified=True
) -> dict:
    """claim แบบ Firebase email/password sign-in (sign_in_provider='password')."""
    return {
        "iss": "https://securetoken.google.com/posternung",
        "aud": "posternung",
        "sub": sub,
        "email": email,
        "email_verified": verified,
        "firebase": {
            "identities": {"email": [email]},
            "sign_in_provider": "password",
        },
    }


def _phone_payload(
    *, sub: str = "firebase-phone-uid", phone_number: str = "+66812345678"
) -> dict:
    """claim แบบ Firebase Phone Auth (sign_in_provider='phone', ไม่มี email)."""
    return {
        "iss": "https://securetoken.google.com/posternung",
        "aud": "posternung",
        "sub": sub,
        "phone_number": phone_number,
        "firebase": {
            "identities": {"phone": [phone_number]},
            "sign_in_provider": "phone",
        },
    }


@pytest.fixture(autouse=True)
def _firebase_configured():
    """ตั้ง Firebase config ชั่วคราว + mock init ระหว่าง test (env ของ CI ทั้งสองค่าว่าง).
    patch _ensure_firebase_app เป็น no-op เพื่อไม่ให้ไป parse service account cred จริง
    (dummy JSON ข้างล่างมีไว้ให้ guard ผ่านเฉยๆ ไม่ได้ถูกใช้ init จริง)."""
    orig_pid = settings.FIREBASE_PROJECT_ID
    orig_sa = settings.FIREBASE_SERVICE_ACCOUNT_JSON
    settings.FIREBASE_PROJECT_ID = "posternung"
    settings.FIREBASE_SERVICE_ACCOUNT_JSON = '{"type":"service_account"}'
    with patch("app.services.auth_service._ensure_firebase_app"):
        yield
    settings.FIREBASE_PROJECT_ID = orig_pid
    settings.FIREBASE_SERVICE_ACCOUNT_JSON = orig_sa


async def test_firebase_google_new_user_creates_account(
    db_session: AsyncSession,
) -> None:
    """ยังไม่เคยมี user/identity มาก่อน → สร้างใหม่, is_verified=True ทันที."""
    payload = _firebase_payload(email="brand-new@test.example")
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        result = await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    assert result.access_token and result.refresh_token

    user = await user_repository.get_by_email(db_session, "brand-new@test.example")
    assert user is not None
    assert user.is_verified is True

    identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.google, provider_user_id=payload["sub"]
    )
    assert identity is not None
    assert identity.user_id == user.id


async def test_firebase_google_existing_identity_reuses_same_user(
    db_session: AsyncSession,
) -> None:
    """login ซ้ำด้วย Google account เดิม → ไม่สร้าง user/identity ซ้ำ คืน user เดิม."""
    payload = _firebase_payload(email="repeat@test.example", sub="google-sub-repeat")
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    users_with_email = await user_repository.get_by_email(
        db_session, "repeat@test.example"
    )
    assert users_with_email is not None
    # ยืนยันไม่มี identity ซ้ำ (unique constraint จะ error ถ้าโค้ด insert ซ้ำ — ผ่านแปลว่า
    # รอบสอง detect ว่ามี identity แล้วและไม่พยายาม insert อีก)
    identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.google, provider_user_id="google-sub-repeat"
    )
    assert identity is not None


async def test_firebase_google_auto_links_existing_account_by_email(
    db_session: AsyncSession,
) -> None:
    """มี user ที่ email นี้อยู่ก่อนแล้ว (ยังไม่ verify, ยังไม่เคยผูก provider ไหน) →
    login Google ด้วย email เดียวกัน (verified) → auto-link เข้า user เดิม ไม่สร้างใหม่
    + set is_verified=True."""
    email = "link-me@test.example"
    user = await user_repository.create(db_session, email=email)
    assert user.is_verified is False

    payload = _firebase_payload(email=email, sub="google-sub-link")
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.google, provider_user_id="google-sub-link"
    )
    assert identity is not None
    assert identity.user_id == user.id  # link เข้า user เดิม ไม่สร้างใหม่

    linked_user = await user_repository.get_by_email(db_session, email)
    assert linked_user.is_verified is True  # Google ยืนยัน email แล้ว → auto-verify


async def test_firebase_google_email_not_verified_rejected(
    db_session: AsyncSession,
) -> None:
    payload = _firebase_payload(email="unverified@test.example", verified=False)
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        with pytest.raises(OAuthEmailNotVerified) as exc_info:
            await auth_service.firebase_login(
                db_session, FirebaseLoginRequest(id_token="fake-token")
            )
    assert exc_info.value.status_code == 403


async def test_firebase_google_invalid_token_rejected(db_session: AsyncSession) -> None:
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        side_effect=auth_service.firebase_auth.InvalidIdTokenError("Token invalid"),
    ):
        with pytest.raises(OAuthTokenInvalid) as exc_info:
            await auth_service.firebase_login(
                db_session, FirebaseLoginRequest(id_token="garbage")
            )
    assert exc_info.value.status_code == 401


async def test_firebase_google_provider_not_configured(
    db_session: AsyncSession,
) -> None:
    settings.FIREBASE_PROJECT_ID = (
        ""  # override fixture's value เพื่อจำลอง env ไม่ได้ตั้งค่า
    )
    with pytest.raises(OAuthProviderNotConfigured) as exc_info:
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )
    assert exc_info.value.status_code == 503


# --- Firebase email/password sign-in (sign_in_provider='password') ---


async def test_firebase_password_new_user_creates_account(
    db_session: AsyncSession,
) -> None:
    """email/password ผ่าน Firebase (verified) → สร้าง user ใหม่ + identity provider
    'password', is_verified=True (verify ที่ Firebase ไม่ใช่ local)."""
    payload = _password_payload(email="pw-new@test.example")
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        result = await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    assert result.access_token and result.refresh_token

    user = await user_repository.get_by_email(db_session, "pw-new@test.example")
    assert user is not None
    assert user.is_verified is True

    identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.password, provider_user_id=payload["sub"]
    )
    assert identity is not None
    assert identity.user_id == user.id


async def test_firebase_password_email_not_verified_rejected(
    db_session: AsyncSession,
) -> None:
    """password provider ที่ยังไม่ verify email → 403 (บังคับ verify email link ก่อน)."""
    payload = _password_payload(email="pw-unverified@test.example", verified=False)
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        with pytest.raises(OAuthEmailNotVerified) as exc_info:
            await auth_service.firebase_login(
                db_session, FirebaseLoginRequest(id_token="fake-token")
            )
    assert exc_info.value.status_code == 403


# --- Firebase Phone Auth (sign_in_provider='phone') ---


async def test_firebase_phone_new_user_creates_account(
    db_session: AsyncSession,
) -> None:
    """Phone Auth: SMS OTP verified โดย Firebase แล้ว → สร้าง user email=NULL,
    phone=phone_number, identity provider 'phone', ไม่เช็ค email_verified."""
    payload = _phone_payload(phone_number="+66899999999", sub="phone-uid-new")
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        result = await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    assert result.access_token and result.refresh_token

    identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.phone, provider_user_id="phone-uid-new"
    )
    assert identity is not None
    assert identity.email is None

    user = await db_session.get(auth_service.User, identity.user_id)
    assert user is not None
    assert user.email is None  # phone-only user ไม่มี email (nullable)
    assert user.phone == "+66899999999"
    assert user.is_verified is True


async def test_firebase_phone_existing_identity_reuses_same_user(
    db_session: AsyncSession,
) -> None:
    """login ซ้ำด้วยเบอร์เดิม (uid เดิม) → ไม่สร้าง user/identity ซ้ำ."""
    payload = _phone_payload(phone_number="+66811111111", sub="phone-uid-repeat")
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.phone, provider_user_id="phone-uid-repeat"
    )
    assert identity is not None  # ผ่าน unique constraint = ไม่ได้ insert ซ้ำ


# --- unsupported provider ---


async def test_firebase_unsupported_provider_rejected(
    db_session: AsyncSession,
) -> None:
    """sign_in_provider ที่ backend ยังไม่รองรับ (เช่น apple.com) → 401."""
    payload = _firebase_payload(email="apple@test.example")
    payload["firebase"]["sign_in_provider"] = "apple.com"
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        with pytest.raises(OAuthTokenInvalid) as exc_info:
            await auth_service.firebase_login(
                db_session, FirebaseLoginRequest(id_token="fake-token")
            )
    assert exc_info.value.status_code == 401
