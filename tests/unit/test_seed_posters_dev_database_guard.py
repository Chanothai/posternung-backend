"""`scripts/seed/seed_posters.py::_assert_dev_database()` — INF-51 (BL-167)

🔴 ก่อนหน้านี้ฟังก์ชันนี้ (parser ชุดที่สามของ `host`/`db_name` ดิบ — คนละก๊อปกับ
`apply_suggestions._url_label()`) ไม่มีเทสเลยสักตัว ทั้งที่หน้าตาและความเสี่ยง
เหมือน `assert_target_database()` ทุกประการ (`urlsplit` ตัด netloc ที่ `/`/`?`/`#`
ตัวแรก ⇒ รหัสผ่านที่มีอักขระพวกนี้โดยไม่ percent-encode ทำให้ชื่อผู้ใช้/เศษรหัสผ่าน
หลุดไปอยู่ใน `host`/`db_name` ที่ข้อความ error เคยพิมพ์ดิบ ๆ)

ADR-0015 §BL-167/INF-51 AC-1 — ตอนนี้ทั้งค่าที่คืนและข้อความทั้งสองจุดผ่าน
`apply_suggestions._url_label()` ตัวเดียวกับทุก lane แล้ว — `host`/`db_name` ดิบ
ยังใช้ *ตัดสิน* เหมือนเดิมทุกจุด (AC-5) สิ่งที่เปลี่ยนคือสิ่งที่ *พิมพ์* เท่านั้น
"""

from __future__ import annotations

import pytest

from scripts.seed import seed_posters as mod
from scripts.seed._shared import PrecheckError
from scripts.seed.apply_suggestions import UNPARSEABLE_URL_LABEL

LEAK_USER = "leakuser"
SLASH_PW = "s3cr3t/xyz"
QUESTION_PW = "ab?cd"
HASH_PW = "ab#cd"
STAGE_PW = "ab/xstagey"
LEAKING_PASSWORDS = (SLASH_PW, QUESTION_PW, HASH_PW, STAGE_PW)


def _fake_env(monkeypatch, files: dict[str, dict[str, str]]) -> None:
    def fake(path) -> dict[str, str]:
        return files.get(getattr(path, "name", str(path)), {})

    monkeypatch.setattr(mod, "_parse_env_file", fake)


def _url_with_password(password: str, *, host: str = "localhost") -> str:
    return f"postgresql+asyncpg://{LEAK_USER}:{password}@{host}:5432/poster_nung_db"


# --- ทางปกติ (url แยกส่วนได้) — regression guard เดิม ---


def test_localhost_dev_url_is_accepted_and_labelled_with_the_real_host_and_db(
    monkeypatch,
) -> None:
    _fake_env(monkeypatch, {})
    label = mod._assert_dev_database(
        "postgresql+asyncpg://u:p@localhost:5432/poster_nung_db"
    )
    assert label == "localhost/poster_nung_db"


def test_remote_host_is_rejected_with_a_message_naming_the_real_host(
    monkeypatch,
) -> None:
    _fake_env(monkeypatch, {})
    with pytest.raises(PrecheckError, match=r"10\.0\.0\.5/poster_nung_db"):
        mod._assert_dev_database(
            "postgresql+asyncpg://u:p@10.0.0.5:5432/poster_nung_db"
        )


@pytest.mark.parametrize("hit", ["sit", "uat", "prod", "stage"])
def test_non_dev_looking_database_name_is_rejected_naming_the_hit(
    monkeypatch, hit: str
) -> None:
    _fake_env(monkeypatch, {})
    with pytest.raises(PrecheckError, match=hit):
        mod._assert_dev_database(
            f"postgresql+asyncpg://u:p@localhost:5432/poster_nung_{hit}"
        )


# --- AC-1/AC-2/AC-3 — url ที่แยกส่วนไม่ได้ต้องไม่พิมพ์/คืนอะไรดิบเลย ---


