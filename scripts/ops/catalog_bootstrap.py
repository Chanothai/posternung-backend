"""ย้ายแคตตาล็อก 117 ใบจาก SIT เข้า production **ครั้งเดียว** — ADR-0015 Amendment 4 (INF-48)

    docker exec -it posternung-production-app python scripts/ops/catalog_bootstrap.py \\
        --actor <อีเมล google-only> \\
        --dump /app/var/ops/backups/sit-catalog-<UTC>.sql \\
        --audit-log /app/var/ops/audit/catalog-bootstrap.jsonl
    # → dry-run: ผ่านด่าน 1–9 แล้ว ROLLBACK · พิมพ์ dump-sha256
    docker exec -it posternung-production-app python scripts/ops/catalog_bootstrap.py \\
        --actor <อีเมล google-only> \\
        --dump /app/var/ops/backups/sit-catalog-<UTC>.sql \\
        --audit-log /app/var/ops/audit/catalog-bootstrap.jsonl \\
        --commit --dump-sha256 <hex จาก dry-run> \\
        --backup-ref /app/var/ops/backups/<UTC>.dump

รายละเอียดเต็ม (ทำไมต้องมีใบนี้ · ตัวเลข/id ที่ล็อก · เหตุผลของแต่ละด่าน) อยู่ที่
`../workspace/docs/adr/ADR-0015-manual-entry-path.md` §"Amendment 4" — **ห้ามเล่าซ้ำที่นี่
เกินกว่าที่จำเป็นให้คนอ่านโค้ดเข้าใจ** ลำดับปฏิบัติจริงบน production อยู่ที่ runbook
`../workspace/docs/runbooks/production-catalog-bootstrap.md`

## นี่ไม่ใช่ lane — เป็น one-shot (A4-D1)

`scripts/seed/*.py` เป็นเส้นทางเขียน `posters` ที่ "มีชีวิตต่อ" รันซ้ำได้ตามใบงานใหม่
ทุกรอบ และขึ้นทะเบียนใน `scripts._production_gate.PRODUCTION_LANES` — ไฟล์นี้คือการ
ก่อร่างฐานที่ทำได้ **ครั้งเดียวต่อ environment** แล้วปิดถาวรด้วย marker (`A4-D4`)
⇒ **ไม่เข้า `poster_ops.py`** · **ไม่เพิ่มชื่อเข้า `PRODUCTION_LANES`** · **ไม่เรียก
`production_gate()`** (ด่าน 0 ของมันจะปฏิเสธโดยนิยาม และถูกต้องแล้วที่ปฏิเสธ) —
สคริปต์นี้ยืมด่านของ `scripts/_production_gate.py` เป็น**รายฟังก์ชัน**แทน

## ลำดับด่าน (A4-D1 · ทุกข้อ fail-closed)

1. marker `${OPS_AUDIT_DIR}/catalog-bootstrap.done` ต้องไม่มี — ตรวจก่อนเปิด connection
   ใด ๆ ทั้งสิ้น (แม้แต่ session สำหรับ resolve actor)
2. `ENVIRONMENT=production` ⇔ สคริปต์รู้จัก production ค่าเดียว ไม่มี `--target`
3. `--actor` = admin google-only (`resolve_admin_actor`)
4. TOTP (`_verify_totp`) — ทั้ง dry-run และ commit
5. `--audit-log` อยู่ใต้ `OPS_AUDIT_DIR` และเขียนได้จริง
6. `--backup-ref` = `pg_dump -Fc` สดของ production ≤ 60 นาที — **commit เท่านั้น**
7. `scripts/` sha ตรงกับ `IMAGE_TAG`
8. `count(*) = 0` ทั้ง 4 ตาราง + `alembic_version` ตรงกับที่ dump มา — ในทรานแซกชัน
   เดียวกับการโหลด (กัน TOCTOU)
9. โหลด → ล้าง (A4-D2) → assert หลังโหลด — ไม่ผ่านข้อใด = ROLLBACK ทั้งชุด

## ทางเลือกที่ implementation ตัดสินเอง (A4-D9 ข้อ 2 — "backend-dev เลือกได้")

**dump ทั้งไฟล์เป็น script เดียวผ่าน asyncpg simple-query protocol** (`conn.execute(sql)`
ไม่มี args) แทนการ parse/ยิงทีละ statement ผ่าน SQLAlchemy — และ **ทั้งสคริปต์ใช้ asyncpg
ล้วน** สำหรับส่วนที่ต้องอยู่ในทรานแซกชันเดียวกัน (precondition → INSERT → RESET →
UNWIND → DELETE → ASSERT) ไม่ผสมกับ `AsyncConnection.get_raw_connection()` ของ
SQLAlchemy — เหตุผล: `get_raw_connection()` คืน `AdaptedConnection` ที่ SQLAlchemy
เป็นเจ้าของ transaction state อยู่แล้ว การยิง raw query ผ่านมันพร้อมกับให้ asyncpg
เป็นคนคุม `BEGIN`/`COMMIT` เองมีความเสี่ยงที่ทั้งสองฝั่งเข้าใจ transaction ไม่ตรงกัน
(SQLAlchemy AsyncConnection ไม่ได้ออกแบบมาให้โค้ดอื่นแย่งคุม transaction ของมัน) —
asyncpg ล้วนตัดปัญหานี้ทิ้งไปเลย ราคาที่จ่ายคือ session สำหรับ `resolve_admin_actor()`
(ด่าน 3) ต้องเปิดแยกเป็น SQLAlchemy `AsyncSession` ของตัวเอง (อ่านอย่างเดียว ไม่ใช่
ส่วนหนึ่งของทรานแซกชันที่โหลดข้อมูล จึงแยกได้โดยไม่กระทบ atomicity)

**allowlist ของ dump สแกนทุกบรรทัดเอง** (ไม่พึ่งว่า runbook กรองมาให้ครบ) — บรรทัดที่
ไม่ว่างและไม่ใช่ `--` comment ต้องขึ้นต้นด้วย `INSERT INTO public.(posters|
poster_images|poster_attribute_reviews) (` เท่านั้น ไม่งั้นปฏิเสธทั้งไฟล์ก่อนเปิด
connection ใด ๆ — runbook ยังคง `grep -E '^INSERT INTO'` ไว้เป็นชั้นแรก (ตัดบรรทัด
`SET …`/`SELECT pg_catalog.set_config(...)`/`\\restrict`/`\\unrestrict` ที่ pg_dump 16
ปล่อยออกมา) ส่วนตัวสแกนในนี้เป็น**ชั้นที่สอง** ที่ไม่พึ่งว่าชั้นแรกทำถูก — พิสูจน์แล้วกับ
dump จริงจาก `pg_dump` 16.15 ของ `posternung-sit-db` (117/407/1132 แถว) ว่ารูปแบบตรงตามนี้
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import socket
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts._actor import resolve_admin_actor  # noqa: E402
from scripts._audit import AuditWriteFailed, append_audit_line  # noqa: E402
from scripts._production_gate import (  # noqa: E402
    _verify_totp,
    assert_audit_path_is_persistent,
    assert_backup_ref,
    assert_environment_matches,
    assert_scripts_match_image,
    confirm_target_interactively,
)
from scripts.seed._shared import PrecheckError  # noqa: E402

if TYPE_CHECKING:
    import asyncpg

# ── ชื่อ/ตำแหน่งไฟล์ (A4-D4) ────────────────────────────────────────────
MARKER_FILENAME = "catalog-bootstrap.done"
LANE_NAME = "catalog-bootstrap"
TARGET_NAME = "production"

# ── allowlist ของ dump (A4-D9 ข้อ 2) ────────────────────────────────────
REQUIRED_TABLES = ("posters", "poster_images", "poster_attribute_reviews")
_INSERT_LINE_RE = re.compile(
    r"^INSERT INTO public\.(posters|poster_images|poster_attribute_reviews) "
    r"\((?P<columns>[^)]*)\) VALUES"
)


def _unquoted_semicolon_positions(line: str) -> list[int]:
    """ตำแหน่ง `;` ที่อยู่**นอก** single-quoted string ของบรรทัด SQL หนึ่งบรรทัด

    เดิน char ต่อ char ติดตามว่าอยู่ในสตริงหรือไม่ — `''` (single quote คู่) ภายใน
    สตริงคือ quote ที่ escape แล้ว (มาตรฐาน SQL) ไม่ใช่ตัวปิดสตริง ต้องแยกให้ถูก
    ไม่งั้นค่าที่มี apostrophe จริง (เช่น `it''s here`) จะถูกตีความผิดว่าสตริงปิดกลาง
    ทาง แล้ว `;`/อักขระหลังจากนั้นกลายเป็น "นอกสตริง" ทั้งที่จริงยังอยู่ในสตริง
    """
    positions: list[int] = []
    in_quote = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if in_quote:
            if ch == "'":
                if i + 1 < n and line[i + 1] == "'":
                    i += 2
                    continue
                in_quote = False
            i += 1
            continue
        if ch == "'":
            in_quote = True
            i += 1
            continue
        if ch == ";":
            positions.append(i)
        i += 1
    return positions


def _assert_single_statement_line(line: str, *, lineno: int) -> None:
    """A4-D9 ข้อ 2 (code-critic รอบ 1 Medium 2) — บรรทัด INSERT ต้องเป็น **statement
    เดียว** เป๊ะ: ลงท้ายด้วย `);` และมี `;` ที่ไม่อยู่ใน quote ตัวเดียวคือตัวปิดท้าย

    กัน `INSERT INTO … VALUES ('x'); DROP TABLE posters;` (statement ที่สองแอบต่อท้าย
    ในบรรทัดเดียวกัน — `_INSERT_LINE_RE` เช็คแค่ *ขึ้นต้น* ของบรรทัด ไม่เคยเช็ค
    *ส่วนที่เหลือ* มาก่อน) — ปฏิเสธทั้งไฟล์ก่อนเปิด connection เหมือนด่านอื่นของ
    allowlist นี้
    """
    if not line.endswith(");"):
        raise BootstrapRefused(
            f"บรรทัดที่ {lineno} ของ --dump ไม่ได้ลงท้ายด้วย ');' — ต้องเป็น statement "
            "INSERT เดียวจบในบรรทัดเดียวกัน ห้ามมีอะไรต่อท้าย (ADR-0015 A4-D9 ข้อ 2) "
            f"ท้ายบรรทัด (20 ตัวอักษรสุดท้าย): {line[-20:]!r}"
        )
    semicolons = _unquoted_semicolon_positions(line)
    if semicolons != [len(line) - 1]:
        raise BootstrapRefused(
            f"บรรทัดที่ {lineno} ของ --dump มี ';' นอก string literal มากกว่าหนึ่งตัว "
            f"(พบที่ตำแหน่ง {semicolons} — ต้องมีตัวเดียวคือตัวปิดท้ายบรรทัด) "
            "— น่าจะมี statement ที่สองแอบต่อท้ายในบรรทัดเดียวกัน ปฏิเสธทั้งไฟล์ "
            "(ADR-0015 A4-D9 ข้อ 2)"
        )


class BootstrapRefused(PrecheckError):
    """ด่านใดด่านหนึ่งของ A4-D1..D9 ไม่ผ่าน — ยังไม่แตะ/ต้องย้อน DB"""


class MarkerAlreadyExists(BootstrapRefused):
    """ด่าน 1 — รันไปแล้วครั้งหนึ่ง marker ปฏิเสธก่อนถาม TOTP/เปิด DB (A4-D1 ด่าน 1)"""


# ── ฟิลด์ที่ UNWIND (③) รับได้ — closed-world (A4-D2 ③) ──────────────────
# = ALLOWED_FIELDS ∪ DERIVED_FIELDS ∪ OVERWRITE_ELIGIBLE ของเส้นที่ 3
#   (`scripts/seed/manual_entry.py`) ∪ {condition_grade, is_unique} ของเส้นที่ 5
#   (`scripts/seed/correction_entry.py` — เฉพาะสองฟิลด์ *ค่า* ไม่รวม verified_at/
#   published_at ซึ่งถูกจัดการแยกที่ ② แล้ว)
# 🔴 **ห้ามเพิ่ม/ลบโดยไม่แก้ ADR-0015 Amendment 4** — `tests/unit/test_catalog_bootstrap.py`
# ล็อกให้ต้องเท่ากับ union ที่คำนวณจากค่าคงที่จริงของทั้งสองเส้น (closed-world test)
_UNWIND_PG_TYPES: dict[str, str] = {
    "condition_grade": "poster_condition",
    "is_unique": "boolean",
    "year": "smallint",
    "poster_type": "poster_type",
    "restoration_status": "restoration_status",
    "tmdb_id": "integer",
    "width_in": "numeric",
    "height_in": "numeric",
    "size_format": "size_format",
    "title": "text",
}


@dataclass(frozen=True)
class BootstrapSpec:
    """ตัวเลข/id ที่ล็อกไว้ตาม ADR-0015 A4-D2 — เทส `test_production_spec_matches_adr`
    เทียบค่าพวกนี้กับตัวเลขในตัว ADR ตรง ๆ (ล็อก ADR ↔ โค้ด · A4-D7 เทสข้อ 8)"""

    alembic_head: str
    cleared_poster_ids: tuple[str, ...]
    sold_poster_id: str
    p1_source_values: tuple[str, ...]
    p1_expected: int
    p2_source: str
    p2_expected: int
    p3_source: str
    p3_window_start: datetime
    p3_window_end: datetime
    p3_expected: int
    p4_source: str  # WITHDRAW 30 ส.ค. — OD-1: **ย้าย ไม่ลบ** (เก็บไว้แค่บันทึกที่มา)
    unwind_pg_types: dict[str, str] = field(
        default_factory=lambda: dict(_UNWIND_PG_TYPES)
    )
    expected_after: dict[str, int] = field(
        default_factory=lambda: {
            "posters": 117,
            "poster_images": 407,
            "poster_splits": 0,
            "poster_attribute_reviews": 1099,
        }
    )

    @property
    def unwind_fields(self) -> frozenset[str]:
        return frozenset(self.unwind_pg_types)


# ── ค่าจริงของ SIT ณ 22 ก.ย. 2026 15:30 (ยืนยันซ้ำด้วย SQL บน posternung-sit-db ตอน
# implement — alembic 07b34457489c ตรงกับ production) — ดู ADR-0015 A4-D2 + screens.yaml
# INF-48 comment ────────────────────────────────────────────────────────
PRODUCTION_SPEC = BootstrapSpec(
    alembic_head="07b34457489c",
    cleared_poster_ids=(
        "f95e7f54-816c-5a20-ba19-6cf1329f7a3a",  # IRON MAN 3
        "074bee1e-f2fc-5698-bc28-bb649cda7ed0",  # HARRY POTTER 2: CHAMBER OF SECRETS
        "c2eaba89-59e0-57b4-bfd4-8a2167b8b02a",  # SPIDER-MAN 3 (TOBEY MAGUIRE)
        "e6c9b3d2-9998-54b0-8505-e1bfdb02bd29",  # TITANIC — smoke sold 18 ก.ย. (SIT artifact)
    ),
    sold_poster_id="ec3478a8-b277-52bc-8a45-ecd85de30653",  # THE MATRIX — ขายจริงนอกระบบ (A-D11 ห้ามถอน)
    p1_source_values=("poster_service.py", "order_service.py"),
    p1_expected=11,
    p2_source="correction-entry-sit-20260916.csv",
    p2_expected=6,
    p3_source="manual-entry.csv",
    p3_window_start=datetime(2026, 9, 16, 0, 0, 0, tzinfo=timezone(timedelta(hours=7))),
    p3_window_end=datetime(2026, 9, 17, 0, 0, 0, tzinfo=timezone(timedelta(hours=7))),
    p3_expected=16,
    p4_source="correction-entry-sit-20260830.csv",
)


# ════════════════════════════════════════════════════════════════════════
# การอ่าน + ตรวจ dump (ก่อนเปิด connection ใด ๆ — A4-D9 ข้อ 2)
# ════════════════════════════════════════════════════════════════════════


def validate_dump_allowlist(dump_text: str) -> tuple[str, dict[str, tuple[str, ...]]]:
    """คืน (script ที่กรองแล้วเฉพาะบรรทัด INSERT เรียงตามไฟล์เดิม, column set ต่อตาราง)

    ปฏิเสธทั้งไฟล์ (`BootstrapRefused`) ถ้า: มีบรรทัดที่ไม่ว่าง/ไม่ใช่ `--` comment ซึ่งไม่
    ขึ้นต้นด้วย `INSERT INTO public.(posters|poster_images|poster_attribute_reviews) (` ·
    ตารางเดียวกันมี column list ไม่ตรงกันระหว่างแถว · ไม่มีข้อมูลของตารางที่ต้องมีครบสาม
    """
    insert_lines: list[str] = []
    columns_by_table: dict[str, tuple[str, ...]] = {}
    for lineno, raw_line in enumerate(dump_text.splitlines(), start=1):
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        if line.startswith("--"):
            continue
        match = _INSERT_LINE_RE.match(line)
        if not match:
            raise BootstrapRefused(
                f"บรรทัดที่ {lineno} ของ --dump ไม่ใช่บรรทัดว่าง/comment และไม่ขึ้นต้นด้วย "
                "'INSERT INTO public.(posters|poster_images|poster_attribute_reviews) (' "
                "— ปฏิเสธทั้งไฟล์ก่อนเปิด connection (ADR-0015 A4-D9 ข้อ 2) "
                f"เนื้อบรรทัด (ตัดที่ 120 ตัวอักษร): {line[:120]!r}"
            )
        _assert_single_statement_line(line, lineno=lineno)
        table = match.group(1)
        columns = tuple(c.strip() for c in match.group("columns").split(","))
        existing = columns_by_table.get(table)
        if existing is None:
            columns_by_table[table] = columns
        elif existing != columns:
            raise BootstrapRefused(
                f"บรรทัดที่ {lineno}: column list ของตาราง {table!r} ไม่ตรงกับแถวก่อนหน้า "
                "ของตารางเดียวกันในไฟล์เดียวกัน — dump ผิดรูปแบบหรือถูกแก้มือ"
            )
        insert_lines.append(line)

    if not insert_lines:
        raise BootstrapRefused("ไฟล์ --dump ไม่มีบรรทัด INSERT เลยสักบรรทัด")
    # 🔴 ไม่บังคับว่าต้องมีครบทั้งสามตาราง — `pg_dump -t <table> --data-only --inserts`
    # ของตารางที่ไม่มีแถวเลยจะไม่ปล่อยบรรทัด INSERT ออกมาสักบรรทัด (พิสูจน์แล้วกับ
    # `poster_splits` จริงตอน implement) การบังคับ "ต้องมีครบสามตาราง" ที่นี่จะปฏิเสธ
    # ไฟล์ที่ถูกต้องสมบูรณ์ในกรณีนั้น — column-set check (ต่อตารางที่ *มี* บรรทัดจริง)
    # และ precondition/assert หลังโหลดเป็นด่านที่ตรวจความถูกต้องของเนื้อหาต่อไป
    return "\n".join(insert_lines) + "\n", columns_by_table


async def _assert_columns_match_table(
    conn: "asyncpg.Connection", table: str, columns: tuple[str, ...]
) -> None:
    """A4-D2 (2) — เทียบ column set ของแต่ละตารางใน dump กับตารางจริงบนฐานที่กำลังจะโหลด
    ก่อน INSERT แรก (ปิดกับดัก BACKLOG §15.3 "เทียบ COPY column list กับตารางจริงก่อนยิง")
    """
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1",
        table,
    )
    real_columns = {r["column_name"] for r in rows}
    dump_columns = set(columns)
    if dump_columns != real_columns:
        missing = sorted(real_columns - dump_columns)
        extra = sorted(dump_columns - real_columns)
        raise BootstrapRefused(
            f"column set ของตาราง {table!r} ใน --dump ไม่ตรงกับตารางจริง — "
            f"ขาด (มีในตารางจริงแต่ไม่มีใน dump): {missing} · "
            f"เกิน (มีใน dump แต่ไม่มีในตารางจริง): {extra}"
        )


# ════════════════════════════════════════════════════════════════════════
# ตรรกะในทรานสแอคชัน (①–⑤) — ผู้เรียกเป็นคนเปิด/ปิดทรานแซกชันเอง (เทสครอบเอง)
# ════════════════════════════════════════════════════════════════════════


@dataclass
class BootstrapReport:
    rows_loaded: dict[str, int]
    rows_deleted: dict[str, int]
    rows_unwound: int
    rows_after: dict[str, int]


def _rowcount(command_tag: str) -> int:
    return int(command_tag.rsplit(" ", 1)[-1])


def _assert_rowcount(command_tag: str, expected: int, label: str) -> int:
    actual = _rowcount(command_tag)
    if actual != expected:
        raise BootstrapRefused(
            f"{label}: rowcount จริง {actual} ไม่ตรงกับตัวเลขที่ล็อกไว้ {expected} "
            "(ADR-0015 A4-D2) — ROLLBACK ทั้งชุด"
        )
    return actual


async def _assert_preconditions(
    conn: "asyncpg.Connection", spec: BootstrapSpec
) -> None:
    """ด่าน 8 — `count(*) = 0` ทั้ง 4 ตาราง + `alembic_version` ตรงกับที่ dump มา
    ในทรานแซกชันเดียวกับการโหลด (กัน TOCTOU) — ต้องผ่านก่อน INSERT แรกเสมอ"""
    counts: dict[str, int] = {}
    for table in (*REQUIRED_TABLES, "poster_splits"):
        counts[table] = await conn.fetchval(f"SELECT count(*) FROM public.{table}")
    nonzero = {t: c for t, c in counts.items() if c}
    if nonzero:
        raise BootstrapRefused(
            "precondition ล้ม (AC-1 (1)) — ทุกตารางต้องว่างก่อนโหลด แต่พบแถวอยู่แล้ว: "
            f"{nonzero} — ถ้าเคยรันสำเร็จมาก่อน marker ควรปฏิเสธไปแล้วที่ด่าน 1 "
            "ก่อนถึงตรงนี้ (ตรวจว่า marker ถูกลบไปหรือไม่ — ต้องมี ADR amendment ใหม่ "
            "ก่อนลบ marker เพื่อรันซ้ำ)"
        )
    version = await conn.fetchval("SELECT version_num FROM alembic_version")
    if version != spec.alembic_head:
        raise BootstrapRefused(
            f"alembic_version ของฐานนี้คือ {version!r} ไม่ตรงกับที่ dump มา "
            f"({spec.alembic_head!r}) — schema ไม่ตรงกัน ห้ามโหลด"
        )


async def assert_no_test_stock_state(
    conn: "asyncpg.Connection", spec: BootstrapSpec
) -> None:
    """A4-D9 ข้อ 3 — ไม่มี `posters.status ∈ {reserved, sold}` นอกจาก `sold_poster_id`
    รายงานชื่อด่าน + id ที่ละเมิดตอนล้ม (ไม่ใช่แค่บอกว่า "ไม่ผ่าน")"""
    rows = await conn.fetch(
        "SELECT id, status FROM public.posters "
        "WHERE status IN ('reserved', 'sold') AND id <> $1::uuid",
        spec.sold_poster_id,
    )
    if rows:
        offending = [f"{r['id']}={r['status']}" for r in rows]
        raise BootstrapRefused(
            "assert_no_test_stock_state ล้ม — พบ "
            f"{len(rows)} แถวที่ status อยู่ใน {{reserved, sold}} ทั้งที่ไม่ใช่ "
            f"{spec.sold_poster_id}: {offending}"
        )


async def assert_no_signature_carried(
    conn: "asyncpg.Connection", spec: BootstrapSpec
) -> None:
    """A4-D9 ข้อ 3 — `verified_at IS NULL` ทั้ง 117 ใบ และ `published_at IS NOT NULL`
    ต้องมีแถวเดียวคือ `sold_poster_id` เท่านั้น (OD-2) — รายงานชื่อด่าน + id ที่ละเมิด
    """
    verified_rows = await conn.fetch(
        "SELECT id FROM public.posters WHERE verified_at IS NOT NULL"
    )
    if verified_rows:
        offending = [str(r["id"]) for r in verified_rows]
        raise BootstrapRefused(
            "assert_no_signature_carried ล้ม — verified_at ต้องเป็น NULL ทั้ง 117 ใบ "
            f"แต่พบ {len(verified_rows)} แถวที่ไม่ใช่ NULL: {offending}"
        )
    published_rows = await conn.fetch(
        "SELECT id FROM public.posters WHERE published_at IS NOT NULL"
    )
    published_ids = sorted(str(r["id"]) for r in published_rows)
    if published_ids != [spec.sold_poster_id]:
        raise BootstrapRefused(
            "assert_no_signature_carried ล้ม — published_at IS NOT NULL ต้องมีแค่แถวเดียว "
            f"({spec.sold_poster_id}) แต่ได้ {published_ids}"
        )


async def _assert_row_shape(conn: "asyncpg.Connection", spec: BootstrapSpec) -> None:
    """ตาราง "หลังโหลดต้องได้" ของ A4-D2 ที่เหลือ (นอกเหนือจากสอง assert ชื่อชัดข้างบน):
    จำนวนแถวต่อตาราง · สถานะ · `sold_at` · ไม่มี poster ไร้รูป/รูปกำพร้า · readiness"""
    actual = {
        table: await conn.fetchval(f"SELECT count(*) FROM public.{table}")
        for table in (*REQUIRED_TABLES, "poster_splits")
    }
    if actual != spec.expected_after:
        raise BootstrapRefused(
            f"จำนวนแถวหลังโหลดไม่ตรงกับที่ล็อกไว้: ได้ {actual} ต้องการ {spec.expected_after}"
        )

    # หลัง ② มีแถว `sold` ได้แถวเดียวเสมอตามการออกแบบของ spec (`sold_poster_id`) —
    # ที่เหลือทั้งหมดต้องเป็น `available` (มาจากเดิมที่ไม่เคยถูกแตะ หรือถูก RESET ที่ ②)
    # คำนวณจาก `spec.expected_after` แทนเลขคงที่ เพื่อให้ทดสอบกับ fixture เล็กได้จริง —
    # บน production ตัวเลขนี้คือ 116/1 เป๊ะตามที่ ADR-0015 A4-D2 ล็อกไว้
    expected_available = spec.expected_after["posters"] - 1
    available = await conn.fetchval(
        "SELECT count(*) FROM public.posters WHERE status = 'available'"
    )
    sold = await conn.fetchval(
        "SELECT count(*) FROM public.posters WHERE status = 'sold'"
    )
    if available != expected_available or sold != 1:
        raise BootstrapRefused(
            f"status หลังโหลดไม่ตรง: available={available} (ต้องการ {expected_available}) · "
            f"sold={sold} (ต้องการ 1)"
        )

    sold_at_rows = await conn.fetch(
        "SELECT id FROM public.posters WHERE sold_at IS NOT NULL"
    )
    sold_at_ids = sorted(str(r["id"]) for r in sold_at_rows)
    if sold_at_ids != [spec.sold_poster_id]:
        raise BootstrapRefused(
            f"sold_at IS NOT NULL ต้องมีแค่ {spec.sold_poster_id} แต่ได้ {sold_at_ids}"
        )

    orphan_images = await conn.fetchval(
        "SELECT count(*) FROM public.poster_images pi "
        "LEFT JOIN public.posters p ON p.id = pi.poster_id WHERE p.id IS NULL"
    )
    if orphan_images:
        raise BootstrapRefused(
            f"พบ poster_images กำพร้า (ไม่มี poster แม่) {orphan_images} แถว"
        )

    posters_without_images = await conn.fetchval(
        "SELECT count(*) FROM public.posters p "
        "LEFT JOIN public.poster_images pi ON pi.poster_id = p.id WHERE pi.id IS NULL"
    )
    if posters_without_images:
        raise BootstrapRefused(f"พบ posters ที่ไม่มีรูปเลย {posters_without_images} ใบ")

    readiness = await conn.fetchval(
        "SELECT count(*) FROM public.posters "
        "WHERE published_at IS NOT NULL AND verified_at IS NULL AND status <> 'sold'"
    )
    if readiness:
        raise BootstrapRefused(
            f"readiness query ของ ADR-0027 A3-D3 ไม่เป็น 0: {readiness} แถว"
        )


def _coerce_unwind_param(pg_type: str, raw_value: str | None) -> object:
    """asyncpg บังคับให้ชนิด Python ของ parameter ตรงกับ OID ที่มันรู้จักไว้ล่วงหน้า —
    ไม่ปล่อยให้ SQL `::cast` ในข้อความ query แปลงให้เหมือน driver อื่น

    🔴 **แก้ตาม code-critic รอบ 1 (High)** — docstring เดิมอ้างว่า "enum/numeric/
    smallint/integer/text ทุกตัวผ่านสบาย ไม่ต้องแปลงฝั่ง Python" ซึ่ง**เท็จ** critic
    พิสูจน์บน test DB จริงว่า `$1::smallint`/`$1::integer` กับพารามิเตอร์ที่เป็น
    Python `str` ได้ `asyncpg.exceptions.DataError: 'str' object cannot be
    interpreted as an integer` ทันที (มีแค่ enum/text เท่านั้นที่ asyncpg fallback
    ไปที่ "unknown"/text OID แล้วปล่อยให้ Postgres cast เองได้จริง) — `boolean`/
    `smallint`/`integer`/`numeric` ทั้งหมดมี OID ที่ asyncpg รู้จักแน่นอนล่วงหน้า
    จึงต้องแปลงชนิดฝั่ง Python **ก่อน**ส่งเสมอ ไม่พึ่ง fallback ของ driver เลย —
    `render_value()` ของ `scripts/seed/manual_entry.py`/`correction_entry.py` เขียน
    ทุกชนิดเป็นข้อความล้วน (`str(value)`) เสมอ ฟังก์ชันนี้จึงเป็นขาตรงข้ามที่แปลง
    ข้อความนั้นกลับเป็นชนิด Python ที่ asyncpg ต้องการต่อ pg_type
    """
    if raw_value is None:
        return None
    if pg_type == "boolean":
        return raw_value.strip().lower() in ("true", "t", "1", "yes", "y")
    if pg_type in ("smallint", "integer"):
        try:
            return int(raw_value)
        except ValueError as exc:
            raise BootstrapRefused(
                f"③ UNWIND: value_before {raw_value!r} แปลงเป็น {pg_type} ไม่ได้: {exc}"
            ) from exc
    if pg_type == "numeric":
        try:
            return Decimal(raw_value)
        except InvalidOperation as exc:
            raise BootstrapRefused(
                f"③ UNWIND: value_before {raw_value!r} แปลงเป็น numeric ไม่ได้: {exc}"
            ) from exc
    # enum (poster_condition/poster_type/restoration_status/size_format) และ text —
    # asyncpg fallback ไปที่ "unknown"/text OID แล้วปล่อยให้ Postgres cast เองได้จริง
    # (พิสูจน์แล้ว — ต่างจากสามชนิดข้างบน)
    return raw_value


async def run_bootstrap(
    conn: "asyncpg.Connection",
    spec: BootstrapSpec,
    insert_script: str,
    columns_by_table: dict[str, tuple[str, ...]],
) -> BootstrapReport:
    """①–⑤ ของ A4-D2 — **รับ connection ที่เปิดทรานแซกชันไว้แล้วจากผู้เรียก** ไม่คุม
    BEGIN/COMMIT/ROLLBACK เอง (`main()`/เทส เป็นคนเปิด `conn.transaction()` เองแล้ว
    ตัดสินใจ commit/rollback จากผลของฟังก์ชันนี้)
    """
    # ด่าน 8 — precondition (ต้องมาก่อน INSERT แรกเสมอ)
    await _assert_preconditions(conn, spec)

    # A4-D2 (2) — เทียบ column set กับตารางจริงก่อน INSERT แรก
    for table, columns in columns_by_table.items():
        await _assert_columns_match_table(conn, table, columns)

    # ① INSERT ทั้งไฟล์เป็น script เดียว — simple-query protocol (ไม่มี args)
    await conn.execute(insert_script)

    rows_loaded = {
        table: await conn.fetchval(f"SELECT count(*) FROM public.{table}")
        for table in REQUIRED_TABLES
    }

    # ② RESET 4 ใบใน UPDATE เดียว (กันจังหวะที่ published_at ยังอยู่แต่ verified_at
    # หายไปแล้ว — ถ้าแยกสอง UPDATE จะชน CHECK กลางทาง)
    reset_tag = await conn.execute(
        "UPDATE public.posters SET status = 'available', published_at = NULL, "
        "verified_at = NULL, sold_at = NULL WHERE id = ANY($1::uuid[])",
        list(spec.cleared_poster_ids),
    )
    _assert_rowcount(reset_tag, len(spec.cleared_poster_ids), "RESET ②")

    # ③ UNWIND ค่าอื่นที่ session 16 ก.ย. เขียนลง posters — LIFO (created_at DESC, id DESC)
    unwind_rows = await conn.fetch(
        "SELECT poster_id, field, value_before FROM public.poster_attribute_reviews "
        "WHERE (source = $1 OR (source = $2 AND reviewed_at >= $3 AND reviewed_at < $4)) "
        "AND field NOT IN ('published_at', 'verified_at') "
        "ORDER BY created_at DESC, id DESC",
        spec.p2_source,
        spec.p3_source,
        spec.p3_window_start,
        spec.p3_window_end,
    )
    for row in unwind_rows:
        field_name = row["field"]
        pg_type = spec.unwind_pg_types.get(field_name)
        if pg_type is None:
            raise BootstrapRefused(
                f"③ UNWIND เจอฟิลด์ {field_name!r} (poster {row['poster_id']}) ที่ไม่อยู่ใน "
                "UNWIND_FIELDS ของ BootstrapSpec — ปฏิเสธทั้งชุด (ADR-0015 A4-D2 ③)"
            )
        await conn.execute(
            f"UPDATE public.posters SET {field_name} = $1::{pg_type} WHERE id = $2::uuid",
            _coerce_unwind_param(pg_type, row["value_before"]),
            row["poster_id"],
        )
    rows_unwound = len(unwind_rows)

    # ④ DELETE ตาม predicate — rowcount ต้องเท่าตัวเลขที่ล็อก (P4 WITHDRAW **ไม่ลบ** —
    # OD-1 ปิดแล้ว: ย้ายทั้ง 115 แถว ไม่มี --drop-withdraw-history ในสคริปต์นี้)
    p1_tag = await conn.execute(
        "DELETE FROM public.poster_attribute_reviews WHERE source = ANY($1::text[])",
        list(spec.p1_source_values),
    )
    _assert_rowcount(
        p1_tag, spec.p1_expected, "DELETE P1 (poster_service.py/order_service.py)"
    )

    p2_tag = await conn.execute(
        "DELETE FROM public.poster_attribute_reviews WHERE source = $1", spec.p2_source
    )
    _assert_rowcount(
        p2_tag, spec.p2_expected, "DELETE P2 (correction-entry-sit-20260916.csv)"
    )

    p3_tag = await conn.execute(
        "DELETE FROM public.poster_attribute_reviews "
        "WHERE source = $1 AND reviewed_at >= $2 AND reviewed_at < $3",
        spec.p3_source,
        spec.p3_window_start,
        spec.p3_window_end,
    )
    _assert_rowcount(p3_tag, spec.p3_expected, "DELETE P3 (manual-entry.csv 16 ก.ย.)")

    # ⑤ ASSERT หลังโหลด — ชื่อชัด (A4-D9 ข้อ 3) ไม่ผ่านข้อใด = ROLLBACK ทั้งชุด
    await assert_no_test_stock_state(conn, spec)
    await assert_no_signature_carried(conn, spec)
    await _assert_row_shape(conn, spec)

    rows_after = {
        table: await conn.fetchval(f"SELECT count(*) FROM public.{table}")
        for table in (*REQUIRED_TABLES, "poster_splits")
    }

    return BootstrapReport(
        rows_loaded=rows_loaded,
        rows_deleted={
            "P1_service": _rowcount(p1_tag),
            "P2_correction_20260916": _rowcount(p2_tag),
            "P3_manual_20260916": _rowcount(p3_tag),
            "P4_withdraw_20260830": 0,
        },
        rows_unwound=rows_unwound,
        rows_after=rows_after,
    )


# ════════════════════════════════════════════════════════════════════════
# main() — ด่าน 1–7 แล้วเปิด connection สำหรับด่าน 8–9 · marker/audit
# ════════════════════════════════════════════════════════════════════════


def _marker_path() -> Path:
    audit_dir = os.environ.get("OPS_AUDIT_DIR", "")
    if not audit_dir:
        raise PrecheckError(
            "OPS_AUDIT_DIR ไม่ได้ตั้งในสภาพแวดล้อมนี้ — หา marker ไม่ได้"
        )
    return Path(audit_dir) / MARKER_FILENAME


def _asyncpg_dsn() -> str:
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    url = make_url(settings.DATABASE_URL)
    # asyncpg.connect() รับ DSN แบบ postgresql:// ธรรมดา ไม่ใช่ postgresql+asyncpg://
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def open_connection() -> "asyncpg.Connection":
    """จุดเดียวที่เปิด raw connection สำหรับทรานแซกชันที่โหลดข้อมูล — แยกเป็นฟังก์ชัน
    เพื่อให้เทส monkeypatch ได้ตรง ๆ ว่า "มี marker ⇒ ห้ามถูกเรียกเด็ดขาด"
    """
    import asyncpg

    return await asyncpg.connect(_asyncpg_dsn())


def _print_report(
    report: BootstrapReport, *, commit: bool, dump_sha256: str, image_tag: str
) -> None:
    mode = "COMMIT" if commit else "DRY-RUN (ROLLBACK)"
    print(f"=== catalog-bootstrap [{mode}] ===")
    print(f"dump-sha256: {dump_sha256}")
    print(f"image-tag:   {image_tag}")
    print(f"rows_loaded (ก่อนล้าง): {report.rows_loaded}")
    print(
        f"cleared_poster_ids ({len(PRODUCTION_SPEC.cleared_poster_ids)}): "
        f"{list(PRODUCTION_SPEC.cleared_poster_ids)}"
    )
    print(f"kept_sold_poster_id: {PRODUCTION_SPEC.sold_poster_id}")
    print(f"rows_unwound: {report.rows_unwound}")
    print(f"rows_deleted: {report.rows_deleted}")
    print(f"rows_after (หลังล้าง+assert): {report.rows_after}")
    if not commit:
        print("dry-run เท่านั้น — ROLLBACK แล้ว ไม่มีอะไรถูกเขียนจริง")


def _audit_record(
    *,
    phase: str,
    actor_user_id: Any,
    file_name: str,
    file_sha256: str,
    image_tag: str,
    backup_ref: str | None,
    ran_at: datetime,
    report: BootstrapReport | None = None,
    error: str | None = None,
    marker_written: bool | None = None,
) -> dict[str, Any]:
    """🔴 ห้ามมี email / URL / ค่าที่เขียน (security-baseline §2) — ทรงเดียวกับ
    `_production_gate.audit_record()` แต่คีย์ต่างกัน (`rows_*`/`cleared_*` เป็นของ
    สคริปต์นี้โดยเฉพาะ ตาม ADR-0015 A4-D4)"""
    record: dict[str, Any] = {
        "phase": phase,
        "lane": LANE_NAME,
        "target": TARGET_NAME,
        "file_name": file_name,
        "file_sha256": file_sha256,
        "alembic_version": PRODUCTION_SPEC.alembic_head,
        "actor_user_id": str(actor_user_id),
        "ran_at": ran_at.isoformat(),
        "hostname": socket.gethostname(),
        "image_tag": image_tag,
        "backup_ref": backup_ref,
    }
    if report is not None:
        record["rows_loaded"] = report.rows_loaded
        record["rows_deleted"] = report.rows_deleted
        record["rows_unwound"] = report.rows_unwound
        record["cleared_poster_ids"] = list(PRODUCTION_SPEC.cleared_poster_ids)
        record["kept_sold_poster_id"] = PRODUCTION_SPEC.sold_poster_id
        record["rows_after"] = report.rows_after
    if error is not None:
        record["error"] = error
    if marker_written is False:
        record["marker_written"] = False
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--actor",
        required=True,
        metavar="<อีเมลแอดมิน google-only>",
        help="ผู้สั่งการ (A4-D1 ด่าน 3) — บังคับเสมอ ไม่มี default",
    )
    parser.add_argument(
        "--dump",
        required=True,
        type=Path,
        metavar="<path>",
        help="ไฟล์ dump ของ SIT (`pg_dump --data-only --inserts --column-inserts` "
        "ผ่าน `grep -E '^INSERT INTO'` แล้ว — ดู runbook)",
    )
    parser.add_argument(
        "--audit-log",
        required=True,
        type=Path,
        metavar="<path ใต้ OPS_AUDIT_DIR>",
        help="A4-D1 ด่าน 5",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="เขียนจริง (ไม่ใส่ = dry-run: ทำครบทุกขั้นแล้ว ROLLBACK)",
    )
    parser.add_argument(
        "--dump-sha256",
        default=None,
        metavar="<hex>",
        help="บังคับตอน --commit — ต้องตรงกับ sha256 ของไฟล์ --dump ของรอบนี้ "
        "(กันสลับไฟล์ระหว่าง dry-run กับ commit — ทรง plan-hash ของ A3-D3 ④)",
    )
    parser.add_argument(
        "--backup-ref",
        default=None,
        type=Path,
        metavar="<path ใต้ OPS_BACKUP_DIR>",
        help="บังคับตอน --commit (A4-D1 ด่าน 6)",
    )
    return parser


async def _run_main(args: argparse.Namespace) -> int:
    # ด่าน 1 — marker (ก่อนเปิด connection ใด ๆ ทั้งสิ้น)
    marker_path = _marker_path()
    if marker_path.exists():
        raise MarkerAlreadyExists(
            "catalog-bootstrap เคยรันสำเร็จมาแล้วบน environment นี้ — marker: "
            f"{marker_path}\n--- เนื้อ marker ---\n"
            f"{marker_path.read_text(encoding='utf-8')}\n"
            "ลบไฟล์นี้เพื่อรันซ้ำ = ต้องมี ADR-0015 amendment ใหม่ก่อนเสมอ"
        )

    # ด่าน 2
    assert_environment_matches(TARGET_NAME)

    # อ่าน + ตรวจ dump ก่อนแตะ connection ใด ๆ เพิ่มเติม (A4-D9 ข้อ 2)
    dump_bytes = args.dump.read_bytes()
    dump_sha256 = hashlib.sha256(dump_bytes).hexdigest()
    if args.commit and args.dump_sha256 != dump_sha256:
        raise PrecheckError(
            f"--dump-sha256 ({args.dump_sha256}) ไม่ตรงกับ sha256 จริงของไฟล์ --dump "
            f"ของรอบนี้ ({dump_sha256}) — ไฟล์เปลี่ยนไปตั้งแต่ dry-run รอบล่าสุด "
            "รัน dry-run ใหม่แล้วคัด sha256 ที่พิมพ์ออกมา"
        )
    dump_text = dump_bytes.decode("utf-8")
    insert_script, columns_by_table = validate_dump_allowlist(dump_text)

    # ด่าน 3 — actor (session อ่านอย่างเดียว แยกจากทรานแซกชันที่โหลดข้อมูล)
    from app.core.database import async_session_maker

    async with async_session_maker() as session:
        actor = await resolve_admin_actor(session, args.actor, require_google_only=True)

    # ด่าน 4 — TOTP (ทั้ง dry-run และ commit)
    audit_dir = Path(os.environ["OPS_AUDIT_DIR"])
    _verify_totp(audit_dir=audit_dir)

    # ด่าน 5 — audit-log ถาวรและเขียนได้จริง
    assert_audit_path_is_persistent(args.audit_log)

    # ด่าน 6 — backup-ref สด (commit เท่านั้น)
    now = datetime.now(timezone.utc)
    if args.commit:
        assert_backup_ref(args.backup_ref, now=now)

    # ด่าน 7 — scripts/ ตรง sha กับ image
    image_tag = assert_scripts_match_image()

    if args.commit:
        confirm_target_interactively(TARGET_NAME)
        intent_record = _audit_record(
            phase="intent",
            actor_user_id=actor.id,
            file_name=args.dump.name,
            file_sha256=dump_sha256,
            image_tag=image_tag,
            backup_ref=str(args.backup_ref),
            ran_at=now,
        )
        # ADR-0031 D6-b — เขียน audit ไม่ได้ = ไม่แตะ DB เลย (AuditWriteFailed จะ
        # propagate ออกจากตรงนี้ก่อนเปิด connection ด้านล่าง)
        append_audit_line(args.audit_log, intent_record)

    conn = await open_connection()
    report: BootstrapReport | None = None
    try:
        tx = conn.transaction()
        await tx.start()
        try:
            report = await run_bootstrap(
                conn, PRODUCTION_SPEC, insert_script, columns_by_table
            )
        except Exception as exc:
            await tx.rollback()
            if args.commit:
                try:
                    append_audit_line(
                        args.audit_log,
                        _audit_record(
                            phase="failed",
                            actor_user_id=actor.id,
                            file_name=args.dump.name,
                            file_sha256=dump_sha256,
                            image_tag=image_tag,
                            backup_ref=(
                                str(args.backup_ref) if args.backup_ref else None
                            ),
                            ran_at=datetime.now(timezone.utc),
                            error=type(exc).__name__,
                        ),
                    )
                except AuditWriteFailed as audit_exc:
                    # เขียน audit "failed" เองก็ล้ม — ต้องเห็น**ทั้งสอง**ข้อความ ไม่ใช่
                    # แค่ตัวหลังที่บังสาเหตุเดิมไว้ (ROLLBACK ทำไปแล้วข้างบน — DB
                    # ปลอดภัย แต่ operator ต้องรู้ทั้งสองสาเหตุพร้อมกัน)
                    print(
                        f"🔴 การโหลดล้มเหลว ({type(exc).__name__}: {exc}) และเขียน "
                        f"audit 'failed' ก็ไม่สำเร็จด้วย ({audit_exc}) — DB ถูก "
                        "ROLLBACK แล้ว ไม่มีผลข้างเคียง แต่ไม่มีร่องรอยลง audit log",
                        file=sys.stderr,
                    )
                    raise
            raise
        else:
            if args.commit:
                await tx.commit()
            else:
                await tx.rollback()
    finally:
        await conn.close()

    assert report is not None
    _print_report(
        report, commit=args.commit, dump_sha256=dump_sha256, image_tag=image_tag
    )

    if args.commit:
        marker_written = True
        committed_record = _audit_record(
            phase="committed",
            actor_user_id=actor.id,
            file_name=args.dump.name,
            file_sha256=dump_sha256,
            image_tag=image_tag,
            backup_ref=str(args.backup_ref),
            ran_at=datetime.now(timezone.utc),
            report=report,
        )
        try:
            with marker_path.open("x", encoding="utf-8") as fh:
                fh.write(json.dumps(committed_record, ensure_ascii=False) + "\n")
                fh.write(
                    "ลบไฟล์นี้เพื่อรันซ้ำ catalog-bootstrap = ต้องมี ADR-0015 "
                    "amendment ใหม่ก่อนเสมอ (ADR-0015 A4-D1 AC-1 (6))\n"
                )
        except OSError as exc:
            marker_written = False
            print(
                f"🔴 COMMIT สำเร็จแล้ว แต่เขียน marker ไม่สำเร็จ: {exc}\n"
                "สร้าง marker ด้วยมือจากบรรทัด audit 'committed' ต่อไปนี้ก่อนใครมารันซ้ำ "
                "(ดู runbook §ถ้าต้องถอย)",
                file=sys.stderr,
            )
        if not marker_written:
            committed_record = _audit_record(
                phase="committed",
                actor_user_id=actor.id,
                file_name=args.dump.name,
                file_sha256=dump_sha256,
                image_tag=image_tag,
                backup_ref=str(args.backup_ref),
                ran_at=datetime.now(timezone.utc),
                report=report,
                marker_written=False,
            )
        append_audit_line(args.audit_log, committed_record)
        if not marker_written:
            return 3

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.commit and not args.dump_sha256:
        parser.error("--commit ต้องระบุ --dump-sha256 ด้วย (กันสลับไฟล์ระหว่างรอบ)")
    if args.commit and not args.backup_ref:
        parser.error("--commit ต้องระบุ --backup-ref ด้วย (A4-D1 ด่าน 6)")

    try:
        return asyncio.run(_run_main(args))
    except MarkerAlreadyExists as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except AuditWriteFailed as exc:
        # code-critic รอบ 1 (Low) — เดิมไม่มีด่านนี้ ⇒ traceback ดิบหลุดถึงผู้ใช้แทน
        # ข้อความอ่านได้ (ADR-0031 D6-b: เขียนร่องรอยไม่ได้ = ไม่แตะ DB — ที่แตะไปแล้ว
        # ก่อนหน้านี้ถ้ามีคือ intent เท่านั้น ไม่ใช่การโหลดจริง)
        print(f"เขียน audit log ไม่สำเร็จ: {exc}", file=sys.stderr)
        return 4
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
