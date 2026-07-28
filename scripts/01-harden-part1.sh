#!/usr/bin/env bash
#
# Ubuntu initial security hardening — PART 1 (steps 1-5)
# =====================================================
# Run this as root (or via sudo) on the TARGET Ubuntu server.
# It performs the non-destructive groundwork and then STOPS, so you can
# verify that the new user can log in with the SSH key BEFORE anything
# that could lock you out (that happens in Part 2).
#
#   sudo bash 01-harden-part1.sh
#
# After it stops: open a SECOND terminal (keep this one open!) and test:
#   ssh -p <SSH_PORT> <NEW_USER>@<server-ip>
# Only when that works, run 02-harden-part2.sh.
#
# The script is idempotent — safe to re-run if interrupted.
# ---------------------------------------------------------------------------

set -euo pipefail

# ======= REVIEW THESE BEFORE RUNNING =======================================
NEW_USER="deploy"          # <-- name of the non-root sudo user to create
TIMEZONE="Asia/Bangkok"
SWAP_SIZE="2G"             # size of the swap file
SWAPPINESS=10
# SSH_PORT is auto-detected from the port THIS session came in on, so UFW /
# fail2ban in Part 2 open the correct port even if SSH is not on 22.
# Override by exporting SSH_PORT before running, e.g.  SSH_PORT=2222 sudo -E bash ...
SSH_PORT="${SSH_PORT:-}"
# ===========================================================================