@pytest.mark.parametrize("password", LEAKING_PASSWORDS)
def test_assert_dev_database_never_leaks_the_username_when_url_is_unparseable(
    monkeypatch, password: str
) -> None:
    """host-mismatch branch — `urlsplit` เอาชื่อผู้ใช้ไปเป็น `host` เมื่อรหัสผ่านมี
    `?`/`#` (M-2) หรือตัด netloc ก่อน `@` เมื่อมี `/` (INF-39) แล้วโดนด่าน "ไม่ใช่
    เครื่องนี้" ปฏิเสธเป็นด่านแรกเสมอ (host ที่แยกได้ไม่ใช่ localhost)"""
    _fake_env(monkeypatch, {})
    url = _url_with_password(password)
    with pytest.raises(PrecheckError) as exc:
        mod._assert_dev_database(url)
    assert LEAK_USER not in str(exc.value)
    assert password not in str(exc.value)
    assert "แยกส่วนไม่ได้" in str(exc.value)


def test_hint_branch_never_prints_the_hit_word_when_url_is_unparseable(
    monkeypatch,
) -> None:
    """🔴 ฆ่า mutant เดียวกับ M7 ของ apply_suggestions — STAGE_PW ทำให้ db_name บังเอิญ
    มีคำว่า 'stage' ปน แต่ host ที่แยกได้ (`localhost`) ผ่านด่านแรกไปได้ตามปกติ (password
    มี `/` แต่ไม่ได้อยู่ก่อน `@` ในกรณีนี้ — ตรวจให้แน่ใจว่า host ยัง local จริง) ⇒ เดิน
    มาถึงด่าน hint จริง ต้องไม่พิมพ์คำว่า 'stage' เมื่อ url แยกส่วนไม่ได้"""
    _fake_env(monkeypatch, {})
    # host ต้องยัง parse เป็น localhost ได้ (password ที่มี "/" อยู่หลัง "@" ไม่กระทบ
    # การหา host เลย — เฉพาะ "/" ที่อยู่ *ก่อน* "@" เท่านั้นที่ตัด netloc พังตั้งแต่ host)
    url = "postgresql+asyncpg://u:p@localhost:5432/poster_nung_db/xstagey"
    with pytest.raises(PrecheckError) as exc:
        mod._assert_dev_database(url)
    assert "stage" not in str(exc.value)
    assert "แยกส่วนไม่ได้" in str(exc.value)


def test_url_label_used_by_seed_posters_is_the_same_function_as_apply_suggestions() -> (
    None
):
    """identity — พิสูจน์ว่า import มาใช้จริง ไม่ใช่ก๊อปพฤติกรรมเอาเอง"""
    from scripts.seed import apply_suggestions as suggest_mod

    assert mod._url_label is suggest_mod._url_label
    assert mod.UNPARSEABLE_URL_LABEL is suggest_mod.UNPARSEABLE_URL_LABEL


def test_positive_control_a_clean_url_is_never_mistaken_for_the_marker(
    monkeypatch,
) -> None:
    """positive control — ป้องกัน mutant ที่ทำให้ `_assert_dev_database` คืน marker
    เสมอไม่ว่า url จะแยกส่วนได้หรือไม่"""
    _fake_env(monkeypatch, {})
    label = mod._assert_dev_database(
        "postgresql+asyncpg://u:p@localhost:5432/poster_nung_db"
    )
    assert label != UNPARSEABLE_URL_LABEL


def test_success_path_yields_the_marker_when_the_url_has_a_query_string(
    monkeypatch,
) -> None:
    """🔴 code-critic round 1 · mutant ME — `_assert_dev_database()` ที่คืนค่าดิบ
    (`f"{host}/{db_name}"`) แทน `_url_label(database_url)` **ผ่านด่านตัดสินได้ปกติ
    ทุกจุด** (host เป็น localhost · db_name ไม่มี hint · ไม่ตรงไฟล์ env จริง) ⇒
    เทสที่เช็คแค่ทาง PrecheckError จับมิวเทชันนี้ไม่ได้เลย ต้องมีเทสที่เดินเส้นทาง
    **สำเร็จ** (ไม่ raise) แล้วเช็คค่าที่คืนมาโดยตรง — `sslmode=require` เป็น query
    string จริงที่ใช้กันทั่วไป (ไม่ใช่รหัสผ่านที่แยกส่วนไม่ได้แบบ `/` `?` `#`) แต่ก็ยัง
    ทำให้ `_url_label()` คืน marker ตาม AC-3 (cosmetic — ไม่ใช่การปฏิเสธ)
    """
    _fake_env(monkeypatch, {})
    label = mod._assert_dev_database(
        "postgresql+asyncpg://u:p@localhost:5432/poster_nung_db?sslmode=require"
    )
    assert label == UNPARSEABLE_URL_LABEL
