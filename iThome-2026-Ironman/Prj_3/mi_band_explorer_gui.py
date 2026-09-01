"""Mi Band 6 BLE Explorer (GUI) —— 唯讀探索工具，MVP 架構單檔版。

與 mi_band_explorer.py 功能相同，但改為 ttkbootstrap 圖形介面。本檔刻意
「完全自包含」：不 import mi_band_explorer，UUID 表與解碼器都自帶一份，
可單獨搬走或打包。

UI 風格參考 NB_BLE/v2.4/nb_ble_controller.py：litera 亮色主題、三段式版面
（上 Log、中 Log Actions、下左右雙欄）、下方控制項優先佈局以保證完整顯示、
按鈕以 bootstyle 語意上色、Log Actions 完整的存檔功能。

架構分層（MVP）：
    Model      BandModel / LogRecorder    純 BLE 與檔案 I/O，完全不碰 Tk
    View       ExplorerView               純 ttkbootstrap widget，完全不懂 BLE
    Presenter  ExplorerPresenter          綁定兩者，並負責跨執行緒交棒

執行緒模型：bleak 走 asyncio、Tk 非執行緒安全，因此 asyncio 事件迴圈跑在
背景 daemon 執行緒，所有結果丟進 queue.Queue，由 View 以 after() 輪詢後
才碰 widget。背景執行緒絕不直接操作任何 widget。

刻意唯讀：不寫入任何 characteristic，不嘗試 Huami 認證。

環境：Python 3.13 + bleak 2.0 + ttkbootstrap
"""

from __future__ import annotations

import asyncio
import ctypes
import queue
import sys
import threading
import tkinter as tk
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, scrolledtext
from typing import Any

import ttkbootstrap as bs
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
from bleak.uuids import normalize_uuid_str, uuidstr_to_str
from ttkbootstrap.constants import (
    BOTH, BOTTOM, DANGER, END, HORIZONTAL, INFO, LEFT, NO, NSEW, PRIMARY,
    RIGHT, SECONDARY, SUCCESS, TOP, VERTICAL, W, WARNING, X, Y, YES,
)

# --- PyInstaller 封裝 ---
# ============================================================================================== #
# 打包設定寫在 MiBand6BleExplorer-onefile.spec，建置指令在該檔的檔頭。
# 不要回頭用一長串命令列參數：conda 的 Library\bin 得在 Analysis 之前塞進 PATH，
# 那件事命令列做不到。
# ============================================================================================== #

# --- 全域設定 (Global Settings) ---
# 視窗幾何：螢幕寬度 3%~97%、高度 3%~87%
GEOMETRY_LEFT = 0.03
GEOMETRY_RIGHT = 0.97
GEOMETRY_TOP = 0.03
GEOMETRY_BOTTOM = 0.87

THEME_LIGHT = "litera"   # 與參考檔 nb_ble_controller.py 一致
THEME_DARK = "darkly"

APP_ID = "Aitronics.MiBand6BleExplorer.v1"
ICON_FILENAME = "app.ico"
LOG_DIR_NAME = "MiBand6_Explorer_Log"


def resource_path(filename: str) -> Path:
    """取得資源檔的絕對路徑，同時支援 .py 執行與 PyInstaller onefile 封裝。"""
    if getattr(sys, "frozen", False):
        # 封裝後資源會被解到暫存目錄 _MEIPASS
        base_path = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base_path = Path(__file__).resolve().parent
    return base_path / filename


# ==============================================================================
# Model: 處理所有藍牙核心邏輯與檔案 I/O（完全與 GUI 分離）
# ==============================================================================

# 華米（Huami/Zepp）私有 UUID base：0000XXXX-0000-3512-2118-0009af100700
HUAMI_SUFFIX = "-0000-3512-2118-0009af100700"

KNOWN_UUIDS: dict[str, str] = {
    "00002a00-0000-1000-8000-00805f9b34fb": "裝置名稱",
    "00002a19-0000-1000-8000-00805f9b34fb": "電池電量 (%)",
    "00002a24-0000-1000-8000-00805f9b34fb": "型號",
    "00002a25-0000-1000-8000-00805f9b34fb": "序號",
    "00002a26-0000-1000-8000-00805f9b34fb": "韌體版本",
    "00002a27-0000-1000-8000-00805f9b34fb": "硬體版本",
    "00002a28-0000-1000-8000-00805f9b34fb": "軟體版本",
    "00002a29-0000-1000-8000-00805f9b34fb": "製造商",
    "00002a2b-0000-1000-8000-00805f9b34fb": "目前時間 (手環時鐘)",
    "00002a37-0000-1000-8000-00805f9b34fb": "心率量測 (notify)",
    "00002a39-0000-1000-8000-00805f9b34fb": "心率控制點 (需認證)",
    f"00000001{HUAMI_SUFFIX}": "Huami: 韌體上傳控制",
    f"00000002{HUAMI_SUFFIX}": "Huami: 韌體資料",
    f"00000003{HUAMI_SUFFIX}": "Huami: 使用者設定",
    f"00000004{HUAMI_SUFFIX}": "Huami: 活動資料",
    f"00000005{HUAMI_SUFFIX}": "Huami: 資料傳輸控制",
    f"00000006{HUAMI_SUFFIX}": "Huami: 電池詳情",
    f"00000007{HUAMI_SUFFIX}": "Huami: 即時步數/活動",
    f"00000008{HUAMI_SUFFIX}": "Huami: 配對",
    f"00000009{HUAMI_SUFFIX}": "Huami: 認證 (auth challenge)",
    f"0000000e{HUAMI_SUFFIX}": "Huami: 感測器控制",
    f"00000010{HUAMI_SUFFIX}": "Huami: 感測器資料",
}

KNOWN_SERVICES: dict[str, str] = {
    "00001800-0000-1000-8000-00805f9b34fb": "通用存取 (GAP)",
    "00001801-0000-1000-8000-00805f9b34fb": "通用屬性 (GATT)",
    "0000180a-0000-1000-8000-00805f9b34fb": "裝置資訊 (免認證可讀)",
    "0000180d-0000-1000-8000-00805f9b34fb": "心率 (通常需認證)",
    "0000180f-0000-1000-8000-00805f9b34fb": "電池",
    "0000fee0-0000-1000-8000-00805f9b34fb": "華米主服務 (私有，多數需認證)",
    "0000fee1-0000-1000-8000-00805f9b34fb": "華米認證服務",
}

MI_BAND_HINTS = ("mi band", "mi smart band", "xiaomi", "amazfit")

WEEKDAYS = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}


def describe_uuid(uuid: str, table: dict[str, str]) -> str:
    """回傳 UUID 的人類可讀說明；先查自訂表，再退回 bleak 內建表。"""
    key = uuid.lower()
    if key in table:
        return table[key]
    builtin = uuidstr_to_str(key)
    return builtin if builtin and builtin != "Unknown" else "未知"


