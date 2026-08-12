"""Unit tests ของ `scripts/seed/split_entry.py` — เส้นที่ 6 (ADR-0024 · INF-22)

🔴 **AC-3 ของ INF-22 บังคับสามชั้นเพื่อพิสูจน์ว่าแถวพ่อไม่ถูกแตะเลย — ทั้งสามชั้นอยู่ที่นี่**

| ชั้น | ตรวจอะไร | เทสในไฟล์นี้ |
|---|---|---|
| 1. ระดับซอร์ส (AST) | ไม่มี `ast.Attribute` ชื่อ `is_unique` เลย · ไม่มี `ast.Call` ชื่อ `update` เลย | §ชั้น 1 |
| 2. ระดับ runtime | session ปลอมพิสูจน์ว่า `run()` ไม่เคย `execute()` statement ชนิด `Update` และแถวลูกที่ `add()` เข้าไปมีแค่ 4 attribute ที่ตั้งใจ (`id`/`title`/`price`/`condition_grade`) | §ชั้น 2 |
| 3. อ่านค่าพ่อกลับมาเทียบ | สร้างพ่อจริงใน `db_session`, รัน `run()` เต็ม (`--commit` จำลอง), query กลับมาว่า `price`/`status`/`published_at`/`needs_review`/`condition_grade` ไม่ขยับ | §ชั้น 3 |

ส่วนที่เหลือ (parse/plan) เป็นฟังก์ชัน pure ทั้งหมด ไม่ต้องมี DB — ตาม
ship-backend-change §3
"""

from __future__ import annotations

import argparse
import ast
import csv
import inspect
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster
from app.models.poster_split import PosterSplit
from scripts.seed import split_entry as mod
from scripts.seed.correction_entry import DEFAULT_CORRECTION_CSV
from scripts.seed.manual_entry import DEFAULT_MANUAL_CSV
from scripts.seed.reference_entry import DEFAULT_REFERENCE_CSV
from scripts.seed.split_entry import (
    SPLIT_SHEET_COLUMNS,
    ParentState,
    PlannedSplit,
    PrecheckError,
    RowAction,
    SplitPayload,
    SplitRow,
    assert_own_sheet,
    assert_schema_ready,
    field_specs,
    parse_rows,
    plan_writes,
)

PARENT = uuid.UUID("11111111-1111-1111-1111-111111111111")
PARENT2 = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _raw(**over: str) -> dict[str, str]:
    row = {
        "parent_poster_uuid": str(PARENT),
        "parent_title": "The Matrix",
        "parent_image_url": "https://example.invalid/a.jpg",
        "condition_grade": "very_good",
        "price": "500",
        "reason": "แยกใบที่สองออกมาเพราะต่างเกรดกัน",
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------
# field_specs — condition_grade / price
# --------------------------------------------------------------------------


def test_condition_grade_rejects_wrong_case() -> None:
    with pytest.raises(ValueError, match="ตัวพิมพ์ไม่ตรง"):
        field_specs()["condition_grade"].parse("Very_Good")


def test_condition_grade_accepts_exact_lowercase() -> None:
    assert field_specs()["condition_grade"].parse("mint") is PosterCondition.mint


def test_price_rejects_negative() -> None:
    with pytest.raises(ValueError, match="ติดลบ"):
        field_specs()["price"].parse("-1")


def test_price_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="ไม่ใช่ตัวเลข"):
        field_specs()["price"].parse("abc")


def test_price_rejects_more_than_two_decimals() -> None:
    with pytest.raises(ValueError, match="ทศนิยมเกิน"):
        field_specs()["price"].parse("500.123")


def test_price_accepts_two_decimals() -> None:
    assert field_specs()["price"].parse("500.50") == Decimal("500.50")


def test_price_rejects_over_the_column_ceiling() -> None:
    with pytest.raises(ValueError, match="เกินเพดาน"):
        field_specs()["price"].parse("99999999999")


# --------------------------------------------------------------------------
# parse_rows — pure, fail-closed ทั้งไฟล์
# --------------------------------------------------------------------------


