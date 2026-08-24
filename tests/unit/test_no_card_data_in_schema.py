"""ADR-0029 D6 · `database-design.md` §9 — schema ต้องไม่มีข้อมูลบัตรหรือเลขบัญชีผู้ซื้อ

🔴 **ทำไมไม่ใช้ `grep -riE "card_number|cvv|expiry" app/` ตามที่ §9 เขียนไว้**
‹พบ 2026-08-22 · INF-32› — grep แบบนั้นจับ **ข้อความในคอมเมนต์ที่อธิบายกฎข้อนี้เอง**
ติดมาด้วย ทำให้ด่านแดงทั้งที่ไม่มีคอลัมน์ผิดแม้แต่ตัวเดียว · ด่านที่ดังเพราะมีคน
*พูดถึง* กฎ คือด่านที่คนจะเรียนรู้ที่จะเพิกเฉย แล้ววันที่มันดังเพราะของจริงจะไม่มีใครฟัง

เทสนี้อ่าน **ชื่อคอลัมน์ใน `Base.metadata`** ซึ่งเป็นสิ่งที่กฎพูดถึงจริง ๆ
และเป็น **closed-world**: กวาดทุกตารางในระบบ ไม่ใช่เฉพาะ `payments`
⇒ ตารางใหม่ที่เพิ่มวันหน้าถูกครอบอัตโนมัติ ไม่ใช่ต้องมีคนนึกได้ว่าต้องมาต่อรายชื่อ
"""

import pytest

import app.models  # noqa: F401 — ต้อง import เพื่อให้ Base.metadata เห็นครบทุกตาราง
from app.core.database import Base

# ชิ้นส่วนของชื่อคอลัมน์ที่แปลว่าเรากำลังเก็บข้อมูลบัตร — ตรวจแบบ substring
# เพราะชื่อจริงที่คนตั้งมักมี prefix/suffix (`buyer_card_number` · `card_cvv_hash`)
FORBIDDEN_FRAGMENTS = (
    "card_number",
    "cardnumber",
    "cvv",
    "cvc",
    "card_expiry",
    "expiry_month",
    "expiry_year",
    "pan",
)

# เลขบัญชีของ **ผู้ซื้อ** ห้ามเก็บ (ADR-0029 D6) — ของ **ผู้ขาย** เก็บได้เพราะต้อง
# โอนเงินให้เขา (BR-L1) และอยู่ใน `seller_profiles` ซึ่งอยู่ใต้ ADR-0020 เต็มรูปแบบ
ALLOWED_BANK_ACCOUNT_COLUMNS = {
    ("seller_profiles", "bank_account_no"),
    # ชื่อบัญชีของผู้ขาย — ต้องมีเพื่อให้โอนเงินถูกคน (BR-L1 · BR-P5)
    ("seller_profiles", "bank_account_name"),
}


def _all_columns() -> list[tuple[str, str]]:
    return [
        (table_name, column.name)
        for table_name, table in sorted(Base.metadata.tables.items())
        for column in table.columns
    ]


def test_no_table_has_a_column_that_looks_like_card_data() -> None:
    offenders = [
        (table, column)
        for table, column in _all_columns()
        if any(fragment in column.lower() for fragment in FORBIDDEN_FRAGMENTS)
    ]
    assert offenders == [], (
        "เจอคอลัมน์ที่ดูเหมือนข้อมูลบัตร — ADR-0029 D6 ห้ามเด็ดขาดทุก Phase "
        f"(ทำแล้วกระโดดไป PCI-DSS SAQ-D): {offenders}"
    )


def test_only_the_seller_may_have_a_bank_account_column() -> None:
    """เลขบัญชี **ผู้ซื้อ** ห้ามเก็บ · ของ **ผู้ขาย** เก็บได้เพราะต้องโอนเงินให้เขา"""
    found = {
        (table, column)
        for table, column in _all_columns()
        if "bank_account" in column.lower()
    }
    unexpected = found - ALLOWED_BANK_ACCOUNT_COLUMNS
    assert unexpected == set(), (
        "เจอคอลัมน์เลขบัญชีนอก seller_profiles — เลขบัญชีที่ปรากฏบนสลิปของผู้ซื้อ "
        f"ห้ามถูกดึงออกมาเก็บเป็นคอลัมน์ (ADR-0029 D6): {sorted(unexpected)}"
    )


