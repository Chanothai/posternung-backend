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
import hashlib
import json
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


async def test_precondition_message_names_poster_splits_specifically() -> None:
    """code-critic รอบ 1 Medium 3 (M5) — เทสเดิมข้างบนมีแค่แถวใน `posters` เท่านั้น
    ⇒ ถ้ามี mutation ถอด `poster_splits` ออกจาก loop ของ `_assert_preconditions()`
    เทสข้างบนก็ยังแดงอยู่ดีเพราะ `posters` เพียงอย่างเดียวพอทำให้ precondition ล้ม —
    ไม่เคยพิสูจน์ว่า `poster_splits` ถูกเช็คจริง

    `poster_splits.parent_poster_id`/`child_poster_id` เป็น FK `ondelete=CASCADE` ไป
    `posters` ⇒ **มีแถวใน poster_splits โดยไม่มี posters เลยไม่ได้จริงทางโครงสร้าง** —
    เทสนี้จึงพิสูจน์แค่ว่า error message ระบุ `poster_splits` (พร้อมจำนวนที่ถูกต้อง)
    ไม่ใช่ว่ามันเป็นตารางเดียวที่ผิด — พอสำหรับจับ mutation ที่ถอด poster_splits
    ออกจาก loop เพราะ mutation นั้นทำให้คำว่า `poster_splits` หายไปจาก error message
    """
    conn, tx = await _connect_clean()
    try:
        parent_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())
        await conn.execute(
            _insert_line("posters", _POSTER_COLUMNS, poster_row(parent_id))
        )
        await conn.execute(
            _insert_line("posters", _POSTER_COLUMNS, poster_row(child_id))
        )
        await conn.execute(
            "INSERT INTO public.poster_splits "
            "(id, child_poster_id, parent_poster_id, piece_no, reviewed_by, "
            "reviewed_at, source, reason, created_at) "
            "VALUES ($1::uuid, $2::uuid, $3::uuid, 2, 'tester', $4, "
            "'TEST_INF48_split.csv', 'ทดสอบ precondition', $4)",
            str(uuid.uuid4()),
            child_id,
            parent_id,
            _BASE_DT,
        )
        head = await _current_alembic_head(conn)
        spec = dataclasses.replace(
            make_spec(
                cleared_ids=(),
                sold_id=str(uuid.uuid4()),
                p1_expected=0,
                p2_expected=0,
                p3_expected=0,
                expected_posters=2,
                expected_images=0,
                expected_reviews=0,
            ),
            alembic_head=head,
        )
        with pytest.raises(boot.BootstrapRefused, match="poster_splits"):
            await boot.run_bootstrap(conn, spec, "", {})
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


