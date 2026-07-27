# Release develop → master และ deploy production

อ่านไฟล์นี้เมื่อพร้อม release ของที่รวมอยู่ใน `develop` ขึ้น `master` (= deploy
trigger) — ไม่ใช่ทุก PR ต้องทำขั้นนี้ ปกติ PR ธรรมดาจบที่ merge เข้า `develop`
เท่านั้น

## Release PR — ต้อง "Create a merge commit" เท่านั้น

```bash
gh pr create --base master --head develop --title "release: ..."
```

**ห้าม squash merge PR นี้เด็ดขาด** — เคยเกิดปัญหาจริง: squash-merge ทำให้ commit บน
`master` ไม่มี shared ancestry กับ `develop` อีกต่อไป พอ release รอบถัดไป (หรือ
reconciliation PR) จะเจอ conflict ปลอมในไฟล์ที่ไม่ได้แก้จริง (เช่น `.env.example`,
`requirements.txt`) ต้องแก้ด้วยการ merge-commit-เข้า-master-ตรงๆ อีกรอบถึงจะหาย

เวลาขอให้ user merge PR นี้ ให้ระบุชัดว่า **"Create a merge commit"** ไม่ใช่ปุ่ม
default ที่บาง repo ตั้งเป็น squash

## Deploy-production มี required-reviewer gate

Push เข้า `master` trigger CI/CD (`test` → `build` → `deploy-production`) แต่
`deploy-production` job ผูก GitHub Environment `production` ที่มี **required
reviewer** — ต้องมี user คนจริงกด approve ใน GitHub Actions UI ก่อนถึงจะรันต่อ
(`gh pr checks`/`gh run view` จะโชว์ job นี้ค้างที่ `waiting` จนกว่าจะ approve)

**อย่าพยายามข้ามขั้นนี้หรือหาทาง approve แทนผู้ใช้** — เป็น manual gate ที่ตั้งใจ
ออกแบบไว้ให้เป็นจุดตัดสินใจของคนจริงก่อน production เปลี่ยนแปลง

## Production ใช้ Firebase project คนละตัวกับ sit/dev

- **Production**: `FIREBASE_PROJECT_ID=posternung`, credential เป็นไฟล์
  bind-mount (`FIREBASE_SERVICE_ACCOUNT_PATH=/run/secrets/firebase-sa.json`)
  อยู่บน `deploy@<prod-host>:/opt/posternung/secrets/`
- **sit (local)**: `FIREBASE_PROJECT_ID=posternung-sit` — คนละ project, คนละ
  credential

**ห้ามเอา credential ของ production มาทดสอบ local หรือ sit เด็ดขาด** — ถ้าจำเป็น
ต้องเช็คอะไรบน production (เช่น verify credential โหลดได้จริง) ให้ทำผ่าน SSH
เข้า production host โดยตรง ไม่ใช่ copy ไฟล์ credential ลงมาที่เครื่อง local

## deploy.sh ต้องรันด้วย `COMPOSE_PROJECT_NAME` คงที่

`.github/scripts/deploy.sh` ตั้ง `export COMPOSE_PROJECT_NAME="posternung"` เอง
เสมอ — ถ้าจะรันสคริปต์นี้ด้วยมือ (ไม่ผ่าน CI) ต้อง export ตัวแปรนี้ก่อนเรียก ไม่งั้น
compose project name จะมาจาก basename ของ working directory แทน (เช่น
`poster-nung-backend` ถ้ารันจาก CI runner checkout dir) ทำให้ deploy ครั้งถัดไป
มองว่าเป็นคนละ stack กับที่รันอยู่จริงบน server แล้วพยายามสร้าง container ชื่อซ้ำ
→ `Conflict. The container name "..." is already in use`

## ลำดับตรวจก่อน merge release PR

1. `gh pr checks <n>` — `test` ต้องผ่าน
2. `gh pr view <n> --json mergeStateStatus` — ต้อง `CLEAN` ไม่ใช่แค่ `MERGEABLE`
   เฉยๆ (`MERGEABLE` แปลว่า merge ได้ ไม่ได้แปลว่าไม่มี conflict — เช็ค
   `mergeStateStatus` ให้ชัดอีกที)
3. ถ้ามี migration ใหม่ตั้งแต่ release ก่อนหน้า — สรุปให้ user รู้ว่า deploy รอบนี้
   จะรัน migration อะไรบ้าง (deploy container รัน `alembic upgrade head`
   อัตโนมัติก่อน serve)
