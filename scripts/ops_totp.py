#!/usr/bin/env python3
"""CLI บาง ๆ สำหรับ `scripts._totp.enroll()` — ใช้ครั้งเดียวตอนตั้งค่า production (INF-44)

    ./venv/bin/python scripts/ops_totp.py enroll

พิมพ์ `otpauth://totp/PosterNung:ops?secret=…&issuer=PosterNung` **ครั้งเดียว** — สแกน
ด้วยแอป authenticator (Google Authenticator / Authy ฯลฯ) ทันที **ไม่มีที่ไหนบันทึกค่านี้
ซ้ำอีก** (ไม่ลง log ไม่ลง audit ไม่มี flag ให้พิมพ์ซ้ำ) ถ้าพลาดต้องลบไฟล์ secret
(`OPS_TOTP_SECRET_PATH`) แล้ว enroll ใหม่ — จะทำให้ code เก่าที่ authenticator app
จำไว้ใช้ไม่ได้อีก (ต้อง re-scan)

secret เขียนไว้ที่ path จาก env `OPS_TOTP_SECRET_PATH` (mode `0400`) — ต้องตั้ง env
นี้ก่อนรัน ไม่มี default (fail-closed: ไม่รู้จะเขียนที่ไหนก็ไม่เขียน)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts._totp import enroll  # noqa: E402
from scripts.seed._shared import PrecheckError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_subparsers(dest="action", required=True).add_parser(
        "enroll", help="สร้าง secret ใหม่ครั้งเดียว — ปฏิเสธถ้ามีไฟล์อยู่แล้ว"
    )
    args = parser.parse_args()

    secret_path_raw = os.environ.get("OPS_TOTP_SECRET_PATH", "")
    if not secret_path_raw:
        print("ไม่พบ env OPS_TOTP_SECRET_PATH — ตั้งก่อนรัน", file=sys.stderr)
        return 1

    if args.action == "enroll":
        try:
            uri = enroll(Path(secret_path_raw))
        except PrecheckError as exc:
            print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
            return 1
        print(
            "สแกน URI นี้ด้วยแอป authenticator ทันที — จะไม่ถูกพิมพ์ซ้ำอีก:\n\n"
            f"  {uri}\n"
        )
        return 0

    return 1  # pragma: no cover — argparse subparsers กันไว้แล้ว


if __name__ == "__main__":
    raise SystemExit(main())