async def test_assert_no_signature_carried_fires_on_published_at_branch_specifically() -> (
    None
):
    """code-critic รอบ 1 (Low) — เทสข้างบนมี `verified_at` รั่วด้วย ⇒ ฟังก์ชันหยุดที่
    เช็ค `verified_at` (บรรทัดแรกของ `assert_no_signature_carried`) เสมอ ไม่เคยเดินไปถึง
    เช็ค `published_at` เลย — เคสนี้ `verified_at IS NULL` ครบทุกแถว (ผ่านเช็คแรก) แต่มี
    `published_at` ตั้งอยู่บนใบที่ไม่ใช่ `sold_poster_id` ⇒ ต้องถูกจับที่กิ่งที่สองโดยเฉพาะ

    🔴 เรียก `assert_no_signature_carried()` **ตรง ๆ** ไม่ผ่าน `run_bootstrap()` เต็ม —
    CHECK `ck_posters_published_requires_verified` ของ DB บังคับว่า `published_at`
    ที่ไม่ใช่ NULL ต้องมี `verified_at` ไม่ใช่ NULL **หรือ** `status='sold'` เท่านั้น
    ⇒ ใบที่จะ published โดย verified_at เป็น NULL ได้ต้องมี `status='sold'` ซึ่งจะไป
    โดน `assert_no_test_stock_state()` (รันก่อนหน้าใน pipeline จริงของ `run_bootstrap`)
    จับไปก่อนถึงกิ่งที่ต้องการทดสอบ — เรียกฟังก์ชันเดียวตรง ๆ จึงตัดปัญหานี้ทิ้ง
    """
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
            # status='sold' เพื่อผ่าน CHECK ของ DB (published_at ต้องคู่กับ verified_at
            # หรือ status='sold') — ไม่ใช่ sold_poster_id ⇒ ต้องถูกจับที่กิ่ง published_at
            poster_row(
                leaked_id,
                status="sold",
                sold_at=_BASE_DT,
                published_at=_BASE_DT,
                verified_at=None,
                condition_grade="mint",
            ),
        ]
        for p in posters:
            await conn.execute(_insert_line("posters", _POSTER_COLUMNS, p))
        head = await _current_alembic_head(conn)
        spec = dataclasses.replace(
            make_spec(
                cleared_ids=(),
                sold_id=sold_id,
                p1_expected=0,
                p2_expected=0,
                p3_expected=0,
                expected_posters=2,
                expected_images=0,
                expected_reviews=0,
            ),
            alembic_head=head,
        )
        with pytest.raises(
            boot.BootstrapRefused, match="published_at IS NOT NULL ต้องมีแค่แถวเดียว"
        ):
            await boot.assert_no_signature_carried(conn, spec)
    finally:
        await tx.rollback()
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
# (3b) commit path ของ _run_main — marker ต้องเขียน**หลัง**ที่ tx.commit() เท่านั้น
#      (code-critic รอบ 1 Medium 1 · A4-D9 ข้อ 1)
# ════════════════════════════════════════════════════════════════════════