@pytest.mark.parametrize("fragment", FORBIDDEN_FRAGMENTS)
def test_the_guard_itself_would_catch_a_bad_column(fragment: str) -> None:
    """ด่านต้องจับได้จริง ไม่ใช่ผ่านเพราะไม่มีอะไรให้จับ

    ‹`test-quality` §3 — เทสที่ผ่านเพราะ input ว่างคือเทสที่ไม่ได้พิสูจน์อะไร›
    """
    fake_column = f"buyer_{fragment}_hash"
    assert any(f in fake_column.lower() for f in FORBIDDEN_FRAGMENTS)


# ══════════════════════════════════════════════════════════════════════
# ADR-0028 INF-32 — สถานะภายในต้องไม่รั่วออก public API
# ══════════════════════════════════════════════════════════════════════


def test_the_public_status_enum_matches_the_query_filter() -> None:
    """`PublicPosterStatus` (สัญญา) กับ `PUBLIC_POSTER_STATUSES` (ตัวกรอง) ต้องตรงกัน

    🔴 ถ้าสองที่นี้หลุดจากกัน จะได้อย่างใดอย่างหนึ่ง:
    · ตัวกรองกว้างกว่าสัญญา → ของหลุดออกไปแล้ว Pydantic ระเบิดเป็น 500
    · สัญญากว้างกว่าตัวกรอง → สัญญาโฆษณาค่าที่ไม่มีวันเกิด
    ทั้งสองแบบเป็นบั๊กที่หาต้นตอยาก เพราะไฟล์ที่ผิดกับไฟล์ที่ระเบิดอยู่คนละชั้น
    """
    from app.repositories.poster_repository import PUBLIC_POSTER_STATUSES
    from app.schemas.poster import PublicPosterStatus

    assert {s.value for s in PUBLIC_POSTER_STATUSES} == {
        s.value for s in PublicPosterStatus
    }


def test_internal_statuses_are_not_part_of_the_public_contract() -> None:
    """ADR-0009 D11 · ADR-0013 D5 — ธงงานภายในไม่ออก public API

    `draft`/`pending_review`/`rejected`/`delisted` บอกเรื่องระหว่างผู้ขายกับ
    แพลตฟอร์ม ไม่ใช่เรื่องของลูกค้า · และการกันไว้ทำให้
    `docs/api/openapi.yaml` **ไม่ต้องเปลี่ยนเลย** จาก ADR-0028
    """
    from app.models.enums import PosterStatus
    from app.schemas.poster import PublicPosterStatus

    internal = {s.value for s in PosterStatus} - {s.value for s in PublicPosterStatus}
    assert internal == {"draft", "pending_review", "rejected", "delisted"}


def test_the_generated_openapi_still_declares_exactly_three_poster_statuses() -> None:
    """ด่านสุดท้าย — อ่านจาก OpenAPI ที่ FastAPI สร้างจริง ไม่ใช่จากโค้ดต้นทาง

    เทสสองตัวข้างบนพิสูจน์ว่า *เราตั้งใจ* ให้มี 3 ค่า · ตัวนี้พิสูจน์ว่า **สิ่งที่ออกไป
    จริงมี 3 ค่า** ซึ่งเป็นคนละคำถาม (docstring ของ enum เคยรั่วเข้า schema มาแล้ว
    ครั้งหนึ่งเมื่อ 2026-08-22)
    """
    from app.main import app

    # 🔴 ชื่อ component ต้องเป็น `PosterStatus` เหมือนเดิมเป๊ะ — เปลี่ยนชื่อคลาสใน
    # `app/schemas/poster.py` เมื่อไหร่ `$ref` ในสัญญาเปลี่ยนทันที = breaking change
    schema = app.openapi()["components"]["schemas"]["PosterStatus"]
    assert schema["enum"] == ["available", "reserved", "sold"]
