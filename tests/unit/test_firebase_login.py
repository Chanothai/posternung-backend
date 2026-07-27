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
    *,
    sub: str = "firebase-phone-uid",
    phone_number: str | None = "+66812345678",
    email: str | None = None,
    email_verified: bool = False,
) -> dict:
    """claim แบบ Firebase Phone Auth (sign_in_provider='phone').

    email/email_verified ใส่ได้เพื่อจำลองบัญชีที่ผูก email ไว้ด้วย — Firebase ใส่ claim
    ตามที่ user record มี ไม่ขึ้นกับ provider ที่ใช้ sign in รอบนี้
    """
    identities: dict = {}
    payload: dict = {
        "iss": "https://securetoken.google.com/posternung",
        "aud": "posternung",
        "sub": sub,
        "firebase": {"identities": identities, "sign_in_provider": "phone"},
    }
    if phone_number is not None:
        payload["phone_number"] = phone_number
        identities["phone"] = [phone_number]
    if email is not None:
        payload["email"] = email
        payload["email_verified"] = email_verified
        identities["email"] = [email]
    return payload


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


async def test_firebase_phone_with_verified_email_links_existing_account(
    db_session: AsyncSession,
) -> None:
    """บัญชี Firebase ที่ผูกทั้งเบอร์และ email (verified) → login ด้วยเบอร์ ต้อง link
    เข้า user เดิมที่ email นั้น **ไม่สร้าง row ใหม่** (กันบัญชีแตกเป็น 2 ใบ) และเติม
    เบอร์ลง row เดิมที่ยังไม่มีเบอร์."""
    email = "linked-both@test.example"
    existing = await user_repository.create(db_session, email=email)
    assert existing.phone is None

    payload = _phone_payload(
        phone_number="+66877777777",
        sub="phone-uid-linked",
        email=email,
        email_verified=True,
    )
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.phone, provider_user_id="phone-uid-linked"
    )
    assert identity is not None
    assert identity.user_id == existing.id  # link เข้า row เดิม ไม่สร้างใหม่

    linked = await user_repository.get_by_email(db_session, email)
    assert linked.id == existing.id
    assert linked.phone == "+66877777777"  # backfill เบอร์ให้ row เดิม
    assert linked.is_verified is True


async def test_firebase_phone_with_unverified_email_still_logs_in(
    db_session: AsyncSession,
) -> None:
    """email ที่ผูกไว้ยังไม่ verified → **ต้อง login ผ่านปกติ ไม่ 403** (phone auth
    ไม่เคยถูกบล็อกด้วย email_verified) แต่ไม่เก็บ email ที่ยังไม่น่าเชื่อถือ."""
    payload = _phone_payload(
        phone_number="+66866666666",
        sub="phone-uid-unverified-email",
        email="not-verified-yet@test.example",
        email_verified=False,
    )
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        result = await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    assert result.access_token  # ไม่ raise OAuthEmailNotVerified

    identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session,
        provider=OAuthProvider.phone,
        provider_user_id="phone-uid-unverified-email",
    )
    user = await db_session.get(auth_service.User, identity.user_id)
    assert user.email is None  # ไม่เก็บ email ที่ยังไม่ verified
    assert user.phone == "+66866666666"


async def test_firebase_phone_without_phone_number_rejected(
    db_session: AsyncSession,
) -> None:
    """phone token ที่ไม่มี claim phone_number = token ผิดปกติ → 401 (กันสร้าง user
    ที่ทั้ง email และ phone เป็น NULL ซึ่งระบุตัวตนไม่ได้เลย)."""
    payload = _phone_payload(phone_number=None, sub="phone-uid-no-number")
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        with pytest.raises(OAuthTokenInvalid) as exc_info:
            await auth_service.firebase_login(
                db_session, FirebaseLoginRequest(id_token="fake-token")
            )
    assert exc_info.value.status_code == 401


# --- ห้าม link ด้วย email ที่ยังไม่ verified ---


async def test_unverified_email_cannot_hijack_existing_account(
    db_session: AsyncSession,
) -> None:
    """**เคสความปลอดภัยหลัก**: ผู้โจมตีสร้างบัญชี Firebase ของตัวเอง (phone) แล้วใส่
    email ของเหยื่อแบบยังไม่ verified → ต้อง **ไม่** ถูก link เข้าบัญชีเหยื่อ

    invariant ของโค้ด: ตัวแปร `email` จะไม่ใช่ None ก็ต่อเมื่อ email_verified=true
    เท่านั้น ทุกจุดที่ใช้ link/create/backfill จึงปลอดภัยโดยอัตโนมัติ
    """
    victim_email = "victim@test.example"
    victim = await user_repository.create(db_session, email=victim_email)

    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=_phone_payload(
            sub="attacker-uid",
            phone_number="+66899998888",
            email=victim_email,  # email ของเหยื่อ
            email_verified=False,  # แต่ยังไม่ verified
        ),
    ):
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    attacker_identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.phone, provider_user_id="attacker-uid"
    )
    assert attacker_identity.user_id != victim.id  # ต้องคนละบัญชี

    attacker = await db_session.get(auth_service.User, attacker_identity.user_id)
    assert attacker.email is None  # ไม่ยึด email ของเหยื่อมาใส่ตัวเอง

    still_victim = await user_repository.get_by_email(db_session, victim_email)
    assert still_victim.id == victim.id  # email ยังอยู่กับเหยื่อ


