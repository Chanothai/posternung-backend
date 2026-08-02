#!/usr/bin/env python3
"""
Migrate TikTok product images -> Cloudflare R2

รันที่เครื่องคุณเอง (ต้องมี network):
    pip install boto3 pillow requests
    export R2_ENDPOINT_URL="https://<ACCOUNT_ID>.r2.cloudflarestorage.com"
    export R2_ACCESS_KEY_ID="..."
    export R2_SECRET_ACCESS_KEY="..."
    export R2_BUCKET="posternung-private-sit"

    python migrate_to_r2.py --dry-run          # เช็คก่อนว่า URL ใช้ได้ ไม่อัปโหลดจริง
    python migrate_to_r2.py --limit 5          # ลองจริง 5 ใบก่อน
    python migrate_to_r2.py                    # ลุยทั้งหมด

ปลอดภัยต่อการรันซ้ำ (idempotent): ข้าม object ที่มีอยู่แล้วใน R2
ผลลัพธ์เขียนลง migration-result.csv ทุกครั้ง
"""

import argparse
import csv
import hashlib
import io
import os
import sys
import time

import requests
from PIL import Image

# boto3 ถูก import แบบ lazy ใน r2_client() เพื่อให้ --dry-run ใช้ได้โดยยังไม่ต้องติดตั้ง/ตั้งค่า R2

MANIFEST = "images-manifest.csv"
RESULT = "migration-result.csv"

# metadata ที่ต้องลบทิ้ง (GPS/ตัวตน) — pixel ไม่ถูกแตะ
STRIP_EXIF = True
TIMEOUT = 60
RETRIES = 3
SLEEP_BETWEEN = 0.2  # กัน rate-limit ฝั่ง CDN

# key มี uuid + เนื้อหาไม่เปลี่ยน -> cache ได้ยาว แก้ทีหลังต้องอัปไฟล์ใหม่ทุกใบ
CACHE_CONTROL = "public, max-age=31536000, immutable"

# error code ที่แปลว่า "ยังไม่มี object" เท่านั้น — code อื่น (403 ฯลฯ) ต้อง raise
NOT_FOUND = {"404", "NoSuchKey", "NotFound"}

# คอลัมน์ที่ loop ใช้จริง — ขาดอะไรให้พังตั้งแต่วินาทีแรก ไม่ใช่กลางทาง
REQUIRED_COLS = {
    "poster_uuid",
    "product_idx",
    "product_name",
    "source_field",
    "sort_order",
    "is_primary",
    "object_key",
    "source_url",
    "duplicate",
}


def r2_client():
    import boto3
    from botocore.client import Config

    missing = [
        k
        for k in (
            "R2_ENDPOINT_URL",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET",
        )
        if not os.environ.get(k)
    ]
    if missing:
        sys.exit(f"ERROR: ต้องตั้ง env ก่อน: {', '.join(missing)}")
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def fetch(url: str) -> bytes:
    """ดาวน์โหลดด้วย GET (HEAD ใช้ไม่ได้ — CDN ตอบ 405 allow: GET)"""
    last = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.content
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = str(e)[:80]
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last or "download failed")


def process(raw: bytes):
    """
    ตรวจว่าเป็นรูปจริง (ไม่เชื่อ content-type) + ลบ EXIF + คืน (bytes, w, h, fmt)
    Pillow จะ raise ถ้าไม่ใช่ไฟล์รูป -> ทำหน้าที่เป็น magic-byte check ไปในตัว
    """
    im = Image.open(io.BytesIO(raw))
    im.verify()  # ตรวจความสมบูรณ์
    im = Image.open(io.BytesIO(raw))  # verify() ทำให้ object ใช้ต่อไม่ได้ ต้องเปิดใหม่
    w, h = im.size
    fmt = (im.format or "JPEG").upper()

    if not STRIP_EXIF:
        return raw, w, h, fmt

    if im.mode in ("RGBA", "P") and fmt == "JPEG":
        im = im.convert("RGB")

    # Pillow ไม่ copy EXIF/GPS ให้ตอน save (ต้องส่ง exif= เองถึงจะติดไป)
    # -> re-encode เฉย ๆ ก็ได้ไฟล์สะอาด ไม่ต้องคัดลอก pixel ทีละจุด
    buf = io.BytesIO()
    if fmt == "JPEG":
        im.save(buf, format="JPEG", quality=95, optimize=True)
    elif fmt == "PNG":
        im.save(buf, format="PNG", optimize=True)
    else:
        im.save(buf, format=fmt)
    return buf.getvalue(), w, h, fmt


