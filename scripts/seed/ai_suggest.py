#!/usr/bin/env python3
"""อ่านรูปโปสเตอร์ (primary) ด้วย Claude แล้วเสนอค่าฟิลด์ลง CSV ให้คนตรวจ

รันที่เครื่องคุณเอง (ต้องมี network):
    pip install anthropic requests
    export ANTHROPIC_API_KEY="..."                          # ห้าม hardcode ในไฟล์นี้
    export MEDIA_BASE_URL="https://media-sit.posternung.com" # CDN ที่ R2 ของเราเอง

    python ai_suggest.py --limit 5      # ลอง 5 ใบก่อน
    python ai_suggest.py                # ลุยทั้งหมด

🔴 สคริปต์นี้ **ไม่แตะ database** เลย — output เป็น CSV อย่างเดียว
   ผลลัพธ์คือ "ข้อเสนอ" ไม่ใช่ข้อมูลจริง ต้องมีคนตรวจก่อนถึงจะ import เข้า DB

ปลอดภัยต่อการรันซ้ำ (resumable): poster_uuid ที่มีใน ai-suggestions.csv แล้วจะถูกข้าม
เขียน CSV ทีละใบทันทีที่ได้ผล (flush + fsync) พังกลางทางแล้วรันซ้ำได้เลย ไม่เสียของเดิม
ใบที่ล้มเหลวจะ **ไม่** ถูกเขียนลง CSV โดยตั้งใจ — เพื่อให้รอบถัดไปหยิบมาทำใหม่
"""

import argparse
import base64
import csv
import json
import os
import sys
import time

import requests

# anthropic ถูก import แบบ lazy ใน build_client() เพื่อให้ --dry-run ใช้ได้โดยยังไม่ต้องติดตั้ง

MANIFEST = "images-manifest-v2.csv"
OUTPUT = "ai-suggestions.csv"

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

# key ที่ไม่ได้อยู่ใต้ prefix นี้ = รูป internal ห้ามประกอบเป็น URL สาธารณะ (ADR-0006 D2/D5)
# กฎเดียวกับ app/core/media.py — ที่นี่ทำซ้ำเพราะสคริปต์ seed ไม่ได้ import app/
PUBLIC_PREFIX = "posters/public/"

HTTP_TIMEOUT = 60
HTTP_RETRIES = 3
API_RETRIES = 4
SLEEP_BETWEEN = 1.0  # หน่วงระหว่างใบ กัน rate limit

# ขนาดสูงสุดของรูปต่อ 1 request ฝั่ง API (5MB base64) — เผื่อ overhead ไว้เล็กน้อย
MAX_IMAGE_BYTES = 3_500_000

MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

# poster_uuid ที่ไม่ใช่โปสเตอร์ → ไม่ต้องเสียค่า API อ่านรูป
#
# 🔴 ห้ามใช้คอลัมน์ `reasons` ของ review-needed.csv มากรองแทนรายการนี้ — มันเชื่อไม่ได้
#    `prepare_seed.py:39,75` ตั้งธง "ไม่ใช่โปสเตอร์" จาก POSTER_HINT = /poster|โปสเตอร์/
#    ซึ่งเช็คแค่ว่า *ชื่อสินค้า* มีคำนั้นไหม ผลคือพลาดทั้งสองทาง:
#      · false positive — 4cdafbd9 (ANTMAN), 7d10488c + 71599f24 (LOTR 4K ปี 2023)
#        ทั้งสามเป็นใบจริง "พิมพ์US 2หน้า ORIGINAL 27x40" แค่ชื่อไม่มีคำว่า poster
#      · false negative — ตัวข้างล่างนี้ ที่หลุดธงเพราะชื่อมีคำว่า "รองรับโปสเตอร์พิมพ์ 2 หน้า"
#    สแกนชื่อครบ 117 ใบแล้ว มีตัวเดียว (116/117 มีคำว่า ORIGINAL/พิมพ์2หน้า ตัวที่ขาดคือใบนี้)
EXCLUDE = {
    # กรอบไฟ Slim Light Box 27x40 สีดำ — เป็นกรอบ ไม่ใช่โปสเตอร์ (quantity=11 ด้วย)
    # ตรงกับที่ ADR-0009 D8 บันทึกไว้เองว่า "แถวที่ 1 ... เป็นกรอบไฟ ไม่ใช่โปสเตอร์ด้วยซ้ำ"
    "240a94bd-242f-5254-9bf3-9b445315b271": "กรอบไฟ ไม่ใช่โปสเตอร์ (ADR-0009 D8)",
}

# ลำดับฟิลด์ในไฟล์ผลลัพธ์ — ตรงกับ key ใน PROMPT และใน SCHEMA
FIELDS = (
    "title",
    "studio",
    "copyright_year",
    "release_date",
    "poster_type",
    "release_region",
    "genres",
    "description",
)

