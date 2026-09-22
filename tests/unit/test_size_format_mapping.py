"""ADR-0009 **D4 + D16** — mapping ตัวเดียวจากขนาดที่วัดได้ → `size_format`

D4 บังคับว่า mapping ต้องมี **เทส** ไฟล์นี้คือเทสนั้น · D16 เติมตารางที่ D4 เว้นไว้
และตัดสินว่า input คือ *การวัด* ไม่ใช่รูป ไม่ใช่ข้อความโฆษณา
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.size_format import _MEASURED_TO_FORMAT, derive_size_format
from app.models.enums import SizeFormat


def _d(v: str) -> Decimal:
    return Decimal(v)


# --- ตาราง D16 ตรง ๆ ---


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        # สองแถวที่ D16 เขียนไว้เป็นตัวอักษร
        ("27", "40", SizeFormat.ONE_SHEET),
        ("27", "41", SizeFormat.ONE_SHEET),
        # "ขนาดอื่นที่ไม่อยู่ในตาราง → OTHER"
        ("30", "40", SizeFormat.OTHER),  # quad — อยู่ใน enum แต่ **ไม่อยู่ในตาราง D16**
        ("21", "31", SizeFormat.OTHER),  # ใบไทยดั้งเดิม — D16 บอกเองว่าถูกต้อง
        ("27", "39", SizeFormat.OTHER),
    ],
)
def test_maps_exactly_what_the_d16_table_says(
    width: str, height: str, expected: SizeFormat
) -> None:
    assert derive_size_format(_d(width), _d(height)) is expected


def test_trailing_zeros_do_not_change_the_answer() -> None:
    """`27.00 × 40.00` ที่อ่านกลับจาก `Numeric(5, 2)` ต้องเท่ากับ `27 × 40`

    ค่าที่คนกรอกเข้าไปคือ `27` แต่ค่าที่ **อ่านกลับจาก DB** คือ `Decimal("27.00")` —
    ถ้า mapping ผูกกับรูปแบบตัวอักษรแทนค่าเชิงตัวเลข ใบเดียวกันจะได้คำตอบต่างกัน
    ระหว่างรอบที่เขียนกับรอบที่อ่านซ้ำ ซึ่งละเมิด "deterministic" ของ D4
    """
    assert derive_size_format(_d("27.00"), _d("40.0")) is SizeFormat.ONE_SHEET


# --- สามค่าที่ต้องแยกจากกันตลอดกาล: None ≠ OTHER ≠ UNKNOWN ---


@pytest.mark.parametrize(
    ("width", "height"),
    [(_d("27"), None), (None, _d("40")), (None, None)],
)
def test_incomplete_measurement_is_none_never_other(
    width: Decimal | None, height: Decimal | None
) -> None:
    """🔴 วัดไม่ครบ = `None` (ยังไม่มีใครวัด) **ไม่ใช่ `OTHER`** (วัดแล้วไม่เข้าสเกล)

    `OTHER` เป็นคำกล่าวอ้างว่า *มีการวัดเกิดขึ้นแล้ว* — คืนมันตอนที่ยังวัดไม่ครบคือ
    การอ้างงานที่ไม่เคยเกิด · ความต่างชนิดเดียวกับที่ ADR-0009 D2 บังคับระหว่าง
    `NULL` กับ `UNKNOWN` แค่เลื่อนลงมาอีกชั้น (D16)
    """
    assert derive_size_format(width, height) is None


def test_unknown_is_never_produced_by_the_machine() -> None:
    """🔴 `UNKNOWN` = *คนตรวจใบจริงแล้วตัดสินไม่ได้* — ADR-0009 D2 ให้คนเขียนเท่านั้น

    closed-world: ไล่ทุกคู่ค่าที่เป็นไปได้ในตาราง + ตัวอย่างนอกตาราง แล้วยืนยันว่า
    ไม่มีเส้นทางไหนคืน `UNKNOWN` เลย · assertion เชิงลบแบบระบุชื่อ (`!= UNKNOWN`)
    ในเคสเดียวจะผ่านฟรี เพราะเคสนั้นตอบ `ONE_SHEET` อยู่แล้ว
    """
    produced = {derive_size_format(w, h) for w, h in _MEASURED_TO_FORMAT}
    produced |= {
        derive_size_format(_d("21"), _d("31")),
        derive_size_format(_d("30"), _d("40")),
        derive_size_format(None, None),
    }
    assert SizeFormat.UNKNOWN not in produced
    # closed-world — ค่าที่ฟังก์ชันนี้ผลิตได้มีสามอย่างนี้เท่านั้น ไม่ใช่ "อย่างน้อยสามอย่าง"
    assert produced == {SizeFormat.ONE_SHEET, SizeFormat.OTHER, None}


# --- สิ่งที่ D16 ตัดสินไว้ชัดและห้ามหลุด ---


def test_swapped_sides_are_not_silently_accepted_as_one_sheet() -> None:
    """`40 × 27` ไม่ใช่ `ONE_SHEET` — ตาราง D16 เขียนเป็น *กว้าง × สูง* มีลำดับ

    ⚠️ **แต่ผลที่ได้คือ `OTHER` ซึ่งแปลว่า "วัดแล้วไม่เข้าสเกล"** ทั้งที่ความจริงคือ
    *กรอกสลับด้าน* — สองอย่างนี้ไม่เท่ากันและ D16 ยังไม่ได้ตัดสินว่าจะแยกยังไง
    (`docs/BACKLOG.md` **BL-95**) · เทสนี้ล็อกพฤติกรรมวันนี้ไว้ **pin ≠ รับรองว่าถูก**
    """
    assert derive_size_format(_d("40"), _d("27")) is SizeFormat.OTHER


def test_near_misses_are_other_because_d16_has_no_tolerance() -> None:
    """`27 × 40.25` → `OTHER` เพราะตาราง D16 ไม่มีระยะคลาดเคลื่อน

    ⚠️ ขอบตัดไม่เท่ากันเป็นเรื่องปกติของงานพิมพ์เก่า — ถ้าวัดจริงแล้วเกือบทุกใบ
    ตกมาที่นี่ แปลว่าต้องแก้ ADR ไม่ใช่แอบใส่ tolerance ในฟังก์ชัน (**BL-95**)
    """
    assert derive_size_format(_d("27"), _d("40.25")) is SizeFormat.OTHER
    assert derive_size_format(_d("26.9"), _d("40")) is SizeFormat.OTHER


def test_the_guess_column_can_never_reach_this_function() -> None:
    """🔴 D4 — `posters.size` (`size_guess`) ใช้เป็น input ไม่ได้ตลอดกาล

    ล็อกที่ **ลายเซ็นของฟังก์ชัน**: มันรับได้แค่ `Decimal | None` สองตัว ไม่มีทาง
    ส่งสตริง `"27x40"` เข้ามาได้เลยแม้จะอยากส่ง · ถ้าวันไหนมีใครเพิ่มพารามิเตอร์
    ที่รับสตริง (หรือ overload ให้ parse เอง) เทสนี้แดงทันที
    """
    import inspect

    params = inspect.signature(derive_size_format).parameters
    assert list(params) == ["width_in", "height_in"]
    for p in params.values():
        assert p.annotation == "Decimal | None"
