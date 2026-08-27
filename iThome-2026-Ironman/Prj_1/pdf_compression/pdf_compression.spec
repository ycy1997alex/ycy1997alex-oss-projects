# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec：PDF 壓縮工具（onefile）
# 打包：pyinstaller pdf_compression.spec
# 應用程式圖示 pdf_compression.ico 為多解析度（16/32/48/64/128/256 px）：
# icon= 供 .exe 檔案圖示使用，datas 則讓執行時的 iconbitmap() 讀得到（onefile 解壓到 sys._MEIPASS）。

import os
import sys

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# conda 環境把 libexpat / tcl86t / tk86t 等原生 DLL 放在 <env>\Library\bin，
# 不在 PyInstaller 預設的搜尋路徑上；沒補上會打包成功但執行時 pyexpat 載入失敗。
# 非 conda 環境（venv）沒有這個目錄，加了也不影響。
_conda_dll_dir = os.path.join(sys.prefix, 'Library', 'bin')
if os.path.isdir(_conda_dll_dir):
    os.environ['PATH'] = _conda_dll_dir + os.pathsep + os.environ.get('PATH', '')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # ttkbootstrap 2.x 的圖示字型／樣式資產（ttkbootstrap/assets/…）是執行時才讀的檔案，
    # 靜態分析抓不到，必須明確收集，否則建立 Window 時會 FileNotFoundError。
    datas=[('pdf_compression.ico', '.')] + collect_data_files('ttkbootstrap'),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # pandas/matplotlib/scipy 只被 pymupdf.table 內一個沒用到、且已用 try/except 保護的
    # Table.to_pandas() 方法引用；本程式未使用表格擷取功能，排除以大幅縮小體積與加快啟動速度。
    excludes=['pandas', 'matplotlib', 'scipy'],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PDF壓縮工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # 不使用 UPX（與 image2ico / webp2image 一致）：壓縮後的執行檔容易被防毒誤判
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='pdf_compression.ico',
)