# ---------------------------------------------------------------------------
# 🔴 PROMPT — คัดลอกมาตามที่ผู้ใช้กำหนด ห้ามแก้เกณฑ์เอง
#    เกณฑ์ poster_type / release_region และรายการฟิลด์ต้องห้าม เป็นข้อตกลงของงานนี้
#    ถ้าจะเปลี่ยน ต้องให้ผู้ใช้สั่ง แล้วแก้ทั้ง PROMPT และ SCHEMA ให้ตรงกัน
# ---------------------------------------------------------------------------
PROMPT = """คุณกำลังดูรูปถ่ายโปสเตอร์หนัง อ่านเฉพาะสิ่งที่เห็นในรูป

ตอบเป็น JSON เท่านั้น ทุกฟิลด์ต้องมี value · confidence (high/medium/low) ·
evidence (บอกว่าอ่านจากตรงไหนของรูป)

{
  "title":          ชื่อเรื่องบนโปสเตอร์
  "studio":         จากโลโก้หรือ billing block
  "copyright_year": ปีจากบรรทัด © ท้ายโปสเตอร์ (ไม่ใช่ปีที่หนังฉาย)
  "release_date":   วันฉายถ้าพิมพ์บนโปสเตอร์ · null ถ้าเขียนว่า COMING SOON
  "poster_type":    TEASER | ADVANCE | THEATRICAL | RERELEASE | UNKNOWN
                    เกณฑ์: "COMING SOON" ไม่มีวันที่ = TEASER/ADVANCE
                           มีวันฉายชัดเจน = THEATRICAL
  "release_region": TH | US | INTL | UNKNOWN
                    เกณฑ์: ข้อความไทย = TH · เรตติ้ง MPAA/rating box = US
                    ⚠️ ภาษาบอกได้แค่ตลาดที่แจก ไม่ได้บอกที่ผลิต
                       ถ้าไม่มั่นใจให้ UNKNOWN
  "genres":         แนวหนัง (array) จากความรู้เรื่องหนังเรื่องนี้
  "description":    บรรยายภาพบนโปสเตอร์ 1-2 ประโยค
}

🔴 ห้ามตอบฟิลด์เหล่านี้เด็ดขาด — ดูจากรูปไม่ได้:
   size · size_format (ไม่มีสเกลอ้างอิงในรูป)
   condition_grade · is_authenticated (ต้องดูของจริง)
   restoration_status (ต้องดูเนื้อกระดาษ)

ถ้าอ่านไม่ออกหรือไม่แน่ใจ ให้ value เป็น null และ confidence เป็น low
ห้ามเดาเพื่อให้ฟิลด์ครบ"""


def _suggestion(value_schema: dict) -> dict:
    """หนึ่งฟิลด์ = value · confidence · evidence (ตามที่ PROMPT กำหนด)"""
    return {
        "type": "object",
        "properties": {
            "value": {"anyOf": [value_schema, {"type": "null"}]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "evidence": {"type": "string"},
        },
        "required": ["value", "confidence", "evidence"],
        "additionalProperties": False,
    }


# structured outputs บังคับรูปทรง JSON ให้ตรงกับ PROMPT ตั้งแต่ฝั่ง API
# → ไม่ต้องเดา/parse ข้อความอิสระ และโมเดลใส่ฟิลด์ต้องห้ามเพิ่มเองไม่ได้เลย
# (ข้อจำกัด: ทุก object ต้องมี additionalProperties=false และ required ครบทุก key)
SCHEMA = {
    "type": "object",
    "properties": {
        "title": _suggestion({"type": "string"}),
        "studio": _suggestion({"type": "string"}),
        "copyright_year": _suggestion({"type": "string"}),
        "release_date": _suggestion({"type": "string"}),
        "poster_type": _suggestion(
            {
                "type": "string",
                "enum": ["TEASER", "ADVANCE", "THEATRICAL", "RERELEASE", "UNKNOWN"],
            }
        ),
        "release_region": _suggestion(
            {"type": "string", "enum": ["TH", "US", "INTL", "UNKNOWN"]}
        ),
        "genres": _suggestion({"type": "array", "items": {"type": "string"}}),
        "description": _suggestion({"type": "string"}),
    },
    "required": list(FIELDS),
    "additionalProperties": False,
}


def build_client(retries: int):
    """สร้าง Anthropic client — key มาจาก env เท่านั้น ไม่มีค่า default ในโค้ด"""
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: ต้อง export ANTHROPIC_API_KEY ก่อน")
    # max_retries ของ SDK จัดการ 429/5xx/connection error ให้เอง (exponential backoff)
    # ลูป retry ของเราด้านล่างเป็นชั้นนอกอีกที เผื่อ error ที่ SDK ไม่ retry ให้
    return anthropic.Anthropic(max_retries=retries)


def media_url(base: str, object_key: str) -> str:
    """ต่อ MEDIA_BASE_URL กับ object_key — กฎเดียวกับ app/core/media.py"""
    key = object_key.lstrip("/")
    if not key.startswith(PUBLIC_PREFIX):
        raise ValueError(f"object_key ไม่ได้อยู่ใต้ {PUBLIC_PREFIX}")
    return f"{base.rstrip('/')}/{key}"


def fetch_image(url: str) -> tuple[str, str]:
    """ดาวน์โหลดรูปเอง แล้วส่งเป็น base64 → คืน (media_type, base64)

    ทำไมไม่ส่ง URL ให้ API ไปดึงเอง: ดึงเองแล้ว error อ่านออก (404/403/ไม่ใช่รูป)
    และคุม retry ได้ ไม่ต้องเดาว่าฝั่ง Anthropic ดึงรูปของเราไม่ได้เพราะอะไร
    """
    ext = url.rsplit(".", 1)[-1].lower().split("?")[0]
    last = None
    for attempt in range(HTTP_RETRIES):
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                media_type = MEDIA_TYPES.get(
                    ext, r.headers.get("content-type", "image/jpeg").split(";")[0]
                )
                if not media_type.startswith("image/"):
                    raise RuntimeError(f"ไม่ใช่รูป (content-type={media_type})")
                if len(r.content) > MAX_IMAGE_BYTES:
                    raise RuntimeError(f"รูปใหญ่เกิน {len(r.content) // 1024}KB")
                return media_type, base64.standard_b64encode(r.content).decode()
            last = f"HTTP {r.status_code}"
        except RuntimeError:
            raise  # ปัญหาที่ retry ไปก็ได้ผลเดิม อย่าวนเสียเวลา
        except Exception as e:  # noqa: BLE001
            last = str(e)[:120]
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last or "download failed")


