"""`scripts/ops/catalog_bootstrap.py` — ADR-0015 Amendment 4 (INF-48) A4-D7

ใช้ `TEST_DATABASE_URL` ของ `tests/conftest.py` ด้วย **engine/connection ของตัวเอง**
(ไม่ใช่ fixture `db_session`) เพราะ `db_session` ครอบด้วย savepoint ที่ rollback ทุกอย่าง
อัตโนมัติ — สคริปต์นี้ต้องคุมทรานแซกชันเอง (`run_bootstrap()` รับ connection ที่เปิด
ทรานแซกชันไว้แล้วจากผู้เรียก) ทุกเทสจึงเปิด `asyncpg` connection ของตัวเอง เริ่มด้วยการ
`DELETE FROM posters` (cascade ไป poster_images/poster_attribute_reviews) ภายใน
ทรานแซกชันที่ **ไม่เคย commit จริง** เพื่อเริ่มจาก state สะอาดโดยไม่กระทบข้อมูลที่เทส
ไฟล์อื่น commit ทิ้งไว้จริง (ทรง "ป้าย"/cleanup ของ `real_client` — ดู docstring ของมัน)

fixture dump ทั้งหมดใน**ไฟล์นี้เป็นข้อมูลสังเคราะห์** (uuid4 สุ่ม + ชื่อ `TEST_INF48_*`)
**ห้ามใช้ข้อมูลจริงจาก SIT/production** — ตัวเลข/id ของ ADR-0015 A4-D2 ถูกทดสอบแยก
ในข้อ (8) เท่านั้น (`test_production_spec_matches_adr_numbers_and_ids`)
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from scripts.ops import catalog_bootstrap as boot
from scripts.seed import manual_entry
from tests.conftest import TEST_DATABASE_URL

BACKEND_ROOT = Path(__file__).resolve().parents[2]
HOUSE_SELLER_ID = "00000000-0000-4000-8000-000000000002"
_BASE_DT = datetime(2026, 8, 1, tzinfo=timezone.utc)


# ════════════════════════════════════════════════════════════════════════
# helpers — dump สังเคราะห์ + connection คุมทรานแซกชันเอง
# ════════════════════════════════════════════════════════════════════════


def _asyncpg_dsn() -> str:
    return (
        make_url(TEST_DATABASE_URL)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'"
    text = str(value).replace("'", "''")
    return f"'{text}'"


_POSTER_COLUMNS = (
    "id",
    "title",
    "tmdb_id",
    "price",
    "status",
    "is_unique",
    "condition_grade",
    "size",
    "era_decade",
    "studio",
    "description",
    "is_authenticated",
    "authenticity_note",
    "provenance",
    "created_at",
    "updated_at",
    "poster_type",
    "release_region",
    "release_date",
    "copyright_year",
    "size_format",
    "year",
    "restoration_status",
    "restoration_note",
    "needs_review",
    "release_date_text",
    "published_at",
    "verification_status",
    "reference_note",
    "reference_url",
    "width_in",
    "height_in",
    "sold_at",
    "verified_at",
    "seller_id",
    "tier",
    "shipping_fee",
    "approved_at",
    "approved_by",
    "rejection_reason",
)
_IMAGE_COLUMNS = (
    "id",
    "poster_id",
    "is_primary",
    "sort_order",
    "created_at",
    "storage_key",
    "width_px",
    "height_px",
    "kind",
)
_REVIEW_COLUMNS = (
    "id",
    "poster_id",
    "field",
    "value_before",
    "value_after",
    "reviewed_by",
    "reviewed_at",
    "source",
    "created_at",
    "reason",
)


def _insert_line(table: str, columns: tuple[str, ...], row: dict) -> str:
    values = ", ".join(_sql_literal(row[c]) for c in columns)
    return f"INSERT INTO public.{table} ({', '.join(columns)}) VALUES ({values});"


def poster_row(poster_id: str, **overrides: object) -> dict:
    row: dict = dict.fromkeys(_POSTER_COLUMNS)
    row.update(
        id=poster_id,
        title="TEST_INF48 POSTER",
        price=Decimal("100.00"),
        status="available",
        is_unique=True,
        is_authenticated=False,
        created_at=_BASE_DT,
        updated_at=_BASE_DT,
        needs_review=True,
        seller_id=HOUSE_SELLER_ID,
        shipping_fee=Decimal("0.00"),
        approved_at=_BASE_DT,
    )
    row.update(overrides)
    return row


def image_row(image_id: str, poster_id: str, **overrides: object) -> dict:
    row: dict = dict.fromkeys(_IMAGE_COLUMNS)
    row.update(
        id=image_id,
        poster_id=poster_id,
        is_primary=False,
        sort_order=1,
        created_at=_BASE_DT,
        storage_key=f"posters/public/{poster_id}/{image_id}.jpg",
        kind="FRONT",
    )
    row.update(overrides)
    return row


def review_row(
    review_id: str,
    poster_id: str,
    *,
    field: str,
    source: str,
    reviewed_at: datetime = _BASE_DT,
    value_before: str | None = None,
    value_after: str | None = None,
    reason: str | None = None,
) -> dict:
    row: dict = dict.fromkeys(_REVIEW_COLUMNS)
    row.update(
        id=review_id,
        poster_id=poster_id,
        field=field,
        value_before=value_before,
        value_after=value_after,
        reviewed_by="tester",
        reviewed_at=reviewed_at,
        source=source,
        created_at=reviewed_at,
        reason=reason,
    )
    return row


def build_dump(posters: list[dict], images: list[dict], reviews: list[dict]) -> str:
    lines = [_insert_line("posters", _POSTER_COLUMNS, r) for r in posters]
    lines += [_insert_line("poster_images", _IMAGE_COLUMNS, r) for r in images]
    lines += [
        _insert_line("poster_attribute_reviews", _REVIEW_COLUMNS, r) for r in reviews
    ]
    return "\n".join(lines) + "\n"


async def _connect_clean() -> (
    tuple[asyncpg.Connection, "asyncpg.transaction.Transaction"]
):
    """เปิด connection ของตัวเอง + เริ่มทรานแซกชัน + เคลียร์ให้ว่าง **ภายในทรานแซกชัน
    เดียวกันที่ยังไม่ commit** — ไม่กระทบข้อมูลจริงที่เทสไฟล์อื่น commit ทิ้งไว้เลย
    เพราะ caller ต้อง `tx.rollback()` เสมอก่อน `conn.close()`
    """
    conn = await asyncpg.connect(_asyncpg_dsn())
    tx = conn.transaction()
    await tx.start()
    await conn.execute("DELETE FROM public.posters")
    await conn.execute("DELETE FROM public.poster_splits")
    return conn, tx


async def _assert_all_empty(conn: asyncpg.Connection) -> None:
    for table in (
        "posters",
        "poster_images",
        "poster_attribute_reviews",
        "poster_splits",
    ):
        count = await conn.fetchval(f"SELECT count(*) FROM public.{table}")
        assert count == 0, f"{table} ควรว่างหลัง rollback แต่มี {count} แถว"


async def _run_and_expect_refusal_then_verify_empty(
    conn: asyncpg.Connection,
    tx: "asyncpg.transaction.Transaction",
    spec: boot.BootstrapSpec,
    insert_script: str,
    columns_by_table: dict,
    *,
    match: str,
) -> None:
    with pytest.raises(boot.BootstrapRefused, match=match):
        await boot.run_bootstrap(conn, spec, insert_script, columns_by_table)
    await tx.rollback()
    await _assert_all_empty(conn)


def make_spec(
    *,
    cleared_ids: tuple[str, ...],
    sold_id: str,
    p1_expected: int,
    p2_expected: int,
    p3_expected: int,
    expected_posters: int,
    expected_images: int,
    expected_reviews: int,
    p3_window_start: datetime = _BASE_DT - timedelta(minutes=1),
    p3_window_end: datetime = _BASE_DT + timedelta(minutes=1),
) -> boot.BootstrapSpec:
    """สร้าง `BootstrapSpec` สำหรับ fixture เล็ก ๆ ของเทส — ใช้ชื่อ source เดียวกับ
    `PRODUCTION_SPEC` (ของจริงตาม ADR) แต่ตัวเลข/id เปลี่ยนได้ต่อเทส
    🔴 `alembic_head` ต้องถูก override ด้วย `dataclasses.replace(...)` ให้ตรงกับ
    เวอร์ชันจริงของ `poster_nung_test` เสมอ (ดูใน caller) — ไม่ hardcode ค่า SIT ที่นี่
    """
    return boot.BootstrapSpec(
        alembic_head="__override_me__",
        cleared_poster_ids=cleared_ids,
        sold_poster_id=sold_id,
        p1_source_values=("poster_service.py", "order_service.py"),
        p1_expected=p1_expected,
        p2_source="correction-entry-sit-20260916.csv",
        p2_expected=p2_expected,
        p3_source="manual-entry.csv",
        p3_window_start=p3_window_start,
        p3_window_end=p3_window_end,
        p3_expected=p3_expected,
        p4_source="correction-entry-sit-20260830.csv",
        expected_after={
            "posters": expected_posters,
            "poster_images": expected_images,
            "poster_splits": 0,
            "poster_attribute_reviews": expected_reviews,
        },
    )


async def _current_alembic_head(conn: asyncpg.Connection) -> str:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


# ════════════════════════════════════════════════════════════════════════
# (1) precondition count≠0 ⇒ BootstrapRefused · ไม่มี INSERT ใดเกิด
# ════════════════════════════════════════════════════════════════════════


async def test_precondition_refuses_when_posters_not_empty_and_writes_nothing() -> None:
    conn, tx = await _connect_clean()
    try:
        existing_id = str(uuid.uuid4())
        await conn.execute(
            _insert_line("posters", _POSTER_COLUMNS, poster_row(existing_id))
        )
        head = await _current_alembic_head(conn)
        spec = dataclasses.replace(
            make_spec(
                cleared_ids=(),
                sold_id=str(uuid.uuid4()),
                p1_expected=0,
                p2_expected=0,
                p3_expected=0,
                expected_posters=1,
                expected_images=0,
                expected_reviews=0,
            ),
            alembic_head=head,
        )
        with pytest.raises(boot.BootstrapRefused, match="precondition"):
            await boot.run_bootstrap(conn, spec, "", {})
        # ยังอยู่ในทรานแซกชันเดิม (Python exception ไม่ทำให้ Postgres tx อยู่ในสถานะ
        # aborted) — ตรวจได้ทันทีว่ามีแค่แถวเดิม 1 แถว ไม่มี INSERT จาก dump เกิดขึ้นเลย
        count = await conn.fetchval("SELECT count(*) FROM public.posters")
        assert count == 1
    finally:
        await tx.rollback()
        await conn.close()


# ════════════════════════════════════════════════════════════════════════
# (2) assert-rollback — ยิง assert_no_test_stock_state · assert_no_signature_carried
#     แยกกันสองเทส (A4-D9 ข้อ 3)
# ════════════════════════════════════════════════════════════════════════


async def test_assert_no_signature_carried_fires_and_full_rollback() -> None:
    conn, tx = await _connect_clean()
    try:
        sold_id = str(uuid.uuid4())
        leaked_id = str(uuid.uuid4())
        posters = [
            poster_row(
                sold_id,
                status="sold",
                sold_at=_BASE_DT,
                published_at=_BASE_DT,
                condition_grade="very_fine",
                verified_at=None,
            ),
            # 🔴 ไม่ได้อยู่ใน cleared_ids ⇒ step ② ไม่แตะ ⇒ verified_at ที่ dump มา
            # ยังอยู่หลังโหลด — ต้องถูก assert_no_signature_carried จับ
            poster_row(
                leaked_id,
                status="available",
                verified_at=_BASE_DT,
                condition_grade="mint",
            ),
        ]
        images = [
            image_row(str(uuid.uuid4()), sold_id),
            image_row(str(uuid.uuid4()), leaked_id),
        ]
        dump_text = build_dump(posters, images, [])
        insert_script, columns = boot.validate_dump_allowlist(dump_text)
        head = await _current_alembic_head(conn)
        spec = dataclasses.replace(
            make_spec(
                cleared_ids=(),
                sold_id=sold_id,
                p1_expected=0,
                p2_expected=0,
                p3_expected=0,
                expected_posters=2,
                expected_images=2,
                expected_reviews=0,
            ),
            alembic_head=head,
        )
        await _run_and_expect_refusal_then_verify_empty(
            conn, tx, spec, insert_script, columns, match="assert_no_signature_carried"
        )
    finally:
        await conn.close()


async def test_assert_no_test_stock_state_fires_and_full_rollback() -> None:
    conn, tx = await _connect_clean()
    try:
        sold_id = str(uuid.uuid4())
        leaked_id = str(uuid.uuid4())
        posters = [
            poster_row(
                sold_id,
                status="sold",
                sold_at=_BASE_DT,
                published_at=_BASE_DT,
                condition_grade="very_fine",
                verified_at=None,
            ),
            # 🔴 ไม่ได้อยู่ใน cleared_ids ⇒ ยังเป็น 'reserved' หลังโหลด — ไม่ใช่
            # sold_poster_id ⇒ ต้องถูก assert_no_test_stock_state จับ
            poster_row(leaked_id, status="reserved", condition_grade="mint"),
        ]
        images = [
            image_row(str(uuid.uuid4()), sold_id),
            image_row(str(uuid.uuid4()), leaked_id),
        ]
        dump_text = build_dump(posters, images, [])
        insert_script, columns = boot.validate_dump_allowlist(dump_text)
        head = await _current_alembic_head(conn)
        spec = dataclasses.replace(
            make_spec(
                cleared_ids=(),
                sold_id=sold_id,
                p1_expected=0,
                p2_expected=0,
                p3_expected=0,
                expected_posters=2,
                expected_images=2,
                expected_reviews=0,
            ),
            alembic_head=head,
        )
        await _run_and_expect_refusal_then_verify_empty(
            conn, tx, spec, insert_script, columns, match="assert_no_test_stock_state"
        )
    finally:
        await conn.close()


# ════════════════════════════════════════════════════════════════════════
# (3) marker มีอยู่ ⇒ ปฏิเสธก่อนเปิด connection (monkeypatch open_connection ให้ระเบิด)
# ════════════════════════════════════════════════════════════════════════


async def test_marker_refuses_before_open_connection_is_ever_called(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("OPS_AUDIT_DIR", str(audit_dir))
    marker = audit_dir / boot.MARKER_FILENAME
    marker.write_text(
        '{"phase": "committed", "lane": "catalog-bootstrap"}\n', encoding="utf-8"
    )

    async def _boom() -> asyncpg.Connection:  # pragma: no cover — ต้องไม่ถูกเรียกเลย
        raise AssertionError("open_connection() ถูกเรียกทั้งที่ marker มีอยู่แล้ว")

    monkeypatch.setattr(boot, "open_connection", _boom)

    args = argparse.Namespace(
        actor="owner@example.test",
        dump=Path("/this/path/does/not/exist.sql"),
        audit_log=audit_dir / "catalog-bootstrap.jsonl",
        commit=False,
        dump_sha256=None,
        backup_ref=None,
    )
    with pytest.raises(boot.MarkerAlreadyExists):
        await boot._run_main(args)


# ════════════════════════════════════════════════════════════════════════
# (4) dump allowlist — statement นอกรายการ/ตารางอื่น → ปฏิเสธก่อน INSERT แรก
# ════════════════════════════════════════════════════════════════════════


def test_dump_allowlist_rejects_non_insert_statement() -> None:
    bad = "INSERT INTO public.posters (id) VALUES ('x');\nDROP TABLE posters;\n"
    with pytest.raises(boot.BootstrapRefused, match="ไม่ใช่บรรทัดว่าง"):
        boot.validate_dump_allowlist(bad)


def test_dump_allowlist_rejects_table_outside_the_three() -> None:
    bad = "INSERT INTO public.users (id) VALUES ('x');\n"
    with pytest.raises(boot.BootstrapRefused):
        boot.validate_dump_allowlist(bad)


def test_dump_allowlist_rejects_raw_pg_dump_preamble_lines() -> None:
    """pg_dump 16 ปล่อย `SET …`/`SELECT pg_catalog.set_config(...)`/`\\restrict`/
    `\\unrestrict` เสมอถ้า runbook ไม่กรองด้วย `grep -E '^INSERT INTO'` ก่อน — สแกน
    ชั้นที่สองในสคริปต์ต้องปฏิเสธเองด้วย ไม่พึ่งว่าชั้นแรกทำถูก (A4-D9 ข้อ 2)
    """
    raw = (
        "SET statement_timeout = 0;\n"
        "SELECT pg_catalog.set_config('search_path', '', false);\n"
        "INSERT INTO public.posters (id) VALUES ('x');\n"
    )
    with pytest.raises(boot.BootstrapRefused):
        boot.validate_dump_allowlist(raw)


def test_dump_allowlist_accepts_blank_lines_and_comments() -> None:
    ok = "-- comment\n\nINSERT INTO public.posters (id) VALUES ('x');\n"
    script, columns = boot.validate_dump_allowlist(ok)
    assert "posters" in columns
    assert script.strip() == "INSERT INTO public.posters (id) VALUES ('x');"


# ════════════════════════════════════════════════════════════════════════
# (5) column-set ≠ ตารางจริง → ปฏิเสธ
# ════════════════════════════════════════════════════════════════════════


async def test_column_set_mismatch_against_real_table_is_refused() -> None:
    conn, tx = await _connect_clean()
    try:
        missing_title = tuple(c for c in _POSTER_COLUMNS if c != "title")
        with pytest.raises(boot.BootstrapRefused, match="column set"):
            await boot._assert_columns_match_table(conn, "posters", missing_title)
    finally:
        await tx.rollback()
        await conn.close()


# ════════════════════════════════════════════════════════════════════════
# (6) unwind cast ครบชนิด (enum · numeric · smallint · boolean · text) + LIFO
# ════════════════════════════════════════════════════════════════════════


async def test_unwind_casts_every_type_and_applies_lifo_order() -> None:
    conn, tx = await _connect_clean()
    try:
        target_id = str(uuid.uuid4())
        sold_id = str(uuid.uuid4())
        posters = [
            poster_row(
                target_id,
                status="available",
                condition_grade="near_mint",
                year=2013,
                tmdb_id=68721,
                width_in=Decimal("27.00"),
                height_in=Decimal("40.00"),
                poster_type="THEATRICAL",
                restoration_status="NONE",
                size_format="ONE_SHEET",
                title="NEW TITLE",
                is_unique=False,
                published_at=None,
                verified_at=None,
            ),
            poster_row(
                sold_id,
                status="sold",
                sold_at=_BASE_DT,
                published_at=_BASE_DT,
                condition_grade="very_fine",
                verified_at=None,
            ),
        ]
        images = [
            image_row(str(uuid.uuid4()), target_id),
            image_row(str(uuid.uuid4()), sold_id),
        ]

        t1 = _BASE_DT
        t2 = _BASE_DT + timedelta(minutes=10)
        reviews = [
            # LIFO — condition_grade เขียนสองครั้ง: NULL→'mint' (t1) แล้ว 'mint'→'near_mint' (t2)
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="condition_grade",
                value_before=None,
                value_after="mint",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="condition_grade",
                value_before="mint",
                value_after="near_mint",
                source="correction-entry-sit-20260916.csv",
                reviewed_at=t2,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="year",
                value_before=None,
                value_after="2013",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="tmdb_id",
                value_before=None,
                value_after="68721",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="width_in",
                value_before=None,
                value_after="27.00",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="height_in",
                value_before=None,
                value_after="40.00",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="poster_type",
                value_before=None,
                value_after="THEATRICAL",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="restoration_status",
                value_before=None,
                value_after="NONE",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="size_format",
                value_before=None,
                value_after="ONE_SHEET",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="title",
                value_before="OLD TITLE",
                value_after="NEW TITLE",
                source="correction-entry-sit-20260916.csv",
                reviewed_at=t2,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="is_unique",
                value_before="True",
                value_after="False",
                source="correction-entry-sit-20260916.csv",
                reviewed_at=t2,
            ),
        ]
        # P4 (WITHDRAW 30 ส.ค.) — OD-1 ปิดแล้วว่า **ย้าย ไม่ลบ** — แถวนี้ต้องรอดหลังโหลด
        # ทุกประการ (ไม่ถูก DELETE ไหนแตะ และไม่ถูก UNWIND แตะเพราะ predicate ③ เลือก
        # เฉพาะ P2 OR P3 เท่านั้น)
        p4_review_id = str(uuid.uuid4())
        reviews.append(
            review_row(
                p4_review_id,
                target_id,
                field="published_at",
                value_before=None,
                value_after="2026-08-20T10:00:00+07:00",
                source="correction-entry-sit-20260830.csv",
                reviewed_at=_BASE_DT - timedelta(days=17),
            )
        )
        dump_text = build_dump(posters, images, reviews)
        insert_script, columns = boot.validate_dump_allowlist(dump_text)
        head = await _current_alembic_head(conn)
        spec = dataclasses.replace(
            make_spec(
                cleared_ids=(target_id,),
                sold_id=sold_id,
                p1_expected=0,
                p2_expected=3,
                p3_expected=8,
                expected_posters=2,
                expected_images=2,
                expected_reviews=1,
                p3_window_start=t1 - timedelta(minutes=1),
                p3_window_end=t1 + timedelta(minutes=1),
            ),
            alembic_head=head,
        )

        report = await boot.run_bootstrap(conn, spec, insert_script, columns)

        surviving = await conn.fetchrow(
            "SELECT id, source, field, value_after FROM public.poster_attribute_reviews"
        )
        assert (
            surviving is not None
        ), "P4 (WITHDRAW 30 ส.ค.) ต้องรอด — OD-1 ปิดแล้วว่าย้ายไม่ลบ แต่ตารางว่างเปล่า"
        assert str(surviving["id"]) == p4_review_id
        assert surviving["source"] == "correction-entry-sit-20260830.csv"
        assert report.rows_deleted["P4_withdraw_20260830"] == 0

        row = await conn.fetchrow(
            "SELECT condition_grade, year, tmdb_id, width_in, height_in, poster_type, "
            "restoration_status, size_format, title, is_unique, published_at, verified_at "
            "FROM public.posters WHERE id = $1::uuid",
            target_id,
        )
        assert (
            row["condition_grade"] is None
        ), "LIFO ต้องย้อนกลับไปที่ NULL (ค่าก่อนเขียนครั้งแรก)"
        assert row["year"] is None
        assert row["tmdb_id"] is None
        assert row["width_in"] is None
        assert row["height_in"] is None
        assert row["poster_type"] is None
        assert row["restoration_status"] is None
        assert row["size_format"] is None
        assert row["title"] == "OLD TITLE"
        assert row["is_unique"] is True
        assert report.rows_unwound == 11
    finally:
        await tx.rollback()
        await conn.close()


# ════════════════════════════════════════════════════════════════════════
# (7) rowcount ของ P1–P3 ≠ ล็อก → ROLLBACK
# ════════════════════════════════════════════════════════════════════════


async def test_delete_rowcount_mismatch_refuses_and_rolls_back_fully() -> None:
    conn, tx = await _connect_clean()
    try:
        cleared_id = str(uuid.uuid4())
        sold_id = str(uuid.uuid4())
        posters = [
            poster_row(cleared_id),
            poster_row(
                sold_id,
                status="sold",
                sold_at=_BASE_DT,
                published_at=_BASE_DT,
                condition_grade="very_fine",
                verified_at=None,
            ),
        ]
        images = [
            image_row(str(uuid.uuid4()), cleared_id),
            image_row(str(uuid.uuid4()), sold_id),
        ]
        reviews = [
            review_row(
                str(uuid.uuid4()),
                cleared_id,
                field="restoration_note",
                source="poster_service.py",
            )
        ]
        dump_text = build_dump(posters, images, reviews)
        insert_script, columns = boot.validate_dump_allowlist(dump_text)
        head = await _current_alembic_head(conn)
        # ล็อก p1_expected ผิดโดยตั้งใจ (มีแค่ 1 แถวจริงที่ source=poster_service.py)
        spec = dataclasses.replace(
            make_spec(
                cleared_ids=(cleared_id,),
                sold_id=sold_id,
                p1_expected=5,
                p2_expected=0,
                p3_expected=0,
                expected_posters=2,
                expected_images=2,
                expected_reviews=0,
            ),
            alembic_head=head,
        )
        await _run_and_expect_refusal_then_verify_empty(
            conn, tx, spec, insert_script, columns, match="DELETE P1"
        )
    finally:
        await conn.close()


# ════════════════════════════════════════════════════════════════════════
# (8) PRODUCTION_SPEC = ตัวเลข/id ของ ADR-0015 A4-D2 ตรงตัว (ล็อก ADR ↔ โค้ด)
# ════════════════════════════════════════════════════════════════════════


def test_production_spec_matches_adr_numbers_and_ids() -> None:
    spec = boot.PRODUCTION_SPEC
    assert spec.alembic_head == "07b34457489c"
    assert spec.cleared_poster_ids == (
        "f95e7f54-816c-5a20-ba19-6cf1329f7a3a",  # IRON MAN 3
        "074bee1e-f2fc-5698-bc28-bb649cda7ed0",  # HARRY POTTER 2: CHAMBER OF SECRETS
        "c2eaba89-59e0-57b4-bfd4-8a2167b8b02a",  # SPIDER-MAN 3 (TOBEY MAGUIRE)
        "e6c9b3d2-9998-54b0-8505-e1bfdb02bd29",  # TITANIC
    )
    assert spec.sold_poster_id == "ec3478a8-b277-52bc-8a45-ecd85de30653"  # THE MATRIX
    assert spec.p1_source_values == ("poster_service.py", "order_service.py")
    assert spec.p1_expected == 11
    assert spec.p2_source == "correction-entry-sit-20260916.csv"
    assert spec.p2_expected == 6
    assert spec.p3_source == "manual-entry.csv"
    assert spec.p3_expected == 16
    assert spec.p3_window_start == datetime(
        2026, 9, 16, 0, 0, 0, tzinfo=timezone(timedelta(hours=7))
    )
    assert spec.p3_window_end == datetime(
        2026, 9, 17, 0, 0, 0, tzinfo=timezone(timedelta(hours=7))
    )
    assert spec.p4_source == "correction-entry-sit-20260830.csv"
    assert spec.expected_after == {
        "posters": 117,
        "poster_images": 407,
        "poster_splits": 0,
        "poster_attribute_reviews": 1099,
    }


# ════════════════════════════════════════════════════════════════════════
# (9) closed-world — UNWIND_FIELDS == union ของค่าคงที่จริงของเส้นที่ 3/5
# ════════════════════════════════════════════════════════════════════════


def test_unwind_fields_is_closed_world_union_of_lane_constants() -> None:
    """`UNWIND_FIELDS` (A4-D2 ③) ต้องเท่ากับ union ที่คำนวณจากค่าคงที่ **จริง** ของ
    `manual_entry.py` (เส้นที่ 3) บวก `{condition_grade, is_unique}` ของเส้นที่ 5
    (`correction_entry.py` — เฉพาะสองฟิลด์ *ค่า* ไม่รวม `verified_at`/`published_at`
    ที่ ② จัดการแยกแล้ว) — ถ้า `manual_entry.ALLOWED_FIELDS` เปลี่ยนวันหน้าโดยไม่แก้
    `_UNWIND_PG_TYPES` ของสคริปต์นี้ เทสนี้ต้องแดง (ล็อก ADR-0015 A4-D7 เทสข้อ 9)
    """
    expected = (
        set(manual_entry.ALLOWED_FIELDS)
        | set(manual_entry.DERIVED_FIELDS)
        | set(manual_entry.OVERWRITE_ELIGIBLE)
        | {"condition_grade", "is_unique"}
    )
    assert boot.PRODUCTION_SPEC.unwind_fields == expected


# ════════════════════════════════════════════════════════════════════════
# (10) AST — ไม่ import poster_ops/lane และไม่เรียก production_gate()
# ════════════════════════════════════════════════════════════════════════


def test_module_does_not_import_lane_modules_or_call_production_gate() -> None:
    source = (BACKEND_ROOT / "scripts" / "ops" / "catalog_bootstrap.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    forbidden_modules = {
        "scripts.seed.poster_ops",
        "scripts.seed.manual_entry",
        "scripts.seed.correction_entry",
        "scripts.orders.order_ops",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert (
                    alias.name not in forbidden_modules
                ), f"ห้าม import {alias.name} — catalog_bootstrap.py ไม่ใช่ lane (A4-D1)"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert (
                module not in forbidden_modules
            ), f"ห้าม import จาก {module} — catalog_bootstrap.py ไม่ใช่ lane (A4-D1)"
            # 🔴 ต้องจับ `from scripts.seed import manual_entry` ด้วย ไม่ใช่แค่
            # `from scripts.seed.manual_entry import X` — `node.module` ของรูปแบบแรก
            # คือ "scripts.seed" เฉย ๆ ซึ่งไม่ตรงกับ forbidden_modules ถ้าไม่ประกอบชื่อ
            # เต็มจาก module + alias.name ก่อนเทียบ (พบระหว่าง implement: checker เดิม
            # ปล่อยรูปแบบนี้ผ่านเงียบ ๆ)
            for alias in node.names:
                full_name = f"{module}.{alias.name}" if module else alias.name
                assert (
                    full_name not in forbidden_modules
                ), f"ห้าม import {full_name} — catalog_bootstrap.py ไม่ใช่ lane (A4-D1)"
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            )
            assert name != "production_gate", (
                "ห้ามเรียก production_gate() — ด่าน 0 ของมันปฏิเสธเส้นที่ไม่อยู่ใน "
                "PRODUCTION_LANES โดยนิยาม และไฟล์นี้ไม่ใช่ lane (A4-D1)"
            )
