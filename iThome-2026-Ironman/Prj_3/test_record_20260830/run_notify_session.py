"""Day 19 實測腳本（第二階段）：訂閱所有可 notify 的 characteristic 並監看。

對應 mi_band_explorer.py 的選項 8。訂閱成功數與「真的會推東西過來」的數量
是兩件事，紀錄檔會分開統計。

監看期間需要人走動，即時步數才會變。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bleak import BleakClient, BleakScanner  # noqa: E402

from mi_band_explorer import (  # noqa: E402
    KNOWN_UUIDS,
    MI_BAND_HINTS,
    decode_value,
    describe_uuid,
    hexdump,
)

LINES: list[str] = []


def log(text: str = "") -> None:
    LINES.append(text)


def mask_mac(addr: str) -> str:
    parts = addr.split(":")
    if len(parts) == 6:
        return f"{parts[0]}:{parts[1]}:**:**:**:{parts[5]}"
    return addr


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--scan-timeout", type=float, default=20.0)
    parser.add_argument("--seconds", type=float, default=90.0)
    args = parser.parse_args()

    log("# Day 19 實測紀錄 — 第二階段（監看 notify）")
    log()
    log(f"開始時間：{datetime.now():%Y-%m-%d %H:%M:%S}")
    log("環境：Windows 11 / Python 3.13.15 / bleak 2.0.0（conda env `nb_ble`）")
    log(f"監看長度：{args.seconds:.0f} 秒，期間有人在室內走動。")
    log()
    log("---")
    log()

    def flush() -> None:
        Path(args.out).write_text("\n".join(LINES) + "\n", encoding="utf-8")

    discovered = await BleakScanner.discover(timeout=args.scan_timeout, return_adv=True)
    target = None
    for device, adv in discovered.values():
        name = (device.name or adv.local_name or "").lower()
        if any(h in name for h in MI_BAND_HINTS):
            target = device
            break
    if target is None:
        log("**沒有掃到小米/華米裝置，本階段中止。**")
        flush()
        return

    log("## 1. 連線")
    log()
    log(f"目標：{target.name}  {mask_mac(target.address)}")
    client = BleakClient(target, timeout=20.0)
    await client.connect()
    log("連線成功。")
    log()

    packets: list[tuple[str, str, bytes]] = []
    subscribed: list = []

    def callback(char, data: bytearray) -> None:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        packets.append((stamp, char.uuid, bytes(data)))

    try:
        candidates = [
            char
            for service in client.services
            for char in service.characteristics
            if "notify" in char.properties or "indicate" in char.properties
        ]
        log(f"## 2. 訂閱（{len(candidates)} 個候選）")
        log()
        failed: list[tuple[str, str]] = []
        for char in candidates:
            try:
                await client.start_notify(char, callback)
                subscribed.append(char)
                log(f"  OK   {char.uuid}  {describe_uuid(char.uuid, KNOWN_UUIDS)}")
            except Exception as exc:
                failed.append((char.uuid, repr(exc)))
                log(f"  FAIL {char.uuid}  {exc!r}")
        log()
        log(f"訂閱成功 {len(subscribed)} 個，失敗 {len(failed)} 個。")
        log("手環未認證時多數欄位不會推送；走動幾步可觸發即時步數。")
        log()

        log(f"## 3. 監看 {args.seconds:.0f} 秒")
        log()
        print(f"[monitor] subscribed={len(subscribed)} failed={len(failed)}", flush=True)
        print(f"[monitor] WALK NOW for {args.seconds:.0f}s", flush=True)
        await asyncio.sleep(args.seconds)
    finally:
        for char in subscribed:
            try:
                await client.stop_notify(char)
            except Exception:
                pass
        await client.disconnect()

    if not packets:
        log("監看期間沒有收到任何封包。")
    else:
        log(f"監看期間共收到 {len(packets)} 個封包。")
        log()
        for stamp, uuid, data in packets:
            log(f"{stamp}  {uuid}  {describe_uuid(uuid, KNOWN_UUIDS)}")
            log(f"    {hexdump(data)}")
            decoded = decode_value(uuid, data)
            if decoded:
                log(f"    => {decoded}")
        log()
        talkers: dict[str, int] = {}
        for _, uuid, _ in packets:
            talkers[uuid] = talkers.get(uuid, 0) + 1
        log("有推送的 characteristic：")
        for uuid, count in sorted(talkers.items(), key=lambda kv: -kv[1]):
            log(f"  {uuid}  {describe_uuid(uuid, KNOWN_UUIDS)}  {count} 個封包")
    log()
    log(f"結束時間：{datetime.now():%Y-%m-%d %H:%M:%S}")
    flush()
    print("[monitor] done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
