"""Unit tests ของ `format_images_per_poster()` — ช่วงจำนวนรูปต่อโปสเตอร์ในรายงาน

ไม่ต่อ DB จริง — ฟังก์ชัน pure รับ Counter เข้ามา (ทรงเดียวกับ
`assert_no_zero_quantity_rows()` / `load_triage()` ในไฟล์เดียวกัน)

เคสที่ทำให้ต้องมีเทสนี้: manifest ว่าง (ยังไม่มีรูป) ซึ่งเกิดจริงเมื่อ seed
โปสเตอร์ก่อนแล้วค่อยเติมรูปด้วย `photo_entry.py` (ADR-0026 · INF-27) —
เดิม `min()` บน Counter ว่างโยน ValueError ที่ `_report()` ซึ่งถูกเรียก **หลัง**
งาน DB ในบล็อก `async with` เดียวกัน ทำให้ transaction rollback ทั้งชุด
"""

from __future__ import annotations

from collections import Counter

from scripts.seed.seed_posters import format_images_per_poster


def test_no_images_at_all_does_not_raise() -> None:
    """เคสที่เคยพัง — ต้องคืนข้อความ ไม่ใช่โยน ValueError."""
    assert format_images_per_poster(Counter()) == "-"


def test_every_poster_has_exactly_one_image() -> None:
    assert format_images_per_poster(Counter({"a": 1, "b": 1})) == "1-1"


def test_range_spans_min_and_max() -> None:
    assert format_images_per_poster(Counter({"a": 1, "b": 4, "c": 2})) == "1-4"


def test_single_poster_reports_its_own_count_on_both_ends() -> None:
    assert format_images_per_poster(Counter({"a": 3})) == "3-3"


# --------------------------------------------------------------------------
# กับดักที่ทำให้ต้องมี guard รอบคำสั่ง INSERT ใน run()
# --------------------------------------------------------------------------


def test_empty_values_compiles_to_default_values_not_a_no_op() -> None:
    """พิสูจน์ว่า `insert().values([])` **ไม่ใช่ no-op**

    SQLAlchemy คอมไพล์ list ว่างเป็น `INSERT ... DEFAULT VALUES` ซึ่งพยายามสร้าง
    แถวเปล่าจริง ๆ แล้วชน NOT NULL ของ `poster_images.poster_id` ทันที — นี่คือ
    เหตุผลที่ `run()` ต้องข้าม *คำสั่ง* เมื่อไม่มีแถว ไม่ใช่พึ่ง ON CONFLICT

    เทสนี้ตรึงพฤติกรรมของ SQLAlchemy ไว้: ถ้าวันหนึ่งมันเปลี่ยนเป็น no-op เทสนี้
    จะแดงและบอกว่า guard นั้นถอดได้แล้ว
    """
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import insert

    from app.models.poster import PosterImage

    sql = str(
        insert(PosterImage.__table__).values([]).compile(dialect=postgresql.dialect())
    )
    assert "DEFAULT VALUES" in sql