def hexdump(data: bytes) -> str:
    """單行 hex + 可列印 ASCII。"""
    hex_part = " ".join(f"{b:02x}" for b in data)
    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"{hex_part}  |{ascii_part}|"


def decode_huami_time(chunk: bytes) -> str:
    """解碼華米 8 位元組時間戳：年(2,小端) 月 日 時 分 秒 時區。

    時區以 15 分鐘為單位（台灣 UTC+8 → 0x20 = 32）。
    """
    if len(chunk) < 7:
        return chunk.hex()
    year = int.from_bytes(chunk[0:2], "little")
    stamp = f"{year:04d}-{chunk[2]:02d}-{chunk[3]:02d} {chunk[4]:02d}:{chunk[5]:02d}:{chunk[6]:02d}"
    if len(chunk) >= 8:
        stamp += f" (UTC{chunk[7] * 15 / 60:+.0f})"
    return stamp


def decode_value(uuid: str, data: bytes) -> str | None:
    """對已知 characteristic 做語意解碼；無法解碼時回傳 None。"""
    key = uuid.lower()

    text_uuids = {
        "00002a00-0000-1000-8000-00805f9b34fb",
        "00002a24-0000-1000-8000-00805f9b34fb",
        "00002a25-0000-1000-8000-00805f9b34fb",
        "00002a26-0000-1000-8000-00805f9b34fb",
        "00002a27-0000-1000-8000-00805f9b34fb",
        "00002a28-0000-1000-8000-00805f9b34fb",
        "00002a29-0000-1000-8000-00805f9b34fb",
    }
    if key in text_uuids:
        return data.decode("utf-8", errors="replace").strip("\x00")

    if key == "00002a19-0000-1000-8000-00805f9b34fb" and len(data) >= 1:
        return f"{data[0]} %"

    # 標準 Current Time：年(2,小端) 月 日 時 分 秒 星期 …
    if key == "00002a2b-0000-1000-8000-00805f9b34fb" and len(data) >= 7:
        year = int.from_bytes(data[0:2], "little")
        stamp = f"{year:04d}-{data[2]:02d}-{data[3]:02d} {data[4]:02d}:{data[5]:02d}:{data[6]:02d}"
        if len(data) >= 8:
            stamp += f" 星期{WEEKDAYS.get(data[7], '?')}"
        return stamp

    # Huami 電池詳情（實測 20 位元組）：
    #   [1]=電量%, [2]=充電狀態, [3:11]/[11:19]=兩個時間戳, [19]=上次充電結束電量
    #   兩個時間戳的確切語意未經證實，故僅標示為時間戳 1 / 2
    if key == f"00000006{HUAMI_SUFFIX}" and len(data) >= 3:
        status = {0: "未充電", 1: "充電中"}.get(data[2], f"未知({data[2]})")
        parts = [f"電量 {data[1]} %", f"狀態 {status}"]
        if len(data) >= 11:
            parts.append(f"時間戳1 {decode_huami_time(data[3:11])}")
        if len(data) >= 19:
            parts.append(f"時間戳2 {decode_huami_time(data[11:19])}")
        if len(data) >= 20:
            parts.append(f"上次充電結束電量 {data[19]} %")
        return "，".join(parts)

    # Huami 即時活動：[1:5] 小端序為步數
    if key == f"00000007{HUAMI_SUFFIX}" and len(data) >= 5:
        steps = int.from_bytes(data[1:5], "little")
        return f"步數 {steps}（其餘位元組未解析）"

    # 標準心率量測：bit0 決定 bpm 是 8 或 16 位元
    if key == "00002a37-0000-1000-8000-00805f9b34fb" and len(data) >= 2:
        if data[0] & 0x01 and len(data) >= 3:
            bpm = int.from_bytes(data[1:3], "little")
        else:
            bpm = data[1]
        return f"心率 {bpm} bpm"

    return None


@dataclass
class ScanRow:
    """掃描結果的一列，View 只認得這個結構，不碰 bleak 型別。"""

    index: int
    name: str
    address: str
    rssi: int
    detail: str
    is_band: bool


@dataclass
class GattNode:
    """GATT 樹的一個節點，供 View 建立 Treeview。"""

    label: str
    detail: str
    children: list["GattNode"] = field(default_factory=list)


class LogRecorder:
    """Log 檔案寫入。純檔案 I/O，完全不碰 Tk。

    檔名與日期子資料夾格式沿用參考檔 nb_ble_controller.py 的慣例。
    """

    def __init__(self) -> None:
        self.save_dir: Path = Path.home() / "Documents" / LOG_DIR_NAME
        self._handler: Any = None

    @property
    def is_saving(self) -> bool:
        return self._handler is not None

    def _build_path(self, log_type: str) -> Path:
        """依日誌類型與當前時間，生成標準格式的檔名與完整路徑。"""
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")
        date_dir = self.save_dir / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        return date_dir / f"MiBand6_Log-{log_type}_{date_str}-{time_str}.txt"

    def start(self) -> Path:
        """開始即時記錄後續訊息；回傳實際檔案路徑。"""
        path = self._build_path("Interval")
        self._handler = open(path, "a", encoding="utf-8")
        return path

    def write(self, message: str) -> None:
        """寫入一行（帶時間戳）。未啟動即時記錄時不做任何事。"""
        if self._handler is None:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self._handler.write(f"{timestamp} - {message.strip()}\n")
        self._handler.flush()

    def finish(self) -> None:
        """結束即時記錄並關閉檔案。"""
        if self._handler is None:
            return
        try:
            self.write("[System] Finished saving log.")
        finally:
            self._handler.close()
            self._handler = None

    def save_snapshot(self, content: str) -> Path:
        """將目前視窗中已有的內容一次性存檔；回傳實際檔案路徑。"""
        path = self._build_path("Printed")
        path.write_text(content, encoding="utf-8")
        return path

    def close_abruptly(self) -> None:
        """關閉程式時的收尾，確保檔案控制代碼不外洩。"""
        if self._handler is None:
            return
        try:
            self.write("[System] Suddenly Closed.")
        except Exception:
            pass
        finally:
            try:
                self._handler.close()
            except Exception:
                pass
            self._handler = None


