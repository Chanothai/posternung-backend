---
name: docker-environments
description: >
  Docker/container operational reference สำหรับ Poster Nung backend ต่อ environment
  (dev, sit local, production) — gotchas ที่เกิดจริงและ best practice ตอนรัน,
  debug, หรือ deploy. ใช้ skill นี้เสมอเมื่อผู้ใช้จะรัน/สตาร์ท stack ด้วย docker
  compose, container ไม่ขึ้นหรือ restart วน, ต่อ localhost/LAN ไม่ได้, port ชนกัน,
  เจอ 503 ที่ดูเหมือน credential ไม่โหลด, ต้องแก้ `.env.sit`/`.env.production`,
  จะ deploy ขึ้น production, หรือต้องตรวจสุขภาพ production ผ่าน SSH — ใช้แม้ผู้ใช้
  จะพูดแค่ "รัน container", "test บน sit", "เช็ค prod" โดยไม่พูดคำว่า docker ตรงๆ
---

# Docker environments (Poster Nung)

ไฟล์นี้เก็บ **สิ่งที่เกิดจริงตอนรัน container ต่อ environment** เท่านั้น

- 12-factor, config field table, secrets policy, เหตุผลเรื่อง base+override, รูปร่าง
  CI/CD pipeline → `.claude/rules/environments.md` (path-scoped rule, โหลดเองตอน
  แตะ `docker-compose*.yml`)
- workflow เขียนโค้ด/เทส/PR → skill `ship-backend-change`
- ไฟล์นี้ไม่ทวนสิ่งเหล่านั้นซ้ำ

## แผนที่ 3 environment

| | dev | sit (local) | production |
|---|---|---|---|
| ใช้ทำอะไร | เขียนโค้ด/`pytest` ประจำวัน | ทดสอบ image จริงก่อน deploy | ของจริง |
| วิธีรัน | `docker compose up -d db` + uvicorn บน host | `docker compose -p posternung-sit -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit up -d --build` | CI เท่านั้น (ดู §5) |
| compose project | default (`posternung-backend`) | **`posternung-sit`** (ต้องระบุ `-p`) | `posternung` (ตั้งใน `deploy.sh`) |
| container app/db | — / `posternung-backend-db-1` | `posternung-sit-app` / `posternung-sit-db` | `posternung-production-app` / `-db` |
| port app | — (uvicorn บน host `:8000`) | `8000:8000` | `8000:8000` (หลัง cloudflared) |
| port db | `5432:5432` (publish) | ไม่ publish (`ports: !reset []`) | ไม่ publish |
| env file | `.env` | `.env.sit` | `.env.production` (อยู่บน host เท่านั้น) |
| Firebase project | ปิด (หรือ dummy สำหรับ mock test) | `posternung-sit` | `posternung` |

## รัน stack

```bash
# dev — ถ้า pytest ต่อ DB ไม่ได้ทั้งที่ docker ps ดูปกติ ให้ up ใหม่ผ่าน compose เสมอ
docker compose -f docker-compose.yml up -d db

# sit — ต้องมี -p แยก project เสมอ
docker compose -p posternung-sit \
  -f docker-compose.yml -f docker-compose.sit.yml \
  --env-file .env.sit up -d --build --force-recreate app
```

**ทำไมต้อง `-p`:** compose ไม่ได้ตั้งชื่อ project ให้เองอัตโนมัติต่างกันตาม override
file ที่ใช้ — ถ้าไม่ระบุ `dev` กับ `sit` จะกลายเป็น project เดียวกัน (default มาจาก
ชื่อ working directory) แล้ว compose มองว่า service `db`/`app` ของทั้งสอง env เป็น
**ตัวเดียวกัน** → รอบไหนสั่ง `up` ทีหลังจะไป recreate/แย่ง container ของอีกฝั่ง โดย
ไม่มี error เตือนล่วงหน้า

## กับดักตอนรัน

| อาการ | สาเหตุ | ทางแก้ |
|---|---|---|
| `docker compose up -d --build` แล้วโค้ดยังเป็นเวอร์ชันเก่า | `--build` build image ใหม่เสมอ แต่**ไม่ recreate container ที่รันอยู่**ถ้า compose config ไม่เปลี่ยน | เติม `--force-recreate` · ยืนยันก่อนเชื่อผล: `docker exec <container> grep -c "<marker ที่เพิ่งเขียน>" <file>` — ได้ `0` แปลว่ายังรันโค้ดเก่า |
| start db ของ sit แล้ว error `port is already allocated` | dev db ถือ `5432` อยู่ก่อนแล้ว, sit override ไม่ได้ reset ports | เช็คว่า `docker-compose.sit.yml` มี `ports: !reset []` ที่ service `db` จริง (อาจอยู่คนละ branch ที่ยังไม่ merge) |
| `docker ps` เห็น container รันปกติ แต่ต่อ DB จาก host ไม่ได้ | ใช้ `docker start` แทน compose — คืน container เดิมได้แต่ไม่รับประกันว่า port ยัง publish (เจอตอน Docker Desktop restart) | เปิด container กลับด้วย `docker compose ... up -d <service>` เสมอ ไม่ใช่ `docker start` เฉยๆ · เช็คด้วย `docker port <container>` ว่ามี mapping จริง |
| bind-mount credential แล้ว container error แบบงงๆ (เช่น `IsADirectoryError`) | source path บน host **ยังไม่มีไฟล์อยู่** ตอน `up` — Docker เห็น path ที่ยังไม่มีจะสร้างเป็น**โฟลเดอร์เปล่า**ให้เงียบๆ แทนที่จะ error ทันที | สร้างไฟล์ credential บน host **ให้เสร็จก่อน** รัน `up` เสมอ ไม่ใช่หลัง |
| เปลี่ยน `POSTGRES_PASSWORD` ใน `.env.sit` แล้ว container ต่อ DB ไม่ได้ | Postgres image ตั้ง user/password จาก env **เฉพาะตอน init data directory ที่ยังว่างเปล่า** — ถ้า volume (`pgdata-sit`) มีข้อมูลจากรอบก่อนอยู่แล้ว password ใหม่จะไม่มีผล | ลบ volume เดิมด้วย `down -v` ถ้าต้องเปลี่ยน password จริงๆ (ข้อมูล test ใน sit หายได้ ไม่ใช่ปัญหา) |

