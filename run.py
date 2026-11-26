#!/usr/bin/env python3
"""Start vout locally and print LAN URLs for phones, admin laptop, and projector."""

from __future__ import annotations

import socket
import uvicorn

from vout.config import ADMIN_PIN, DB_PATH, HOST, PORT


def detect_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main() -> None:
    lan_ip = detect_lan_ip()
    print("=" * 64)
    print("  vout – Elektronické hlasovanie zastupiteľstva")
    print("=" * 64)
    print(f"  Databáza:   {DB_PATH}")
    print(f"  Admin PIN:  {ADMIN_PIN}  (zmena cez env VOUT_ADMIN_PIN)")
    print("-" * 64)
    print(f"  Lokálne:    http://127.0.0.1:{PORT}")
    print(f"  Na Wi-Fi:   http://{lan_ip}:{PORT}")
    print(f"    • Poslanec (mobil):     http://{lan_ip}:{PORT}/vote")
    print(f"    • Zapisovateľ (admin):  http://{lan_ip}:{PORT}/admin")
    print(f"    • Projektor (TV):       http://{lan_ip}:{PORT}/display")
    print("=" * 64)
    uvicorn.run("vout.app:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
