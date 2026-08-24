"""DB-level test ของ 3 คอลัมน์ใหม่ตาม ADR-0014 — พิสูจน์กับ DB จริง ไม่ใช่กับโมเดล

ยิงตรงเข้า session ไม่ผ่าน service เพราะสิ่งที่ล็อกอยู่ตรงนี้เป็นพฤติกรรมของ *schema*
(ค่าของ enum · การไม่มี server_default) ซึ่ง `scripts/seed/seed_posters.py` ที่เขียน
ตารางตรง ๆ ก็ต้องเจอเหมือนกัน — ทรงเดียวกับ `test_poster_publication_constraint.py`
"""

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import VerificationStatus
from app.models.poster import Poster
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID

# ADR-0014 §Amendment 2 D21 (2026-08-07) — **สองค่านี้เท่านั้น**
# ประวัติของชุดค่า: D3 สามค่า → D12/D13 สี่ค่า → D21 ยุบเหลือสอง เพราะ
# `DISCREPANCY_FOUND` อ้างว่ารู้ว่าอะไรคือมาตรฐาน (ไม่ใช่สิ่งที่ร้านนี้ทำ) และ
# `UNKNOWN` ไม่มีทาง derive ได้จาก 2 ช่องที่คนกรอก (D22)
EXPECTED_ENUM_VALUES = [
    "REFERENCE_FOUND",
    "NO_REFERENCE_FOUND",
]
# ค่าที่ **เคยมีและถูกตัดออกแล้ว** — assertion เชิงลบระบุชื่อ เพราะการ "เผลอเติมกลับ"
# ต่างจากการเติมค่าใหม่ที่ไม่เคยมี: มันมีโค้ดเก่าและเอกสารเก่าชวนให้ทำอยู่เต็มไปหมด
REMOVED_ENUM_VALUES = ["ARTWORK_MATCHED", "DISCREPANCY_FOUND", "UNKNOWN"]


async def test_verification_status_enum_has_exactly_the_two_values(
    db_session: AsyncSession,
) -> None:
    """🔴 ต้องไม่มี `NOT_CHECKED` — `NULL` เป็นสถานะนั้นเอง (D21)

    และต้องไม่มีค่าที่ D21 ตัดออกกลับมาอีก
    """
    result = await db_session.execute(
        text("SELECT unnest(enum_range(NULL::verification_status))::text")
    )
    values = [row[0] for row in result]

    assert values == EXPECTED_ENUM_VALUES
    assert "NOT_CHECKED" not in values
    for removed in REMOVED_ENUM_VALUES:
        assert removed not in values, f"{removed} ถูกตัดออกแล้วที่ D21"
    assert [member.value for member in VerificationStatus] == EXPECTED_ENUM_VALUES


async def test_new_poster_row_gets_null_verification_columns(
    db_session: AsyncSession,
) -> None:
    """ไม่มี `server_default` ทั้งสามคอลัมน์ (ADR-0014 D2)

    เทสนี้แดงทันทีถ้ามีคนเผลอเติม `server_default` ให้คอลัมน์ไหนภายหลัง — ซึ่งจะเป็น
    การอ้างว่าทุกแถวถูกตรวจมาแล้ว (เหตุผลเต็มอยู่ใน D3 · ADR-0009 Alternative 7)
    """
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title="Fresh Row",
        price=Decimal("100"),
    )
    db_session.add(poster)
    await db_session.flush()

    row = (
        await db_session.execute(
            text(
                "SELECT verification_status, reference_note, reference_url "
                "FROM posters WHERE id = :id"
            ),
            {"id": poster.id},
        )
    ).one()

    assert row == (None, None, None)


async def test_old_verification_note_column_is_gone(
    db_session: AsyncSession,
) -> None:
    """ADR-0014 D22 — `verification_note` เปลี่ยนชื่อเป็น `reference_note`

    🔴 **assertion เชิงลบต้องมีคู่กับเชิงบวก** — ถ้าเช็คแค่ว่า `reference_note` มีอยู่
    migration ที่ `add_column` ตัวใหม่แทนที่จะ `alter_column` จะผ่านหน้าตาเฉย
    ทั้งที่ทิ้งคอลัมน์เก่าค้างไว้เป็นแหล่งความจริงที่สอง
    """
    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'posters' AND column_name IN "
            "('reference_note', 'verification_note')"
        )
    )
    columns = {row[0] for row in result}

    assert columns == {"reference_note"}
