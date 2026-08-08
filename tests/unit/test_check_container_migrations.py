"""`scripts/check_container_migrations.py` — ด่านที่ทำให้ image เก่าล้มเสียงดัง (**BL-88**)

เทสอยู่กับ `diagnose()` และตัว parser ซึ่งเป็น pure ล้วน — ไม่แตะ docker ไม่แตะ alembic
· ส่วน IO (เรียก `docker exec`) พิสูจน์ด้วยการรันจริงกับคอนเทนเนอร์ SIT ไม่ใช่ด้วยเทส
(ดู §"สิ่งที่เทสนี้พิสูจน์ไม่ได้" ท้ายไฟล์)
"""

from __future__ import annotations

import pytest

from scripts.check_container_migrations import (
    Side,
    diagnose,
    parse_heads,
    parse_revisions,
)

# ตัวอย่างจริงจาก `alembic history` ของ repo นี้ (2026-08-08) — ไม่ใช่ข้อความสมมติ
# 🔴 เลือกสามแถวนี้เพราะข้อความ commit **มีทั้ง `->` และ `,` ปนอยู่ในตัวมันเอง**
# ซึ่งเป็นจุดที่ parser แบบ split ทั้งบรรทัดจะพัง
REAL_HISTORY = """\
a7c31e5f9b04 -> f4c8a1e07b93 (head), verification: enum เหลือ 2 ค่า + verification_note → reference_note (ADR-0014 D21/D22)
4f0b6c2ad713 -> a7c31e5f9b04, verification_status: ARTWORK_MATCHED + NO_REFERENCE_FOUND (ADR-0014 D12/D13)
d1a7c9e04b62 -> 4f0b6c2ad713, posters verification model — 3 คอลัมน์ + enum verification_status (ADR-0014)
"""


def _side(revs: set[str], heads: set[str]) -> Side:
    return Side(revisions=revs, heads=heads)


# --- parser ---


def test_history_parser_reads_the_child_revision_not_the_parent() -> None:
    """แต่ละบรรทัดคือ `<พ่อ> -> <ลูก>` — ที่ต้องเก็บคือ **ลูก**

    ถ้าเก็บผิดฝั่ง เซตจะเลื่อนไปหนึ่งขั้นทั้งชุด แล้วการเทียบสองฝั่งจะยังดู "ต่างกัน
    หนึ่งตัว" เหมือนเดิม — ผิดแบบที่ยังดูสมเหตุสมผล
    """
    assert parse_revisions(REAL_HISTORY) == {
        "f4c8a1e07b93",
        "a7c31e5f9b04",
        "4f0b6c2ad713",
    }
    assert "d1a7c9e04b62" not in parse_revisions(REAL_HISTORY)


def test_history_parser_survives_arrows_and_commas_inside_thai_commit_messages() -> (
    None
):
    """🔴 ข้อความ commit ของโปรเจกต์นี้มี `→` และ `,` ปนจริง

    `verification_note → reference_note (ADR-0014 D21/D22)` — split ทั้งบรรทัดด้วย
    `->` หรือ `,` จะกลืนคำในข้อความมาเป็น revision id · ตัดที่คอมมาแรกก่อนเสมอ
    """
    revisions = parse_revisions(REAL_HISTORY)
    assert all(len(r) == 12 and r.isalnum() for r in revisions), revisions


def test_history_parser_handles_the_base_row_that_has_no_arrow() -> None:
    assert parse_revisions("5464b7ff3fbc, init F1-F3 schema\n") == {"5464b7ff3fbc"}


def test_heads_parser_of_an_unmigrated_database_is_empty_not_a_match() -> None:
    """🔴 `alembic current` ของ DB เปล่าไม่พิมพ์อะไรเลย

    ถ้า parser คืนอะไรที่ไม่ใช่เซตว่าง หรือ `diagnose()` ตีความว่า "ไม่มีอะไรต่าง"
    DB ที่ยังไม่ migrate เลยจะผ่านด่านนี้ไปได้
    """
    assert parse_heads("") == set()
    assert parse_heads("\n  \n") == set()
    assert parse_heads("f4c8a1e07b93 (head)\n") == {"f4c8a1e07b93"}


