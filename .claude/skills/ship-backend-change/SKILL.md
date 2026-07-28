---
name: ship-backend-change
description: >
  End-to-end workflow สำหรับส่งงานหนึ่งชิ้นบน Poster Nung FastAPI backend — ตั้งแต่
  แตก branch, เขียนโค้ดครบ layer, เขียนเทส, verify ให้ตรงกับสิ่งที่ CI เช็คจริง,
  ไปจนถึงเปิด PR. ใช้ skill นี้เสมอเมื่อผู้ใช้ขอเพิ่ม/แก้/ลบ endpoint, service,
  repository, model, migration, แก้บั๊กใน app/, ก่อนเปิด PR ทุกครั้ง, ตอน CI แดง/pytest
  แดง, ตอนต้อง sync หรือ retarget PR, หรือเตรียม release ขึ้น master — ใช้แม้ผู้ใช้
  จะไม่พูดคำว่า "skill" หรือ "workflow" ตรงๆ แค่บอกว่าจะแก้/เพิ่มโค้ดในโปรเจกต์นี้ก็เข้าเงื่อนไข
---

# Ship a backend change (Poster Nung)

ไฟล์นี้เก็บ **ลำดับปฏิบัติจริง + กับดักที่เจอมาแล้วในโปรเจกต์นี้** เท่านั้น

กฎ/นโยบายทั้งหมด (architecture, Global Rules, New API Checklist, Git Workflow,
commit format, ห้าม auto-merge) อยู่ใน **`CLAUDE.md` ซึ่งโหลดอัตโนมัติทุก session
อยู่แล้ว — ไม่ทวนซ้ำที่นี่** ถ้าต้องการรายละเอียดกฎข้อไหนให้ย้อนอ่านจากตรงนั้น

## 1. เริ่มงาน

```bash
git checkout develop && git pull origin develop --ff-only
git checkout -b <type>/<scope>
```

**ถ้าต่อยอดงานที่ยังเป็น PR ค้างอยู่** (stacked PR): แตกจาก branch ของ PR นั้นแทน
develop แล้วตั้ง base ของ PR ใหม่เป็น branch นั้นด้วย — diff จะได้เห็นเฉพาะงานใหม่
ไม่ปนกับ PR ก่อนหน้า (ดูเรื่อง retarget ใน §5)

## 2. เขียนโค้ด

อ้างอิงไฟล์ที่มีอยู่แล้วเป็น pattern แทนที่จะออกแบบใหม่ — โปรเจกต์นี้ทำ auth/catalog
มาแล้วเต็มรูปแบบ ดู `app/services/auth_service.py` / `app/services/poster_service.py`
เป็นตัวอย่างการวาง service + repository + error handling

ไม่ใช่ทุกงานต้องแตะครบทุกชั้น — endpoint ใหม่มักมี api+service+repo, แก้ validation
อาจแค่ schema

## 3. เขียนเทส

fixture ที่มีให้ใน `tests/conftest.py`: **`db_session`** (เรียก service/repository
ตรงๆ ใน `tests/unit/`) และ **`client`** (ยิง HTTP ใน `tests/integration/`)

**พิสูจน์ว่าเทสใหม่จับบั๊กได้จริง ก่อนเชื่อว่ามันคุ้มครองอะไร** — comment fix ออก
ชั่วคราวแล้วรันเทสตัวนั้น ต้อง **fail** ถ้ายัง pass แปลว่าเทสไม่ได้ทดสอบสิ่งที่ตั้งใจ
(เคยเกิดจริง — เทสชุดเดิมไม่มีเคสไหนจับบั๊ก account-linking ได้เลย ทั้งที่โค้ดมี
ช่องโหว่มาตลอด กว่าจะรู้ก็ตอนไล่อ่านโค้ดเอง)

## 4. Verify — mirror CI ให้ตรงเป๊ะ

`.github/workflows/test.yml` รันตามลำดับนี้ — verify ผิดขอบเขตเท่ากับยังไม่ได้ verify:

```bash
ruff check .
black --check .
alembic upgrade head
pytest
```

**ใช้ `.` เสมอ ไม่ใช่ `app/ tests/`** — CI สั่งกับทั้ง repo รวม `alembic/` ด้วย
เคยพลาดจริง: format แค่ `app/ tests/` แล้ว push ไป CI แดงเพราะไฟล์ migration ที่เพิ่ง
สร้างไม่ได้ format

**เปลี่ยน schema (model ใหม่/แก้ column) หรือสลับ branch ที่ migration ต่างกัน?**
DB ทดสอบไม่ migrate ตามให้เอง ต้อง reset ก่อน `pytest` รอบแรก:
```bash
docker exec posternung-backend-db-1 psql -U poster_nung_app -d postgres \
  -c "DROP DATABASE IF EXISTS poster_nung_test;"
```
(`tests/conftest.py` สร้างใหม่ + migrate ให้เองตอนรัน pytest ครั้งถัดไป)

ถ้า `alembic upgrade head` ฟ้อง `Can't locate revision identified by '<hash>'`
แปลว่า dev DB ค้าง revision จาก branch อื่นที่ migration ตัวนั้นไม่มีอยู่ — เทียบ
`alembic heads` กับค่าในตาราง `alembic_version` แล้วปรับให้ตรง branch ปัจจุบันก่อน

