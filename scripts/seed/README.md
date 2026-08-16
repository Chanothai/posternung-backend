# `scripts/seed/` — วิธีรัน

> **คำตอบสั้นที่สุด: รัน*บนเครื่อง*ด้วย `./venv/bin/python` ไม่ใช่ในคอนเทนเนอร์
> และไม่ใช่ `python3` เปล่า ๆ**
>
> ```bash
> cd ~/Desktop/frameshine/movieposter/posternung-backend
> docker compose up -d db                       # ต้องมี db ขึ้นก่อน
> ./venv/bin/python scripts/seed/make_manual_sheet.py
> ```

---

## 1. `python3` เปล่า ๆ ใช้ไม่ได้ — มี venv 2 ตัวในโปรเจกต์นี้ คนละหน้าที่

| venv | มีอะไร | ใช้กับสคริปต์ไหน |
|---|---|---|
| **`venv/` ที่ root ของ repo** | ทั้ง stack ของแอป (`sqlalchemy` · `asyncpg` · `alembic` · `pydantic`) | **ทุกตัวที่แตะ DB** — ทั้ง 6 ตัวในตาราง §4 ยกเว้น `ai_suggest.py` |
| `scripts/seed/.venv` | `anthropic` + `requests` เท่านั้น | **`ai_suggest.py` ตัวเดียว** (คุยกับ Claude API ไม่แตะ DB เลย) |

🔴 **`ModuleNotFoundError: No module named 'sqlalchemy'` = หยิบ venv ผิดตัว**
`scripts/seed/.venv` ถูกสร้างไว้ตอนทำ `ai_suggest.py` โดยเฉพาะ มันไม่มี `sqlalchemy`
และ **ไม่ควรมี** — สคริปต์ที่คุยกับ Claude API ไม่ควรลากทั้ง stack ของแอปมาด้วย
· `python3` ของระบบ (`/usr/local/bin/python3`) ก็ไม่มีเหมือนกัน

