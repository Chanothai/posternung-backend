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

Skill นี้เก็บ **กับดักที่เจอมาแล้วจริงในโปรเจกต์นี้** — งานเสร็จเร็วขึ้นเพราะไม่ต้องเจอ
ปัญหาเดิมซ้ำ ไม่ใช่แค่ checklist ทั่วไป (กฎ/นโยบายอยู่ใน `CLAUDE.md` ที่โหลดอัตโนมัติแล้ว
ไม่ต้องอ่านซ้ำที่นี่)

## Orientation

Dependency ทางเดียวเสมอ: `api → services → repositories → models`
- `app/api/v1/` — thin controller, **ห้ามมี DB query**
- `app/services/` — business logic, 1 ไฟล์ต่อ feature
- `app/repositories/` — DB access ล้วนๆ, ไม่มี business logic
- `app/models/` — SQLAlchemy ORM
- `app/schemas/` — Pydantic request/response
- `tests/unit/` (fixture `db_session`) vs `tests/integration/` (fixture `client`,
  ระดับ HTTP)

## 1. เริ่มงาน

```bash
git checkout develop && git pull origin develop --ff-only
git checkout -b <type>/<scope>
```

แตกจาก **`develop`** เสมอ ไม่ใช่ `master` — ทั้งสอง branch ถูก GitHub protect ระดับ
server (push ตรงถูกปฏิเสธเสมอ ไม่มีข้อยกเว้นแม้ admin) `develop` คือ integration
branch, `master` เป็นแค่ deploy trigger

**ถ้ากำลังต่อยอดงานที่ยังเป็น PR ค้างอยู่** (stacked PR): แตกจาก branch ของ PR นั้น
ไม่ใช่ develop — ดู §6 เรื่อง retarget

## 2. เขียนโค้ด

เขียนให้ครบ layer ตามที่ feature ต้องการ (ไม่ใช่ทุก feature ต้องมีครบทุกชั้น — endpoint
ใหม่มักมี api+service+repo, แก้ validation อาจแค่ schema) อ้างอิงไฟล์ที่มีอยู่แล้วเป็น
pattern แทนที่จะออกแบบใหม่ — โปรเจกต์นี้ทำ auth/catalog มาแล้วเต็มรูปแบบ ดู
`app/services/auth_service.py` / `app/services/poster_service.py`

## 3. เขียนเทส

- Business logic ล้วน (validation, การคำนวณ, การตัดสินใจ) → `tests/unit/`
- พฤติกรรมระดับ HTTP (status code, error envelope, auth, ownership) →
  `tests/integration/`

**พิสูจน์ว่าเทสใหม่จับบั๊กได้จริง** ก่อนเชื่อว่ามันคุ้มครองอะไร — วิธีที่เร็วที่สุดคือ
comment fix ออกชั่วคราวแล้วรันเทสตัวนั้น ต้อง **fail** ถ้ายัง pass แปลว่าเทสไม่ได้
ทดสอบสิ่งที่ตั้งใจ (เคยเกิดขึ้นจริง — เทสเก่าไม่มีเคสไหนจับบั๊ก account-linking ได้
เลยทั้งที่โค้ดมีช่องโหว่มาตลอด)

## 4. Verify — mirror CI ให้ตรงเป๊ะ

`.github/workflows/test.yml` รันตามลำดับนี้ — verify ผิดลำดับหรือขอบเขตต่างกัน
เท่ากับยังไม่ได้ verify:

```bash
ruff check .
black --check .
alembic upgrade head
pytest
```

**ใช้ `.` เสมอ ไม่ใช่ `app/ tests/`** — CI สั่ง `ruff check .` / `black --check .`
กับทั้ง repo รวม `alembic/` ด้วย เคยพลาดจริง: format แค่ `app/ tests/` แล้ว push
ไป CI แดงเพราะไฟล์ migration ที่เพิ่งสร้างไม่ได้ format

**เปลี่ยน schema (model ใหม่/แก้ column)?** DB ทดสอบไม่ migrate ย้อนหลังเอง —
ต้อง reset ก่อน `pytest` รอบแรกหลังแก้ schema:
```bash
docker exec posternung-backend-db-1 psql -U poster_nung_app -d postgres \
  -c "DROP DATABASE IF EXISTS poster_nung_test;"
```
(`tests/conftest.py` สร้างใหม่ + migrate ให้เองตอนรัน pytest ครั้งถัดไป)

**เขียน migration?** ต้องพิสูจน์ว่า downgrade กลับได้จริง ไม่ใช่แค่เขียนแล้วเดา:
```bash
alembic upgrade head
alembic downgrade -1   # เช็คว่าไม่ error
alembic upgrade head   # เช็คว่า apply ซ้ำได้ไม่ error
```
แล้ว query DB ยืนยันว่า object ที่ควรถูกสร้าง/ลบ มีจริง (`\d tablename`, `\di
index_name`) — อย่าเชื่อแค่ว่า alembic ไม่ error

