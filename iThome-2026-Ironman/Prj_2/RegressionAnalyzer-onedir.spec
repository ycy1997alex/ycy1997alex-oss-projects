# -*- mode: python ; coding: utf-8 -*-
"""onedir 打包設定（啟動快，交付時整個資料夾一起給）。

建置：
    C:\\Users\\Alex\\anaconda3\\envs\\stats\\python.exe -m PyInstaller ^
        RegressionAnalyzer-onedir.spec --noconfirm --distpath dist\\onedir --workpath build\\onedir

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
datas += collect_data_files("docx")           # python-docx 的 default.docx 樣板

hiddenimports = [
    "sklearn.utils._typedefs",
    "sklearn.utils._heap",
    "sklearn.utils._sorting",
    "sklearn.utils._vector_sentinel",
    "scipy._lib.array_api_compat.numpy.fft",
    "statsmodels.tsa.statespace._filters",
    "statsmodels.tsa.statespace._smoothers",
]

# 這個環境裡不存在也無妨；留著是保險，不要因為現在沒對到就刪掉。
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
    [],
    exclude_binaries=True,
    name="RegressionAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RegressionAnalyzer",
)
