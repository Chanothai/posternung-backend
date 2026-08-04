"""Parser เดียวที่แปลง `Poster.release_date_text` (observed) → `Poster.release_date`
(derived) ตาม ADR-0009 D13 ข้อ 2 — **ห้ามมี writer ตัวที่สอง** ทั้ง INF-08
(apply_suggestions ในอนาคต) และ admin write endpoint ที่จะมาทีหลังต้องเรียกฟังก์ชัน
นี้ตัวเดียวกัน ไม่ใช่ copy logic ไปเขียนเอง

เป็น pure function ล้วน — รับ `str | None` คืนผล ไม่อ่าน `year`/`era_decade` หรือ
อะไรจาก DB มาช่วยตัดสิน (D13 ข้อ 4)

## ทำไมวันที่กำกวมต้องคืน "parse ไม่ได้" แทนที่จะเดา

โปสเตอร์ต้นฉบับของสหรัฐฯ พิมพ์วันที่แบบ `MM/DD/YY` ส่วนของไทย/UK พิมพ์แบบ
`DD/MM/YY` — แคตตาล็อกนี้มีทั้งสองแบบปนกันและไม่มีธงบอกว่าใบไหนเป็นแบบไหน
ถ้าทั้งสองตัวเลข ≤ 12 (เช่น `05/06/23`) การเดาแล้วเก็บลง `DATE` จะสร้างข้อมูลที่
"ดูสมบูรณ์" แต่ผิดได้ 50% โดยตรวจย้อนไม่ได้เลยว่าเดาผิดหรือถูก — ขัด D2/D6 ที่ห้าม
เครื่องอ้างว่าตัดสินใจแทนคน จึงต้องคืนสถานะ AMBIGUOUS แยกออกมาแทนที่จะยัดเป็น
`DATE` ที่ดูน่าเชื่อถือ

เคสที่ *แยกได้จริง* เพราะเลขตัวใดตัวหนึ่ง > 12 (ไม่มีทางเป็นเดือน) ไม่ถือว่ากำกวม —
แก้ปัญหาด้วยขนาดตัวเลข ไม่ต้องเดาจาก separator (`.` หรือ `/`) เลย
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum

# --- ปีสองหลัก (YY) ---
# ตีความตามธรรมเนียม POSIX/glibc strptime("%y"): 00–68 → 20YY, 69–99 → 19YY
# เลือกค่าคงที่นี้แทนการคำนวณจาก datetime.now()/date.today() เพราะถ้าคำนวณจาก
# วันที่ปัจจุบัน ผลลัพธ์จะเปลี่ยนไปเรื่อยๆ ตามวันที่รัน — parser จะไม่ deterministic
# (เทสวันนี้ผ่าน พรุ่งนี้อาจไม่ผ่าน) และข้อมูลที่ import ปีนี้กับปีหน้าจะตีความปีเดียวกัน
# ต่างกัน ซึ่งกู้คืนย้อนหลังไม่ได้ (แนวเดียวกับเหตุผลที่ D2 ห้ามใช้เวลาปัจจุบันตัดสิน)
# ทบทวนอีกครั้งเมื่อแคตตาล็อกเริ่มมีโปสเตอร์พิมพ์วันที่หลังปี ค.ศ. 2068 จริง —
# ไม่ควรเกิดขึ้นในช่วงอายุของระบบนี้ (โปสเตอร์หนังเก่าสุดที่พบในแคตตาล็อกปัจจุบันคือ
# ทศวรรษ 1960s ไม่มีทางมีปีพิมพ์เกินปีปัจจุบันของโลกจริง)
TWO_DIGIT_YEAR_PIVOT = 69

# --- พ.ศ. → ค.ศ. ---
# ปี 4 หลักที่อยู่ในช่วงนี้ถือว่าเป็นพุทธศักราช (ปีคริสต์ศักราชของโปสเตอร์หนังไม่มีทาง
# อยู่ในช่วง 2400-2600) — ลบ 543 เสมอ (ADR-0009 D13 กติกาข้อ 3)
_BUDDHIST_ERA_MIN = 2400
_BUDDHIST_ERA_MAX = 2600
_BUDDHIST_ERA_OFFSET = 543

_ENGLISH_MONTHS: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_THAI_MONTHS: dict[str, int] = {
    "มกราคม": 1,
    "กุมภาพันธ์": 2,
    "มีนาคม": 3,
    "เมษายน": 4,
    "พฤษภาคม": 5,
    "มิถุนายน": 6,
    "กรกฎาคม": 7,
    "กรกฏาคม": 7,  # สะกดแบบพบได้ใน CSV จริง (ฏ/ฎ)
    "สิงหาคม": 8,
    "กันยายน": 9,
    "ตุลาคม": 10,
    "พฤศจิกายน": 11,
    "ธันวาคม": 12,
}

# ตัดคำนำหน้าวันในสัปดาห์แบบไทยออกก่อน tokenize เช่น "พุธที่ 15 กุมภาพันธ์"
_THAI_WEEKDAY_PREFIX = re.compile(
    r"^(?:วันจันทร์|วันอังคาร|วันพุธ|วันพฤหัสบดี|วันศุกร์|วันเสาร์|วันอาทิตย์|"
    r"จันทร์|อังคาร|พุธ|พฤหัสบดี|ศุกร์|เสาร์|อาทิตย์)ที่\s*"
)

# รูปแบบตัวเลขคั่นด้วย `.` `/` หรือช่องว่าง สามกลุ่ม เช่น 11.16.12 · 20/7/23 ·
# 20/7/2023 · 20 7 2023 — รองรับช่องว่างเพิ่มเพราะพบจริงใน CSV (`'20 7 2023'`) และ
# ไม่กำกวมเรื่องตัวคั่นเลย เทียบกับ `.`/`/` (ตัดสินด้วยขนาดตัวเลขเหมือนกันทั้งหมด)
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[./ ](\d{1,2})[./ ](\d{2}|\d{4})$")

# รูปแบบตัวเลขคั่นด้วย `.` `/` หรือช่องว่าง สองกลุ่ม (ไม่มีปี) เช่น 11.19 · 7.15 —
# รู้แค่วัน/เดือน เหมือน "March 18" ต่างกันแค่เดือนเป็นตัวเลขแทนชื่อ
_NUMERIC_MONTH_DAY = re.compile(r"^(\d{1,2})[./ ](\d{1,2})$")


class ReleaseDateParseStatus(str, Enum):
    """สถานะของการ parse — แยก "ไม่มีข้อมูลเลย" ออกจาก "มีข้อความแต่ parse ไม่ผ่าน"
    เพราะ INF-08 ต้องรายงานว่ามีกี่แถวที่มี `release_date_text` แต่ parse ไม่ผ่าน
    (ต้องกลับมาเติมด้วยมือ) แยกจากแถวที่ไม่มี input เลยตั้งแต่ต้น
    """

    # ไม่มี release_date_text เลย (None หรือ string ว่าง)
    NO_INPUT = "NO_INPUT"
    # parse สำเร็จ ได้ date ครบทั้งวัน/เดือน/ปี
    PARSED = "PARSED"
    # มีข้อความและอ่านส่วนประกอบได้บ้าง (เช่น เดือน) แต่ไม่ครบพอเป็น DATE
    # (ขาดวัน และ/หรือขาดปี)
    INCOMPLETE = "INCOMPLETE"
    # ตัวเลขรูปแบบ DD/MM หรือ MM/DD ที่ทั้งสองค่า ≤ 12 — แยกไม่ได้ว่าแบบไหน
    AMBIGUOUS = "AMBIGUOUS"
    # catch-all: มีข้อความแต่ไม่เข้าเงื่อนไขของสถานะอื่นข้างบนเลย ครอบทั้ง (ก) ไม่มี
    # ส่วนประกอบวันที่ที่จับได้เลย (เช่น "COMING SOON") (ข) จับองค์ประกอบบางส่วนได้แต่
    # ไม่พอจะนับเป็น INCOMPLETE เพราะไม่รู้เดือน (เช่น "2022", "SUMMER 2010" — มีปีแต่
    # ไม่มีชื่อเดือนที่ parser รู้จัก) (ค) ตัวเลขจับได้ครบสามส่วนแต่ไม่ใช่ปฏิทินจริง
    # (เช่น 30 กุมภาพันธ์) หรือ (ง) ตัวเลขสองตัว > 12 พร้อมกันจนไม่มีทางเป็นวัน/เดือนได้เลย
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class ReleaseDateParseResult:
    """ผลของ `parse_release_date_text()` — `value` มีค่าเฉพาะตอน
    `status is ReleaseDateParseStatus.PARSED` เท่านั้น สถานะอื่นทั้งหมด `value`
    ต้องเป็น `None` เสมอ (ผู้เรียกไม่ควรอ่าน `value` โดยไม่เช็ค `status` ก่อน)
    """

    status: ReleaseDateParseStatus
    value: date | None


def _expand_two_digit_year(yy: int) -> int:
    return 2000 + yy if yy < TWO_DIGIT_YEAR_PIVOT else 1900 + yy


def _apply_buddhist_era(year: int) -> int:
    if _BUDDHIST_ERA_MIN <= year <= _BUDDHIST_ERA_MAX:
        return year - _BUDDHIST_ERA_OFFSET
    return year


def _expand_year_component(value: int, digits: int) -> int:
    """ขยาย (value, จำนวนหลักดั้งเดิม) ให้เป็นปี ค.ศ. เต็ม — ตรรกะเดียวกับ `_resolve_year`
    ทุกอย่าง (pivot 69 สำหรับปีสองหลัก, ช่วง พ.ศ. 2400-2600 สำหรับปีสี่หลัก) แค่รับ
    ค่าที่ tokenizer ของ `_parse_named` แยกไว้แล้วแทนที่จะรับ raw string ตรงๆ —
    ทำให้เส้นทางชื่อเดือนกับเส้นทางตัวเลขขยายปีด้วยกฎชุดเดียวกันเป๊ะ (ไม่มี writer
    ที่สองสำหรับกฎขยายปี — ดู module docstring ข้อ D13 ข้อ 2)"""
    year = _expand_two_digit_year(value) if digits == 2 else value
    return _apply_buddhist_era(year)


def _resolve_year(raw: str) -> int:
    return _expand_year_component(int(raw), len(raw))


def _build(year: int, month: int, day: int) -> ReleaseDateParseResult:
    try:
        parsed = date(year, month, day)
    except ValueError:
        # เช่น 30 กุมภาพันธ์ — ตัวเลขจับได้ครบแต่ไม่ใช่ปฏิทินจริง
        return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)
    return ReleaseDateParseResult(ReleaseDateParseStatus.PARSED, parsed)


def _parse_numeric(match: re.Match[str]) -> ReleaseDateParseResult:
    a, b = int(match.group(1)), int(match.group(2))
    year = _resolve_year(match.group(3))

    if a == 0 or b == 0:
        # 0 ไม่ใช่วันหรือเดือนที่ valid ไม่ว่าตีความแบบไหน — ตัดสินไม่ได้แม้จะเดา
        # (ต่างจากกรณี a==b ที่ตีความแบบไหนก็ได้ผลลัพธ์เดียวกัน เพราะ 0 ไม่ valid เลย
        # ไม่มี "ผลลัพธ์เดียวกัน" ให้พูดถึง)
        return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)
    if a > 12 and b > 12:
        # ไม่มีทางเป็นทั้งวันและเดือนพร้อมกัน (เดือน > 12 ไม่มีจริง) — จับไม่ได้ว่า
        # ใครคือวันใครคือเดือน แม้เดาก็ไม่ได้ผลลัพธ์ที่ valid
        return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)
    if a > 12:
        # a เป็นเดือนไม่ได้ (>12) → a ต้องเป็นวัน, b เป็นเดือน (DD/MM)
        day, month = a, b
    elif b > 12:
        # b เป็นเดือนไม่ได้ → a เป็นเดือน, b เป็นวัน (MM/DD)
        day, month = b, a
    elif a == b:
        # ค่าเท่ากัน ตีความแบบไหนก็ได้ผลลัพธ์เดียวกัน ไม่กำกวมจริง
        day = month = a
    else:
        # ทั้งคู่ ≤ 12 และไม่เท่ากัน — DD/MM กับ MM/DD ให้คนละวันที่ ตัดสินไม่ได้จาก
        # ตัวเลขอย่างเดียว (ดู module docstring) → ต้องคืน "parse ไม่ได้" ไม่ใช่เดา
        return ReleaseDateParseResult(ReleaseDateParseStatus.AMBIGUOUS, None)

    return _build(year, month, day)


def _parse_numeric_month_day(match: re.Match[str]) -> ReleaseDateParseResult:
    """ตัวเลขสองกลุ่มคั่นด้วย `.` `/` หรือช่องว่าง ไม่มีปี (เช่น `11.19`, `7.15`) —
    เทียบเท่า "March 18" ที่รู้เดือน+วันแต่ขาดปี ต่างกันแค่เดือนเป็นตัวเลขแทนชื่อ ใช้
    กฎแยกวัน/เดือนชุดเดียวกับ `_parse_numeric` (เลข > 12 ไม่มีทางเป็นเดือน)"""
    a, b = int(match.group(1)), int(match.group(2))

    if a == 0 or b == 0:
        return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)
    if a > 12 and b > 12:
        return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)
    if a > 12:
        day, month = a, b
    elif b > 12:
        day, month = b, a
    elif a == b:
        day = month = a
    else:
        # ทั้งคู่ ≤ 12 และไม่เท่ากัน — ไม่รู้ว่าใครคือวันใครคือเดือน (เหมือน
        # `_parse_numeric` แต่ไม่มีปีให้ด้วย ยังกำกวมเรื่อง day/month เหมือนเดิม)
        return ReleaseDateParseResult(ReleaseDateParseStatus.AMBIGUOUS, None)

    if not (1 <= month <= 12) or not (1 <= day <= 31):
        # ตัวเลขเกินขอบเขตที่เป็นวัน/เดือนได้จริง (เช่น "45.6") — ไม่ใช่ปฏิทินจริง
        return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)

    return ReleaseDateParseResult(ReleaseDateParseStatus.INCOMPLETE, None)


def _parse_named(stripped: str) -> ReleaseDateParseResult:
    without_weekday = _THAI_WEEKDAY_PREFIX.sub("", stripped)
    tokens = without_weekday.replace(",", " ").split()

    month: int | None = None
    numbers: list[tuple[int, int]] = []  # (value, จำนวนหลัก)

    for token in tokens:
        if token.isdigit():
            numbers.append((int(token), len(token)))
            continue
        month_num = _ENGLISH_MONTHS.get(token.lower()) or _THAI_MONTHS.get(token)
        if month_num is not None:
            if month is not None:
                # มีชื่อเดือนสองตัว (ข้อความประหลาด) — ไม่พยายามเดาว่าตัวไหนถูก
                return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)
            month = month_num
        # token อื่นที่จับไม่ได้ (เช่น "SUMMER", "COMING", "SOON") ถูกข้ามเงียบๆ —
        # ไม่ใช้เป็นสัญญาณอะไร เพราะไม่มีความหมายที่ระบุวันที่ได้ชัดเจน

    if month is None:
        # ไม่มีชื่อเดือนที่จับได้เลย — ต่อให้มีตัวเลข (เช่น "SUMMER 2021" มี 2021)
        # ก็ไม่ถือว่า "รู้เดือน แต่ขาดวัน/ปี" ตามนิยามของ INCOMPLETE (ADR-0009 D13
        # อธิบายเคส incomplete ด้วยคำว่า "ขาดปี/ขาดวัน" ซึ่งสื่อว่าเดือนต้องรู้อยู่แล้ว)
        return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)

    if not numbers:
        # มีแค่ชื่อเดือน ไม่มีวัน ไม่มีปี (เช่น "MARCH", "JUNE")
        return ReleaseDateParseResult(ReleaseDateParseStatus.INCOMPLETE, None)

    if len(numbers) == 1:
        value, digits = numbers[0]
        if digits == 4:
            # ตัวเลข 4 หลัก = ปี, ขาดวัน (เช่น "MARCH 2022", "February 2005")
            return ReleaseDateParseResult(ReleaseDateParseStatus.INCOMPLETE, None)
        if 1 <= value <= 31:
            # ตัวเลข 1-2 หลักที่เป็นวันได้ = วัน, ขาดปี (เช่น "March 18", "MAY 1")
            return ReleaseDateParseResult(ReleaseDateParseStatus.INCOMPLETE, None)
        return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)

    if len(numbers) == 2:
        day: int | None = None
        # (value, digits) ของตัวที่ตัดสินว่าเป็นปี — เก็บ digits ไว้ด้วยเพื่อส่งต่อให้
        # `_expand_year_component` ตัดสินว่าต้องขยาย pivot ปีสองหลักหรือไม่ (บั๊กเดิม:
        # โค้ดนี้เคย apply แค่กฎ พ.ศ. 2400-2600 แล้วปล่อยปีสองหลักผ่านดิบๆ ทำให้
        # "15 กุมภาพันธ์ 62" กลาย เป็น 0062-02-15 แทนที่จะขยายเป็น ค.ศ. เต็มเหมือน
        # เส้นทางตัวเลข)
        year_component: tuple[int, int] | None = None
        for value, digits in numbers:
            if digits == 4 or value > 31:
                if year_component is not None:
                    return ReleaseDateParseResult(
                        ReleaseDateParseStatus.UNREADABLE, None
                    )
                year_component = (value, digits)
            else:
                if day is not None:
                    return ReleaseDateParseResult(
                        ReleaseDateParseStatus.UNREADABLE, None
                    )
                day = value
        if day is None or year_component is None:
            return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)
        year = _expand_year_component(*year_component)
        return _build(year, month, day)

    # มากกว่า 2 ตัวเลขปนกับชื่อเดือน — ไม่อยู่ในรูปแบบที่รู้จัก
    return ReleaseDateParseResult(ReleaseDateParseStatus.UNREADABLE, None)


def parse_release_date_text(text: str | None) -> ReleaseDateParseResult:
    """แปลงข้อความวันฉายที่อ่านจากใบ (`release_date_text`) เป็น `date | None` พร้อม
    สถานะที่บอกว่า parse ไปถึงไหน — **writer เดียวของ `Poster.release_date`**
    (ADR-0009 D13 ข้อ 2) ห้ามมีจุดอื่นเขียน `release_date` โดยไม่ผ่านฟังก์ชันนี้

    Pure function: รับ `str | None` คืนผลจบในตัว ไม่พึ่งพา state ภายนอกใดๆ
    (ไม่มี `datetime.now()`, ไม่อ่าน DB, ไม่อ่าน `year`/`era_decade` ของแถวเดียวกัน)
    """
    if text is None:
        return ReleaseDateParseResult(ReleaseDateParseStatus.NO_INPUT, None)

    stripped = text.strip()
    if not stripped:
        return ReleaseDateParseResult(ReleaseDateParseStatus.NO_INPUT, None)

    numeric_match = _NUMERIC_DATE.match(stripped)
    if numeric_match:
        return _parse_numeric(numeric_match)

    numeric_month_day_match = _NUMERIC_MONTH_DAY.match(stripped)
    if numeric_month_day_match:
        return _parse_numeric_month_day(numeric_month_day_match)

    return _parse_named(stripped)