**เปลี่ยนพฤติกรรม runtime** (เช่น auth flow, business rule ที่ mock ในเทสไม่ครอบ
ทุกมุม)? สมควร smoke test ผ่าน ASGI กับ DB จริงเพิ่มอีกชั้น:
```python
from httpx import AsyncClient, ASGITransport
from app.main import app
# ยิง endpoint จริงผ่าน transport นี้ ไม่ต้องรัน server แยก
```
**ลบ test data ที่ seed ไว้ทิ้งเสมอหลังเช็คเสร็จ** — ไม่งั้นข้อมูลปลอมจะค้างใน DB dev

## 5. เปิด PR

```bash
git add <files ที่เกี่ยวข้องเท่านั้น>   # ห้าม git add -A
git commit -m "type(scope): subject"
git push -u origin <branch>
gh pr create --base develop --head <branch> --title "..." --body "..."
```

**หยุดรอผู้ใช้ merge เอง** — ห้าม auto-merge แม้ CI ผ่านแล้ว การเปิด PR คือจุดสิ้นสุด
งานของ turn นี้

## 6. กับดักที่เจอมาแล้ว

| อาการ | สาเหตุ | ทางแก้ |
|---|---|---|
| CI แดงที่ `black --check .` แต่ local ผ่าน | รัน `black app/ tests/` ไม่รวม `alembic/` | รัน `black .` เสมอ (ดู §4) |
| `docker compose up -d --build` แล้วโค้ดยังเป็นเวอร์ชันเก่า | `--build` แค่ build image ใหม่ ไม่ recreate container ที่รันอยู่ | เพิ่ม `--force-recreate`, หรือเช็คด้วย `docker exec <container> grep <marker> <file>` ก่อนสรุปผลทดสอบ — ดู `references/local-environments.md` |
| container ชื่อ `db` ของ sit ไปแย่ง port/ทับ container dev | สอง compose stack ใช้ service name เดียวกัน ไม่ได้แยก project | รันด้วย `-p <project-name>` แยกกันเสมอเวลามีมากกว่า 1 stack |
| merge PR แล้ว PR ถัดไป (ที่ stack ต่อ) ยัง base เป็น branch เก่า | GitHub retarget base อัตโนมัติ **เฉพาะตอน branch ต้นทางถูกลบ** ไม่ใช่ตอน merge | เช็ค `gh pr view <n> --json baseRefName` หลัง merge เสมอ, `gh pr edit <n> --base develop` ถ้ายังไม่ retarget, แล้ว `git merge origin/develop` เข้า branch ปัจจุบันก่อน push ต่อ |
| release PR `develop → master` conflict ทั้งที่ควร fast-forward ได้ | เผลอ squash-merge PR ก่อนหน้า ทำ commit ancestry ระหว่าง branch หลุด | release/reconciliation PR ต้อง **merge ด้วย "Create a merge commit"** เท่านั้น ไม่ใช่ squash |
| สอง PR ไม่ conflict กัน แต่เนื้อหา (โดยเฉพาะ docs) ขัดกันเองหลัง merge | คนละ PR แก้เอกสารคนละบรรทัดในไฟล์เดียวกัน git merge ผ่านได้ปกติแต่ไม่มีใครเช็ค semantic | หลัง merge PR ที่ 2 ของ 2 PR ที่แตะไฟล์เดียวกัน ให้ diff ผลลัพธ์เทียบ base ที่อัปเดตแล้วอีกรอบ อย่าเชื่อแค่ `mergeable: true` |
| เขียนเทสใหม่แล้วมั่นใจว่าคุ้มครองบั๊ก แต่จริงๆ ไม่ได้ทดสอบอะไรเลย | ไม่เคยพิสูจน์ว่าเทส fail ได้ตอนไม่มี fix | ดู §3 — comment fix ออกชั่วคราวแล้วรันเทสนั้นให้เห็น fail ก่อนเชื่อ |

## เมื่อไหร่ควรอ่านต่อ

- **ต้องรัน/ทดสอบผ่าน Docker บนเครื่อง** (dev หรือ production-like/sit) →
  `references/local-environments.md`
- **ทำ release PR develop→master หรือใกล้ถึงขั้น deploy** →
  `references/release-and-deploy.md`

อย่าเปิดสองไฟล์นี้ถ้างานไม่เกี่ยวกับ Docker/deploy — งานส่วนใหญ่ (แก้โค้ด+เทส+PR)
จบได้ในไฟล์นี้ไฟล์เดียว