class BandModel:
    """所有 BLE 行為。全部方法皆為 coroutine，執行於背景事件迴圈。

    對外只透過 emit callback 回報訊息，不認識任何 widget。
    """

    def __init__(self, emit: Callable[[str, Any], None]) -> None:
        self._emit = emit
        self.found: list[tuple[BLEDevice, AdvertisementData]] = []
        self.target: BLEDevice | None = None
        self.client: BleakClient | None = None
        self._subscribed: list[BleakGATTCharacteristic] = []

    # --- 訊息輔助 ---

    def log(self, text: str, tag: str = "normal") -> None:
        self._emit("log", (text, tag))

    def system(self, text: str) -> None:
        """系統層級訊息，沿用參考檔的 [System] 前綴慣例。"""
        self._emit("log", (f"[System] {text}", "system"))

    # --- 掃描裝置 ---

    async def scan(self, timeout: float, named_only: bool) -> None:
        self._emit("status", f"Scanning ({timeout:.0f}s)…")
        self.system(f"Scanning for BLE devices ({timeout:.0f} seconds)…")

        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
        self.found = sorted(discovered.values(), key=lambda pair: pair[1].rssi, reverse=True)

        rows: list[ScanRow] = []
        hidden = 0
        for index, (device, adv) in enumerate(self.found):
            has_name = bool(device.name or adv.local_name)
            if named_only and not has_name:
                hidden += 1
                continue
            name = device.name or adv.local_name or "(無名稱)"
            details: list[str] = []
            if adv.service_uuids:
                details.append("服務 " + ", ".join(normalize_uuid_str(u)[4:8] for u in adv.service_uuids))
            for company, payload in adv.manufacturer_data.items():
                details.append(f"廠商 0x{company:04x}: {payload.hex()}")
            rows.append(
                ScanRow(
                    index=index,
                    name=name,
                    address=device.address,
                    rssi=adv.rssi,
                    detail="；".join(details),
                    is_band=any(hint in name.lower() for hint in MI_BAND_HINTS),
                )
            )

        self._emit("devices", rows)
        self.system(f"Scan complete: Found {len(self.found)} device(s), listed {len(rows)}.")
        if hidden:
            self.log(f"已隱藏 {hidden} 個無名稱裝置", "dim")
        bands = [row for row in rows if row.is_band]
        if bands:
            self.log(f"其中 {len(bands)} 個疑似小米/華米裝置", "ok")
        self._emit("status", "Scan complete")

    def select_target(self, index: int) -> None:
        """由 Presenter 在使用者點選清單後呼叫（同步，不碰 BLE）。"""
        if 0 <= index < len(self.found):
            self.target = self.found[index][0]

    # --- 連線與斷線 ---

    def _on_disconnect(self, _client: BleakClient) -> None:
        # 由 bleak 的執行緒呼叫，只丟訊息不碰 widget
        self._emit("disconnected", None)

    async def connect(self) -> None:
        if self.target is None:
            self.system("Error: No device selected.")
            return
        if self.client is not None and self.client.is_connected:
            self.system("Already connected.")
            return

        self._emit("status", f"Connecting {self.target.address}…")
        self.system(f"Connecting to {self.target.name or '(no name)'} | {self.target.address}…")
        client = BleakClient(self.target, disconnected_callback=self._on_disconnect, timeout=20.0)
        try:
            await client.connect()
        except BleakError as exc:
            self.system(f"Connection failed: {exc}")
            self.log("手環同時只能被一個中央裝置連線，請先在手機關閉 Zepp Life。", "dim")
            self._emit("status", "Connection failed")
            return
        self.client = client
        self.system("Connection successful")
        self._emit("status", "Connected")
        self._emit("connected", None)

    async def disconnect(self) -> None:
        if self.client is None:
            return
        await self.stop_notify()
        try:
            await self.client.disconnect()
            self.system("Disconnected")
        except BleakError as exc:
            self.system(f"Disconnect error: {exc}")
        finally:
            self.client = None
            self._emit("status", "Disconnected")
            self._emit("disconnected", None)

    def _require_client(self) -> BleakClient | None:
        if self.client is None or not self.client.is_connected:
            self.system("Error: Not connected.")
            return None
        return self.client

    # --- GATT 探索 ---

    async def dump_gatt(self) -> None:
        client = self._require_client()
        if client is None:
            return

        self._emit("status", "Enumerating GATT…")
        tree: list[GattNode] = []
        service_count = char_count = 0
        for service in client.services:
            service_count += 1
            node = GattNode(
                label=f"{service.uuid[4:8]}  {describe_uuid(service.uuid, KNOWN_SERVICES)}",
                detail=service.uuid,
            )
            for char in service.characteristics:
                char_count += 1
                child = GattNode(
                    label=f"{char.uuid[4:8]}  {describe_uuid(char.uuid, KNOWN_UUIDS)}",
                    detail=f"{char.uuid}  [{','.join(char.properties)}]  handle={char.handle}",
                )
                for descriptor in char.descriptors:
                    child.children.append(
                        GattNode(
                            label=f"desc {descriptor.uuid[4:8]}  {describe_uuid(descriptor.uuid, {})}",
                            detail=descriptor.uuid,
                        )
                    )
                node.children.append(child)
            tree.append(node)

        self._emit("gatt", tree)
        self.system(f"GATT enumerated: {service_count} service(s), {char_count} characteristic(s).")
        self.log("完整結構請看上方「GATT Structure」分頁", "dim")
        self._emit("status", "Connected")

    async def read_all(self) -> None:
        client = self._require_client()
        if client is None:
            return

        self._emit("status", "Reading all readable characteristics…")
        self.system("Reading all readable characteristics…")
        succeeded = 0
        denied: list[tuple[str, str]] = []

        for service in client.services:
            for char in service.characteristics:
                if "read" not in char.properties:
                    continue
                self.log(f"{char.uuid}  {describe_uuid(char.uuid, KNOWN_UUIDS)}", "name")
                try:
                    data = await client.read_gatt_char(char)
                except Exception as exc:  # WinRT 後端可能拋出非 BleakError
                    self.log(f"    讀取被拒: {exc}", "fail")
                    denied.append((char.uuid, str(exc)))
                    continue
                succeeded += 1
                self._log_value(char.uuid, bytes(data))

        self.system(f"Read complete: {succeeded} succeeded, {len(denied)} denied.")
        if denied:
            self.log("被拒絕的多為 Read Not Permitted，屬手環刻意封鎖的欄位：", "warn")
            for uuid, reason in denied:
                self.log(f"    {uuid}  {reason}", "dim")
        self._emit("status", "Connected")

    async def read_one(self, raw_uuid: str) -> None:
        client = self._require_client()
        if client is None:
            return
        try:
            uuid = normalize_uuid_str(raw_uuid.strip())
        except ValueError:
            self.system(f"Invalid UUID: {raw_uuid}")
            return
        self.log(f"{uuid}  {describe_uuid(uuid, KNOWN_UUIDS)}", "name")
        try:
            data = await client.read_gatt_char(uuid)
        except Exception as exc:
            self.log(f"    讀取失敗: {exc}", "fail")
            return
        self._log_value(uuid, bytes(data))

    def _log_value(self, uuid: str, data: bytes) -> None:
        self.log(f"    {hexdump(data)}", "dim")
        decoded = decode_value(uuid, data)
        if decoded:
            self.log(f"    => {decoded}", "ok")

    # --- 摘要 ---

    async def summary(self) -> None:
        client = self._require_client()
        if client is None:
            return

        self._emit("status", "Reading summary…")
        self.system("Band summary (unauthenticated fields only)")
        # 欄位依 Mi Band 6 實測結果挑選：手環沒有 2A24/2A26/2A29，
        # 韌體版本實際上放在 2A28（軟體版本）。
        wanted = [
            ("00002a00-0000-1000-8000-00805f9b34fb", "裝置名稱"),
            ("00002a25-0000-1000-8000-00805f9b34fb", "序號"),
            ("00002a27-0000-1000-8000-00805f9b34fb", "硬體版本"),
            ("00002a28-0000-1000-8000-00805f9b34fb", "韌體版本"),
            ("00002a19-0000-1000-8000-00805f9b34fb", "電池電量"),
            (f"00000006{HUAMI_SUFFIX}", "電池詳情"),
            ("00002a2b-0000-1000-8000-00805f9b34fb", "手環時間"),
        ]
        for uuid, label in wanted:
            try:
                data = await client.read_gatt_char(uuid)
            except Exception as exc:
                self.log(f"  {label}: 無法讀取", "fail")
                self.log(f"      {exc}", "dim")
                continue
            decoded = decode_value(uuid, bytes(data)) or bytes(data).hex()
            self.log(f"  {label}: {decoded}", "ok")

        # 即時步數禁止 read，但實測 notify 免認證就會推送
        self.log("  即時步數: 禁止直接讀取，請用「Start Notify」", "warn")
        self._emit("status", "Connected")

    # --- Notify 監看 ---

    async def start_notify(self) -> None:
        client = self._require_client()
        if client is None:
            return
        if self._subscribed:
            self.system("Already monitoring.")
            return

        candidates = [
            char
            for service in client.services
            for char in service.characteristics
            if "notify" in char.properties or "indicate" in char.properties
        ]
        if not candidates:
            self.system("No notifiable characteristic on this device.")
            return

        self.system(f"Starting notify monitor ({len(candidates)} candidates)…")

        def callback(char: BleakGATTCharacteristic, data: bytearray) -> None:
            stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.log(f"{stamp}  {char.uuid}  {describe_uuid(char.uuid, KNOWN_UUIDS)}", "name")
            self._log_value(char.uuid, bytes(data))

        failed = 0
        for char in candidates:
            try:
                await client.start_notify(char, callback)
                self._subscribed.append(char)
            except Exception as exc:
                failed += 1
                self.log(f"    訂閱失敗 {char.uuid}: {exc}", "dim")

        self.system(f"Subscribed {len(self._subscribed)}, failed {failed}.")
        if self._subscribed:
            self.log("手環未認證時多數欄位不會推送；走動幾步可觸發即時步數。", "dim")
            self._emit("notifying", True)
            self._emit("status", "Monitoring notify")

    async def stop_notify(self) -> None:
        if not self._subscribed:
            return
        client = self.client
        for char in self._subscribed:
            if client is not None and client.is_connected:
                try:
                    await client.stop_notify(char)
                except Exception:
                    pass
        count = len(self._subscribed)
        self._subscribed.clear()
        self.system(f"Notify monitor stopped ({count} subscriptions).")
        self._emit("notifying", False)
        if self.client is not None and self.client.is_connected:
            self._emit("status", "Connected")


