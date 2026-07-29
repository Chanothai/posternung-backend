#!/bin/bash
# wrapper — implementation จริงอยู่ที่ workspace/.claude/hooks/block-secrets.sh
# แก้ที่นั่นที่เดียว มีผลทั้ง 3 repo (ไม่มีสำเนาให้ drift)
#
# ทำไมต้องมีใน repo นี้ด้วย: hook เป็น project setting ของ repo ที่เปิดเซสชัน
# ตัวที่ workspace ครอบเฉพาะตอนเปิดจาก workspace/ ซึ่งเป็นตอนที่ระวังมากที่สุดอยู่แล้ว
# ตอนเปิดจาก repo นี้ตรง ๆ คือตอนที่ระวังน้อยที่สุด
#
# ใช้ `cd && pwd` ไม่ใช่ `readlink -f` — BSD readlink บน macOS ไม่มี -f
# ถ้าใช้จะ error แล้ว exit 0 เงียบ ๆ กลายเป็น hook ที่ตายโดยไม่มีใครรู้
dir="$(cd "$(dirname "$0")/../../../workspace/.claude/hooks" 2>/dev/null && pwd)" || exit 0
real="$dir/block-secrets.sh"
[ -x "$real" ] || exit 0   # ไม่มี workspace (clone มา repo เดียว) → ไม่ตัดสิน ไม่บล็อกงาน
exec "$real"
