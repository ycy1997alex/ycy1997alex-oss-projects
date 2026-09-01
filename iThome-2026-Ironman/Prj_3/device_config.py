"""測試腳本用來決定「要測哪一支手環」的地方。

手環的 MAC 位址屬於裝置識別資訊，不該寫死在會進版控的程式碼裡，
所以放在同目錄的 device.local，由 .gitignore 排除。
複製 device.local.example 改成自己的位址即可。

檔案格式是 `key = value`，井字號開頭的行是註解。
沒有這個檔案也要能跑，所以 find_device() 在拿不到位址的時候
會退回用名稱掃描，而不是直接失敗。
"""

from __future__ import annotations

from pathlib import Path

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

import mi_band_explorer as m

CONFIG_PATH = Path(__file__).resolve().parent / "device.local"


def load(key: str) -> str | None:
    """回傳設定檔裡某個 key 的值；檔案不存在或沒有這個 key 時回傳 None。"""
    if not CONFIG_PATH.exists():
        return None
    for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip() or None
    return None


async def find_device(address: str | None, timeout: float = 15.0) -> BLEDevice | None:
    """有位址就照位址找，沒有就用名稱掃第一支小米／華米裝置。"""
    if address:
        print(m.c(f"\n  搜尋 {address} …", m.C_DIM))
        return await BleakScanner.find_device_by_address(address, timeout=timeout)

    print(m.c("\n  device.local 沒有位址，改用名稱掃描 …", m.C_DIM))

    def matches(_device: BLEDevice, adv) -> bool:
        name = (adv.local_name or "").lower()
        return any(hint in name for hint in m.MI_BAND_HINTS)

    return await BleakScanner.find_device_by_filter(matches, timeout=timeout)
