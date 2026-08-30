"""ตัวอ่าน `.env` ของ `scripts/seed/` — ADR-0015 **Amendment 2 (A2-D1 … A2-D4)** · `INF-39`

🔴 **ทุกเทสในไฟล์นี้อ่านไฟล์จริงจาก `tmp_path` — ห้าม monkeypatch `parse_env_file` ทิ้ง**
(`INF-39` **AC-3**) · เหตุผลไม่ใช่ความชอบด้านสไตล์: เทส `assert_target` ที่มีอยู่เดิม
ทั้ง 6 ตัวใน `test_manual_entry.py` **patch ตัวอ่านทิ้งทั้งตัว** แล้วป้อน dict ที่
*ขยายแล้ว* เข้าไปเอง ⇒ **รูปแบบไฟล์จริงไม่เคยถูกทดสอบสักครั้ง** และนั่นคือเหตุผลเดียว
ที่บั๊ก "`--target sit` ถูกปฏิเสธ 100%" รอดมาได้ตั้งแต่ 2026-08-06 โดยเทสเขียวตลอด

**เทสไฟล์นี้ล้มบนโค้ดก่อนแก้ทุกตัวที่แตะการขยายตัวแปร** (AC-2) — พิสูจน์แล้วด้วยการ
รันบน `_parse_env_file()` ฉบับเดิมที่คืนค่า `KEY=VALUE` ดิบ ๆ
"""

from __future__ import annotations

import pytest

from scripts.seed import apply_suggestions as apply_mod
from scripts.seed import manual_entry as manual_mod
from scripts.seed._shared import PrecheckError, parse_env_file

# รหัสผ่านปลอมความยาว 32 อักขระ ทรงเดียวกับ `openssl rand -hex 16` ของจริง
FAKE_PW = "deadbeefdeadbeefdeadbeefdeadbeef"
SIT_URL_EXPANDED = f"postgresql+asyncpg://poster_app:{FAKE_PW}@db:5432/poster_db_sit"
SIT_URL_POINTER = (
    "postgresql+asyncpg://poster_app:$POSTGRES_PASSWORD@db:5432/poster_db_sit"
)


def _write_env(dir_path, name: str, body: str) -> None:
    (dir_path / name).write_text(body, encoding="utf-8")