def ask_claude(client, media_type: str, b64: str, effort: str) -> tuple[dict, object]:
    """ถาม Claude 1 ใบ แล้วคืน (dict ตาม SCHEMA, usage) — retry เองอีกชั้นกัน rate limit

    คืน usage มาด้วยเพื่อให้รอบ `--limit 5` บอกได้ว่าทำครบ 117 ใบจะใช้ token เท่าไร
    """
    import anthropic

    last = None
    for attempt in range(API_RETRIES):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": SCHEMA},
                },
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": b64,
                                },
                            },
                            {"type": "text", "text": PROMPT},
                        ],
                    }
                ],
            )
            if response.stop_reason == "refusal":
                raise RuntimeError("โมเดลปฏิเสธคำขอ (stop_reason=refusal)")
            if response.stop_reason == "max_tokens":
                raise RuntimeError("คำตอบถูกตัดกลางคัน (max_tokens)")
            text = next(b.text for b in response.content if b.type == "text")
            return json.loads(text), response.usage
        except RuntimeError:
            raise
        except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
            last = f"{type(e).__name__}: {str(e)[:100]}"
        except anthropic.APIConnectionError as e:
            last = f"connection: {str(e)[:100]}"
        # backoff แบบทวีคูณ: 5s → 15s → 45s (rate limit ของ vision หนักกว่าปกติ)
        time.sleep(5 * (3**attempt))
    raise RuntimeError(last or "api call failed")


def flatten(poster_uuid: str, url: str, data: dict) -> list[dict]:
    """แปลง JSON 1 ใบ → หลายแถว (1 ฟิลด์ = 1 แถว) ตามรูปแบบ ai-suggestions.csv"""
    rows = []
    for field in FIELDS:
        item = data.get(field) or {}
        value = item.get("value")
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        rows.append(
            {
                "poster_uuid": poster_uuid,
                "field": field,
                # value ว่าง + confidence=low = โมเดลบอกว่าอ่านไม่ออก (ตาม PROMPT)
                "value": "" if value is None else str(value),
                "confidence": item.get("confidence", ""),
                "evidence": item.get("evidence", ""),
                "image_url": url,
            }
        )
    return rows


