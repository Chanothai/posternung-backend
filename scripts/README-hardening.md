# Ubuntu Initial Security Hardening

Reviewable, idempotent scripts implementing the 10-step hardening in the
requested order — split into **two parts** with a mandatory manual checkpoint
between them so you cannot get locked out.

> These are meant to be **reviewed and run by you** on the target Ubuntu server.
> Nothing was run from the Mac (it's macOS — no `apt`/`ufw`/`systemd`), and the
> scripts were **static-checked only** (`bash -n`), not executed against a real
> server. Read them before running.

## Files
| File | Steps | When to run |
|------|-------|-------------|
| `01-harden-part1.sh` | 1–5 | First. Ends with a **hard STOP**. |
| `02-harden-part2.sh` | 6–10 | Only **after** confirming new-user SSH login works. |

## Before you run — review the variables at the top of `01-harden-part1.sh`
| Variable | Default | Notes |
|----------|---------|-------|
| `NEW_USER` | `deploy` | The non-root sudo user to create. Change if you want another name. |
| `TIMEZONE` | `Asia/Bangkok` | |
| `SWAP_SIZE` | `2G` | |
| `SWAPPINESS` | `10` | |
| `SSH_PORT` | *auto-detected* | Taken from the port your **current** SSH session came in on, so UFW/fail2ban open the right port even if SSH isn't on 22. Override with `SSH_PORT=2222 sudo -E bash 01-harden-part1.sh`. |

Two decisions worth a look before running:
- **sudo auth model** — Part 1 sets a **password** for the new user (so `sudo`
  still requires authentication after SSH password login is disabled). If you'd
  rather have **passwordless sudo** (convenient, less secure), the script has a
  clearly-marked commented block to switch to `/etc/sudoers.d/`.
- **auto-reboot** — `unattended-upgrades` is enabled but **auto-reboot is off**.
  Instructions to turn it on are commented in Part 2 step 10.

## How to run

```bash
# copy both scripts to the server (as root or a user that can sudo)
scp 01-harden-part1.sh 02-harden-part2.sh root@<server-ip>:/root/

# on the server:
sudo bash 01-harden-part1.sh
```

### ⛔ The checkpoint (do NOT skip)
When Part 1 finishes it stops and tells you to verify login. **Keep your current
root session open**, open a **second terminal**, and test:

```bash
ssh -p <SSH_PORT> <NEW_USER>@<server-ip>
sudo -v          # confirm sudo works
```

Only when that succeeds:

```bash
sudo bash 02-harden-part2.sh     # it will ask you to type 'yes' to confirm
```

Part 2 reads the `SSH_PORT`/`NEW_USER` chosen in Part 1 from
`/root/.hardening-vars`, so they always match.

## What each step does
1. `apt update` + `apt upgrade` (non-interactive, keeps existing configs)
2. Timezone `Asia/Bangkok` + `timedatectl set-ntp true`
3. 2 GB `/swapfile` (chmod 600), `swapon`, persisted in `/etc/fstab`,
   `vm.swappiness=10` in `/etc/sysctl.d/99-swappiness.conf`
4. `adduser --disabled-password` + add to `sudo` group + set a password
5. Copy `/root/.ssh/authorized_keys` → new user, `700` dir / `600` file, correct
   owner. **Aborts if root has no key** (otherwise Part 2 would lock you out).
6. UFW: `allow OpenSSH` + `allow <SSH_PORT>/tcp` + `80` + `443` **before**
   `ufw --force enable` (default deny incoming / allow outgoing)
7. If IPv6 is active, set `IPV6=yes` in `/etc/default/ufw` and reload so rules
   cover v6; if IPv6 is off, it's skipped
8. Drop-in `/etc/ssh/sshd_config.d/00-hardening.conf`: `PermitRootLogin no`,
   `PasswordAuthentication no` (+ related). Validated with `sshd -t`, then
   `systemctl reload ssh` (reload does **not** drop your session). The `00-`
   prefix ensures it wins over `50-cloud-init.conf` (sshd = first-match-wins);
   verified with `sshd -T` which prints the **effective** values.
9. `fail2ban` with an `[sshd]` jail on `<SSH_PORT>` (maxretry 5, findtime 10m,
   bantime 1h, systemd backend)
10. `unattended-upgrades` enabled via `/etc/apt/apt.conf.d/20auto-upgrades`

At the end Part 2 prints a 10-line status summary plus `ufw status verbose` and
`systemctl status fail2ban`.

## If you get locked out
Because Part 1 stops for the login test and Part 2 uses `reload` (not `restart`)
after `sshd -t`, lock-out is very unlikely. If it still happens, use your VPS
provider's **web/serial console** (out-of-band, not SSH) and:

```bash
# re-enable password auth temporarily
rm /etc/ssh/sshd_config.d/00-hardening.conf
systemctl reload ssh
# or allow your SSH port through the firewall
ufw allow <SSH_PORT>/tcp
```

## Idempotent
Both scripts are safe to re-run — every step checks before acting (existing
swap, existing user, existing fstab/UFW rules, etc.).
