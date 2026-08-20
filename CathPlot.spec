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
# [수정 - 더 심각한 원인 발견] PNG/JPG는 이제 PDF를 PyMuPDF(fitz)로
# 래스터화하는 방식이 기준인데, 이 fitz도 같은 방식(함수 내 try/except
# 지연 import)이라 PyInstaller가 못 찾아서 exe에서 통째로 빠져 있었음 -
# 없으면 legend box 크기 추정이 옛날(레거시 pngcairo 전용) 기준으로
# 조용히 폴백해서 "legend box가 축의 107%로 커짐" 버그가 재현됨. 실제로
# pip install PyMuPDF 설치 후 재현 안 됨을 직접 확인함.
# [수정] Print/Save 경고 미리보기 창(신규 기능)이 PIL.ImageTk로 렌더 결과를
# Tkinter 창에 띄우는데, 이 서브모듈은 지금까지 코드 어디서도 import된 적이
# 없어서 위 PIL 하나만으로는 PyInstaller가 확실히 같이 안 묶을 수 있음(Tk
# 연동 C확장 _imagingtk 포함 여부가 불확실) - 위와 같은 이유로 명시 추가.
# [수정] 코드에서 `import fitz` -> `import pymupdf as fitz`로 바꿔서(fitz는
# deprecated 경고를 내는 구버전 별칭) hiddenimports도 실제 import되는 모듈
# 이름(pymupdf)으로 맞춘다 - 'fitz'로 남겨두면 PyInstaller가 더 이상
# 코드에 없는 이름을 찾다가 정작 실제로 필요한 pymupdf를 못 찾을 수 있음.
hiddenimports = ['PIL', 'PIL.ImageTk', 'pymupdf']
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
    # [추가 - 요청] "file size/실행속도 개선 방안?" - 실제 dist 폴더를 열어보니
    # pandas(11M)/numpy(numpy+numpy.libs 합쳐 17M)/lxml(4.2M)/pytz(1.8M)/
    # dateutil(156K) 등 CathPlot 코드 어디서도(import numpy/pandas/lxml 등)
    # 직접 쓰지 않는 패키지가 통째로 묶여 있었음(약 34M, dist 전체의 약 1/4) -
    # PyMuPDF(pymupdf)의 부수 기능(옵션 의존성)까지 PyInstaller 정적 분석이
    # 딸려서 끌고 온 것으로 보임. CathPlot이 실제로 쓰는 PyMuPDF 기능(PDF->
    # PNG/JPG 래스터화, PDF->SVG 변환, 텍스트 추출로 잘림 여부 확인)은 이
    # 패키지들이 전혀 필요 없는 순수 경로임을 직접 검증함(numpy/pandas/lxml/
    # pytz/dateutil을 강제로 import 불가능하게 만든 상태에서 single/multi-plot
    # PDF/PNG/EMF 생성 + PyMuPDF 텍스트 추출까지 전부 정상 동작, 이 5개 패키지
    # import 시도 자체가 한 번도 안 일어남을 확인). onedir 폴더 크기와 스캔할
    # 파일 수가 줄어드는 만큼 시작 속도에도 도움이 됨.
    excludes=['numpy', 'pandas', 'lxml', 'pytz', 'dateutil'],
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