## Firebase credential ต่อ environment

โค้ด (`_ensure_firebase_app()`) รองรับ 2 ทาง — เข้าใจผิดกันบ่อยว่าเป็นตัวเดียวกัน:

| ตัวแปร | อยู่ที่ไหน | ความหมาย |
|---|---|---|
| `FIREBASE_SERVICE_ACCOUNT_PATH` | ใน `.env.<env>`, ไปโผล่เป็น env ของ **container** | path **ในคอนเทนเนอร์** ที่แอปอ่านไฟล์ credential (เช่น `/run/secrets/firebase-sa.json`) |
| `FIREBASE_SA_HOST_PATH` | ใน `.env.<env>` เช่นกัน แต่ใช้ตอน **interpolate compose file** (ไม่ใช่ env ของ container) | path **บน host** ที่มีไฟล์จริง ให้ compose เอาไป bind-mount |

ตั้งแค่ 2 ตัวนี้ไม่พอ — ต้องมี **`FIREBASE_PROJECT_ID`** ด้วย ไม่งั้น guard ใน
`firebase_login()` เห็นว่า project ID ว่างแล้วคืน 503 ทั้งที่ mount ไฟล์ credential
ถูกต้องแล้ว (503 กับ "mount ไม่ครบ" หน้าตาเหมือนกันจากมุมมอง client แต่คนละสาเหตุ)

**สัญญาณตรวจเร็วว่า credential โหลดสำเร็จ** — ยิง `/auth/firebase` ด้วย token มั่ว:
- **`401 OAUTH_TOKEN_INVALID`** = credential โหลดสำเร็จ (verify แล้วปฏิเสธ token ปลอม)
- **`503 OAUTH_PROVIDER_NOT_CONFIGURED`** = ยังไม่เห็น credential หรือ `FIREBASE_PROJECT_ID`

**production ใช้ Firebase project `posternung`, sit local ใช้ `posternung-sit`** —
คนละ project แยกกันตั้งใจ **ห้ามเอา credential ของ production มาทดสอบที่อื่นเด็ดขาด**

## Production: topology จริง (ตรวจจาก server แล้ว)

Deploy ไม่ได้ใช้ compose file ที่วางอยู่บน production host — CI checkout โค้ดสดบน
runner แล้วสั่ง `docker compose` ผ่าน **docker context ที่ชี้ไป SSH** เข้า
production daemon (`DOCKER_CONTEXT` ใน `.github/scripts/deploy.sh`) compose file
และ logic ที่ใช้จริงมาจาก runner ทั้งหมด

**ผลที่ตามมา: แก้ compose file ที่วางอยู่บน `/opt/posternung` (host) ไม่มีผลต่อ
deploy รอบถัดไปเลย** — โฟลเดอร์นั้นเป็นแค่ checkout เก่าที่ค้างไว้ ใช้เก็บ
`.env.production` (ที่ CI `scp` ไปอ่านตอน deploy) กับ `secrets/` เท่านั้น

`deploy.sh` ตั้ง `export COMPOSE_PROJECT_NAME="posternung"` เองเสมอ — ถ้าจะรัน
สคริปต์นี้ด้วยมือ (ไม่ผ่าน CI) ต้อง export ตัวแปรนี้ก่อนเรียก ไม่งั้น compose
project name จะมาจาก basename ของ working directory แทน แล้ว deploy จะมองว่าเป็น
คนละ stack กับที่รันอยู่จริง → พยายามสร้าง container ชื่อซ้ำ →
`Conflict. The container name "..." is already in use`

Traffic เข้าถึง production ผ่าน Cloudflare Tunnel (`cloudflared`, systemd service
บน host) ไป `api.posternung.com` — ไม่ได้ expose port ตรงจาก droplet

`deploy-production` job ค้างที่ `waiting` จนกว่าจะมีคนกด approve ใน GitHub Actions
UI (required reviewer) — **ห้ามพยายามข้ามหรือ approve แทนผู้ใช้**

## ตรวจสุขภาพ production แบบปลอดภัย

SSH เข้า production host ได้เพื่ออ่านสถานะ (read-only) — ห้ามแก้อะไรโดยไม่ถามก่อน
และห้าม dump ค่า secret ออกมาแสดง:

```bash
ssh deploy@<prod-host> 'docker ps --format "{{.Names}}\t{{.Status}}"'
ssh deploy@<prod-host> 'docker inspect posternung-production-app --format "{{.Config.Image}}"'
# เช็คว่ามี key credential ตั้งไว้ — เช็คแค่ "มีบรรทัดนี้ไหม" ไม่ cat ค่า:
ssh deploy@<prod-host> 'grep -c "^FIREBASE_SERVICE_ACCOUNT_PATH=" /opt/posternung/.env.production'
curl -s -o /dev/null -w "%{http_code}\n" https://api.posternung.com/health
```

ถ้าจำเป็นต้องยิง `/auth/firebase` จริงเพื่อยืนยัน credential (ดู §Firebase ด้านบน)
ใช้ **token มั่วเท่านั้น** — อย่าใช้ token จริงของ user ผ่าน production API โดยไม่มี
เหตุผลชัดเจน