def test_a_fully_filled_row_parses_into_a_payload() -> None:
    (row,) = parse_rows([_raw()])
    assert row.parent_poster_uuid == PARENT
    assert row.payload == SplitPayload(
        condition_grade=PosterCondition.very_good,
        price=Decimal("500"),
        reason="แยกใบที่สองออกมาเพราะต่างเกรดกัน",
    )


def test_a_fully_blank_row_is_normal_not_an_error() -> None:
    """ยังไม่ได้กรอก — สถานะปกติของใบงานที่ทำไปครึ่งเดียว"""
    (row,) = parse_rows([_raw(condition_grade="", price="", reason="")])
    assert row.payload is None


@pytest.mark.parametrize(
    "over",
    [
        {"condition_grade": "", "price": "500", "reason": "why"},
        {"condition_grade": "mint", "price": "", "reason": "why"},
        {"condition_grade": "mint", "price": "500", "reason": ""},
        {"condition_grade": "mint", "price": "", "reason": ""},
    ],
    ids=["missing_grade", "missing_price", "missing_reason", "missing_two"],
)
def test_partially_filled_rows_reject_the_whole_file(over: dict[str, str]) -> None:
    """🔴 เส้นนี้ไม่มีแนวคิด 'เติมทีหลัง' — ต่างจากเส้นที่ 3 ตรง ๆ"""
    with pytest.raises(PrecheckError, match="กรอกมาไม่ครบ"):
        parse_rows([_raw(**over)])


def test_bad_uuid_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="ไม่ใช่ UUID"):
        parse_rows([_raw(parent_poster_uuid="not-a-uuid")])


def test_duplicate_parent_uuid_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="ซ้ำกับแถวก่อนหน้า"):
        parse_rows([_raw(), _raw(reason="อีกเหตุผลหนึ่ง")])


def test_bad_grade_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="condition_grade"):
        parse_rows([_raw(condition_grade="not-a-grade")])


def test_bad_price_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="price"):
        parse_rows([_raw(price="not-a-number")])


def test_one_good_row_does_not_save_a_bad_row_next_to_it() -> None:
    """fail-closed แปลว่าทั้งไฟล์ — ไม่ใช่แค่แถวที่ผิด"""
    with pytest.raises(PrecheckError):
        parse_rows(
            [
                _raw(parent_poster_uuid=str(PARENT)),
                _raw(parent_poster_uuid=str(PARENT2), price="not-a-number"),
            ]
        )


# --------------------------------------------------------------------------
# plan_writes — pure, รับสถานะพ่อเข้ามา
# --------------------------------------------------------------------------


def _row(**over: object) -> SplitRow:
    base: dict[str, object] = {
        "lineno": 2,
        "parent_poster_uuid": PARENT,
        "payload": SplitPayload(
            condition_grade=PosterCondition.very_good,
            price=Decimal("500"),
            reason="เหตุผล",
        ),
    }
    base.update(over)
    return SplitRow(**base)  # type: ignore[arg-type]


def test_blank_row_is_skipped_before_touching_parents() -> None:
    (plan,) = plan_writes([_row(payload=None)], {})
    assert plan.action is RowAction.SKIP_BLANK


def test_parent_not_in_db_is_skipped_not_an_error() -> None:
    (plan,) = plan_writes([_row()], {})
    assert plan.action is RowAction.SKIP_NOT_FOUND


def test_parent_already_unique_is_skipped() -> None:
    """มีคนแก้ผ่านเส้นที่ 5 ไปแล้วระหว่างที่ใบงานนี้ยังค้างอยู่"""
    parents = {PARENT: ParentState(title="The Matrix", is_unique=True)}
    (plan,) = plan_writes([_row()], parents)
    assert plan.action is RowAction.SKIP_NOT_ELIGIBLE
    assert plan.parent_title == "The Matrix"


def test_eligible_parent_produces_a_write_plan() -> None:
    parents = {PARENT: ParentState(title="The Matrix", is_unique=False)}
    (plan,) = plan_writes([_row()], parents)
    assert plan.action is RowAction.WRITE
    assert plan.parent_title == "The Matrix"


