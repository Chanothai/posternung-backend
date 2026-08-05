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

# ADR-0014 D3 · §Verification ข้อ 1 — สามค่านี้เท่านั้น
EXPECTED_ENUM_VALUES = ["REFERENCE_MATCHED", "DISCREPANCY_FOUND", "UNKNOWN"]


async def test_verification_status_enum_has_exactly_the_three_values(
    db_session: AsyncSession,
) -> None:
    """🔴 ต้องไม่มี `NOT_CHECKED` — `NULL` แปลว่า "ยังไม่มีใครตรวจ" อยู่แล้ว"""
    result = await db_session.execute(
        text("SELECT unnest(enum_range(NULL::verification_status))::text")
    )
    values = [row[0] for row in result]

    assert values == EXPECTED_ENUM_VALUES
    assert "NOT_CHECKED" not in values
    assert [member.value for member in VerificationStatus] == EXPECTED_ENUM_VALUES


async def test_new_poster_row_gets_null_verification_columns(
    db_session: AsyncSession,
) -> None:
    """ไม่มี `server_default` ทั้งสามคอลัมน์ (ADR-0014 D2)

    เทสนี้แดงทันทีถ้ามีคนเผลอเติม `server_default` ให้คอลัมน์ไหนภายหลัง — ซึ่งจะเป็น
    การอ้างว่าทุกแถวถูกตรวจมาแล้ว (เหตุผลเต็มอยู่ใน D3 · ADR-0009 Alternative 7)
    """
    poster = Poster(title="Fresh Row", price=Decimal("100"))
    db_session.add(poster)
    await db_session.flush()

    row = (
        await db_session.execute(
            text(
                "SELECT verification_status, verification_note, reference_url "
                "FROM posters WHERE id = :id"
            ),
            {"id": poster.id},
        )
    ).one()

    assert row == (None, None, None)
