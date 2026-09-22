#!/usr/bin/env bash
#
# posternung deploy prep — install Docker Engine + Compose on the (hardened) server
# =================================================================================
# Run as root/sudo on the target Ubuntu server AFTER the hardening scripts.
#
#   sudo bash 03-server-docker-setup.sh
#
# Installs Docker Engine + compose plugin from Docker's official apt repo, adds the
# deploy user to the docker group, and creates the deploy directory. Idempotent.
# ---------------------------------------------------------------------------------

set -euo pipefail

DEPLOY_DIR="/opt/posternung"

log()  { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
ok()   { printf '    \033[1;32m✔\033[0m %s\n' "$*"; }
warn() { printf '    \033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "ต้องรันเป็น root — ใช้: sudo bash $0"
command -v apt-get >/dev/null 2>&1 || die "ไม่ใช่ Ubuntu/Debian (ไม่มี apt-get)"

# --- deploy user: อ่านจากไฟล์ที่ hardening Part 1 เขียนไว้ (fallback 'deploy') --------
NEW_USER="deploy"
if [ -f /root/.hardening-vars ]; then
    # shellcheck disable=SC1091
    . /root/.hardening-vars
fi
id "$NEW_USER" >/dev/null 2>&1 || die "ไม่พบ user '$NEW_USER' — รัน hardening Part 1 ก่อน"
printf 'Deploy user: %s\n' "$NEW_USER"

export DEBIAN_FRONTEND=noninteractive

# ===========================================================================
# 1. Docker's official apt repository
# ===========================================================================
log "1/4  ตั้งค่า Docker official apt repo"
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.asc ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    ok "เพิ่ม Docker GPG key"
else
    ok "Docker GPG key มีอยู่แล้ว"
fi
ARCH="$(dpkg --print-architecture)"
CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$ARCH" "$CODENAME" > /etc/apt/sources.list.d/docker.list
ok "เขียน /etc/apt/sources.list.d/docker.list ($CODENAME)"

# ===========================================================================
# 2. Install Docker Engine + compose plugin
# ===========================================================================
log "2/4  ติดตั้ง Docker Engine + compose plugin"
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
ok "ติดตั้งแล้ว: $(docker --version)"
ok "$(docker compose version)"

# ===========================================================================
# 3. deploy user เข้ากลุ่ม docker + สร้าง deploy dir
# ===========================================================================
log "3/4  ตั้งค่า deploy user + directory"
usermod -aG docker "$NEW_USER"
ok "ใส่ '$NEW_USER' เข้ากลุ่ม docker (ต้อง re-login ให้มีผล)"
install -d -o "$NEW_USER" -g "$NEW_USER" "$DEPLOY_DIR"
ok "สร้าง deploy dir: $DEPLOY_DIR (เจ้าของ $NEW_USER)"

# ===========================================================================
# 4. Verify
# ===========================================================================
log "4/4  Verify"
docker run --rm hello-world >/dev/null 2>&1 && ok "docker run hello-world สำเร็จ" \
    || warn "docker run hello-world ไม่ผ่าน — ดู 'systemctl status docker'"

cat <<EOF

$(printf '\033[1;32m')Docker พร้อมแล้ว.$(printf '\033[0m')  ขั้นต่อไป (ดู DEPLOY-SETUP.md):
  1) ออกจาก session แล้ว login '$NEW_USER' ใหม่ (ให้ docker group มีผล) แล้วลอง:
         docker run --rm hello-world     # ต้องรันได้โดยไม่ต้อง sudo
  2) เอา compose files + สร้าง .env.sit ใน $DEPLOY_DIR แล้ว pull + up (ดู guide)
EOF