def exists(s3, bucket: str, key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in NOT_FOUND:
            return False
        raise  # 403 = สิทธิ์/คีย์ผิด ห้ามกลืน ไม่งั้น idempotency พังเงียบ ๆ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dry-run", action="store_true", help="ดาวน์โหลด+ตรวจ แต่ไม่อัปโหลด"
    )
    ap.add_argument("--limit", type=int, default=0, help="จำกัดจำนวนรูป (0 = ทั้งหมด)")
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument(
        "--skip-desc",
        action="store_true",
        help="ข้ามรูปที่ฝังใน product_description (เอาเฉพาะ gallery)",
    )
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED_COLS - set(reader.fieldnames or [])
        if missing:
            sys.exit(
                f"ERROR: manifest ขาดคอลัมน์ {', '.join(sorted(missing))} "
                f"— ต้องใช้ images-manifest-v2.csv ไม่ใช่ v1 "
                f"(object_key ของ v1 ไม่มี prefix posters/public/)"
            )
        rows = list(reader)

    if args.skip_desc:
        rows = [r for r in rows if r["source_field"] != "product_description"]
    rows = [r for r in rows if r["duplicate"] != "1"]  # อัปโหลด URL ซ้ำครั้งเดียวพอ
    if args.limit:
        rows = rows[: args.limit]

    s3 = bucket = None
    if not args.dry_run:
        s3 = r2_client()
        bucket = os.environ["R2_BUCKET"]

    out = []
    ok = skip = fail = 0

    for i, r in enumerate(rows, 1):
        key, url = r["object_key"], r["source_url"]
        rec = {
            **{
                k: r[k]
                for k in (
                    "poster_uuid",
                    "product_idx",
                    "product_name",
                    "source_field",
                    "sort_order",
                    "is_primary",
                    "object_key",
                )
            },
            "status": "",
            "sha256": "",
            "bytes": "",
            "width": "",
            "height": "",
            "error": "",
        }
        try:
            if not args.dry_run and exists(s3, bucket, key):
                rec["status"] = "skipped_exists"
                skip += 1
                out.append(rec)
                print(f"[{i}/{len(rows)}] SKIP  {key}")
                continue

            raw = fetch(url)
            data, w, h, fmt = process(raw)
            sha = hashlib.sha256(data).hexdigest()
            rec.update(sha256=sha, bytes=len(data), width=w, height=h)

            if args.dry_run:
                rec["status"] = "ok_dryrun"
            else:
                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=data,
                    ContentType=f"image/{'jpeg' if fmt == 'JPEG' else fmt.lower()}",
                    CacheControl=CACHE_CONTROL,
                    Metadata={"sha256": sha, "source": "tiktok-batch-export"},
                )
                rec["status"] = "uploaded"
            ok += 1
            print(f"[{i}/{len(rows)}] OK    {key}  {w}x{h}  {len(data)//1024}KB")

        except Exception as e:  # noqa: BLE001
            rec["status"] = "failed"
            rec["error"] = str(e)[:160]
            fail += 1
            print(f"[{i}/{len(rows)}] FAIL  {key}  -> {rec['error']}")

        out.append(rec)
        time.sleep(SLEEP_BETWEEN)

    with open(RESULT, "w", newline="", encoding="utf-8-sig") as fh:
        wtr = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        wtr.writeheader()
        wtr.writerows(out)

    print(f"\n=== done: ok={ok} skipped={skip} failed={fail} -> {RESULT}")
    if fail:
        print(
            "มีรูปที่ล้มเหลว — ดูคอลัมน์ error ใน CSV แล้วรันซ้ำได้ (ของเดิมจะถูก skip)"
        )


if __name__ == "__main__":
    main()
