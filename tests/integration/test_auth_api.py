"""Integration tests (HTTP-level) ของ F1 auth — เน้น /auth/me + /auth/refresh
+ auth dependency และ edge case ที่เห็นผลชัดเฉพาะระดับ HTTP (envelope, status, security).

Token ตั้งต้นได้มาจาก /auth/firebase (mock verify_id_token) เพราะ local register/login
ถูกถอดออกแล้ว — sign-in ทุกวิธีทำที่ Firebase ฝั่ง client
"""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.config import settings

API = "/api/v1/auth"


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


def _payload(*, sub: str, email: str) -> dict:
    """claim แบบ Firebase ID token (email/password sign-in)."""
    return {
        "iss": "https://securetoken.google.com/posternung",
        "aud": "posternung",
        "sub": sub,
        "email": email,
        "email_verified": True,
        "firebase": {
            "identities": {"email": [email]},
            "sign_in_provider": "password",
        },
    }


async def _firebase_login(client: AsyncClient, email: str, sub: str) -> dict:
    """login ผ่าน /auth/firebase (mock token verify); คืน TokenResponse dict."""
    with patch(
        "app.services.auth_service.firebase_auth.verify_id_token",
        return_value=_payload(sub=sub, email=email),
    ):
        res = await client.post(f"{API}/firebase", json={"id_token": "fake-token"})
    assert res.status_code == 200, res.text
    return res.json()


async def test_login_then_me_returns_current_user(client: AsyncClient) -> None:
    email = "flow@test.example"
    tokens = await _firebase_login(client, email, "flow-uid")

    res = await client.get(
        f"{API}/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email"] == email
    assert body["is_verified"] is True
    assert "hashed_password" not in body  # ห้าม leak (คอลัมน์ถูกถอดออกแล้วด้วย)


async def test_me_without_token_is_401_envelope(client: AsyncClient) -> None:
    res = await client.get(f"{API}/me")
    assert res.status_code == 401
    assert res.json()["error_code"] == "UNAUTHORIZED"


async def test_me_with_garbage_token_is_401(client: AsyncClient) -> None:
    res = await client.get(
        f"{API}/me", headers={"Authorization": "Bearer not-a-real-jwt"}
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "UNAUTHORIZED"


async def test_me_rejects_refresh_token_used_as_access(client: AsyncClient) -> None:
    tokens = await _firebase_login(client, "rt-as-at@test.example", "rt-as-at-uid")
    # เอา refresh token มาใช้แทน access token → ต้องโดนปฏิเสธ (type != access)
    res = await client.get(
        f"{API}/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "UNAUTHORIZED"


async def test_refresh_with_access_token_is_401(client: AsyncClient) -> None:
    tokens = await _firebase_login(client, "at-as-rt@test.example", "at-as-rt-uid")
    res = await client.post(
        f"{API}/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "REFRESH_TOKEN_INVALID"


async def test_refresh_rotated_token_reuse_is_401(client: AsyncClient) -> None:
    tokens = await _firebase_login(client, "rotate@test.example", "rotate-uid")
    old_refresh = tokens["refresh_token"]

    # ใช้ครั้งแรก → rotate สำเร็จ (revoke ตัวเก่า ออกตัวใหม่)
    first = await client.post(f"{API}/refresh", json={"refresh_token": old_refresh})
    assert first.status_code == 200

    # ใช้ตัวเก่าซ้ำ → ต้องถูกปฏิเสธ (ถูก revoke แล้ว)
    reuse = await client.post(f"{API}/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401
    assert reuse.json()["error_code"] == "REFRESH_TOKEN_INVALID"


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    """logout สำเร็จ (204) แล้วเอา refresh token เดิมไปต่ออายุไม่ได้อีก — พิสูจน์ว่า
    revoke มีผลจริง ไม่ใช่แค่ตอบ 204 เฉยๆ."""
    tokens = await _firebase_login(client, "logout-me@test.example", "logout-uid")

    res = await client.post(
        f"{API}/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert res.status_code == 204
    assert res.content == b""

    refresh_res = await client.post(
        f"{API}/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_res.status_code == 401
    assert refresh_res.json()["error_code"] == "REFRESH_TOKEN_INVALID"


async def test_logout_is_idempotent(client: AsyncClient) -> None:
    """logout ซ้ำด้วย token เดิม (ที่ revoke ไปแล้ว) ก็ยัง 204 — ไม่ error."""
    tokens = await _firebase_login(client, "logout-twice@test.example", "logout-2-uid")

    first = await client.post(
        f"{API}/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert first.status_code == 204

    second = await client.post(
        f"{API}/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert second.status_code == 204


async def test_logout_with_garbage_token_is_204(client: AsyncClient) -> None:
    """token ที่ไม่เคยมีจริงในระบบ (string มั่ว) → ยัง 204 เสมอ — ไม่ leak ว่า
    token ไหนมีจริง (RFC 7009-style) และไม่ crash เป็น 500."""
    res = await client.post(f"{API}/logout", json={"refresh_token": "not-a-real-token"})
    assert res.status_code == 204


async def test_logout_does_not_revoke_access_token(client: AsyncClient) -> None:
    """ข้อจำกัดที่ตั้งใจ ไม่ใช่บั๊ก: access token เป็น stateless JWT — logout ไม่มี
    ทางทำให้มันใช้ต่อไม่ได้ทันที ยังเรียก /me ผ่านได้จนกว่าจะหมดอายุเอง (30 นาที)."""
    tokens = await _firebase_login(client, "logout-at@test.example", "logout-at-uid")

    await client.post(f"{API}/logout", json={"refresh_token": tokens["refresh_token"]})

    me = await client.get(
        f"{API}/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200


async def test_removed_local_auth_endpoints_are_404(client: AsyncClient) -> None:
    """register/verify-otp/login/google ถูกถอดออกแล้ว — ต้องไม่มี route เหลืออยู่."""
    for path, body in (
        ("/register", {"email": "x@test.example", "password": "Passw0rd1"}),
        ("/verify-otp", {"email": "x@test.example", "code": "123456"}),
        ("/login", {"email": "x@test.example", "password": "Passw0rd1"}),
        ("/google", {"id_token": "fake-token"}),
    ):
        res = await client.post(f"{API}{path}", json=body)
        assert res.status_code == 404, f"{path} ยังตอบ {res.status_code}"