# --- helpers ---------------------------------------------------------------
log()  { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
ok()   { printf '    \033[1;32m✔\033[0m %s\n' "$*"; }
warn() { printf '    \033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "ต้องรันเป็น root — ใช้: sudo bash $0"
command -v apt-get >/dev/null 2>&1 || die "ไม่ใช่ระบบ Debian/Ubuntu (ไม่มี apt-get)"

# Detect the SSH port of the CURRENT connection (last field of SSH_CONNECTION).
if [ -z "$SSH_PORT" ]; then
    if [ -n "${SSH_CONNECTION:-}" ]; then
        SSH_PORT="${SSH_CONNECTION##* }"
    else
        SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"
    fi
fi
[ -n "$SSH_PORT" ] || SSH_PORT=22
printf 'Detected/using SSH port: %s   (new user: %s)\n' "$SSH_PORT" "$NEW_USER"
# Persist SSH_PORT so Part 2 reuses the exact same value.
printf 'SSH_PORT=%s\nNEW_USER=%s\n' "$SSH_PORT" "$NEW_USER" > /root/.hardening-vars
chmod 600 /root/.hardening-vars

export DEBIAN_FRONTEND=noninteractive

# ===========================================================================
# 1. Update package list + upgrade
# ===========================================================================
log "1/5  apt update + upgrade"
apt-get update
apt-get -y -o Dpkg::Options::="--force-confold" -o Dpkg::Options::="--force-confdef" upgrade
ok "ระบบ upgrade แล้ว"
if [ -f /var/run/reboot-required ]; then
    warn "ต้อง reboot (มี kernel/lib ใหม่) — reboot ก่อนรัน Part 2 ได้ ปลอดภัย"
fi

# ===========================================================================
# 2. Timezone + NTP
# ===========================================================================
log "2/5  Timezone = $TIMEZONE + NTP sync"
timedatectl set-timezone "$TIMEZONE"
timedatectl set-ntp true
ok "ตั้งค่าแล้ว — verify:"
timedatectl show -p Timezone -p NTP -p NTPSynchronized | sed 's/^/    /'

# ===========================================================================
# 3. Swap file + swappiness (persist)
# ===========================================================================
log "3/5  Swap file $SWAP_SIZE + vm.swappiness=$SWAPPINESS"
if swapon --show=NAME --noheadings | grep -qx /swapfile; then
    ok "/swapfile active อยู่แล้ว — ข้ามการสร้าง"
else
    if [ ! -f /swapfile ]; then
        if ! fallocate -l "$SWAP_SIZE" /swapfile 2>/dev/null; then
            warn "fallocate ใช้ไม่ได้กับ filesystem นี้ — ใช้ dd แทน"
            # strip trailing G -> count in MiB
            size_mb=$(( ${SWAP_SIZE%G} * 1024 ))
            dd if=/dev/zero of=/swapfile bs=1M count="$size_mb" status=progress
        fi
    fi
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    ok "สร้าง + เปิด swap แล้ว"
fi
# persist ใน fstab (idempotent)
if ! grep -qE '^\s*/swapfile\s' /etc/fstab; then
    printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
    ok "เพิ่ม /swapfile เข้า /etc/fstab (persist หลัง reboot)"
else
    ok "/etc/fstab มี /swapfile อยู่แล้ว"
fi
# swappiness persist
printf 'vm.swappiness=%s\n' "$SWAPPINESS" > /etc/sysctl.d/99-swappiness.conf
sysctl --system >/dev/null
ok "verify:"
swapon --show | sed 's/^/    /'
printf '    vm.swappiness = %s\n' "$(cat /proc/sys/vm/swappiness)"

# ===========================================================================
# 4. Non-root user + sudo
# ===========================================================================
log "4/5  สร้าง user '$NEW_USER' + sudo"
if id "$NEW_USER" >/dev/null 2>&1; then
    ok "user '$NEW_USER' มีอยู่แล้ว — ข้ามการสร้าง"
else
    adduser --disabled-password --gecos "" "$NEW_USER"
    ok "สร้าง user '$NEW_USER' แล้ว (ยังไม่มี password)"
fi
usermod -aG sudo "$NEW_USER"
ok "ใส่ '$NEW_USER' เข้ากลุ่ม sudo แล้ว"

# ตั้ง password ให้ user เพื่อให้ 'sudo' ยังต้อง authenticate ได้
# (การปิด PasswordAuthentication ใน Part 2 ปิดแค่ SSH — sudo ยังใช้ password นี้)
#
# ทางเลือก: ถ้าต้องการ passwordless sudo (สะดวกกว่าแต่ปลอดภัยน้อยกว่า) ให้ comment
# บล็อก passwd ข้างล่างนี้ แล้ว uncomment 2 บรรทัดนี้แทน:
#   printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$NEW_USER" > /etc/sudoers.d/90-$NEW_USER
#   chmod 440 /etc/sudoers.d/90-$NEW_USER
if passwd --status "$NEW_USER" | awk '{print $2}' | grep -qE '^(P|PS)$'; then
    ok "user '$NEW_USER' มี password ตั้งไว้แล้ว — ข้าม"
else
    warn "ตั้ง password ให้ '$NEW_USER' (ใช้ตอน sudo) — กรอกด้านล่าง:"
    passwd "$NEW_USER"
fi
ok "verify: $(id "$NEW_USER")"

# ===========================================================================
# 5. Copy SSH key root -> new user, perms 700/600, then STOP
# ===========================================================================
log "5/5  Copy SSH authorized_keys -> '$NEW_USER'"
ROOT_KEYS="/root/.ssh/authorized_keys"
# GUARD สำคัญ: ถ้า root ไม่มี key ห้ามทำต่อ ไม่งั้น Part 2 (ปิด password auth) = lock out ถาวร
if [ ! -s "$ROOT_KEYS" ]; then
    die "ไม่พบ/ไฟล์ว่าง: $ROOT_KEYS
    ต้องมี SSH public key ของ root ก่อน (ที่คุณใช้ login อยู่ตอนนี้)
    ถ้าไม่มี key — อย่ารัน Part 2 เด็ดขาด เพราะจะปิด password login แล้วเข้าไม่ได้อีก"
fi
USER_SSH="/home/$NEW_USER/.ssh"
mkdir -p "$USER_SSH"
cp "$ROOT_KEYS" "$USER_SSH/authorized_keys"
chmod 700 "$USER_SSH"
chmod 600 "$USER_SSH/authorized_keys"
chown -R "$NEW_USER:$NEW_USER" "$USER_SSH"
ok "copy key แล้ว — verify perms:"
printf '    dir : %s\n' "$(stat -c '%a %U:%G %n' "$USER_SSH")"
printf '    file: %s\n' "$(stat -c '%a %U:%G %n' "$USER_SSH/authorized_keys")"

# ---------------------------------------------------------------------------
cat <<EOF

$(printf '\033[1;33m')############################################################################
#                          หยุดตรงนี้  (STOP)                               #
############################################################################$(printf '\033[0m')

Part 1 เสร็จแล้ว. ก่อนรัน Part 2 (ซึ่งจะปิด root login + password auth):

  1) อย่าปิด session นี้
  2) เปิด terminal ใหม่อีกหน้าต่าง แล้วทดสอบ login ด้วย user ใหม่:

         ssh -p $SSH_PORT $NEW_USER@<server-ip>

     - ต้อง login เข้าได้ด้วย SSH key (ไม่ถาม password)
     - ลอง 'sudo -v' ให้แน่ใจว่า sudo ใช้ได้

  3) เมื่อยืนยันว่าเข้าได้จริงแล้ว ค่อยรัน:

         sudo bash 02-harden-part2.sh

ค่า SSH_PORT=$SSH_PORT และ NEW_USER=$NEW_USER ถูกบันทึกไว้ที่ /root/.hardening-vars
Part 2 จะอ่านค่าเดิมนี้ให้อัตโนมัติ
EOF
