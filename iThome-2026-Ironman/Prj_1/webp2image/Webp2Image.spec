# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_data_files

# conda 的原生 DLL（ffi-8 / tcl86t / tk86t 等）放在 <env>\Library\bin，不在 PyInstaller
# 的搜尋路徑上。少了這段，打包會成功但執行時閃退：
# ImportError: DLL load failed while importing _ctypes。
_conda_dll_dir = os.path.join(sys.prefix, 'Library', 'bin')
if os.path.isdir(_conda_dll_dir):
    os.environ['PATH'] = _conda_dll_dir + os.pathsep + os.environ.get('PATH', '')

# ttkbootstrap 2.x 需要隨附字型與圖示資產（assets/icons/bootstrap.ttf 等），
# PyInstaller 不會自動收集，缺少時程式啟動就會 FileNotFoundError。
ttkbootstrap_datas = collect_data_files('ttkbootstrap')

a = Analysis(
    ['webp2image.py'],
    pathex=[],
    binaries=[],
    # .ico 同時給 exe 圖示與視窗圖示用；onefile 會解壓到 sys._MEIPASS，程式端以 resource_path() 讀取
    datas=[('webp2image_icon.ico', '.')] + ttkbootstrap_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='Webp2Image',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # 不使用 UPX：本機未安裝，且壓縮後容易被防毒軟體誤判
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['webp2image_icon.ico'],
)
