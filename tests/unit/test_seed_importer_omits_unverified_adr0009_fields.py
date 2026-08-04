"""ล็อกกฎ ADR-0009 D6: importer (`scripts/seed/seed_posters.py`) เขียนได้แค่ `year`
กับ `needs_review` จาก 10 ฟิลด์ใหม่ของ `posters` — 8 ฟิลด์ที่เหลือต้องไม่ถูกสร้างขึ้น
เลยแม้แต่ key เดียวใน dict ที่จะ insert (ต้องเป็น NULL จนกว่าจะมีคนตรวจใบจริง)

`release_date_text` เพิ่มเข้ารายการนี้ตาม ADR-0009 D13 ข้อ 4 (amendment) — D6 ใช้กับ
ฟิลด์นี้เต็มรูปแบบเหมือน 7 ฟิลด์เดิม

ไม่ต่อ DB จริง — ทดสอบที่ dict ซึ่ง `build_poster_rows()` สร้างเท่านั้น (ตาม
ship-backend-change §3 — เลี่ยง fixture ที่ไม่จำเป็น)
"""

from decimal import Decimal

from scripts.seed.seed_posters import build_poster_rows

# 8 ฟิลด์ของ ADR-0009 (D1 + D13 amendment) ที่ importer ห้ามเขียนเด็ดขาด
# (ต้องเป็น NULL จนกว่าจะมีคนตรวจ)
FORBIDDEN_ADR0009_KEYS = {
    "poster_type",
    "release_region",
    "release_date_text",
    "release_date",
    "copyright_year",
    "size_format",
    "restoration_status",
    "restoration_note",
}


def _row(**overrides: str) -> dict[str, str]:
    base = {
        "poster_uuid": "240a94bd-242f-5254-9bf3-9b445315b271",
        "idx": "1",
        "title": "Test Poster",
        "price_thb": "1000",
        "is_unique": "1",
        "size": "27x40",
        "era_decade": "1990",
        "studio": "Test Studio",
        "year": "",
        "needs_review": "0",
        # มีอยู่ใน CSV จริง (print_region) — ใส่ไว้เพื่อพิสูจน์ว่า importer ไม่หยิบไปใช้
        # เป็น release_region เลย (ADR-0009 D7) แม้ค่าจะหน้าตาคล้ายกัน (TH/US)
        "print_region": "TH",
    }
    base.update(overrides)
    return base


def test_importer_row_never_contains_forbidden_adr0009_keys() -> None:
    rows, _notes = build_poster_rows(
        [_row(year="1999", needs_review="0")],
        status="available",
        dedupe=False,
        grade_threshold=None,
    )

    assert len(rows) == 1
    produced_keys = set(rows[0].keys())
    leaked = produced_keys & FORBIDDEN_ADR0009_KEYS
    assert not leaked, f"importer เขียนฟิลด์ที่ยังไม่ผ่านการตรวจ: {leaked}"


def test_importer_never_maps_print_region_into_release_region() -> None:
    """D7 — print_region (ภูมิภาคที่พิมพ์) ต้องไม่ถูกใช้เป็น release_region
    (ภูมิภาคที่ฉาย) แม้ค่าจะเป็น TH/US เหมือนกันก็ตาม"""
    rows, _notes = build_poster_rows(
        [_row(year="", needs_review="0")],
        status="available",
        dedupe=False,
        grade_threshold=None,
    )

    assert "release_region" not in rows[0]


def test_needs_review_is_always_true_with_year_even_if_csv_says_false() -> None:
    """ADR-0009 D6: importer ไม่มีสิทธิ์เขียน needs_review=False เลย — ค่า `0`
    ใน CSV มาจาก heuristic ของ prepare_seed.py ไม่ใช่คนตรวจ ต้องถูกทับเป็น True เสมอ."""
    rows, _notes = build_poster_rows(
        [_row(year="1999", needs_review="0")],
        status="available",
        dedupe=False,
        grade_threshold=None,
    )

    assert rows[0]["year"] == 1999
    assert rows[0]["needs_review"] is True


def test_needs_review_is_always_true_without_year_even_if_csv_says_false() -> None:
    """เคสที่เคย regress: ไม่มี year ก็ยังต้องเป็น True เสมอ ไม่ใช่หยิบค่า CSV
    มาใช้ตรง ๆ (ก่อนแก้ตาม GATE 3 F1 โค้ดเก่าจะคืน False ในเคสนี้ — ทดสอบนี้ fail
    กับโค้ดเก่าจริง เป็นการพิสูจน์ว่าจับ regression ได้)."""
    rows, _notes = build_poster_rows(
        [_row(year="", needs_review="0")],
        status="available",
        dedupe=False,
        grade_threshold=None,
    )

    assert rows[0]["year"] is None
    assert rows[0]["needs_review"] is True


def test_needs_review_is_always_true_when_csv_already_says_true() -> None:
    """sanity — เคสที่ CSV เห็นด้วยอยู่แล้วว่า True ต้องไม่เพี้ยนไปเป็น False."""
    rows, _notes = build_poster_rows(
        [_row(year="", needs_review="1")],
        status="available",
        dedupe=False,
        grade_threshold=None,
    )

    assert rows[0]["year"] is None
    assert rows[0]["needs_review"] is True


def test_importer_row_has_exactly_the_two_allowed_adr0009_keys() -> None:
    """สอง sanity check รวมกัน: ต้องมี year/needs_review อยู่จริง (ไม่ใช่แค่ไม่มี
    7 ตัวที่ห้าม) และค่าที่เหลือของ Decimal ราคายังแปลงถูกต้องตามเดิม (ไม่ regress)."""
    rows, _notes = build_poster_rows(
        [_row(year="1985", needs_review="0", price_thb="450.00")],
        status="available",
        dedupe=False,
        grade_threshold=None,
    )

    row = rows[0]
    assert "year" in row
    assert "needs_review" in row
    assert row["price"] == Decimal("450.00")