def test_planned_split_carries_the_original_row() -> None:
    parents = {PARENT: ParentState(title="The Matrix", is_unique=False)}
    (plan,) = plan_writes([_row()], parents)
    assert isinstance(plan, PlannedSplit)
    assert plan.row.parent_poster_uuid == PARENT


# --------------------------------------------------------------------------
# assert_own_sheet / assert_schema_ready
# --------------------------------------------------------------------------


def test_the_sheets_of_other_lanes_are_refused_by_name() -> None:
    for path, lane in (
        (DEFAULT_MANUAL_CSV, "เส้นที่ 3"),
        (DEFAULT_REFERENCE_CSV, "เส้นที่ 4"),
        (DEFAULT_CORRECTION_CSV, "เส้นที่ 5"),
    ):
        with pytest.raises(PrecheckError, match=lane):
            assert_own_sheet(path)


def test_our_own_sheet_passes_wherever_it_lives() -> None:
    assert_own_sheet(mod.DEFAULT_SPLIT_CSV) is None
    assert_own_sheet(mod.SEED_DIR / "some-other-name.csv") is None


def test_schema_ready_passes_when_the_table_exists() -> None:
    assert assert_schema_ready(True) is None


def test_schema_ready_refuses_when_the_table_is_missing() -> None:
    with pytest.raises(PrecheckError, match="poster_splits"):
        assert_schema_ready(False)


# --------------------------------------------------------------------------
# §ชั้น 1 — ระดับซอร์ส (AST)
# --------------------------------------------------------------------------


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(mod))


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def test_source_never_writes_is_unique_anywhere() -> None:
    """D3 — เส้นนี้ไม่เขียน `is_unique` ของใครเลย ทั้งพ่อและลูก

    🔴 ตรวจเฉพาะ `ast.Store` (เช่น `poster.is_unique = ...`) — `ParentState.is_unique`
    (field ของตัวเอง) และ `state.is_unique` (อ่านค่าเพื่อตัดสิน SKIP_NOT_ELIGIBLE)
    เป็นการ**อ่าน**ที่ตั้งใจและถูกต้องตาม D3 ไม่ใช่การเขียน — กวาดทั้งไฟล์ ไม่ใช่แค่
    ใน `run()` เพราะผิดที่ไหนในไฟล์นี้ก็ผิดหลักเดียวกัน
    """
    tree = _tree()
    written = {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
    }
    # keyword ของ `Poster(...)` โดยเฉพาะ — คนละเรื่องกับ `ParentState(..., is_unique=...)`
    # ซึ่งเป็นการสร้าง dataclass ภายในของไฟล์นี้เอง ไม่ใช่การเขียนลง `posters`
    poster_kwargs = {
        kw.arg
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _callee_name(n) == "Poster"
        for kw in n.keywords
        if kw.arg is not None
    }
    assert "is_unique" not in written
    assert "is_unique" not in poster_kwargs


def test_source_has_no_update_call_at_all() -> None:
    """ไม่มีคำสั่ง UPDATE บน `posters` เลยแม้แต่บรรทัดเดียว — เส้นนี้ INSERT อย่างเดียว"""
    calls = [
        ast.unparse(n)
        for n in ast.walk(_tree())
        if isinstance(n, ast.Call) and _callee_name(n) == "update"
    ]
    assert calls == []


def test_the_only_poster_attributes_ever_assigned_are_the_intended_four() -> None:
    """closed-world — ถ้าวันหลังมีใครเพิ่ม `poster.status = ...` เข้าไปในไฟล์นี้
    เทสนี้ต้องแดงทันที ไม่ต้องรอ mutation test มาจับ
    """
    tree = ast.parse(inspect.getsource(mod.run))
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            assigned.add(node.attr)
    # เฉพาะ attribute ที่ตั้งค่าจริงผ่าน `.attr = ` (ไม่ใช่ Poster(...) kwargs ซึ่งเป็น
    # ast.keyword ไม่ใช่ ast.Attribute) — ใน run() วันนี้ไม่มีการ setattr เลยสักบรรทัด
    # เพราะ Poster ใหม่ถูกสร้างผ่าน constructor kwargs ทั้งหมด (ดูเทส kwargs ด้านล่าง)
    assert assigned == set()


