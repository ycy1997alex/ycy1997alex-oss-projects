"""Mi Band 6 BLE Explorer —— 唯讀探索工具。

用途：掃描、連線小米手環 6（或其他 BLE 裝置），列舉完整 GATT 結構、
讀取所有可讀 characteristic、監看 notify 封包。

刻意「唯讀」：本程式不會寫入任何 characteristic，不會嘗試 Huami 認證，
也不會修改手環上的任何設定。手環的私有服務（0xFEE0）多數需要 auth key，
未認證時讀取會被拒絕，程式會把拒絕原因如實列出。

環境：Python 3.13 + bleak 2.0（2.x API，與 0.2x 範例寫法不同）
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
from bleak.uuids import normalize_uuid_str, uuidstr_to_str

# --------------------------------------------------------------------------
# 終端機色彩
# --------------------------------------------------------------------------

C_RESET = "\033[0m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_RED = "\033[31m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"


def enable_ansi() -> None:
    """在 Windows 主控台啟用 ANSI 跳脫序列（VT processing）。"""
    if sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)


def c(text: str, color: str) -> str:
    return f"{color}{text}{C_RESET}"


def title(text: str) -> None:
    print(f"\n{c('=' * 68, C_BLUE)}")
    print(c(f" {text}", C_BOLD + C_CYAN))
    print(c("=" * 68, C_BLUE))


def ok(text: str) -> None:
    print(c(f"  [OK] {text}", C_GREEN))


def warn(text: str) -> None:
    print(c(f"  [!] {text}", C_YELLOW))


def fail(text: str) -> None:
    print(c(f"  [X] {text}", C_RED))


# --------------------------------------------------------------------------
# UUID 對照表
# --------------------------------------------------------------------------

# 華米（Huami/Zepp）私有 UUID base：0000XXXX-0000-3512-2118-0009af100700
HUAMI_SUFFIX = "-0000-3512-2118-0009af100700"

# 已知 characteristic 的用途說明。key 一律為小寫完整 128-bit UUID。
KNOWN_UUIDS: dict[str, str] = {
    # 標準 GATT
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
    # 華米私有
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

# 服務層級的說明
KNOWN_SERVICES: dict[str, str] = {
    "0000180a-0000-1000-8000-00805f9b34fb": "裝置資訊 (免認證可讀)",
    "0000180d-0000-1000-8000-00805f9b34fb": "心率 (通常需認證)",
    "0000180f-0000-1000-8000-00805f9b34fb": "電池",
    "00001800-0000-1000-8000-00805f9b34fb": "通用存取 (GAP)",
    "00001801-0000-1000-8000-00805f9b34fb": "通用屬性 (GATT)",
    "0000fee0-0000-1000-8000-00805f9b34fb": "華米主服務 (私有，多數需認證)",
    "0000fee1-0000-1000-8000-00805f9b34fb": "華米認證服務",
}


def describe_uuid(uuid: str, table: dict[str, str]) -> str:
    """回傳 UUID 的人類可讀說明；先查自訂表，再退回 bleak 內建表。"""
    key = uuid.lower()
    if key in table:
        return table[key]
    builtin = uuidstr_to_str(key)
    # bleak 查不到時會回傳 "Unknown"
    return builtin if builtin and builtin != "Unknown" else "未知"


# --------------------------------------------------------------------------
# 資料呈現
# --------------------------------------------------------------------------


def hexdump(data: bytes) -> str:
    """單行 hex + 可列印 ASCII。"""
    hex_part = " ".join(f"{b:02x}" for b in data)
    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"{hex_part}  |{ascii_part}|"


WEEKDAYS = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}


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

    # 純文字型 characteristic
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


def print_value(uuid: str, data: bytes, indent: str = "      ") -> None:
    print(f"{indent}{c(hexdump(data), C_DIM)}")
    decoded = decode_value(uuid, data)
    if decoded:
        print(f"{indent}{c('=> ' + decoded, C_GREEN + C_BOLD)}")


# --------------------------------------------------------------------------
# 探索器
# --------------------------------------------------------------------------

MI_BAND_HINTS = ("mi band", "mi smart band", "xiaomi", "amazfit")


class Explorer:
    def __init__(self) -> None:
        self.found: list[tuple[BLEDevice, AdvertisementData]] = []
        self.target: BLEDevice | None = None
        self.client: BleakClient | None = None

    # ---------------- 掃描 ----------------

    async def scan(self, timeout: float = 8.0) -> None:
        title(f"掃描 BLE 裝置（{timeout:.0f} 秒）")
        # 環境中的無名稱廣播裝置動輒上百個，預設濾掉以免刷屏
        answer = (await ainput("  只列出有名稱的裝置？(Y/n): ")).strip().lower()
        named_only = answer != "n"

        print(c("  請確認手環未被手機 App 佔用，並在筆電附近。", C_DIM))
        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
        # 依訊號強度由強到弱排序
        self.found = sorted(discovered.values(), key=lambda pair: pair[1].rssi, reverse=True)

        if not self.found:
            fail("沒有掃到任何裝置。檢查藍牙是否開啟。")
            return

        hidden = 0
        print()
        for idx, (device, adv) in enumerate(self.found):
            name = device.name or adv.local_name or "(無名稱)"
            if named_only and not (device.name or adv.local_name):
                hidden += 1
                continue
            is_band = any(hint in name.lower() for hint in MI_BAND_HINTS)
            marker = c(" <== 疑似小米/華米裝置", C_MAGENTA + C_BOLD) if is_band else ""
            name_col = c(f"{name:<26}", C_YELLOW if is_band else C_RESET)
            print(f"  [{idx:>2}] {name_col} {device.address}  RSSI {adv.rssi:>4} dBm{marker}")
            if adv.service_uuids:
                short = [normalize_uuid_str(u)[4:8] for u in adv.service_uuids]
                print(f"       {c('廣播服務: ' + ', '.join(short), C_DIM)}")
            if adv.manufacturer_data:
                for company, payload in adv.manufacturer_data.items():
                    print(f"       {c(f'廠商資料 0x{company:04x}: {payload.hex()}', C_DIM)}")
        # 編號沿用完整清單的索引，過濾後會不連續，但選項 2 仍可直接輸入
        ok(f"共 {len(self.found)} 個裝置")
        if hidden:
            print(c(f"  （已隱藏 {hidden} 個無名稱裝置，選 n 可全部列出）", C_DIM))

    async def choose_target(self) -> None:
        if not self.found:
            warn("尚未掃描。請先執行選項 1。")
            return
        raw = await ainput("  輸入編號（或直接輸入 MAC 位址）: ")
        raw = raw.strip()
        if not raw:
            return
        if raw.isdigit() and int(raw) < len(self.found):
            self.target = self.found[int(raw)][0]
        else:
            device = await BleakScanner.find_device_by_address(raw, timeout=10.0)
            if device is None:
                fail(f"找不到位址 {raw}")
                return
            self.target = device
        ok(f"目標設為 {self.target.name or '(無名稱)'} / {self.target.address}")

    # ---------------- 連線 ----------------

    def _on_disconnect(self, _client: BleakClient) -> None:
        print(c("\n  [!] 裝置已斷線", C_YELLOW))

    async def connect(self) -> None:
        if self.target is None:
            warn("尚未選定目標。請先執行選項 1、2。")
            return
        if self.client is not None and self.client.is_connected:
            warn("已在連線中。")
            return

        title(f"連線 {self.target.name or self.target.address}")
        client = BleakClient(self.target, disconnected_callback=self._on_disconnect, timeout=20.0)
        try:
            await client.connect()
        except BleakError as exc:
            fail(f"連線失敗: {exc}")
            print(c("  提示：手環同時只能被一個中央裝置連線，請先在手機關閉 Zepp Life。", C_DIM))
            return
        self.client = client
        ok("連線成功")

    async def disconnect(self) -> None:
        if self.client is None:
            return
        try:
            await self.client.disconnect()
            ok("已斷線")
        except BleakError as exc:
            fail(f"斷線時發生錯誤: {exc}")
        finally:
            self.client = None

    def _require_client(self) -> BleakClient | None:
        if self.client is None or not self.client.is_connected:
            warn("尚未連線。請先執行選項 3。")
            return None
        return self.client

    # ---------------- GATT ----------------

    async def dump_gatt(self) -> None:
        client = self._require_client()
        if client is None:
            return

        title("GATT 完整結構")
        for service in client.services:
            desc = describe_uuid(service.uuid, KNOWN_SERVICES)
            print(f"\n  {c('SERVICE', C_BLUE + C_BOLD)} {c(service.uuid, C_CYAN)}  {c(desc, C_MAGENTA)}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                cdesc = describe_uuid(char.uuid, KNOWN_UUIDS)
                print(
                    f"    {c('CHAR', C_BOLD)} {char.uuid}  "
                    f"{c(f'[{props}]', C_YELLOW)}  handle={char.handle}"
                )
                print(f"      {c(cdesc, C_MAGENTA)}")
                for descriptor in char.descriptors:
                    dname = describe_uuid(descriptor.uuid, {})
                    print(f"      {c(f'DESC {descriptor.uuid}  {dname}', C_DIM)}")

    async def read_all(self) -> None:
        """讀取所有帶 read 屬性的 characteristic，並統計成功/被拒。"""
        client = self._require_client()
        if client is None:
            return

        title("讀取所有可讀的 characteristic")
        succeeded = 0
        denied: list[tuple[str, str]] = []

        for service in client.services:
            for char in service.characteristics:
                if "read" not in char.properties:
                    continue
                cdesc = describe_uuid(char.uuid, KNOWN_UUIDS)
                print(f"\n  {char.uuid}  {c(cdesc, C_MAGENTA)}")
                try:
                    data = await client.read_gatt_char(char)
                except BleakError as exc:
                    fail(f"讀取被拒: {exc}")
                    denied.append((char.uuid, str(exc)))
                    continue
                except Exception as exc:  # WinRT 後端可能拋出非 BleakError
                    fail(f"讀取失敗: {exc!r}")
                    denied.append((char.uuid, repr(exc)))
                    continue
                succeeded += 1
                print_value(char.uuid, bytes(data))

        print()
        ok(f"成功讀取 {succeeded} 個")
        if denied:
            warn(f"{len(denied)} 個被拒絕（多為 Read Not Permitted，屬手環刻意封鎖的欄位）：")
            for uuid, reason in denied:
                print(f"    {uuid}  {c(reason, C_DIM)}")

    async def read_one(self) -> None:
        client = self._require_client()
        if client is None:
            return
        raw = (await ainput("  輸入 characteristic UUID（可用 16-bit 短碼如 2a26）: ")).strip()
        if not raw:
            return
        try:
            uuid = normalize_uuid_str(raw)
        except ValueError:
            fail("UUID 格式不正確")
            return
        try:
            data = await client.read_gatt_char(uuid)
        except Exception as exc:
            fail(f"讀取失敗: {exc}")
            return
        print(f"  {uuid}  {c(describe_uuid(uuid, KNOWN_UUIDS), C_MAGENTA)}")
        print_value(uuid, bytes(data))

    # ---------------- Notify ----------------

    async def monitor_notify(self) -> None:
        """訂閱所有可 notify/indicate 的 characteristic 並監看一段時間。"""
        client = self._require_client()
        if client is None:
            return

        candidates = [
            char
            for service in client.services
            for char in service.characteristics
            if "notify" in char.properties or "indicate" in char.properties
        ]
        if not candidates:
            warn("此裝置沒有任何可訂閱的 characteristic。")
            return

        title(f"監看 notify（{len(candidates)} 個候選 characteristic）")

        def callback(char: BleakGATTCharacteristic, data: bytearray) -> None:
            stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            cdesc = describe_uuid(char.uuid, KNOWN_UUIDS)
            print(f"\n  {c(stamp, C_CYAN)}  {char.uuid}  {c(cdesc, C_MAGENTA)}")
            print_value(char.uuid, bytes(data), indent="    ")

        subscribed: list[BleakGATTCharacteristic] = []
        for char in candidates:
            try:
                await client.start_notify(char, callback)
                subscribed.append(char)
                ok(f"已訂閱 {char.uuid}  {describe_uuid(char.uuid, KNOWN_UUIDS)}")
            except Exception as exc:
                fail(f"訂閱失敗 {char.uuid}: {exc}")

        if not subscribed:
            warn("沒有任何 characteristic 訂閱成功（未認證時屬正常）。")
            return

        raw = (await ainput("\n  監看幾秒？（預設 30）: ")).strip()
        seconds = float(raw) if raw.replace(".", "", 1).isdigit() else 30.0
        print(c(f"  監看中… {seconds:.0f} 秒（手環未認證時可能完全沒有封包）", C_DIM))
        try:
            await asyncio.sleep(seconds)
        finally:
            for char in subscribed:
                try:
                    await client.stop_notify(char)
                except Exception:
                    pass
        ok("監看結束")

    # ---------------- 摘要 ----------------

    async def summary(self) -> None:
        """免認證就能拿到的手環資訊摘要。"""
        client = self._require_client()
        if client is None:
            return

        title("手環摘要（僅免認證欄位）")
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
                print(f"  {label:<10} {c('無法讀取', C_RED)}")
                print(f"  {'':<10} {c(str(exc), C_DIM)}")
                continue
            decoded = decode_value(uuid, bytes(data)) or bytes(data).hex()
            print(f"  {label:<10} {c(decoded, C_GREEN + C_BOLD)}")

        # 即時步數禁止 read，但實測 notify 免認證就會推送，故導向選項 8
        print(f"  {'即時步數':<8} {c('禁止直接讀取，請用選項 8 監看 notify', C_YELLOW)}")


# --------------------------------------------------------------------------
# 互動選單
# --------------------------------------------------------------------------


async def ainput(prompt: str) -> str:
    """在執行緒中呼叫 input()，避免阻塞事件迴圈（斷線 callback 才能運作）。"""
    return await asyncio.to_thread(input, prompt)


MENU = """
  1) 掃描 BLE 裝置
  2) 選擇目標裝置
  3) 連線
  4) 斷線
  5) 列舉 GATT 完整結構
  6) 讀取所有可讀 characteristic
  7) 讀取單一 characteristic
  8) 監看 notify
  9) 手環摘要（免認證欄位）
  0) 離開
