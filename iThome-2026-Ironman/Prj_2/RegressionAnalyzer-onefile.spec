# -*- mode: python ; coding: utf-8 -*-
"""onefile 打包設定（單一 exe 好交付，代價是每次啟動都要解壓）。

建置：
    C:\\Users\\AlexYu\\.conda\\envs\\stats\\python.exe -m PyInstaller ^
        RegressionAnalyzer-onefile.spec --noconfirm --distpath dist\\onefile --workpath build\\onefile

驗收標準是「建置紀錄裡沒有任何 Library not found」，不是 exit 0 —— 兩者都會回 0。
"""

import os
import sys

# 見 RegressionAnalyzer-onedir.spec 的同一段說明：conda 的原生 DLL 在
# <sys.prefix>\Library\bin，不加進 PATH 的話 .exe 會在啟動時死掉。
os.environ["PATH"] = os.path.join(sys.prefix, "Library", "bin") + os.pathsep + os.environ["PATH"]

from PyInstaller.utils.hooks import collect_data_files

datas = [("app.ico", ".")]
datas += collect_data_files("ttkbootstrap")
datas += collect_data_files("docx")

hiddenimports = [
    "sklearn.utils._typedefs",
    "sklearn.utils._heap",
    "sklearn.utils._sorting",
    "sklearn.utils._vector_sentinel",
    "scipy._lib.array_api_compat.numpy.fft",
    "statsmodels.tsa.statespace._filters",
    "statsmodels.tsa.statespace._smoothers",
]

excludes = [
    "PyQt5", "PyQt6", "PySide2", "PySide6",
    "IPython", "jupyter", "notebook", "nbconvert", "nbformat",
    "pytest", "sphinx", "tornado",
]

a = Analysis(
    ["main.py"],
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
    name="RegressionAnalyzer",
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