# ==============================================================================
# 背景 asyncio 執行緒
# ==============================================================================


class AsyncRunner:
    """在背景 daemon 執行緒跑一個 asyncio 事件迴圈，供 Model 的 coroutine 使用。"""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="ble-loop", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """把 coroutine 丟到背景迴圈，回傳 concurrent.futures.Future。"""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def _cancel_pending(self) -> None:
        """取消所有進行中的 task 並等它們收尾。

        關鍵：掃描／連線中途關窗時，必須讓 bleak 的 finally 有機會停掉 WinRT
        掃描器，否則迴圈關閉後掃描器仍會投遞廣播封包，噴 Event loop is closed。
        """
        pending = [task for task in asyncio.all_tasks(self.loop) if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def shutdown(self, timeout: float = 5.0) -> None:
        """依序：取消未完成工作 → 停迴圈 → join → close。

        daemon 執行緒確保即使 join 逾時也不會卡住行程結束。
        """
        try:
            self.submit(self._cancel_pending()).result(timeout=timeout)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=timeout)
        if not self._thread.is_alive():
            self.loop.close()


# ==============================================================================
# View: 處理所有 GUI 元件的建立與排版
# ==============================================================================
# +--------------------------------------------------------------------------------------+
# | Mi Band 6 BLE Explorer - Read Only                                          -- [] X  |
# +======================================================================================+
# | [ Communication Log | GATT Structure ]                                                    |
# | |----------------------------------------------------------------------------------| |
# | | [System] Scanning for BLE devices (8 seconds)...                                 | |
# | | [System] Scan complete: Found 113 device(s), listed 4.                           | |
# | | [System] Connecting to Mi Smart Band 6 | AA:BB:CC:DD:EE:FF...                    | |
# | | [System] Connection successful                                                   | |
# | |   電池電量: 99 %                                                                  | |
# | |   4d 69 20 53 6d 61 72 74 ...  |Mi Smart ...|                                    | |
# | |   => Mi Smart Band 6                                                             | |
# | |----------------------------------------------------------------------------------| |
# +--------------------------------------------------------------------------------------+
# | [Log Actions]                                                                        |
# | [Clear][Save Printed][Start Save][Finish Save]  [Path to Save][ ...path... ] [Dark]  |
# +--------------------------------------------------------------------------------------+
# | [Device Connection]                    [Explorer Actions]                            |
# | |----------------------------------|   |-------------------------------------------| |
# | | Name       Address        RSSI   |   | Read UUID [ 2a28          ]      [ Read ]  | |
# | | MiBand6    AA:BB:...      -45    |   |                                           | |
# | | ...                              |   | [Enumerate GATT][Read All][Summary]       | |
# | | Timeout[8] [x]Named only         |   | [Start Notify]                            | |
# | | [ Scan ] [ Connect ] [Disconnect]|   |                                           | |
# | |----------------------------------|   |-------------------------------------------| |
# +--------------------------------------------------------------------------------------+

# log 各語意標籤在明暗主題下的顏色
LOG_COLORS: dict[str, dict[str, str]] = {
    THEME_LIGHT: {
        "background": "#ffffff",
        "normal": "#212529",
        "system": "#0d6efd",
        "name": "#6f42c1",
        "ok": "#198754",
        "warn": "#b8860b",
        "fail": "#dc3545",
        "dim": "#6c757d",
    },
    THEME_DARK: {
        "background": "#1b1b1b",
        "normal": "#e0e0e0",
        "system": "#4dabf7",
        "name": "#da77f2",
        "ok": "#51cf66",
        "warn": "#ffd43b",
        "fail": "#ff6b6b",
        "dim": "#909296",
    },
}


