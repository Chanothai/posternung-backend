#!/usr/bin/env python3
"""
เตรียมไฟล์ seed + manifest ให้ตรงกับ schema และ ADR ของโปรเจกต์

    python prepare_seed.py

อ่าน:   posters-seed.csv · images-manifest.csv
เขียน:  posters-seed-v2.csv · images-manifest-v2.csv · review-needed.csv

สิ่งที่ทำ (ทั้งหมดเป็น derived data — ไม่ทับไฟล์ต้นฉบับ):
  1. สร้าง poster_uuid ให้ทุกสินค้า → ใช้เป็น posters.id ตอน seed
     และเป็นส่วนหนึ่งของ object_key ทำให้ storage ไม่ผูกกับ TikTok
  2. เติม prefix posters/public/ ตามที่ตกลงใน ADR (แยกจาก internal/)
  3. สกัด title จากชื่อขาย (ตัด ' - YEAR MOVIE POSTER ...' และ [STx] ออก)
  4. ล้าง studio จาก 'Warner Bros. (72664...)' -> 'Warner Bros.'
  5. เดา print_region จาก 'พิมพ์US' / 'พิมพ์ไทย'
  6. รวบรวม *เหตุผล* ที่ของชิ้นนั้นต้องให้คนตัดสิน ลง review-needed.csv
     (is_unique ยังคำนวณให้ เพราะมาจาก quantity ตรง ๆ ไม่ใช่การตีความ)

🔴 **is_poster และ needs_review ไม่ใช่ของสคริปต์นี้อีกแล้ว** — เขียนเป็นค่าว่างเสมอ
ใน posters-seed-v2.csv · regex `poster|โปสเตอร์` และเงื่อนไข 6 ข้อยังทำงานอยู่ แต่ผล
ของมันไปอยู่ใน review-needed.csv ในฐานะ **หลักฐานให้คนอ่าน** เท่านั้น คนตัดสินจริงใน
poster-triage-signoff.csv ที่สร้างด้วย make_triage_sheet.py แล้ว seed_posters.py อ่าน
ไฟล์นั้น (ไฟล์นี้ไม่แตะ) — หลักเดียวกับ ADR-0010 D5

⚠️ **posters-seed-v2.csv เป็น derived data และ .gitignore กันไว้** (`scripts/seed/*.csv`)
การรันสคริปต์นี้ใหม่จะเขียนทับทั้งไฟล์ **โดยไม่มี backup ใน git** — ค่าที่คนกรอกจึงห้าม
อยู่ในไฟล์นี้เด็ดขาด นี่คือเหตุผลที่ไฟล์เซ็นรับต้องเป็นไฟล์แยก

ห้ามใช้ผลลัพธ์นี้ publish ตรง ๆ — condition_grade และ is_authenticated
ต้องกรอกด้วยคนเสมอ (ADR-0003)
"""

import csv
import re
import uuid

SEED_IN = "posters-seed.csv"
IMG_IN = "images-manifest.csv"
SEED_OUT = "posters-seed-v2.csv"
IMG_OUT = "images-manifest-v2.csv"
REVIEW_OUT = "review-needed.csv"

# namespace คงที่ -> รัน 10 ครั้งได้ uuid เดิม (idempotent)
NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

YEAR_CUT = re.compile(r"^(.*?)\s*[-–]\s*((?:19|20)\d{2})\b")
ST_TAG = re.compile(r"\s*\[\s*ST\s*\d+\s*\]\s*", re.I)
BRAND_ID = re.compile(r"\s*\(\d{6,}\)\s*$")
POSTER_HINT = re.compile(r"poster|โปสเตอร์", re.I)

# ข้อความเหตุผลที่ make_triage_sheet.py ใช้ย้อนกลับเป็น hint_is_poster — ประกาศเป็น
# ค่าคงที่เพื่อไม่ให้สองไฟล์ถือสตริงคู่ขนานที่ค้างไม่ตรงกันเวลามีคนแก้ข้อความ
NOT_A_POSTER_REASON = "ไม่ใช่โปสเตอร์ — ตาราง posters แทนไม่ได้"


def clean_title(name: str) -> tuple[str, str]:
    """คืน (title, วิธีที่ได้มา) — วิธีที่ได้มาใช้ตัดสินว่าต้องรีวิวไหม"""
    n = " ".join(name.split())
    m = YEAR_CUT.match(n)
    if m:
        t = ST_TAG.sub(" ", m.group(1))
        return " ".join(t.split()).strip(" -–"), "cut_at_year"
    t = ST_TAG.sub(" ", n)
    return " ".join(t.split())[:120], "fallback_full_name"


def print_region(name: str) -> str:
    if re.search(r"พิมพ์\s*ไทย", name):
        return "TH"
    if re.search(r"พิมพ์\s*US", name, re.I):
        return "US"
    return ""