ทั้งสอง venv อยู่ใน `.gitignore` (`venv/` บรรทัด 17 · `.venv/` บรรทัด 18) — clone ใหม่
แล้วไม่มี ต้องสร้างเอง:

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
```

## 2. ทำไมต้องบนเครื่อง ไม่ใช่ `docker compose exec`

**ไม่ใช่เพราะ `:ro` — แต่เพราะ guard ของตัวสคริปต์เองปฏิเสธ**

สคริปต์ที่เขียน DB ทุกตัวเรียก `assert_target_database(url, "dev")` ซึ่งบังคับว่า
host ต้องเป็นเครื่องนี้ (`localhost` · `127.0.0.1` · `::1` · ว่าง) แต่ `docker-compose.dev.yml`
ตั้ง `DATABASE_URL` ของคอนเทนเนอร์ให้ชี้ hostname **`db`** (ต้องเป็นแบบนั้นเพราะมันคุยกัน
ผ่าน docker network) → รันข้างในได้ผลนี้เสมอ:

```
precheck ไม่ผ่าน: --target dev แต่ DATABASE_URL ชี้ host 'db' ซึ่งไม่ใช่เครื่องนี้
```

**ดังนั้นคำถามเรื่อง "เขียน `manual-entry.csv` ออกมาที่ไหนตอน mount เป็น `:ro`"
ไม่เกิดขึ้นเลย** — เส้นทางคอนเทนเนอร์ตันตั้งแต่ก่อนถึงจุดเขียนไฟล์

### 🔴 ห้ามถอด `:ro` ออกจาก `./scripts:/app/scripts:ro`

mount นั้น **ไม่ได้มีไว้ให้ `make_manual_sheet.py`/`manual_entry.py` ใช้** — มันมีไว้ให้
`apply_suggestions.py --target sit` ซึ่งเป็นโหมดเดียวที่ยอมให้ host ไม่ใช่เครื่องนี้
(เทียบกับ `.env.sit` แทน) · โฟลเดอร์นี้มี CSV ที่มีราคา · `seller_sku` ·
`tiktok_product_id` และ object key ของ R2 ครบทุกใบ การให้คอนเทนเนอร์เขียนกลับได้
ไม่ได้แลกอะไรกลับมาเลยในเมื่อไม่มีสคริปต์ตัวไหนต้องการ

## 3. dev DB ต่อจากเครื่องได้จริง — ยืนยันแล้ว

- `.env` ตั้ง `DATABASE_URL` ชี้ `localhost:5432/poster_nung_db`
- `docker-compose.yml` service `db` publish port ออกมาแล้ว
  (`docker ps` → `posternung-backend-db-1  0.0.0.0:5432->5432/tcp`)
- ผลรันจริง: `make_manual_sheet.py` → `อ่านจาก localhost/poster_nung_db — 117 ใบ`

ถ้าต่อไม่ได้ ให้ไล่ตามลำดับนี้ก่อนไปแก้โค้ด:

```bash
docker compose up -d db                        # db ขึ้นหรือยัง
docker ps --format '{{.Names}}\t{{.Ports}}'    # port 5432 publish ออกมาไหม
```

⚠️ `posternung-sit-db` **ไม่** publish port ออกมา (เห็นเป็น `5432/tcp` เฉย ๆ) — ตั้งใจ
· รายละเอียด gotcha ระดับ Docker อยู่ในสกิล `docker-environments` ไม่เขียนซ้ำที่นี่

## 4. สคริปต์ทั้งหมดในโฟลเดอร์นี้

| สคริปต์ | ทำอะไร | แตะ DB | รันด้วย |
|---|---|---|---|
| `make_triage_sheet.py` | ใบงานให้คนตัดสิน `is_poster`/`needs_review` | ไม่ | `./venv/bin/python` |
| `seed_posters.py` | **INSERT** แถวตั้งต้น (`on_conflict_do_nothing`) | ✅ เขียน | `./venv/bin/python` |
| `ai_suggest.py` | ให้ Claude อ่านรูป → `ai-suggestions.csv` | ❌ **ไม่แตะ DB เลย** | `scripts/seed/.venv/bin/python` |
| `make_review_sheet.py` | ใบงานให้คนเซ็นรับผลของ AI | ไม่ | `./venv/bin/python` |
| `apply_suggestions.py` | **UPDATE** `release_date_text` (ADR-0010) | ✅ เขียน | `./venv/bin/python` |
| `make_manual_sheet.py` | ใบงานให้คนกรอกเอง (อ่าน DB) | อ่านอย่างเดียว | `./venv/bin/python` |
| `manual_entry.py` | **UPDATE** 7 ฟิลด์ + `size_format` + `published_at` (ADR-0015) | ✅ เขียน | `./venv/bin/python` |
| `make_reference_sheet.py` | ใบงานให้คนแปะลิงก์แหล่งอ้างอิง (อ่าน DB) | อ่านอย่างเดียว | `./venv/bin/python` |
| `reference_entry.py` | **UPDATE** `reference_url`/`reference_note` + `verification_status` ที่ derive เอง (ADR-0014 Amendment 3) | ✅ เขียน | `./venv/bin/python` |
| `make_correction_sheet.py` | ใบงานให้คนตรวจซ้ำแล้วแก้ค่าที่ผิด (อ่าน DB) | อ่านอย่างเดียว | `./venv/bin/python` |
| `correction_entry.py` | **ทับ** `condition_grade`/`is_unique` พร้อมเหตุผลต่อค่า (ADR-0010 Amendment 2026-08-09) | ✅ เขียน | `./venv/bin/python` |
| `make_split_sheet.py` | ใบงานให้คนกรอกเกรด/ราคา/เหตุผลของชิ้นที่จะแตกออกจากแถวพ่อ (อ่าน DB) | อ่านอย่างเดียว | `./venv/bin/python` |
| `split_entry.py` | **INSERT** แถวลูกใหม่ + แถว `poster_splits` คู่กัน (ADR-0024 · INF-22) | ✅ เขียน | `./venv/bin/python` |
| `sold_entry.py` | เรียก `poster_service.mark_sold()` — **UPDATE** `status`→`sold` + `sold_at` (ADR-0025 · INF-24, **ไม่เขียน ORM ตรง**) | ✅ เขียน | `./venv/bin/python` |
| `poster_ops.py` | **ไม่ทำอะไรเอง** — เรียกสคริปต์ข้างบนตามชื่อ lane (INF-26 · ดูหัวข้อถัดไป) | ผ่านตัวที่มันเรียก | `./venv/bin/python` |

**cwd ไหนก็ได้** — ทุกตัวอ้าง path จากตำแหน่งไฟล์ตัวเอง (`Path(__file__)`) และอ่าน `.env`
จาก root ของ repo เสมอ · ตัวอย่างในเอกสารใช้ root เพื่อให้ path สั้น

### 🔴 ขั้นนำเข้าครั้งแรกไม่มีสคริปต์เหลืออยู่แล้ว ‹ลบ 2026-08-16 · คำสั่งเจ้าของ›

**`prepare_seed.py` และ `migrate_to_r2.py` ถูกลบออกจากโฟลเดอร์นี้** — ทั้งคู่เป็นสคริปต์
ของการนำเข้า **ครั้งเดียว** จาก TikTok export และ **รันไม่ได้มาก่อนหน้านี้แล้ว** เพราะ
input ต้นทาง (`posters-seed.csv` · `images-manifest.csv`) ไม่มีในเครื่องและติด `.gitignore`
· การถอด `prepare_seed.py` ผ่าน **ADR-0019 A-D3** เพราะ D9 เคยระบุชื่อมันเป็นเจ้าของ
ประตูนำเข้า (ซึ่งวัดแล้วว่ามันไม่เคยบังคับ — ด่านจริงคือ `assert_no_zero_quantity_rows()`
ใน `seed_posters.py`)

**สิ่งที่หายไปพร้อมมันคือคำอธิบายว่าข้อมูลตั้งต้นเกิดขึ้นมายังไง** — ที่ยังเหลือและใช้ได้:

| ไฟล์ที่ยังอยู่ | ใครอ่าน |
|---|---|
| `posters-seed-v2.csv` · `images-manifest-v2.csv` · `review-needed.csv` | `seed_posters.py` · `make_triage_sheet.py` |
| `migration-result.csv` (ผลอัปโหลดรายไฟล์: `object_key` · `sha256` · `bytes` · `width` · `height`) | `seed_posters.py` |

🔴 **ทั้งหมดเป็นฉบับสุดท้าย สร้างใหม่ไม่ได้** — ลบไฟล์เหล่านี้เมื่อไหร่ = ไม่มีทางกู้
· `NOT_A_POSTER_REASON` ที่ `make_triage_sheet.py` ใช้ย้ายไปอยู่ `_shared.py` แล้ว และ
**ห้ามแก้ข้อความ** เพราะต้องแมตช์กับค่าที่อยู่ใน `review-needed.csv`
· **รูปชุดใหม่ของ BL-40 ต้องมีเครื่องมือใหม่อยู่แล้ว** (ต้นทางเป็นโฟลเดอร์ในเครื่อง
ไม่ใช่ URL ปลายทาง) — ไม่ได้เสียอะไรไปจากการลบสองไฟล์นี้

### `poster_ops.py` — ประตูเดียวสำหรับคนที่จำชื่อไฟล์ไม่ไหว (INF-26)

```bash
./venv/bin/python scripts/seed/poster_ops.py --help          # เห็นครบทั้ง 7 เส้นในจอเดียว
./venv/bin/python scripts/seed/poster_ops.py manual sheet    # = make_manual_sheet.py
./venv/bin/python scripts/seed/poster_ops.py manual apply --commit --target sit
```

`<lane> <action>` โดย lane = `seed` · `suggest` · `manual` · `reference` · `correction`
· `split` · `sold` (เรียงตามหมายเลขเส้นใน §5) และ action = `sheet` (สร้างใบงาน) หรือ
`apply` (เขียน DB) · **เส้นที่ 7 มีแค่ `apply`** เพราะไม่มีใบงาน CSV (ADR-0025 OD-3)

🔴 **คำสั่งเดิมทุกตัวยังใช้ได้เหมือนเดิม ไม่ถูก deprecate และจะไม่ถูกถอด** — ตัวอย่าง
ที่เหลือทั้งหน้านี้จึงยังเขียนด้วยชื่อไฟล์ตรง ๆ ต่อไป · `poster_ops.py` เป็น**หน้ากาก
คำสั่ง**ที่เรียก `subprocess` ไปหาสคริปต์ตัวเดิม ไม่ได้ห่อ ไม่ได้แก้ ไม่ได้เพิ่มกฎ
อะไรทั้งสิ้น (ADR-0015 **D1** ห้ามยุบเส้นเข้าด้วยกัน — ใบนี้ไม่ได้ยุบ)
· argument ทุกตัวหลัง `<action>` ถูกส่งต่อทั้งก้อนโดยไม่ตีความ ⇒
`poster_ops.py <lane> <action> --help` แสดง help **ของสคริปต์นั้นเอง**

**ตัวเดียวที่เรียกผ่านประตูนี้ไม่ได้โดยตั้งใจ:** `ai_suggest.py` — รันด้วย **venv คนละตัว**
(§1) ถ้าเรียกจากที่นี่จะได้ interpreter ผิดตัวแบบเงียบ ๆ · `--help` บอกเหตุผลไว้ด้วย

## 5. เจ็ดเส้นทางที่เขียน `posters` — คนละแหล่ง คนละกฎ (ADR-0015 D1 · ADR-0024 D2 · ADR-0025)

**แบ่งเส้นด้วย *แหล่งของค่า* ไม่ใช่ *ใครเป็นคนกรอก*** — เส้นที่ 3 กับเส้นที่ 4 เป็นคน
คนเดียวกันและดูรูปชุดเดียวกัน แต่ค่ามาจากคนละที่ (จับใบจริง ↔ เปิดเว็บอ้างอิง)
จึงยังเป็นคนละเส้น · เหตุผลเต็ม: ADR-0015 D1 (Amendment 2026-08-08) + ADR-0014 D28

🔴 **เส้นที่ 1–4 เติมช่องที่ยังว่าง · เส้นที่ 5 ทับค่าที่ลูกค้าเห็นไปแล้ว · เส้นที่ 6
INSERT แถวใหม่ · เส้นที่ 7 ไม่เขียน ORM ตรงเองเลยสักบรรทัด** — นั่นคือเส้นแบ่งที่
สำคัญที่สุดในหน้านี้ และเป็นเหตุผลที่เส้นที่ 5 มีกติกาที่เส้นอื่นไม่มี (ADR-0015 D1
Amendment 2026-08-09 · ADR-0010 A-D2) ส่วนเส้นที่ 6 เป็นเส้นแรกที่สร้างแถว `posters`
ใหม่นอกจาก `seed_posters.py` (ADR-0024) และเส้นที่ 7 เป็นเส้นแรก (และเส้นเดียว)
ที่เรียก `app/services/poster_service.mark_sold()` แทนที่จะเขียน `posters` ตรง
(ADR-0025 D1 — `status` เป็นแกนที่ service คุมแต่ผู้เดียว)

### เส้นที่ 1 — ข้อมูลตั้งต้นจาก TikTok export

```bash
./venv/bin/python scripts/seed/make_triage_sheet.py    # → กรอก is_poster/needs_review เอง
./venv/bin/python scripts/seed/seed_posters.py                       # dry-run
./venv/bin/python scripts/seed/seed_posters.py --commit --status available
```

‹2026-08-16› **ขั้นแรกของเส้นนี้ (`prepare_seed.py`) ไม่มีแล้ว** — ดู §4 · CSV ที่มันเคย
สร้างยังอยู่ครบและสองคำสั่งข้างบนอ่านมันได้ตามปกติ

### เส้นที่ 2 — AI เสนอ คนเซ็นรับ (ADR-0010 · `release_date_text` ฟิลด์เดียว)

```bash
scripts/seed/.venv/bin/python scripts/seed/ai_suggest.py --limit 5   # ← venv คนละตัว
./venv/bin/python scripts/seed/make_review_sheet.py    # → กรอก approved/corrected_text เอง
./venv/bin/python scripts/seed/apply_suggestions.py                  # dry-run
./venv/bin/python scripts/seed/apply_suggestions.py --commit \
    --reviewed-by <ชื่อคุณ> \
    --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>
