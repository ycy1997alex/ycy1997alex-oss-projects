"""測試 1：掃描 BLE 裝置。

驗證 bleak 2.0 的 discover(return_adv=True) 路徑，以及廣播封包解析
（名稱、RSSI、service UUID、廠商資料）。不需連線，不影響手環。

執行：
    python unit_test\\test_scan.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mi_band_explorer as m  # noqa: E402


async def main() -> None:
    m.enable_ansi()

    # scan() 會詢問是否只列出有名稱的裝置，測試中直接採用預設（Y）
    async def scripted_input(prompt: str) -> str:
        print(prompt)
        return ""

    m.ainput = scripted_input

    explorer = m.Explorer()
    await explorer.scan(timeout=8.0)

    # 檢查是否掃到小米手環
    bands = [
        (device, adv)
        for device, adv in explorer.found
        if any(hint in (device.name or adv.local_name or "").lower() for hint in m.MI_BAND_HINTS)
    ]
    print()
    if bands:
        m.ok(f"找到 {len(bands)} 支小米/華米裝置：")
        for device, adv in bands:
            print(f"    {device.name}  {device.address}  RSSI {adv.rssi} dBm")
    else:
        m.warn("沒有掃到小米/華米裝置。確認手環在範圍內且螢幕已喚醒。")


if __name__ == "__main__":
    asyncio.run(main())
