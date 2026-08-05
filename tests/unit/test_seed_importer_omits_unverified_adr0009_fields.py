"""ล็อกกฎ ADR-0009 D6: importer (`scripts/seed/seed_posters.py`) เขียนได้แค่ `year`
กับ `needs_review` จาก 10 ฟิลด์ใหม่ของ `posters` — 8 ฟิลด์ที่เหลือต้องไม่ถูกสร้างขึ้น
เลยแม้แต่ key เดียวใน dict ที่จะ insert (ต้องเป็น NULL จนกว่าจะมีคนตรวจใบจริง)

`release_date_text` เพิ่มเข้ารายการนี้ตาม ADR-0009 D13 ข้อ 4 (amendment) — D6 ใช้กับ
ฟิลด์นี้เต็มรูปแบบเหมือน 7 ฟิลด์เดิม · `published_at` เพิ่มตาม ADR-0013 D4 ด้วยหลัก
เดียวกัน (เครื่องไม่มีสิทธิ์ตัดสินใจแทนคนว่าจะเปิดขายใบไหน) · 3 คอลัมน์ของ ADR-0014
เพิ่มตาม D7 (การเขียนค่าคือการอ้างว่ามีคนเทียบใบจริงแล้ว) รวมเป็น 12 ฟิลด์

ไม่ต่อ DB จริง — ทดสอบที่ dict ซึ่ง `build_poster_rows()` สร้างเท่านั้น (ตาม
ship-backend-change §3 — เลี่ยง fixture ที่ไม่จำเป็น)
"""

from decimal import Decimal

from scripts.seed.apply_suggestions import ALLOWED_FIELDS
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
# ADR-0013 D4 — ความพร้อมขายเป็นการตัดสินใจของคน ไม่ใช่ผลพลอยได้ของการ import
# (รอบนี้ไม่มี writer ของ published_at เลยโดยตั้งใจ — เส้นทางเปิดขายคือ INF-11)
FORBIDDEN_PUBLICATION_KEYS = {"published_at"}
# ADR-0014 D7 — ผลการเทียบกับฐานข้อมูลอ้างอิงมาจากคนเท่านั้น · AI/สคริปต์ห้ามเขียน
# **ตลอดกาล** ไม่ใช่แค่รอบนี้ (ข้อห้ามเดียวกับที่ BL-70/BL-71 ล็อกไว้กับ
# `is_authenticated` — ย้ายมาครอบคอลัมน์ใหม่ทั้งดุ้น)
FORBIDDEN_VERIFICATION_KEYS = {
    "verification_status",
    "verification_note",
    "reference_url",
}
FORBIDDEN_IMPORTER_KEYS = (
    FORBIDDEN_ADR0009_KEYS | FORBIDDEN_PUBLICATION_KEYS | FORBIDDEN_VERIFICATION_KEYS
)


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
    leaked = produced_keys & FORBIDDEN_IMPORTER_KEYS
    assert not leaked, f"importer เขียนฟิลด์ที่ยังไม่ผ่านการตรวจ: {leaked}"


def test_importer_never_writes_published_at() -> None:
    """ADR-0013 D4 — seeder ห้ามเปิดขายให้เอง ไม่ว่าจะตั้ง --status เป็นอะไร

    `--status available` แปลว่า "ของอยู่ในวงจรสต็อกขั้น available" เท่านั้น
    ไม่ได้แปลว่าเปิดขายแล้ว (ADR-0013 D1 — สองแกนตั้งฉากกัน)
    """
    rows, _notes = build_poster_rows(
        [_row(year="1999", needs_review="0")],
        status="available",
        dedupe=False,
        grade_threshold=None,
    )

    assert "published_at" not in rows[0]


def test_apply_suggestions_allowlist_never_includes_published_at() -> None:
    """ADR-0013 D4 · ADR-0010 D4.1 — allowlist ของ apply_suggestions ไม่ขยายรอบนี้

    สคริปต์นั้น fail-closed อยู่แล้ว แต่เทสนี้ล็อกไว้ว่าการเผลอเติม `published_at`
    เข้า allowlist ในอนาคตต้องเป็นการตัดสินใจที่มีคนแก้เทสด้วย ไม่ใช่เติมเงียบ ๆ
    """
    assert "published_at" not in ALLOWED_FIELDS


def test_forbidden_keys_set_has_all_twelve_names() -> None:
    """ADR-0014 §Verification ข้อ 5 — ทะเบียนต้องมีครบ 12 ชื่อ

    ล็อกจำนวนไว้เพื่อให้การ *ถอด* ชื่อออกจากทะเบียนต้องเป็นการตัดสินใจที่มีคนแก้เทสด้วย
    """
    assert len(FORBIDDEN_IMPORTER_KEYS) == 12


def test_forbidden_key_registry_catches_a_planted_verification_column() -> None:
    """ADR-0014 §Verification ข้อ 6 — ตรวจ *ตัวกฎ* ไม่ใช่ *อาการ*

    เทสที่ยิง `build_poster_rows()` จะเขียวอยู่ดีถ้ามีคนลบชื่อคอลัมน์ออกจาก
    `FORBIDDEN_IMPORTER_KEYS` (เพราะ importer ไม่ได้เขียนค่าพวกนี้อยู่แล้ว) — เทสนี้
    คือตัวที่ต้องแดงในกรณีนั้น: ยัดคอลัมน์เข้า row dict ปลอมแล้วทะเบียนต้องจับได้ครบทั้งสาม
    """
    planted_row = {
        "title": "Planted",
        "verification_status": "REFERENCE_MATCHED",
        "verification_note": "เทียบกับฐานข้อมูลอ้างอิงแล้ว",
        "reference_url": "https://example.invalid/ref",
    }

    leaked = planted_row.keys() & FORBIDDEN_IMPORTER_KEYS

    # เทียบกับชื่อตรง ๆ ไม่ใช่กับ FORBIDDEN_VERIFICATION_KEYS — ไม่งั้นการลบชื่อออกจาก
    # ทะเบียนจะทำให้ทั้งสองข้างหดพร้อมกันแล้วเทสยังเขียว (จุดอ่อนแบบเดียวกับที่
    # ADR-0014 §Verification ข้อ 6 เตือนไว้)
    assert leaked == {"verification_status", "verification_note", "reference_url"}


def test_apply_suggestions_allowlist_never_includes_verification_fields() -> None:
    """ADR-0014 D7 · ADR-0010 D4.1 — allowlist ไม่ขยายรอบนี้

    `apply_suggestions.py` เป็นเส้นทางที่เอา *ข้อเสนอของ AI* ลง DB จริง การมีชื่อ
    คอลัมน์เหล่านี้ใน allowlist = ให้เครื่องสรุปผลการตรวจแทนคน ซึ่ง D7 ห้ามถาวร
    """
    leaked = FORBIDDEN_VERIFICATION_KEYS & ALLOWED_FIELDS
    assert not leaked, f"AI เขียนฟิลด์ผลการตรวจได้: {leaked}"


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