def _point_repo_root_at(tmp_path, monkeypatch) -> None:
    """ให้ทั้งสองชั้นของด่านอ่านไฟล์จาก `tmp_path`

    ต้องตั้งสองที่: ชั้นแรก (`assert_target_database`) อ่าน `REPO_ROOT` ของ
    `apply_suggestions` · ชั้นที่สอง (`assert_target`) อ่านของ `manual_entry`
    """
    monkeypatch.setattr(apply_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(manual_mod, "REPO_ROOT", tmp_path)


# --------------------------------------------------------------------------
# A2-D1 — รูปที่รองรับ
# --------------------------------------------------------------------------


def test_bare_pointer_is_expanded_from_the_same_file(tmp_path) -> None:
    """`$NAME` ที่ชี้คีย์อื่นในไฟล์เดียวกัน — รูปที่ `.env.sit` ของจริงใช้อยู่"""
    _write_env(
        tmp_path,
        ".env.sit",
        f"POSTGRES_PASSWORD={FAKE_PW}\nDATABASE_URL={SIT_URL_POINTER}\n",
    )
    values = parse_env_file(tmp_path / ".env.sit")

    assert values["DATABASE_URL"] == SIT_URL_EXPANDED
    # 🔴 assertion เชิงลบ — ค่าที่คืนต้อง **ไม่มีตัวชี้หลงเหลือ** ไม่ใช่แค่ "ยาวเท่าที่คาด"
    assert "$" not in values["DATABASE_URL"]
    # ความยาวต้องขยับเท่ากับ (ความยาวรหัสผ่าน − ความยาวตัวชี้) เป๊ะ — บนไฟล์จริง
    # คือ 68 → 82 · ที่นี่ผูกกับ *ความสัมพันธ์* ไม่ใช่ตัวเลขดิบ เพราะชื่อ database
    # ในเทสไม่ใช่ตัวเดียวกับของจริง
    assert len(values["DATABASE_URL"]) == len(SIT_URL_POINTER) - len(
        "$POSTGRES_PASSWORD"
    ) + len(FAKE_PW)


def test_braced_pointer_is_expanded_too(tmp_path) -> None:
    _write_env(
        tmp_path,
        ".env.sit",
        f"POSTGRES_PASSWORD={FAKE_PW}\n"
        "DATABASE_URL=postgresql+asyncpg://poster_app:${POSTGRES_PASSWORD}@db:5432/poster_db_sit\n",
    )
    assert parse_env_file(tmp_path / ".env.sit")["DATABASE_URL"] == SIT_URL_EXPANDED


def test_a_file_without_any_dollar_is_returned_unchanged(tmp_path) -> None:
    """ไฟล์ที่ไม่มีตัวชี้ต้องได้ค่าเดิมเป๊ะ — กันไม่ให้ตัวขยายไปแตะของที่ไม่เกี่ยว"""
    _write_env(
        tmp_path, ".env", f"DATABASE_URL={SIT_URL_EXPANDED}\nJWT_ALGORITHM=HS256\n"
    )
    values = parse_env_file(tmp_path / ".env")

    assert values == {"DATABASE_URL": SIT_URL_EXPANDED, "JWT_ALGORITHM": "HS256"}


def test_expansion_is_one_level_only_and_does_not_recurse(tmp_path) -> None:
    """`ระดับเดียว ไม่ขยายซ้อน` — ค่าที่ถูกอ้างถึงถูกใส่ลงไป **ดิบ ๆ**

    ถ้าวันหนึ่งมีคนทำให้มันขยายซ้อน เทสนี้จะแดง — ตั้งใจให้เป็นการตัดสินใจที่ต้องแก้ ADR
    ไม่ใช่ผลข้างเคียงของการ refactor
    """
    _write_env(tmp_path, ".env", "Z=v\nY=$Z\nX=$Y\n")
    values = parse_env_file(tmp_path / ".env")

    assert values["Y"] == "v"
    assert values["X"] == "$Z"  # ไม่ใช่ "v"


# --------------------------------------------------------------------------
# A2-D1 — รูปที่ **ไม่** รองรับ ต้อง fail-closed ทุกตัว
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "line"),
    [
        (
            "default value",
            "DATABASE_URL=postgresql://u:${POSTGRES_PASSWORD:-fallback}@db/x",
        ),
        ("required form", "DATABASE_URL=postgresql://u:${POSTGRES_PASSWORD:?err}@db/x"),
        ("alternate form", "DATABASE_URL=postgresql://u:${POSTGRES_PASSWORD:+x}@db/x"),
        ("escaped dollar", "DATABASE_URL=postgresql://u:pw$$word@db/x"),
        ("dollar then digit", "DATABASE_URL=postgresql://u:$1abc@db/x"),
        ("trailing dollar", "DATABASE_URL=postgresql://u:pw@db/x$"),
    ],
)
def test_unsupported_variable_forms_fail_closed(tmp_path, label, line) -> None:
    """รูปนอกพื้นผิวของ A2-D1 = `PrecheckError` **ไม่ใช่การเดาว่าเป็นข้อความธรรมดา**

    นี่คือหัวใจของทางเลือก (ค): เราไม่เลียน semantics ของ compose ให้ครบ แต่ปฏิเสธ
    ทุกอย่างที่อยู่นอกพื้นผิว **ดัง ๆ** ⇒ "เลียนไม่ครบ" เป็น error ที่มองเห็น
    ไม่ใช่ค่าที่เพี้ยนเงียบ
    """
    _write_env(tmp_path, ".env.sit", f"POSTGRES_PASSWORD={FAKE_PW}\n{line}\n")

    with pytest.raises(PrecheckError, match="A2-D1") as exc:
        parse_env_file(tmp_path / ".env.sit")
    assert ".env.sit" in str(exc.value)
    assert "DATABASE_URL" in str(exc.value)


def test_pointer_to_a_variable_outside_the_file_fails_closed(tmp_path) -> None:
    """ตัวแปรที่มาจาก shell — compose ขยายให้ได้ แต่เราไม่มีทางรู้ค่า ⇒ ห้ามเดา"""
    _write_env(
        tmp_path,
        ".env.sit",
        "DATABASE_URL=postgresql+asyncpg://poster_app:$PASSWORD_FROM_SHELL@db:5432/poster_db_sit\n",
    )

    with pytest.raises(PrecheckError, match="PASSWORD_FROM_SHELL"):
        parse_env_file(tmp_path / ".env.sit")