# --- diagnose: อาการที่ BL-88 มีไว้จับ ---


def test_image_older_than_code_is_the_headline_case() -> None:
    """🔴 เคสของ BL-88 เป๊ะ — `alembic upgrade head` ในคอนเทนเนอร์จะ exit 0 เงียบ ๆ

    ยืนยันกับของจริงแล้ว 2026-08-08: วาง migration `c5a8f31e64d7` ลง repo โดย image
    ของ SIT ยังเป็นของเก่า → `docker exec ... alembic upgrade head` **exit 0**
    ไม่มี error ไม่มี warning · ด่านนี้คือสิ่งเดียวที่พูดออกมา
    """
    verdict = diagnose(
        repo=_side({"a", "b", "c"}, {"c"}),
        image=_side({"a", "b"}, {"b"}),
        db_current={"b"},
    )
    assert not verdict.ok
    assert verdict.code == "IMAGE_BEHIND_CODE"
    # ต้องบอก *ชื่อ revision ที่ขาด* ไม่ใช่แค่ว่า "ไม่ตรง" — คนอ่านต้องรู้ว่าจะไปหาอะไร
    assert "c" in verdict.message


def test_db_matching_a_stale_image_head_must_not_be_reported_as_ok() -> None:
    """🔴 กับดักที่อันตรายที่สุด — DB ตรงกับ head ของ image ที่ *เก่า*

    ทั้งสองฝั่งในคอนเทนเนอร์ตรงกันเป๊ะ (`current == heads`) ซึ่งเป็นสิ่งที่คนใช้ตัดสิน
    ว่า "migrate ครบแล้ว" · ถ้า `diagnose()` เช็ค DB ก่อน image มันจะตอบ OK
    ให้กับสถานะที่ผิด — ลำดับการเช็คจึงเป็นส่วนหนึ่งของความถูกต้อง ไม่ใช่สไตล์
    """
    verdict = diagnose(
        repo=_side({"a", "b", "c"}, {"c"}),
        image=_side({"a", "b"}, {"b"}),
        db_current={"b"},  # ← ตรงกับ image เป๊ะ
    )
    assert verdict.code == "IMAGE_BEHIND_CODE"


def test_image_newer_than_checked_out_code_is_its_own_symptom() -> None:
    """deploy ของเก่าทับของใหม่ — คนละทางแก้กับ IMAGE_BEHIND_CODE จึงต้องแยกรหัส"""
    verdict = diagnose(
        repo=_side({"a", "b"}, {"b"}),
        image=_side({"a", "b", "c"}, {"c"}),
        db_current={"c"},
    )
    assert not verdict.ok
    assert verdict.code == "IMAGE_AHEAD_OF_CODE"


def test_two_sided_difference_is_reported_as_diverged_not_as_behind() -> None:
    """rebase/merge ที่เขียน migration ทับกัน — "เก่ากว่า" อธิบายมันไม่ได้"""
    verdict = diagnose(
        repo=_side({"a", "b"}, {"b"}),
        image=_side({"a", "z"}, {"z"}),
        db_current={"z"},
    )
    assert verdict.code == "DIVERGED"


def test_database_ahead_of_image_is_flagged_as_dangerous_not_as_behind() -> None:
    """DB ถูก migrate ด้วยโค้ดใหม่กว่า image ที่กำลังจะรัน = ถอยโค้ดโดยไม่ถอย schema

    ต้องไม่แนะนำให้ downgrade (CLAUDE.md ห้ามอยู่แล้ว) — ข้อความต้องชี้ไปทาง
    "deploy image ที่ตรงกับ DB" แทน
    """
    verdict = diagnose(
        repo=_side({"a", "b"}, {"b"}),
        image=_side({"a", "b"}, {"b"}),
        db_current={"c"},
    )
    assert verdict.code == "DB_AHEAD_OF_IMAGE"
    assert "downgrade" in verdict.message


def test_empty_database_is_not_silently_ok() -> None:
    verdict = diagnose(
        repo=_side({"a"}, {"a"}), image=_side({"a"}, {"a"}), db_current=set()
    )
    assert verdict.code == "DB_NOT_MIGRATED"


