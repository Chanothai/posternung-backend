#!/usr/bin/env bash
#
# Promote/deploy image sha เดิม ไป environment ที่ระบุ (sit|uat|production)
# "Build once, deploy many": ไม่ build ใหม่ — pull image tag = git sha ที่ build job สร้างไว้
#
# ⚠️ TEMPLATE — ต้องทำ manual steps เหล่านี้เองก่อนใช้จริง (repo ไม่ตั้งให้):
#   [ ] เลือกวิธีเข้าถึง target host: self-hosted runner บน host / docker context
#       (`docker context create` ชี้ ssh://user@host) แล้วตั้ง DEPLOY_TARGET = ชื่อ context นั้น
#   [ ] `docker login ghcr.io` บน target host (หรือ imagePullSecret) ให้ pull image ได้
#   [ ] provision ไฟล์ .env.<env> (secret ของ env นั้น) ไว้ที่ target host — จาก secret
#       manager / GitHub Environment secrets (repo ไม่มีไฟล์นี้ · gitignored)
#   [ ] ตั้ง GitHub Environments (sit/uat/production) + required reviewers เป็น gate promote
#
# สคริปต์นี้ fail-fast ทุก precondition ที่ขาด — ไม่มี exit 0 แบบแกล้งสำเร็จ
#
set -euo pipefail

ENV_NAME="${1:?usage: deploy.sh <sit|uat|production>}"

case "$ENV_NAME" in
  sit|uat|production) ;;
  *) echo "invalid environment: $ENV_NAME (ต้องเป็น sit|uat|production)" >&2; exit 1 ;;
esac

: "${IMAGE_REGISTRY:?ต้องตั้ง IMAGE_REGISTRY (เช่น ghcr.io/org/repo)}"
: "${IMAGE_TAG:?ต้องตั้ง IMAGE_TAG (= git sha ที่ promote — ห้าม build ใหม่)}"
# กัน deploy ลง docker ของ CI runner เองโดยไม่ตั้งใจ — ต้องชี้ target host ชัดเจน
: "${DEPLOY_TARGET:?ต้องตั้ง DEPLOY_TARGET = docker context ของ host ปลายทาง (กัน deploy ลง runner เอง)}"

# ให้ docker compose ทุกคำสั่งด้านล่างวิ่งไปที่ host ปลายทางผ่าน context นี้
export DOCKER_CONTEXT="$DEPLOY_TARGET"

# docker compose default project name = basename ของ working directory ตอนรัน คำสั่งนี้
# ต่างกันระหว่าง manual deploy (cwd /opt/posternung → project "posternung") กับ CI runner
# (actions/checkout clone เข้า dir ชื่อ repo "poster-nung-backend" → project
# "poster-nung-backend") — คนละ project label ทำให้ compose มองว่าเป็นคนละ stack กัน
# ทั้งที่ container_name: ชี้ชื่อเดียวกัน (posternung-<env>-app/db) → พยายามสร้าง
# container ซ้ำชื่อเดิม แล้ว conflict กับของเดิมที่มีอยู่แล้ว (เจอจริงตอน deploy-production
# ครั้งแรกผ่าน CI) ต้อง pin ชื่อ project ให้ตรงกันเสมอไม่ว่าจะรันจากไหน
# หมายเหตุ: ถ้าอนาคตมี sit/uat มา deploy บน host เดียวกันจริง ต้องแยก
# COMPOSE_PROJECT_NAME ต่อ env (เช่น posternung-sit) กันชนกันเรื่อง default network —
# ตอนนี้ยังมีแค่ production เดียวจึงยังไม่ต้องแยก
export COMPOSE_PROJECT_NAME="posternung"

ENV_FILE=".env.${ENV_NAME}"
OVERRIDE="docker-compose.${ENV_NAME}.yml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ไม่พบ $ENV_FILE บน target host — ต้อง provision secret ของ $ENV_NAME ก่อน deploy" >&2
  exit 1
fi

# MEDIA_BASE_URL เป็น required setting (ADR-0006) — app/core/config.py fail fast ตอน
# boot ถ้าค่านี้ว่างหรือไม่มี scheme http(s):// เช็คแค่ "มีบรรทัดไม่ว่าง" ที่นี่ (ไม่ parse
# ค่าเต็มตามกฎ validator ของแอป — deploy.sh ไม่ควรผูกกับ business logic นั้น) เพื่อกัน
# crash-loop เงียบๆ หลัง deploy แทนที่จะรู้ตัวหลัง container ขึ้นแล้วตายทันที
if ! grep -qE '^MEDIA_BASE_URL=.+' "$ENV_FILE"; then
  echo "MEDIA_BASE_URL ไม่มีหรือว่างใน $ENV_FILE บน target host — app จะ crash-loop ตอน boot (ADR-0006) ต้องเติมค่านี้บน target host ก่อน deploy" >&2
  exit 1
fi

echo "==> Deploying $IMAGE_REGISTRY:$IMAGE_TAG to $ENV_NAME"

# IMAGE_REGISTRY/IMAGE_TAG ส่งเข้า compose ผ่าน env (substitute ${IMAGE_*} ใน base compose)
export IMAGE_REGISTRY IMAGE_TAG

# pull sha ที่ระบุ แล้ว up ใหม่ โดย --no-build (ใช้ image ที่ build ครั้งเดียวเท่านั้น)
docker compose \
  -f docker-compose.yml \
  -f "$OVERRIDE" \
  --env-file "$ENV_FILE" \
  pull app

docker compose \
  -f docker-compose.yml \
  -f "$OVERRIDE" \
  --env-file "$ENV_FILE" \
  up -d --no-build

# ---- ด่านหลัง deploy: image ที่เพิ่งขึ้นต้องรู้จัก migration ครบเท่าโค้ด (BL-88) ----
#
# 🔴 ไม่มีอะไรฟ้องเลยเมื่อ image เก่ากว่า migration ในโค้ด — `alembic upgrade head`
# ในคอนเทนเนอร์ **จบเงียบ ๆ exit 0** เพราะมันไม่เห็นไฟล์ revision ใหม่ · และ `CMD`
# ของ image ก็รัน upgrade ตอน start อยู่แล้ว ทำให้ output ของ "migrate ครบแล้ว" กับ
# "image ไม่รู้จัก migration ใหม่" **หน้าตาเหมือนกันเป๊ะ**
#
# รอบ 2026-08-07 รอดมาเพราะคน `ls` ไฟล์ revision ในคอนเทนเนอร์ด้วยมือก่อน migrate —
# ด่านนี้ทำให้ไม่ต้องพึ่งว่าใครจำได้
#
# --wait: `CMD` เพิ่งเริ่มรัน `alembic upgrade head` ตอน `up -d` เมื่อกี้ ยังไม่จบ
# · ตัวเช็ครอเฉพาะอาการที่เวลาแก้ได้ (DB ตามไม่ทัน) ส่วนอาการเรื่อง image ผิดตัว
# ตอบทันทีไม่รอ เพราะรอไปก็ไม่หาย
APP_CONTAINER="posternung-${ENV_NAME}-app"
echo "==> ตรวจว่า image รู้จัก migration ครบเท่าโค้ด ($APP_CONTAINER)"
python3 scripts/check_container_migrations.py "$APP_CONTAINER" --wait 90

echo "==> $ENV_NAME now running $IMAGE_REGISTRY:$IMAGE_TAG"
