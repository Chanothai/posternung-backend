---
paths:
  - "app/core/config.py"
  - "app/main.py"
  - "docker-compose*.yml"
  - "Dockerfile"
  - ".dockerignore"
  - ".env.example"
  - ".github/workflows/**"
  - ".github/scripts/**"
---

# Environment & Deployment Rules

> แหล่งเดียวของเรื่อง environment/deploy ใน repo (path-scoped — โหลดเข้า context เฉพาะตอนแตะไฟล์ config/deploy)
> รวมจาก `backend-setup-step-by-step.md` เดิม (ที่เคยอยู่นอก repo) — ไฟล์นอก repo นั้น superseded แล้ว

## หลักการ (12-Factor)
**Build once, deploy many, config via environment เท่านั้น** — image เดียว (tag = git sha) deploy ได้ทั้ง sit/uat/production พฤติกรรมโค้ดเหมือนกันทุก env ต่างกันได้เฉพาะจาก **environment variable**
- ❌ ห้าม `if env == "production"` กระจายใน business logic
- ✅ ต่างกันได้ผ่าน config เท่านั้น; guardrail รวมศูนย์อยู่ที่ `app/core/config.py` (`_enforce_production_safety`)
- business logic / validation / error code / response shape ต้องเหมือนกันทุก env

## Local setup (จาก setup guide เดิม)
- Python 3.11–3.13 (venv): `python3 -m venv venv && source venv/bin/activate`
- ติดตั้ง deps: `pip install -r requirements.txt`
  - ⚠️ **zsh** (default macOS) ตีความ `[...]` เป็น glob — ต้อง quote package ที่มีวงเล็บเหลี่ยม เช่น `"uvicorn[standard]"`
- DB (local dev): `docker compose up -d db` แล้วรัน `uvicorn app.main:app` บน host
  - local `.env` ใช้ `DATABASE_URL=...@localhost:5432/...` (app รันบน host)
  - แต่ app ที่รัน **ใน container** ต้องใช้ host `db` ไม่ใช่ `localhost` → `.env.<env>` ตั้ง DATABASE_URL ชี้ `@db:5432`

## Config fields (`app/core/config.py` — UPPERCASE, อ่านจาก env)
| field | note |
|---|---|
| `ENVIRONMENT` | **required** `sit\|uat\|production` — ขาด/ผิดค่า = fail fast ตอน boot |
| `DEBUG`, `DOCS_ENABLED` | production **ต้อง false ทั้งคู่** (config validator บังคับ raise ถ้าไม่ใช่) |
| `CORS_ORIGINS` | comma-separated string → list (ต่าง env ต่างค่า) |
| `RESERVE_TTL_MINUTES` | F3 (ยังไม่มี consumer) |
| `DATABASE_URL`, `JWT_SECRET`, `JWT_*` | secret — placeholder เท่านั้นใน `.env.example` |

## Secrets (Global Rule 7 + rule ท้าย CLAUDE.md)
- `.env.example` = committed, **placeholder เท่านั้น** — ห้ามค่าที่ใช้งานได้จริงแม้ local
- `.env` / `.env.sit` / `.env.uat` / `.env.production` = gitignored (`.env.*`, ยกเว้น `!.env.example`) — สร้างตอน deploy, inject ผ่าน env
- ห้าม secret เดียวกันข้าม env · ห้าม sit/uat ชี้ production DB · ห้าม production PII ที่ไม่ mask ใน sit/uat

## Docker Compose (base + per-env override)
```bash
docker compose -f docker-compose.yml -f docker-compose.<env>.yml --env-file .env.<env> up -d
```
- base = `app` + `db`; override (`docker-compose.<env>.yml`) ตั้ง image sha, `env_file: .env.<env>`, container_name, volume แยก, production ใช้ `ports: !reset []` (ไม่ expose DB)
- **ทำไม base+override ไม่ใช่ `--env-file` อย่างเดียว:** `--env-file` สลับได้แค่ *ค่า* ตัวแปร — เปลี่ยน *topology* (image tag / container name / เปิด-ปิด port ต่อ env) ไม่ได้ ต้องใช้ override; ใช้คู่กันคือ idiomatic
- deploy: `--no-build` + `pull` (ใช้ image sha ที่ build ครั้งเดียว ห้าม build ใหม่)

## CI/CD (`.github/workflows/test.yml` — ไฟล์เดียว)
`test` (F6: postgres + alembic + pytest + ruff + black) → `build` (`needs: test`, image tag=sha, push ghcr.io) → `deploy-sit` → `deploy-uat` → `deploy-production` (promote **sha เดิม** ไม่ build ใหม่)
- อยู่ไฟล์เดียวเพราะ GitHub Actions `needs:` อ้าง job ข้ามไฟล์ไม่ได้ (แยกไฟล์ต้องใช้ `workflow_run`)
- gate promote uat/production = **GitHub Environment required reviewers**
- `.github/scripts/deploy.sh` เป็น template — ต้องต่อกับ target host จริง (self-hosted runner / docker context / ssh) + provision `.env.<env>` ที่ host
