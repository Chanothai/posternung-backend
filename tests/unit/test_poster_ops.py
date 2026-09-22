"""ประตูเดียวของเส้นทางข้อมูลโปสเตอร์ — `scripts/seed/poster_ops.py` (INF-26)

สิ่งที่ต้องล็อกไว้ที่นี่มีสองเรื่องเท่านั้น เพราะไฟล์นั้นตั้งใจไม่มีตรรกะอย่างอื่นเลย:

1. **มันไม่รู้จัก argument ของเส้นไหน** — argv หลัง `<lane> <action>` ต้องถึงสคริปต์ลูก
   **ครบทั้งก้อนโดยไม่ถูกตีความ** (AC-3) · dispatcher ที่ประกาศ argument เองคือแหล่ง
   ความจริงที่สองที่ drift ทันทีที่เส้นใดเพิ่ม flag
2. **แผนที่ของมันเป็น closed-world** — สคริปต์ทุกตัวใน `scripts/seed/` ต้องอยู่ในแผนที่
   หรืออยู่ในเซตยกเว้นที่มีเหตุผลกำกับ อย่างใดอย่างหนึ่ง (AC-5) ⇒ เส้นที่ 8 ที่เพิ่ม
   วันหน้าทำให้เทสนี้แดง ไม่ใช่หายเงียบ

🔴 **เทสที่รันจริงใช้สคริปต์ปลอมใน `tmp_path` ไม่ใช่สคริปต์ของเส้นจริง** — เส้นจริง
แตะ DB และมีด่าน env ของตัวเอง การเรียกมันในเทสจะเป็นการทดสอบเส้นนั้น ไม่ใช่ทดสอบ
ประตู · สิ่งที่ประตูรับผิดชอบมีแค่ "argv ถึงไหม" กับ "exit code กลับมาไหม" ซึ่งพิสูจน์
กับสคริปต์ปลอมได้ตรงกว่าและไม่ผูกกับสถานะของ DB
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.seed import poster_ops

SEED_DIR = Path(poster_ops.__file__).resolve().parent

# สคริปต์ปลอมที่พิมพ์ argv ที่ได้รับออก stdout แล้วจบด้วย exit code ที่สั่งผ่าน env —
# ใช้พิสูจน์ทั้ง AC-3 (argv ถึงครบ) และ AC-4 (exit code ทะลุ) ด้วยการรันจริง
STUB = """
import json, os, sys
print(json.dumps(sys.argv[1:]))
sys.exit(int(os.environ.get("STUB_RC", "0")))
"""


@pytest.fixture
def stub_lane(tmp_path, monkeypatch):
    """ชี้ `SEED_DIR` ของประตูไปที่โฟลเดอร์ชั่วคราวที่มีสคริปต์ปลอมชื่อเดียวกับเส้นจริง

    ไม่แตะ `LANES` เลยโดยตั้งใจ — แผนที่ที่ถูกทดสอบยังเป็นตัวจริง เปลี่ยนแค่ว่าไฟล์
    ปลายทางอยู่ที่ไหน ⇒ ถ้าใครแก้ชื่อไฟล์ใน `LANES` เทสกลุ่มนี้จะพังตาม ซึ่งถูกแล้ว
    """
    for lane in poster_ops.LANES.values():
        for script in lane.scripts.values():
            (tmp_path / script).write_text(STUB, encoding="utf-8")
    monkeypatch.setattr(poster_ops, "SEED_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------- AC-3 · AC-4


def test_everything_after_the_action_reaches_the_child_untouched(
    stub_lane, capfd
) -> None:
    """🔴 ตัวฆ่า mutation หลักของ AC-3 — ถ้าประตูเริ่มตีความ argv เทสนี้ต้องแดง

    ชุดที่ส่งเข้าไปจงใจมีของที่ `argparse` ชอบกลืน: flag ที่ประตูไม่รู้จัก · ค่าที่ขึ้นต้น
    ด้วย `-` · `--` · และ `--help` ซึ่งถ้าประตูดักเองจะไม่มีวันถึงลูก
    """
    passthrough = [
        "--commit",
        "--target",
        "sit",
        "--flag-ที่ประตูไม่รู้จัก",
        "--reason",
        "-ค่าที่ขึ้นต้นด้วยขีด",
        "--",
        "--help",
    ]
    assert poster_ops.main(["manual", "apply", *passthrough]) == 0

    received = capfd.readouterr().out.strip().splitlines()[-1]
    assert received == json.dumps(
        passthrough
    ), "argv ที่ลูกได้รับไม่ตรงกับที่ผู้ใช้พิมพ์ — ประตูตีความบางตัวไปแล้ว"


def test_the_child_script_that_runs_is_the_one_the_map_names(stub_lane, capfd) -> None:
    """ประตูต้องเรียกไฟล์ตามแผนที่ ไม่ใช่เดาจากชื่อ lane"""
    poster_ops.main(["correction", "sheet"])
    capfd.readouterr()
    # สคริปต์ปลอมของ correction/sheet มีอยู่จริงใน tmp — ยืนยันชื่อไฟล์ที่แผนที่ชี้
    assert poster_ops.LANES["correction"].sheet == "make_correction_sheet.py"
    assert (stub_lane / "make_correction_sheet.py").is_file()


@pytest.mark.parametrize("code", ["0", "1", "3"])
def test_the_exit_code_of_the_child_passes_straight_through(
    stub_lane, monkeypatch, capfd, code
) -> None:
    """AC-4 — รวม exit code ที่ไม่ใช่ 0/1 ซึ่งเป็นรูปที่ `returncode != 0 → 1` จะกลืนหาย"""
    monkeypatch.setenv("STUB_RC", code)
    assert poster_ops.main(["split", "apply"]) == int(code)
    capfd.readouterr()


# ---------------------------------------------------------------- AC-1 · AC-5


def test_every_script_in_the_map_exists_on_disk() -> None:
    """AC-1 — แผนที่ที่ชี้ไปไฟล์ที่ไม่มีอยู่จริงคือ `--help` ที่โกหกคนอ่าน"""
    missing = [
        script
        for lane in poster_ops.LANES.values()
        for script in lane.scripts.values()
        if not (SEED_DIR / script).is_file()
    ]
    assert missing == [], f"แผนที่ชี้ไปไฟล์ที่ไม่มีอยู่จริง: {missing}"


def test_the_map_and_the_exclusion_list_together_cover_every_script() -> None:
    """🔴 closed-world ของ AC-5 — assert **ความเท่ากันของเซต** ไม่ใช่ subset

    เส้นที่ 8 ที่เพิ่มวันหน้าจะโผล่ที่ฝั่ง `on_disk` ทันทีและไม่มีที่อยู่ทั้งสองฝั่ง ⇒ แดง
    · การลบสคริปต์ทิ้งโดยลืมถอนออกจากแผนที่ก็แดงเหมือนกัน (ฝั่งตรงข้าม)
    """
    on_disk = {path.name for path in SEED_DIR.glob("*.py")}
    mapped = {
        script for lane in poster_ops.LANES.values() for script in lane.scripts.values()
    }
    accounted = mapped | set(poster_ops.EXCLUDED)
    assert on_disk == accounted, (
        f"สคริปต์ที่ไม่มีที่อยู่ทั้งในแผนที่และในเซตยกเว้น: {sorted(on_disk - accounted)} · "
        f"อยู่ในแผนที่/เซตยกเว้นแต่ไม่มีไฟล์แล้ว: {sorted(accounted - on_disk)}"
    )


def test_the_map_covers_all_lanes_in_order() -> None:
    """`README.md` §5 — แผนที่ที่ตกไปหนึ่งเส้นจะ `--help` ครบดูดีแต่เรียกเส้นนั้นไม่ได้

    ‹2026-08-16› เจ็ด → แปด · เส้นที่ 8 = นำเข้ารูปจากโฟลเดอร์ (ADR-0026 D10 · INF-27)
    """
    assert [lane.number for lane in poster_ops.LANES.values()] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
    ]


def test_only_the_sold_lane_has_no_sheet() -> None:
    """ADR-0025 OD-3 — เส้นที่ 7 เป็นเส้นเดียวที่ไม่มีใบงาน CSV (argument ต่อใบ)

    assertion เชิงลบคู่กับเชิงบวก: เส้นอื่น**ต้องมี** sheet ครบทุกเส้น ไม่ใช่แค่
    "sold ไม่มี" ซึ่งยังเขียวได้แม้เส้นอื่นจะหาย sheet ไปด้วย
    """
    without_sheet = {
        name for name, lane in poster_ops.LANES.items() if lane.sheet is None
    }
    # ‹2026-08-16› เส้นที่ 8 เข้ามาเป็นตัวที่สองที่ไม่มีใบงาน — ด้วยเหตุผลคนละอย่าง:
    # `sold` เพราะปริมาณน้อยจึงใช้ argument ต่อใบ (ADR-0025 OD-3) ส่วน `photo`
    # เพราะ "ใบงาน" ของมันคือตัวโฟลเดอร์รูปเอง ชื่อไฟล์คือช่องที่คนกรอก
    assert without_sheet == {"sold", "photo"}


# ---------------------------------------------------------------- AC-6 · AC-7


def test_the_dispatcher_never_spells_the_reviewed_at_flag_as_a_quoted_literal() -> None:
    """🔴 AC-6(ก) — `test_every_script_that_accepts_reviewed_at_is_in_LANES` สแกนหา
    literal รูปนั้นในทุกไฟล์ `.py` ของโฟลเดอร์ เพื่อจับ *เส้นใหม่ที่ลืมต่อรายชื่อ LANES*

    ประตูไม่ใช่เส้นและไม่รู้จัก flag ไหนเลย — ถ้าวันหนึ่งมันมี literal นั้นขึ้นมา เทสตัวนั้น
    จะแดงพร้อมข้อความที่**ชี้ทางแก้ผิด** (บอกให้เอา `poster_ops` ไปใส่ `LANES` ซึ่งจะทำให้
    ด่านของเส้นทั้งชุดถูกบังคับกับ dispatcher ที่ไม่มี `reviewed_at` เลย) · เทสนี้แดงก่อน
    พร้อมทางแก้ที่ถูก: **เอา literal ออก อย่าเอาไฟล์นี้เข้า LANES**
    """
    source = (SEED_DIR / "poster_ops.py").read_text(encoding="utf-8")
    needle = '"' + "--reviewed-at" + '"'
    assert needle not in source


def test_ai_suggest_is_excluded_with_the_venv_reason_spelled_out() -> None:
    """AC-7 — เรียก `ai_suggest.py` ด้วย interpreter ของประตูจะรันผิด venv เงียบ ๆ"""
    assert "ai_suggest.py" not in {
        script for lane in poster_ops.LANES.values() for script in lane.scripts.values()
    }
    assert "venv" in poster_ops.EXCLUDED["ai_suggest.py"]


def test_every_exclusion_carries_a_reason() -> None:
    """รายชื่อยกเว้นที่ไม่มีเหตุผลกำกับ = รายชื่อที่ไม่มีใครรู้ว่ายังจริงอยู่ไหม"""
    empty = [name for name, reason in poster_ops.EXCLUDED.items() if not reason.strip()]
    assert empty == []


def test_the_help_screen_names_every_lane_and_every_script() -> None:
    """`--help` คือเหตุผลทั้งหมดที่ไฟล์นี้มีอยู่ (AC-1) — ตกไปตัวเดียวคือคนกลับไปเปิด README"""
    usage = poster_ops._usage()
    for name, lane in poster_ops.LANES.items():
        assert name in usage
        for script in lane.scripts.values():
            assert script in usage
    for filename in poster_ops.EXCLUDED:
        if filename in ("_shared.py", "poster_ops.py"):
            continue
        assert (
            filename in usage
        ), f"{filename} ถูกยกเว้นแต่ --help ไม่บอกคนว่าต้องเรียกตรง"


# ---------------------------------------------------------------- ทางที่ผิด


def test_an_unknown_lane_exits_2_and_lists_the_real_ones(capsys) -> None:
    assert poster_ops.main(["ไม่มีเส้นนี้"]) == 2
    err = capsys.readouterr().err
    assert "manual" in err and "sold" in err


def test_a_lane_without_an_action_exits_2(capsys) -> None:
    assert poster_ops.main(["manual"]) == 2
    assert "action" in capsys.readouterr().err


def test_asking_for_a_sheet_on_the_lane_that_has_none_says_why(capsys) -> None:
    """ข้อความต้องบอก*เหตุผล* ไม่ใช่แค่ปฏิเสธ — ADR-0025 OD-3 ตั้งใจให้เส้นนี้ไม่มีใบงาน"""
    assert poster_ops.main(["sold", "sheet"]) == 2
    err = capsys.readouterr().err
    assert "ไม่มีใบงาน" in err


def test_no_argument_prints_the_help_and_exits_0(capsys) -> None:
    assert poster_ops.main([]) == 0
    assert "poster_ops.py <lane> <action>" in capsys.readouterr().out


def test_the_module_is_runnable_as_a_script() -> None:
    """ประตูที่ import ได้แต่ `python poster_ops.py` ไม่ได้ ไม่ได้แก้ปัญหาของใครเลย"""
    result = subprocess.run(
        [sys.executable, str(SEED_DIR / "poster_ops.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "poster_ops.py <lane> <action>" in result.stdout