```

🔴 **ค่าในวงเล็บมุมเป็น placeholder ที่ก๊อปแล้วรันไม่ผ่านโดยตั้งใจ** — ดูเหตุผลที่
§เส้นที่ 4 · `apply_suggestions.py` ปฏิเสธ `--reviewed-at` ที่อยู่ในอนาคตตั้งแต่ก่อน
แตะ database เหมือนกันทั้งหกเส้นที่รับ `--reviewed-at`

`ai_suggest.py` ต้องมี `ANTHROPIC_API_KEY` + `MEDIA_BASE_URL` (ดู `.env.ai` — **ไม่อยู่ใน git**)

### เส้นที่ 3 — คนกรอกเอง (ADR-0015 · INF-11)

```bash
./venv/bin/python scripts/seed/make_manual_sheet.py    # → เปิดรูปดูแล้วกรอกเอง
./venv/bin/python scripts/seed/manual_entry.py                       # dry-run
./venv/bin/python scripts/seed/manual_entry.py --commit \
    --reviewed-by <ชื่อคุณ> \
    --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>
```

🔴 **ค่าในวงเล็บมุมเป็น placeholder ที่ก๊อปแล้วรันไม่ผ่านโดยตั้งใจ** — เส้นนี้แพงที่สุด
ในหกเส้นเพราะ `--reviewed-at` ถูกใช้เป็น `published_at` ของแถวที่ `publish=Y` ด้วย
ค่าที่ผิดตรงนั้นคือบันทึกผิดว่า *ใครสั่งเอาของขึ้นขายเมื่อไหร่* · `manual_entry.py`
ปฏิเสธค่าที่อยู่ในอนาคตตั้งแต่ก่อนแตะ database

🔴 **เฟส 1 กรอกเกรดอย่างเดียว `publish=N` ทั้งหมด** — ห้ามใช้ `publish=Y` จนกว่า
**SCR-11 Condition Guide** และแถบแสดงตำแหน่งบนสเกลจะเสร็จ (ADR-0003 §ข้อบังคับด้าน UI:
`fine > very_good` สวนสัญชาตญาณ → dispute ที่คืนเงินอัตโนมัติไม่ได้ตาม ADR-0002)

#### `--target sit` — ใช้ได้จริงแล้ว (ใช้ครั้งแรก 2026-08-07)

`manual_entry.py` · `reference_entry.py` · `correction_entry.py` รับ `--target dev|sit`
(default `dev`) ·
**`production` ไม่มีให้เลือกและห้ามเพิ่มโดยไม่แก้ ADR-0015 D8** ·
`reference_entry.py` **import `assert_target()` ตัวเดียวกัน ไม่ก๊อป** — guard สองชั้น
จะได้ไม่ drift · `--target sit` ต้อง:

- **รันข้างในคอนเทนเนอร์ sit** — `.env.sit` ชี้ hostname `db` ซึ่ง resolve ได้เฉพาะใน
  docker network และ SIT DB ไม่ publish port ออกมาที่ host (นี่คือเหตุผลที่ mount
  `./scripts:/app/scripts:ro` มีอยู่)
- `DATABASE_URL` **ตรงกับ `.env.sit` เป๊ะ** · ไม่มีไฟล์ = **ไม่ให้รัน** ไม่ใช่เดาจาก
  ชื่อ database (เข้มกว่า `apply_suggestions.py --target sit` หนึ่งชั้น)

```bash
docker compose -p posternung-sit \
  -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit \
  exec app python scripts/seed/manual_entry.py --target sit      # dry-run