**เขียน migration?** ต้องพิสูจน์ว่า downgrade กลับได้จริง ไม่ใช่เขียนแล้วเดา:
```bash
alembic upgrade head
alembic downgrade -1   # ต้องไม่ error
alembic upgrade head   # ต้อง apply ซ้ำได้ไม่ error
```
แล้ว query DB ยืนยันว่า object ที่ควรถูกสร้าง/ลบมีจริง (`\d <table>`, `\di <index>`)
— อย่าเชื่อแค่ว่า alembic ไม่ error

**เปลี่ยนพฤติกรรม runtime** (auth flow, business rule ที่ mock ในเทสไม่ครอบทุกมุม)?
สมควร smoke test ผ่าน ASGI กับ DB จริงอีกชั้น:
```python
from httpx import AsyncClient, ASGITransport
from app.main import app
# ยิง endpoint จริงผ่าน transport นี้ ไม่ต้องรัน server แยก
```
**ลบ test data ที่ seed ไว้ทิ้งเสมอหลังเช็คเสร็จ** — ไม่งั้นข้อมูลปลอมค้างใน DB dev

## 5. เปิด PR

```bash
git add <files ที่เกี่ยวข้องเท่านั้น>   # ไม่ใช้ git add -A — repo มีไฟล์ untracked
                                        # ที่ไม่ควร commit ค้างอยู่ (scripts/, typescript)
```

หลังจากนั้นทำตาม Git Workflow ใน `CLAUDE.md` (commit format, `--base develop`,
หยุดรอผู้ใช้ merge)

**หลัง PR อื่น merge เข้า develop ระหว่างที่ PR เรายัง open** — sync ก่อนเสมอ:
```bash
git merge origin/develop --no-edit
```
แล้วรัน §4 ซ้ำ (โดยเฉพาะถ้า PR นั้นมี migration ใหม่) เพราะ CI รันบนผลลัพธ์หลัง merge
ไม่ใช่บน branch เราเดี่ยวๆ

## 6. กับดักที่เจอมาแล้ว

| อาการ | สาเหตุ | ทางแก้ |
|---|---|---|
| CI แดงที่ `black --check .` แต่ local ผ่าน | รัน `black app/ tests/` ไม่รวม `alembic/` | รัน `black .` เสมอ (§4) |
| ทดสอบผ่าน Docker แล้วผลดูไม่สมเหตุสมผล (โค้ดที่เพิ่งแก้เหมือนไม่มีผล) | มักเป็น container/port/credential gotcha ระดับ Docker ไม่ใช่บั๊กในโค้ด | ดู skill `docker-environments` ก่อนไล่ debug ที่โค้ด |
| merge PR แล้ว PR ถัดไป (ที่ stack ต่อ) ยัง base เป็น branch เก่า | GitHub retarget base ให้อัตโนมัติ **เฉพาะตอน branch ต้นทางถูกลบ** ไม่ใช่ตอน merge | เช็ค `gh pr view <n> --json baseRefName` หลัง merge เสมอ · `gh pr edit <n> --base develop` ถ้ายังไม่ retarget · แล้ว sync ตาม §5 |
| release PR `develop → master` conflict ทั้งที่ควร fast-forward ได้ | เผลอ squash-merge PR ก่อนหน้า ทำ commit ancestry ระหว่าง branch หลุด | release/reconciliation PR ต้องใช้ **"Create a merge commit"** เท่านั้น ไม่ใช่ squash |
| สอง PR ไม่ conflict กัน แต่เนื้อหา (โดยเฉพาะ docs) ขัดกันเองหลัง merge | คนละ PR แก้คนละบรรทัดในไฟล์เดียวกัน git merge ผ่านปกติแต่ไม่มีใครเช็ค semantic | หลัง merge PR ที่สองของสอง PR ที่แตะไฟล์เดียวกัน ให้ diff ผลลัพธ์เทียบ base ที่อัปเดตแล้วอีกรอบ อย่าเชื่อแค่ `mergeable: true` |
| เทสใหม่ที่คิดว่าคุ้มครองบั๊ก แต่จริงๆ ไม่ได้ทดสอบอะไร | ไม่เคยพิสูจน์ว่าเทส fail ได้ตอนไม่มี fix | §3 — comment fix ออกแล้วรันให้เห็น fail ก่อน |

## เมื่อไหร่ควรอ่านต่อ

**ต้องรัน/debug container จริง** (dev, sit, หรือ production — container ไม่ขึ้น,
ต่อไม่ได้, 503 ที่ดูเหมือน credential, จะ deploy) → skill **`docker-environments`**

**แก้/เพิ่ม schema ของ poster** (model ใหม่, migration, enum, constraint ที่แตะ
`posters`/`poster_images`/`reservations`) → skill **`poster-database`** ก่อนเขียน
model — มี convention เฉพาะ (enum `create_type=False`, ลำดับลงทะเบียน model ใหม่)
และมติ resolve ข้อขัดแย้งกับ spec ภายนอกที่ไม่ทวนซ้ำที่นี่

งานส่วนใหญ่ (แก้โค้ด + เทส + PR) จบได้ในไฟล์นี้ไฟล์เดียว ไม่ต้องเรียก skill นั้น
