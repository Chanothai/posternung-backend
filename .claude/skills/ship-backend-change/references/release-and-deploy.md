# Release develop → master และ deploy production

> โครงสร้าง pipeline (`test → build → deploy-*`), gate ที่เป็น GitHub Environment
> required reviewers, และเรื่อง secret ต่อ env อยู่ใน `.claude/rules/environments.md`
> ไฟล์นี้เก็บเฉพาะ **สิ่งที่ต้องระวังตอนลงมือทำจริง** ซึ่ง rule นั้นไม่ได้ครอบ

อ่านไฟล์นี้เมื่อพร้อม release ของที่อยู่ใน `develop` ขึ้น `master` — ไม่ใช่ทุก PR ต้อง
ถึงขั้นนี้ ปกติ PR จบที่ merge เข้า `develop` เท่านั้น

## Release PR ต้องใช้ "Create a merge commit" เท่านั้น

```bash
gh pr create --base master --head develop --title "release: ..."
```

**ห้าม squash merge PR นี้เด็ดขาด** — เคยเกิดจริง: squash-merge ทำให้ commit บน
`master` ไม่มี shared ancestry กับ `develop` อีกต่อไป พอ release รอบถัดไปจะเจอ
**conflict ปลอม** ในไฟล์ที่ไม่ได้แก้จริง (`.env.example`, `requirements.txt`,
`auth_service.py`) แก้ได้ทางเดียวคือ merge-commit เข้า master ตรงๆ อีกรอบ

ตอนขอให้ผู้ใช้ merge PR นี้ **ระบุให้ชัดว่าใช้ปุ่ม "Create a merge commit"** เพราะ
default ของ repo อาจเป็น squash

## Approve gate เป็นของผู้ใช้เท่านั้น

`deploy-production` ค้างที่สถานะ `waiting` จนกว่าจะมีคนกด approve ใน GitHub Actions UI

**อย่าพยายามข้าม กด approve แทน หรือหาทางรันสคริปต์ deploy เอง** — gate นี้ตั้งใจให้
เป็นจุดตัดสินใจของคนจริงก่อน production เปลี่ยนแปลง หน้าที่เราคือรายงานว่าอะไรกำลังจะ
ถูก deploy (โดยเฉพาะถ้ามี migration ใหม่) แล้วรอ

## Firebase: production กับ sit เป็นคนละ project

| env | `FIREBASE_PROJECT_ID` | credential |
|---|---|---|
| production | `posternung` | ไฟล์บน host จริง `/opt/posternung/secrets/` (bind-mount read-only) |
| sit (local) | `posternung-sit` | `secrets/firebase-sa-sit.json` บนเครื่อง |

**ห้ามเอา credential ของ production มาใช้ทดสอบ local/sit เด็ดขาด** — ถ้าต้องเช็คอะไร
บน production (เช่นยืนยันว่า credential โหลดได้) ให้ทำผ่าน SSH เข้า production host
โดยตรง ไม่ใช่ copy ไฟล์ลงมาที่เครื่อง

วิธีเช็คเร็วว่า credential ฝั่งไหนโหลดสำเร็จ: ยิง `/auth/firebase` ด้วย token มั่ว
- ได้ **401 `OAUTH_TOKEN_INVALID`** = credential โหลดได้ (verify แล้วปฏิเสธ token)
- ได้ **503 `OAUTH_PROVIDER_NOT_CONFIGURED`** = ยังไม่เห็น credential/`FIREBASE_PROJECT_ID`

## `deploy.sh` ต้องมี `COMPOSE_PROJECT_NAME` คงที่

`.github/scripts/deploy.sh` `export COMPOSE_PROJECT_NAME="posternung"` เองอยู่แล้ว
— แต่ถ้ารันสคริปต์ด้วยมือ (ไม่ผ่าน CI) ต้อง export ก่อนเรียก ไม่งั้น compose project
name จะมาจาก basename ของ working directory แทน ทำให้ deploy มองว่าเป็นคนละ stack
กับที่รันอยู่บน server แล้วพยายามสร้าง container ชื่อซ้ำ →
`Conflict. The container name "..." is already in use`

## เช็คก่อนขอให้ merge release PR

1. `gh pr checks <n>` — `test` ต้องผ่าน
2. `gh pr view <n> --json mergeStateStatus` — ต้อง **`CLEAN`** ไม่ใช่แค่
   `mergeable: MERGEABLE` (`MERGEABLE` แปลว่า merge ได้ ไม่ได้แปลว่า base ทันสมัย
   — `BEHIND` ก็ยัง `MERGEABLE`)
3. ถ้ามี migration ใหม่ตั้งแต่ release ก่อน — สรุปให้ผู้ใช้รู้ว่า deploy รอบนี้จะรัน
   migration อะไร (container รัน `alembic upgrade head` อัตโนมัติก่อน serve)