```

🔴 **`-p posternung-sit` ห้ามลืม** — ไม่ใส่แล้ว compose จะใช้ project เดียวกับ dev
(ชื่อมาจากโฟลเดอร์) แล้วไป recreate/แย่ง `posternung-backend-db-1` ซึ่งคือ **dev db**
· รายละเอียดอยู่ในสกิล `docker-environments` §"ทำไมต้อง `-p`"

`docker-compose.sit.yml` mount `./.env.sit:/app/.env.sit:ro` ให้ด้วย เพราะ guard เทียบกับ
**ไฟล์** ไม่ใช่ env var — image COPY แค่ `app/` `alembic/` `alembic.ini` ไฟล์ env จึงไม่มี
อยู่ข้างใน · ไม่ได้เพิ่มความเสี่ยงใหม่ (ค่าทุกตัวอยู่ใน env ของคอนเทนเนอร์อยู่แล้วผ่าน
`env_file:`) และ **production/uat ไม่ inherit** (ตรวจแล้วด้วยคำสั่งในสกิล `docker-environments`)

✅ **SIT พร้อมรับแล้ว — ยืนยันด้วย query จริง 2026-08-07** (`BACKLOG.md` **BL-75** และ
**BL-83** ปิดแล้วทั้งคู่) · SIT มีคอลัมน์ครบ มี CHECK ของ ADR-0013 D3 และ app ที่รันอยู่
มี `published_only()` แล้ว · `--target sit --commit` ถูกใช้จริงครั้งแรกวันนั้น
‹ข้อความเดิมตรงนี้เขียนว่า "SIT ยังรับไม่ได้จริงวันนี้ — ตามหลัง migration 2 ตัว"
ซึ่ง **ตกยุคและทำให้เข้าใจผิดว่าเส้นทางนี้ยังใช้ไม่ได้"** แก้ 2026-08-08›

· ⚠️ **นโยบาย `publish=N` ของเฟส 1 ยังไม่มีด่านในโค้ด** — วันนี้ `publish=Y` ผ่านได้
ถ้าใบนั้นมีเกรดและมีรูป ไม่มีอะไรเช็คว่า SCR-11 เสร็จหรือยัง
(ดู `screens.yaml` INF-11 `known_gaps` · ADR-0015 §ต้องทำตามมา)

### เส้นที่ 4 — คนเปิดเว็บอ้างอิงแล้วแปะลิงก์ (ADR-0014 Amendment 3 · INF-13)

```bash
./venv/bin/python scripts/seed/make_reference_sheet.py   # → เปิดเว็บหาแล้วกรอกเอง
./venv/bin/python scripts/seed/reference_entry.py                    # dry-run
./venv/bin/python scripts/seed/reference_entry.py --commit \
    --reviewed-by <ชื่อคุณ> \
    --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>
```

🔴 **ค่าในวงเล็บมุมเป็น placeholder ที่ก๊อปแล้วรันไม่ผ่านโดยตั้งใจ** — บล็อกนี้เคยเขียน
`--reviewed-at` เป็นเวลาจริง แล้วถูกก๊อปมาทั้งบรรทัดเมื่อ 2026-08-08 จน `reviewed_at`
ของ **232 แถวลงเป็นเวลาในอนาคต 3.5 ชั่วโมง** · ตอนนี้ `reference_entry.py` ปฏิเสธ
`--reviewed-at` ที่อยู่ในอนาคตตั้งแต่ก่อนแตะ database และบอกว่าล้ำหน้าไปเท่าไหร่
(ดูข้อ `--reviewed-at` ใน §6)

ใบงาน `reference-entry.csv` มี **2 ช่องที่คนกรอก** — กรอกได้ **ช่องเดียวต่อแถว**:

| กรอกอะไร | ผล |
|---|---|
| `reference_url` (URL ล้วน ๆ) | `verification_status = REFERENCE_FOUND` |
| `reference_note` (เหตุผลตอนหาไม่เจอ) | `verification_status = NO_REFERENCE_FOUND` |
| ไม่กรอกอะไรเลย | คงเป็น `NULL` (= ยังไม่มีใครเปิดหา) |
| **กรอกทั้งคู่** | 🔴 **ปฏิเสธทั้งไฟล์** — ข้อมูลขัดกันเอง (ADR-0014 D29) |

- 🔴 **ไม่มีคอลัมน์ `verification_status` ให้กรอก** — สคริปต์ derive เอง (ADR-0014 D22)
- คอลัมน์ `previous_note` เป็น **ช่องช่วยจำของคน** ยกมาจาก `note` ของ `manual-entry.csv`
  — `reference_entry.py` **ไม่อ่านมันเลย** (ADR-0014 D28 · มีเทสล็อก)
- เขียนเฉพาะใบที่ **ทั้งสามคอลัมน์เป็น `NULL` ครบ** · ไม่มีโหมดเขียนทับ (D29)
- ⚠️ **`reference_url` ซ้ำข้ามแถวเป็นเรื่องปกติ ไม่ใช่บั๊ก** — ขึ้นเป็น warning แล้วเดินต่อ
  · เหตุผล (ใบไทยใช้อาร์ตเวิร์กชุดเดียวกับฉบับต่างประเทศ) อยู่ที่ **ADR-0014 D30**
  และ docstring ของสคริปต์ · 🔴 **ห้ามใครเปลี่ยนเป็นด่านปฏิเสธ**
- 🔴 **สคริปต์นี้ไม่ต่อเน็ต** — ไม่ยิง HTTP ไปเช็คว่าลิงก์มีชีวิต และไม่ normalize URL
- audit ลง `poster_attribute_reviews` **2 แถวต่อใบที่เขียนจริง** (ช่องที่คนกรอก +
  `verification_status` ที่ derive ได้) · `value_before` เป็น `NULL` เสมอ (ADR-0014 D31)

### เส้นที่ 5 — คนตรวจซ้ำแล้วพบว่าค่าที่อยู่ในระบบผิด (ADR-0010 Amendment 2026-08-09 · INF-21)

```bash
./venv/bin/python scripts/seed/make_correction_sheet.py  # → หยิบใบจริงมาตรวจซ้ำแล้วกรอกเอง
./venv/bin/python scripts/seed/correction_entry.py                   # dry-run
./venv/bin/python scripts/seed/correction_entry.py --commit \
    --reviewed-by <ชื่อคุณ> \
    --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>