def main():
    seed = list(csv.DictReader(open(SEED_IN, encoding="utf-8-sig")))
    imgs = list(csv.DictReader(open(IMG_IN, encoding="utf-8-sig")))

    uuid_by_idx, review = {}, []
    out_seed = []

    for r in seed:
        idx = r["idx"]
        pid = str(uuid.uuid5(NS, f"posternung:tiktok:{r['tiktok_product_id']}"))
        uuid_by_idx[idx] = pid

        title, how = clean_title(r["product_name"])
        qty = int(r["quantity"] or 0)
        is_poster = bool(POSTER_HINT.search(r["product_name"]))

        reasons = []
        if not is_poster:
            reasons.append(NOT_A_POSTER_REASON)
        if qty > 1:
            reasons.append(
                f"quantity={qty} ขัดกับ is_unique=true (database-design §4.4)"
            )
        if qty == 0:
            reasons.append("quantity=0")
        if how != "cut_at_year":
            reasons.append("สกัด title อัตโนมัติไม่ได้")
        if not r["year_guess"].strip():
            reasons.append("ไม่มีปี")
        if not r["brand"].strip():
            reasons.append("ไม่มี studio")

        out_seed.append(
            {
                "poster_uuid": pid,
                "idx": idx,
                "title": title,
                "title_source": how,
                "year": r["year_guess"],  # ยังเป็นการเดา ต้องตรวจ
                "era_decade": r["era_decade_guess"],
                "studio": BRAND_ID.sub("", r["brand"]).strip(),
                "size": r["size_guess"],
                "price_thb": r["price_thb"],
                "quantity": r["quantity"],
                "is_unique": "1" if qty == 1 else "0",
                "print_region": print_region(r["product_name"]),
                # 🔴 is_poster / needs_review เป็นของ **คน** ไม่ใช่ของ heuristic —
                # เขียนเป็นค่าว่างเสมอ ผลของ regex/เงื่อนไขไปอยู่ใน review-needed.csv
                # ในฐานะ *หลักฐานให้คนอ่าน* แล้วคนไปตัดสินใน poster-triage-signoff.csv
                # (หลักเดียวกับ ADR-0010 D5: ผลของเครื่อง = หลักฐานดิบ คนละชั้นกับคำยืนยัน)
                # ห้ามเติมค่ากลับเข้ามาตรงนี้ — test_prepare_seed_leaves_human_columns_blank
                # ล็อกไว้ระดับ AST
                "is_poster": "",
                "needs_review": "",
                # ต้องกรอกด้วยคน — ห้าม AI หรือสคริปต์เติม (ADR-0003)
                "condition_grade": "",
                "is_authenticated": "",
                "restoration_status": "",
                "description": "",
                "tiktok_product_id": r["tiktok_product_id"],
                "seller_sku": r["seller_sku"],
                "original_name": r["product_name"],
            }
        )
        if reasons:
            review.append(
                {
                    "idx": idx,
                    "poster_uuid": pid,
                    "title": title,
                    "quantity": r["quantity"],
                    "price_thb": r["price_thb"],
                    "reasons": " · ".join(reasons),
                    "original_name": r["product_name"],
                }
            )

    out_imgs = []
    for r in imgs:
        pid = uuid_by_idx[r["product_idx"]]
        tail = r["object_key"].rsplit("/", 1)[-1]  # NN-<asset_id>.jpg
        out_imgs.append(
            {
                "poster_uuid": pid,
                "product_idx": r["product_idx"],
                "product_name": r["product_name"],
                "source_field": r["source_field"],
                "is_gallery": (
                    "0" if r["source_field"] == "product_description" else "1"
                ),
                "sort_order": r["sort_order"],
                "is_primary": r["is_primary"],
                "object_key": f"posters/public/{pid}/{tail}",  # ← prefix ตามแผน
                "source_url": r["source_url"],
                "duplicate": r["duplicate"],
                "asset_id": r["asset_id"],
            }
        )

    for path, rows in ((SEED_OUT, out_seed), (IMG_OUT, out_imgs), (REVIEW_OUT, review)):
        if not rows:
            continue
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    gallery = sum(
        1 for r in out_imgs if r["is_gallery"] == "1" and r["duplicate"] != "1"
    )
    print(f"สินค้า           {len(out_seed)}")
    print(f"  ต้องรีวิว       {len(review)}  -> {REVIEW_OUT}")
    print(f"  is_unique=1     {sum(1 for r in out_seed if r['is_unique']=='1')}")
    print(f"รูปทั้งหมด        {len(out_imgs)}")
    print(f"  gallery (ไม่ซ้ำ) {gallery}   <- แนะนำอัปแค่ชุดนี้ก่อน (--skip-desc)")
    print(f"\nเขียนแล้ว: {SEED_OUT} · {IMG_OUT} · {REVIEW_OUT}")


if __name__ == "__main__":
    main()
