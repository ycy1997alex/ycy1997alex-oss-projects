# -*- mode: python ; coding: utf-8 -*-
r"""onefile 打包設定（單一 exe 好交付，代價是每次啟動都要解壓）。

建置：
    C:\Users\Alex\anaconda3\envs\nb_ble\python.exe -m PyInstaller ^
        MiBand6BleExplorer-onefile.spec --noconfirm ^
        --distpath dist\onefile --workpath build\onefile

驗收標準是「建置紀錄裡沒有任何 Library not found」，不是 exit 0 —— 兩者都會回 0。
"""

import os
import sys

# conda 把原生 DLL 放在 <sys.prefix>\Library\bin，這個目錄不在 PyInstaller 的
# 相依搜尋路徑上。少了這一行，建置會成功，但 .exe 啟動時死在
# ImportError: DLL load failed while importing _ctypes。
# 用 Analysis(pathex=[...]) 沒有用：pathex 管的是 Python 模組搜尋，DLL 走的是 PATH。
os.environ["PATH"] = os.path.join(sys.prefix, "Library", "bin") + os.pathsep + os.environ["PATH"]

from PyInstaller.utils.hooks import collect_data_files

datas = [("app.ico", ".")]
datas += collect_data_files("ttkbootstrap")   # 主題定義

# bleak 的 Windows 後端走 winrt 投影模組，全部是動態 import。原本在這裡列了
# 七個 winrt.* 當 hiddenimports，實測拿掉之後 exe 照樣掃得到裝置、體積也一樣
# ——pyinstaller-hooks-contrib 內建的 bleak hook 已經收乾淨了。留空是刻意的。
hiddenimports = []

# 這個環境裡不存在也無妨；留著是保險，不要因為現在沒對到就刪掉。
excludes = [
    "PyQt5", "PyQt6", "PySide2", "PySide6",
    "numpy", "pandas", "scipy", "matplotlib",
    "IPython", "jupyter", "notebook", "nbconvert", "nbformat",
    "pytest", "sphinx", "tornado",
]

a = Analysis(
    ["mi_band_explorer_gui.py"],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MiBand6BleExplorer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app.ico",
)