```

🔴 **ค่าในวงเล็บมุมเป็น placeholder ที่ก๊อปแล้วรันไม่ผ่านโดยตั้งใจ** — เหมือนอีกสี่เส้น

🔴 **เส้นเดียวที่ *ทับ* ค่าที่มีอยู่แล้ว** — อีกหกเส้นทับไม่ได้เลย: เส้นที่ 2–4 เขียนได้
เฉพาะช่องที่ยังว่าง · เส้นที่ 1 กับ 6 **สร้างแถวใหม่** จึงไม่มีค่าเดิมให้ทับตั้งแต่ต้น ·
เส้นที่ 7 เปลี่ยน `status` จาก `available` (ค่าที่กำหนดไว้ล่วงหน้าเสมอ ไม่ใช่ค่าที่คน
กรอกไว้ก่อน) และเขียน `sold_at` ซึ่งเริ่มเป็น `NULL` เสมอ จึงเป็นการเติม ไม่ใช่ทับ
ค่าที่เส้นนี้ทับคือค่าที่ลูกค้าอ่านไปแล้วก่อนตัดสินใจซื้อ บนระบบที่ ADR-0002 ยืนยันว่า
**คืนเงินอัตโนมัติไม่ได้** · กติกาทั้งหมดข้างล่างมาจากข้อนั้นข้อเดียว

ใบงาน `correction-entry.csv` มี **4 ช่องที่คนกรอก** — ค่ากับเหตุผลต้องมาคู่กันเสมอ:

| กรอกอะไร | ผล |
|---|---|
| `condition_grade` + `condition_grade_reason` | ทับเกรดเดิม + audit 1 แถวพร้อมเหตุผล |
| `is_unique` = **`Y` เท่านั้น** + `is_unique_reason` | ทับค่าเดิม + audit 1 แถวพร้อมเหตุผล |
| **`is_unique` = `N`** | 🔴 **ปฏิเสธทั้งไฟล์ทุกกรณี** — อ่านออกแต่เขียนไม่ได้ (ดูข้อถัดไป) |
| ไม่กรอกอะไรเลย | ไม่ทำอะไร (สถานะปกติของใบงานที่ทำไปครึ่งเดียว) |
| **กรอกค่าแต่ไม่กรอกเหตุผล** | 🔴 **ปฏิเสธทั้งไฟล์** — ไม่ใช่ข้ามแถวนั้น (A-D2 ข้อ 2) |
| **กรอกเหตุผลแต่ไม่กรอกค่า** | 🔴 ปฏิเสธทั้งไฟล์ — ข้อมูลขัดกันเอง |

- 🔴 **`--allow-overwrite` ของเส้นที่ 3 ไม่เปลี่ยนเลย** ยังเป็น `title` · `year` เท่านั้น
  (A-D4 ข้อ 3 · มีเทสล็อก) — สองฟิลด์ของเส้นนี้ **ห้าม**เข้ารายการนั้นตลอดกาล (A-D1)
- `--field {condition_grade,is_unique}` จำกัดว่ารอบนี้จะ**เขียน**อะไร ระบุซ้ำได้ ·
  **ไม่มีรูปแบบที่แปลว่า "ทุกฟิลด์" แบบเปิดกว้าง** · ไม่ว่าจะระบุอะไร ด่าน `reason`
  ยัง**ตรวจทั้งไฟล์**เสมอ (ไม่งั้น `--field` จะกลายเป็นทางเลี่ยงด่าน)
- 🔴 **`is_unique = N` เขียนไม่ได้เลย ไม่มีเงื่อนไข — เกรดไม่เกี่ยว แม้แต่ `mint`**
  ‹แก้ 2026-08-09 หลัง code-critic รอบที่ 1 — ข้อความเดิมเขียนว่า *"เขียนได้เฉพาะแถวที่
  เกรดเป็น mint"* ตาม **D1** ซึ่งอ่าน ADR ไม่ครบ›
  **ADR-0019 D6** เขียนหัวข้อของตัวเองว่า `is_unique` ต้องเป็น `true` **ทุกแถว** และ
  **D5** ปิดท้ายว่า *"แม้ใบ `mint` ก็เก็บเป็น 1 แถว 1 ชิ้น — D1 คือสิทธิ์ที่ยังไม่มี
  เครื่องมือรองรับ"* · เหตุผลอยู่ในโค้ดจริง: `posters.status` เป็นสถานะของ**แถว** ·
  reservation ผูกกับ `poster_id` ไม่ใช่กับชิ้น · `uq_active_reservation_per_poster`
  ปฏิเสธ active reservation ที่สองของแถวเดียวกันที่ระดับ DB
  · วันเปิดกลไกต้องทำ **สามอย่างพร้อมกันรอบเดียว** (`quantity` + รื้อ unique index
  พร้อมเขียน concurrency ใหม่ + BR-04 ทั้ง 5 จุดของ D7) — มติเจ้าของเขียนว่า
  **"ห้ามทยอย"** ⇒ สคริปต์ที่ยอมให้เขียน `N` คือการทยอยข้อแรก
  · จะเปิดจริงต้องมี **amendment ของ ADR-0019 ก่อน ไม่ใช่แก้สคริปต์**
  · ของหลายชิ้นต้อง **แตกเป็นหลายแถว** = **INF-22**
- ⚠️ **"อ่านไม่ออก" กับ "อ่านออกแต่ห้าม" เป็นคนละข้อความ** — `N` ไม่ใช่ค่ากำกวม
  parser จึงยัง parse ได้ตามปกติ ส่วนด่านนโยบายอยู่ที่ `parse_rows()` และอธิบาย
  เหตุผลของตัวเอง · คนที่พิมพ์ `N` ถูกตามที่เข้าใจต้องไม่ได้ข้อความว่าพิมพ์ผิด
- 🔴 **ช่อง `is_unique` รับแค่ `Y`/`N`** — `1`/`0`/`true`/`false` ถูกปฏิเสธ**โดยเจตนา**
  เพราะช่องนี้อยู่ในใบงานเดียวกับงานนับใบจริง: คนที่นับได้ `0` แล้วพิมพ์ `0` จะได้
  *"หลายชิ้น"* ซึ่งคือเคส `THE MATRIX (ADVANCE 4K)` เป๊ะ ๆ
- **ใบที่ `condition_grade` ยังเป็น `NULL` ถูกข้ามพร้อมรายงาน** — เส้นนี้ *แก้* ไม่ใช่
  *เติม* ให้ไปใช้เส้นที่ 3 · นี่คือกลไกที่ทำให้ `value_before` ไม่มีทางเป็น `NULL`
- **ค่าใหม่เท่าค่าเดิม = ไม่ใช่การเขียน** ไม่มีแถว audit (ADR-0010 D8) → รันซ้ำได้
- คอลัมน์ `current_*` เป็น **ช่องช่วยจำของคน** — `correction_entry.py` **ไม่อ่านเลย**
  (มีเทสล็อก · precedent คือ `previous_note` ของเส้นที่ 4)
- audit ลง `poster_attribute_reviews` **1 แถวต่อ 1 ค่าที่ทับจริง** · `value_before`
  **ห้ามเป็น `NULL` แม้แถวเดียว** และ `reason` มีครบทุกแถว (A-D2 ข้อ 3/4)
- **ไม่มี assert ด้วย `count(<column>)`** ต่างจากเส้นอื่น — การทับไม่ทำให้ตัวนับขยับ
  เลยสักหน่วย ตัวที่ตรวจคือ `verify_corrections()` ซึ่ง**อ่านค่ากลับมาเทียบ**

### เส้นที่ 6 — แตกแถวพ่อที่แทนของหลายชิ้นออกเป็นแถวลูกใหม่ (ADR-0024 · INF-22/INF-25)

```bash
./venv/bin/python scripts/seed/make_split_sheet.py       # → หยิบใบจริงมากรอกเกรด/ราคา/เหตุผล
./venv/bin/python scripts/seed/split_entry.py                        # dry-run
./venv/bin/python scripts/seed/split_entry.py --commit \
    --reviewed-by <ชื่อคุณ> \
    --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>
