#!/usr/bin/env bash
#
# Ubuntu initial security hardening — PART 2 (steps 6-10)
# =====================================================
# Run this ONLY AFTER you have confirmed, in a separate terminal, that the
# new user can log in with the SSH key and use sudo. This part enables the
# firewall and disables root SSH login + password auth — a mistake here can
# lock you out, which is why Part 1 stopped first.
#
#   sudo bash 02-harden-part2.sh
#
# Idempotent — safe to re-run.
# ---------------------------------------------------------------------------

set -euo pipefail

# --- helpers ---------------------------------------------------------------
log()  { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
ok()   { printf '    \033[1;32m✔\033[0m %s\n' "$*"; }
warn() { printf '    \033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "ต้องรันเป็น root — ใช้: sudo bash $0"
command -v apt-get >/dev/null 2>&1 || die "ไม่ใช่ระบบ Debian/Ubuntu (ไม่มี apt-get)"

# --- load vars saved by Part 1 (SSH_PORT, NEW_USER) ------------------------
NEW_USER="${NEW_USER:-deploy}"
SSH_PORT="${SSH_PORT:-}"
if [ -f /root/.hardening-vars ]; then
    # shellcheck disable=SC1091
    . /root/.hardening-vars
fi
if [ -z "${SSH_PORT:-}" ]; then
    if [ -n "${SSH_CONNECTION:-}" ]; then SSH_PORT="${SSH_CONNECTION##* }"
    else SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"; fi
fi
[ -n "$SSH_PORT" ] || SSH_PORT=22
printf 'Using SSH port: %s   new user: %s\n' "$SSH_PORT" "$NEW_USER"

export DEBIAN_FRONTEND=noninteractive

# --- SAFETY GUARD: ยืนยันว่า new-user login ทดสอบแล้ว --------------------------
USER_KEYS="/home/$NEW_USER/.ssh/authorized_keys"
[ -s "$USER_KEYS" ] || die "ไม่พบ $USER_KEYS — รัน Part 1 ให้ผ่านก่อน"
cat <<EOF

$(printf '\033[1;33m')ก่อนทำต่อ: ยืนยันว่าคุณทดสอบแล้วว่า login ด้วย '$NEW_USER' + SSH key สำเร็จ
และ 'sudo' ใช้ได้ (จาก terminal อีกหน้าต่าง). Part 2 จะปิด root login + password auth.$(printf '\033[0m')
EOF
read -r -p "พิมพ์ 'yes' เพื่อยืนยันและทำต่อ: " CONFIRM
[ "$CONFIRM" = "yes" ] || die "ยกเลิก — ยังไม่ได้ยืนยัน (ทดสอบ login ให้ผ่านก่อน)"

# ===========================================================================
# 6. UFW — allow SSH BEFORE enabling, then 22/80/443
# ===========================================================================
log "6/10  UFW firewall"
apt-get install -y ufw
# ตั้ง default policy ก่อน
ufw default deny incoming
ufw default allow outgoing
# *** allow SSH ก่อน enable เสมอ (กัน lock out) ***
ufw allow OpenSSH || true                 # app profile = 22/tcp
ufw allow "${SSH_PORT}/tcp"               # เผื่อ SSH ไม่ได้อยู่ port 22
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ok "UFW เปิดแล้ว (allow SSH:$SSH_PORT, 80, 443)"

# ===========================================================================
# 7. IPv6 — ถ้าเปิดอยู่ ให้ UFW ครอบ IPv6 ด้วย
# ===========================================================================
log "7/10  ตรวจสอบ IPv6"
ipv6_disabled="$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6 2>/dev/null || echo 1)"
has_global_v6="$(ip -6 addr show scope global 2>/dev/null | grep -c 'inet6' || true)"
if [ "$ipv6_disabled" = "0" ] || [ "${has_global_v6:-0}" -gt 0 ]; then
    ok "IPv6 เปิดอยู่ — ตั้ง UFW ให้ครอบ IPv6 (IPV6=yes)"
    if grep -qE '^\s*IPV6=' /etc/default/ufw; then
        sed -i 's/^\s*IPV6=.*/IPV6=yes/' /etc/default/ufw
    else
        printf 'IPV6=yes\n' >> /etc/default/ufw
    fi
    ufw reload
    ok "UFW reload แล้ว (rule ครอบทั้ง IPv4 + IPv6)"
else
    warn "IPv6 ปิดอยู่บน host นี้ — ไม่ต้องตั้ง UFW IPv6 เพิ่ม"
fi

# ===========================================================================
# 8. Disable root SSH login + password authentication
# ===========================================================================
log "8/10  ปิด root SSH login + password auth"
DROPIN="/etc/ssh/sshd_config.d/00-hardening.conf"
mkdir -p /etc/ssh/sshd_config.d
# ตั้งชื่อ 00- ให้ sshd อ่าน "ก่อน" 50-cloud-init.conf — sshd ใช้ first-match-wins
cat > "$DROPIN" <<EOF
# managed by hardening script — do not edit by hand
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
EOF
chmod 644 "$DROPIN"
# validate ก่อน reload — ถ้า config พังจะไม่ reload (กัน sshd ตาย)
sshd -t
systemctl reload ssh 2>/dev/null || systemctl reload sshd
ok "reload sshd แล้ว (reload ไม่ตัด session ที่ต่ออยู่) — verify ค่า effective จริง:"
sshd -T | grep -Ei '^(permitrootlogin|passwordauthentication|pubkeyauthentication) ' | sed 's/^/    /'

# ===========================================================================
# 9. fail2ban — ป้องกัน brute-force SSH
# ===========================================================================
log "9/10  fail2ban"
apt-get install -y fail2ban
cat > /etc/fail2ban/jail.local <<EOF
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
port    = $SSH_PORT
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban
sleep 2
ok "fail2ban ทำงานแล้ว — verify:"
fail2ban-client status sshd 2>/dev/null | sed 's/^/    /' || warn "jail sshd ยังไม่ขึ้น (ดู 'systemctl status fail2ban')"

# ===========================================================================
# 10. unattended-upgrades — security patch อัตโนมัติ
# ===========================================================================
log "10/10  unattended-upgrades"
apt-get install -y unattended-upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
# auto-reboot ปิดไว้ (ปลอดภัยกว่า). ถ้าต้องการให้ reboot อัตโนมัติตอนตี 3 เมื่อจำเป็น
# ให้ uncomment 2 บรรทัดใน /etc/apt/apt.conf.d/50unattended-upgrades:
#   Unattended-Upgrade::Automatic-Reboot "true";
#   Unattended-Upgrade::Automatic-Reboot-Time "03:00";
systemctl enable --now unattended-upgrades
ok "เปิด unattended-upgrades แล้ว — verify:"
apt-config dump 2>/dev/null | grep -i 'Periodic::\(Update-Package-Lists\|Unattended-Upgrade\)' | sed 's/^/    /' || true

# ===========================================================================
# สรุป + output ให้ตรวจสอบ
# ===========================================================================
log "สรุปสถานะ hardening"
cat <<EOF
    [1] apt update+upgrade ....... done (Part 1)
    [2] timezone Asia/Bangkok+NTP  done (Part 1)
    [3] swap 2G + swappiness=10 ... done (Part 1)
    [4] non-root sudo user ....... $NEW_USER (Part 1)
    [5] ssh key copied 700/600 ... done (Part 1)
    [6] UFW allow SSH:$SSH_PORT,80,443  done
    [7] IPv6 coverage ............ done
    [8] root login + pw auth ..... DISABLED
    [9] fail2ban (sshd) .......... enabled
    [10] unattended-upgrades ..... enabled
EOF

log "ufw status verbose"
ufw status verbose

log "systemctl status fail2ban"
systemctl status fail2ban --no-pager || true

log "เสร็จสิ้น — ยังคง session นี้ไว้ แล้วเปิด terminal ใหม่ทดสอบ:  ssh -p $SSH_PORT $NEW_USER@<server-ip>"