async def test_verified_email_without_email_claim_rejected(
    db_session: AsyncSession,
) -> None:
    """token ที่ email_verified=true แต่ไม่มี claim email = ผิดปกติ → 401

    สมมาตรกับ guard ของ phone (ต้องมี phone_number) — กันสร้าง user ที่ไม่มีทั้ง email
    และ phone ซึ่งระบุตัวตนไม่ได้เลย (support ตามตัวไม่ได้ · link ทีหลังไม่ได้)
    """
    payload = _password_payload(sub="ghost-uid", verified=True)
    del payload["email"]  # verified=true แต่ไม่มี email

    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        with pytest.raises(OAuthTokenInvalid) as exc_info:
            await auth_service.firebase_login(
                db_session, FirebaseLoginRequest(id_token="fake-token")
            )
    assert exc_info.value.status_code == 401


# --- account linking ด้วย Firebase uid (ข้าม provider) ---


async def test_same_firebase_uid_across_providers_links_one_account(
    db_session: AsyncSession,
) -> None:
    """เคสที่เคยพังจริง: login ด้วยเบอร์ก่อน (ยังไม่ผูก email) → ผู้ใช้ทำ
    linkWithCredential ผูก email เข้าบัญชี Firebase เดิม (uid ไม่เปลี่ยน) → login ด้วย
    email → ต้องได้ **user row เดียว** ไม่แตกเป็น 2 ใบ.

    uid เดียวกัน = Firebase ยืนยันเองว่าบัญชีเดียวกัน — สัญญาณนี้ต้องมาก่อน email
    """
    uid = "shared-uid-link-1"
    email = "linked-later@test.example"

    # 1) phone login ครั้งแรก — ยังไม่มี email ผูก
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=_phone_payload(sub=uid, phone_number="+66850000001"),
    ):
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    phone_identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.phone, provider_user_id=uid
    )
    first_user_id = phone_identity.user_id

    # 2) email login — uid เดิมเป๊ะ (ผูก provider เพิ่มใน Firebase แล้ว)
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=_password_payload(sub=uid, email=email, verified=True),
    ):
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    pw_identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.password, provider_user_id=uid
    )
    assert pw_identity is not None
    # หัวใจของเทสนี้ — identity คนละ provider แต่ต้องชี้ user row เดียวกัน
    assert pw_identity.user_id == first_user_id

    user = await db_session.get(auth_service.User, first_user_id)
    assert user.phone == "+66850000001"  # ข้อมูลจาก phone login เดิมยังอยู่
    assert user.email == email  # backfill email ที่เพิ่งผูกเข้ามา


async def test_uid_link_takes_priority_over_email_match(
    db_session: AsyncSession,
) -> None:
    """uid ต้องมาก่อน email: มี user คนอื่นถือ email นี้อยู่แล้ว (คนละ uid) →
    ต้อง link ตาม uid ไม่ใช่ไปรวมกับ row ที่ email ตรง และต้องไม่พังด้วย
    unique violation (ปล่อย email ว่างไว้แทน)."""
    uid = "shared-uid-link-2"
    email = "already-taken@test.example"

    other = await user_repository.create(db_session, email=email)  # คนอื่นถือ email นี้

    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=_phone_payload(sub=uid, phone_number="+66850000002"),
    ):
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )
    phone_identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.phone, provider_user_id=uid
    )
    phone_user_id = phone_identity.user_id
    assert phone_user_id != other.id

    # email login ด้วย uid เดียวกัน แต่ email ไปตรงกับ row ของคนอื่น
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=_password_payload(sub=uid, email=email, verified=True),
    ):
        result = await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    assert result.access_token  # ไม่พัง
    pw_identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.password, provider_user_id=uid
    )
    assert pw_identity.user_id == phone_user_id  # ตาม uid ไม่ใช่ตาม email

    linked = await db_session.get(auth_service.User, phone_user_id)
    assert linked.email is None  # ไม่ยัด email ที่คนอื่นถืออยู่ → ไม่ชน unique


async def test_different_uid_same_email_still_links_by_email(
    db_session: AsyncSession,
) -> None:
    """uid ไม่ตรง (คนละบัญชี Firebase) แต่ email verified ตรงกัน → ยัง link ด้วย email
    เหมือนเดิม (regression ของพฤติกรรมเดิม ไม่ถูก uid-first ทำให้เสีย)."""
    email = "same-email-diff-uid@test.example"

    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=_password_payload(sub="uid-A", email=email, verified=True),
    ):
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )
    first = await user_repository.get_by_email(db_session, email)

    # google login คนละ uid แต่ email เดียวกัน (verified)
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=_firebase_payload(sub="uid-B", email=email),
    ):
        await auth_service.firebase_login(
            db_session, FirebaseLoginRequest(id_token="fake-token")
        )

    google_identity = await oauth_identity_repository.get_by_provider_user_id(
        db_session, provider=OAuthProvider.google, provider_user_id="uid-B"
    )
    assert google_identity.user_id == first.id  # ยัง link ด้วย email ได้


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
