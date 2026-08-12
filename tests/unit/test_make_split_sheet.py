"""Unit tests ของ `scripts/seed/make_split_sheet.py` — INF-22 (ADR-0024)

จุดสำคัญที่สุดที่ต้องล็อก (เหมือน `make_correction_sheet.py`): สคริปต์นี้ **ห้ามกรอก
ช่องของคนให้** — เครื่องที่เสนอเกรด/ราคาให้คนเซ็นคือเครื่องที่ตัดสินสภาพและราคาสินค้า
แทนคน (ADR-0009 D6) และตัวกรองปริยาย (`is_unique=false` + published) ต้องตรงกับ
ความหมายของ ADR-0019 D1/D2 — ไม่ใช่ "มีเกรดอยู่แล้ว" แบบเส้นที่ 5
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, datetime

from scripts.seed import make_split_sheet as mod
from scripts.seed.make_split_sheet import HUMAN_COLUMNS, build_sheet_rows
from scripts.seed.split_entry import SPLIT_SHEET_COLUMNS

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PID2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
PUBLISHED = datetime(2026, 1, 1, tzinfo=UTC)


def _db_row(**over: object) -> dict:
    row: dict = {
        "id": PID,
        "title": "The Matrix",
        "is_unique": False,
        "published_at": PUBLISHED,
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------
# เครื่องห้ามกรอกช่องของคน
# --------------------------------------------------------------------------


def test_the_three_human_columns_are_always_left_empty() -> None:
    """🔴 กฎที่สำคัญที่สุดของสคริปต์นี้"""
    rows = build_sheet_rows(
        [_db_row(), _db_row(id=PID2, title="Another")], {}, include_all=True
    )
    assert len(rows) == 2
    for row in rows:
        for column in HUMAN_COLUMNS:
            assert row[column] == "", column


def test_generator_never_writes_into_the_human_columns() -> None:
    """ล็อกที่ระดับซอร์ส — ถ้ามีใครเพิ่ม flag ให้เดาเกรด/ราคาที่ "น่าจะถูก"
    ต้องแดงทันที (closed-world บน `seen`)
    """
    tree = ast.parse(inspect.getsource(mod.build_sheet_rows))
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value in HUMAN_COLUMNS:
                assert isinstance(
                    value, ast.Constant
                ), f"{key.value} ถูกเติมด้วยนิพจน์ ไม่ใช่ค่าว่างคงที่"
                assert value.value == "", f"{key.value} ถูกกรอกค่าให้: {value.value!r}"
                seen.add(key.value)
    assert seen == set(HUMAN_COLUMNS)


def test_the_human_columns_match_split_entrys_own_definition() -> None:
    """ประกอบจากค่าคงที่ของ split_entry.py ไม่ใช่รายชื่อที่พิมพ์ไว้ — ฟิลด์ที่เพิ่มเข้า
    วันหน้าจะถูกล็อกทันทีโดยไม่ต้องมีใครนึกได้ว่าต้องมาต่อรายชื่อ"""
    from scripts.seed.split_entry import HUMAN_COLUMNS as SPLIT_ENTRY_HUMAN_COLUMNS

    assert set(HUMAN_COLUMNS) == set(SPLIT_ENTRY_HUMAN_COLUMNS)


def test_generator_never_reaches_for_the_current_time() -> None:
    source = ast.unparse(ast.parse(inspect.getsource(mod)))
    for forbidden in ("now(", "today(", "utcnow("):
        assert forbidden not in source, f"พบ {forbidden} ในซอร์ส"


def test_sheet_uses_the_column_list_shared_with_the_applier() -> None:
    (row,) = build_sheet_rows([_db_row()], {}, include_all=True)
    assert tuple(row) == SPLIT_SHEET_COLUMNS


# --------------------------------------------------------------------------
# image_url
# --------------------------------------------------------------------------


def test_image_url_comes_from_the_public_url_map_only() -> None:
    """ADR-0006 D5 — key ที่ไม่ public ถูกกรองทิ้งก่อนถึง build_media_url() (ที่ชั้น
    `load_from_db()` ไม่ใช่ในนี้) — ที่นี่ตรวจแค่ว่า build_sheet_rows() ใช้ map ที่ส่งมา
    """
    rows = build_sheet_rows(
        [_db_row(), _db_row(id=PID2, title="Another")],
        {PID: "https://cdn.invalid/a.jpg"},
        include_all=True,
    )
    by_id = {r["parent_poster_uuid"]: r for r in rows}
    assert by_id[str(PID)]["parent_image_url"] == "https://cdn.invalid/a.jpg"
    assert by_id[str(PID2)]["parent_image_url"] == ""


# --------------------------------------------------------------------------
# ใบไหนเข้าใบงาน — is_unique=false + published (ต่างจากเส้นที่ 5)
# --------------------------------------------------------------------------


def test_default_filter_is_is_unique_false_and_published() -> None:
    rows = build_sheet_rows([_db_row()], {}, include_all=False)
    assert len(rows) == 1


def test_a_unique_row_is_excluded_by_default() -> None:
    row = _db_row(is_unique=True)
    assert build_sheet_rows([row], {}, include_all=False) == []
    assert len(build_sheet_rows([row], {}, include_all=True)) == 1


def test_an_unpublished_row_is_excluded_by_default() -> None:
    row = _db_row(published_at=None)
    assert build_sheet_rows([row], {}, include_all=False) == []
    assert len(build_sheet_rows([row], {}, include_all=True)) == 1


def test_all_flag_includes_everything_regardless_of_filter() -> None:
    rows = [
        _db_row(id=PID, is_unique=True, published_at=None),
        _db_row(id=PID2, is_unique=False, published_at=PUBLISHED),
    ]
    assert len(build_sheet_rows(rows, {}, include_all=False)) == 1
    assert len(build_sheet_rows(rows, {}, include_all=True)) == 2


def test_rows_sort_by_title() -> None:
    rows = build_sheet_rows(
        [
            _db_row(id=PID, title="ZZZ"),
            _db_row(id=PID2, title="AAA"),
        ],
        {},
        include_all=True,
    )
    assert [r["parent_title"] for r in rows] == ["AAA", "ZZZ"]