def test_the_child_poster_constructor_only_ever_receives_the_intended_four_kwargs() -> (
    None
):
    """D3/D4 — `Poster(...)` ใน `run()` ต้องมีแค่ `id`/`title`/`price`/`condition_grade`"""
    tree = ast.parse(inspect.getsource(mod.run))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _callee_name(n) == "Poster"
    ]
    assert len(calls) == 1
    kwargs = {kw.arg for kw in calls[0].keywords}
    assert kwargs == {"id", "title", "price", "condition_grade"}


# --------------------------------------------------------------------------
# §ชั้น 2 — ระดับ runtime ด้วย session ปลอม (ไม่ต้องมี DB จริง)
# --------------------------------------------------------------------------


def _write_sheet(path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SPLIT_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


class _FakeResult:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class _FakeSession:
    """session ปลอม — ไม่มี DB จริง ใช้พิสูจน์ *สิ่งที่ถูกเรียก* ระหว่าง `run()`

    ทรงเดียวกับ `_FakeSession`/`_PosterSpy` ของ `test_correction_entry.py` แต่เล็กกว่า
    เพราะเส้นนี้ไม่มีโหมด overwrite ให้ต้องจำลอง
    """

    def __init__(self, parent_rows: list[tuple]) -> None:
        self._parent_rows = parent_rows
        self.added: list[object] = []
        self.executed: list[object] = []
        self.committed = False
        self.rolled_back = False

    async def scalar(self, stmt: object, params: object = None) -> int:
        return 1  # _check_schema — ตารางมีอยู่เสมอในเทสชุดนี้

    async def execute(self, stmt: object) -> _FakeResult:
        self.executed.append(stmt)
        return _FakeResult(self._parent_rows)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _SessionCtx:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


async def test_run_never_executes_an_update_and_only_sets_the_intended_child_fields(
    monkeypatch, tmp_path
) -> None:
    """🔴 ตัวฆ่า mutation หลักของ AC-3 — ถ้ามีใครแอบเพิ่ม `session.execute(update(...))`
    หรือ `poster.is_unique = True` เข้าไปใน `run()` เทสนี้ต้องแดง
    """
    parent_rows = [(PARENT, "The Matrix", False)]
    fake_session = _FakeSession(parent_rows)

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(fake_session)
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(PARENT))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "fake-target")

    assert result == 0
    assert fake_session.committed is True
    # §ชั้น 2 ข้อ 1 — ไม่มี statement ชนิด Update เลยสักตัว
    assert not any(isinstance(e, Update) for e in fake_session.executed)

    added_posters = [o for o in fake_session.added if isinstance(o, Poster)]
    added_splits = [o for o in fake_session.added if isinstance(o, PosterSplit)]
    assert len(added_posters) == 1
    assert len(added_splits) == 1

    child = added_posters[0]
    # §ชั้น 2 ข้อ 2 — แถวลูกไม่ใช่แถวพ่อ (id ต่างกัน) และไม่มี attribute อื่นถูก set
    # นอกเหนือจากสี่ตัวที่ตั้งใจ (closed-world บน __dict__ ของ instance จริง)
    assert child.id != PARENT
    set_attrs = {k for k in vars(child) if not k.startswith("_sa_")}
    assert set_attrs == {"id", "title", "price", "condition_grade"}
    assert child.title == "The Matrix"
    assert child.price == Decimal("500")
    assert child.condition_grade is PosterCondition.very_good

    split = added_splits[0]
    assert split.parent_poster_id == PARENT
    assert split.child_poster_id == child.id
    assert split.reason == "แยกใบที่สองออกมาเพราะต่างเกรดกัน"


