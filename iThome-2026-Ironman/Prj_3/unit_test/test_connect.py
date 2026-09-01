"""測試 2：連線手環，列舉 GATT、讀取摘要與所有可讀 characteristic。

同時做解碼器的離線驗證——用先前實機抓到的原始位元組，確認解碼結果
不會因為改動而悄悄跑掉（不必連手環也能跑到這一段）。

執行：
    python unit_test\\test_connect.py
    python unit_test\\test_connect.py AA:BB:CC:DD:EE:FF   # 指定位址（不給就讀 device.local）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import device_config  # noqa: E402
import mi_band_explorer as m  # noqa: E402


def test_decoders() -> None:
    """離線驗證：資料取自 2026-08-14 對 Mi Band 6 的實機讀取。"""
    print(m.c("\n-- 解碼器離線驗證 --", m.C_BOLD + m.C_CYAN))

    cases = [
        (
            "00002a2b-0000-1000-8000-00805f9b34fb",
            "ea07080e0a32240500 0020".replace(" ", ""),
            "2026-08-14 10:50:36 星期五",
        ),
        (
            "00000006" + m.HUAMI_SUFFIX,
            "0f6300ea07080e0a301e20ea07080e0a30232064",
            "電量 99 %，狀態 未充電，時間戳1 2026-08-14 10:48:30 (UTC+8)，"
            "時間戳2 2026-08-14 10:48:35 (UTC+8)，上次充電結束電量 100 %",
        ),
        ("00002a19-0000-1000-8000-00805f9b34fb", "63", "99 %"),
        # 即時步數：實機 notify 推送的封包，步數 502
        ("00000007" + m.HUAMI_SUFFIX, "0cf6010000530100000c000000", "步數 502（其餘位元組未解析）"),
    ]

    failures = 0
    for uuid, hex_data, expected in cases:
        actual = m.decode_value(uuid, bytes.fromhex(hex_data))
        if actual == expected:
            m.ok(f"{uuid[:8]}  {actual}")
        else:
            failures += 1
            m.fail(f"{uuid[:8]}  預期 {expected!r}")
            print(f"        實得 {actual!r}")

    if failures:
        m.fail(f"{failures} 項解碼驗證未通過")
    else:
        m.ok("解碼器全部通過")


async def main() -> None:
    m.enable_ansi()
    test_decoders()

    # 位址優先序：命令列參數 > device.local > 沒有（改用名稱掃）
    address = sys.argv[1] if len(sys.argv) > 1 else device_config.load("address")
    explorer = m.Explorer()

    device = await device_config.find_device(address)
    if device is None:
        m.fail("找不到手環，跳過連線測試")
        return

    explorer.target = device
    await explorer.connect()
    if explorer.client is None:
        return
    try:
        await explorer.dump_gatt()
        await explorer.summary()
        await explorer.read_all()
    finally:
        await explorer.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