async def test_commit_writes_marker_only_after_tx_commit_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """พิสูจน์ลำดับจริงของ `_run_main(commit=True)`: marker ต้อง**ยังไม่มี**ตอน
    `tx.commit()` ถูกเรียก (เพราะ A4-D9 ข้อ 1 สั่งให้เขียน marker **หลัง** COMMIT
    สำเร็จเท่านั้น — กัน "COMMIT ล้มแต่ marker เขียนไปแล้ว" ซึ่งจะทำให้รันซ้ำไม่ได้
    ทั้งที่ DB ยังว่าง) แล้ว**มีอยู่จริง**หลัง `_run_main()` จบ — mutation ที่ย้าย
    `marker_path.open("x")` ไปวางไว้**ก่อน** `await tx.commit()` ต้องทำให้เทสนี้แดง

    ไม่แตะ DB จริงเลย — `open_connection()`/`run_bootstrap()` ถูก monkeypatch เป็น
    fake object ทั้งคู่ (เทสนี้ทดสอบ**ลำดับการเรียก** ไม่ใช่ตรรกะของการโหลดข้อมูล
    ซึ่งมีเทสของตัวเองอยู่แล้วในข้อ (1)/(2)/(6)/(7))
    """
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("OPS_AUDIT_DIR", str(audit_dir))
    monkeypatch.setenv("ENVIRONMENT", "production")
    marker_path = audit_dir / boot.MARKER_FILENAME

    dump_path = tmp_path / "dump.sql"
    dump_path.write_text(
        "INSERT INTO public.posters (id) VALUES ('x');\n", encoding="utf-8"
    )
    dump_sha256 = hashlib.sha256(dump_path.read_bytes()).hexdigest()
    backup_path = tmp_path / "backup.dump"
    backup_path.write_bytes(b"fake-backup-not-real")

    class _FakeActor:
        id = "11111111-1111-1111-1111-111111111111"

    async def _fake_resolve_admin_actor(session, email, *, require_google_only):
        return _FakeActor()

    class _FakeSessionCM:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc_info):
            return False

    def _fake_session_maker():
        return _FakeSessionCM()

    def _fake_verify_totp(*, audit_dir):
        return None

    def _fake_assert_audit_path_is_persistent(path):
        return None

    def _fake_assert_backup_ref(path, *, now):
        return None

    def _fake_assert_scripts_match_image():
        return "test-image-tag"

    def _fake_confirm_target_interactively(target):
        return None

    class _FakeTransaction:
        def __init__(self, marker_path: Path) -> None:
            self._marker_path = marker_path
            self.marker_existed_at_commit: bool | None = None
            self.committed = False

        async def start(self):
            return None

        async def commit(self):
            self.marker_existed_at_commit = self._marker_path.exists()
            self.committed = True

        async def rollback(self):
            return None

    class _FakeConn:
        def __init__(self, marker_path: Path) -> None:
            self.tx = _FakeTransaction(marker_path)

        def transaction(self):
            return self.tx

        async def close(self):
            return None

    fake_conn = _FakeConn(marker_path)

    async def _fake_open_connection():
        return fake_conn

    fake_report = boot.BootstrapReport(
        rows_loaded={"posters": 1, "poster_images": 0, "poster_attribute_reviews": 0},
        rows_deleted={
            "P1_service": 0,
            "P2_correction_20260916": 0,
            "P3_manual_20260916": 0,
            "P4_withdraw_20260830": 0,
        },
        rows_unwound=0,
        rows_after={
            "posters": 1,
            "poster_images": 0,
            "poster_attribute_reviews": 0,
            "poster_splits": 0,
        },
    )

    async def _fake_run_bootstrap(conn, spec, insert_script, columns_by_table):
        return fake_report

    monkeypatch.setattr(boot, "resolve_admin_actor", _fake_resolve_admin_actor)
    monkeypatch.setattr("app.core.database.async_session_maker", _fake_session_maker)
    monkeypatch.setattr(boot, "_verify_totp", _fake_verify_totp)
    monkeypatch.setattr(
        boot,
        "assert_audit_path_is_persistent",
        _fake_assert_audit_path_is_persistent,
    )
    monkeypatch.setattr(boot, "assert_backup_ref", _fake_assert_backup_ref)
    monkeypatch.setattr(
        boot, "assert_scripts_match_image", _fake_assert_scripts_match_image
    )
    monkeypatch.setattr(
        boot, "confirm_target_interactively", _fake_confirm_target_interactively
    )
    monkeypatch.setattr(boot, "open_connection", _fake_open_connection)
    monkeypatch.setattr(boot, "run_bootstrap", _fake_run_bootstrap)

    args = argparse.Namespace(
        actor="owner@example.test",
        dump=dump_path,
        audit_log=audit_dir / "catalog-bootstrap.jsonl",
        commit=True,
        dump_sha256=dump_sha256,
        backup_ref=backup_path,
    )

    assert not marker_path.exists()
    exit_code = await boot._run_main(args)
    assert exit_code == 0

    assert fake_conn.tx.committed, "tx.commit() ต้องถูกเรียกจริงในโหมด --commit"
    assert fake_conn.tx.marker_existed_at_commit is False, (
        "marker ต้องยังไม่มีอยู่ ณ จังหวะที่ tx.commit() ถูกเรียก — ถ้าแดงแปลว่า "
        "marker ถูกเขียนก่อน COMMIT ซึ่งผิด ADR-0015 A4-D9 ข้อ 1"
    )
    assert marker_path.exists(), "marker ต้องถูกเขียนหลัง COMMIT สำเร็จเท่านั้น"

    audit_lines = (
        (audit_dir / "catalog-bootstrap.jsonl").read_text(encoding="utf-8").splitlines()
    )
    phases = [json.loads(line)["phase"] for line in audit_lines]
    assert phases == ["intent", "committed"], phases


