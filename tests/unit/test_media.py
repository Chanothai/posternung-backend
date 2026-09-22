"""Unit test ของ app/core/media.py — join base URL + storage_key (ADR-0006).

storage_key ตัวอย่างในเทสนี้ใช้รูปแบบจริงตาม ADR-0006 D2
(`posters/<visibility>/<poster_uuid>/<NN>-<asset_id>.<ext>`).
"""

import pytest

from app.core.config import settings
from app.core.media import (
    UnsafeStorageKeyError,
    build_media_url,
    is_public_storage_key,
)


def test_base_with_trailing_slash_key_without_leading_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_BASE_URL", "https://cdn.example.com/")

    assert (
        build_media_url("posters/public/abc/01-a19c.jpg")
        == "https://cdn.example.com/posters/public/abc/01-a19c.jpg"
    )


def test_base_without_trailing_slash_key_with_leading_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_BASE_URL", "https://cdn.example.com")

    assert (
        build_media_url("/posters/public/abc/01-a19c.jpg")
        == "https://cdn.example.com/posters/public/abc/01-a19c.jpg"
    )


def test_base_with_trailing_slash_key_with_leading_slash_no_double_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_BASE_URL", "https://cdn.example.com/")

    result = build_media_url("/posters/public/abc/01-a19c.jpg")

    assert result == "https://cdn.example.com/posters/public/abc/01-a19c.jpg"
    # เฉพาะ "://" ของ scheme เท่านั้นที่มี // ได้ ที่เหลือของ path ต้องไม่มี // ซ้ำ
    assert "//" not in result.split("://", 1)[1]


def test_normal_case_no_extra_slashes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEDIA_BASE_URL", "https://cdn.example.com")

    assert (
        build_media_url("posters/public/abc/01-a19c.jpg")
        == "https://cdn.example.com/posters/public/abc/01-a19c.jpg"
    )


def test_internal_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEDIA_BASE_URL", "https://cdn.example.com")

    with pytest.raises(UnsafeStorageKeyError):
        build_media_url("posters/internal/abc/01-a19c.jpg")


def test_key_without_posters_prefix_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEDIA_BASE_URL", "https://cdn.example.com")

    with pytest.raises(UnsafeStorageKeyError):
        build_media_url("other/public/abc/01-a19c.jpg")


def test_near_miss_prefix_public_x_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """`posters/publicX/...` ต้องไม่ผ่าน — เช็ค prefix ต้องเป็น `posters/public/`
    ทั้งก้อน ไม่ใช่ `startswith("posters/public")` เฉยๆ."""
    monkeypatch.setattr(settings, "MEDIA_BASE_URL", "https://cdn.example.com")

    with pytest.raises(UnsafeStorageKeyError):
        build_media_url("posters/publicX/abc/01-a19c.jpg")


def test_near_miss_no_trailing_slash_after_public_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`posters/public` ไม่มี `/` ปิดท้าย — ยังไม่ใช่ segment `public` ที่สมบูรณ์."""
    monkeypatch.setattr(settings, "MEDIA_BASE_URL", "https://cdn.example.com")

    with pytest.raises(UnsafeStorageKeyError):
        build_media_url("posters/public")


def test_error_message_does_not_leak_storage_key_or_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_BASE_URL", "https://cdn.example.com")
    secret_key = "posters/internal/3f2a-secret-poster/01-uv-scan.jpg"

    with pytest.raises(UnsafeStorageKeyError) as exc_info:
        build_media_url(secret_key)

    message = str(exc_info.value)
    assert secret_key not in message
    assert "cdn.example.com" not in message


# --- is_public_storage_key (ADR-0007) ---
#
# เทส near-miss ข้างบนยิงที่ `build_media_url()` ซึ่งเป็นด่านหลัง — ชุดนี้ยิงที่ตัว
# predicate ที่ผู้เรียกใช้กรองก่อน ถ้า predicate ผ่อนปรนกว่า `build_media_url()`
# แม้แต่เคสเดียว key นั้นจะหลุด filter ไปโดน raise = 500 กลับมาโดยไม่มีเทสไหนแดง


def test_is_public_storage_key_public_key_is_true() -> None:
    assert is_public_storage_key("posters/public/abc/01-a19c.jpg") is True


def test_is_public_storage_key_leading_slash_is_true() -> None:
    """ต้อง normalize `/` นำหน้าแบบเดียวกับ `build_media_url()` ไม่งั้นเกณฑ์สองด่านต่างกัน."""
    assert is_public_storage_key("/posters/public/abc/01-a19c.jpg") is True


def test_is_public_storage_key_internal_key_is_false() -> None:
    assert is_public_storage_key("posters/internal/abc/01-uv.jpg") is False


def test_is_public_storage_key_near_miss_publicx_is_false() -> None:
    """`posters/publicx/...` ไม่ใช่ segment `public` — ถ้า predicate ใช้
    `startswith("posters/public")` เฉย ๆ เคสนี้จะ True แล้วไปพังที่ build_media_url().
    """
    assert is_public_storage_key("posters/publicx/a.jpg") is False


def test_is_public_storage_key_no_trailing_slash_after_public_is_false() -> None:
    assert is_public_storage_key("posters/public") is False


def test_is_public_storage_key_other_domain_prefix_is_false() -> None:
    assert is_public_storage_key("other/public/abc/01-a19c.jpg") is False