def test_error_message_never_contains_the_secret(tmp_path) -> None:
    """`security-baseline` §2 — ข้อความบอกได้แค่ *ชื่อไฟล์ · ชื่อคีย์ · ชื่อตัวแปร*"""
    _write_env(
        tmp_path,
        ".env.sit",
        f"POSTGRES_PASSWORD={FAKE_PW}\n"
        "DATABASE_URL=postgresql://u:${POSTGRES_PASSWORD:-x}@db/x\n",
    )

    with pytest.raises(PrecheckError) as exc:
        parse_env_file(tmp_path / ".env.sit")
    assert FAKE_PW not in str(exc.value)


# --------------------------------------------------------------------------
# AC-2 / AC-4 — `--target sit` ต้องผ่านจริงกับไฟล์ที่มีตัวชี้
# --------------------------------------------------------------------------


def test_target_sit_passes_with_a_real_env_file_that_uses_a_pointer(
    tmp_path, monkeypatch
) -> None:
    """🔴 **เทสหลักของ `INF-39`** — ล้มบนโค้ดก่อนแก้ ผ่านหลังแก้

    ก่อนแก้: ตัวอ่านคืนสตริงยาว 68 ที่ยังมี `$POSTGRES_PASSWORD` ส่วนค่าที่ compose
    ส่งเข้ามาใน environment ยาว 82 ⇒ เทียบตรงเป๊ะแล้วไม่มีวันเท่ากัน ⇒ `PrecheckError`
    """
    _write_env(
        tmp_path,
        ".env.sit",
        f"POSTGRES_PASSWORD={FAKE_PW}\nDATABASE_URL={SIT_URL_POINTER}\n",
    )
    _point_repo_root_at(tmp_path, monkeypatch)

    label = manual_mod.assert_target(SIT_URL_EXPANDED, "sit")

    assert label == "db/poster_db_sit"


def test_target_sit_still_rejects_a_genuinely_different_database(
    tmp_path, monkeypatch
) -> None:
    """AC-6 — ด่านต้องไม่อ่อนลง: ขยายตัวแปรแล้วยังต่างกันจริง = ปฏิเสธเหมือนเดิม"""
    _write_env(
        tmp_path,
        ".env.sit",
        f"POSTGRES_PASSWORD={FAKE_PW}\nDATABASE_URL={SIT_URL_POINTER}\n",
    )
    _point_repo_root_at(tmp_path, monkeypatch)
    other = f"postgresql+asyncpg://poster_app:{FAKE_PW}@db:5432/somewhere_else_sit"

    with pytest.raises(PrecheckError, match="ไม่ตรงกับค่าใน"):
        manual_mod.assert_target(other, "sit")


def test_target_sit_rejects_the_same_place_with_a_different_password(
    tmp_path, monkeypatch
) -> None:
    """🔴 **ข้อที่ทางเลือก (ข) จะปล่อยผ่าน** — host/database เหมือนกันเป๊ะ ต่างแค่รหัสผ่าน

    ในโทโพโลยีนี้ hostname เป็น `db` ทุก environment และชื่อ database ก็ซ้ำกันได้
    (ค่า default ของ `.env.example`) ⇒ ถ้าถอดรหัสผ่านออกจากการเทียบ จะไม่เหลืออะไร
    แยก sit ออกจาก environment อื่นเลย (ADR-0015 **A2-D2**)
    """
    _write_env(
        tmp_path,
        ".env.sit",
        f"POSTGRES_PASSWORD={FAKE_PW}\nDATABASE_URL={SIT_URL_POINTER}\n",
    )
    _point_repo_root_at(tmp_path, monkeypatch)
    same_place = (
        "postgresql+asyncpg://poster_app:0000000000000000@db:5432/poster_db_sit"
    )

    with pytest.raises(PrecheckError) as exc:
        manual_mod.assert_target(same_place, "sit")
    assert "ต่างที่ผู้ใช้หรือรหัสผ่าน" in str(exc.value)
    assert FAKE_PW not in str(exc.value)