class ExplorerView(bs.Frame):
    """處理所有 GUI 介面的建立與佈局。

    完全不認識 BLE，也不持有 Presenter 參考；使用者操作一律經由 on_* callback
    屬性外露，由 Presenter 指派（這是與參考檔 MVC 的差異：View 不反向依賴）。
    """

    def __init__(self, master: bs.Window) -> None:
        super().__init__(master, padding=15)
        self.root = master
        self.style = master.style
        self.theme = THEME_LIGHT

        # --- Presenter 指派的事件處理器，預設為無動作 ---
        self.on_scan: Callable[[], None] = lambda: None
        self.on_select_device: Callable[[int], None] = lambda _index: None
        self.on_connect: Callable[[], None] = lambda: None
        self.on_disconnect: Callable[[], None] = lambda: None
        self.on_dump_gatt: Callable[[], None] = lambda: None
        self.on_read_all: Callable[[], None] = lambda: None
        self.on_read_one: Callable[[str], None] = lambda _uuid: None
        self.on_summary: Callable[[], None] = lambda: None
        self.on_toggle_notify: Callable[[], None] = lambda: None
        self.on_clear_log: Callable[[], None] = lambda: None
        self.on_save_printed: Callable[[], None] = lambda: None
        self.on_start_save: Callable[[], None] = lambda: None
        self.on_finish_save: Callable[[], None] = lambda: None
        self.on_select_path: Callable[[], None] = lambda: None
        self.on_close: Callable[[], None] = lambda: None

        self._device_indices: list[int] = []
        self._connected = False
        self._busy = False

        self._setup_window()
        self.pack(fill=BOTH, expand=YES)
        self._create_widgets()
        self._apply_log_theme()

        self.root.protocol("WM_DELETE_WINDOW", lambda: self.on_close())

    # --- 視窗設定 ---

    def _setup_window(self) -> None:
        self.root.title("Mi Band 6 BLE Explorer —— Read Only")
        self._apply_icon()
        self._apply_geometry()

    def _apply_geometry(self) -> None:
        """視窗佔螢幕寬 3%~97%、高 3%~87%。"""
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = int(screen_w * GEOMETRY_LEFT)
        y = int(screen_h * GEOMETRY_TOP)
        width = int(screen_w * (GEOMETRY_RIGHT - GEOMETRY_LEFT))
        height = int(screen_h * (GEOMETRY_BOTTOM - GEOMETRY_TOP))
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(1100, 700)

    def _apply_icon(self) -> None:
        """專案目錄放入 app.ico 就會自動套用；沒有就靜默沿用 Tk 預設圖示。"""
        icon_path = resource_path(ICON_FILENAME)
        if not icon_path.exists():
            return
        try:
            self.root.iconbitmap(str(icon_path))
        except tk.TclError:
            print(f"Warning: Could not load icon at {icon_path}")

    # --- 版面 ---

    def _create_widgets(self) -> None:
        """建立並排版所有 GUI 元件。

        佈局次序沿用參考檔：下方控制項與 Log Actions 先以 side=BOTTOM 佈局，
        確保它們永遠完整顯示，Log 區最後才填滿所有剩餘空間。
        """
        control_frame = bs.Frame(self)
        control_frame.pack(side=BOTTOM, fill=X, expand=NO, pady=(12, 0))

        log_actions_frame = bs.Labelframe(self, text="Log Actions", padding=12)
        log_actions_frame.pack(side=BOTTOM, fill=X, expand=NO, pady=(0, 12))

        log_frame = bs.Frame(self)
        log_frame.pack(side=TOP, fill=BOTH, expand=YES)

        self._create_control_widgets(control_frame)
        self._create_log_action_widgets(log_actions_frame)
        self._create_log_display_widgets(log_frame)

    def _create_control_widgets(self, parent_frame: bs.Frame) -> None:
        """下方區域（控制項）：左右雙欄 PanedWindow。"""
        # 注意：本環境的 ttkbootstrap 只有 Panedwindow（小寫 w），
        # 參考檔的 bs.PanedWindow 在此會 AttributeError
        h_pane = bs.Panedwindow(parent_frame, orient=HORIZONTAL)
        h_pane.pack(fill=BOTH, expand=YES)

        # --- 裝置連線區塊 (Device Connection) ---
        device_frame = bs.Labelframe(h_pane, text="Device Connection", padding=14, width=420)
        h_pane.add(device_frame, weight=1)
        self._create_device_widgets(device_frame)

        # --- 探索操作區塊 (Explorer Actions) ---
        action_frame = bs.Labelframe(h_pane, text="Explorer Actions", padding=14)
        h_pane.add(action_frame, weight=2)
        self._create_action_widgets(action_frame)

    def _create_device_widgets(self, parent: bs.Labelframe) -> None:
        # 裝置清單保留 Treeview：探索工具需要 RSSI 才能判斷哪一支是手邊的手環
        tree_container = bs.Frame(parent)
        tree_container.pack(fill=BOTH, expand=YES)

        columns = ("name", "address", "rssi")
        self.device_tree = bs.Treeview(
            tree_container, columns=columns, show="headings", selectmode="browse", height=5
        )
        self.device_tree.heading("name", text="Name")
        self.device_tree.heading("address", text="Address")
        self.device_tree.heading("rssi", text="RSSI")
        self.device_tree.column("name", width=180, anchor=W)
        self.device_tree.column("address", width=150, anchor=W)
        self.device_tree.column("rssi", width=60, anchor="e")
        self.device_tree.tag_configure("band", font=("Segoe UI", 9, "bold"))

        tree_scroll = bs.Scrollbar(tree_container, orient=VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=tree_scroll.set)
        self.device_tree.pack(side=LEFT, fill=BOTH, expand=YES)
        tree_scroll.pack(side=RIGHT, fill=Y)
        self.device_tree.bind("<<TreeviewSelect>>", self._on_device_selected)

        # 掃描選項
        option_frame = bs.Frame(parent)
        option_frame.pack(fill=X, pady=(8, 5))
        bs.Label(option_frame, text="Timeout (s)").pack(side=LEFT, padx=(0, 4))
        self.timeout_var = bs.StringVar(value="8")
        bs.Spinbox(option_frame, from_=3, to=60, width=4, textvariable=self.timeout_var).pack(side=LEFT)
        self.named_only_var = bs.BooleanVar(value=True)
        bs.Checkbutton(
            option_frame, text="Named devices only", variable=self.named_only_var,
            bootstyle="round-toggle",
        ).pack(side=LEFT, padx=10)

        # 按鈕列
        btn_container = bs.Frame(parent)
        btn_container.pack(fill=X, pady=5)
        self.scan_button = bs.Button(
            btn_container, text="Scan", command=lambda: self.on_scan(), bootstyle=SUCCESS
        )
        self.scan_button.pack(side=LEFT, fill=X, expand=YES, padx=(0, 2))
        self.connect_button = bs.Button(
            btn_container, text="Connect", command=lambda: self.on_connect(),
            state="disabled", bootstyle="primary-outline",
        )
        self.connect_button.pack(side=LEFT, fill=X, expand=YES, padx=2)
        self.disconnect_button = bs.Button(
            btn_container, text="Disconnect", command=lambda: self.on_disconnect(),
            state="disabled", bootstyle=DANGER,
        )
        self.disconnect_button.pack(side=LEFT, fill=X, expand=YES, padx=(2, 0))

    def _create_action_widgets(self, parent: bs.Labelframe) -> None:
        # 讀取單一 UUID
        entry_frame = bs.Frame(parent)
        entry_frame.pack(fill=X, pady=(5, 10))
        entry_frame.columnconfigure(1, weight=1)
        bs.Label(entry_frame, text="Read UUID").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.uuid_var = bs.StringVar(value="2a28")
        self.uuid_entry = bs.Entry(entry_frame, textvariable=self.uuid_var)
        self.uuid_entry.grid(row=0, column=1, sticky="ew", padx=(0, 5))
        self.uuid_entry.bind("<Return>", lambda _event: self.on_read_one(self.uuid_var.get()))
        self.read_button = bs.Button(
            entry_frame, text="Read", command=lambda: self.on_read_one(self.uuid_var.get()),
            state="disabled", bootstyle=PRIMARY,
        )
        self.read_button.grid(row=0, column=2, sticky="e")

        # 探索快捷按鈕：四欄等寬
        quick_frame = bs.Frame(parent)
        quick_frame.pack(fill=X, pady=5)
        for column in range(4):
            quick_frame.columnconfigure(column, weight=1)

        self.gatt_button = bs.Button(
            quick_frame, text="Enumerate GATT", command=lambda: self.on_dump_gatt(),
            state="disabled", bootstyle=INFO,
        )
        self.gatt_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.read_all_button = bs.Button(
            quick_frame, text="Read All", command=lambda: self.on_read_all(),
            state="disabled", bootstyle=INFO,
        )
        self.read_all_button.grid(row=0, column=1, sticky="ew", padx=2)
        self.summary_button = bs.Button(
            quick_frame, text="Summary", command=lambda: self.on_summary(),
            state="disabled", bootstyle=INFO,
        )
        self.summary_button.grid(row=0, column=2, sticky="ew", padx=2)
        self.notify_button = bs.Button(
            quick_frame, text="Start Notify", command=lambda: self.on_toggle_notify(),
            state="disabled", bootstyle=WARNING,
        )
        self.notify_button.grid(row=0, column=3, sticky="ew", padx=(2, 0))

        # 狀態列（參考檔沒有，但探索流程長，保留一行即時狀態）
        # 連線時轉為 SUCCESS 綠並加粗，作為簡易的連線狀態指示（無法在 ttk 畫出圓角 pill，改以顏色+粗體傳達）
        self.status_var = bs.StringVar(value="Disconnected")
        self.status_label = bs.Label(
            parent, textvariable=self.status_var, bootstyle=SECONDARY,
            font=("Segoe UI", 9, "bold"),
        )
        self.status_label.pack(side=LEFT, pady=(8, 0))
        self.target_var = bs.StringVar(value="Target: none")
        bs.Label(parent, textvariable=self.target_var, bootstyle=SECONDARY).pack(
            side=RIGHT, pady=(8, 0)
        )

        # 連線後才可用的元件集中管理
        self.command_buttons = [
            self.read_button, self.gatt_button, self.read_all_button,
            self.summary_button, self.notify_button,
        ]

    def _create_log_action_widgets(self, parent_frame: bs.Labelframe) -> None:
        """中間區域（Log Actions）：沿用參考檔的存檔流程。"""
        self.clear_log_button = bs.Button(
            parent_frame, text="Clear Log Window", command=lambda: self.on_clear_log(),
            bootstyle="secondary-outline",
        )
        self.clear_log_button.pack(side=LEFT, padx=2)

        self.save_printed_button = bs.Button(
            parent_frame, text="Save Printed Log", command=lambda: self.on_save_printed(),
            bootstyle="secondary-outline",
        )
        self.save_printed_button.pack(side=LEFT, padx=2)

        self.start_save_button = bs.Button(
            parent_frame, text="Start to Save Log", command=lambda: self.on_start_save(),
            bootstyle=SUCCESS,
        )
        self.start_save_button.pack(side=LEFT, padx=2)

        self.finish_save_button = bs.Button(
            parent_frame, text="Finish to Save Log", command=lambda: self.on_finish_save(),
            bootstyle=DANGER, state="disabled",
        )
        self.finish_save_button.pack(side=LEFT, padx=2)

        path_button = bs.Button(
            parent_frame, text="Path to Save", command=lambda: self.on_select_path(),
            bootstyle="secondary-outline",
        )
        path_button.pack(side=LEFT, padx=(10, 2))

        self.theme_var = bs.BooleanVar(value=False)
        bs.Checkbutton(
            parent_frame, text="Dark", variable=self.theme_var,
            bootstyle="round-toggle", command=self._toggle_theme,
        ).pack(side=RIGHT, padx=(10, 0))

        self.save_path_entry = bs.Entry(parent_frame, state="readonly")
        self.save_path_entry.pack(side=LEFT, fill=X, expand=YES, padx=2)

    def _create_log_display_widgets(self, parent_frame: bs.Frame) -> None:
        """上方區域：Notebook 分「Communication Log」與「GATT Structure」兩頁。"""
        parent_frame.rowconfigure(0, weight=1)
        parent_frame.columnconfigure(0, weight=1)

        notebook = bs.Notebook(parent_frame)
        notebook.grid(row=0, column=0, sticky=NSEW)

        # 分頁一：通訊紀錄
        log_tab = bs.Frame(notebook, padding=5)
        notebook.add(log_tab, text=" Communication Log ")
        self.comm_log = scrolledtext.ScrolledText(
            log_tab, wrap=tk.WORD, state="disabled", font=("Consolas", 10)
        )
        self.comm_log.pack(fill=BOTH, expand=YES)

        # 分頁二：GATT 結構樹（Mi Band 6 實測 85 個節點，需要專屬區域）
        gatt_tab = bs.Frame(notebook, padding=5)
        notebook.add(gatt_tab, text=" GATT Structure ")
        self.gatt_tree = bs.Treeview(gatt_tab, columns=("detail",), show="tree headings")
        self.gatt_tree.heading("#0", text="Service / Characteristic")
        self.gatt_tree.heading("detail", text="UUID / Properties")
        self.gatt_tree.column("#0", width=340, anchor=W)
        self.gatt_tree.column("detail", width=560, anchor=W)
        gatt_scroll = bs.Scrollbar(gatt_tab, orient=VERTICAL, command=self.gatt_tree.yview)
        self.gatt_tree.configure(yscrollcommand=gatt_scroll.set)
        self.gatt_tree.pack(side=LEFT, fill=BOTH, expand=YES)
        gatt_scroll.pack(side=RIGHT, fill=Y)

    # --- 主題 ---

    def _toggle_theme(self) -> None:
        self.theme = THEME_DARK if self.theme_var.get() else THEME_LIGHT
        self.style.theme_use(self.theme)
        self._apply_log_theme()

    def _apply_log_theme(self) -> None:
        """ScrolledText 不隨 ttk 主題連動，配色需手動同步。"""
        colors = LOG_COLORS[self.theme]
        self.comm_log.configure(
            background=colors["background"],
            foreground=colors["normal"],
            insertbackground=colors["normal"],
        )
        for tag, color in colors.items():
            if tag != "background":
                self.comm_log.tag_configure(tag, foreground=color)

    # --- Helper Methods ---

    def log_to_window(self, message: str, tag: str = "normal") -> None:
        """將訊息附加到通訊紀錄視窗。

        沿用參考檔慣例：[System] 訊息前後各空一行，其餘保留原始格式。
        """
        self.comm_log.configure(state="normal")
        if message.strip().startswith("[System]"):
            formatted = f"\n{message.strip()}\n"
        else:
            formatted = message + "\n"
        self.comm_log.insert(tk.END, formatted, tag)
        self.comm_log.configure(state="disabled")
        self.comm_log.see(tk.END)

    def clear_log_window(self) -> None:
        self.comm_log.configure(state="normal")
        self.comm_log.delete("1.0", tk.END)
        self.comm_log.configure(state="disabled")

    def get_log_content(self) -> str:
        return self.comm_log.get("1.0", tk.END)

    def update_save_path_display(self, path: str) -> None:
        self.save_path_entry.config(state="normal")
        self.save_path_entry.delete(0, tk.END)
        self.save_path_entry.insert(0, path)
        self.save_path_entry.config(state="readonly")

    def set_log_saving_state(self, is_saving: bool) -> None:
        """依是否正在即時儲存，切換相關按鈕的啟用狀態。"""
        self.start_save_button.config(state="disabled" if is_saving else "normal")
        self.finish_save_button.config(state="normal" if is_saving else "disabled")

    def set_devices(self, rows: list[ScanRow]) -> None:
        self.device_tree.delete(*self.device_tree.get_children())
        self._device_indices = []
        for row in rows:
            tags = ("band",) if row.is_band else ()
            self.device_tree.insert("", END, values=(row.name, row.address, row.rssi), tags=tags)
            self._device_indices.append(row.index)
        # 掃描結果為空時不應留著可按的 Connect
        if not rows:
            self.connect_button.config(state="disabled")

    def set_gatt(self, tree: list[GattNode]) -> None:
        self.gatt_tree.delete(*self.gatt_tree.get_children())
        for node in tree:
            self._insert_gatt_node("", node, open_=True)

    def _insert_gatt_node(self, parent: str, node: GattNode, open_: bool = False) -> None:
        item = self.gatt_tree.insert(parent, END, text=node.label, values=(node.detail,), open=open_)
        for child in node.children:
            self._insert_gatt_node(item, child)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def set_target(self, text: str) -> None:
        self.target_var.set(f"Target: {text}")

    def set_notifying(self, notifying: bool) -> None:
        self.notify_button.config(text="Stop Notify" if notifying else "Start Notify")

    def set_ui_connection_state(self, is_connected: bool) -> None:
        """依連線狀態集中設定所有相關元件的啟用/禁用。"""
        self._connected = is_connected
        self.status_label.configure(bootstyle=SUCCESS if is_connected else SECONDARY)
        if is_connected:
            self.connect_button.config(state="disabled")
            self.disconnect_button.config(state="normal")
            self.scan_button.config(state="disabled")
            for button in self.command_buttons:
                button.config(state="normal")
        else:
            has_device = bool(self.device_tree.selection())
            self.connect_button.config(state="normal" if has_device else "disabled")
            self.disconnect_button.config(state="disabled")
            self.scan_button.config(state="normal")
            for button in self.command_buttons:
                button.config(state="disabled")

    def set_busy(self, busy: bool) -> None:
        """操作進行中時鎖住按鈕，避免重複送出重疊的 BLE 請求。

        解除忙碌時不逐一還原，而是重新套用連線狀態，避免兩套狀態互相打架。
        """
        self._busy = busy
        if busy:
            for button in (
                self.scan_button, self.connect_button, self.disconnect_button, *self.command_buttons
            ):
                button.config(state="disabled")
            self.root.configure(cursor="watch")
        else:
            self.root.configure(cursor="")
            self.set_ui_connection_state(self._connected)

    def _on_device_selected(self, _event: object) -> None:
        selection = self.device_tree.selection()
        if not selection:
            return
        row_index = self.device_tree.index(selection[0])
        if 0 <= row_index < len(self._device_indices):
            self.on_select_device(self._device_indices[row_index])
        if not self._connected and not self._busy:
            self.connect_button.config(state="normal")


