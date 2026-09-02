"""診斷用：長時間掃描，列出所有廣播（含無名稱），標出華米特徵。

小米手環 6 在被手機 App 連著的時候不一定會廣播名稱，
所以除了名稱之外也比對 FEE0/FEE1 服務與華米的廠商代碼。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from bleak import BleakScanner

HUAMI_SERVICES = {"fee0", "fee1"}
LINES: list[str] = []


def log(text: str = "") -> None:
    LINES.append(text)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    log(f"診斷掃描 {args.timeout:.0f} 秒 — {datetime.now():%Y-%m-%d %H:%M:%S}")
    log()
    discovered = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
    found = sorted(discovered.values(), key=lambda pair: pair[1].rssi, reverse=True)
    log(f"共 {len(found)} 個廣播裝置")
    log()
    hits = 0
    for device, adv in found:
        name = device.name or adv.local_name or "(無名稱)"
        shorts = {u[4:8].lower() for u in adv.service_uuids}
        is_huami = bool(shorts & HUAMI_SERVICES)
        mark = "  <== 華米服務" if is_huami else ""
        if is_huami:
            hits += 1
        log(f"{name:<24} {device.address}  RSSI {adv.rssi:>4}{mark}")
        if adv.service_uuids:
            log(f"    services: {', '.join(sorted(shorts))}")
        if adv.service_data:
            for k, v in adv.service_data.items():
                log(f"    service_data {k[4:8]}: {v.hex()}")
        if adv.manufacturer_data:
            for company, payload in adv.manufacturer_data.items():
                log(f"    manufacturer 0x{company:04x}: {payload.hex()}")
    log()
    log(f"帶華米服務的廣播：{hits} 個")
    Path(args.out).write_text("\n".join(LINES) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
