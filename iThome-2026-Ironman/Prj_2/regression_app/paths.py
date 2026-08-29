"""執行時資源路徑。

PyInstaller onefile 會把 datas 解壓到一個暫存資料夾（sys._MEIPASS），
寫死的相對路徑在打包後一定會失效，所有資源都要走這裡。
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """回傳打包前後都成立的資源絕對路徑。"""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = Path(__file__).resolve().parent.parent
    return Path(base) / relative
