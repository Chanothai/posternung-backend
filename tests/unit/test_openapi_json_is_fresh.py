"""`openapi.json` ที่ commit ไว้ ต้องเท่ากับสิ่งที่โค้ดวันนี้สร้าง — `docs/BACKLOG.md` **BL-91**

## ทำไมเป็นเทส ไม่ใช่ step ใน CI

ทั้งสองทางจับ drift ได้เหมือนกัน แต่เทสจับได้**ตั้งแต่ก่อน push** และมีที่เดียว ·
step ใน CI ที่ทำเรื่องเดียวกับเทสคือกลไกที่สองที่ต้องคอยดูให้ตรงกัน — และรอบที่มัน
ไม่ตรงกัน จะไม่มีอะไรบอก (ปัญหาทรงเดียวกับที่ BL-81 บันทึกไว้เรื่อง "สามที่ที่พูด
เรื่อง publish ได้หรือยัง") · CI รัน `pytest` อยู่แล้ว เทสนี้จึงอยู่ใน CI ด้วยโดยอัตโนมัติ

## ทำไมต้องมีอะไรบังคับเลย

`openapi.json` ถูก `CLAUDE.md` แต่งตั้งว่าเป็น *"สิ่งที่ generate จาก FastAPI = สะท้อน
โค้ดจริง ใช้เทียบ drift"* และสกิล `contract-drift-check` §2 ใช้มันเป็นฝั่ง "โค้ดจริง"
ของการเทียบ · **ไฟล์ที่ค้างไม่ได้ทำให้อะไรพัง — มันทำให้การตรวจ drift ตอบผิด**
คนรันจะได้คำตอบว่า "ตรงกันแล้ว" จากการเทียบ contract กับไฟล์ที่ไม่ใช่โค้ดจริง

เคยเกิดจริง 2026-08-07: ไฟล์ค้างที่ชุดค่า `REFERENCE_MATCHED` · `DISCREPANCY_FOUND`
· `UNKNOWN` + `verification_note` = **ชุดก่อน `a7c31e5f9b04`** คือค้างข้าม migration
มา 2 รอบ · แก้ด้วยมือที่ `1e62092` แล้ว **แต่ไม่มีอะไรกันไม่ให้ค้างอีก จนถึงเทสนี้**
"""

from __future__ import annotations

from pathlib import Path

from scripts.generate_openapi import OUTPUT, build_schema


def test_committed_openapi_json_matches_what_the_code_produces() -> None:
    """ไฟล์ที่ commit ไว้ = ผลของ `app.openapi()` วันนี้ · ต่างเมื่อไหร่ = ค้าง

    เทียบ **ทั้งไฟล์แบบตัวต่อตัว** ไม่ใช่ทีละคีย์ที่นึกออก — drift ครั้งที่แล้วอยู่ที่
    *ค่าใน enum* ซึ่งเป็นที่ที่ไม่มีใครนึกจะไล่เช็ค · การเทียบทั้งก้อนคือ closed-world
    รูปหนึ่ง: มันจับสิ่งที่ **ถูกเพิ่มเข้ามา** ได้ด้วย ไม่ใช่แค่สิ่งที่เราเดาชื่อถูก
    """
    assert OUTPUT.is_file(), f"ไม่พบ {OUTPUT} — สร้างด้วย scripts/generate_openapi.py"

    committed = OUTPUT.read_text(encoding="utf-8")
    generated = build_schema()

    assert committed == generated, (
        f"\n🔴 {OUTPUT.name} ไม่ตรงกับโค้ดจริง — มันคือฝั่ง 'โค้ดจริง' ที่สกิล\n"
        "   `contract-drift-check` §2 ใช้เทียบกับ contract · ไฟล์ที่ค้างทำให้การตรวจ\n"
        "   drift ตอบผิดโดยไม่มีอะไรฟ้อง\n\n"
        "   แก้ด้วย: ./venv/bin/python scripts/generate_openapi.py\n"
        "   แล้ว commit ไฟล์ที่ได้มา **พร้อมกับการเปลี่ยน schema ในรอบเดียวกัน**\n\n"
        "   🔴 ห้ามแก้ openapi.json ด้วยมือให้ตรงกับ contract — contract ตัวจริงอยู่ที่\n"
        "      ../workspace/docs/api/openapi.yaml · การแก้ไฟล์นี้ด้วยมือคือการทำลาย\n"
        "      เครื่องมือวัด ไม่ใช่การแก้ drift\n"
    )


def test_generator_is_deterministic() -> None:
    """เรียกสองครั้งต้องได้ผลเท่ากัน — ไม่งั้นเทสข้างบนจะแดงสุ่ม ๆ แล้วคนจะเลิกเชื่อมัน

    จุดที่เคยพลาดได้จริงคือการ `sort_keys` ไม่สม่ำเสมอ หรือการเอาเวลา/uuid เข้ามาปน ·
    ถ้าเทสนี้แดง แปลว่าเทสข้างบน**ไม่มีค่า**ไม่ว่ามันจะเขียวหรือแดง
    """
    assert build_schema() == build_schema()


def test_generated_schema_is_not_trivially_empty() -> None:
    """closed-world กันเคสที่ generator พังเงียบ ๆ แล้วคืนโครงเปล่า

    ถ้า `build_schema()` วันหนึ่งคืน `{"openapi": "3.1.0", "paths": {}}` เพราะ import
    ผิดทาง เทสข้างบนจะยัง**เขียวได้** ทันทีที่มีคนรัน generator แล้ว commit ไฟล์เปล่า
    ตามไป — สองเทสข้างบนเทียบไฟล์กับตัวเอง ไม่ได้เทียบกับความจริงว่า API มีอะไรบ้าง
    """
    import json

    schema = json.loads(build_schema())
    paths = schema["paths"]
    assert len(paths) >= 5, f"เจอแค่ {len(paths)} path — generator น่าจะพัง"
    # เส้นที่มีอยู่จริงแน่ ๆ และหายไม่ได้โดยไม่มีใครตั้งใจ
    assert "/api/v1/posters" in paths
    assert "/api/v1/auth/firebase" in paths
    assert schema["components"]["schemas"]


def test_generator_writes_where_the_repo_expects_it() -> None:
    """ปลายทางต้องเป็น `openapi.json` ที่ root — path ที่ `CLAUDE.md` และสกิลอ้างถึง"""
    assert OUTPUT.name == "openapi.json"
    assert OUTPUT.parent == Path(__file__).resolve().parents[2]
