"""เส้นที่ 8 — นำเข้ารูปจากโฟลเดอร์ (ADR-0026 D10 · INF-27 AC-7)

สิ่งที่ล็อกไว้ที่นี่คือ **การตัดสินใจ** ทั้งหมดของเส้นนี้ ซึ่งเป็นฟังก์ชัน pure โดยตั้งใจ:
`parse_kind()` (ด่านชื่อไฟล์ · fail-closed) · `plan_folder()` (แถบ `sort_order` ·
ด่าน front-required · การข้ามไฟล์ซ้ำ · การตั้งรูปนำ)

🔴 **สิ่งที่เทสที่นี่ *ไม่* ครอบ และต้องบอกไว้แทนการอ้างว่าครบ** (`test-quality` §5):
* **การอัปโหลดขึ้น R2 จริง** — ต้องมี credential ของ bucket ซึ่งไม่มีในเครื่องนี้และ
  ไม่ควรมีใน repo · จุดที่พิสูจน์ไม่ได้คือ `put_object()` ทำงานถูกไหม
* **การล้าง EXIF กับรูปจากมือถือจริง** — เทสใช้รูปที่ Pillow สร้างเอง ซึ่งไม่มี GPS
  อยู่แล้วตั้งแต่ต้น ⇒ พิสูจน์ได้แค่ว่า "ไฟล์ที่ออกมายังเป็นรูปที่เปิดได้และไม่มี EXIF"
  ไม่ได้พิสูจน์ว่า "GPS ที่เคยมีถูกลบจริง"
* ทั้งสองข้อต้องพิสูจน์ด้วยการรันจริงกับรูปชุดแรกของ BL-40 — เป็น `known_gap` ของ INF-27
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest

from scripts.seed._shared import PrecheckError
from scripts.seed.photo_entry import (
    BANDS,
    PhotoAction,
    PosterPhotoState,
    build_storage_key,
    parse_kind,
    plan_folder,
    read_folders,
    strip_exif,
)

PID = uuid.UUID("3f2a8c91-1111-2222-3333-444455556666")


def _state(**over) -> PosterPhotoState:
    base = {
        "exists": True,
        "has_primary": False,
        "max_in_band": {},
        "known_hashes": frozenset(),
    }
    base.update(over)
    return PosterPhotoState(**base)


def _files(*names: str) -> list[tuple[Path, str]]:
    """(path, sha256) — แฮชสมมติที่ต่างกันต่อไฟล์ ไม่ต้องมีไฟล์จริง"""
    return [(Path(n), f"{i:064x}") for i, n in enumerate(names, start=1)]


# ── ด่านชื่อไฟล์ (AC-7) ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("front.jpg", ("FRONT", 0)),
        ("front-02.jpg", ("FRONT", 2)),
        ("back.jpg", ("BACK", 0)),
        ("back-01.jpeg", ("BACK", 1)),
        ("defect-01.jpg", ("DEFECT", 1)),
        ("defect-12.png", ("DEFECT", 12)),
    ],
)
def test_filenames_map_to_the_kind_they_name(filename: str, expected) -> None:
    assert parse_kind(filename) == expected


@pytest.mark.parametrize(
    "filename",
    [
        "FRONT.jpg",  # ตัวใหญ่ — ADR-0026 D2 รับ lowercase ที่ขอบนี้เท่านั้น
        "Front.jpg",
        "front.JPG",  # นามสกุลตัวใหญ่
        "cover.jpg",  # คำที่ไม่อยู่ในสามชนิด
        "front_02.jpg",  # ขีดล่างแทนขีดกลาง
        "defect.txt",  # ไม่ใช่รูป
        "IMG_2481.jpg",  # ชื่อจากกล้องที่ยังไม่ถูกเปลี่ยน
        "front-002.jpg",  # เลขสามหลัก
        "",
    ],
)
def test_a_filename_that_does_not_name_its_kind_is_rejected(filename: str) -> None:
    """🔴 ตัวฆ่า mutation หลักของ AC-7 — **ไม่มี default** ชื่ออ่านไม่ออก = ปฏิเสธ

    `IMG_2481.jpg` คือเคสที่จะเกิดจริงที่สุดระหว่างงาน BL-40 (ก๊อปจากกล้องมาตรง ๆ)
    · ถ้ามี default เป็น FRONT รูปตำหนิจะไปโผล่หน้า Home เงียบ ๆ (ADR-0026 D9)
    """
    with pytest.raises(PrecheckError):
        parse_kind(filename)


def test_the_rejection_message_names_the_shapes_it_accepts() -> None:
    """ข้อความต้องบอกทางแก้ ไม่ใช่แค่บอกว่าผิด — คนกำลังยืนอยู่หน้ากองไฟล์"""
    with pytest.raises(PrecheckError) as exc:
        parse_kind("IMG_2481.jpg")
    message = str(exc.value)
    assert "front.jpg" in message and "defect-NN.jpg" in message


# ── แถบ sort_order (ADR-0026 D5) ───────────────────────────────────────────


def test_each_kind_starts_at_the_bottom_of_its_own_band() -> None:
    plans = plan_folder(PID, _files("front.jpg", "back.jpg", "defect-01.jpg"), _state())

    assert [(p.kind, p.sort_order) for p in plans] == [
        ("FRONT", 0),
        ("BACK", 100),
        ("DEFECT", 200),
    ]


def test_photos_within_a_kind_follow_the_number_in_the_filename() -> None:
    """ลำดับในกลุ่มมาจากชื่อไฟล์ ไม่ใช่ลำดับที่ระบบไฟล์คืนมา

    ‹ต้องส่ง state ที่ใบนี้มีรูป FRONT อยู่แล้ว ไม่งั้นด่าน front-required ปฏิเสธก่อน —
    ซึ่งเป็นพฤติกรรมที่ถูก และเป็นเหตุผลที่เทสนี้เคยแดงตอนเขียนครั้งแรก›
    """
    plans = plan_folder(
        PID,
        _files("defect-03.jpg", "defect-01.jpg", "defect-02.jpg"),
        _state(max_in_band={"FRONT": 0}, has_primary=True),
    )

    assert [p.path.name for p in plans] == [
        "defect-01.jpg",
        "defect-02.jpg",
        "defect-03.jpg",
    ]
    assert [p.sort_order for p in plans] == [200, 201, 202]


def test_adding_a_front_photo_later_continues_its_own_band_not_the_max() -> None:
    """🔴 ตัวฆ่า mutation ของ D5 — ห้ามต่อท้าย `max(sort_order)` ข้ามกลุ่ม

    ใบนี้มีรูปตำหนิถึง 202 อยู่แล้ว · ถ้าคำนวณจาก max ทั้งใบ รูปหน้าใบที่เพิ่มใหม่จะได้
    203 แล้ว **ไปโผล่ท้ายสุดหลังรูปตำหนิ** บน SCR-05 โดยไม่มีอะไรฟ้อง
    """
    state = _state(max_in_band={"FRONT": 1, "DEFECT": 202}, has_primary=True)

    (plan,) = plan_folder(PID, _files("front-09.jpg"), state)

    assert plan.sort_order == 2, "ต้องต่อจากแถบ FRONT (1) ไม่ใช่จาก max ทั้งใบ (202)"
    assert plan.sort_order < BANDS["BACK"]


def test_overflowing_a_band_is_rejected_loudly() -> None:
    """ล้นแถบต้องพังดัง ไม่ใช่ปล่อยให้เลขไหลไปทับกลุ่มถัดไป"""
    state = _state(max_in_band={"FRONT": 99}, has_primary=True)

    with pytest.raises(PrecheckError, match="ล้นแถบ"):
        plan_folder(PID, _files("front-02.jpg"), state)


# ── ด่าน front-required ฝั่งเครื่องมือ (ADR-0026 D8 ชั้นที่ 3) ──────────────


def test_a_folder_without_a_front_photo_is_rejected() -> None:
    """เคสจริงของ BL-40 — ถ่ายตำหนิกับด้านหลังไว้ก่อนแล้วนำเข้าเลย"""
    with pytest.raises(PrecheckError, match="front"):
        plan_folder(PID, _files("back.jpg", "defect-01.jpg"), _state())


def test_a_folder_without_front_is_accepted_when_the_poster_already_has_one() -> None:
    """ด้านตรงข้าม — ใบที่มีรูปหน้าใบใน DB แล้ว เพิ่มเฉพาะรูปตำหนิได้

    ถ้าไม่มีเทสนี้ ด่านที่ปฏิเสธทุกโฟลเดอร์ที่ไม่มี `front*` ก็ผ่านเทสข้างบนเหมือนกัน
    """
    state = _state(max_in_band={"FRONT": 0}, has_primary=True)

    plans = plan_folder(PID, _files("defect-01.jpg"), state)

    assert [p.kind for p in plans] == ["DEFECT"]


def test_a_poster_that_does_not_exist_is_rejected() -> None:
    with pytest.raises(PrecheckError, match="ไม่มีใบนี้"):
        plan_folder(PID, _files("front.jpg"), _state(exists=False))


# ── รูปนำ (is_primary) ─────────────────────────────────────────────────────


def test_the_first_front_becomes_primary_when_the_poster_has_none() -> None:
    plans = plan_folder(PID, _files("front.jpg", "front-02.jpg", "back.jpg"), _state())

    assert [p.is_primary for p in plans] == [True, False, False]


def test_no_new_primary_when_the_poster_already_has_one() -> None:
    """🔴 `uq_poster_images_primary` เป็น partial unique — ตั้งซ้ำ = IntegrityError

    ด่านนี้อยู่ฝั่งเครื่องมือเพื่อให้ error อ่านรู้เรื่อง ส่วนตัวกันจริงอยู่ที่ DB
    """
    state = _state(has_primary=True, max_in_band={"FRONT": 0})

    plans = plan_folder(PID, _files("front-02.jpg"), state)

    assert [p.is_primary for p in plans] == [False]


def test_a_back_photo_never_becomes_primary() -> None:
    """ADR-0026 D3 — `ck_poster_images_primary_is_front` ห้ามไว้ที่ DB อยู่แล้ว
    เครื่องมือต้องไม่พยายามตั้งแต่แรก"""
    state = _state(max_in_band={"FRONT": 0}, has_primary=False)

    plans = plan_folder(PID, _files("back.jpg"), state)

    assert all(not p.is_primary for p in plans)


# ── รันซ้ำ (idempotent) ────────────────────────────────────────────────────


def test_a_file_whose_hash_is_already_in_the_poster_is_skipped_not_duplicated() -> None:
    """รันซ้ำโฟลเดอร์เดิมต้องไม่สร้างแถวซ้ำ — ข้าม + รายงาน (ทรงเดียวกับ ADR-0024 A-D6)"""
    files = _files("front.jpg", "defect-01.jpg")
    known = frozenset({files[0][1]})
    state = _state(known_hashes=known, max_in_band={"FRONT": 0}, has_primary=True)

    plans = plan_folder(PID, files, state)

    assert [p.action for p in plans] == [
        PhotoAction.SKIP_ALREADY,
        PhotoAction.UPLOAD,
    ]


def test_two_identical_files_in_one_folder_only_upload_once() -> None:
    """ก๊อปไฟล์เดิมมาสองชื่อ — แฮชเดียวกันจึงเป็นรูปเดียวกัน"""
    same = "a" * 64
    files = [(Path("front.jpg"), same), (Path("front-02.jpg"), same)]

    plans = plan_folder(PID, files, _state())

    assert [p.action for p in plans] == [PhotoAction.UPLOAD, PhotoAction.SKIP_ALREADY]


def test_the_storage_key_carries_the_content_hash() -> None:
    """key ที่ผูกกับเนื้อไฟล์ ⇒ ไฟล์เดิมได้ key เดิมเสมอ · ADR-0006 D2 รูปแบบ path"""
    key = build_storage_key(PID, 7, "b" * 64, ".jpg")

    assert key.startswith(f"posters/public/{PID}/07-")
    assert key.endswith(".jpg")
    assert "b" * 32 in key


def test_every_planned_key_is_under_the_public_prefix() -> None:
    """ADR-0026 D7 — รอบนี้ public ทั้งหมด · key ที่หลุดไป internal จะทำให้
    `build_media_url()` raise แล้วรูปหายทั้งใบ (ADR-0006 D5)"""
    plans = plan_folder(PID, _files("front.jpg", "back.jpg", "defect-01.jpg"), _state())

    for plan in plans:
        assert plan.storage_key.startswith("posters/public/")


# ── โครงโฟลเดอร์ ───────────────────────────────────────────────────────────


def test_a_folder_name_that_is_not_a_uuid_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "blade-runner").mkdir()
    (tmp_path / "blade-runner" / "front.jpg").write_bytes(b"x")

    with pytest.raises(PrecheckError, match="UUID"):
        read_folders(tmp_path)


def test_an_empty_folder_is_rejected(tmp_path: Path) -> None:
    (tmp_path / str(PID)).mkdir()

    with pytest.raises(PrecheckError, match="ว่าง"):
        read_folders(tmp_path)


def test_hidden_files_are_ignored(tmp_path: Path) -> None:
    """`.DS_Store` ของ macOS อยู่ในทุกโฟลเดอร์ที่เคยเปิดด้วย Finder — ถ้าไม่ข้าม
    ด่านชื่อไฟล์จะปฏิเสธทั้งรอบด้วยเหตุผลที่คนแก้ไม่ได้"""
    folder = tmp_path / str(PID)
    folder.mkdir()
    (folder / ".DS_Store").write_bytes(b"junk")
    (folder / "front.jpg").write_bytes(b"x")

    assert [p.name for p in read_folders(tmp_path)[PID]] == ["front.jpg"]


# ── ล้าง EXIF ──────────────────────────────────────────────────────────────


def test_strip_exif_returns_a_clean_readable_image() -> None:
    """ดู docstring หัวไฟล์ว่าเทสนี้พิสูจน์อะไรไม่ได้ (รูปทดสอบไม่มี GPS แต่แรก)"""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 25), "red").save(buffer, format="JPEG")

    clean, width, height = strip_exif(buffer.getvalue())

    assert (width, height) == (40, 25)
    reopened = Image.open(io.BytesIO(clean))
    assert reopened.size == (40, 25)
    assert not dict(reopened.getexif())


def test_a_file_that_is_not_an_image_is_rejected() -> None:
    """ไม่เชื่อนามสกุลไฟล์ — Pillow ทำหน้าที่ตรวจ magic byte ไปในตัว"""
    from PIL import UnidentifiedImageError

    with pytest.raises((UnidentifiedImageError, OSError)):
        strip_exif(b"not an image at all")