async def test_commit_path_reports_both_errors_when_failed_audit_write_also_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """code-critic รอบ 1 (Low) — ถ้าการโหลดล้มเหลว (เช่น `BootstrapRefused`) *และ*
    เขียน audit `phase="failed"` เองก็ล้มด้วย ผู้รันต้องเห็น**ทั้งสอง**ข้อความ ไม่ใช่
    แค่ตัวหลังที่บังสาเหตุเดิมไว้ — และ `AuditWriteFailed` (RuntimeError) ต้อง propagate
    ออกมาให้ `main()` จับได้ (ไม่ใช่แดงคาที่ `_run_main` เงียบ ๆ)"""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("OPS_AUDIT_DIR", str(audit_dir))
    monkeypatch.setenv("ENVIRONMENT", "production")

    dump_path = tmp_path / "dump.sql"
    dump_path.write_text(
        "INSERT INTO public.posters (id) VALUES ('x');\n", encoding="utf-8"
    )
    dump_sha256 = hashlib.sha256(dump_path.read_bytes()).hexdigest()
    backup_path = tmp_path / "backup.dump"
    backup_path.write_bytes(b"fake-backup-not-real")

    class _FakeActor:
        id = "11111111-1111-1111-1111-111111111111"

    async def _fake_resolve_admin_actor(session, email, *, require_google_only):
        return _FakeActor()

    class _FakeSessionCM:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc_info):
            return False

    def _fake_session_maker():
        return _FakeSessionCM()

    def _fake_verify_totp(*, audit_dir):
        return None

    def _fake_assert_audit_path_is_persistent(path):
        return None

    def _fake_assert_backup_ref(path, *, now):
        return None

    def _fake_assert_scripts_match_image():
        return "test-image-tag"

    def _fake_confirm_target_interactively(target):
        return None

    class _FakeTransaction:
        async def start(self):
            return None

        async def commit(self):
            raise AssertionError("ไม่ควรถูกเรียก — run_bootstrap ล้มก่อนถึง commit")

        async def rollback(self):
            return None

    class _FakeConn:
        def transaction(self):
            return _FakeTransaction()

        async def close(self):
            return None

    async def _fake_open_connection():
        return _FakeConn()

    async def _fake_run_bootstrap(conn, spec, insert_script, columns_by_table):
        raise boot.BootstrapRefused("จำลอง precondition ล้ม")

    call_count = {"n": 0}

    def _fake_append_audit_line(path, record):
        call_count["n"] += 1
        if call_count["n"] == 1:
            assert record["phase"] == "intent"
            return
        assert record["phase"] == "failed"
        raise boot.AuditWriteFailed("จำลอง — เขียน audit failed ไม่สำเร็จ")

    monkeypatch.setattr(boot, "resolve_admin_actor", _fake_resolve_admin_actor)
    monkeypatch.setattr("app.core.database.async_session_maker", _fake_session_maker)
    monkeypatch.setattr(boot, "_verify_totp", _fake_verify_totp)
    monkeypatch.setattr(
        boot,
        "assert_audit_path_is_persistent",
        _fake_assert_audit_path_is_persistent,
    )
    monkeypatch.setattr(boot, "assert_backup_ref", _fake_assert_backup_ref)
    monkeypatch.setattr(
        boot, "assert_scripts_match_image", _fake_assert_scripts_match_image
    )
    monkeypatch.setattr(
        boot, "confirm_target_interactively", _fake_confirm_target_interactively
    )
    monkeypatch.setattr(boot, "open_connection", _fake_open_connection)
    monkeypatch.setattr(boot, "run_bootstrap", _fake_run_bootstrap)
    monkeypatch.setattr(boot, "append_audit_line", _fake_append_audit_line)

    args = argparse.Namespace(
        actor="owner@example.test",
        dump=dump_path,
        audit_log=audit_dir / "catalog-bootstrap.jsonl",
        commit=True,
        dump_sha256=dump_sha256,
        backup_ref=backup_path,
    )

    with pytest.raises(boot.AuditWriteFailed):
        await boot._run_main(args)

    printed = capsys.readouterr().err
    assert "จำลอง precondition ล้ม" in printed, printed
    assert "จำลอง — เขียน audit failed ไม่สำเร็จ" in printed, printed


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