# ==============================================================================
# Presenter: 串連 Model 與 View
# ==============================================================================

POLL_INTERVAL_MS = 50


class ExplorerPresenter:
    """主控制器，作為 Model 與 View 之間的橋樑，並負責跨執行緒交棒。"""

    def __init__(self, view: ExplorerView) -> None:
        self.view = view
        self.queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.model = BandModel(emit=self._emit)
        self.recorder = LogRecorder()
        self.runner = AsyncRunner()
        self._after_id: str | None = None
        self._busy = False
        self._notifying = False
        self._closing = False

        view.on_scan = self._scan
        view.on_select_device = self._select_device
        view.on_connect = self._connect
        view.on_disconnect = self._disconnect
        view.on_dump_gatt = self._dump_gatt
        view.on_read_all = self._read_all
        view.on_read_one = self._read_one
        view.on_summary = self._summary
        view.on_toggle_notify = self._toggle_notify
        view.on_clear_log = self._clear_log
        view.on_save_printed = self._save_printed
        view.on_start_save = self._start_save
        view.on_finish_save = self._finish_save
        view.on_select_path = self._select_path
        view.on_close = self.close

        self.view.update_save_path_display(str(self.recorder.save_dir))
        self.view.set_ui_connection_state(False)
        self._schedule_poll()

        self._log("[System] Mi Band 6 BLE Explorer — read-only mode.", "system")
        self._log("本工具不會寫入手環，也不會嘗試認證。", "dim")

    # --- 跨執行緒橋接 ---

    def _emit(self, kind: str, payload: Any) -> None:
        """由背景執行緒呼叫。只入佇列，絕不碰 widget。"""
        self.queue.put((kind, payload))

    def _schedule_poll(self) -> None:
        self._after_id = self.view.root.after(POLL_INTERVAL_MS, self._drain_queue)

    def _drain_queue(self) -> None:
        """在 Tk 主執行緒消化佇列，是唯一能碰 widget 的地方。"""
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        if not self._closing:
            self._schedule_poll()

    def _handle(self, kind: str, payload: Any) -> None:
        if kind == "log":
            text, tag = payload
            self._log(text, tag)
        elif kind == "status":
            self.view.set_status(payload)
        elif kind == "devices":
            self.view.set_devices(payload)
        elif kind == "gatt":
            self.view.set_gatt(payload)
        elif kind == "connected":
            self.view.set_ui_connection_state(True)
        elif kind == "disconnected":
            self._notifying = False
            self.view.set_notifying(False)
            self.view.set_ui_connection_state(False)
        elif kind == "notifying":
            self._notifying = bool(payload)
            self.view.set_notifying(self._notifying)
        elif kind == "done":
            self._busy = False
            self.view.set_busy(False)

    def _log(self, message: str, tag: str = "normal") -> None:
        """集中處理所有日誌訊息：更新視窗，並在需要時同步寫入檔案。"""
        self.view.log_to_window(message, tag)
        try:
            self.recorder.write(message)
        except Exception as exc:
            self.view.log_to_window(f"[System] FATAL: Log file write error: {exc}", "fail")

    def _run(self, coro: Coroutine[Any, Any, Any]) -> None:
        """送出一個 Model 操作；期間鎖住按鈕，結束後解鎖。"""
        if self._busy:
            # coroutine 物件在呼叫端就已建立，不執行也必須關閉，
            # 否則會留下 "coroutine was never awaited" 警告
            coro.close()
            self._log("[System] Previous operation still running.", "warn")
            return
        self._busy = True
        self.view.set_busy(True)

        async def wrapper() -> None:
            try:
                await coro
            except Exception as exc:
                self._emit("log", (f"[System] Unexpected error: {exc!r}", "fail"))
            finally:
                self._emit("done", None)

        self.runner.submit(wrapper())

    # --- View -> Presenter 的事件處理 ---

    def _scan(self) -> None:
        try:
            timeout = float(self.view.timeout_var.get())
        except ValueError:
            timeout = 8.0
        self.view.set_devices([])
        self._run(self.model.scan(timeout, self.view.named_only_var.get()))

    def _select_device(self, index: int) -> None:
        self.model.select_target(index)
        if self.model.target is not None:
            name = self.model.target.name or "(no name)"
            self.view.set_target(f"{name} | {self.model.target.address}")

    def _connect(self) -> None:
        self._run(self.model.connect())

    def _disconnect(self) -> None:
        self._run(self.model.disconnect())

    def _dump_gatt(self) -> None:
        self._run(self.model.dump_gatt())

    def _read_all(self) -> None:
        self._run(self.model.read_all())

    def _read_one(self, uuid: str) -> None:
        if uuid.strip():
            self._run(self.model.read_one(uuid))

    def _summary(self) -> None:
        self._run(self.model.summary())

    def _toggle_notify(self) -> None:
        if self._notifying:
            self._run(self.model.stop_notify())
        else:
            self._run(self.model.start_notify())

    # --- Log Actions ---

    def _clear_log(self) -> None:
        self.view.clear_log_window()
        self._log("[System] Log window cleared.", "system")

    def _save_printed(self) -> None:
        content = self.view.get_log_content()
        if not content.strip():
            self._log("[System] Log is empty, nothing to save.", "warn")
            return
        try:
            path = self.recorder.save_snapshot(content)
        except Exception as exc:
            self._log(f"[System] Error saving log: {exc}", "fail")
            return
        self._log(f"[System] Log saved to: {path}", "ok")

    def _start_save(self) -> None:
        if self.recorder.is_saving:
            self._log("[System] Already saving log.", "warn")
            return
        try:
            path = self.recorder.start()
        except Exception as exc:
            self._log(f"[System] Error starting log save: {exc}", "fail")
            return
        self.view.set_log_saving_state(True)
        self._log(f"[System] Started saving log to: {path}", "ok")

    def _finish_save(self) -> None:
        if not self.recorder.is_saving:
            self._log("[System] Not currently saving a log.", "warn")
            return
        try:
            self.recorder.finish()
        except Exception as exc:
            self._log(f"[System] Error finishing log save: {exc}", "fail")
        self.view.set_log_saving_state(False)
        self._log("[System] Finished saving log.", "ok")

    def _select_path(self) -> None:
        new_dir = filedialog.askdirectory(initialdir=str(self.recorder.save_dir))
        if not new_dir:
            return
        self.recorder.save_dir = Path(new_dir)
        self.view.update_save_path_display(new_dir)
        self._log(f"[System] Log save path changed to: {new_dir}", "system")

    # --- 程式關閉處理 ---

    def close(self) -> None:
        """依序：停 after 輪詢 → 收 log 檔 → 斷 BLE → 收事件迴圈 → destroy。"""
        if self._closing:
            return
        self._closing = True
        self.view.set_status("Closing…")

        # 步驟 1: 取消排程中的 after callback，避免 destroy 後觸發 invalid command name
        if self._after_id is not None:
            self.view.root.after_cancel(self._after_id)
            self._after_id = None

        # 步驟 2: 關閉日誌檔案控制代碼
        self.recorder.close_abruptly()

        # 步驟 3: 斷開 BLE，給有限等待時間避免卡住關閉
        try:
            self.runner.submit(self.model.disconnect()).result(timeout=5.0)
        except Exception:
            pass

        # 步驟 4: 取消未完成工作並收掉背景事件迴圈
        self.runner.shutdown(timeout=5.0)

        # 步驟 5: 銷毀主視窗
        self.view.root.destroy()


# ==============================================================================
# 進入點
# ==============================================================================


def main() -> None:
    # 必須在建立 root 之前設定，否則工作列會顯示 Python 直譯器的圖示
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception as exc:
            print(f"Warning: Could not set AppUserModelID: {exc}")

    root = bs.Window(themename=THEME_LIGHT)
    view = ExplorerView(root)
    presenter = ExplorerPresenter(view)
    try:
        root.mainloop()
    finally:
        # 主迴圈因未預期例外或主控台中斷而結束時，仍要收掉背景執行緒與檔案
        presenter.close()


if __name__ == "__main__":
    main()