```

🔴 **ค่าในวงเล็บมุมเป็น placeholder ที่ก๊อปแล้วรันไม่ผ่านโดยตั้งใจ** — เหมือนอีกสี่เส้น

🔴 **เส้นเดียวที่ INSERT แถวใหม่ นอกจาก `seed_posters.py`** — เส้นที่ 2–5 ล้วน UPDATE
แถวที่มีอยู่แล้ว เส้นนี้สร้างแถวลูกใหม่ทั้งแถวจากการตัดสินใจว่า "แถวพ่อแทนของมากกว่า
หนึ่งชิ้น ต้องแยกชิ้นนี้ออกมา" (ADR-0019 D1/D2/D8) — จึงไม่มีคอนเซปต์ "ค่าเดิม/ทับค่าเดิม"
เลยในเส้นนี้

🔴 **ใบงานใบเดียวใส่พ่อได้หลายคน — ข้อจำกัดคือ "1 ลูกต่อพ่อ*หนึ่งคน* ต่อรอบ"**
(ADR-0024 **A-D4** · ยืนยันด้วยการรันจริง 2026-08-15)

| ใบงานหน้าตาแบบไหน | ผล |
|---|---|
| พ่อ **ต่างคน** กี่แถวก็ได้ในไฟล์เดียว | ✅ `--commit` รอบเดียวสร้างลูกครบทุกแถว (ทรานแซกชันเดียว) |
| พ่อ **คนเดียวกัน** ซ้ำในไฟล์ | 🔴 **ปฏิเสธทั้งไฟล์ก่อนแตะ DB** |
| พ่อคนเดิมอีกรอบ = **ใบงานใหม่** (regenerate ด้วย `make_split_sheet.py` เพื่อได้ `piece_no` ถัดไป) | ✅ ได้ลูกเพิ่มอีกตัว |

⇒ **จำนวนรอบที่ต้องรัน = จำนวนลูกมากที่สุดที่พ่อ*คนเดียว*ต้องการ ไม่ใช่จำนวนลูกทั้งหมด**
· ตัวอย่างจริง: ลูกที่ต้องสร้าง 38 แถว แต่ไม่มีพ่อคนไหนต้องการเกิน 4 ⇒ **4 รอบ**
🔴 **ห้ามอ่านผิดเป็น "หนึ่งใบงาน = หนึ่งพ่อ"** — เคยเข้าใจผิดแบบนั้นมาแล้วและประเมินงาน
เกินจริงไปสิบเท่า (ADR-0024 A-D4 บันทึกที่มาไว้)

⚠️ **ใบงานที่ generator สร้างวันนี้จะออกมา 0 แถว** และนั่นคือพฤติกรรมที่ถูกต้อง —
`make_split_sheet.py` มีสองด่านที่ทำงานเสมอแม้ใส่ `--all`
(รายละเอียดเต็มอยู่ใน docstring ของสคริปต์ §สองด่านเพิ่มเติมที่ใช้เสมอ):
ต้อง **มีเกรดแล้ว** และต้อง **มีผลนับใน `count_actual` ของ `manual-entry.csv`** ซึ่งวันนี้
ยังว่างทั้งไฟล์ · **ไม่ใช่เครื่องมือพัง** — ปลดล็อกด้วยการนับใบจริงแล้วกรอกช่องนั้น
(ADR-0019 **D10** · ADR-0024 **AC-1** ห้ามรันก่อนมีผลนับ) · สคริปต์พิมพ์บอกเหตุผลไว้ให้แล้ว

🔴 **`split_entry.py` ต้องมีทั้ง `split-entry.csv` และ `manual-entry.csv` อยู่ให้พร้อม**
(ADR-0024 A-D5 · INF-25) — ด่านผลนับ (AC-6) อ่าน `count_actual` จาก `manual-entry.csv`
โดยตรง (`_load_counts()` ผ่าน parser เดียวกับเส้นที่ 3) ไม่ใช่แค่ `split-entry.csv`
เหมือนที่เคยพอ · **รัน `--target sit` ต้องก๊อป `manual-entry.csv` เข้าคอนเทนเนอร์ sit
ก่อนเสมอ** เพราะ CSV ของทั้งสองไฟล์อยู่นอก git (`.gitignore` — ดูท้ายส่วนนี้):

```bash
docker cp scripts/seed/manual-entry.csv posternung-sit-app:/app/scripts/seed/manual-entry.csv
```

ใบงาน `split-entry.csv` มี **7 คอลัมน์** — `parent_poster_uuid` · `parent_title` ·
`parent_image_url` · **`piece_no`** · `condition_grade` · `price` · `reason`
🔴 **ใบงานเก่าก่อน INF-25 ใช้ต่อไม่ได้** (6 คอลัมน์ ไม่มี `piece_no`) ต้อง regenerate
ด้วย `make_split_sheet.py` ใหม่เสมอ — วันนี้ใบว่าง 0 แถวอยู่แล้ว ต้นทุน = 0

**3 ช่องที่คนกรอก ต้องกรอกครบพร้อมกันเสมอ** ส่วน `piece_no` เป็นช่องที่ **เครื่อง** เติม
ให้ (อ่าน `max(piece_no)+1` ต่อพ่อจาก DB) คนไม่ต้องพิมพ์เลขชิ้นเอง:

| กรอกอะไร | ผล |
|---|---|
| `condition_grade` + `price` + `reason` | INSERT แถวลูกใหม่ (`title` คัดจากพ่อ) + audit 1 แถวลง `poster_splits` ด้วย `piece_no` ตามที่ generator เติมให้ในไฟล์ |
| กรอกมาไม่ครบทั้งสามช่อง (เช่นมีแค่เกรดกับราคา) | 🔴 **ปฏิเสธทั้งไฟล์** — ไม่มีแนวคิด "เติมทีหลัง" แบบเส้นที่ 3 |
| ไม่กรอกอะไรเลย | ไม่ทำอะไร (สถานะปกติของใบงานที่ทำไปครึ่งเดียว) |
| `piece_no` ในไฟล์ชนกับที่มีอยู่แล้วใน DB | 🔴 **ข้ามเฉพาะแถวนั้น + รายงานดัง — ไม่ปฏิเสธทั้งไฟล์** (ADR-0024 A-D6 — ดูหมายเหตุท้ายส่วนนี้) |

🔴 **exit code ตอนรันไฟล์เดิมซ้ำเปลี่ยนจาก `1` → `0` (ADR-0024 A-D6 · INF-25)** —
ก่อนหน้านี้ชนคีย์ = ปฏิเสธทั้งไฟล์ (`exit 1`) ตอนนี้ชนคีย์ = ข้ามเฉพาะแถวที่ชนแล้ว
**สำเร็จ** (`exit 0`) พร้อมรายงานว่ากี่แถวถูกข้ามและเพราะอะไร **ใครที่เคยอ่าน exit
code เป็นสัญญาณ "รันซ้ำ/ไม่มีอะไรใหม่" จะไม่เห็นสัญญาณนั้นจาก exit code อีกต่อไป —
ต้องอ่านรายงานที่พิมพ์ออกมา (หัวข้อ "piece_no นี้ถูกใช้ไปแล้ว") แทน**

- 🔴 **ไม่มีคำสั่ง UPDATE บน `posters` เลยแม้แต่บรรทัดเดียว** — `price`/`status`/
  `published_at`/`needs_review`/`condition_grade` ของแถวพ่อห้ามถูกแตะทุกกรณี โดยเฉพาะ
  `price` ซึ่ง ADR-0019 **D11 ข้อ 3** ห้ามแก้ย้อนเพราะระบบไม่มีประวัติราคา · มีเทสสามชั้น
  ล็อกไว้ (AST · runtime session ปลอม · อ่านค่าพ่อกลับมาเทียบหลัง commit จริง)
- 🔴 **ไม่เขียน `is_unique` เลยสักบรรทัด ทั้งพ่อและลูก** — ของแถวลูกได้จาก
  `server_default = true` ของคอลัมน์ · **ลำดับบังคับ: แตกลูกก่อน → แก้ `is_unique`
  ของพ่อทีหลังด้วยเส้นที่ 5** (`correction_entry.py`) ไม่ใช่กลับกัน (ADR-0024 D3)
- **แถวลูกได้แค่ `title` (คัดจากพ่อ) + `price`/`condition_grade` (จากใบงาน)** —
  ฟิลด์ระดับงานพิมพ์ทั้งหมด (`tmdb_id`/`year`/`poster_type`/`studio`/`era_decade`/
  `size`/`release_date*`) ปล่อย `NULL` ให้เส้นที่ 3 เติมทีหลัง (OD-2) ·
  `status`/`published_at`/`needs_review`/`is_authenticated` ปล่อยเป็น `server_default`
- **ใบไหนเข้าใบงาน** — ปริยาย = `is_unique = false` และ published (แถวที่รอแตกจริงตาม
  ADR-0019 D1/D2) ต่างจากเส้นที่ 5 ที่กรองด้วย "มีเกรดอยู่แล้ว" เพราะคนละคำถามกัน
- **พ่อยังไม่มี `condition_grade`** (AC-5 — กันกรอบไฟของ BL-82 หลุดเข้ามาจากใบงานที่
  แก้มือ) และ **ยังไม่มีผลนับ (`count_actual` ว่าง/ไม่มีแถวใน `manual-entry.csv`) หรือ
  `piece_no` เกินผลนับ** (AC-6) → **ข้ามเฉพาะแถว พร้อมรายงาน** เช่นเดียวกัน
- **แถวลูกไม่มีรูปตอนสร้าง** จึง publish ไม่ได้จนกว่าจะถ่ายรูป — ด่าน BR-06 ของเส้นที่ 3
  ที่มีอยู่แล้วครอบแถวลูกด้วยโดยไม่ต้องเขียนอะไรใหม่ (มีเทสพิสูจน์)
- 🔴 **คีย์กันรันซ้ำย้ายจาก `(parent, reason)` ไป `(parent, piece_no)` (ADR-0024 A-D5 ·
  INF-25)** — `uq_poster_splits_parent_reason` เดิมผูกด่านไว้กับข้อความที่ workflow
  จริงบังคับให้เปลี่ยนทุกรอบ (~4 รอบต่อพ่อหนึ่งคน — A-D4) ทำให้แก้คำผิดใน `reason`
  แล้วรันไฟล์เดิมซ้ำสร้างลูกเกินมาได้โดยไม่มีอะไรฟ้อง (`screens.yaml` INF-22 G2) ·
  `piece_no` มาจากไฟล์เท่านั้น (applier ห้ามคำนวณเอง) ตรวจซ้ำกับ `poster_splits` ที่
  ระดับสคริปต์ + `uq_poster_splits_parent_piece` ที่ระดับ DB คู่กัน
- **ใบพ่อที่ไม่มีใน DB หรือไม่ใช่ `is_unique=false` แล้ว ณ ตอนรัน** (มีคนแก้ผ่านเส้นที่ 5
  ไปแล้วระหว่างที่ใบงานค้างอยู่) → **ข้ามเฉพาะแถว พร้อมรายงาน** ไม่ทำทั้งไฟล์พัง
  (ต่างจากรูปแบบผิดซึ่งทำทั้งไฟล์พัง — ตัดสินใจตามธรรมเนียมเดิม: ปัญหาที่ตัวไฟล์ =
  ทั้งไฟล์ · ปัญหาที่ต้องรู้สถานะ DB สด ๆ = ข้ามเฉพาะแถว)

### เส้นที่ 7 — บันทึกการขายนอกระบบ (ADR-0025 · INF-24)

```bash
./venv/bin/python scripts/seed/sold_entry.py \
    --poster-uuid <uuid ของใบที่ขายไปแล้ว> \
    --sold-at <เวลาที่ของขายออกไปจริง ISO-8601 พร้อม timezone> \
    --reason <เพราะอะไรถึงบันทึกว่าขายแล้ว>                     # dry-run
