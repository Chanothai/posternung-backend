"""Unit test ของ app/core/media.py — join base URL + storage_key (ADR-0006)."""

import pytest

from app.core.config import settings
from app.core.media import build_media_url


@pytest.fixture(autouse=True)
def _restore_media_base_url():
    """แต่ละเทสตั้งค่า settings.MEDIA_BASE_URL เอง — คืนค่าเดิมหลังจบเทสกันรั่วข้ามเทส."""
    original = settings.MEDIA_BASE_URL
    yield
    settings.MEDIA_BASE_URL = original


def test_base_with_trailing_slash_key_without_leading_slash() -> None:
    settings.MEDIA_BASE_URL = "https://cdn.example.com/"

    assert (
        build_media_url("posters/abc/1.jpg")
        == "https://cdn.example.com/posters/abc/1.jpg"
    )


def test_base_without_trailing_slash_key_with_leading_slash() -> None:
    settings.MEDIA_BASE_URL = "https://cdn.example.com"

    assert (
        build_media_url("/posters/abc/1.jpg")
        == "https://cdn.example.com/posters/abc/1.jpg"
    )


def test_base_with_trailing_slash_key_with_leading_slash_no_double_slash() -> None:
    settings.MEDIA_BASE_URL = "https://cdn.example.com/"

    result = build_media_url("/posters/abc/1.jpg")

    assert result == "https://cdn.example.com/posters/abc/1.jpg"
    # เฉพาะ "://" ของ scheme เท่านั้นที่มี // ได้ ที่เหลือของ path ต้องไม่มี // ซ้ำ
    assert "//" not in result.split("://", 1)[1]


def test_normal_case_no_extra_slashes() -> None:
    settings.MEDIA_BASE_URL = "https://cdn.example.com"

    assert (
        build_media_url("posters/abc/1.jpg")
        == "https://cdn.example.com/posters/abc/1.jpg"
    )