"""


async def main() -> None:
    enable_ansi()
    explorer = Explorer()

    print(c("\n  Mi Band 6 BLE Explorer —— 唯讀模式", C_BOLD + C_CYAN))
    print(c("  本工具不會寫入手環，也不會嘗試認證。", C_DIM))

    actions = {
        "1": explorer.scan,
        "2": explorer.choose_target,
        "3": explorer.connect,
        "4": explorer.disconnect,
        "5": explorer.dump_gatt,
        "6": explorer.read_all,
        "7": explorer.read_one,
        "8": explorer.monitor_notify,
        "9": explorer.summary,
    }

    try:
        while True:
            connected = explorer.client is not None and explorer.client.is_connected
            state = c("已連線", C_GREEN) if connected else c("未連線", C_DIM)
            target = explorer.target.address if explorer.target else "未選定"
            print(c("\n" + "-" * 68, C_BLUE))
            print(f"  狀態: {state}   目標: {c(target, C_YELLOW)}")
            print(MENU)
            choice = (await ainput("  選擇: ")).strip()
            if choice == "0":
                break
            action = actions.get(choice)
            if action is None:
                warn("無效的選項")
                continue
            try:
                await action()
            except Exception as exc:
                fail(f"執行時發生例外: {exc!r}")
    finally:
        await explorer.disconnect()
        print(c("\n  再見。\n", C_CYAN))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(c("\n  已中斷。\n", C_YELLOW))
