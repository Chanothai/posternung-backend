"""Integration tests (HTTP-level) ของ POST /auth/firebase — mock Firebase token
verification เพื่อไม่ต้องพึ่ง Firebase server จริง."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import auth_service

API = "/api/v1/auth"


def _firebase_payload(
    *, sub: str = "firebase-uid-http", email: str = "ghttp@test.example", verified=True
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


@pytest.fixture(autouse=True)
def _firebase_configured():
    """ตั้ง Firebase config ชั่วคราว + mock init (ไม่ให้ไป parse cred จริง) ระหว่าง test."""
    orig_pid = settings.FIREBASE_PROJECT_ID
    orig_sa = settings.FIREBASE_SERVICE_ACCOUNT_JSON
    settings.FIREBASE_PROJECT_ID = "posternung"
    settings.FIREBASE_SERVICE_ACCOUNT_JSON = '{"type":"service_account"}'
    with patch("app.services.auth_service._ensure_firebase_app"):
        yield
    settings.FIREBASE_PROJECT_ID = orig_pid
    settings.FIREBASE_SERVICE_ACCOUNT_JSON = orig_sa


async def test_firebase_google_returns_token_and_me_works(client: AsyncClient) -> None:
    payload = _firebase_payload(email="google-flow@test.example")
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        res = await client.post(f"{API}/firebase", json={"id_token": "fake-token"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"

    me = await client.get(
        f"{API}/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["email"] == "google-flow@test.example"
    assert me_body["is_verified"] is True
    assert "hashed_password" not in me_body


async def test_firebase_google_email_not_verified_403(client: AsyncClient) -> None:
    payload = _firebase_payload(email="unverified-http@test.example", verified=False)
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        res = await client.post(f"{API}/firebase", json={"id_token": "fake-token"})

    assert res.status_code == 403
    assert res.json()["error_code"] == "OAUTH_EMAIL_NOT_VERIFIED"


async def test_firebase_google_invalid_token_401(client: AsyncClient) -> None:
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        side_effect=auth_service.firebase_auth.InvalidIdTokenError("bad token"),
    ):
        res = await client.post(f"{API}/firebase", json={"id_token": "garbage"})

    assert res.status_code == 401
    assert res.json()["error_code"] == "OAUTH_TOKEN_INVALID"


async def test_firebase_google_missing_id_token_is_422(client: AsyncClient) -> None:
    res = await client.post(f"{API}/firebase", json={})
    assert res.status_code == 422
    assert res.json()["error_code"] == "VALIDATION_ERROR"


async def test_firebase_google_provider_not_configured_503(client: AsyncClient) -> None:
    settings.FIREBASE_PROJECT_ID = ""  # จำลอง env ไม่ได้ตั้งค่า (override fixture)
    res = await client.post(f"{API}/firebase", json={"id_token": "fake-token"})
    assert res.status_code == 503
    assert res.json()["error_code"] == "OAUTH_PROVIDER_NOT_CONFIGURED"


def _password_payload(
    *, sub: str = "firebase-pw-http", email: str = "pwhttp@test.example", verified=True
) -> dict:
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
    sub: str = "firebase-phone-http",
    phone_number: str = "+66822222222",
    email: str | None = None,
    email_verified: bool = False,
) -> dict:
    identities: dict = {"phone": [phone_number]}
    payload: dict = {
        "iss": "https://securetoken.google.com/posternung",
        "aud": "posternung",
        "sub": sub,
        "phone_number": phone_number,
        "firebase": {"identities": identities, "sign_in_provider": "phone"},
    }
    if email is not None:
        payload["email"] = email
        payload["email_verified"] = email_verified
        identities["email"] = [email]
    return payload


async def test_firebase_password_login_returns_token_and_me_works(
    client: AsyncClient,
) -> None:
    """POST /auth/firebase ด้วย email/password token → ออก JWT + /me คืน email ถูกต้อง."""
    payload = _password_payload(email="pw-flow@test.example")
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        res = await client.post(f"{API}/firebase", json={"id_token": "fake-token"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["access_token"] and body["refresh_token"]

    me = await client.get(
        f"{API}/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "pw-flow@test.example"
    assert me.json()["is_verified"] is True


async def test_firebase_phone_login_returns_token_and_me_null_email(
    client: AsyncClient,
) -> None:
    """POST /auth/firebase ด้วย phone token → ออก JWT + /me คืน email=None, phone ตรง."""
    payload = _phone_payload(phone_number="+66833333333", sub="phone-http-flow")
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        res = await client.post(f"{API}/firebase", json={"id_token": "fake-token"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["access_token"] and body["refresh_token"]

    me = await client.get(
        f"{API}/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["email"] is None  # phone-only user ไม่มี email
    assert me_body["phone"] == "+66833333333"
    assert me_body["is_verified"] is True


async def test_firebase_phone_with_verified_email_returns_that_email(
    client: AsyncClient,
) -> None:
    """บัญชี Firebase ที่ผูกทั้งเบอร์และ email (verified) → login ด้วยเบอร์ แล้ว /me
    ต้องคืน email นั้นด้วย (ไม่ใช่ null) — ยืนยันว่าไม่ทิ้ง email ที่ token ส่งมา."""
    payload = _phone_payload(
        phone_number="+66844444444",
        sub="phone-http-with-email",
        email="phone-linked@test.example",
        email_verified=True,
    )
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        res = await client.post(f"{API}/firebase", json={"id_token": "fake-token"})

    assert res.status_code == 200, res.text
    me = await client.get(
        f"{API}/me",
        headers={"Authorization": f"Bearer {res.json()['access_token']}"},
    )
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["email"] == "phone-linked@test.example"
    assert me_body["phone"] == "+66844444444"


async def test_firebase_unsupported_provider_401(client: AsyncClient) -> None:
    """sign_in_provider ที่ยังไม่รองรับ (apple.com) → 401 OAUTH_TOKEN_INVALID."""
    payload = _firebase_payload(email="apple-http@test.example")
    payload["firebase"]["sign_in_provider"] = "apple.com"
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=payload,
    ):
        res = await client.post(f"{API}/firebase", json={"id_token": "fake-token"})

    assert res.status_code == 401
    assert res.json()["error_code"] == "OAUTH_TOKEN_INVALID"