def test_target_sit_still_refuses_when_the_file_is_missing(
    tmp_path, monkeypatch
) -> None:
    """AC-6 — fail-closed เดิมของชั้นที่สองต้องอยู่ครบ (ไม่มีไฟล์ = ไม่รัน)"""
    _point_repo_root_at(tmp_path, monkeypatch)

    with pytest.raises(PrecheckError, match="ยืนยันปลายทางไม่ได้"):
        manual_mod.assert_target(SIT_URL_EXPANDED, "sit")


# --------------------------------------------------------------------------
# AC-11 — ด่าน fail-open ของ ADR-0010 D7 (A2-D3)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["dev", "sit"])
def test_production_env_file_written_with_a_pointer_now_blocks_every_target(
    tmp_path, monkeypatch, target
) -> None:
    """🔴 **ด่านที่ไม่เคยยิงเลย** — `DATABASE_URL` ห้ามตรงกับค่าใน `.env.production`

    ด่านนี้ **fail-open โดยธรรมชาติ** (ไม่เท่ากัน = ปล่อยผ่าน) และใช้ตัวอ่านตัวเดียวกัน
    ⇒ ถ้าไฟล์ฝั่ง production เขียน `DATABASE_URL` แบบประกอบจากตัวแปร (ซึ่งเป็นธรรมเนียม
    เดียวกับ `.env.sit`) มันจะเทียบสตริงที่ยังมีตัวชี้กับค่าที่ขยายแล้ว **ไม่มีวันเท่ากัน
    และไม่มีใครรู้** · เทสนี้คือด่านที่กันไม่ให้ย้อนกลับไปสภาพนั้น
    """
    prod_url = f"postgresql+asyncpg://poster_app:{FAKE_PW}@db:5432/poster_db"
    _write_env(
        tmp_path,
        ".env.production",
        f"POSTGRES_PASSWORD={FAKE_PW}\n"
        "DATABASE_URL=postgresql+asyncpg://poster_app:$POSTGRES_PASSWORD@db:5432/poster_db\n",
    )
    _write_env(tmp_path, ".env.sit", f"DATABASE_URL={prod_url}\n")
    _point_repo_root_at(tmp_path, monkeypatch)

    with pytest.raises(PrecheckError, match=r"\.env\.production"):
        apply_mod.assert_target_database(prod_url, target)


def test_the_production_guard_would_catch_a_url_it_is_supposed_to_catch(
    tmp_path, monkeypatch
) -> None:
    """เทสคู่ที่พิสูจน์ว่า **ด่านนั้นมีอยู่จริง** ไม่ใช่ผ่านเพราะไม่มีอะไรให้ตรวจ

    ‹ทรงเดียวกับ `test_the_guard_itself_would_catch_a_bad_column`› — url ที่ **ไม่**
    ตรงกับไฟล์ production ต้องผ่านด่านนี้ไปได้ ถ้าเทสข้างบนแดงเพราะเหตุอื่น
    (เช่นชื่อ database มีคำต้องห้าม) เทสนี้จะจับได้
    """
    _write_env(
        tmp_path,
        ".env.production",
        f"POSTGRES_PASSWORD={FAKE_PW}\n"
        "DATABASE_URL=postgresql+asyncpg://poster_app:$POSTGRES_PASSWORD@db:5432/poster_db\n",
    )
    _point_repo_root_at(tmp_path, monkeypatch)
    dev_url = "postgresql+asyncpg://poster_app:other@localhost:5432/poster_nung_db"

    assert (
        apply_mod.assert_target_database(dev_url, "dev") == "localhost/poster_nung_db"
    )


# --------------------------------------------------------------------------
# AC-8 / AC-12 — ตัวอ่านมีตัวเดียว
# --------------------------------------------------------------------------


def test_every_lane_uses_the_same_reader_object(tmp_path) -> None:
    """`is` ไม่ใช่ `==` — ก๊อปที่สองคือบั๊กเดิมที่รอวันกลับมา (AC-12)"""
    from scripts.seed import seed_posters as seed_mod

    assert apply_mod._parse_env_file is parse_env_file
    assert manual_mod._parse_env_file is parse_env_file
    assert seed_mod._parse_env_file is parse_env_file
    # `seed_posters` เคยมี `PrecheckError` เป็นคลาสของตัวเอง — ถ้ากลับไปเป็นแบบนั้น
    # `except PrecheckError` ของมันจะจับ error จากตัวอ่านที่ย้ายไป `_shared` ไม่ติด
    assert seed_mod.PrecheckError is PrecheckError
