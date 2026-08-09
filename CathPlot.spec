# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
# [수정 - 빌드 경고 원인] gnu_generator.py가 PIL(Pillow)을 함수 안 try/except로
# "delayed, optional" import하는데(legend 폭 실측/PNG 300dpi 업스케일용),
# PyInstaller의 정적 분석이 이런 지연 import는 못 찾아서 dist에 PIL이 통째로
# 빠져 있었음(build/CathPlot/warn-CathPlot.txt의 "missing module named PIL"
# 경고, dist/CathPlot/_internal에 PIL 폴더 자체가 없는 것으로 직접 확인) -
# 코드 자체는 try/except로 안전하게 fallback해서 exe가 죽지는 않지만, 그
# fallback 경로가 "PNG는 300dpi 업스케일 없이 72dpi로 저장"이라 최근
# 지적된 "Word 이미지 해상도가 떨어진다" 증상의 실제 원인으로 보임.
hiddenimports = ['PIL']
tmp_ret = collect_all('pywin32')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['cathplot_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='CathPlot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CathPlot',
)