def load_done(path: str) -> set[str]:
    """poster_uuid ที่มีในผลลัพธ์แล้ว = ทำไปแล้ว ข้ามได้ (resumable)"""
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8-sig") as fh:
        return {r["poster_uuid"] for r in csv.DictReader(fh) if r.get("poster_uuid")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--limit", type=int, default=0, help="จำกัดจำนวนโปสเตอร์ (0 = ทั้งหมด)"
    )
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--out", default=OUTPUT)
    ap.add_argument(
        "--effort",
        default="high",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="ความลึกในการคิดของโมเดล (สูง = แม่นกว่า แพงกว่า)",
    )
    ap.add_argument(
        "--delay", type=float, default=SLEEP_BETWEEN, help="หน่วงระหว่างใบ (วินาที)"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="แสดงรายการที่จะทำ + เช็ค URL ว่าโหลดได้ แต่ไม่เรียก API และไม่เขียนไฟล์",
    )
    args = ap.parse_args()

    base = os.environ.get("MEDIA_BASE_URL")
    if not base:
        sys.exit(
            "ERROR: ต้อง export MEDIA_BASE_URL ก่อน (เช่น https://media-sit.posternung.com)"
        )

    with open(args.manifest, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = {"poster_uuid", "is_primary", "object_key", "product_name"} - set(
            reader.fieldnames or []
        )
        if missing:
            sys.exit(f"ERROR: manifest ขาดคอลัมน์ {', '.join(sorted(missing))}")
        rows = [r for r in reader if r["is_primary"] == "1"]

    done = load_done(args.out)
    seen: set[str] = set()
    todo = []
    excluded = []
    for r in rows:
        uuid = r["poster_uuid"]
        # manifest มี poster ที่ติด is_primary=1 ซ้ำได้ — เอาใบแรกใบเดียวพอ
        if uuid in seen:
            continue
        seen.add(uuid)
        if uuid in EXCLUDE:
            excluded.append(uuid)
            continue
        if uuid in done:
            continue
        todo.append(r)

    skipped = len(done & seen)
    if args.limit:
        todo = todo[: args.limit]

    for uuid in excluded:
        print(f"EXCLUDE {uuid}  {EXCLUDE[uuid]}")
    print(
        f"primary={len(rows)} · poster={len(seen)} · ตัดออก={len(excluded)} · "
        f"ทำไปแล้ว={skipped} · จะทำรอบนี้={len(todo)}"
    )
    if not todo:
        return

    client = None if args.dry_run else build_client(API_RETRIES)

    fh_out = None
    writer = None
    if not args.dry_run:
        new_file = not os.path.exists(args.out)
        fh_out = open(args.out, "a", newline="", encoding="utf-8-sig")
        writer = csv.DictWriter(
            fh_out,
            fieldnames=[
                "poster_uuid",
                "field",
                "value",
                "confidence",
                "evidence",
                "image_url",
            ],
        )
        if new_file:
            writer.writeheader()
            fh_out.flush()

    ok = fail = tok_in = tok_out = 0
    failures = []
    try:
        for i, r in enumerate(todo, 1):
            uuid, name = r["poster_uuid"], r["product_name"]
            try:
                url = media_url(base, r["object_key"])
                if args.dry_run:
                    head = requests.head(
                        url, timeout=HTTP_TIMEOUT, allow_redirects=True
                    )
                    print(f"[{i}/{len(todo)}] DRY  {url} -> HTTP {head.status_code}")
                    ok += 1
                    continue

                media_type, b64 = fetch_image(url)
                data, usage = ask_claude(client, media_type, b64, args.effort)
                tok_in += usage.input_tokens
                tok_out += usage.output_tokens
                writer.writerows(flatten(uuid, url, data))
                # เขียนลงดิสก์จริงทันที ไม่รอจบงาน — พังกลางทางแล้วของเดิมยังอยู่ครบ
                fh_out.flush()
                os.fsync(fh_out.fileno())

                title = (data.get("title") or {}).get("value") or "—"
                ok += 1
                print(
                    f"[{i}/{len(todo)}] OK    {uuid}  "
                    f"in={usage.input_tokens} out={usage.output_tokens}  {title}"
                )
            except Exception as e:  # noqa: BLE001
                fail += 1
                msg = str(e)[:160]
                failures.append((uuid, msg))
                print(f"[{i}/{len(todo)}] FAIL  {uuid}  {name[:30]}  -> {msg}")

            if i < len(todo):
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nหยุดกลางคัน — ของที่เขียนไปแล้วยังอยู่ รันซ้ำได้เลย")
    finally:
        if fh_out:
            fh_out.close()

    print(f"\n=== done: ok={ok} failed={fail} -> {args.out}")
    if ok and tok_in:
        # เอาไว้คูณจำนวนใบที่เหลือ ประเมินค่าใช้จ่ายก่อนลุยทั้งชุด
        print(
            f"token: in={tok_in} out={tok_out} · เฉลี่ยต่อใบ in={tok_in // ok} out={tok_out // ok}"
        )
    for uuid, msg in failures:
        print(f"  FAIL {uuid}: {msg}")
    if fail:
        print("ใบที่ล้มเหลวไม่ได้ถูกเขียนลง CSV — รันซ้ำจะหยิบมาทำใหม่เอง")
    if ok and not args.dry_run:
        print("🔴 ยังไม่ได้แตะ database — ตรวจ CSV ให้ผ่านก่อนค่อยว่ากันเรื่อง import")


if __name__ == "__main__":
    main()