./venv/bin/python scripts/seed/sold_entry.py --commit \
    --poster-uuid <uuid> --sold-at <...> --reason <...> \
    --reviewed-by <ชื่อคุณ> \
    --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>
```

🔴 **ค่าในวงเล็บมุมเป็น placeholder ที่ก๊อปแล้วรันไม่ผ่านโดยตั้งใจ** — เหมือนอีกห้าเส้น
ที่รับ `--reviewed-at`

🔴 **เส้นเดียวที่ไม่มีใบงาน CSV** (ADR-0025 OD-3 — argument ต่อใบ ไม่ใช่ไฟล์ batch
เพราะปริมาณจริง 3–5 ใบ/เดือน) และ **เส้นเดียวที่ไม่เขียน ORM/Core เข้า `posters` ตรง**
— เรียก `poster_service.mark_sold()` แทน เพราะ `status` เป็นแกนที่ service คุมแต่
ผู้เดียว (`poster-database` §3 · ADR-0010 D2 · ADR-0019 A-D1)

**เขียนได้แค่สองคอลัมน์: `posters.status` → `sold` และ `posters.sold_at`** ไม่แตะ
`published_at` ไม่แตะ `reservations` เลยสักคอลัมน์ — ปฏิเสธทั้งรายการถ้าใบนั้นมี
reservation ที่ยัง `active` อยู่ (ไม่มี `--force`) หรือ `status` เดิมไม่ใช่ `available`
รายละเอียดครบอยู่ในดอคสตริงของ `sold_entry.py` เอง

`--target dev|sit` เท่านั้น — ไม่มี `production` ให้เลือก (ADR-0015 D8) เหมือนเส้นอื่น
· ไม่มี endpoint เรียกเส้นนี้ได้เลย (Phase 1 ไม่มี admin auth — INF-24 AC-7)

## 6. กติกาที่ใช้ร่วมกันทุกตัว

- **dry-run เป็น default เสมอ** ต้องใส่ `--commit` ถึงเขียนจริง
- ตัวสร้างใบงานทุกตัว **ปฏิเสธที่จะเขียนทับไฟล์ที่มีอยู่แล้ว** — กันทับงานที่กรอกไปครึ่งทาง
  (ลบหรือเปลี่ยนชื่อไฟล์เดิมก่อน) เพราะ CSV ไม่อยู่ใน git จึงกู้ไม่ได้
- 🔴 **`.gitignore` กัน `scripts/seed/*.csv` · `*.bak` · `*.csv.*` ไว้ทั้งหมด** — repo นี้
  เป็น public และ CSV มี object key ของ R2 ครบทุกใบ ซึ่งทำลายเจตนาของ ADR-0006 D2
  · **ห้าม `git add -f` ไฟล์พวกนี้เด็ดขาด**
- `--reviewed-at` **ไม่มี default เป็นเวลาปัจจุบัน** โดยตั้งใจ (ADR-0010 D5) — เวลาที่คน
  ตัดสินกับเวลาที่รันสคริปต์เป็นคนละเวลากันได้มาก การเดาให้คือการกรอกข้อมูลแทนคน
  · 🔴 **แต่ค่าที่อยู่ในอนาคตถูกปฏิเสธ** — ‹แก้ 2026-08-09› บรรทัดนี้เคยเขียนว่า
  *"`reference_entry.py` เท่านั้นในตอนนี้"* ซึ่ง**ไม่จริงตั้งแต่ด่านถูกยกไป `_shared.py`**:
  ทั้งหกเส้นที่รับ `--reviewed-at` ใช้ `assert_not_in_the_future()` **object เดียวกัน**
  และมีเทส parametrize ล็อกไว้ทุกเส้น —
  `reviewed_at` แปลว่า *เวลาที่คนตัดสิน* อนาคตจึงผิดโดยนิยาม ไม่มีเคสที่ถูกต้อง ·
  อ่านนาฬิกาเพื่อ**ปฏิเสธ**คนละเรื่องกับอ่านเพื่อ**จ่ายค่า** — D5 ห้ามอย่างหลังเท่านั้น
  · ข้อความ error บอกว่าล้ำหน้าไปกี่ชั่วโมงกี่นาที เพราะสาเหตุที่พบจริงคือ timezone ผิด
  หรือก๊อปตัวอย่างมาทั้งบรรทัด
- 🔴 **ยกงานเดิมขึ้นปลายทางที่สอง (`dev` → `sit` ตาม ADR-0010 D7) ไม่ใช่การตรวจรอบใหม่**
  — `--reviewed-by` และ `--reviewed-at` ของรอบ SIT ต้องเป็น **ค่าเดิมของรอบ dev เป๊ะ**
  ไม่ใช่เวลาที่ไปรัน · และ **หนึ่งรอบเซ็นรับ = หนึ่งการรันต่อปลายทาง** — SIT ตามหลังอยู่
  กี่รอบ ต้องรันเท่านั้นครั้ง ครั้งละค่าของรอบนั้น
  · **กฎเต็ม เหตุผล และสามอย่างที่ต้องพิสูจน์หลังยก (dry-run รอบสองได้ 0 · checksum ของ
  *ค่า* ตรงกันสองปลายทาง · audit ตรงกัน) อยู่ที่ ADR-0010 §Amendment 2026-08-13
  (A-D5–A-D7) — ที่นี่ไม่เขียนซ้ำ**

  **หาค่าที่ต้องใส่จาก audit ของปลายทางต้นทาง ไม่ใช่จากความจำ** — จำนวนแถวที่ได้ =
  จำนวนครั้งที่ต้องรันที่ปลายทางที่สอง:

  ```bash
  docker exec posternung-backend-db-1 psql -U poster_nung_app -d poster_nung_db -c \
    "select reviewed_by, reviewed_at, count(*) from poster_attribute_reviews \
     where source='<ชื่อใบงาน>.csv' group by 1,2 order by 2;"
  ```

  🔴 **ยังไม่มีด่านในสคริปต์บังคับสองข้อนี้เลย — พึ่งคนที่รันล้วน ๆ** (งานทำด่านคือ
  **BL-133**) · เคสที่พลาดมาแล้วจริง: การยก `correction-entry.csv` ขึ้น SIT เมื่อ
  2026-08-11 **ยุบสองรอบเป็นรันเดียว** ทำให้ 5 แถวบน SIT ถือเวลาเซ็นรับช้ากว่าที่คน
  ตัดสินจริง 55 นาที และ **แก้ย้อนไม่ได้** เพราะ `poster_attribute_reviews` เป็น append-only
- **`production` ไม่มีให้เลือกในสคริปต์ตัวไหนเลย** — `--target` รับแค่ `dev|sit`
  (`manual_entry.py:TARGETS` · `reference_entry.py` · `correction_entry.py` และ
  `split_entry.py` import ทูเพิลเดียวกันมาใช้ ไม่ประกาศซ้ำ) และ
  การเพิ่มต้องแก้ ADR-0015 D8 ก่อน มีเทสล็อกไว้ทั้งสองฝั่ง
  ‹แก้ 2026-08-08 — บรรทัดนี้เคยเขียนว่า *"`manual_entry.py` ไม่มี `--target` ด้วยซ้ำ"*
  ซึ่งไม่จริงตั้งแต่ ADR-0015 D8 Amendment (2026-08-06): ของจริงมี `--target` และ
  guard **เข้มกว่า** `apply_suggestions.py` หนึ่งชั้น ไม่ใช่ไม่มีเลย›

กฎเรื่อง lint/test/PR ของ repo นี้อยู่ใน `CLAUDE.md` + สกิล `ship-backend-change`
— ไม่เขียนซ้ำที่นี่