def test_database_behind_a_correct_image_points_at_the_container_logs() -> None:
    verdict = diagnose(
        repo=_side({"a", "b"}, {"b"}),
        image=_side({"a", "b"}, {"b"}),
        db_current={"a"},
    )
    assert verdict.code == "DB_BEHIND_IMAGE"


def test_container_without_any_migration_files_is_caught_first() -> None:
    """image build ผิด (ลืม COPY alembic/) หรือชี้คอนเทนเนอร์ผิดตัว

    ต้องจับก่อนทุกข้อ — ไม่งั้นจะไปโผล่เป็น `IMAGE_BEHIND_CODE` ซึ่งชี้ทางแก้ผิด
    (บอกให้ rebuild ทั้งที่ปัญหาคือชี้ผิดตัว)
    """
    verdict = diagnose(
        repo=_side({"a"}, {"a"}), image=_side(set(), set()), db_current=set()
    )
    assert verdict.code == "IMAGE_HAS_NO_MIGRATIONS"


def test_everything_lined_up_is_the_only_way_to_pass() -> None:
    verdict = diagnose(
        repo=_side({"a", "b"}, {"b"}),
        image=_side({"a", "b"}, {"b"}),
        db_current={"b"},
    )
    assert verdict.ok
    assert verdict.code == "OK"


@pytest.mark.parametrize(
    ("repo", "image", "db"),
    [
        ({"a", "b", "c"}, {"a", "b"}, {"b"}),  # image เก่า
        ({"a", "b"}, {"a", "b", "c"}, {"c"}),  # image ใหม่
        ({"a", "b"}, {"a", "z"}, {"z"}),  # คนละสาย
        ({"a", "b"}, {"a", "b"}, {"c"}),  # DB อยู่หน้า
        ({"a", "b"}, {"a", "b"}, set()),  # DB เปล่า
        ({"a", "b"}, {"a", "b"}, {"a"}),  # DB ตามไม่ทัน
        ({"a"}, set(), set()),  # image ไม่มี migration
    ],
)
def test_no_broken_shape_ever_reports_ok(
    repo: set[str], image: set[str], db: set[str]
) -> None:
    """closed-world ของ "ผ่าน" — ทุกอาการที่รู้จักต้องไม่ผ่าน

    เขียนคู่กับเทสรายตัวข้างบนโดยตั้งใจ: เทสรายตัวล็อก *รหัสอาการ* (ถ้ารหัสเปลี่ยน
    ข้อความแนะนำจะผิด) ส่วนข้อนี้ล็อก *ผลผ่าน/ไม่ผ่าน* ซึ่งเป็นสิ่งที่ deploy.sh ใช้จริง
    — การเปลี่ยนชื่อรหัสไม่ควรทำให้ด่านเปิด
    """
    heads_of = lambda s: {sorted(s)[-1]} if s else set()  # noqa: E731
    verdict = diagnose(_side(repo, heads_of(repo)), _side(image, heads_of(image)), db)
    assert not verdict.ok, verdict


# --- สิ่งที่เทสนี้พิสูจน์ไม่ได้ (skill `test-quality` §5) ---
#
# เทสทั้งไฟล์ทำงานกับ `diagnose()` และ parser เท่านั้น · สิ่งที่ **พิสูจน์ด้วยเทสไม่ได้**
# และต้องพิสูจน์ด้วยการรันจริง:
#   · `docker exec` เรียกถูกคอนเทนเนอร์และอ่าน stdout ได้จริง
#   · `alembic history/heads` บน host ไม่ต้องการ env/DB (ยืนยันแล้ว: `env -i` ยังได้ผลถูก)
#   · `--wait` รอ `CMD` ของคอนเทนเนอร์จริง ๆ
# ทั้งหมดรันจริงกับ `posternung-sit-app` เมื่อ 2026-08-08 แล้ว — ทั้งเคสผ่าน (exit 0)
# และเคส IMAGE_BEHIND_CODE (exit 1) โดยวางไฟล์ migration ของอีก branch ลง repo ชั่วคราว
