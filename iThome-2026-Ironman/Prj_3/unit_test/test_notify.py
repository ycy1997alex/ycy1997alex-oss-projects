"""測試 3：訂閱手環所有可 notify 的 characteristic 並監看封包。

這是唯一能拿到即時步數的路徑——0x0007 禁止 read，但 notify 免認證就會推送。
測試中會把 mi_band_explorer.ainput 換掉以免卡在互動輸入。

執行：
    python unit_test\\test_notify.py
    python unit_test\\test_notify.py 60                    # 監看 60 秒
    python unit_test\\test_notify.py 60 AA:BB:CC:DD:EE:FF  # 指定秒數與位址
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import device_config  # noqa: E402
import mi_band_explorer as m  # noqa: E402

DEFAULT_SECONDS = "20"


async def main() -> None:
    m.enable_ansi()

    seconds = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SECONDS
    # 位址優先序：命令列參數 > device.local > 沒有（改用名稱掃）
    address = sys.argv[2] if len(sys.argv) > 2 else device_config.load("address")

    # monitor_notify 會用 ainput 詢問監看秒數，測試中直接餵入
    async def scripted_input(prompt: str) -> str:
        print(f"{prompt}{seconds}")
        return seconds

    m.ainput = scripted_input

    explorer = m.Explorer()
    device = await device_config.find_device(address)
    if device is None:
        m.fail("找不到手環")
        return

    explorer.target = device
    await explorer.connect()
    if explorer.client is None:
        return
    try:
        await explorer.monitor_notify()
    finally:
        await explorer.disconnect()

    print(m.c("\n  提示：手環未認證時多數 characteristic 不會推送封包，", m.C_DIM))
    print(m.c("  但 0x0007 即時步數會——走動幾步再跑一次即可看到數字變化。", m.C_DIM))


if __name__ == "__main__":
    asyncio.run(main())