@pytest.mark.parametrize(
    "preamble_line",
    [
        "SET statement_timeout = 0;",
        "SET client_encoding = 'UTF8';",
        "SELECT pg_catalog.set_config('search_path', '', false);",
        "\\restrict aBcDeFgH1234567890",
        "\\unrestrict aBcDeFgH1234567890",
    ],
    ids=["SET-plain", "SET-with-quoted-value", "set_config", "restrict", "unrestrict"],
)
def test_dump_allowlist_rejects_each_pg_dump_preamble_line_type(
    preamble_line: str,
) -> None:
    """code-critic รอบ 1 Medium 2 (M3) — เทสรวมเดิมยิง SET กับ set_config พร้อมกันใน
    ไฟล์เดียว ⇒ mutation ที่ทำให้สแกนเนอร์ยอม `SET` อย่างเดียว (แต่ยังปฏิเสธ
    `set_config`) จะรอดเพราะบรรทัด `set_config` ยังทำให้เทสแดงอยู่ดี — แยกเป็นเคส
    ต่อบรรทัดจริง (parametrize) ให้แต่ละรูปแบบมีเทสของตัวเองที่ต้องแดงเดี่ยว ๆ
    """
    raw = f"{preamble_line}\nINSERT INTO public.posters (id) VALUES ('x');\n"
    with pytest.raises(boot.BootstrapRefused):
        boot.validate_dump_allowlist(raw)


def test_dump_allowlist_accepts_blank_lines_and_comments() -> None:
    ok = "-- comment\n\nINSERT INTO public.posters (id) VALUES ('x');\n"
    script, columns = boot.validate_dump_allowlist(ok)
    assert "posters" in columns
    assert script.strip() == "INSERT INTO public.posters (id) VALUES ('x');"


def test_dump_allowlist_rejects_second_statement_injected_via_semicolon() -> None:
    """code-critic รอบ 1 Medium 2 — `_INSERT_LINE_RE` เช็คแค่ *ขึ้นต้น* ของบรรทัด ·
    ถ้าไม่เช็คส่วนที่เหลือด้วย บรรทัดที่มี statement ที่สองแอบต่อท้ายจะหลุดผ่านไปได้
    (`; DROP TABLE …` ไม่ได้ขึ้นต้นบรรทัดจึง regex prefix ไม่เคยเห็น)"""
    bad = "INSERT INTO public.posters (id) VALUES ('x'); DROP TABLE posters;\n"
    with pytest.raises(boot.BootstrapRefused):
        boot.validate_dump_allowlist(bad)


def test_dump_allowlist_rejects_commit_injected_after_insert() -> None:
    bad = "INSERT INTO public.posters (id) VALUES ('x'); COMMIT;\n"
    with pytest.raises(boot.BootstrapRefused):
        boot.validate_dump_allowlist(bad)


def test_dump_allowlist_rejects_second_statement_that_still_ends_with_close_paren() -> (
    None
):
    """เคสที่ซ่อนได้แนบเนียนกว่า test_dump_allowlist_rejects_second_statement_injected_
    via_semicolon — statement ที่สองลงท้ายด้วย `);` เหมือนกัน (`line.endswith(");")`
    เพียงอย่างเดียวจับไม่ได้) ต้องอาศัยการนับ `;` นอก string literal ทั้งบรรทัด"""
    bad = (
        "INSERT INTO public.posters (id) VALUES ('x'); "
        "UPDATE public.posters SET price = 0 WHERE (price > 0);\n"
    )
    with pytest.raises(boot.BootstrapRefused):
        boot.validate_dump_allowlist(bad)


def test_dump_allowlist_rejects_line_missing_trailing_close_paren_semicolon() -> None:
    bad = "INSERT INTO public.posters (id) VALUES ('x')\n"  # ไม่มี ; ปิดท้าย
    with pytest.raises(boot.BootstrapRefused):
        boot.validate_dump_allowlist(bad)