async def test_run_does_not_write_anything_when_no_row_is_eligible(
    monkeypatch, tmp_path
) -> None:
    """ด้านที่ต้องไม่พัง — ถ้าพ่อ `is_unique=true` แล้ว (แก้ผ่านเส้นที่ 5 ไปแล้ว)
    ต้องไม่มีอะไรถูกสร้างเลย ไม่ใช่แค่ "ไม่มี Update" (ซึ่งเป็นจริงเสมออยู่แล้ว)
    """
    parent_rows = [(PARENT, "The Matrix", True)]  # is_unique=True แล้ว
    fake_session = _FakeSession(parent_rows)

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(fake_session)
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(PARENT))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "fake-target")

    assert result == 0
    assert fake_session.added == []
    # ยัง commit อยู่ (ไม่มีอะไรผิดพลาด แค่ไม่มีอะไรให้เขียน) — เทียบ session.added
    # ว่างเปล่าคือหลักฐานจริง ไม่ใช่ exit code


# --------------------------------------------------------------------------
# §ชั้น 3 — อ่านค่าพ่อกลับมาเทียบ (DB จริงผ่าน db_session fixture)
# --------------------------------------------------------------------------


async def test_the_parent_row_is_byte_for_byte_unchanged_after_a_real_commit(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """🔴 นี่คือเทสที่สำคัญที่สุดของทั้งไฟล์ — พิสูจน์ด้วย DB จริง ไม่ใช่ mock

    สร้างพ่อที่มีค่า **ไม่ใช่ default ของคอลัมน์สักตัว** (status/published_at/
    needs_review ทุกตัวตั้งใจให้ต่างจาก server_default) เพื่อให้เทสนี้ไวต่อการเปลี่ยน
    จริง — ถ้าโค้ดเผลอ reset อะไรกลับไปหาค่า default โดยบังเอิญ เทสจะยังจับได้
    """
    parent = Poster(
        title="The Matrix (ADVANCE 4K)",
        price=Decimal("999.00"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
        status=PosterStatus.reserved,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        needs_review=False,
    )
    db_session.add(parent)
    await db_session.flush()
    parent_id = parent.id

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(
        sheet,
        [
            _raw(
                parent_poster_uuid=str(parent_id),
                condition_grade="near_mint",
                price="1200",
                reason="ใบที่สองสภาพต่างจากใบแรกชัดเจน",
            )
        ],
    )

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "test-db")
    assert result == 0

    # query กลับมาแบบ Core select (ไม่ผ่าน ORM identity map ของ `parent`) — พิสูจน์ที่
    # ระดับแถวจริงใน DB ไม่ใช่แค่ว่า python object เดิมไม่ถูกแตะ
    row = (
        await db_session.execute(
            select(
                Poster.price,
                Poster.status,
                Poster.published_at,
                Poster.needs_review,
                Poster.condition_grade,
                Poster.is_unique,
            ).where(Poster.id == parent_id)
        )
    ).one()

    assert row.price == Decimal("999.00")
    assert row.status is PosterStatus.reserved
    assert row.published_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert row.needs_review is False
    assert row.condition_grade is PosterCondition.very_fine
    # is_unique ของพ่อยังเป็น false — เส้นนี้ไม่แก้มัน (D3: ต้องผ่านเส้นที่ 5 ต่างหาก)
    assert row.is_unique is False

    # ด้านบวก — แถวลูกต้องถูกสร้างจริงพร้อมค่าที่กรอก และ is_unique มาจาก
    # server_default (ไม่ใช่ทั้งไฟล์นี้ปฏิเสธเงียบ ๆ จนไม่มีอะไรเกิดขึ้นเลย)
    split_row = (
        await db_session.execute(
            select(PosterSplit).where(PosterSplit.parent_poster_id == parent_id)
        )
    ).scalar_one()
    child = (
        await db_session.execute(
            select(Poster).where(Poster.id == split_row.child_poster_id)
        )
    ).scalar_one()
    assert child.title == "The Matrix (ADVANCE 4K)"
    assert child.price == Decimal("1200.00")
    assert child.condition_grade is PosterCondition.near_mint
    assert child.is_unique is True
    assert child.status is PosterStatus.available
    assert child.needs_review is True
    assert child.published_at is None
