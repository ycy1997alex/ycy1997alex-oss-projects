"""Day 19 實測腳本（第一階段）：掃描 → 連線 → 列舉 → 全讀 → 摘要。

非互動版，把 mi_band_explorer.py 選項 1/3/5/6/9 的流程一次跑完，
輸出寫成 UTF-8 紀錄檔（本機主控台是 cp950，直接印中文會亂碼）。

解碼邏輯一律 import 自 mi_band_explorer，不另外複製一份，
避免紀錄檔跟工具本身的解讀不一致。

隱私：序號與 MAC 位址在紀錄檔中遮蔽，原值另外寫到 --raw 指定的檔案。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bleak import BleakClient, BleakScanner  # noqa: E402
from bleak.exc import BleakError  # noqa: E402

from mi_band_explorer import (  # noqa: E402
    HUAMI_SUFFIX,
    KNOWN_SERVICES,
    KNOWN_UUIDS,
    MI_BAND_HINTS,
    decode_value,
    describe_uuid,
    hexdump,
)

LINES: list[str] = []
RAW: list[str] = []
SECRETS: list[str] = []  # 要從輸出裡清掉的識別資訊（目前只有 MAC）


def log(text: str = "") -> None:
    LINES.append(text)


def mask_mac(addr: str) -> str:
    parts = addr.split(":")
    if len(parts) == 6:
        return f"{parts[0]}:{parts[1]}:**:**:**:{parts[5]}"
    return addr[:5] + "****" + addr[-2:]


def mask_serial(text: str) -> str:
    text = text.strip()
    if len(text) <= 4:
        return "*" * len(text)
    return text[:2] + "*" * (len(text) - 4) + text[-2:]


def scrub(text: str) -> str:
    """最後一道：把 MAC 位址從整份輸出裡清掉。

    光遮欄位不夠，因為同一組位元組會用別的形式再出現一次：廣播的廠商資料
    尾端夾著 MAC，2A23 System ID 則是把 MAC 拆成 EUI-64（前三個位元組 +
    fffe + 後三個位元組）。所以連續 hex 與空白分隔 hex 兩種寫法都要換掉。
    """
    for addr in SECRETS:
        raw = addr.replace(":", "").lower()
        head, tail = raw[:4], raw[-2:]
        eui = raw[:6] + "fffe" + raw[6:]
        for src in (raw, eui):
            spaced = " ".join(src[i : i + 2] for i in range(0, len(src), 2))
            masked = head + "*" * (len(src) - 6) + tail
            text = text.replace(src, masked)
            text = text.replace(spaced, " ".join(masked[i : i + 2] for i in range(0, len(masked), 2)))
        text = text.replace(addr, mask_mac(addr))
    return text


async def find_band(timeout: float) -> tuple[object, object] | None:
    log(f"## 1. 掃描（{timeout:.0f} 秒）")
    log()
    discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    found = sorted(discovered.values(), key=lambda pair: pair[1].rssi, reverse=True)
    named = [(d, a) for d, a in found if d.name or a.local_name]
    log(f"掃到 {len(found)} 個裝置，其中有名稱的 {len(named)} 個。")
    log()
    for device, adv in named:
        name = device.name or adv.local_name
        hit = any(h in name.lower() for h in MI_BAND_HINTS)
        marker = "  <== 疑似小米/華米裝置" if hit else ""
        log(f"  {name:<28} {mask_mac(device.address)}  RSSI {adv.rssi:>4} dBm{marker}")
        if adv.service_uuids:
            log(f"      廣播服務: {', '.join(u[4:8] for u in adv.service_uuids)}")
        if adv.manufacturer_data:
            for company, payload in adv.manufacturer_data.items():
                log(f"      廠商資料 0x{company:04x}: {payload.hex()}")
    log()

    for device, adv in found:
        name = (device.name or adv.local_name or "").lower()
        if any(h in name for h in MI_BAND_HINTS):
            SECRETS.append(device.address)
            RAW.append(f"target address: {device.address}")
            RAW.append(f"target name: {device.name or adv.local_name}")
            return device, adv
    return None


async def dump_gatt(client: BleakClient) -> dict[str, int]:
    log("## 3. GATT 完整結構")
    log()
    n_service = n_char = n_desc = 0
    for service in client.services:
        n_service += 1
        log(f"SERVICE {service.uuid}  {describe_uuid(service.uuid, KNOWN_SERVICES)}")
        for char in service.characteristics:
            n_char += 1
            props = ",".join(char.properties)
            log(f"  CHAR {char.uuid}  [{props}]  handle={char.handle}")
            log(f"       {describe_uuid(char.uuid, KNOWN_UUIDS)}")
            for descriptor in char.descriptors:
                n_desc += 1
                log(f"       DESC {descriptor.uuid}  {describe_uuid(descriptor.uuid, {})}")
        log()
    total = n_service + n_char + n_desc
    log(f"合計：服務 {n_service}、特徵 {n_char}、描述元 {n_desc}，節點總數 {total}")
    log()
    return {"service": n_service, "char": n_char, "desc": n_desc, "total": total}


async def read_all(client: BleakClient) -> dict[str, object]:
    log("## 4. 讀取所有帶 read 屬性的 characteristic")
    log()
    succeeded: list[str] = []
    denied: list[tuple[str, str]] = []

    for service in client.services:
        for char in service.characteristics:
            if "read" not in char.properties:
                continue
            desc = describe_uuid(char.uuid, KNOWN_UUIDS)
            log(f"{char.uuid}  {desc}")
            try:
                data = await client.read_gatt_char(char)
            except BleakError as exc:
                log(f"      讀取被拒: {exc}")
                denied.append((char.uuid, str(exc)))
                continue
            except Exception as exc:  # WinRT 後端可能拋出非 BleakError
                log(f"      讀取失敗: {exc!r}")
                denied.append((char.uuid, repr(exc)))
                continue
            succeeded.append(char.uuid)
            raw = bytes(data)
            shown = raw
            if char.uuid.lower() == "00002a25-0000-1000-8000-00805f9b34fb":
                RAW.append(f"2a25 serial raw: {raw!r}")
                shown = mask_serial(raw.decode("utf-8", "replace")).encode()
            log(f"      {hexdump(shown)}")
            decoded = decode_value(char.uuid, raw)
            if decoded:
                if char.uuid.lower() == "00002a25-0000-1000-8000-00805f9b34fb":
                    decoded = mask_serial(decoded)
                log(f"      => {decoded}")
    log()
    log(f"成功讀取 {len(succeeded)} 個，被拒 {len(denied)} 個。")
    log()
    if denied:
        log("被拒清單（原始錯誤字串，未加工）：")
        for uuid, reason in denied:
            log(f"  {uuid}  {reason}")
        log()
    return {"succeeded": succeeded, "denied": denied}


async def summary(client: BleakClient) -> list[tuple[str, str]]:
    log("## 5. 手環摘要（選項 9 的七個欄位）")
    log()
    wanted = [
        ("00002a00-0000-1000-8000-00805f9b34fb", "裝置名稱"),
        ("00002a25-0000-1000-8000-00805f9b34fb", "序號"),
        ("00002a27-0000-1000-8000-00805f9b34fb", "硬體版本"),
        ("00002a28-0000-1000-8000-00805f9b34fb", "韌體版本"),
        ("00002a19-0000-1000-8000-00805f9b34fb", "電池電量"),
        (f"00000006{HUAMI_SUFFIX}", "電池詳情"),
        ("00002a2b-0000-1000-8000-00805f9b34fb", "手環時間"),
    ]
    rows: list[tuple[str, str]] = []
    for uuid, label in wanted:
        try:
            data = await client.read_gatt_char(uuid)
        except Exception as exc:
            log(f"  {label:<6} 無法讀取 — {exc}")
            rows.append((label, f"無法讀取（{exc}）"))
            continue
        raw = bytes(data)
        value = decode_value(uuid, raw) or raw.hex()
        if label == "序號":
            RAW.append(f"summary serial: {value}")
            value = mask_serial(value)
        log(f"  {label:<6} {value}")
        rows.append((label, value))
    log(f"  {'即時步數':<6} 禁止直接讀取，請用選項 8 監看 notify")
    rows.append(("即時步數", "禁止直接讀取，請用選項 8 監看 notify"))
    log()
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--scan-timeout", type=float, default=8.0)
    args = parser.parse_args()

    started = datetime.now()
    log("# Day 19 實測紀錄 — 第一階段（讀取）")
    log()
    log(f"開始時間：{started:%Y-%m-%d %H:%M:%S}")
    log("環境：Windows 11 / Python 3.13.15 / bleak 2.0.0（conda env `nb_ble`）")
    log("模式：唯讀，全程沒有寫入任何 characteristic，沒有嘗試認證。")
    log()
    log("---")
    log()

    def flush() -> None:
        Path(args.out).write_text(scrub("\n".join(LINES) + "\n"), encoding="utf-8")
        Path(args.raw).write_text("\n".join(RAW) + "\n", encoding="utf-8")

    pair = await find_band(args.scan_timeout)
    if pair is None:
        log("**沒有掃到小米/華米裝置，實測中止。**")
        flush()
        return
    device, adv = pair

    log("## 2. 連線")
    log()
    log(f"目標：{device.name or adv.local_name}  {mask_mac(device.address)}  RSSI {adv.rssi} dBm")
    client = BleakClient(device, timeout=20.0)
    connect_start = datetime.now()
    try:
        await client.connect()
    except Exception as exc:
        log(f"連線失敗: {exc!r}")
        log("提示：手環同時只能被一個中央裝置連線，請先在手機關閉 Zepp Life。")
        flush()
        return
    elapsed = (datetime.now() - connect_start).total_seconds()
    log(f"連線成功，耗時 {elapsed:.1f} 秒。")
    log()

    try:
        await dump_gatt(client)
        await read_all(client)
        await summary(client)
    finally:
        await client.disconnect()
        log("## 6. 斷線")
        log()
        log("已主動斷線，本階段結束。")
        log()
        log(f"結束時間：{datetime.now():%Y-%m-%d %H:%M:%S}")
        flush()


if __name__ == "__main__":
    asyncio.run(main())