def test_dump_allowlist_accepts_escaped_single_quote_inside_string_literal() -> None:
    """`it''s` คือ apostrophe ที่ escape แล้วตามมาตรฐาน SQL (single quote คู่) — ต้อง
    ไม่ถูกตีความว่าสตริงปิดกลางทางแล้วมี `;`/อักขระหลังจากนั้นเป็น "นอกสตริง" ปลอม ๆ
    """
    ok = "INSERT INTO public.posters (id, title) VALUES ('x', 'it''s here; not a stmt');\n"
    script, columns = boot.validate_dump_allowlist(ok)
    assert "it''s here; not a stmt" in script
    assert "posters" in columns


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


async def test_column_set_same_length_different_name_is_refused() -> None:
    """code-critic รอบ 1 Medium 4 (M6) — เทสข้างบนลบคอลัมน์ทิ้งไปหนึ่งตัว (เซตเล็กลง)
    ซึ่ง mutation ที่เทียบแค่ `len(dump_columns) == len(real_columns)` แทน set equality
    ก็ยังจับเคสนั้นได้ (ยาวไม่เท่ากัน) — เคสนี้สลับชื่อคอลัมน์ (`title` → `titel`)
    จำนวนคอลัมน์เท่าเดิมเป๊ะ ต้องอาศัย set equality จริง ๆ ถึงจะจับได้"""
    conn, tx = await _connect_clean()
    try:
        renamed = tuple("titel" if c == "title" else c for c in _POSTER_COLUMNS)
        assert len(renamed) == len(_POSTER_COLUMNS), "เทสนี้ต้องมีจำนวนคอลัมน์เท่าเดิม"
        with pytest.raises(boot.BootstrapRefused, match="column set"):
            await boot._assert_columns_match_table(conn, "posters", renamed)
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
            # 🔴 code-critic รอบ 1 (High) — `value_before` ของทุกฟิลด์ที่ไม่ใช่ LIFO/boolean/
            # text ต้อง**ไม่เป็น NULL** ที่นี่ เพราะ NULL ไม่พิสูจน์ว่า `_coerce_unwind_param()`
            # แปลงชนิดถูก (asyncpg ส่ง `None` ผ่านได้ทุก OID อยู่แล้วโดยไม่ต้องแปลงอะไรเลย
            # — เคสที่พังจริงคือ str ที่ไม่ใช่ None เข้าพารามิเตอร์ smallint/integer)
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="year",
                value_before="1999",
                value_after="2013",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="tmdb_id",
                value_before="100",
                value_after="68721",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="width_in",
                value_before="11.00",
                value_after="27.00",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="height_in",
                value_before="17.00",
                value_after="40.00",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="poster_type",
                value_before="ADVANCE",
                value_after="THEATRICAL",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="restoration_status",
                value_before="RESTORED",
                value_after="NONE",
                source="manual-entry.csv",
                reviewed_at=t1,
            ),
            review_row(
                str(uuid.uuid4()),
                target_id,
                field="size_format",
                value_before="HALF_SHEET",
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
        # ค่าที่เหลือทั้งหมด value_before **ไม่ใช่ NULL** — พิสูจน์ว่า _coerce_unwind_param()
        # แปลงชนิด Python ถูกต้องจริงสำหรับ smallint/integer/numeric/enum ทุกตัว ไม่ใช่แค่
        # ผ่าน None ซึ่งไม่ต้องแปลงอะไรเลย (code-critic รอบ 1 High)
        assert row["year"] == 1999
        assert row["tmdb_id"] == 100
        assert row["width_in"] == Decimal("11.00")
        assert row["height_in"] == Decimal("17.00")
        assert row["poster_type"] == "ADVANCE"
        assert row["restoration_status"] == "RESTORED"
        assert row["size_format"] == "HALF_SHEET"
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
