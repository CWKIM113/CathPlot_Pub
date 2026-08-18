# -*- coding: utf-8 -*-

from data_parser import CathenaDatParser  # 파서 모듈 임포트
from dataclasses import dataclass, field
import math
import os
import sys
import re
import shutil
import struct
import subprocess

# gnuplot.exe(콘솔 프로그램)를 실행할 때마다 배경에서 콘솔창이 잠깐 깜빡이는 것을
# 막기 위한 플래그 (Windows 전용 - 다른 OS에는 이 속성이 없으므로 getattr로 안전하게 처리)
_NO_CONSOLE_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# [수정] creationflags만으로는 일부 Windows 환경에서 콘솔 창 숨김이 불완전하게
# 동작하는 경우가 있다는 PyInstaller 이슈가 확인됨 - STARTUPINFO(SW_HIDE)를
# 같이 지정해서 더 확실하게 숨긴다. 아래 헬퍼로 두 값을 한 번에 반환.
def _no_console_kwargs():
    kwargs = {"creationflags": _NO_CONSOLE_FLAG}
    if hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs
import uuid
import time


def _force_focus_window_by_title(title, timeout_sec=2.0):
    """[추가 - 버그 수정] "Animation에서 space bar가 안 먹힘" - bind 자체는
    고쳤는데도 재현됨 - Windows가 새로 뜬 gnuplot 창에 입력 포커스를 자동으로
    주지 않아서(포커스 스틸링 방지), 사용자가 누른 space bar가 실제로는
    포커스를 그대로 갖고 있는 CathPlot(Tk) 창으로 들어가 아무 반응이 없던
    것으로 추정됨 - gnuplot 창을 제목으로 찾아 강제로 앞에 띄우고 포커스를
    준다. Windows 전용(ctypes.windll) - 다른 OS에서는 조용히 아무것도
    안 한다(이 프로그램 자체가 Windows 전용이라 실사용에 영향 없음)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
    except ImportError:
        return
    user32 = ctypes.windll.user32
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            try:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            return
        time.sleep(0.1)

# [수정] legend box 폭 계산에 쓰는 char_width_in 경험적 계수(아래 참고)는 원래
# "맑은 고딕" 기준으로 실측(PyMuPDF)해서 얻은 값이라, 지정한 폰트가 시스템에
# 없어서 다른 폰트(주로 Arial)로 대체되면 실제 렌더링 폭과 어긋날 수 있음
# ("폰트가 바뀌면 margin도 유동적이어야 하지 않나" 피드백) - tkinter로 실측해
# 보정하는 방법을 시도했었으나, gnuplot 스크립트 생성이 백그라운드 스레드에서
# 실행되는데 tkinter는 스레드 세이프하지 않아서 "gnuplot이 그래프를 그리지
# 못하고 바로 종료" 되는 심각한 회귀를 일으켰음(realtime 실측) - 그 방식은
# 폐기하고, 항상 1.0(보정 없음, 기존 방식 그대로)을 반환하는 안전한 자리
# 표시자로 되돌린다. 폰트별 실제 비율로 보정하려면 실측 없이도 안전한 방식
# (예: 알려진 폰트별 고정 비율표를 미리 만들어두는 등)으로 다시 검토해야 함.
def _font_width_ratio(font_name):
    return 1.0

# [추가] "font_pt/72 기준이 폰트를 바꾸면 왜곡될 수 있다 - 결과를 보고
# intelligent하게 할 수 없나" - 위 tkinter 실측 시도는 스레드 문제로
# 폐기됐지만, PIL(Pillow)의 ImageFont는 GUI가 아닌 순수 이미지 라이브러리라
# 백그라운드 스레드에서도 안전하게 쓸 수 있음(위 tkinter 실패 사례와는
# 다른 라이브러리). Legend Font 콤보박스에 있는 알려진 폰트들만 실제 .ttf
# 파일 경로를 미리 매핑해두고, PIL로 문자열의 실제 폭을 직접 측정해서
# legend box 폭 추정에 쓴다(문자별 가중치 추측 대신 실측) - 매핑에 없는
# 폰트거나 Pillow/폰트 파일이 없으면 기존 문자 가중치 방식으로 안전하게
# 대체(폴백)한다.
_FONT_FILE_MAP = {
    "malgun gothic": r"C:\Windows\Fonts\malgun.ttf",
    "arial": r"C:\Windows\Fonts\arial.ttf",
    "times new roman": r"C:\Windows\Fonts\times.ttf",
    "courier new": r"C:\Windows\Fonts\cour.ttf",
    "consolas": r"C:\Windows\Fonts\consola.ttf",
}
_font_measure_cache = {}

def _measure_text_width_in(text, font_name, font_pt):
    """text를 font_name(Legend Font 콤보 값) 폰트의 font_pt 크기로 실제
    렌더링했을 때의 폭을 inch로 반환. 측정 불가능하면 None(호출부가 기존
    문자 가중치 추정으로 대체해야 함)."""
    if not text:
        return 0.0
    path = _FONT_FILE_MAP.get((font_name or "").strip().lower())
    if not path or not os.path.exists(path):
        return None
    cache_key = (path, round(font_pt, 2))
    font_obj = _font_measure_cache.get(cache_key)
    if font_obj is None:
        try:
            from PIL import ImageFont
            # PIL의 truetype size는 72dpi 기준 픽셀이라, 그대로 pt로 써도
            # "1pt=1/72in" 정의와 일치해 inch 환산이 바로 됨.
            font_obj = ImageFont.truetype(path, max(int(round(font_pt)), 1))
        except Exception:
            return None
        _font_measure_cache[cache_key] = font_obj
    try:
        return font_obj.getlength(text) / 72.0
    except Exception:
        return None

_GNUPLOT_FALLBACK_PATHS = [
    r"C:\Program Files\gnuplot\bin\gnuplot.exe",
    r"C:\Program Files\gnuplot\bin\wgnuplot.exe",
    r"C:\Program Files (x86)\gnuplot\bin\gnuplot.exe",
    r"C:\Program Files (x86)\gnuplot\bin\wgnuplot.exe",
]
_gnuplot_exe_cache = None

def _resolve_gnuplot_exe():
    global _gnuplot_exe_cache
    if _gnuplot_exe_cache:
        return _gnuplot_exe_cache

    found = shutil.which("gnuplot") or shutil.which("wgnuplot")
    if not found:
        for candidate in _GNUPLOT_FALLBACK_PATHS:
            if os.path.exists(candidate):
                found = candidate
                break

    _gnuplot_exe_cache = found or "gnuplot"
    return _gnuplot_exe_cache

# pngcairo는 size에 단위(in/cm)를 주면 항상 72dpi로 래스터화한다(gnuplot
# 매뉴얼 명시) - PDF/SVG와 완전히 같은 비율로 그리기 위해 png도 "in" 단위로
# 물리 크기를 그대로 준 뒤(_get_terminal_cmd의 "png" 분기 참고), 그 결과로
# 나온 72dpi(저해상도) 이미지를 여기서 인쇄 품질(300dpi)로 업스케일한다.
_PNG_TARGET_DPI = 300.0
_PNG_NATIVE_DPI = 72.0

# [추가] "PNG/JPG를 PDF 기준으로 래스터화하면 어떨까(EMF/SVG는 계속 gnuplot이
# 직접)" 요청 - pngcairo/jpeg 터미널이 pdfcairo와 서로 다른 텍스트 엔진을 써서
# 포맷마다 legend/폰트 크기가 어긋나는 문제(오늘 하루 종일 겪음)의 근본 원인을
# 없애기 위해, PNG/JPG는 이미 검증된 PDF 결과를 PyMuPDF(fitz)로 그대로
# 래스터화해서 만든다(gnuplot의 pngcairo/jpeg 터미널을 더 안 부름). 덤으로
# JPG가 dashtype을 못 그리던 한계도 함께 해결됨(PDF는 dash를 제대로 그리므로
# 그걸 그대로 픽셀로 옮기면 dash도 같이 옮겨짐 - 직접 렌더링해서 확인).
# PyMuPDF가 없는 환경에서는 False를 반환해 호출자가 기존 gnuplot 자체
# 터미널 방식으로 그대로 대체(fallback)하게 한다(하위호환).
def _rasterize_pdf_to_image(pdf_path, out_path, fmt, dpi=_PNG_TARGET_DPI):
    try:
        import pymupdf as fitz  # [수정] "fitz API is deprecated" 경고 제거 - pymupdf가 정식 이름
    except ImportError:
        return False
    # [수정 - 버그] doc.close()가 성공 경로 끝에만 있어서, get_pixmap/save 등이
    # 예외를 던지면(디스크 꽉 참, 백신 잠금, 손상된 임시 PDF 등) 문서가 열린
    # 채로 남아 호출부의 임시 PDF 삭제(os.remove, 실패 시 조용히 무시)가
    # Windows에서 파일이 사용 중이라 계속 실패 - 임시 파일이 영구히 남는
    # 문제가 있었음. try/finally로 성공/실패 무관하게 항상 닫는다.
    doc = None
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pix.set_dpi(int(dpi), int(dpi))
        if (fmt or "").lower() in ("jpg", "jpeg"):
            pix.save(out_path, jpg_quality=90)
        else:
            pix.save(out_path)
        return True
    except Exception:
        return False
    finally:
        if doc is not None:
            doc.close()

# [추가 - 근본 원인 재해결] "SVG는 PDF→SVG 변환 수단이 이 환경에 없어서
# 그대로 gnuplot이 직접 그린다"고 알고 있었는데, PyMuPDF(fitz)에 이미
# Page.get_svg_image()가 있음을 재확인함 - PNG/JPG와 똑같은 이유(gnuplot의
# svg 터미널이 pdfcairo와 별개로 구현된 렌더러라 폰트 절대 크기/legend
# 폭/여백이 서로 어긋남 - 이번 세션에 EMF/SVG 폰트 비율, single-plot 극소형
# 여백 등을 하나씩 고쳤는데도 "text-anchor(오른쪽/가운데 정렬)를 렌더러가
# 지키지 않아 legend 텍스트가 box 밖으로 밀려나거나 tic 숫자가 frame과
# 겹치는" 문제가 실측(fitz get_text로 렌더링된 실제 글자 bbox 좌표 직접
# 확인)으로 새로 드러남 - "text-anchor에 의존하는 gnuplot svg 터미널을
# 패치"보다 "PNG/JPG처럼 이미 검증된 PDF를 그대로 SVG로 변환"이 더 근본적
# 이라고 판단해 SVG도 이 방식으로 전환한다.
# [주의] get_svg_image(text_as_path=0)(진짜 <text>, 검색/선택 가능)을 먼저
# 시도했으나, 그 결과물을 fitz 자신의 SVG 임포터로 다시 열어 렌더링하면
# 회전된 텍스트(Y1/Y2 title)가 깨져서 나옴(fitz의 SVG import가 자신이 만든
# tspan-x-array 방식을 제대로 못 읽는 비대칭 - 실측 확인) - 기본값인
# text_as_path=1(글자를 도형 윤곽선으로 변환)로 확정한다. 텍스트 검색/선택은
# 안 되지만(EMF/PNG는 여전히 필요하면 사용), 어떤 렌더러로 열어도 PDF와
# 완전히 동일한 절대 위치/크기로 나온다는 게 실측으로 확인됨(fitz로 재렌더링
# 결과 legend 겹침/tic 겹침/제목 중심 이탈 등 오늘 발견된 문제 전부 재현 안 됨).
def _convert_pdf_to_svg(pdf_path, out_path):
    try:
        import pymupdf as fitz  # [수정] "fitz API is deprecated" 경고 제거 - pymupdf가 정식 이름
    except ImportError:
        return False
    # [수정 - 버그] _rasterize_pdf_to_image와 같은 이유 - doc.close()를
    # try/finally로 옮겨 예외 발생 시에도 항상 닫히게 한다.
    doc = None
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        svg_text = page.get_svg_image(text_as_path=1)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(svg_text)
        return True
    except Exception:
        return False
    finally:
        if doc is not None:
            doc.close()


def _upscale_png_dpi(png_path):
    """72dpi로 그려진 png를 _PNG_TARGET_DPI/_PNG_NATIVE_DPI배 확대해서 저장한다.
    Pillow가 없으면 조용히 건너뛴다(비율은 이미 정확하고 해상도만 낮게 남음)."""
    try:
        from PIL import Image
    except ImportError:
        return
    try:
        scale = _PNG_TARGET_DPI / _PNG_NATIVE_DPI
        with Image.open(png_path) as im:
            new_size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
            # [수정 - 버그] "PNG 해상도가 나쁘다(300dpi 아님)" - 픽셀 수는
            # 300/72배로 늘렸지만 dpi= 없이 save()하면 PNG의 pHYs 메타데이터에
            # 해상도가 안 남아서, Word 등에서 불러올 때 기본값(예: 96dpi)으로
            # 간주해 실제보다 훨씬 크게 배치되거나 "해상도가 낮다"고 보임 -
            # 실제 목표 dpi(300,300)를 메타데이터에 명시적으로 기록한다.
            im.resize(new_size, Image.LANCZOS).save(png_path, dpi=(_PNG_TARGET_DPI, _PNG_TARGET_DPI))
    except Exception:
        pass  # 업스케일 실패해도 원본(저해상도지만 비율은 정확한) 파일은 이미 저장돼 있음

DEFAULT_COLORS = ["black", "red", "blue", "green", "magenta", "cyan", "orange", "brown", "purple", "gray"]
DEFAULT_LINESTYLES = ["solid", "dash", "dot", "dashdot", "shortdash", "dashdotdot"]
DASH_PATTERNS = {
    # [수정 - 심각한 버그] "red curve가 Dash 지정해도 실선으로 보임" - 데이터가
    # 빠르게 진동해서 그런 걸로 예전에 추정했었는데, 그건 틀렸음. 실측 확인:
    # gnuplot(6.0.3)이 "dashtype (6,3)"처럼 콤마 뒤 공백이 없는 튜플을 stdin/
    # 파일 어느 쪽으로 줘도 에러 없이 그냥 조용히 선 자체를 안 그려버림(빈
    # plot이 됨) - 콤마 뒤 공백을 넣은 "dashtype (6, 3)"는 정상 동작함을
    # 직접 렌더링 비교로 확인함. 이 파싱 특이사항 때문에 그동안 Dash/Dot 등
    # 모든 점선 스타일이 항상 조용히 실패해서 실선처럼 보였던 것.
    # [수정 - 버그] "Word에서 보면 dash가 short-dash나 dot처럼 보임" - 곡선이
    # 가파르게 오르내리는 구간(CATHENA 데이터에 흔함)에서는 dash 세그먼트가
    # 진행 방향(경로 길이) 기준이라 화면(수직) 투영 길이가 짧아져, 6pt
    # 세그먼트가 거의 정사각형(점)처럼 보였음 - 직접 렌더링 비교로 14pt까지
    # 늘리면 가파른 구간에서도 확실히 "선분"으로 보임을 확인.
    # [수정] "Dash 사이 공간(간격)을 반이나 2/3로 줄여줘요" - 세그먼트(14)는
    # 그대로 두고 간격만 7 -> 3.5(절반)로 축소해 더 촘촘하게 보이게 함.
    "dash": "14, 3.5",
    "dot": "1, 2",
    "dashdot": "8, 3, 1, 3",       # dash를 길게(6->8), dot과의 틈새도 넓힘(2->3)
    "shortdash": "3, 2",
    "dashdotdot": "8, 3, 1, 3, 1, 3",  # 위와 동일하게 확대
}

# [수정 - 버그] "PNG는 dot가 실선으로 보임(간격이 너무 작아 보임), 점선 dash
# 길이를 1.5~2배로(screen/emf는 세그먼트가 2개인데 PNG는 4개 - 길이가 절반)" -
# 실측(동일 dashtype을 pdfcairo/emf 양쪽에 그려서 300dpi로 캡처해 비교)으로
# 확인: pdfcairo(PDF/PNG/JPG가 이제 다 이 경로) 쪽 dot("1, 2")은 세그먼트가
# 워낙 짧아(1pt 미만) anti-aliasing에 묻혀 거의 실선처럼 보이는데, emf(GDI
# 네이티브 렌더러)는 같은 값이어도 또렷하게 점선으로 보임 - cairo 래스터화
# 단계에서 작은 dash 세그먼트가 뭉개지는 것으로 보임. cairo 계열(pdf/png/jpg)
# 에만 dashtype 숫자를 키워 세그먼트를 더 굵게(살아남게) 만든다.
_CAIRO_DASH_BOOST = 1.75  # 요청한 "1.5~2배" 범위의 중간값
# [수정 - 반영 안 됐던 것 재확인] "PNG legend 내 점선이 너무 짧다, 늘려달라" -
# 처음엔 "dash"(14,3.5)는 세그먼트가 이미 길어서 괜찮을 거라 보고 최소
# 세그먼트<2pt인 패턴("dot"/"dashdot"/"dashdotdot")에만 적용했는데, 실제
# 화면(legend의 "dash" 스타일)으로 재확인하니 그것도 짧다는 피드백 - 문턱
# 없이 cairo 계열 전체 dashtype에 그대로 적용한다.
def _dash_pattern_for_fmt(linestyle, fmt):
    base = DASH_PATTERNS.get(linestyle)
    if base is None:
        return None
    if (fmt or "").lower() not in ("pdf", "png", "jpg", "jpeg"):
        return base
    try:
        nums = [float(v.strip()) * _CAIRO_DASH_BOOST for v in base.split(",")]
    except ValueError:
        return base
    return ", ".join(f"{v:.3g}" for v in nums)

# Legend 샘플선 위에 마커를 표시할 때 쓰는 유니코드 기호 (pointtype 번호 -> 기호)
MARKER_SYMBOL_MAP = {
    6: "○", 7: "●",    # Circle (속빈/채운)
    4: "□", 5: "■",    # Square
    8: "△", 9: "▲",    # Triangle (위)
    10: "▽", 11: "▼",  # Tri-Down (아래세모)
    12: "◇", 13: "◆",  # Diamond
    1: "+",            # Cross
    3: "★",            # Star
}
# Legend 샘플선 위 마커 기호의 수직 보정치(ROW_H 배수, +면 위로/-면 아래로).
# 세모류(△▲▽▼)는 잉크 무게중심이 위/아래로 치우쳐 있어 "center" 정렬만으로는
# 샘플선 대비 어긋나 보임 - 실측(마커 전체 종류를 그려서 비교)으로 보정.
MARKER_Y_OFFSET = {8: 0.08, 9: 0.08, 10: 0.10, 11: 0.18}
# 화면(Interactive, windows 터미널)은 pngcairo와 텍스트 기준선 방향이 반대로
# 확인됨(위쪽 세모가 화면에서는 아래로, 아래쪽 세모는 위로 나타남) - 부호를
# 반대로 둔 화면 전용 보정치. 나머지 기호는 _screen_marker_bias(공통) 하나로 처리.
MARKER_Y_OFFSET_SCREEN = {8: 0.05, 9: 0.00, 10: -0.15, 11: -0.10}  # 위쪽 세모(8,9) 추가로 더 내림(동일 폭만큼 재조정)
# 위와 같은 이유로, 기호별 em-box 잉크 크기 차이를 보정하는 폰트 크기 배율
# (1.0=그대로). "+"(pointtype 1)는 원/사각형/별표보다 훨씬 얇고 작게 그려져서
# 눈에 띄게 작아 보인다는 피드백으로 확대.
MARKER_SIZE_SCALE = {1: 1.8}

#----------------------------------------------------------
# Interactive
#----------------------------------------------------------
SCREEN_FONT_SCALE  = 1.00
SCREEN_LINE_SCALE  = 1.00
SCREEN_BORDER_SCALE = 1.00
SCREEN_TIC_MAJOR_SCALE = 2.0   # 화면 tic 길이 - 저장/print(PRINT_TIC_*)에는 영향 없음
SCREEN_TIC_MINOR_SCALE = 1.0

#----------------------------------------------------------
# Print / Save Output Scale
#----------------------------------------------------------
PRINT_FONT_SCALE = 1.60     # [수정 - 버그] "PDF 그림에서 font size가 plot 대비 너무 작음(폰트
# 크기 입력으로 해결될 사항 아님), Legend box도 너무 작음 - 폰트·legend 모두
# 2배로" - PDF가 PNG/JPG의 기준(기준 포맷을 PyMuPDF로 래스터화)이 되면서
# 이 문제가 셋 다에 그대로 나타났음. 원인은 여기 이 배율 자체 - 예전에
# "screen보다 폰트가 크게 보인다"는 반대 피드백으로 1.60 → 1.00 → 0.60(잘림
# 회귀로 되돌림) → 0.80까지 계속 줄여왔던 값인데, 결과적으로 A4보다 큰
# 10x8in 캔버스에 7~11pt 폰트가 남아 너무 작아 보이게 됐음 - 원래
# 시작값이었던 1.60으로 되돌린다(정확히 요청하신 "2배"). legend box/margin은
# 모두 font_pt에 비례해 계산되므로 이 배율 하나로 같이 커짐.
PRINT_LINE_SCALE = 1.00     # 기존 1.70
PRINT_BORDER_SCALE = 1.00   # 기존 1.50

# [추가 - 근본 원인 발견, 이후 되돌림, 다시 방향 전환] gnuplot의 pdfcairo
# 터미널(png/jpg도 PDF를 거쳐 만들어지므로 동일)은 "font 'Name,SIZE'"로
# 지정한 값과 무관하게 실제 PDF에 기록되는 폰트 크기가 항상 정확히 2/3로
# 줄어드는 자체 특성이 있음(우리 코드와 무관한 최소 재현 스크립트로 확인 -
# 지정 36 -> 실제 24 등 예외 없이 정확한 2/3. PyMuPDF span.size로 직접
# 측정 - 이 관찰 자체는 지금도 사실). 한때 이 축소를 "EMF/SVG와 절대
# 크기를 맞춘다"는 목표로 상쇄(1.5배)했다가, legend box가 axis의 55%까지
# 커지는 부작용으로 되돌린 적 있음(CAIRO_FONT_RENDER_FIX=1.0). 그런데 그
# 되돌림 이후 box_chars/margin 등 전체 계산이 "PDF가 2/3로 작게 나오는
# 상태"를 기준으로 다시 맞춰졌고, 이 상태의 PDF 결과물이 지금은 "정상
# 기준"으로 확정됨 - 사용자 확인: "EMF가 PDF 대비 상대적으로 크게 보이니
# EMF/SVG를 PDF 수준으로 조정하라"(PDF를 키우는 방향이 아니라 EMF/SVG를
# 줄이는 방향). PDF는 그대로 두고(CAIRO_FONT_RENDER_FIX=1.0 유지), EMF와
# SVG의 절대 렌더 크기를 PDF에 맞춰 줄인다(아래 EMF_FONT_RENDER_FIX/
# SVG_FONT_RENDER_FIX 참고).
CAIRO_FONT_RENDER_FIX = 1.0
# [수정 - 방향 전환, 범위 한정] "EMF가 PDF보다 상대적으로 크게 나온다"
# 지적으로 실측 재확인(EMF 파일의 EMR_EXTCREATEFONTINDIRECTW.lfHeight를
# 직접 읽어 pt로 환산 후 PyMuPDF로 잰 PDF 실제 렌더 크기와 비교) -
# title/xlabel/ylabel/y2label/tic/legend 전부 예외 없이 정확히 1.5배(EMF가
# 큼, 10x8/20x16/5x4cm 세 크기 모두 동일 비율 재확인, single-plot 기준).
# 이전에 "EMF가 PDF보다 작게 나온다"고 실측했던 것(0.745~0.847배)은 그
# CAIRO_FONT_RENDER_FIX=1.5가 적용 중이던 상태(PDF가 그만큼 커져 있던
# 상태)와 비교한 값이라, 지금(PDF 보정 없음, 원래 작은 상태)과는 비교
# 기준 자체가 다름 - 지금 기준으로 EMF를 1/1.5=0.667배로 줄여 PDF와 절대
# 크기를 맞춘다.
# [범위 한정 - 요청] "지금은 single-plot부터 맞추는 작업" - EMF_FONT_
# RENDER_FIX는 M-P(create_multiplot_script의 font_panel_scale)에도 같이
# 쓰이는 공용 상수라, 이 값 자체를 바꾸면 M-P의 이미 검증된 margin-need
# 공식들(_need_left_in 등, 전부 이 상수가 반영된 font_panel_scale 기준으로
# 튜닝됨)이 갑자기 다른 폰트 크기를 전제로 계산하게 돼 4/p·6/p Manual
# 2줄 조합에서 텍스트 소실 회귀가 실측 확인됨. M-P는 손대지 않고 이후
# 별도로 재보정하기로 하고, single-plot 전용 상수(SP_ 접두사)를 새로
# 만들어 single-plot 경로에서만 쓴다 - EMF_FONT_RENDER_FIX/SVG_FONT_
# RENDER_FIX 자체는 M-P 호환을 위해 1.0(미적용)으로 유지.
EMF_FONT_RENDER_FIX = 1.0
SP_EMF_FONT_RENDER_FIX = 1.0 / 1.5
# [추가 - 신규] SVG도 PDF 대비 실측 1.125배 크게 나옴(같은 방법 - SVG는
# lfHeight 대신 XML의 font-size 속성을 직접 읽음, 세 크기 모두 동일 비율,
# single-plot 기준). EMF와 같은 이유로 PDF 수준에 맞춰 1/1.125=0.889배로
# 줄인다 - 지금까지는 SVG 전용 보정 자체가 없었음(EMF만 있었음). single-plot
# 전용 상수로만 도입(M-P는 아직 손대지 않음) - _compute_f_scale과
# _build_plot_commands의 단일 plot 전용(not is_multiplot) 분기 2곳에 적용.
SP_SVG_FONT_RENDER_FIX = 1.0 / 1.125
# [추가 - 후속 작업] "M-P의 EMF/SVG 폰트-비율도 같은 방식으로 재보정" - single-
# plot과 같은 실측(1/p: EMF/PDF=1.497~1.500, SVG/PDF=1.125 균일 - single-plot과
# 정확히 동일한 드라이버 자체 비율)을 M-P에도 확인함. 단 4/p·6/p 등 칸이 작은
# Auto 레이아웃에서는 이미 존재하는 클리핑 방지용 축소 로직(font_panel_scale의
# floor/shrink, fmt='emf'/'svg' 조건부)이 일부 겹쳐 있어 실측 비율이 더 낮음
# (1.217~1.332) - font_panel_scale 자체(margin-need 계산에도 쓰이는 공용 값,
# EMF_FONT_RENDER_FIX와 같은 이유로 손대면 4/p·6/p Manual 2줄 회귀 재현 위험)는
# 그대로 두고, 실제 gnuplot에 보내는 최종 pt 숫자(title/xlabel/ylabel/y2label/
# tic/legend)에만 이 비율을 곱해 "항상 그대로거나 더 작게"만 만든다(절대 커지지
# 않음 - margin은 이 축소를 모르는 채 기존(더 큰 값 기준)대로 남아 여유가 늘어나는
# 방향이라 텍스트 소실 회귀 위험이 없음). 1/p는 정확히 일치, 4/p·6/p는 기존 축소가
# 이미 일부 반영돼 있어 PDF보다 살짝 작아지는 정도로 남음(더 크게 보이는 원래
# 문제의 반대 방향이라 안전).
MP_EMF_FONT_RENDER_FIX = 1.0 / 1.5
MP_SVG_FONT_RENDER_FIX = 1.0 / 1.125
PRINT_TIC_MAJOR_SCALE = 1.0
PRINT_TIC_MINOR_SCALE = 0.5

#----------------------------------------------------------
# [수정 - 죽은 코드 제거] PAGE_MARGIN_LEFT/RIGHT/TOP/BOTTOM_CM, SAVE_PAGE_
# MARGIN_CM(모듈 레벨) - 예전 "Print는 물리 프린터용 큰 비대칭 여백(좌2·
# 우1·상3·하2cm), Save는 작은 여백"이라는 설계의 잔재였는데, "Print/Save가
# 결과 다르면 혼란스럽다"는 요청으로 이미 통일돼서(create_multiplot_script
# 안의 로컬 SAVE_PAGE_MARGIN_IN = 0.3/2.54를 Print/Save 둘 다 씀) 이
# 5개 모듈 상수는 grep 결과 파일 전체(gnu_generator.py, cathplot_gui.py)
# 어디에서도 실제로 참조되지 않는 죽은 값이었음 - 남겨두면 "Print가 아직도
# 이 큰 여백을 쓴다"고 오해하기 쉬워 제거함.
#----------------------------------------------------------

# gnuplot의 emf 터미널이 실제로 EMF 헤더(rclFrame)에 기록하는 기준 해상도.
# gdi32.GetEnhMetaFileHeader로 알려진 픽셀 크기(예: 1000x800)의 EMF를 만들어
# rclFrame(0.01mm 단위)을 역산해서 얻은 값(96.32px/in) - 표준 96dpi와 거의
# 같지만 정확히 96은 아님. 인쇄(_print_emf_and_cleanup)가 이 rclFrame을 그대로
# 물리 크기 기준으로 쓰므로, emf의 cm/in->px 환산은 반드시 이 값을 써야
# 요청한 물리 크기(cm/in) 그대로 인쇄/저장된다.
EMF_PX_PER_IN = 96.32

MARGIN_LEFT_IN = 0.9
MARGIN_RIGHT_IN = 0.3         
MARGIN_RIGHT_LEGEND_IN = 1.8  
MARGIN_RIGHT_Y2_IN = 0.6
MARGIN_RIGHT_Y2_NO_LABEL_IN = 0.2  # y2 축은 있지만 y2label 문자열이 없을 때(tic 숫자만)
MARGIN_TOP_IN = 0.6           
MARGIN_TOP_NO_TITLE_IN = 0.08 
MARGIN_TOP_PER_EXTRA_LINE_IN = 0.35  
MARGIN_BOTTOM_IN = 0.7        
CELL_SPACING_IN = 0.03  # [수정 - 재축소] 이전엔 0.05도 Manual EMF 4/p·6/p Y1·Y2
# 둘 다 2줄인 극단 조합에서 텍스트 소실이 나서 0.10으로 되돌렸었는데, 그
# 사이 margin-need 안전 배율 재조정(EMF 1.15->1.4 등)이 들어가 지금은
# 0.0까지 줄여도(재검증) 그 극단 조합(6x5cm 포함)에서 텍스트 소실이 없음 -
# "칸 사이 간격 최소화" 요청으로 0.03(거의 0에 가깝지만 칸 사이 시각적
# 구분이 아예 없어지진 않는 값)으로 확정. 줄어든 만큼은 기존 axis-확대
# 재사용 장치(_col_gap_l/r, _row_gap_t/b 기반 grow)가 그대로 axis 크기로
# 돌려줌.

@dataclass
class CurveDefinition:
    dat_file: str
    output_no: int
    title: str    # Y축 컬럼 번호 (예: y1)
    axis: str = "y1"
    x_shift: float = 0.0
    color: str | None = None
    linestyle: str | None = None
    linewidth: float = 1.5
    x_output_no: int | None = None  # X축 컬럼 번호 (None인 경우 플롯 전역 x_output_no 참조)
    legend_group: int = 1  # 이 curve가 Legend1(1)/Legend2(2) 중 어디에 나타날지
    in_legend1: bool = True  # Legend1(box1)에 이 curve를 넣을지 (기본 포함)
    marker_shape: int | None = None  # gnuplot pointtype 번호 (None = 마커 없음)
    marker_size: float = 1.0         # gnuplot pointsize
    marker_max_count: int | None = None  # None = Auto(20~30개 근처로 자동 계산)

    def __post_init__(self):
        # [위치] 데이터클래스 속성 정의 바로 아래, 일반 메서드들보다 위에 위치합니다.
        if self.x_output_no is not None and self.x_output_no == self.output_no:
            raise ValueError(f"동일한 변수 번호({self.output_no})를 X축과 Y축으로 동시에 지정할 수 없습니다.")

@dataclass
class PlotDefinition:
    title: str = "CathPlot"
    xlabel: str = "Time (sec)"
    ylabel: str = ""
    y2label: str = ""

    annotations: list = field(default_factory=list)
    arrows: list = field(default_factory=list)
    circles: list = field(default_factory=list)  # {"x","y","rx","ry","coord_mode"} - 원/타원 주석
    curves: list = field(default_factory=list)
    output_format: str = "Interactive"
    xauto: bool = True
    yauto: bool = True
    y2auto: bool = True

    xmin: str = ""
    xmax: str = ""
    ymin: str = ""
    ymax: str = ""
    y2min: str = ""
    y2max: str = ""

    plot_id: int = 0
    xtics: str = ""
    ytics: str = ""
    y2tics: str = ""

    mxtics: str = ""
    mytics: str = ""
    my2tics: str = ""
    major_grid: bool = True
    minor_grid: bool = False

    legend_outside_margin: bool = True
    legend_on: bool = True
    legend_box: bool = True
    legend_pos: str = "right top"
    # [추가] "Auto"(기존 방식: pos의 x값이 50% 이상이면 우측 정렬, 아니면 좌측
    # 정렬)/"Left"/"Right" - 자동 판정과 다르게 명시적으로 정렬을 고르고 싶다는
    # 요청으로 추가.
    legend_align: str = "Auto"
    legend_thick: str = "1.5"  # legend box 테두리 두께
    legend_font: str = "Malgun Gothic"  # Legend 전용 폰트 (Comment도 같이 씀)
    legend_size: str = "9"  # Legend 전용 크기 (Comment도 같이 씀)
    # [추가] "자동 추정이 안 맞는 경우만 사용자 입력(axis 대비 %)으로" - 비어
    # 있으면(기본) 기존 폰트 기반 자동 추정, 값이 있으면 그 크기(axis width/
    # height 대비 %)로 고정. Print/Save 전용(포맷별 렌더링 차이로 자동
    # 추정이 어긋나는 예외 상황 대응용).
    legend_box_width_pct: str = ""
    legend_box_height_pct: str = ""

    legend2_on: bool = False
    legend2_box: bool = True
    legend2_pos: str = "right bottom"
    legend2_align: str = "Auto"  # Legend1과 동일(legend_align 참고)
    legend2_thick: str = "1.5"
    legend2_box_width_pct: str = ""   # Legend1과 동일(legend_box_width_pct 참고)
    legend2_box_height_pct: str = ""

    title_font: str = "Malgun Gothic"
    title_size: str = "14"
    xlabel_font: str = "Malgun Gothic"
    xlabel_size: str = "11"
    ylabel_font: str = "Malgun Gothic"
    ylabel_size: str = "11"
    y2label_font: str = "Malgun Gothic"
    y2label_size: str = "11"

    is_print_mode: bool = False

    frame_auto: bool = True
    frame_width: str = ""
    frame_height: str = ""
    frame_unit: str = "in"

    x_output_no: int = 0  # 플롯 전역 기본 X축 컬럼 (Var no=0 포함 허용)
    extra_gnuplot: str = ""  # Advanced: 화면의 Raw gnuplot 입력창 내용 (plot 직전에 그대로 삽입)
    xlog: bool = False
    y1log: bool = False
    y2log: bool = False
    xfmt: str = "Normal"   # Normal/Scientific/Power10 - tic 숫자 표시 형식
    y1fmt: str = "Normal"
    y2fmt: str = "Normal"

class GnuplotGenerator:

    def __init__(self, plot_dir=None):
        self.plot_dir = plot_dir
        self.use_default_colors = True
        self.use_default_styles = True
        self.custom_export_path = None
        self.last_process = None
        # [추가] Interactive 애니메이션 실행 중 CathPlot의 Pause/Speed/Exit
        # 버튼이 실행 중인 gnuplot에 값을 전달하는 파일 경로/초기 프레임
        # 간격(초) - create_animation_script가 채우고, GUI가 읽어서 컨트롤
        # 패널을 만든다(gnuplot 키보드 bind에 의존하지 않는 방식).
        self.last_anim_ctrl_path = None
        self.last_anim_frame_pause = None
        self.last_size_warning = None  # 종이 여백 부족으로 plot 크기를 자동 축소했을 때 메시지가 여기 담김
        self.warnings = []  # create_script/create_multiplot_script 호출 중 발견된 경고 메시지 목록(legend 폰트 과대 등)

    @staticmethod
    def _format_number(value):
        return format(value, ".12g")

    def _tic_label_extra_chars(self, min_val, max_val, step_val, baseline=2):
        """[추가] "tic 숫자에 소수점/음수가 있으면 여백도 넓어야" - min/max/
        tic-step으로부터 실제 찍힐 tic 숫자들의 최대 글자수를 추정해서,
        기준(정수 2자리, 예: "10")보다 몇 글자 더 넓은지 반환한다. step을
        모르면(수동 tic이 "auto"인 경우 등) min/max 두 값만으로 근사한다."""
        try:
            vmin = float(min_val)
            vmax = float(max_val)
        except (TypeError, ValueError):
            return 0
        candidates = [vmin, vmax]
        try:
            step = float(step_val) if step_val not in (None, "") else None
        except (TypeError, ValueError):
            step = None
        if step and step > 0:
            n0 = math.ceil(vmin / step - 1e-9)
            n1 = math.floor(vmax / step + 1e-9)
            if 0 <= (n1 - n0) <= 200:
                candidates = [n * step for n in range(int(n0), int(n1) + 1)] or candidates
        try:
            max_len = max(len(self._format_number(v)) for v in candidates)
        except (TypeError, ValueError):
            return 0
        return max(0, max_len - baseline)

    def _safe_manual_range(self, min_str, max_str, is_log):
        """사용자가 직접 입력한(또는 이전에 자동 계산되어 남아있던) min/max
        문자열을 그대로 쓰되, log 스케일이 켜진 상태에서 min이 0 이하로
        파싱되면 안전한 양수로 보정한다 - gnuplot이 log축에 0/음수 범위를
        만나면 아무것도 못 그리고 에러로 죽는 것을 방지하기 위함."""
        min_str = (min_str or "").strip()
        max_str = (max_str or "").strip()
        if is_log and min_str:
            try:
                min_val = float(min_str)
                if min_val <= 0:
                    try:
                        max_val = float(max_str) if max_str else 1.0
                    except ValueError:
                        max_val = 1.0
                    min_str = str(max(max_val * 0.001, 1e-6))
            except ValueError:
                pass  # 숫자로 파싱 안 되면(예: 비워둠) 그대로 둠 - gnuplot이 알아서 처리
        return min_str, max_str

    def _select_marker_points(self, curve, x_col_idx, y_col_idx, target_count, is_log_x, shared_x_range=None):
        """curve의 실제 (x,y) 데이터를 읽어서 마커로 찍을 점들을 고른다.
        - 데이터가 target_count보다 적으면 전부 반환
        - 많으면, X축이 log면 log(x) 공간에서, 아니면 x 값 그대로에서
          등간격 목표값을 정하고 그 각각에 가장 가까운 실제 데이터 포인트를
          선택한다 (log축에서도 시각적으로 고르게 보이도록)
        - shared_x_range(전체 plot의 공통 X범위)가 주어지면, 목표 지점을 이
          curve 자신의 데이터 범위가 아니라 그 공통 범위를 기준으로 잡는다 -
          curve마다 x범위가 다를 때(예: var1은 0~1000, var2는 0~2000) 같은
          목표 개수를 쓰면 좁은 범위의 curve가 상대적으로 촘촘해지는 문제가
          있었음. 공통 범위 기준으로 목표를 잡고 이 curve의 실제 범위 안에
          드는 것만 남기면, 걸치는 구간만큼만 비례해서 마커를 받게 된다.
        x_shift는 여기서 이미 반영해서 반환한다(실제 plot에 그려지는 좌표 기준)."""
        try:
            parser = CathenaDatParser()
            dat_info = parser.parse(curve.dat_file)
            with open(curve.dat_file, "r", encoding="utf-8", errors="ignore") as f:
                file_lines = f.readlines()
        except Exception:
            return []

        pts = []
        max_col = max(x_col_idx, y_col_idx)
        for row in file_lines[dat_info.data_start_line:]:
            text = row.strip()
            if not text:
                continue
            fields = re.split(r'[,\s]+', text)
            if len(fields) <= max_col:
                continue
            try:
                x_val = float(fields[x_col_idx].replace("D", "E").replace("d", "e").replace(",", "")) + curve.x_shift
                y_val = float(fields[y_col_idx].replace("D", "E").replace("d", "e").replace(",", ""))
            except ValueError:
                continue
            if math.isfinite(x_val) and math.isfinite(y_val):
                pts.append((x_val, y_val))

        if not pts:
            return []

        x_min = min(p[0] for p in pts)
        x_max = max(p[0] for p in pts)

        if len(pts) <= target_count and not shared_x_range:
            return pts

        ref_min, ref_max = shared_x_range if shared_x_range else (x_min, x_max)
        # [수정 - 버그] "Marker Max Count를 1로 지정하면 ZeroDivisionError" -
        # 아래 log/선형 분기 모두 (target_count - 1)로 나누는데, target_count=1
        # (사용자가 직접 1을 입력한 경우 - GUI 쪽에 최소값 검증이 없음)이면
        # 0으로 나누기가 됨. 목표점이 1개뿐이면 등간격 계산 자체가 의미
        # 없으므로(간격을 나눌 구간이 없음) 중간점 하나만 반환한다.
        if target_count <= 1:
            all_targets = [(ref_min + ref_max) / 2.0]
        elif is_log_x and ref_max > 0:
            if ref_min <= 0:
                # [수정] 로그축인데 구간이 0부터 시작하면(흔한 케이스: Time=0)
                # 무조건 선형으로 폴백하고 있었음 - 그러면 로그축으로 볼 때
                # 마커가 큰 값 쪽으로 몰려 보이는 문제가 있었음. 이 curve의
                # 실제 데이터 중 가장 작은 양수값으로 대신해서 로그 간격을 유지한다
                positive_xs = [px for px, _ in pts if px > 0]
                ref_min = min(positive_xs) if positive_xs else ref_max * 0.001
            lo, hi = math.log10(ref_min), math.log10(ref_max)
            all_targets = [10 ** (lo + (hi - lo) * i / (target_count - 1)) for i in range(target_count)]
        elif ref_max != ref_min:
            all_targets = [ref_min + (ref_max - ref_min) * i / (target_count - 1) for i in range(target_count)]
        else:
            all_targets = [ref_min] * target_count

        # 공통 범위 기준 목표 중, 이 curve의 실제 데이터 범위 안에 드는 것만 사용
        targets = [t for t in all_targets if x_min <= t <= x_max] if shared_x_range else all_targets
        if not targets:
            targets = [x_min]
        if len(pts) <= len(targets):
            return pts

        selected = []
        used_idx = set()
        for t in targets:
            best_i, best_d = None, None
            for i, (px, _) in enumerate(pts):
                d = abs(math.log10(px) - math.log10(t)) if (is_log_x and px > 0 and t > 0) else abs(px - t)
                if best_d is None or d < best_d:
                    best_i, best_d = i, d
            if best_i is not None and best_i not in used_idx:
                used_idx.add(best_i)
                selected.append(pts[best_i])
        selected.sort(key=lambda p: p[0])
        return selected

    def _nice_axis_range(self, plotdef, axis, is_log=False):
        parser = CathenaDatParser()
        
        # 변수 초기화
        x_min = None
        x_max = None
        
        # axis가 'x'일 때만 사용자의 X축 제한 설정을 적용합니다.
        if axis == "x" and not plotdef.xauto:
            try: x_min = float(plotdef.xmin) if (plotdef.xmin or "").strip() else None
            except (AttributeError, ValueError): x_min = None
            try: x_max = float(plotdef.xmax) if (plotdef.xmax or "").strip() else None
            except (AttributeError, ValueError): x_max = None

        values = []
        default_x_col = getattr(plotdef, "x_output_no", 0)

        for curve in plotdef.curves:
            # [핵심 수정] 곡선의 축 설정을 가져오되, 지정되지 않았으면 기본값으로 'y1'을 부여합니다.
            curve_axis = getattr(curve, "axis", "y1")
            x_col_idx = curve.x_output_no if getattr(curve, "x_output_no", None) is not None else default_x_col

            if axis == "x":
                # [수정] X축 계산은 curve.axis(y1/y2 소속)와 무관하게 모든 curve의
                # X 컬럼 값을 모아야 한다 - curve.axis는 "x"가 될 수 없어서(항상
                # y1/y2), 예전처럼 curve_axis != axis로 걸러내면 전부 건너뛰어져
                # X축 계산이 항상 실패(None)했었다.
                column = x_col_idx
            else:
                # 현재 함수가 계산 중인 대상 축(y1/y2)과 곡선의 축이 다르면 건너뜁니다.
                if curve_axis != axis:
                    continue
                column = curve.output_no

            try:
                dat_info = parser.parse(curve.dat_file)
            except Exception:
                continue

            try:
                with open(curve.dat_file, "r", encoding="utf-8", errors="ignore") as data:
                    file_lines = data.readlines()
            except OSError:
                continue

            # 헤더/데이터 경계는 이미 파서가 판단해둔 data_start_line을 그대로 사용
            # ("---","===","OUTPUT" 등을 다시 문자열로 추측하는 중복 로직을 두지 않음)
            for row in file_lines[dat_info.data_start_line:]:
                text = row.strip()
                if not text:
                    continue

                fields = re.split(r'[,\s]+', text)
                if not fields:
                    continue

                max_col = max(column, x_col_idx)
                if len(fields) <= max_col:
                    continue

                # X축 값 검증
                try:
                    x_val_check = float(fields[x_col_idx].replace("D", "E").replace("d", "e").replace(",", ""))
                except ValueError:
                    continue

                # x_min, x_max 필터링은 오직 axis == "x" 이고 제한이 유효할 때만 작동
                if x_min is not None or x_max is not None:
                    try:
                        x_val = x_val_check + curve.x_shift
                    except (ValueError, IndexError):
                        x_val = None
                    if x_val is not None:
                        if x_min is not None and x_val < x_min:
                            continue
                        if x_max is not None and x_val > x_max:
                            continue

                try:
                    val_str = fields[column].replace("D", "E").replace("d", "e").replace(",", "")
                    value = float(val_str)
                except (ValueError, IndexError):
                    continue

                if math.isfinite(value):
                    values.append(value)

        if not values:
            return None

        data_min, data_max = min(values), max(values)
        span = data_max - data_min
        if span == 0:
            if is_log:
                lo_val = data_min if data_min > 0 else 0.001
                axis_min = 10 ** math.floor(math.log10(lo_val))
                axis_max = 10 ** math.ceil(math.log10(lo_val * 10))
                if axis_min >= axis_max:
                    axis_max = axis_min * 10
                return axis_min, axis_max, (axis_max - axis_min) / 4.0
            span = max(abs(data_min) * 0.1, 1.0)
            data_min -= span / 2
            data_max += span / 2
            return data_min, data_max, span / 4.0

        # "보기 좋은" 눈금 간격(step) 계산
        raw_step = span / 4.0
        magnitude = 10 ** math.floor(math.log10(raw_step))
        normalized = raw_step / magnitude
        step = raw_step
        for candidate in (1, 2, 2.5, 5, 10):
            if normalized <= candidate:
                step = candidate * magnitude
                break

        if is_log:
            # [수정] 로그축은 10의 거듭제곱 형태의 정수로 맞춰서 Major tic이
            # 딱 떨어지게 한다 (예: 데이터가 2~2100이면 축 범위는 1~10000)
            lo_val = data_min if data_min > 0 else max(data_max * 0.001, 1e-6)
            hi_val = data_max if data_max > 0 else 1.0
            axis_min = 10 ** math.floor(math.log10(lo_val))
            axis_max = 10 ** math.ceil(math.log10(hi_val))
            if axis_min >= axis_max:
                axis_max = axis_min * 10
            return axis_min, axis_max, step

        # [수정] 선형축은 계산된 min/max를 정수로 취한다. Min은 데이터 자체가
        # 정수면(예: x_min=0) 패딩 없이 그대로 사용해서 0부터 시작하는 등
        # 자연스러운 값이 유지되게 한다. [버그 수정] 이전엔 min/max가 둘 다
        # 정수면 max에도 패딩을 아예 안 줘서 데이터가 축 끝에 딱 붙어버리는
        # 문제가 있었음(예: 실 데이터 min=310,max=360인데 축도 그대로
        # 310~360) - Max는 정수여도 항상 여유를 준다.
        data_min_is_int = abs(data_min - round(data_min)) < 1e-9
        if data_min_is_int:
            axis_min = float(round(data_min))
            axis_max = math.ceil(data_max + span * 0.05)
        else:
            axis_min = math.floor(data_min - span * 0.05)
            axis_max = math.ceil(data_max + span * 0.05)
        return axis_min, axis_max, step
        
    def _has_enhanced_markup(self, text):
        if not text: return False
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch in ("_", "^") and i + 1 < n and text[i + 1] == "{":
                depth = 1
                j = i + 2
                while j < n and depth > 0:
                    if text[j] == "{": depth += 1
                    elif text[j] == "}": depth -= 1
                    j += 1
                if depth == 0: return True
                i = j
                continue
            i += 1
        return False

    _LINEBREAK_MARKER = "\x01"

    def _render_text(self, text):
        text = (text or "").replace("|", self._LINEBREAK_MARKER)
        if self._has_enhanced_markup(text):
            rendered, mode = self._sanitize(text), "enhanced"
        else:
            safe = text.replace("\\", "\\\\").replace('"', '\\"')
            rendered, mode = safe, "noenhanced"
        rendered = rendered.replace(self._LINEBREAK_MARKER, "\\n")
        return rendered, mode

    def _sanitize(self, text):
        if not text: return ""
        result = []
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch in ("_", "^") and i + 1 < n and text[i + 1] == "{":
                depth = 1
                j = i + 2
                while j < n and depth > 0:
                    if text[j] == "{": depth += 1
                    elif text[j] == "}": depth -= 1
                    j += 1
                if depth == 0:
                    result.append(text[i:j])
                    i = j
                    continue
                else:
                    result.append("\\\\" + ch)
                    i += 1
                    continue
            elif ch in ("_", "^") or ch == "\\":
                result.append("\\\\" + ch)
                i += 1
            else:
                result.append(ch)
                i += 1
        return "".join(result)

    def _render_legend_box(self, lines, curves, pos_raw, box_on, thick_val, id_offset,
                            f_scale, line_scale, panel_scale, is_print_mode, curve_index_map, font_name,
                            axis_w_in=5.0, legend_size=None, axis_h_in=4.0, box_w_extra_chars_override=None,
                            align="Auto", fmt=None, box_w_pct_override=None, box_h_pct_override=None,
                            axis_x_span=None, axis_y_span=None):
        """gnuplot 네이티브 key 대신, set object(박스)+set arrow(샘플선)+set label(텍스트)를
        직접 조합해서 legend box를 그린다. Legend1/Legend2 둘 다 이 함수로 통일해서
        그린다 (네이티브 key의 정렬/여백이 예측하기 어려워서, 완전히 직접 제어하는
        방식으로 변경). id_offset은 Legend1(8000대)/Legend2(9000대)가 서로
        set object/arrow/label 번호가 겹치지 않도록 구분하기 위함."""
        if not curves:
            return

        # [수정 - 버그] "axis title/Plot Title은 비슷해 보이는데 legend만 너무
        # 커 보임(10~11pt 정도가 적당해 보임)" - title/xlabel/legend 모두 같은
        # f_scale(1.60)을 그대로 곱해서 서로간 비율은 원래와 같은데도, legend만
        # 유독 큰 느낌이라는 피드백 - legend에서만 그 배율을 추가로 낮춘다
        # (9pt 기준 * 1.60 * 0.7 ≈ 10.1pt로 요청하신 범위에 맞춤). 화면(screen)은
        # 이 2배 확대 대상이 아니었으므로 손대지 않음.
        _legend_font_extra = 0.7 if is_print_mode else 1.0
        # [수정] "Legend Font: PNG 등은 약간 작아 보임, EMF/SVG는 오케이" - EMF는
        # f_scale 자체가 이미 0.75 축소돼 있고 SVG는 축소가 없는데도(즉 PDF/PNG와
        # font_pt 계산이 같은데도) SVG는 괜찮고 PDF/PNG(cairo 렌더러)만 작다는
        # 피드백 - font_pt 수식이 아니라 cairo 렌더러 자체가 같은 pt를 더 작게
        # 그리는 것으로 보여, cairo 계열(pdf/png/jpg - 실제로는 다 pdf 경로)에만
        # 약간의 보정 배율을 추가로 곱한다.
        # [삭제 - 근본 원인 확인, 이 boost 자체가 오히려 원인이었음] "PNG 등은
        # legend가 약간 작아 보임, EMF/SVG는 오케이"로 1.1->1.2배까지 올렸었지만
        # "legend/title 비율이 PNG는 0.417, EMF/SVG는 0.333로 다르다"는 이번
        # 피드백으로 재조사함. gnuplot 자체(우리 코드와 무관한 최소 재현
        # 스크립트로 별도 확인)를 직접 실측한 결과: pdfcairo 터미널은 "font
        # 'Name,SIZE'"로 지정한 값과 무관하게 PDF에 실제로 기록되는 폰트
        # 크기가 title/xlabel/tic/legend 전부 예외 없이 정확히 2/3로 축소됨
        # (지정 36->실제 24, 지정 15->실제 10 - PyMuPDF로 span.size 직접 측정,
        # 우리 legend box 폭 추정 코드에 이미 있던 "text_corr=2/3(PIL 추정폭이
        # 실제보다 1.5배 크게 나옴)"과 정확히 같은 현상 - 원인이 하나였음).
        # 이 축소는 title/legend 등 "모든" 요소에 똑같이 걸리므로, legend에만
        # 추가 배율을 곱하지 않아도 (legend/title) 비율 자체는 원래 EMF/SVG와
        # 이미 같았음(직접 계산 확인: 이 boost를 걷어내면 PDF·PNG·SVG·EMF
        # 넷 다 legend/title=0.333로 정확히 일치). 즉 "PNG legend가 작아
        # 보인다"는 원래 피드백은 legend만의 문제가 아니라 PDF/PNG 텍스트
        # 전체(title도 포함)가 2/3로 줄어 "절대 크기"가 작게 보이는 것이었는데,
        # legend에만 국소적으로 boost를 걸어 절대 크기는 어느 정도 보완됐지만
        # 그 대신 EMF/SVG와의 "비율 일치"가 깨진 것 - 지금 요청(포맷 간 불일치
        # 해소)에 맞춰 boost를 제거해 비율을 맞춘다(절대 크기를 EMF/SVG 수준으로
        # 올리려면 legend만이 아니라 title/xlabel/tic 전부에 똑같이 1.5배를
        # 곱해야 하는데, 그러면 이미 이 "축소된" 크기 기준으로 검증돼 있는
        # margin 여유값들도 전부 다시 맞춰야 해서 별도로 논의 필요).
        # [추가 - 요청] "칸이 좁아지면(예: Auto 3/p Landscape, axis_w=2.34in인데
        # axis_h=2.92in - axis 자체 비율이 기준 10:8=1.25보다 훨씬 좁음) legend
        # box가 axis 폭의 90%+까지 차지함" - box_w는 이미 axis_w_in 대비 비율로
        # 계산되지만(_render_legend_box 아래 char_width_frac 등), font_pt(=box
        # 안 글자 크기) 자체는 axis_w_in과 무관하게 f_scale(칸 전체 크기 기준)
        # 로만 정해져서, axis가 유독 "가로로만" 좁아진 경우엔 font가 상대적으로
        # 안 줄어 box가 좁은 axis에 비해 커 보였음. axis 자체의 가로:세로 비율이
        # 기준(10:8=1.25)보다 좁을 때만(넓을 때는 손대지 않음 - 가로가 넉넉한
        # 경우는 문제가 없었음) 그 비율만큼 font를 같이 줄인다 - sqrt로 완화(전부
        # 다 줄이면 극단적으로 좁을 때 글자가 너무 작아짐), 0.5 밑으로는 더
        # 줄지 않게 최소한도를 둔다(가독성 보장).
        _REF_AXIS_RATIO = 10.0 / 8.0
        _axis_shape_scale = 1.0
        if axis_w_in and axis_h_in:
            _cur_axis_ratio = axis_w_in / max(axis_h_in, 0.01)
            if _cur_axis_ratio < _REF_AXIS_RATIO:
                _axis_shape_scale = max((_cur_axis_ratio / _REF_AXIS_RATIO) ** 0.5, 0.5)
        font_pt = (legend_size if legend_size else 9) * f_scale * _legend_font_extra * _axis_shape_scale
        # [주의] pngcairo가 pdfcairo보다 legend 글자를 아주 약간 더 크게 그리는
        # 경향이 실측됐지만(동일 스크립트, 터미널만 다르게 비교), 보정 계수가
        # panel_scale/legend_size에 따라 비선형으로 달라져 신뢰할 수 있는 고정
        # 공식을 찾지 못했음 - 잘못된 계수로 legend box가 과도하게 커지는 쪽이
        # 더 나쁜 실패라 보정 없이 pdfcairo와 동일한 추정을 그대로 쓴다. 대신
        # box_w/box_h(아래)가 axis 대비 과도하게 커지면 경고로 미리 알린다.
        # [수정] ROW_H가 축 높이와 무관하게 그냥 graph 비율(0.048*panel_scale)로
        # 고정돼 있어서, explicit frame으로 작은 물리 크기를 지정하면 실제 폰트
        # 크기(font_pt)에 비해 줄 간격이 너무 좁아져 legend 줄들이 서로 겹쳐
        # 보이는 문제가 있었음 - 축의 실제 물리적 높이(axis_h_in)를 기준으로
        # 폰트 크기에 맞는 절대 줄 높이를 먼저 구하고, 그걸 graph 비율로 환산한다.
        # [수정] "legend 안 curve간 위아래 간격이 너무 큼" - 줄간격 배수를
        # 1.35 -> 1.15 -> 1.0으로 계속 줄임(더 줄여달라는 후속 요청).
        # [수정] "Print에서 첨자(subscript) 넣으면 줄끼리 겹칠 듯하다"는 피드백으로
        # print만 1.0 -> 1.2로 다시 늘림(화면은 기존 1.0 유지).
        # [수정 - 버그] "PNG는 legend 줄이 겹침(2.0으로 고쳐야 했음), 그런데
        # PDF/EMF는 반대로 줄 간격이 너무 넓어짐" - 같은 폰트 pt·같은 1.2
        # 기준값이어도 터미널(렌더러)마다 실제 그려지는 글자 높이가 달라서
        # (pngcairo가 유독 작은 폰트에서 크게 그림 - 실측 확인) 한 배수를
        # 전 포맷에 공유하면 한쪽은 겹치고 한쪽은 헐거워짐 - 포맷별로 따로
        # 둔다. [수정 - 버그] "반으로/2/3로 줄여줘요"는 원래 기준(1.2)이
        # 아니라 "지금 보고 있는(=2.0 기준) 결과" 대비 배수였음 - 1.2 기준으로
        # 잘못 계산해서 EMF 렌더링 확인 결과 줄끼리 완전히 겹쳐버리는 심각한
        # 회귀가 났음(직접 렌더링해서 발견) - 2.0 기준으로 다시 계산.
        # box-title 간격(_box_w_extra_chars)도 같은 이유로 포맷별.
        # [수정] "parameter를 행렬형태로 fmt별로 지정하면 단순할 것 - 나중에
        # 조정하기도 쉽고" 요청으로, 그동안 여기저기 흩어져 있던 포맷별 계수
        # (row_mult/box_chars/style 길이 배율/PIL 실측 보정)를 fmt를 key로,
        # 각 계수를 column으로 하는 표 하나(_FORMAT_TUNING)로 모음. 항목 뜻:
        #   row_mult  : legend 줄 간격 배수(폰트 크기 기준)
        #   box_chars : legend box 테두리<->curve title 사이 여백(대문자
        #               기준 "실제 보이는" 글자 수 - text_corr 보정 이후
        #               기준이라 격식대로 해석 가능)
        #   sample_mult: style(샘플선) 길이의 포맷별 추가 배율(1.0=보정 없음)
        #   text_corr : PIL로 잰 글자폭을 gnuplot이 실제로 그리는 폭에 맞게
        #               보정하는 배율. PDF를 PyMuPDF로 직접 실측(4개의 서로
        #               다른 라벨 문자열 각각 확인)한 결과 PIL 추정치가
        #               gnuplot pdfcairo 실제 렌더링보다 항상 정확히 1.5배
        #               크게 나옴(오차 0.1% 이하로 매우 일관됨) - 즉 PIL
        #               추정폭에 2/3을 곱해야 실제 폭과 일치함.
        #               [주의] pngcairo도 같은 cairo 엔진이라 처음엔 PDF와
        #               동일하게 2/3을 적용했으나, 실제 렌더링해서 확인해
        #               보니 "MFLO:R-SDRT1>L-STLF1" 같은 라벨이 box 밖으로
        #               삐져나옴(box가 너무 작아짐) - PNG는 PDF와 별개로
        #               "실측 대비 텍스트를 더 크게 그림"이라는 기존에 이미
        #               알려진 자체 차이가 하나 더 있어서(PDF 실측과 다른
        #               수치), PDF의 1.5배 계수를 그대로 재사용하면 과보정됨.
        #               PNG 자체의 정확한 계수는 아직 실측 못 했으므로 안전하게
        #               text_corr=1.0(보정 없음)으로 되돌리고, box_chars만
        #               기존값에서 조금 줄인다. EMF(GDI)/JPG(libgd)는 cairo가
        #               아니라 이 보정과 무관 - 1.0 유지.
        _fmt_l = (fmt or "").lower()
        # [수정] 실제 GUI Save 결과(out111 등) 재확인 피드백 - "PNG는 line↔title
        # 1글자 이상 겹침 -> 가로길이 2자 늘릴 것", "EMF는 반자 더 줄이고",
        # "SVG는 2자 줄일 것". (PNG는 이제 PDF 래스터화 경로를 쓰므로 실제로는
        # "pdf" 항목이 적용되지만, PyMuPDF 미탑재 등으로 레거시 경로로 빠질 때를
        # 대비해 png 항목도 함께 조정해 둔다.)
        # [수정] 실제 GUI Save 재확인 추가 피드백 - "PNG는 1글자, EMF 0.5글자,
        # SVG는 3글자 폭을 추가로 감소", "SVG는 legend 내 curve 간 아래위
        # 간격을 0.8배로 축소".
        # [수정 - 근본 원인, 재작업] "box 왼쪽 테두리<->title 텍스트 여백을
        # legend font 기준 '1글자'로 통일" - 1차 보정 때 실수로 짧은 문자열
        # ("PRESS:PRSTNK(1)")만 재서 확인했는데, box_w는 실제로 max_label_len
        # (둘 중 더 긴 "MFLO:R-SDRT1>L-STLF1")을 기준으로 정해지므로 그
        # 문자열로 재야 맞았음(사용자 지적으로 재확인 - 실제로 긴 문자열은
        # box 밖까지 삐져나가 있었음). 긴 문자열 기준으로 PyMuPDF 재실측한
        # 결과 PDF는 box_chars=1.0에서 정확히 1.00자로 확인됨 - 나머지
        # 포맷도 같은 방식으로 다시 실측해서 확정한다(아래 각 값 옆 주석 참고).
        _FORMAT_TUNING = {
            "png": {"row_mult": 2.0,           "box_chars": 1.0, "sample_mult": 2 / 3,   "text_corr": 1.0},
            "pdf": {"row_mult": 2.0 * 0.5,      "box_chars": 1.0, "sample_mult": (2/3)**2, "text_corr": 2 / 3},
            "emf": {"row_mult": 2.0 * (2 / 3),  "box_chars": 1.0, "sample_mult": (2 / 3) * 0.8, "text_corr": 1.0},
            "jpg": {"row_mult": 2.0 * (2 / 3),  "box_chars": 1.0, "sample_mult": 2 / 3,   "text_corr": 1.0},
            "jpeg": {"row_mult": 2.0 * (2 / 3), "box_chars": 1.0, "sample_mult": 2 / 3,   "text_corr": 1.0},
            "svg": {"row_mult": 2.0 * (2 / 3) * 0.8, "box_chars": 1.0, "sample_mult": 0.5, "text_corr": 1.0},
        }
        # [수정 - 버그] "화면(screen)은 건드리지 말라고 했는데 왜 바뀌었나" -
        # 실측 확인 결과 screen의 row_mult=1.0(폰트 크기와 정확히 같은 줄
        # 높이, 여유 0)은 원래부터 자체적으로 너무 빠듯해서 curve가 2개만
        # 있어도 줄끼리 겹쳐 보이는 문제가 있었음(직접 렌더링해서 확인 -
        # 오늘 바꾼 적 없는 값인데도 재현됨). "노트북에서 title-box 간격이
        # 대문자 5자 정도 과하다" 피드백으로 box_chars도 1.7 -> 0.5로 축소.
        # [수정] "screen에서도 여백이 반영 안됨" 재확인 - PNG에서 검증 없이
        # text_corr을 적용했다가 라벨이 box 밖으로 삐져나오는 사고가 났으므로
        # (바로 위 주석 참고), 실측 못 한 screen도 안전하게 text_corr=1.0
        # (보정 없음) 유지 - box_chars(0.5)만으로 대응한다.
        # [수정] 실제 windows 창을 캡처해서 확인한 결과도 여전히 간격이 커서
        # box_chars를 0.5 -> -0.5로 축소 + style 길이(SAMPLE_W)만큼 추가로
        # 빼는 보정(아래) 적용. "screen_v4는 개선됐지만 대문자 1자 정도 더
        # 줄여달라(사무실 PC에서는 더 크게 보임)" 후속 피드백으로 한 번 더
        # -1.0 축소.
        # [수정] "사무실 큰 화면에서는 legend box 마진이 더 커서 title과의
        # 간격이 늘어남 - 1글자(10pt) 더 줄여줘요" - 이전에도 같은 이유(사무실
        # PC 화면 DPI 차이)로 한 번 줄인 적 있음(0.5->-0.5) - 같은 폭(-1.0)
        # 만큼 추가로 축소.
        _legend_tuning = (_FORMAT_TUNING.get(_fmt_l, {"row_mult": 1.2, "box_chars": 2.0, "sample_mult": 1.0, "text_corr": 1.0})
                          if is_print_mode else {"row_mult": 1.2, "box_chars": -1.5, "sample_mult": 1.0, "text_corr": 1.0})
        ROW_LINE_HEIGHT_IN = (font_pt / 72.0) * _legend_tuning["row_mult"]
        ROW_H = ROW_LINE_HEIGHT_IN / max(axis_h_in, 0.3)
        # [수정] 박스 위/아래 내부 여백이 너무 얇아서(0.06) 맨 아래 줄 글자가
        # 박스 테두리에 닿아 보인다는 피드백으로 화면에서 크게 늘렸는데(0.3),
        # 이걸 print/save에도 그대로 적용해서 이번엔 "여분이 너무 크다"는
        # 반대 피드백이 나왔음 - print/save는 원래 값에 가깝게 되돌리고
        # 화면만 크게 유지한다
        # [수정] "legend box 테두리와 첫/끝 줄 글자 사이 여백도 줄여달라"는
        # 요청으로 print 쪽 계수를 0.12 -> 0.08로 축소(화면은 그대로 유지).
        _row_margin_ratio = 0.08 if is_print_mode else 0.3
        ROW_MARGIN = _row_margin_ratio * ROW_H
        # [수정] "문자 하나당 대략적인 폭(인치)"을 legend 라벨 폭 추정뿐 아니라
        # legend box와 axis frame 사이 간격(1자 정도)에도 재사용한다 - font_pt에
        # 비례하는 절대(인치) 값을 먼저 구하고, 가로/세로는 각각 axis_w_in/
        # axis_h_in으로 나눠 graph 비율로 환산해야 실제 물리적 간격이 가로세로
        # 동일해진다. 예전엔 ROW_H(세로 기준 비율)를 가로에도 그대로 썼어서,
        # 축의 가로세로 비율이 1:1이 아니면(거의 항상 그럼) 가로/세로 실제
        # 간격이 서로 달라지는 문제가 있었음(화면 전용으로 1000/700 비율을
        # 어림으로 보정하던 땜질도 이 근본 문제 때문이었음 - 이제 필요 없어짐).
        # [수정] 0.0065는 실측(PyMuPDF로 렌더링된 PDF의 실제 글자 폭 측정)해보니
        # 순수 대문자(가장 넓은 경우, 예: "ABCDEFGHIJKLMNOPQRST")조차 실제보다
        # 커서, 그 오차가 라벨 길이만큼 누적되어(20자면 20배) legend box 왼쪽에
        # 큰 빈 공간이 남는 원인이었음 - 실측 기준(대문자 1자 폭)으로 재보정.
        char_width_in = (0.0055 if is_print_mode else 0.0049) * font_pt  # 문자 하나당 대략적인 폭(인치, 대문자 기준 실측), 폰트 크기(pt)에 비례
        char_width_in *= _font_width_ratio(font_name)  # 폰트가 대체된 경우 실제 폭 비율로 보정
        # [수정] legend box와 plot 테두리(frame) 사이 간격은 major tic 길이의
        # 1.5배로 맞춘다("major tic 길이의 1.3~1.5배로" 요청). gnuplot이 실제
        # 그리는 major tic 길이를 Python에서 직접 조회할 수는 없어서, 렌더링된
        # PDF를 실측(PyMuPDF)해 font_pt 대비 비율로 역산한 근사 계수를 쓴다
        # (실측: is_print_mode 기준 font_pt=7.2일 때 major tic 길이 ≈ 0.0443in
        # → 계수 ≈ 0.00615/font_pt). tic 길이 자체가 font_pt에 비례해 커지므로,
        # 이 간격도 legend 폰트가 커지면 같이 커진다.
        # [수정 - 버그] "legend box와 축 frame 사이도 major tic 1.5배 정도
        # 여유를 둬야 함" - 처음엔 계수(1.5)는 그대로 두고 최종 간격만 4.5~6배로
        # 늘렸었는데("1.5배라면서 왜 2배로 보이냐"는 피드백으로 되돌아옴) -
        # 요청대로 기준이 되는 TIC_LEN_IN 자체를 1.5배로 올리고, 최종 간격
        # 배수는 다시 깔끔하게 "1.5 * TIC_LEN_IN" 공식으로 되돌린다(결과적으론
        # 이전 실측 기준 대비 2.25배 - "2배처럼 보였다"는 반응과 "간격이 있어야
        # 한다"는 요청 사이의 절충점).
        # [수정 - 버그] "PNG(PDF)에서 frame<->legend box 간격이 너무 큰데 maj
        # tic은 오히려 짧아 보임 - 같은 규칙 아닌가?" - 정확한 지적. 이 계수는
        # legend 폰트 크기(font_pt)에서 역산한 근사치일 뿐, _build_plot_commands
        # 에서 png/pdf/svg에 따로 적용하는 실제 tic 길이 축소(2/3, 0.8배 등)를
        # 전혀 반영하지 못해서 실제(줄어든) tic보다 간격이 상대적으로 커
        # 보이게 됐음 - 같은 포맷별 축소 비율을 여기도 그대로 곱한다.
        _tic_len_fmt_mult = {"png": 2 / 3, "pdf": 2 / 3, "svg": 0.8 * 0.8}.get((fmt or "").lower(), 1.0)
        TIC_LEN_IN = 1.5 * 0.00615 * font_pt * _tic_len_fmt_mult
        FRAME_GAP_IN = 1.5 * TIC_LEN_IN
        FRAME_MARGIN_X = FRAME_GAP_IN / max(axis_w_in, 0.5)  # plot 테두리(frame)와 박스 사이 가로 간격
        FRAME_MARGIN_Y = FRAME_GAP_IN / max(axis_h_in, 0.3)  # 세로 간격(동일한 물리 거리)

        def _resolve_anchor(pos_raw):
            pos_raw = (pos_raw or "").strip()
            is_raw = pos_raw.startswith("graph ") or pos_raw.startswith("screen ") or pos_raw.startswith("at ")
            is_pct = False
            if not is_raw and "," in pos_raw:
                parts = [p.strip() for p in pos_raw.split(",")]
                if len(parts) == 2:
                    try:
                        float(parts[0]); float(parts[1])
                        is_pct = True
                    except ValueError:
                        is_pct = False
            if is_pct:
                px, py = pos_raw.split(",")
                return float(px) / 100.0, float(py) / 100.0, "left bottom"
            if is_raw:
                nums = re.findall(r"[-+]?\d*\.?\d+", pos_raw)
                ax = float(nums[0]) if len(nums) > 0 else 0.95
                ay = float(nums[1]) if len(nums) > 1 else 0.05
                return ax, ay, "left bottom"
            if pos_raw == "outside right":
                return 1.0 - FRAME_MARGIN_X + 0.02, 0.5, "left top"
            h = "right" if "right" in pos_raw else ("left" if "left" in pos_raw else "center")
            v = "top" if "top" in pos_raw else ("bottom" if "bottom" in pos_raw else "center")
            ax = (1.0 - FRAME_MARGIN_X) if h == "right" else (FRAME_MARGIN_X if h == "left" else 0.5)
            ay = (1.0 - FRAME_MARGIN_Y) if v == "top" else (FRAME_MARGIN_Y if v == "bottom" else 0.5)
            corner = f"{h} {v}".strip() if not (h == "center" and v == "center") else "center"
            return ax, ay, corner

        ax, ay, corner = _resolve_anchor(pos_raw)
        # 좌표(%,graph) 입력일 때 corner가 "left bottom"으로 고정되어 있어도,
        # 실제 ax(0~1) 값으로 좌/우를 직접 판단해서 미러링 방향을 정한다
        # [수정] "이 자동 판정과 다르게 정렬하고 싶다"는 요청으로, align이
        # "Left"/"Right"로 명시되면 그 값을 그대로 따르고, "Auto"(기본)일 때만
        # 기존 x값 기준 자동 판정을 쓴다.
        if align == "Left":
            is_right_side = False
        elif align == "Right":
            is_right_side = True
        else:
            is_right_side = ax >= 0.5

        # [수정 - 버그] SAMPLE_W(가로 길이)를 ROW_H(세로=axis_h_in 기준 비율)로
        # 그대로 계산해서, 축이 정사각형이 아니면(Portrait처럼 axis_h_in이
        # axis_w_in보다 크면) 실제 세로 절대 길이(ROW_LINE_HEIGHT_IN)를
        # axis_w_in이 아닌 axis_h_in으로 나눈 값이 가로 길이로 잘못 쓰여서
        # style이 실제보다 짧게 나오는 문제가 있었음("port에서 style이 축
        # 비율 대비 더 짧다" 실측 확인) - 같은 절대 길이(ROW_LINE_HEIGHT_IN)를
        # axis_w_in으로 나눠 올바른 가로 비율로 계산한다(정사각형 축이면
        # 기존과 동일).
        # [수정 - 버그] style(샘플선) 길이는 줄 간격(ROW_LINE_HEIGHT_IN)과
        # 수식을 공유했었는데, 위에서 줄 간격을 포맷별로 다르게 만들면서
        # (PDF 0.5배, EMF 2/3배 등) style 길이까지 덩달아 줄어드는 부작용이
        # 생김 - style 길이는 이 고정 기준(기존 PNG 기준과 동일한 2.0)으로
        # 계산을 완전히 분리하고, 포맷별 최종 배율(_SAMPLE_W_FMT_MULT)만
        # 따로 곱한다.
        _SAMPLE_REF_ROW_HEIGHT_IN = (font_pt / 72.0) * 2.0
        SAMPLE_W = 1.3 * 1.3 * (_SAMPLE_REF_ROW_HEIGHT_IN / max(axis_w_in, 0.5))  # style(샘플선) 길이가 너무 짧다는 피드백으로 1.3배 확대
        SAMPLE_W -= 1.5 * (char_width_in / max(axis_w_in, 0.5))  # 다시 대문자 1.5자만큼 축소 요청
        # [수정] "Print/Save에서 style 길이가 여전히 너무 짧다" - print만 2배로
        # (screen은 별도 문제 제기가 없었으므로 기존 값 유지, screen/print 마진을
        # 분리해야 한다는 후속 피드백 반영).
        if is_print_mode:
            SAMPLE_W *= 2
            # [수정] "지금(2배) 길이가 너무 길다 - 2/3 정도로 줄일 것" 후속 피드백.
            # 결과적으로 원래 값의 2*(2/3) ≈ 1.33배가 됨.
            SAMPLE_W *= 2 / 3
        # [수정] "Legend 내 style 길이 조금 더 길게(1.2배 정도)" 요청 - screen/print
        # 공통으로 추가 확대.
        SAMPLE_W *= 1.2
        # [수정 - 버그] "PDF/EMF/JPG의 style 길이=2/3로 줄일 것"(EMF/JPG는 이번에
        # 새로 요청, PDF는 "지금 기준"으로 한 번 더) - 위 _FORMAT_TUNING의
        # sample_mult로 통일 관리(PNG/SVG는 요청 없어 1.0 유지).
        # [수정] "화면(screen)도 style 길이를 지금의 2/3 정도로" - 화면은
        # is_print_mode=False라 _FORMAT_TUNING(print 전용)을 안 타서 별도로 적용.
        if is_print_mode:
            SAMPLE_W *= _legend_tuning["sample_mult"]
        else:
            SAMPLE_W *= 2 / 3
        # [수정] char_width_in은 대문자(가장 넓은 경우) 실측 기준인데, 글자수를
        # 그냥 len()으로 세면 숫자/콜론/대시처럼 대문자보다 좁은 문자가 많은
        # 라벨(CATHENA 변수명 특성상 흔함, 예: "MFLO:R-SDRT1>L-STLF1")은 실제
        # 폭보다 훨씬 넓게 box가 잡혀 라벨 앞에 불필요한 빈 공간이 남았음
        # ("우측(순수 대문자)은 괜찮은데 좌측(콜론/대시 섞인 라벨)은 너무 넓음")
        # - 문자별로 폭 비중을 달리해서 실측 폭에 더 가깝게 라벨 길이를 추정한다.
        # [수정 - 버그] "space를 따로 count해야지, 대소문자로도 나눠야" - 예전엔
        # space를 "narrow"에도 안 넣어서 대문자(1.0)와 동일하게 셌고(가장 흔한
        # 과대평가 원인), 숫자/기호도 전부 0.65 하나로 뭉뚱그렸음 - 실측(pngcairo,
        # Malgun Gothic 20pt, "AAAA.."/"aaaa.."/"0000.."/"A A A.."/"::::.."/
        # "----.."/"((((.." 등을 렌더링해서 픽셀 폭 직접 측정)해 4단계로 나눔:
        # 대문자 1.0(기준) > 소문자 0.8 ≈ 숫자 0.8 > 하이픈/괄호류 0.6 >
        # space/마침표/쉼표/콜론류 0.35(가장 좁음, 예전엔 1.0으로 계산되던 것).
        # [주의] 이 비율은 Malgun Gothic 실측치라 Legend Font를 다른 폰트로
        # 바꾸면 실제 비율과 어긋날 수 있음(폰트별 실측을 다 할 수는 없음) -
        # 정확도가 중요하면 추후 "박스 폭 직접 입력" 옵션도 고려할 만함.
        _VERY_NARROW_CHARS = set(" .,:;'\"")          # space/마침표/쉼표/콜론류 - 실측 약 0.3~0.35
        _MEDIUM_CHARS = set("-_()[]{}<>=*+/")          # 하이픈/괄호/기호류 - 실측 약 0.45~0.6

        def _weighted_label_len(title):
            def _w(ch):
                if ch in _VERY_NARROW_CHARS:
                    return 0.35
                if ch in _MEDIUM_CHARS:
                    return 0.6
                if ch.isdigit() or ch.islower():
                    return 0.8
                return 1.0  # 대문자 및 그 외(한글 등)는 기준(1.0) 그대로
            return sum(_w(ch) for ch in (title or "")) or 1.0

        # [수정] "AI가 결과 보고 intelligent하게 할 수 없나" - 위 문자 가중치는
        # 여전히 추측이라, Legend Font가 알려진 폰트(_FONT_FILE_MAP)면 PIL로
        # 각 curve title의 실제 렌더 폭을 직접 측정해서 쓴다(추측이 아니라
        # 실측 - 폰트를 바꿔도 자동으로 맞음). 측정 실패(모르는 폰트, Pillow
        # 없음 등)시에만 위 문자 가중치 추정으로 안전하게 대체.
        # [수정 - 버그] "PDF/PNG legend box가 너무 큼" 근본 원인 발견 - PyMuPDF로
        # pdfcairo가 실제로 그린 4개의 서로 다른 라벨 폭을 직접 측정해보니, PIL
        # (freetype) 추정치가 gnuplot의 cairo 텍스트 렌더링보다 정확히(오차
        # 0.1% 이하) 1.5배 크게 나옴 - box_chars 등 여백 계수를 아무리 줄여도
        # 라벨 자체가 실제보다 1.5배 넓게 추정되니 box가 계속 커 보였던 것.
        # _legend_tuning["text_corr"](위 _FORMAT_TUNING)로 포맷별 보정.
        _measured_widths_in = [_measure_text_width_in(c.title, font_name, font_pt) for c in curves]
        if curves and all(w is not None for w in _measured_widths_in):
            max_label_len = max(_measured_widths_in) * _legend_tuning["text_corr"] / char_width_in
        else:
            max_label_len = max((_weighted_label_len(c.title) for c in curves), default=1.0)
        char_width_frac = char_width_in / max(axis_w_in, 0.5)
        # [수정] "legend box 샘플선과 curve title 사이 간격을 줄여달라(13자
        # 라벨 기준 2자 정도)" - 기존엔 이 간격(그리고 박스 테두리<->샘플선
        # 간격)이 axis_w_in에만 반영되고 font 크기와는 무관한 고정값(0.01,
        # 0.015)이라, 폰트를 키우면 간격은 그대로라 상대적으로 더 좁아
        # 보이고 폰트를 줄이면 반대로 헐거워 보였음 - char_width_frac(문자
        # 폭, font_pt에 비례)을 기준으로 한 "문자 개수" 단위로 바꿔서 폰트
        # 크기에 비례하게 하고, print/save(is_print_mode)와 화면 모두 이
        # 공식을 그대로 공유한다. 간격 자체도 실측(위 13자 라벨 기준) 대비
        # 크게 줄임.
        # [수정] "screen에서 legend box frame과 title 사이가 더 넉넉해야 한다"는
        # 피드백으로 screen만 대문자 1자만큼 추가(print/save는 기존 0.4 유지).
        # [수정] "Print/Save에서도 title이 샘플선에 붙어 보인다"는 후속 피드백으로
        # print도 소폭(0.4 -> 0.6) 늘림 - box_w가 폭 폭주 우려가 있어 screen(1.4)
        # 만큼은 아니고 절반 정도만 늘림.
        LABEL_GAP_FRAC = (0.6 if is_print_mode else 1.4) * char_width_frac   # 샘플선 <-> curve title 간격
        # [수정] "screen에서 박스 테두리와 샘플선이 붙어 보인다"는 재확인 피드백.
        # 계산해보면 print/screen 공통 계수(0.3)는 기본 legend_size(9pt) 기준
        # 물리 간격이 0.013in 안팎(≈2px)에 불과해, 샘플선 자체의 굵기(lw)나
        # 화면 렌더링의 안티에일리어싱만으로도 시각적으로 거의 사라지는 크기였음.
        # [수정 - 버그] "Legend 우측 align 기준으로 style과 box 사이 간격이 없음" -
        # 당시엔 print/save가 문제 없다고 봐서 0.3을 그대로 뒀는데, 실측 확인
        # 결과 legend_size 9pt 기준 물리 간격이 0.013in(≈2px)뿐이라 샘플선
        # 두께(lw)만으로도 거의 다 채워져 시각적으로 안 보였음(우측 정렬이면
        # 샘플선이 box 오른쪽 테두리에 바로 붙는 쪽이라 특히 눈에 띔) - screen과
        # 동일한 계수(0.7+1/3)로 맞춘다.
        BOX_EDGE_GAP_FRAC = (0.7 + 1 / 3) * char_width_frac  # 박스 테두리 <-> 샘플선 간격
        # [수정] "screen 창에서도 마진이 너무 넓다(5자 이상 줄여야 함)" - 예전엔
        # screen의 char_width_in 계수(0.0049)가 실측 재보정이 안 돼 실제 폭을
        # 과소평가한다는 이유로 여유분을 6.7자까지 늘려뒀었는데, 그 결과 라벨이
        # 짧을 때(예: "FLOWRATE-A") 박스 왼쪽에 텍스트 3~4개 폭에 달하는 빈
        # 공간이 남는 문제가 있었음 - 실제로 32자짜리 극단적으로 긴 라벨까지
        # 렌더링해서 확인해보니 여유분을 5자 줄인 1.7자(print와 동일한 기존
        # 기본값)로도 박스 밖으로 잘리지 않아, 화면도 print와 같은 값으로
        # 통일한다. 이후 "2/p는 1자 늘리고 4/p,6/p는 2자 더 줄여달라"는
        # 요청으로 호출자가 override를 넘기면(multiplot에서 total_cells 기준)
        # 그 값을 우선한다.
        if box_w_extra_chars_override is not None and is_print_mode:
            _box_w_extra_chars = box_w_extra_chars_override
        else:
            # [수정] "Print에서 title이 box 밖으로 5자 정도 삐져나간다"는 피드백 -
            # 폰트가 없어 대체(Arial 등)되면 실제 렌더링 폭이 실측 계수(맑은
            # 고딕 기준)보다 커질 수 있어 안전 여유를 크게 둔다(tkinter 실측
            # 보정은 스레드 문제로 폐기했으므로, 여기서 고정 버퍼로 흡수한다).
            # [수정] "box와 title 간격을 대문자 4자만큼 줄여줘요" 피드백으로
            # 18.0 -> 14.0까지 줄였었으나, PNG를 기준으로 잡은 값이라 PDF/EMF/
            # JPG에서는 오히려 "간격이 너무 크다(1~2자면 충분)"는 재확인
            # 피드백을 받음 - 포맷별로 실제 필요한 안전 여유가 다르다는 뜻이라
            # (PNG만 유독 실측 대비 텍스트 폭을 크게 그림) 위에서 정의한
            # _legend_tuning["box_chars"]를 그대로 쓴다(PNG=14.0 유지).
            # [참고] "EMF는 코드값 14인데도 실제로는 5자 정도 간격으로 보임"
            # 이라는 실측 보고로 역산하면 EMF의 코드값 대비 실제 배율이
            # 약 0.36 - 요청하신 "1~2자"를 문자 그대로(2.0) 넣으면 이 비율상
            # 실제로는 1자도 안 남을 걸로 보여, 조금 더 여유(4.0)를 둠(직접
            # 렌더링 확인 결과 이 정도는 겹치지 않음 - 그래도 여전히 넉넉하면
            # 추가로 줄여도 됨). PDF/JPG/SVG는 EMF와 같은 근거가 없어 일단
            # 동일하게 4.0을 임시로 공유(각각 재확인 필요). box_w 자체는
            # 여전히 max_label_len을 포함해 체크된 curve/surface 중 가장 긴
            # 라벨 글자 수에 맞춰 자동으로 넓어짐.
            _box_w_extra_chars = _legend_tuning["box_chars"]
        # [수정] "screen에서도 box line과 title 사이 간격이 너무 큼 - style
        # 길이만큼 줄여야 함" - 실제 화면(windows 터미널) 창을 캡처해서
        # 직접 확인한 결과 여전히 간격이 넓었음. 사용자가 준 정확한 기준대로
        # box_chars가 만드는 여백(char_width_frac*box_chars)에서 style(샘플선,
        # SAMPLE_W)의 길이만큼을 그대로 빼서 줄인다(screen 전용 - print/save는
        # 이미 실측 기반으로 따로 맞춰서 여기서는 손대지 않음).
        if not is_print_mode:
            _box_w_extra_chars -= SAMPLE_W / max(char_width_frac, 1e-9)
        # [수정] box가 title을 못 감싸는(밖으로 삐져나옴) 버그 - LABEL_GAP_FRAC
        # (샘플선<->title 간격)이 여기 폭 계산에 빠져 있어서, 그 간격을 늘릴수록
        # title이 안쪽으로 밀리기만 하고 box는 안 넓어져 오히려 더 잘려 보였음.
        box_w = SAMPLE_W + char_width_frac * (max_label_len + _box_w_extra_chars) + BOX_EDGE_GAP_FRAC + LABEL_GAP_FRAC
        box_h = ROW_H * len(curves) + 2 * ROW_MARGIN

        # [추가] "자동 추정이 안 맞는 경우만 사용자 입력으로 직접 지정" -
        # 비워두면(None/빈 문자열/숫자 아님) 위 자동 추정을 그대로 쓰고,
        # 값이 있으면 그 크기로 고정한다. 높이를 고정하면 줄 간격(ROW_H)/
        # 줄 위아래 여백(ROW_MARGIN)도 그 고정 높이에 맞춰 다시 나눠야,
        # 아래 curve별 루프에서 쓰는 row_y가 실제로 그 안에 고르게 들어간다
        # (안 그러면 박스만 커지고 줄 간격은 그대로라 위아래에 빈 공간만
        # 남거나, 반대로 줄어들면 여전히 겹침).
        # [추가] "%뿐 아니라 x,y 좌표값으로도 - 인터랙티브 창에서 마우스
        # 커서로 좌표를 직접 읽어서 넣기 편하게, print/save 결과와 정확히
        # 안 맞을 수 있어도 참고하기 쉬움" 요청 - "%"로 끝나면 axis 대비
        # 비율(기존), 그냥 숫자면 실제 데이터 좌표값 차이로 보고 axis의
        # 전체 데이터 범위(axis_x_span/axis_y_span)로 나눠 비율로 환산한다.
        # 좌표값 모드인데 범위를 못 구했으면(예: auto인데 아직 데이터 없음)
        # 조용히 무시하고 자동 추정으로 대체한다.
        def _parse_box_dim(v, axis_span):
            s = (v or "").strip()
            if not s:
                return None
            is_pct = s.endswith("%")
            try:
                num = float(s[:-1] if is_pct else s)
            except ValueError:
                return None
            if num <= 0:
                return None
            if is_pct:
                return num / 100.0
            if not axis_span or axis_span <= 0:
                return None  # 좌표값 모드인데 axis 범위를 모름 - 자동 추정으로 대체
            return num / axis_span
        # [수정 - 버그] "Print/Save 전용" 툴팁을 달아놓고 정작 코드는 화면
        # (Interactive)에서도 그대로 적용되고 있었음 - "프린트나 이미지에서"
        # 라는 명시적 요청과 툴팁 문구에 맞게 is_print_mode일 때만 적용한다
        # (기존 box_w_extra_chars_override와 동일한 방식).
        _box_w_override = _parse_box_dim(box_w_pct_override, axis_x_span) if is_print_mode else None
        _box_h_override = _parse_box_dim(box_h_pct_override, axis_y_span) if is_print_mode else None
        if _box_w_override is not None:
            box_w = _box_w_override
        if _box_h_override is not None:
            box_h = _box_h_override
            n_rows = max(len(curves), 1)
            ROW_H = box_h / (n_rows + 2 * _row_margin_ratio)
            ROW_MARGIN = _row_margin_ratio * ROW_H

        # [추가] Legend box가 axis 가로/세로의 절반을 넘으면 plot을 너무 많이
        # 가려서 미리 경고한다(정확한 렌더링 크기가 아니라 Python 추정값
        # 기준이라 완벽하진 않지만, box_w/box_h는 axis 대비 fraction이라 실제
        # 렌더링 크기와도 비례해서 신뢰할 만한 지표임).
        # [수정] "M-P 1p/2p에서 legend box가 너무 크다는 경고가 매번 뜬다" -
        # 실제 사용자 docx로 재현·실측한 결과, 곡선명이 길면(예: 20자
        # "MFLO:R-SDRT1>L-STLF1") legend가 축 폭의 70~85%를 차지하는 게
        # 정상이었음(렌더링 자체는 legend가 axis 안에 잘 들어가 있고 겹침/
        # 잘림 없음 - 계산 오류가 아니라 임계값 50%가 너무 보수적이었던
        # 것). 사용자와 상의해 "실제 렌더링에는 손대지 않고 경고 임계값만
        # 올리는" 방향으로 확정 - 0.5 -> 0.9로 올려서 진짜 심각한 경우(예:
        # 90%+, 곡선이 아주 많거나 이름이 극단적으로 긴 경우)만 잡는다.
        if box_w > 0.9 or box_h > 0.9:
            self.warnings.append(
                f"Legend box가 axis 크기의 90%를 넘습니다(가로 {box_w*100:.0f}%, "
                f"세로 {box_h*100:.0f}%). Legend Font 크기, curve title 길이, "
                f"curve 개수를 줄이거나 Frame 크기를 키워보세요."
            )

        # [수정 - 버그, 실제 사용자 docx 재현으로 발견] "M-P 2/p Landscape에서
        # legend box가 왼쪽 axis 경계를 넘어 tic 숫자/Y1 title과 겹침" - 원인
        # 확인: box_w(axis 폭 대비 legend 필요 폭 비율)가 큰 폰트(예:
        # multiplot에서 칸이 커서 font_panel_scale이 큰 경우) + 좁은 축이
        # 겹치면 1.0을 훌쩍 넘을 수 있음(실측: 1.56, 156%) - 위 경고는 이
        # 사실을 알려주기만 할 뿐 실제 렌더링 크기는 그대로 안 잘라서, box가
        # anchor(ax) 기준 반대쪽으로 axis 밖까지 밀려나가 tic 숫자 자리를
        # 침범했음. anchor 위치 기준으로 axis 경계(graph 0~1)를 넘지 않도록
        # box_w 자체를 축소한다(경고는 위에서 이미 실제 필요 크기 기준으로
        # 떴으므로 그대로 두고, 그리기에만 안전한 값을 쓴다).
        _box_w_before_clamp = box_w
        if "right" in corner:
            box_w = min(box_w, max(ax - 0.02, 0.3))
        elif "left" in corner:
            box_w = min(box_w, max(1.0 - ax - 0.02, 0.3))
        else:
            box_w = min(box_w, max(2 * min(ax, 1.0 - ax) - 0.04, 0.3))

        if "right" in corner:
            box_right, box_left = ax, ax - box_w
        elif "left" in corner:
            box_left, box_right = ax, ax + box_w
        else:
            box_left, box_right = ax - box_w / 2, ax + box_w / 2

        # [수정 - 버그] 위 box_w와 같은 이유로 box_h(세로)도 axis 경계를
        # 넘지 않도록 clamp한다(가로만 넘치는 경우가 대부분이었지만 방어적으로).
        # box_h를 줄이면 그 안의 줄 간격(ROW_H/ROW_MARGIN)도 같이 다시
        # 나눠야 실제로 그 안에 고르게 들어간다(안 그러면 clamp 전 크기
        # 기준으로 배치된 줄들이 줄어든 box 밖으로 삐져나옴) - box_h_override
        # 분기와 동일한 방식으로 재계산한다.
        _box_h_before_clamp = box_h
        if "top" in corner:
            box_h = min(box_h, max(ay - 0.02, 0.2))
        elif "bottom" in corner:
            box_h = min(box_h, max(1.0 - ay - 0.02, 0.2))
        else:
            box_h = min(box_h, max(2 * min(ay, 1.0 - ay) - 0.04, 0.2))
        if box_h < _box_h_before_clamp:
            n_rows = max(len(curves), 1)
            ROW_H = box_h / (n_rows + 2 * _row_margin_ratio)
            ROW_MARGIN = _row_margin_ratio * ROW_H

        # [수정 - 버그] "box_w/h를 axis 안으로 눌러 넣었더니 글자가 box 테두리를
        # 살짔 넘어 curve 쪽으로 삐져나옴(4/p Portrait 등)" - box는 줄였는데
        # 그 안의 글자 크기(font_pt)는 원래(clamp 전) 필요했던 더 넓은 폭
        # 기준 그대로라 안 맞음. box_w/h가 clamp로 줄어든 비율만큼 legend
        # 텍스트 폰트도 같이 줄여서(단, box 테두리·샘플선·줄간격 등 나머지
        # 기하는 그대로 둠 - single-plot에서 이미 검증된 "필요하면 폰트부터
        # 줄인다" 방식을 참고) 글자가 다시 box 안에 들어가게 한다.
        _legend_font_shrink = min(
            box_w / _box_w_before_clamp if _box_w_before_clamp > 0 else 1.0,
            box_h / _box_h_before_clamp if _box_h_before_clamp > 0 else 1.0,
            1.0,
        )
        _label_font_pt = font_pt * _legend_font_shrink

        if "top" in corner:
            box_top, box_bottom = ay, ay - box_h
        elif "bottom" in corner:
            box_bottom, box_top = ay, ay + box_h
        else:
            box_bottom, box_top = ay - box_h / 2, ay + box_h / 2

        if box_on:
            lines.append(
                f"set object {id_offset} rect from graph {box_left:.4f},{box_bottom:.4f} "
                f"to graph {box_right:.4f},{box_top:.4f} "
                f"fc rgb 'white' fs solid 1.0 border lc rgb 'black' lw {thick_val} front"
            )

        for row_i, curve in enumerate(curves):
            row_y = box_top - ROW_MARGIN - ROW_H * (row_i + 0.5)
            if is_right_side:
                sample_x2 = box_right - BOX_EDGE_GAP_FRAC
                sample_x1 = sample_x2 - SAMPLE_W
                label_x = sample_x1 - LABEL_GAP_FRAC
                label_just = "right"
            else:
                sample_x1 = box_left + BOX_EDGE_GAP_FRAC
                sample_x2 = sample_x1 + SAMPLE_W
                label_x = sample_x2 + LABEL_GAP_FRAC
                label_just = "left"

            idx = curve_index_map.get(id(curve), row_i)
            color = curve.color or DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]
            linestyle = curve.linestyle or DEFAULT_LINESTYLES[idx % len(DEFAULT_LINESTYLES)]
            lw2 = curve.linewidth * line_scale
            _dash_pat = _dash_pattern_for_fmt(linestyle, fmt)
            dt_clause = f" dashtype ({_dash_pat})" if _dash_pat else ""
            lines.append(
                f"set arrow {id_offset + row_i + 1} from graph {sample_x1:.4f},{row_y:.4f} "
                f"to graph {sample_x2:.4f},{row_y:.4f} nohead front "
                f"lc rgb \"{color}\" lw {lw2}{dt_clause}"
            )
            # [추가] 마커가 설정된 curve는 샘플선 중앙에 마커 모양(유니코드 기호)을
            # 같이 찍어서, legend만 보고도 이 curve에 마커가 있는지 알 수 있게 함
            marker_shape = getattr(curve, "marker_shape", None)
            if marker_shape in MARKER_SYMBOL_MAP:
                sample_mid_x = (sample_x1 + sample_x2) / 2
                # [수정] "center" 정렬은 폰트의 cap-height 기준 중심에 맞추는데,
                # 세모(△▲▽▼) 같은 기호는 실제 잉크(도형)의 무게중심이 위/아래로
                # 치우쳐 있어서 그 기준으로는 샘플선 대비 위 또는 아래로 치우쳐
                # 보이는 문제가 있었음(위쪽 세모는 위로, 아래쪽 세모는 아래로) -
                # 기호별로 작은 보정치를 둬서 샘플선에 시각적으로 맞춘다.
                # [추가] 화면(Interactive, windows 터미널)은 pngcairo와 텍스트
                # 기준선 방향이 달라서, 위 보정치(pngcairo 기준)를 그대로 쓰면
                # 세모가 반대로 어긋남(실측: 위쪽 세모가 화면에서는 오히려
                # 아래로, 아래쪽 세모는 위로) - 화면에서는 세모류만 부호를
                # 반대로 둔 MARKER_Y_OFFSET_SCREEN을 쓰고, 나머지 기호는
                # 공통으로 위로 0.12만큼 보정한다.
                if is_print_mode:
                    _marker_offset = MARKER_Y_OFFSET.get(marker_shape, 0.0)
                else:
                    _marker_offset = MARKER_Y_OFFSET_SCREEN.get(marker_shape, 0.0) + 0.12
                symbol_y = row_y + _marker_offset * ROW_H
                # [추가] 유니코드 기호마다 글자 em-box 안에 그려지는 잉크 크기가
                # 서로 달라서(예: "+"는 원/사각형보다 훨씬 작고 얇게 그려짐),
                # 같은 font_pt로 찍어도 시각적 크기가 들쭥날쭥해 보이는 문제 -
                # 기호별 배율을 둬서 시각적 크기를 서로 맞춘다.
                symbol_pt = _label_font_pt * MARKER_SIZE_SCALE.get(marker_shape, 1.0)
                lines.append(
                    f'set label {id_offset + 5000 + row_i + 1} "{MARKER_SYMBOL_MAP[marker_shape]}" '
                    f'at graph {sample_mid_x:.4f},{symbol_y:.4f} center front '
                    f'font "{font_name},{int(round(symbol_pt))}" textcolor rgb "{color}"'
                )
            lbl_text, lbl_enh = self._render_text(curve.title)
            lines.append(
                f'set label {id_offset + row_i + 1} "{lbl_text}" at graph {label_x:.4f},{row_y:.4f} '
                f'{label_just} front font "{font_name},{max(int(_label_font_pt), 5)}" {lbl_enh}'
            )

    @staticmethod
    def _compute_f_scale(plotdef, panel_scale, fmt):
        """[추가 - 버그 수정] "Axis Frame W=10cm로 지정해도 실제 축 크기가 그보다
        훨씬 작게 나옴(예: 8.7cm)" - 실측(PDF의 lmargin/rmargin at screen 값과
        전체 캔버스 크기를 직접 비교)으로 확인: create_script가 "축+여백=전체
        캔버스" 크기를 계산할 때는 _compute_manual_margins_in에 panel_scale만
        (예: 1.0) 넘겼는데, 실제 그 여백을 "화면 비율"로 그리는 _build_plot_
        commands 안에서는 여기(f_scale, 예: 1.6)로 다시 계산해서 - 두 곳이
        서로 다른 스케일로 같은 여백을 계산하는 불일치가 있었음. 그래서 실제
        여백이 "전체 캔버스 계산에 쓴 여백"보다 커져서, 그만큼 축이 지정한
        크기보다 작아짐. 두 호출부(create_script/_build_plot_commands)가
        항상 같은 값을 쓰도록 이 계산을 한 곳으로 모은다."""
        if getattr(plotdef, "is_print_mode", False):
            f_scale = PRINT_FONT_SCALE * (panel_scale or 1.0)
            if (fmt or "").lower() == "emf":
                # [수정 - 근본 원인 재확인] 이 함수(_compute_f_scale)는 오직
                # single-plot margin 계산에만 쓰이므로(멀티플롯은 별도 경로,
                # font_panel_scale 쪽에서 이미 처리) 중복 적용 위험이 없음 -
                # _build_plot_commands와 동일하게 SP_EMF_FONT_RENDER_FIX로 통일
                # (M-P와 공유하는 EMF_FONT_RENDER_FIX는 건드리지 않음).
                f_scale *= SP_EMF_FONT_RENDER_FIX
            elif (fmt or "").lower() in ("pdf", "png", "jpg", "jpeg"):
                # [수정 - 요청] "single-plot도 M-P처럼 축소된 title 기준으로
                # margin 바닥값을 같이 줄여달라" - 이 함수는 오직 margin
                # 계산(_compute_manual_margins_in) 한 곳에만 쓰이므로(위
                # 독스트링 참고), 여기 f_scale은 사실상 "margin 전용
                # f_scale"이다. 폰트 자체(실제 title/label 크기, EMF/SVG와
                # 맞추는 CAIRO_FONT_RENDER_FIX 전체 1.5배)는 그대로 두고,
                # margin만 절반(제곱근, 약 1.22배)만 반영해 여백을 줄인다.
                # [수정 - 버그] title/xlabel/ylabel/y2label 중 하나라도 2줄
                # 이상("|" 포함)이면 원래도 여백이 빠듯한 경우라, 이 축소를
                # 적용하면 실제로 텍스트가 캔버스 밖으로 잘림(실측 확인: 2줄
                # y2label의 둘째 줄이 페이지 밖으로 6pt 정도 나감) - 2줄 이상인
                # 라벨이 하나라도 있으면 이 축소를 건너뛰고 기존 전체 배율을
                # 그대로 쓴다(1줄만 있는, 가장 흔한 경우에만 안전하게 축소).
                _any_multiline = any(
                    "|" in (getattr(plotdef, attr, "") or "")
                    for attr in ("title", "xlabel", "ylabel", "y2label")
                )
                if not _any_multiline:
                    f_scale *= CAIRO_FONT_RENDER_FIX ** 0.5
                else:
                    f_scale *= CAIRO_FONT_RENDER_FIX
            elif (fmt or "").lower() == "svg":
                # [추가 - 방향 전환] "EMF뿐 아니라 SVG도 PDF 대비 상대적으로
                # 크게 나온다" - 실측(lfHeight/XML font-size 직접 비교) 결과
                # SVG가 PDF보다 1.125배 크게 나옴을 확인, EMF와 동일한 방식으로
                # SP_SVG_FONT_RENDER_FIX(1/1.125)를 곱해 PDF 수준으로 줄인다.
                f_scale *= SP_SVG_FONT_RENDER_FIX
        else:
            f_scale = SCREEN_FONT_SCALE * (panel_scale or 1.0)
        return f_scale

    def _build_plot_commands(self, plotdef, lines, is_multiplot=False, annotations=None, arrows=None, circles=None, panel_scale=1.0, axis_w_in=None, axis_h_in=None, fmt=None, legend_scale_boost=1.0, legend_width_extra_chars=None, frame_auto=None, ylabel_margin_ratio=1.0, y2label_margin_ratio=1.0, title_margin_ratio=1.0, xlabel_margin_ratio=1.0):
        # [추가] Interactive(화면) 창은 frame_auto/frame_width와 무관하게 항상
        # 고정된 1000x700 캔버스로 뜬다(_get_terminal_cmd 참고) - 그런데 아래
        # 절대 여백 보정(축소 시 title/label이 사라지는 것 방지 등)은 "캔버스가
        # 실제로 frame_width/height 물리 크기와 같다"고 가정하고 계산해서,
        # Axis Frame Auto를 끄고 작은 크기(예: 10x8cm)를 입력한 채 화면(PLOT)을
        # 띄우면 실제 캔버스(약 5.95x4.17in)보다 훨씬 작은 크기를 기준으로 여백
        # 비율을 구해 화면에서 마진이 과도하게 커지는 문제가 있었음(실측 확인) -
        # Interactive는 이 보정 자체를 건너뛰어 기존(이미 적절히 튜닝된) 화면
        # 여백 비율을 그대로 쓰게 한다.
        _is_interactive = (fmt or "").lower() == "interactive"
        # [추가] Auto(frame_auto) + Print/Save에서 legend box 폭/높이 추정에 쓰는
        # "축 실제 물리 크기" 계산이 항상 Interactive 캔버스(1000x700px, 약
        # 5.95x4.17in) 기준을 썼는데, pngcairo/pdfcairo(Auto 기본 크기
        # 11.7x8.3in, _get_terminal_cmd의 size_clause 기본값과 동일)는 실제로
        # 거의 2배 넓은 캔버스를 쓰고 있어서 legend box가 실제보다 훨씬
        # 크게(약 2배) 계산되는 문제가 있었음("screen은 괜찮은데 PNG/PDF만
        # legend가 과도하게 크다" 피드백, 실측 이미지로 확인) - inch 단위
        # 캔버스를 그대로 쓰는 포맷(png/pdf/eps)은 그 실제 크기를 쓴다.
        # EMF/jpg/svg/windows는 자체 픽셀 계수(_get_terminal_cmd의
        # size_clause_px)로 이미 따로 맞춰져 있어(EMF는 문제 제기가 없었음)
        # 여기서는 그대로 둔다.
        _AUTO_INCH_CANVAS = {"png": (11.7, 8.3), "pdf": (11.7, 8.3), "eps": (11.7, 8.3)}
        _auto_canvas_in = _AUTO_INCH_CANVAS.get((fmt or "").lower())

        if getattr(plotdef, "is_print_mode", False):
            f_scale = PRINT_FONT_SCALE * panel_scale
            line_scale = PRINT_LINE_SCALE * panel_scale
            border_scale = PRINT_BORDER_SCALE * panel_scale
            # [삭제] "PNG는 폰트가 크게 보임" 대응으로 넣었던 PNG 전용 0.8배 축소 -
            # PNG/JPG가 이제 PDF를 그대로 래스터화해서 만들어지므로(fmt='png'로
            # 이 함수까지 오지 않고 create_script 단계에서 이미 'pdf'로 바뀜)
            # 여기 도달할 일이 없는 죽은 코드가 됨. 혼동 방지로 제거.
            # [추가 - 근본 원인 수정] gnuplot pdfcairo 터미널이 지정한 폰트
            # 크기를 실제로는 항상 정확히 2/3만 PDF에 기록한다는 사실을
            # 최소 재현 스크립트(코드와 무관)로 확인함 - title/xlabel/tic/
            # legend 전부 동일 비율로 축소되는 걸 PyMuPDF span.size로 직접
            # 측정 확인. f_scale 자체에 그 역수(1.5)를 곱해두면, f_scale에
            # 비례하는 모든 것(font_pt는 물론, margin 여유값도 전부 f_scale에
            # 비례하는 식이라 - _compute_manual_margins_in/멀티플롯 margin
            # floor 참고) 같이 커져서 별도로 margin을 하나하나 다시 맞출
            # 필요가 없다(실제 렌더링 크기가 커지는 만큼 필요 여백도 그
            # 비율만큼 커지는 게 정확히 맞는 방향). PNG/JPG(fmt='png'가
            # 단일 plot에서는 위 주석대로 'pdf'로 이미 바뀌어 들어오지만,
            # 멀티플롯은 fmt='png' 그대로 들어오므로 둘 다 명시).
            # EMF/SVG는 이 축소가 없어(별도 확인) 대상에서 제외.
            # [주의 - 중복 적용 방지] 멀티플롯(is_multiplot=True) 호출은
            # panel_scale 자체(=font_panel_scale)가 create_multiplot_script
            # 쪽에서 이미 이 보정을 적용한 채로 넘어오므로(margin_left/right/
            # top/bottom도 그 보정된 값 기준으로 계산돼야 하기 때문 - 위
            # font_panel_scale 주석 참고), 여기서 또 곱하면 1.5배가 두 번
            # 걸려버림. 단일 plot(create_script, is_multiplot=False)만 여기서
            # 적용한다.
            _margin_cairo_boost = 1.0
            if not is_multiplot and (fmt or "").lower() in ("pdf", "png", "jpg", "jpeg"):
                _margin_cairo_boost = CAIRO_FONT_RENDER_FIX
                f_scale *= CAIRO_FONT_RENDER_FIX
            # [수정 - 근본 원인, cairo와 동일 패턴으로 재구현] 실측(20pt에서
            # EMF가 PNG의 84.7%, 40pt에서 74.5%)으로 기존 0.75(축소)는 방향이
            # 틀렸고 EMF_FONT_RENDER_FIX(1.8, 확대)가 맞음을 확인. 처음엔
            # 여기서만 1.8을 곱해서 멀티플롯에서 tic/legend가 margin을 침범하는
            # 회귀가 났었는데(margin 계산이 이 배율을 모름), cairo와 똑같이
            # "멀티플롯은 caller(create_multiplot_script)가 font_panel_scale에
            # 이미 반영해서 넘겨주므로 여기서 또 곱하면 중복" 패턴을 EMF에도
            # 적용해서 해결한다 - 단일 plot만 여기서 적용.
            if not is_multiplot and (fmt or "").lower() == "emf":
                f_scale *= SP_EMF_FONT_RENDER_FIX
            # [추가 - 방향 전환] EMF와 같은 이유로 SVG도 단일 plot에서만
            # SP_SVG_FONT_RENDER_FIX(1/1.125)를 적용 - 멀티플롯은 caller가
            # font_panel_scale에 이미 반영해서 넘기므로 여기서 또 곱하면 중복.
            if not is_multiplot and (fmt or "").lower() == "svg":
                f_scale *= SP_SVG_FONT_RENDER_FIX
        else:
            f_scale = SCREEN_FONT_SCALE * panel_scale
            line_scale = SCREEN_LINE_SCALE * panel_scale
            border_scale = SCREEN_BORDER_SCALE * panel_scale
            _margin_cairo_boost = 1.0

        # [수정 - 요청] "single-plot도 M-P처럼 축소된 title 기준으로 margin
        # 바닥값을 같이 줄여달라" - single-plot(Auto)은 panel_scale이 항상
        # 1.0이라 M-P의 "칸이 기준보다 큰 경우" 같은 캡핑 여지 자체가 없어서
        # (font/margin이 이미 같은 비율로 같이 커짐 - 서로 어긋나는 버그가
        # 없음), M-P와 동일한 방식은 그대로 적용할 게 없음. 대신 margin
        # 계산에서만 cairo 보정을 완전히(1.5배) 다 반영하지 않고 절반만
        # (제곱근, 약 1.22배) 반영해서 margin_left/right/top/bottom을 줄인다
        # (폰트 자체 크기는 f_scale 그대로 유지 - EMF/SVG와 계속 같은 절대
        # 크기). 실제 렌더링해서 title/xlabel/ylabel이 잘리지 않는지 직접
        # 확인 후 안전한 값으로 확정함.
        # [수정 - 버그] title/xlabel/ylabel/y2label 중 2줄 이상("|" 포함)이
        # 있으면 원래도 여백이 빠듯해서 이 축소를 적용하면 실측상 텍스트가
        # 캔버스 밖으로 잘림(2줄 y2label 둘째 줄이 페이지 밖 6pt 정도로
        # 나가는 것 확인) - 그 경우엔 축소하지 않는다(_compute_f_scale의
        # 동일 가드와 일관되게).
        _any_multiline_margin = any(
            "|" in (getattr(plotdef, attr, "") or "")
            for attr in ("title", "xlabel", "ylabel", "y2label")
        )
        if _margin_cairo_boost and not _any_multiline_margin:
            _margin_f_scale = f_scale / _margin_cairo_boost * (_margin_cairo_boost ** 0.5)
        else:
            _margin_f_scale = f_scale

        # [수정 - 요청] "M-P Auto의 Plot Title/X title/Y1 title/Y2 title 폰트가
        # single-plot보다 확연히 커 보임(1p는 59%, 2p는 29% 더 크게 실측됨)" -
        # single-plot과 "거의 동일하게(완전 고정)"으로 맞춰달라는 요청. M-P
        # Auto가 칸(cell)이 기준(10x8cm)보다 큰 경우 font_panel_scale이
        # sqrt로 완화는 되지만 여전히 1.0을 넘게(예: 1p는 1.62) 커지는데,
        # tic/legend/margin은 이 완화된 값을 그대로 써야 하는 반면(안 그러면
        # 여백이 부족해짐) title/xlabel/ylabel/y2label 네 가지만 별도로
        # panel_scale을 1.0로 상한을 둬서(=single-plot의 항상-1.0 방식과
        # 동일) 계산한다.
        # [수정 - 버그] 멀티플롯의 panel_scale(=font_panel_scale)은 "칸 크기에
        # 따른 완화된 배율"과 "CAIRO_FONT_RENDER_FIX(pdf/png 전용 1.5배)"가
        # 이미 곱해져 하나로 합쳐진 값이라, 단순히 min(panel_scale, 1.0)로
        # 자르면 칸 크기 배율뿐 아니라 cairo 보정까지 같이 잘려나가 PDF/PNG
        # M-P의 title이 EMF/SVG보다 다시 작아지는 회귀가 생김(실측: PDF
        # title이 22, EMF/SVG는 16이어야 할 자리에 서로 안 맞음) - 멀티플롯
        # cairo 보정 배율만 별도로 구해서 상한을 적용한 뒤 다시 곱해준다
        # (EMF/SVG는 이 배율이 1.0이라 기존과 동일).
        _title_cairo_mult = CAIRO_FONT_RENDER_FIX if (is_multiplot and (fmt or "").lower() in ("pdf", "png", "jpg", "jpeg")) else 1.0
        # [주의 - 시도했다가 되돌림] "1/p Manual 40x30cm처럼 기준(10x8cm)보다
        # 훨씬 큰 Manual 크기에서 title이 tic/legend 대비 작게 나옴"을 고치려고
        # Manual일 때 이 상한을 없애봤으나, f_scale 자체가 tic 등 다른 요소용
        # 배율(cairo 보정 등 여러 배수가 이미 곱해진 큰 값)이라 title에 그대로
        # 적용하면 title이 화면을 다 덮을 정도로 폭주함(실측: 40x30cm에서
        # title 126pt, 렌더링 결과 title이 plot 전체를 가림 - 원래(33pt, 작음)
        # 보다 훨씬 심각한 회귀). 상한을 없애는 대신 완화(sqrt 등) 계수가
        # 필요한데 안전하게 확정할 시간이 없어 일단 원래(항상 상한 1.0) 동작
        # 으로 되돌림 - Manual 극단 크기에서 title이 작게 보이는 문제는
        # 미해결 상태로 남겨둠(별도 검토 필요).
        if is_multiplot:
            _title_panel_scale = min(panel_scale / _title_cairo_mult, 1.0) * _title_cairo_mult
        else:
            _title_panel_scale = panel_scale
        _title_f_scale = f_scale * (_title_panel_scale / panel_scale) if panel_scale else f_scale

        # [추가 - 후속 작업] "M-P의 EMF/SVG 폰트-비율도 같은 방식으로 재보정" -
        # MP_EMF_FONT_RENDER_FIX/MP_SVG_FONT_RENDER_FIX 참고. f_scale/_title_
        # f_scale 자체(margin-need 계산에도 쓰임)는 그대로 두고, 실제로 gnuplot에
        # 보내는 최종 pt 숫자(아래 tic_size/title_size 등, _render_legend_box에
        # 넘기는 f_scale)에만 곱해 "커지지 않고 그대로거나 작아지기만" 하게 한다.
        _mp_font_fix = 1.0
        if is_multiplot:
            _fmt_l_for_fix = (fmt or "").lower()
            if _fmt_l_for_fix == "emf":
                _mp_font_fix = MP_EMF_FONT_RENDER_FIX
            elif _fmt_l_for_fix == "svg":
                _mp_font_fix = MP_SVG_FONT_RENDER_FIX

        uses_y2_for_log = any(getattr(curve, "axis", "y1") == "y2" for curve in plotdef.curves)
        # [수정] gnuplot은 "비선형(log) 축은 link를 풀기 전에 먼저 선형으로
        # 되돌려야 한다"고 요구함 (에러: "you must clear nonlinear x2 or y2
        # before linking it") - 그런데 기존엔 set logscale y2를 먼저 실행하고
        # unset link y2를 나중에 해서 이 에러로 크래시하고 있었음. Y2를 실제로
        # 쓰면 link 자체가 필요 없으니, log 설정보다 먼저 링크를 해제한다.
        if uses_y2_for_log:
            lines.append("unset link y2")

        if getattr(plotdef, "xlog", False):
            lines.append("set logscale x")
        if getattr(plotdef, "y1log", False):
            lines.append("set logscale y")
        if getattr(plotdef, "y2log", False):
            lines.append("set logscale y2")
        elif not uses_y2_for_log and getattr(plotdef, "y1log", False):
            # [수정] Y2가 미사용이면 'set link y2'로 Y1 범위에 연동되는데, Y1이
            # log인데 Y2는 log가 아니면 연동된 두 축의 스케일이 안 맞아 gnuplot이
            # 조용히 실패(plot 창이 아예 안 뜸)하는 문제가 있었음 - Y2도 같이
            # log로 맞춰준다
            lines.append("set logscale y2")

        if plotdef.xauto:
            nice_x = self._nice_axis_range(plotdef, "x", is_log=getattr(plotdef, "xlog", False))
            if nice_x:
                xmin, xmax, _ = nice_x
                lines.append(f"set xrange [{self._format_number(xmin)}:{self._format_number(xmax)}]")
                shared_x_range = (xmin, xmax)
            else:
                lines.append("set autoscale x")
                shared_x_range = None
        else:
            _xmin, _xmax = self._safe_manual_range(plotdef.xmin, plotdef.xmax, getattr(plotdef, "xlog", False))
            lines.append(f"set xrange [{_xmin}:{_xmax}]")
            try:
                shared_x_range = (float(_xmin), float(_xmax))
            except (ValueError, TypeError):
                shared_x_range = None

        y1_auto_tics = ""
        # [추가] "tic 숫자에 소수점/음수가 있으면 여백도 그만큼 넓어야 하지
        # 않나?" - 맞는 지적(margin 계산이 Scientific/Power10 형식만 챙기고
        # 일반 형식의 소수점·음수 폭은 전혀 반영 안 하고 있었음). 아래에서
        # 실제로 결정된 min/max/tic-step을 담아둬서, 마진 계산 시점에 실제
        # tic 숫자들의 최대 글자수를 추정할 수 있게 한다.
        _y1_min_val = _y1_max_val = _y1_step_val = None
        if plotdef.yauto:
            nice_y1 = self._nice_axis_range(plotdef, "y1", is_log=getattr(plotdef, "y1log", False))
            if nice_y1:
                ymin, ymax, y1_auto_tics = nice_y1
                lines.append(f"set yrange [{self._format_number(ymin)}:{self._format_number(ymax)}]")
                _y1_min_val, _y1_max_val, _y1_step_val = ymin, ymax, y1_auto_tics
            else:
                lines.append("set autoscale y")
        else:
            _ymin, _ymax = self._safe_manual_range(plotdef.ymin, plotdef.ymax, getattr(plotdef, "y1log", False))
            lines.append(f"set yrange [{_ymin}:{_ymax}]")
            _y1_min_val, _y1_max_val = _ymin, _ymax
        if plotdef.ytics:
            _y1_step_val = plotdef.ytics

        uses_y2 = uses_y2_for_log

        y2_auto_tics = ""
        _y2_min_val = _y2_max_val = _y2_step_val = None
        if uses_y2 and not getattr(plotdef, "y2auto", True):
            _y2min, _y2max = self._safe_manual_range(plotdef.y2min, plotdef.y2max, getattr(plotdef, "y2log", False))
            lines.append(f"set y2range [{_y2min}:{_y2max}]")
            _y2_min_val, _y2_max_val = _y2min, _y2max
        elif uses_y2:
            nice_y2 = self._nice_axis_range(plotdef, "y2", is_log=getattr(plotdef, "y2log", False))
            if nice_y2:
                y2min, y2max, y2_auto_tics = nice_y2
                lines.append(f"set y2range [{self._format_number(y2min)}:{self._format_number(y2max)}]")
                _y2_min_val, _y2_max_val, _y2_step_val = y2min, y2max, y2_auto_tics
            else:
                lines.append("set autoscale y2")
        else:
            lines.append("set link y2")
        if uses_y2 and plotdef.y2tics:
            _y2_step_val = plotdef.y2tics

        lines.append(f"set xtics {plotdef.xtics if plotdef.xtics else 'auto'}")

        def _tic_fmt_clause(fmt_label, is_log=False):
            if fmt_label == "Scientific":
                return "%.1e"
            elif fmt_label == "Power10":
                # [수정] "10^{%L}"의 %L(로그 특성값)은 log축 tic 값 기준으로만
                # 의미가 있음 - 이걸 선형(linear) 축에 그대로 쓰면, 같은 자릿수
                # 구간(예: 250~350)의 tic들이 전부 log10(v)를 내림한 같은 정수로
                # 뭉개져서 "10^2"가 계속 반복되는(실제 값과 무관하게 똑같이
                # 보이는) 문제가 있었음 - log축이 아니면 Scientific과 동일하게
                # 처리한다(실제 값이 tic마다 구분되게 보이도록).
                return "10^{%L}" if is_log else "%.1e"
            return None  # Normal - 별도 지정 안 함(기본 표시)

        _xfmt = _tic_fmt_clause(getattr(plotdef, "xfmt", "Normal"), getattr(plotdef, "xlog", False))
        if _xfmt:
            lines.append(f'set format x "{_xfmt}"')

        # Log scale 축은 자동 계산된 선형 tic 간격(예: '5')을 그대로 쓰면 10의
        # 거듭제곱이 아닌 이상한 위치에 눈금이 찍히므로, 사용자가 Tics를 직접
        # 입력하지 않았다면 log에서는 'auto'(gnuplot이 알아서 10^n 배치)를 사용
        if plotdef.ytics:
            lines.append(f"set ytics {plotdef.ytics}")
        elif getattr(plotdef, "y1log", False):
            lines.append("set ytics auto")
        elif y1_auto_tics:
            lines.append(f"set ytics {self._format_number(y1_auto_tics)}")
        else:
            lines.append("set ytics auto")
        _y1fmt = _tic_fmt_clause(getattr(plotdef, "y1fmt", "Normal"), getattr(plotdef, "y1log", False))
        if _y1fmt:
            lines.append(f'set format y "{_y1fmt}"')
        if uses_y2:
            if plotdef.y2tics:
                lines.append(f"set y2tics {plotdef.y2tics}")
            elif getattr(plotdef, "y2log", False):
                lines.append("set y2tics auto")
            elif y2_auto_tics:
                lines.append(f"set y2tics {self._format_number(y2_auto_tics)}")
            else:
                lines.append("set y2tics auto")
            _y2fmt = _tic_fmt_clause(getattr(plotdef, "y2fmt", "Normal"), getattr(plotdef, "y2log", False))
            if _y2fmt:
                lines.append(f'set format y2 "{_y2fmt}"')
        else:
            # Y2 미사용 시 range는 'set link y2'로 이미 Y1과 연동되지만,
            # tic 간격(step)은 따로 지정 안 하면 gnuplot이 Y2용으로 별도 계산해서
            # Y1과 다른 간격(예: 2배)이 나올 수 있으므로 Y1과 동일한 간격을 명시적으로 지정.
            # [수정] Y1(또는 Y2)이 log면 이 "선형 간격 숫자"를 그대로 y2tics에 쓰면
            # 안 됨(로그축엔 무의미한 값이라 크래시하거나 Y1과 다른 이상한 tic/숫자
            # 표기가 나오던 원인) - log면 auto로 처리한다
            if getattr(plotdef, "y1log", False) or getattr(plotdef, "y2log", False):
                lines.append("set y2tics auto")
            else:
                y1_tic_value = plotdef.ytics if plotdef.ytics else (self._format_number(y1_auto_tics) if y1_auto_tics else None)
                if y1_tic_value:
                    lines.append(f"set y2tics {y1_tic_value}")
                else:
                    lines.append("set y2tics")
            lines.append('set format y2 ""')

        effective_minor_grid = plotdef.minor_grid and getattr(plotdef, "major_grid", True)

        def _minor_tic_clause(tic_name, user_val, is_log, log_default, linear_default):
            """Minor tic 설정 - Log축에서 사용자가 0을 입력해도 계속 보조눈금이
            찍히던 버그 수정: gnuplot은 log축에서 'set Ntics 1'로는 보조눈금이
            사라지지 않고 'unset Ntics'라야 진짜로 없어진다."""
            if user_val:
                if int(user_val) == 0:
                    return f"unset {tic_name}"
                return f"set {tic_name} {int(user_val)+1}"
            if is_log:
                return f"set {tic_name} {log_default}"
            if effective_minor_grid:
                return f"set {tic_name} {linear_default}"
            return f"unset {tic_name}"

        # Log scale 축은 보조눈금(minor tic) 기본을 데케이드당 9개(2,3,4,..,9)로 -
        # gnuplot에서 'set mxtics 10'을 주면 이 형태가 됨. 사용자가 Minor 칸에
        # 직접 값을 입력했으면(plotdef.mxtics 등) 그 값을 그대로 우선 적용한다.
        lines.append(_minor_tic_clause("mxtics", plotdef.mxtics, getattr(plotdef, "xlog", False), 10, 2))
        lines.append(_minor_tic_clause("mytics", plotdef.mytics, getattr(plotdef, "y1log", False), 10, 2))

        if uses_y2:
            lines.append(_minor_tic_clause("my2tics", plotdef.my2tics, getattr(plotdef, "y2log", False), 10, 2))
        else:
            # Y2 미사용 시 보조눈금(minor tic) 개수도 Y1(mytics)과 동일하게 맞춰서
            # Y1만 있을 때와 같은 모양이 되도록 함 (my2tics를 별도로 계산하지 않음)
            lines.append(_minor_tic_clause("my2tics", plotdef.mytics, getattr(plotdef, "y1log", False), 10, 2))

        grid_parts = []
        if getattr(plotdef, "major_grid", True): grid_parts += ["xtics", "ytics"]
        if effective_minor_grid: grid_parts += ["mxtics", "mytics"]

        if grid_parts:
            # [수정 - 발견] grid 선에 dashtype을 명시 안 해서, 터미널 기본값이
            # 서로 달라 EMF(굵은 대시)와 PDF/PNG(촘촘한 점선)가 다르게 보임
            # (버그가 아니라 "명시 안 한 값이 터미널마다 다름" - Print vs Save
            # 재현 비교 중 발견). dashtype을 명시해서 포맷 간 통일한다(오늘
            # 확인한 "dashtype은 콤마 뒤 공백 필요" 규칙 적용).
            lines.append(f"set grid {' '.join(grid_parts)} lw 1.5 dashtype (1, 2), lw 1.0 dashtype (1, 2)")
        else:
            lines.append("unset grid")

        lines.append("set mouse")
        lines.append(f"set border lw {1.5 * border_scale}")

        # [핵심 수정] 이 고정 마진 설정이 is_multiplot 여부와 무관하게 항상 실행되고
        # 있어서, create_multiplot_script가 각 칸(cell)마다 미리 계산해둔 올바른
        # per-cell 마진(set lmargin/rmargin/tmargin/bmargin at screen ...)을 바로
        # 뒤이어 이 코드가 매번 덮어써버리고 있었음 - 그 결과 멀티플롯의 모든
        # subplot이 같은 위치(전체 페이지 크기)에 겹쳐 그려지던 버그의 원인.
        # 멀티플롯일 때는 이 블록을 건너뛰고, create_multiplot_script가 지정한
        # per-cell 마진을 그대로 사용한다.
        if not is_multiplot:
            #if getattr(plotdef, "is_print_mode", False) and not is_multiplot:
            #    lines.append("set lmargin at screen 0.10")
            #    lines.append("set tmargin at screen 0.90")
            #    lines.append("set bmargin at screen 0.12")
            # 화면(Interactive)/저장(Batch) 공통으로 기본 여백을 확보하여
            # Y2 타이틀이나 라벨이 창/이미지 경계에 잘리지 않도록 함
            # [추가] Scientific/Power10 형식은 숫자가 길어져서 기본 여백으로는
            # 부족해 창 밖으로 나가거나 title이 안 보이는 문제가 있었음 - 형식에
            # 따라 여백을 추가로 확보한다
            # [수정] 화면과 용지는 매체가 다르므로 마진을 분리한다 - 화면은
            # 절반으로 줄인 값(여유 있게), 인쇄는 원래(줄이기 전) 값을 사용
            _is_print = getattr(plotdef, "is_print_mode", False)
            # [수정] 화면(1줄 label 기준)에서도 외부 여백이 여전히 조금 크다는
            # 피드백으로, 좌측 여백을 10pt만큼 더 줄임(interactive 캔버스
            # 1000px/168px_per_in=5.952in 기준, 10pt=10/72in -> 약 0.0233 비율).
            # 2줄 label일 때 더해지는 증가분(_lmargin_base += 0.05 등)은 그대로
            # 둬서, 기준값이 줄어든 만큼 2줄 경우도 자연히 비례해서 좁아짐.
            _lmargin_base = 0.15 if _is_print else (0.12 - (10.0 / 72.0) / (1000.0 / 168.0))
            _y1fmt_label = getattr(plotdef, "y1fmt", "Normal")
            if _y1fmt_label == "Scientific": _lmargin_base += 0.07
            elif _y1fmt_label == "Power10": _lmargin_base += 0.03
            # [추가] "tic 숫자에 소수점/음수가 있으면 여백도 넓어야 하지 않나?" -
            # Scientific/Power10만 챙기고 일반 형식의 소수점·음수 폭은 반영이
            # 안 돼 있었음(실제로 Y1/Y2 중 한쪽만 소수점 tic이면 margin은
            # 대칭인데 title이 상대적으로 더 좁아 보이는 원인이었음) - 실제
            # min/max/tic-step으로 결정될 tic 숫자들의 최대 글자수를 추정해서
            # (기준 2자리 대비 초과분) 그만큼 여백을 넓힌다.
            elif _y1fmt_label == "Normal":
                _lmargin_base += 0.012 * self._tic_label_extra_chars(_y1_min_val, _y1_max_val, _y1_step_val)
            # [수정] "전부 2줄"로 겹쳐 테스트하면 네 방향이 동시에 커져 체감상
            # 과하다는 피드백으로, 화면에서는 2줄 증가분을 절반으로 줄임(print는
            # 그대로 유지 - 이미 확인됨)
            # [수정 - 삭제] "2줄 title에서 Y2 tic<->title 간격이 늘어나 좌우
            # 마진 폭이 심하게 달라짐, Y2 마진을 키우지 말 것" - offset 공식은
            # margin 크기와 무관하게 "tic 위치 기준" 간격을 목표로 계산하는데,
            # 여기서 마진을 추가로 키우면 tic 위치 자체가 바뀌어서(border가
            # 같이 밀려나며 tic도 같이 밀려남) 그 목표가 어긋남 - 2줄이어도
            # 세로 길이만 늘 뿐 좌우 폭은 1줄과 같아야 하므로, 이 추가 여백을
            # 제거해 1줄과 동일한 tic 위치를 유지한다(Y1/Y2 대칭).
            # if "|" in (plotdef.ylabel or ""): _lmargin_base += 0.05 if _is_print else 0.025  # Y1 title 2줄 이상이면 여백 추가
            # [추가] Plot Title이 '|'로 2줄 이상이면 상단 여백을 추가로 확보
            # (Multi-Print는 이미 반영되어 있었는데 단일 plot은 빠져 있었음)
            _title_lines = 1 + (plotdef.title or "").count("|")
            # [수정] 화면에서 title과 legend box 사이 간격이 너무 커 보인다는
            # 피드백으로 0.895->0.925로 축소(이전에 30% 늘렸던 것을 다시 되돌리는
            # 정도) - legend 자체 위치(FRAME_MARGIN)는 축 상단 기준이라 안 바뀌고,
            # title이 축에 더 가까워져서 그 사이 간격이 줄어드는 효과. 단, 이
            # 여백은 원래 "Y2 title/label이 창 경계에서 잘리는" 문제 때문에
            # 늘려둔 것이라, 너무 줄이면 그 문제가 재발할 수 있어 화면에서
            # Y2 라벨 잘림 여부도 같이 확인 필요.
            # [추가] title 위쪽 여백을 10pt만큼 다시 더 줌(interactive 캔버스
            # 700px/168px_per_in=4.167in 기준, 10pt=10/72in -> 약 0.0333 비율)
            # [추가] 1줄 title은 여전히 여백이 작다는 피드백으로 화면에서만 다시
            # 5pt 더 늘림(누적 15pt, 처음 요청은 10pt였으나 5pt로 축소 조정됨).
            # 2줄 title은 이미 적절하다고 확인됐으므로, 줄당 감소분(0.09)도 같은
            # 5pt만큼 같이 줄여서 2줄 결과값은 그대로 유지되게 한다(1줄만 커지고
            # 2줄은 안 바뀜).
            _pt_to_frac_v = lambda pt: (pt / 72.0) / (700.0 / 168.0)
            _tmargin_ref = 0.88 if _is_print else (0.925 - _pt_to_frac_v(10.0) - _pt_to_frac_v(5.0))
            _title_line_decrement = 0.09 if _is_print else 0.045  # 화면은 2줄 증가분 절반으로
            _tmargin_base = _tmargin_ref - _title_line_decrement * (_title_lines - 1)
            # [수정] 화면 하단 여백도 10pt만큼 줄임(위 lmargin과 동일한 이유/방식)
            _bmargin_base = 0.12 if _is_print else (0.16 - (10.0 / 72.0) / (700.0 / 168.0))  # X title 아래 마진 0.16으로 재조정
            _xfmt_label = getattr(plotdef, "xfmt", "Normal")
            if _xfmt_label == "Scientific": _bmargin_base += 0.03
            elif _xfmt_label == "Power10": _bmargin_base += 0.015
            if "|" in (plotdef.xlabel or ""): _bmargin_base += 0.09 if _is_print else 0.045  # X title 2줄 이상이면 여백 추가(화면은 절반)
            if _is_print:
                _rmargin_base = 0.85 if uses_y2 else 0.90
            else:
                _rmargin_base = 0.88 if uses_y2 else 0.93
            _y2fmt_label = getattr(plotdef, "y2fmt", "Normal")
            if uses_y2:
                if _y2fmt_label == "Scientific": _rmargin_base -= 0.07
                elif _y2fmt_label == "Power10": _rmargin_base -= 0.03
                elif _y2fmt_label == "Normal":
                    # [추가] Y1과 같은 이유(위 lmargin의 소수점/음수 폭 보정 주석
                    # 참고) - Y2도 같은 방식으로 여백을 넓힌다.
                    _rmargin_base -= 0.012 * self._tic_label_extra_chars(_y2_min_val, _y2_max_val, _y2_step_val)
                # [수정 - 삭제] 위 Y1과 동일한 이유("Y2 마진을 키우지 말 것") -
                # 이 추가 여백을 제거해 1줄과 동일한 tic 위치를 유지한다.
                # if "|" in (plotdef.y2label or ""): _rmargin_base -= 0.05 if _is_print else 0.025  # Y2 title 2줄 이상이면 여백 추가(화면은 절반)

            # [추가] 위 마진들은 전부 "화면 비율(fraction)"이라서, frame_auto를 끄고
            # 작은 물리 크기(예: 10x8cm)를 직접 지정하면 같은 비율이라도 절대
            # 여백(inch)이 줄어든다. gnuplot/pngcairo는 title/xlabel/ylabel이 이
            # 절대 여백에 안 들어가면 clip이 아니라 통째로 안 그리는(사라지는)
            # 것으로 실측 확인됨(예: 10x8cm에서 title/xlabel/ylabel이 전부
            # 사라짐) - 흔히 쓰는 인쇄 크기에서 자주 발생하므로, 프레임이 작을
            # 때만 폰트 크기(f_scale)에 비례한 최소 절대 여백을 보장한다(큰
            # 프레임은 기존 fraction으로 이미 충분해서 영향 없음).
            if not getattr(plotdef, "frame_auto", True) and not _is_interactive:
                try:
                    _fw_in = float((plotdef.frame_width or "").strip() or 0)
                    _fh_in = float((plotdef.frame_height or "").strip() or 0)
                    if (plotdef.frame_unit or "in") == "cm":
                        _fw_in, _fh_in = _fw_in / 2.54, _fh_in / 2.54
                except ValueError:
                    _fw_in, _fh_in = 0, 0
                if _fw_in > 0 and _fh_in > 0:
                    # [수정 - 개념 정정] "Frame(Axis) 크기는 axis 자체의 크기" -
                    # _fw_in/_fh_in(frame_width/height)은 axis 크기이고, 실제
                    # 페이지(터미널) 크기는 axis + 이 마진들을 더한 값이다
                    # (create_script가 _get_terminal_cmd를 호출하기 전에 이미 같은
                    # 계산으로 그 페이지 크기를 정해뒀음 - 반드시 같은 값을 써야
                    # 하므로 _compute_manual_margins_in()을 공유한다). 그래서 여기
                    # 마진은 "axis 크기 대비 fraction"이 아니라 "axis+마진(=페이지)
                    # 대비 fraction"으로 구해야 한다.
                    _need_left_in, _need_right_in, _need_top_in, _need_bottom_in = \
                        self._compute_manual_margins_in(plotdef, _margin_f_scale, _is_print, uses_y2, fmt=fmt)
                    _total_w_in = _fw_in + _need_left_in + _need_right_in
                    _total_h_in = _fh_in + _need_top_in + _need_bottom_in
                    _lmargin_base = _need_left_in / _total_w_in
                    _rmargin_base = 1.0 - _need_right_in / _total_w_in
                    _tmargin_base = 1.0 - _need_top_in / _total_h_in
                    _bmargin_base = _need_bottom_in / _total_h_in

            # Legend box 줄 높이 계산에 쓸 축의 실제 물리적 "높이"(인치) - axis_w_in과
            # 같은 이유로 필요(작은 explicit frame에서 legend 줄 간격이 폰트 크기에
            # 비해 너무 좁아져 줄들이 겹쳐 보이는 문제의 원인이었음)
            if axis_h_in is None:
                try:
                    if not getattr(plotdef, "frame_auto", True) and not _is_interactive:
                        # [수정] frame_height는 이제 axis 크기 그 자체이므로
                        # (fraction과 다시 곱할 필요 없이) 그대로 쓴다.
                        axis_h_in = float((plotdef.frame_height or "4").strip() or 4.0)
                        if (plotdef.frame_unit or "in") == "cm":
                            axis_h_in /= 2.54
                    elif not _is_interactive and _auto_canvas_in is not None:
                        # [추가] axis_w_in과 동일한 이유로 실제 inch 캔버스 높이를 쓴다.
                        axis_h_in = max((_tmargin_base - _bmargin_base) * _auto_canvas_in[1], 0.3)
                    else:
                        _fh_for_legend = 700.0 / 168  # interactive 기본 터미널 높이(700px/168px_per_in)
                        axis_h_in = max((_tmargin_base - _bmargin_base) * _fh_for_legend, 0.3)
                except ValueError:
                    axis_h_in = 4.0
                axis_h_in = max(axis_h_in, 0.3)

            lines.append(f"set lmargin at screen {_lmargin_base}")
            lines.append(f"set tmargin at screen {_tmargin_base}")
            lines.append(f"set bmargin at screen {_bmargin_base}")
            lines.append(f"set rmargin at screen {_rmargin_base}")

        def _pct_to_frac(value, default=0.5):
            try: return float(value) / 100.0
            except (TypeError, ValueError): return default

        # [추가] "% 대신 실제 데이터 좌표값(화면 커서에 보이는 x/y1 값 그대로)을
        # 입력하고 싶다"는 요청으로 행별 coord_mode를 추가했다 - "data"면 gnuplot의
        # "first"(데이터 축 실제 좌표) 시스템을 쓰고, 기존 "pct"(기본값)면 그대로
        # "graph"(0~100% 비율) 시스템을 쓴다. "first"는 y1 축 기준이다(Y2 데이터
        # 값을 쓰려면 추후 별도 축 선택이 필요할 수 있음).
        def _coord_clause(value, coord_mode, default_frac):
            if coord_mode == "data":
                try:
                    return f"first {float(value)}"
                except (TypeError, ValueError):
                    pass
            return f"graph {_pct_to_frac(value, default_frac)}"

        if annotations:
            _ann_font = getattr(plotdef, "legend_font", None) or plotdef.xlabel_font
            _ann_size = int(float(getattr(plotdef, "legend_size", "9") or 9) * f_scale)
            for i, ann in enumerate(annotations):
                ann_text, ann_enh = self._render_text(ann["text"])
                _mode = ann.get("coord_mode", "pct")
                gx = _coord_clause(ann["x"], _mode, 0.5)
                gy = _coord_clause(ann["y"], _mode, 0.5)
                try: angle_val = float(ann.get("angle", "0") or 0)
                except (TypeError, ValueError): angle_val = 0
                rotate_clause = f"rotate by {angle_val}" if angle_val else "norotate"
                # [추가] Comment/Arrow/Circle 각각 행별로 색상을 고를 수 있게 함
                # ("Auto"면 빈 문자열 -> gnuplot 기본색, 그 외엔 lc/textcolor 지정).
                _color = (ann.get("color") or "").strip()
                _color_clause = f' textcolor rgb "{_color}"' if _color else ""
                lines.append(f'set label {i+1} "{ann_text}" at {gx},{gy} {rotate_clause} font "{_ann_font},{_ann_size}"{_color_clause} {ann_enh}')

        if arrows:
            head_map = {"No head": "nohead", "Forward": "head", "Backhead": "backhead", "Both heads": "heads"}
            for i, arr in enumerate(arrows):
                head = head_map.get(arr.get("head", "Forward"), "head")
                _mode = arr.get("coord_mode", "pct")
                gx1 = _coord_clause(arr["x1"], _mode, 0.1)
                gy1 = _coord_clause(arr["y1"], _mode, 0.1)
                gx2 = _coord_clause(arr["x2"], _mode, 0.5)
                gy2 = _coord_clause(arr["y2"], _mode, 0.5)
                _color = (arr.get("color") or "").strip()
                _color_clause = f' lc rgb "{_color}"' if _color else ""
                # [추가] "화살표 크기 옵션(각도는 auto)" - 화살촉 길이는 GUI에서
                # 고른 프리셋(graph 비율, 축 크기와 무관하게 항상 같은 시각적
                # 크기)을, 각도는 15도 고정으로 자동 적용한다.
                _head_size = arr.get("head_size")
                _size_clause = f" size graph {_head_size},15" if _head_size else ""
                lines.append(f'set arrow {i+1} from {gx1},{gy1} to {gx2},{gy2} {head}{_size_clause}{_color_clause}')

        # [수정 - 버그] Circle(ellipse) 렌더링은 axis_w_in/axis_h_in(축 물리
        # 가로세로 비율)이 있어야 Ry 자동보정이 되는데, 이 지점에서는 아직
        # axis_w_in이 None(단일 plot은 한참 아래 "if axis_w_in is None:"
        # 블록에서야 실제 값이 계산됨)이라 항상 예외로 빠져 보정이 조용히
        # 무시되고 있었음("%로 Rx만 넣어도 타원으로 나옴" 실측 확인) - 이
        # 블록 자체를 axis_w_in/axis_h_in이 확정된 뒤로 옮긴다(_render_circles
        # 참고, 아래로 이동).

        tic_size = int(9 * f_scale * _mp_font_fix)
        if getattr(plotdef, "is_print_mode", False):
            tic_major_scale, tic_minor_scale = PRINT_TIC_MAJOR_SCALE, PRINT_TIC_MINOR_SCALE
            # [수정 - 버그] "PNG의 major tic이 EMF 대비 약 2배로 길게 나옴,
            # 2/3로 줄일 것" - 같은 "set tics scale 1.0"이어도 pngcairo가
            # emf(네이티브 GDI)보다 실제 tic 길이를 더 길게 그리는 것으로
            # 보임(사용자 실측 비교) - 직접 SVG(자체 렌더러, XML이라 tic
            # 좌표를 직접 읽을 수 있음) vs PNG(72dpi 원본)를 같은 물리 단위
            # (inch)로 환산해 재확인한 결과도 PNG 쪽이 확연히 더 김(SVG
            # 0.086in vs PNG 0.194in, 약 2.3배) - PDF는 PNG와 같은 cairo
            # 렌더러(pngcairo/pdfcairo)를 쓰므로 같은 문제가 있을 가능성이
            # 높아(PDF는 이 환경에 rasterize 도구가 없어 직접 확인은 못 함)
            # 같이 축소해둔다. EMF/JPG/SVG는 문제 제기가 없어 그대로 둠.
            if (fmt or "").lower() in ("png", "pdf"):
                tic_major_scale *= 2 / 3
                tic_minor_scale *= 2 / 3
            elif (fmt or "").lower() == "svg":
                # [수정] "SVG는 tic 크기도 0.8배로 줄일 것" 요청 후, 실제 GUI Save
                # 재확인 피드백으로 "지금(이미 0.8배 적용된 상태) 대비 또
                # 0.8배로 줄일 것" - 누적 0.8*0.8=0.64배.
                tic_major_scale *= 0.8 * 0.8
                tic_minor_scale *= 0.8 * 0.8
        else:
            tic_major_scale, tic_minor_scale = SCREEN_TIC_MAJOR_SCALE, SCREEN_TIC_MINOR_SCALE
        lines.append(f"set tics scale {tic_major_scale}, {tic_minor_scale}")

        lines.append(f"set xtics font '{plotdef.xlabel_font},{tic_size}'")
        lines.append(f"set ytics font '{plotdef.ylabel_font},{tic_size}'")
        lines.append(f"set y2tics font '{plotdef.y2label_font},{tic_size}'")

        title_size = int(float(plotdef.title_size) * _title_f_scale * _mp_font_fix)
        xlabel_size = int(float(plotdef.xlabel_size) * _title_f_scale * _mp_font_fix)
        # [주의] ylabel_size/y2label_size는 아래 _ylabel_offset/_y2label_offset
        # 보간식(_term_font_pt_ref 대비 비율)의 입력으로도 그대로 쓰이므로 여기서
        # _mp_font_fix를 곱하면 그 튜닝된 비율(offset 공식)까지 같이 틀어짐 -
        # 실제 font 문자열에 넣을 축소된 값은 별도(_ylabel_size_emit/
        # _y2label_size_emit)로 따로 계산해서 offset 계산과 분리한다.
        ylabel_size = int(float(plotdef.ylabel_size) * _title_f_scale)
        y2label_size = int(float(plotdef.y2label_size) * _title_f_scale)
        _ylabel_size_emit = int(round(ylabel_size * _mp_font_fix))
        _y2label_size_emit = int(round(y2label_size * _mp_font_fix))

        title_text, title_enh = self._render_text(plotdef.title)
        # [추가 - 요청] "Auto 4칸 이상 + 다행 레이아웃의 세로 확대"를 켜려면,
        # margin_top이 안쪽 면 축소로 줄어들 때 Plot Title도 ylabel/y2label처럼
        # 그 축소분만큼 축 쪽으로 당겨줘야 함(안 그러면 title이 위 칸의 tic와
        # 겹침) - title은 지금까지 offset 자체가 없어(gnuplot 기본 위치 그대로)
        # ylabel처럼 "기존 offset에 비율을 곱하는" 방식이 아니라, 축소된 비율
        # (1-title_margin_ratio)에 비례해 새로 음수 offset을 만들어 준다(단일
        # plot·margin 안 줄어든 칸은 비율=1.0이라 offset 0, 기존과 동일).
        if is_multiplot and title_margin_ratio < 0.999:
            _title_gap = -1.0 * (1.0 - title_margin_ratio) * _title_f_scale
            lines.append(f'set title "{title_text}" font "{plotdef.title_font},{title_size}" offset 0,{_title_gap:.3f} {title_enh}')
        else:
            lines.append(f'set title "{title_text}" font "{plotdef.title_font},{title_size}" {title_enh}')

        # [수정 - 심각한 버그] "Print/Save에서 X title이 캔버스 맨 아래 경계에
        # 걸쳐서 잘림" - ylabel과 같은 원인(위 ylabel 주석 참고): "at screen"
        # 절대 마진 + 명시적 tic 간격 조합에서 gnuplot의 기본 xlabel 위치가
        # 캔버스 맨 아래 경계에 거의 딱 붙게 나와, 정작 실제 300dpi로
        # 업스케일한 최종 파일에서는(72dpi 미리보기에선 티가 잘 안 남 -
        # 육안으로는 괜찮아 보여서 놓쳤던 부분) 글자 아래쪽이 진짜로 잘려
        # 나감(픽셀 단위로 직접 확인). "offset 0,0.5"만 줘도(위로 살짝
        # 당김) 확실한 여유가 생기는 걸 렌더링 비교로 확인함.
        effective_xlabel = plotdef.xlabel
        xlabel_text, xlabel_enh = self._render_text(effective_xlabel)
        # [수정] "X-title과 tic 사이 간격을 소문자 두께 정도 키워달라" - offset의
        # dy를 늘리면(위로 당김) 캔버스 아래쪽 잘림은 막아주지만 그만큼 tic
        # 숫자와의 간격은 좁아지는 관계라, 요청대로 간격을 늘리려면 반대로
        # dy를 줄여야 함(0.5 -> 0.15, 소문자 두께 정도인 0.35만큼 아래로).
        # [수정 - 버그] "X title이 tic 숫자에 거의 붙어 보임(Manual 큰 크기에서
        # 특히 심함)" - offset 0.15가 고정값이라, 큰 Manual 크기에서 폰트가
        # 커져도(_title_f_scale) 이 간격은 그대로라 상대적으로 거의 안 보이게
        # 됨(실측: 40x30cm에서 xlabel 52pt인데 간격은 여전히 0.15자 몫뿐이라
        # tic 숫자와 거의 붙음) - 폰트가 커지는 배율(_title_f_scale)만큼 이
        # 간격도 같이 키운다(기준 크기에서는 _title_f_scale≈1.0이라 기존
        # 튜닝값과 동일하게 유지됨 - 회귀 없음).
        # [수정 - 근본 원인, 방향이 반대였음] 위 fix가 single-plot EMF에서
        # "Time"이 "400" tic 숫자와 겹치는 새 버그를 유발함 - 직접 렌더링+PIL
        # 측정으로 재확인한 결과 위 주석의 방향 자체가 틀렸었음: offset의 dy를
        # "늘리면" 오히려 tic 쪽(위)으로 당겨져 간격이 좁아지고, "줄이면"(음수
        # 포함) 아래로 밀려 간격이 벌어짐(바로 위 1970년 주석이 원래 맞는
        # 방향이었는데, 이 fix가 그와 반대로 폰트가 커질수록 dy를 "늘려서"
        # 오히려 더 겹치게 만들었음). PDF 10x8/40x30cm, EMF 10x8/30x24cm를
        # 실제로 렌더링해서(gnuplot 직접 호출 + PyMuPDF/PIL 크롭 측정) 새로
        # 잰 결과: cairo(pdf/png/jpg)는 기준 크기(_title_panel_scale=1)에서는
        # 기존 값(0.36)이 이미 안전하고 2배 크기(scale=2)에서만 과함(0.72는
        # 겹침, ~0.10 필요) - EMF는 기준 크기에서부터 이미 겹쳐서(scale=1에서
        # -0.20, scale=2에서 -0.50 필요) cairo보다 훨씬 더 큰 폭으로 아래로
        # 밀어야 함(포맷마다 offset 1칸당 실제 거리가 달라 같은 공식을 못
        # 쓴다는 게 ylabel/y2label의 기존 포맷별 분기와 동일한 이유). 이
        # single-plot 대상 재보정은 M-P(멀티플롯, is_multiplot=True)는 건드리지
        # 않음(멀티플롯은 이미 여러 번 검증된 상태라 "지금 잘되는 M-P는 그대로
        # 두라"는 요청에 따름) - 멀티플롯은 기존 공식 그대로 유지.
        # [수정 - 재확인, 위 "0.36이 기준크기에서 안전"이 틀렸었음] 위 판단은
        # 크롭 이미지를 눈으로만 보고 내린 것이었는데, 실제로 PyMuPDF로
        # "Time" bbox와 tic 숫자 bbox를 좌표로 직접 재보니 0.36에서 -9.9pt
        # 겹침(눈으로는 못 알아챔)이 있었음(사용자 지적으로 재확인). 10x8cm/
        # 40x30cm 둘 다 좌표 기반으로 다시 스윕해서 -1.2로 확정했었음.
        # [수정 - 재보정, CAIRO/EMF_FONT_RENDER_FIX 원복에 따라] 위 -1.2는
        # CAIRO_FONT_RENDER_FIX=1.5가 걸려있던 상태(폰트가 더 큼) 기준이었는데,
        # 그 배율 자체를 없앤 뒤(폰트가 작아짐) 좌표 기반으로 재스윕한 결과
        # 10x8cm는 -0.5, 40x30cm는 -0.3~-0.5 둘 다 충분해서 처음엔 고정값
        # -0.4로 정했었음.
        # [수정 - 재지적, 고정값의 문제] "작은 plot에선 여백이 과하고 큰
        # plot에선 부족하지 않냐"는 지적이 맞음 - 실측(5x4cm, 폰트 5.3pt)
        # 해보니 고정 -0.4가 만드는 간격(6.8pt)이 폰트 크기(5.3pt)보다도 커서
        # 상대적으로 과했음. 폰트 크기(_title_f_scale)에 비례하는 공식으로
        # 바꾼다 - 기준(10x8cm, f_scale=1.6)에서 검증된 -0.4가 나오도록
        # 계수를 역산(-0.4/1.6=-0.25)해서 -0.25*_title_f_scale로 재확정.
        _fmt_l = (fmt or "").lower()
        if not is_multiplot and _fmt_l in ("pdf", "png", "jpg", "jpeg"):
            _xlabel_gap = -0.25 * _title_f_scale
        elif not is_multiplot and _fmt_l == "emf":
            # [수정 - 원칙 정정] "폰트/축 크기에 따라 배율이 달라지면 안 됨 -
            # 항상 같은 비율로 적용돼야 함" - 기존 절편식(-0.20 - 0.30*(scale-1))
            # 은 scale=1.0에서만 -0.20이고 그 외 크기에서는 비례가 아닌 어긋난
            # 값이 나오는 구조라(PDF는 이미 -0.25*_title_f_scale로 순수 비례식
            # 으로 고쳐져 있었는데 EMF만 안 고쳐져 있었음), 같은 기준점(scale=1.0
            # 일 때 -0.20)을 지나는 순수 비례식으로 통일한다.
            _xlabel_gap = -0.20 * (_title_panel_scale or 1.0)
        else:
            _xlabel_gap = 0.15 * _title_f_scale
            # [추가 - 요청] title과 같은 이유(Auto 다행 세로 확대 대비) - margin_bottom이
            # 안쪽 면 축소로 줄어들면 xlabel도 tic 쪽으로 더 당겨줘야 함. 이 gap은
            # 양수일수록 위(tic 쪽)로 당겨지는 방향이라(주석 1984행 참고), 축소
            # 비율(1-xlabel_margin_ratio)만큼 더해서 커지게 한다(줄어든 여백 안에
            # xlabel이 들어가도록).
            if xlabel_margin_ratio < 0.999:
                _xlabel_gap += 1.0 * (1.0 - xlabel_margin_ratio) * _title_f_scale
        lines.append(f'set xlabel "{xlabel_text}" font "{plotdef.xlabel_font},{xlabel_size}" offset 0,{_xlabel_gap:.3f} {xlabel_enh}')

        # [수정 - 심각한 버그] "Manual(frame_auto 꺼짐) + png 저장에서 Y1 title이
        # 통째로 안 보임(잘리는 게 아니라 아예 안 그려짐)" - 실측으로 원인을
        # 새로 확인: 위에서 이미 "set lmargin at screen ..."으로 마진을 절대
        # 위치로 고정해두면, gnuplot(pngcairo)이 ylabel의 기본 자동 위치 계산을
        # 그 고정 마진과 맞물려 캔버스 밖(왼쪽 음수 좌표)으로 밀어버려서 통째로
        # 안 보이게 됨 - margin을 아무리 넉넉히 잡아도(기존 1.6배 안전여유로도)
        # 안 고쳐짐(margin 부족이 원인이 아니었음). 특히 "set ytics <간격>"처럼
        # tic을 명시적 숫자로 지정했을 때(항상 그렇게 함 - 아래 tic 계산 참고)
        # 더 심해져서, offset 1글자로는 부족하고 2글자는 모든 테스트 조합
        # (여러 frame 크기/폰트 크기)에서 안전하게 캔버스 안으로 들어옴을
        # 직접 렌더링 비교로 확인함(Y1은 오른쪽 +, Y2는 왼쪽 -). lmargin/rmargin을
        # "at screen"으로 고정하는 경우(Print/Save 전부)에만 필요하고 부작용도
        # 없어 항상 적용.
        # [수정 - 버그] "emf 파일에 Y1 title이 아예 안 보임" - png(pngcairo, 벡터
        # 렌더러 cairo)에서는 2글자 offset이면 충분했는데, emf(네이티브 GDI
        # 렌더러)는 offset 단위(문자폭)의 기준 폰트가 다른 것으로 보여 2로는
        # 여전히 캔버스 밖에 남고 4는 모든 테스트에서 확실히 들어옴을 직접
        # 렌더링 비교로 확인함 - 터미널(fmt)별로 다른 offset을 쓴다.
        # [수정 - 버그] "Y1 title이 tic에 겹침" - EMF 폰트를 1.5배 키우면서
        # (위 f_scale 참고) 라벨 자체는 커졌는데, 이 offset은 "문자폭" 기준이
        # 라벨 자신의 커진 폰트가 아니라 터미널 기본(고정) 폰트를 기준으로 잡는
        # 것으로 보여(바로 위 2016년~ 주석 참고 - "offset 단위의 기준 폰트가
        # 다르다") 라벨 폰트만 커지고 간격은 그대로라 침범하게 됨. offset 값을
        # 3/6/8/10으로 바꿔가며 직접 렌더링 비교한 결과, 3~6에서는 계속 tic
        # 숫자와 겹치다가 8에서 깨끗이 벗어나고(10은 오히려 curve 쪽을 침범) -
        # 선형으로 조금씩 늘어나는 게 아니라 8 근처에서 갑자기 벗어나는 임계값
        # 형태로 확인됨.
        # [수정 - 버그] "screen plot에서 y1 title이 tic 안쪽으로 들어가고 y2
        # title은 안 보임" - EMF/PDF 등 print 포맷 폰트를 키우면서 8로 올린
        # 값을 실수로 화면(interactive)에도 그대로 적용해버렸음. 화면은
        # 폰트를 키운 적이 없으니 원래 값(2)을 그대로 써야 함 - print 포맷
        # 여부로 분기한다.
        # [수정] "screen plot에서 y1 title은 tic에 너무 붙음" - 화면 원래값(2)을
        # 되돌렸지만 Y1은 그것도 빠듯하다는 재확인 - 화면만 소폭(2->3) 늘림.
        # [수정 - 심각한 버그] "모든 그림에서 y1 title이 frame에 붙어서 tic
        # 숫자와 겹침" - 위에서 8로 고정했던 값은 ylabel_size(입력)=11일 때
        # 기준으로만 맞춰져 있었음. 실측(PyMuPDF, ylabel_size를 11/14/18/22/
        # 28/36으로 바꿔가며 tic 숫자 우측 끝과 title 좌측 끝 간격을 직접
        # 측정)으로 확인: offset의 "문자폭" 단위는 라벨 자신의 폰트가 아니라
        # 터미널 기본폰트(_term_font_pt, panel_scale에만 비례 - _get_terminal_cmd
        # 참고) 기준인데, 라벨 폰트(ylabel_size)는 그와 별도로 f_scale(EMF는
        # 추가 0.75까지) 만큼 더 커질 수 있어서, 라벨이 커질수록 고정 8칸으로는
        # 라벨 자신의 두꺼워진 폭을 못 따라가 결국 겹침(ylabel_size 입력=11
        # 에선 여유+8pt였는데 22 근처부터 역전되어 겹침, 36에선 -11pt).
        # offset(gap 8pt 간격 기준 1칸≈4.04pt, panel_scale=1/오프셋 8~12 구간
        # 실측)과 ylabel_size/_term_font_pt 비율이 선형 관계임을 확인해서
        # 고정값 대신 비율 기반 공식으로 바꿈 - ylabel_size가 커지는 포맷/설정
        # (EMF의 0.75 축소도 ylabel_size 자체에 이미 반영돼 있어 별도 분기 불필요,
        # panel_scale 배율도 비율이라 자동으로 상쇄됨)에서도 항상 비슷한 여유가
        # 남게 됨. 화면(interactive)은 폰트를 키운 적이 없어 기존 값 그대로 둠.
        # [수정 - 근본 오류 발견] "실제 GUI로 저장한 4-curve+Y2 그림(out111)에서
        # title이 커브 한복판까지 밀려 들어와 있음" - 실측(PyMuPDF, 실제
        # out111.dat/4-curve 조합으로 재현)으로 확인: 위에서 목표로 삼았던
        # "tic 숫자 우측 끝 ~ axis border 사이(폭 4pt)"는 틀린 목표였음 - 그
        # 좁은 틈에 라벨을 끼워 넣으려 했던 것 자체가 문제로, 라벨 자신의
        # 두께(폰트 크기에 비례, 예: size=11→약 15pt)가 그 틈(4pt)보다 항상
        # 커서 라벨 오른쪽 절반이 border 안쪽(plot 영역)까지 넘어갈 수밖에
        # 없었음. 원래 있어야 할 자리는 tic 숫자보다도 더 왼쪽(캔버스
        # 왼쪽 끝~tic 숫자 사이의 빈 여백)이라는 걸 재확인 - tic 숫자 "좌측"
        # 끝과 라벨 "우측" 끝 사이 간격을 직접 실측(offset을 -4~2로 바꿔가며
        # 비교)해서 다시 절편/기울기를 구함(size=11→offset≈-0.85,
        # size=36→offset≈-4.92 에서 간격 4pt로 균일). EMF는 별도 검증된
        # 값(Y1=8, Y2=3) 그대로 유지(포맷마다 offset 1칸당 실제 거리가
        # 달라 이 공식을 적용하면 안 됨 - 위에서 확인됨).
        _is_screen = (fmt or "").lower() == "interactive"
        _is_emf = (fmt or "").lower() == "emf"
        # [수정] title_size 등에 위 _title_f_scale(panel_scale 상한 적용)을 쓰게
        # 바뀌었으므로, 이 기준값도 같은 _title_panel_scale로 맞춰야 ylabel_size/
        # _term_font_pt_ref 비율(아래 offset 보간식의 입력)이 어긋나지 않는다.
        # [시도했다가 되돌림 - M-P 3/p 좁은 칸 겹침] 이 바닥값(8)이 원인이라
        # 보고 없애봤으나(1로 낮춤), 실측(PyMuPDF 좌표 비교, 2/p·3/p Manual
        # 6x4cm)해보니 오히려 겹침이 더 심해짐(예: 3/p 겹침 폭 5.46pt->
        # 6.41pt) - ratio가 커지면서 offset이 "+"쪽으로 더 커졌는데(공식이
        # +기울기), y2label은 offset이 커질수록(+) 오히려 옆 칸 쪽으로 더
        # 밀려나는 방향이라(반대는 ylabel) 방향을 잘못 짚었던 것. 원인은
        # 이 바닥값이 아닌 다른 곳에 있으므로 원래 값(8)으로 되돌리고 계속
        # 조사한다.
        _term_font_pt_ref = max(int(round(11 * (_title_panel_scale or 1.0))), 8)
        if _is_screen:
            # [수정 - 버그, 사용자 지적으로 재확인] "screen에서 y1 title이 지금
            # tic 숫자 위에 표시됨 - logic이 이상한 거 아닌지?" - git log로
            # 어젯밤/오늘 오전 "회귀 수정" 커밋(8658297, offset=3)까지 확인했지만
            # 그 값도 실측해보니 겹침이었음: interactive는 실제로 렌더링해서
            # 잴 방법이 없어(대화형 창) pdfcairo를 windows 터미널과 같은 크기
            # (1000x700px≈10.42x7.29in, 같은 기본폰트 11)로 맞춘 대체 렌더로
            # 근사 측정한 결과, offset=3에선 label이 tic 숫자 폭 전체를
            # 덮을 만큼 겹침(gap=-6.1)을 확인 - offset을 낮출수록(0 -> gap
            # +6.1) 겹침이 사라지는, Print 포맷에서 찾은 것과 같은 방향의
            # 문제였음. gap≈4가 되는 지점(약 0.5)으로 낮춤. windows 터미널
            # 자체를 직접 잰 게 아니라 근사치이므로, 실제 화면에서 다시 확인
            # 필요.
            # [수정] "이 기법(비례식)을 screen에도 적용해야 하지 않나 - screen도
            # 사용자 입력 폰트 크기를 참조하지 않나?" - 맞는 지적. screen도
            # SCREEN_FONT_SCALE(=1.0)만 다를 뿐 ylabel_size 입력을 그대로
            # 반영하므로 고정값(0.5)은 Print와 같은 이유로 큰 폰트에서 깨짐.
            # 같은 proxy 렌더로 ylabel_size=36까지 추가 실측(off=-2→gap≈3.9)
            # 해서 Print와 동일한 방식(기준 크기의 gap=4pt 유지, 그 외는 비례)
            # 으로 절편/기울기 재계산.
            _ylabel_offset = 2.612 - 2.112 * (ylabel_size / _term_font_pt_ref)
        elif _is_emf:
            # [수정 - 버그, 실제 out111.dat로 재현] "EMF에서 y1 title이 사라짐/
            # curve에 겹침" - 실제 데이터로 직접 sweep(-15~5)해서 확인: 기존
            # 값(8)은 커브 한복판까지 밀려 들어와 있었고, -4~-1 구간에서는
            # border 왼쪽 여백에 깨끗이 위치함(그 구간 내내 안정적) - 여유
            # 있게 -3으로 설정.
            # [수정] "y1,y2 모두 tic<->title 간격이 너무 큼 - 지금의 반으로
            # 줄일 것" - -1.5로 실측 재확인(여전히 title 정상 출력, -4~-1
            # 안전 구간 안에 있음) 후 확정.
            # [수정] "2줄 EMF는 y1 title 2번째 줄과 tic 숫자 사이를 2/3배로
            # 줄일 것(축 size는 유지)" - 2줄일 때 tic에 더 가까운 쪽은 뒤쪽
            # 줄(2번째 줄)이므로, 이 offset 하나가 그 간격을 결정한다(gnuplot은
            # 여러 줄 라벨 전체를 한 anchor로만 옮기므로 줄 단위로 따로 줄
            # 수는 없음) - 이전 -3->-1.5(반으로) 변경이 실측대로 간격을 절반
            # 으로 줄였던 비율을 그대로 적용해서 -1.5*(2/3)=-1.0으로 조정.
            _ylabel_offset = -1.0
        elif (fmt or "").lower() == "svg":
            # [수정] "2줄 SVG는 y1 title 2번째 줄과 tic 숫자 사이 마진을
            # 1.5배로 늘릴 것(이전과 동일 요청 - 반영 확인)" - 공통 비율식
            # (gap 4pt 기준)에서 SVG만 목표 gap을 6pt(4pt*1.5)로 올린다.
            # offset 1칸당 실제 거리(약 4.05pt, 이 파일의 다른 pt<->offset
            # 환산에서 쓰인 것과 같은 비율)를 그대로 써서 절편만 그만큼
            # (2pt/4.05≈0.494) 낮춘다(더 음수일수록 간격이 커지는 방향).
            _ylabel_offset = (1.874 - 1.763 * (ylabel_size / _term_font_pt_ref)) - 0.494
        else:
            # [수정] "여백이 폰트 크기와 무관하게 4pt 고정인데, 비례해야
            # 되지 않나?" - 맞는 지적. 이전 값은 gap을 모든 크기에서 4pt로
            # 고정하는 것을 목표로 절편/기울기를 구했었음(작은 글씨 옆은
            # 여유 있어 보이고 큰 글씨 옆은 상대적으로 빡빡해 보이는 부작용) -
            # 기준 크기(ylabel_size=11, ratio≈1.545)에서의 gap(4pt)은 그대로
            # 두고, 다른 크기에서는 그 비율(gap ∝ ratio)만큼 커지도록 목표를
            # 다시 잡아서 절편/기울기 재계산(같은 실측 데이터의 offset↔gap
            # 선형관계를 이용해 재계산, size=36→gap 4->13.4pt에 해당하는
            # offset로 재조정).
            _ylabel_offset = 1.874 - 1.763 * (ylabel_size / _term_font_pt_ref)
            # [수정] "2줄 PNG는 tic 숫자<->y1 title 여백을 지금의 1.5배로"
            # - PNG는 PDF를 그대로 래스터화해서 만들기 때문에(create_script의
            # png/jpg 분기 참고, 실제로는 fmt="pdf"로 다시 호출됨) 이 "else"
            # 분기(pdf/jpg/png 공용)를 고쳐야 PNG에도 반영된다. 1줄은 그대로
            # 두고 2줄(ylabel에 "|" 있음)일 때만 늘린다.
            # [주의 - 부호가 1줄과 반대] 1줄에서는 절편을 낮출수록(더 음수)
            # 간격이 커졌지만, 2줄 라벨은 PyMuPDF 실측(out111 실데이터, tic
            # 좌측 끝 ~ 2번째 줄 우측 끝 간격 직접 측정) 결과 오히려 반대
            # 부호로 움직임을 확인함(절편을 낮추면 2번째 줄이 tic 쪽으로
            # 더 가까워져 겹침 발생, 절편을 높여야 멀어짐) - 기준 2줄 간격
            # (5.3pt)을 1.5배(7.95pt)로 만드는 델타(+0.65, 1칸≈4.05pt 실측
            # 재확인)를 그대로 더한다(1줄과 부호가 다른 이유는 다줄 라벨의
            # anchor 기준점이 1줄과 다르기 때문으로 보임 - 정확한 내부 동작은
            # gnuplot 소스 확인 전까지는 실측값으로만 확정).
            if "|" in (plotdef.ylabel or ""):
                _ylabel_offset += 0.65
        # [수정 - 근본 원인, 사용자 지적] "offset 공식이 실제 예약된 margin
        # 값을 몰라서" 여러 회귀가 났던 것 - 위 4가지(_is_screen/_is_emf/svg/
        # else) 분기는 전부 "이 패널이 한 페이지에 혼자 있다"고 가정하고
        # 계산된 값이라, M-P에서 옆 칸과 마진을 나눠 쓰는 안쪽(interior) 칸은
        # 실제 여백이 그보다 작은데도 이 값을 그대로 씀 - 그 결과가 "2/p·4/p
        # 오른쪽 열 Y1 title이 왼쪽 칸의 Y2 title과 겹침"으로 나타남(원인
        # 규명: create_multiplot_script의 _eff_margin_left/right가 안쪽 면은
        # _interior_k=0.5로 절반만 예약하는데, 여기 offset은 그 사정을 몰라
        # 절반이 아닌 "혼자 있을 때" 기준 위치를 그대로 요구했던 것). 실제
        # 예약된 여백 비율(ylabel_margin_ratio - 안쪽 면이면 0.5, 바깥쪽/
        # 단일 plot이면 1.0)만큼 offset도 같이 줄여서, 줄어든 여백 안에
        # 맞춰 들어가게 한다(single-plot은 항상 1.0이라 회귀 없음).
        _ylabel_offset *= ylabel_margin_ratio
        ylabel_text, ylabel_enh = self._render_text(plotdef.ylabel)
        lines.append(f'set ylabel "{ylabel_text}" font "{plotdef.ylabel_font},{_ylabel_size_emit}" offset {_ylabel_offset:.2f},0 {ylabel_enh}')

        if plotdef.y2label:
            # [수정 - 버그] "MFLO:R-SDRT1>L-STLF1" 같은 y2 title이 tic 숫자와
            # 겹침(port/land 공통) - 실제 저장 파일(out111_L.emf)로 재현해서
            # 원인을 찾음: 바로 위 y1 주석의 "Y2는 왼쪽 -"라는 가정이 틀렸었음
            # (Y1 title이 캔버스 밖으로 사라지는 것을 막을 때 대칭이라고
            # 추정만 하고 Y2는 따로 실측 검증을 안 했던 것으로 보였음) - offset
            # 값(0/2/4/6)을 직접 바꿔가며 렌더링 비교한 결과, 음수(-)는 y2label을
            # 오히려 tic 숫자 쪽/플롯 안쪽으로 당겨서 겹치게 하고, y1과 같은
            # 부호(+)로 줘야 tic 숫자 바깥쪽으로 밀려나 겹치지 않음을 확인함.
            # [수정 - 버그] "EMF에서 Y2 title은 너무 떨어짐(마진을 현재의 반으로)" -
            # Y1과 완전히 같은 값을 쓰면 Y1은 딱 맞아도 Y2는 항상 더 헐거워
            # 보였던 것으로 보임(왼쪽 tic 숫자 자릿수와 오른쪽 tic 숫자 자릿수가
            #달라 실제 필요한 간격이 다를 수 있음) - Y2만 별도로 절반 수준으로
            # 낮춘다(Y1의 offset 인상과는 독립적으로 조정).
            # [수정] "screen에서 y2 title은 tic 숫자와 간격을 조금 줄여줘요" -
            # Y1(3)보다 화면에서는 Y2를 더 타이트하게(2) 별도로 낮춤.
            # [수정 - 근본 오류 발견] Y1과 같은 원인(위 y1 offset 주석 참고) -
            # 실측(실제 out111.dat 2-curve+Y2 조합, offset -실측)으로 재확인:
            # Y2도 "tic 숫자 우측 끝 ~ border 사이"가 아니라 "tic 숫자 우측 끝
            # ~ 캔버스 우측 끝 사이의 빈 여백"에 자리해야 함(Y1의 좌우 대칭).
            # size=11→offset≈1.13, size=36→offset≈5.85 에서 간격 4pt로 균일
            # (Y1과 부호만 반대, 기울기 크기는 비슷 - digit 폭 차이로 살짝 다름).
            if _is_screen:
                # [수정] "screen도 비례식 적용해야" - Y1과 동일하게 screen Y2도
                # 고정값(1.5)이 큰 폰트에서 깨짐을 proxy 렌더로 확인(size=36
                # 에서 gap 1.3pt까지 줄어듦) - 기준 크기(ratio=1.0)의 현재 gap
                # (13.1pt, 기존 1.5 그대로 유지 시)을 보존하고 그 이상 크기는
                # 비례해서 커지도록 절편/기울기 재계산.
                # [수정] "2줄 plot에서 Y2 title 2번째 줄이 잘림, tic<->title
                # 간격이 너무 크다 - 7pt는 줄여도 될 듯" - 1칸≈4.05pt 기준
                # 7pt만큼(약 1.73칸) 절편을 낮춰 간격을 줄이고 캔버스 안쪽으로
                # 당긴다.
                _y2label_offset = -4.757 + 4.527 * (y2label_size / _term_font_pt_ref)
            elif _is_emf:
                # [수정] "y1,y2 모두 tic<->title 간격이 너무 큼 - 반으로 줄일
                # 것" - 1.5로 실측 재확인(title 정상 출력) 후 확정.
                # [수정] "2줄 EMF는 y2 title 1번째 줄과 tic 숫자 사이를
                # 반으로 줄일 것(축 size는 유지)" - 2줄일 때 tic에 더 가까운
                # 쪽은 앞쪽 줄(1번째 줄)이므로 이 offset 하나가 그 간격을
                # 결정함 - 이전과 같은 비율(반으로)로 1.5*0.5=0.75로 조정.
                # [수정 - 근본 원인] single-plot EMF에서 이 고정값(0.75)이
                # y2label_size 크기와 무관하게 그대로라, 이번 세션에서 EMF
                # 폰트 보정(EMF_FONT_RENDER_FIX)이 제대로 반영되어 y2label이
                # 커진 뒤로는(예: 31pt) tic 숫자("40","30","20","10")와 항상
                # 겹침(직접 렌더링으로 확인 - "S"/"D"/"R" 등이 숫자 위에 얹힘).
                # 실측(10x8cm/30x24cm 두 크기, offset을 0.75~6.0까지 바꿔가며
                # 렌더링+크롭 비교)으로 재보정: 두 크기 모두 겹침이 사라지는
                # 지점이 대략 2.0~2.5로 비슷해(ylabel/xlabel처럼 크기에 따라
                # 크게 달라지지 않음) 크기 무관 고정값 2.5로 안전하게 확정.
                # 멀티플롯(is_multiplot=True)은 font_panel_scale 산정 방식이
                # 달라 y2label_size가 이 정도로 커지지 않고, 이미 여러 번
                # 검증되어 문제 없는 상태라 - "지금 잘되는 M-P는 그대로 두라"는
                # 요청에 따라 그대로(0.75) 둔다.
                _y2label_offset = 0.75 if is_multiplot else 2.5
                # [수정 - 버그, 실측으로 근본 원인 발견] "Manual 소형 칸(예: 2/p
                # 7.0cm 근방)에서 Y2 2줄 title의 둘째 줄이 EMF 파일에 텍스트
                # 레코드 자체가 통째로 안 씀" - margin_right를 키워도(0.62->
                # 0.79in) 전혀 안 고쳐져 "margin 부족"이 아님을 확인, EMF
                # 바이너리 직접 파싱(rclFrame vs 텍스트 rx)으로 1번째 줄
                # anchor가 이미 프레임 우측 끝에서 0.1in밖에 안 남을 만큼
                # 바깥쪽에 찍혀 있어 2번째 줄이 캔버스 밖으로 밀려 gnuplot이
                # 그 레코드를 통째로 안 쓰는 것으로 확인됨(offset 값을 0.7~3.0
                # 으로 바꿔가며 재현 - 0.65 이하에서만 정상 출력). tic<->1번째
                # 줄 간격(offset)을 줄여 1번째 줄을 tic 쪽으로 당기면 2번째
                # 줄이 쓸 캔버스 여유가 생김 - Y1(ylabel)은 2줄일 때 반대로
                # +0.65(간격을 늘림)로 이미 대응돼 있는데(줄 순서가 y2와 반대:
                # Y1은 안쪽[tic]줄이 뒤쪽 줄이라 부호가 다름) Y2는 이 대응이
                # 빠져 있었던 것 - 2/p Manual 6x5cm 기본 크기 기준 offset 값을
                # 실측 스윕(0.7~-0.5)한 결과 절대값이 -0.3 이하여야 정상 출력
                # (0, -0.1, -0.2는 여전히 소실, -0.3부터 정상) - 기준값 0.75
                # 대비 1.1을 빼 -0.35(여유 포함)로 확정, 96-combo 회귀로 4/p·
                # 6/p 등 이미 정상인 조합에 부작용 없음 재확인.
                # [수정 - 원칙 정정, 범위 한정] "폰트/축 크기와 무관하게 항상
                # 같은 비율로 적용돼야 함"이라는 지적은 맞지만, M-P(base=0.75)
                # 용으로 이미 검증된 고정값(-1.1)을 건드리면 M-P 4/p·6/p Manual
                # 양쪽 2줄 조합에 회귀가 재현됨(실측 확인) - M-P는 그대로 두고,
                # single-plot(base=2.5)에만 비례식(_title_f_scale 기준, 10x8cm
                # 실측으로 계수 2.5 확정)을 적용해 분리한다.
                if "|" in (plotdef.y2label or ""):
                    if is_multiplot:
                        _y2label_offset -= 1.1
                    else:
                        _y2label_offset -= 2.5 * _title_f_scale
            elif (fmt or "").lower() == "svg":
                # [수정] "SVG는 y2 title 1글자 폭을 줄일 것" - 공통 비율식보다
                # SVG만 1칸 더 타이트하게.
                _y2label_offset = (-1.871 + 1.939 * (y2label_size / _term_font_pt_ref)) - 1.0
            else:
                # [수정] Y1과 같은 이유("여백이 폰트 크기에 비례해야") - 기준
                # 크기(ratio≈1.545)의 gap(4pt)은 유지하고 다른 크기에서는
                # 비례해서 커지도록 절편/기울기 재계산.
                _y2label_offset = -1.871 + 1.939 * (y2label_size / _term_font_pt_ref)
            # [수정 - 근본 원인, 위 ylabel과 동일한 이유] M-P 안쪽(interior) 칸은
            # margin_right도 절반만(_interior_k=0.5) 예약되는데 이 offset은 그걸
            # 몰랐음 - 실제 예약 비율(y2label_margin_ratio)만큼 같이 줄인다.
            _y2label_offset *= y2label_margin_ratio
            y2label_text, y2label_enh = self._render_text(plotdef.y2label)
            lines.append(f'set y2label "{y2label_text}" font "{plotdef.y2label_font},{_y2label_size_emit}" offset {_y2label_offset:.2f},0 {y2label_enh}')

        lines.append("set ytics nomirror")

        lines.append("unset key")  # 두 legend 모두 수동으로 직접 그리므로 네이티브 key는 항상 끔

        # 'outside right' 위치는 plot 밖에 legend를 두는 것이므로, 실제 축(plot) 영역을
        # 줄여서 legend box가 곡선과 겹치지 않게 자리를 마련해줘야 한다
        if not is_multiplot:
            if plotdef.legend_on and plotdef.legend_pos == "outside right":
                lines.append(f"set rmargin at screen {0.75 if uses_y2 else 0.78}")
            elif getattr(plotdef, "legend2_on", False) and getattr(plotdef, "legend2_pos", "") == "outside right":
                lines.append(f"set rmargin at screen {0.75 if uses_y2 else 0.78}")

        # curve.color/linestyle이 Auto(미지정)일 때 기본값은 plotdef.curves 전체에서의
        # 순서(i)를 기준으로 정해지므로(아래 실제 plot 명령 루프와 동일), Legend1/2
        # 둘 다 이 전체 순서 기준 매핑을 공유해서 실제 그려지는 색/스타일과 일치시킨다
        curve_index_map = {id(c): i for i, c in enumerate(plotdef.curves)}

        # Legend box 폭 계산에 쓸 축의 실제 물리적 폭(인치) - multiplot에서는
        # 호출자가 이미 계산해서 넘겨주고(axis_w_in), 단일 plot 등 안 넘어온
        # 경우 frame_width에서 좌우 margin을 대략 제외해 역산한다
        if axis_w_in is None:
            # [수정] 기존엔 "lmargin=0.15 고정"이라고 가정하고 rmargin_frac에서
            # 그만큼만 뺀 값으로 축 폭을 추정했는데, 위에서 ylabel/tic 폭에 맞춰
            # lmargin을 실제로 더 늘리는 보정이 들어간 뒤로는 이 가정이 안 맞아
            # 축 폭을 실제보다 넓게(=legend box를 좁게) 추정해서, legend 글자가
            # box 밖으로 삐져나오는 문제가 있었음 - 방금 계산해 둔 실제
            # lmargin/rmargin(_lmargin_base/_rmargin_base, is_multiplot=False일
            # 때만 이 분기에 옴)으로 정확히 계산한다.
            try:
                if not getattr(plotdef, "frame_auto", True) and not _is_interactive:
                    # [수정] frame_width는 이제 axis 크기 그 자체이므로 그대로 쓴다.
                    axis_w_in = float((plotdef.frame_width or "5").strip() or 5.0)
                    if (plotdef.frame_unit or "in") == "cm":
                        axis_w_in /= 2.54
                elif not _is_interactive and _auto_canvas_in is not None:
                    # [추가] Auto + png/pdf/eps(실제 inch 캔버스) - 실제 터미널
                    # 물리 폭을 그대로 쓴다.
                    axis_w_in = max((_rmargin_base - _lmargin_base) * _auto_canvas_in[0], 0.5)
                else:
                    fw = 1000.0 / 168  # interactive 기본 터미널 크기(1000px/168px_per_in)
                    axis_w_in = max((_rmargin_base - _lmargin_base) * fw, 0.5)
            except ValueError:
                axis_w_in = 5.0
            axis_w_in = max(axis_w_in, 0.5)

        # [추가] "Circle(중심축 2개 타원, 반지름 입력, 좌표값/% 선택, 반지름 1개만
        # 입력하면 원, 두께는 Arrow와 동일)" - 중심(x,y)과 반지름(rx,ry)에 Comment/
        # Arrow와 동일한 coord_mode(좌표값/%) 변환을 그대로 재사용한다. ry가
        # 비어있으면 rx를 그대로 써서 원이 된다. 두께는 Arrow처럼 별도 지정 없이
        # gnuplot 기본값을 그대로 써서 서로 같게 맞춘다.
        # [수정 - 위치 이동] axis_w_in/axis_h_in이 확정된(위에서 이미 계산된)
        # 뒤로 옮김 - 예전 위치(annotations/arrows 바로 다음)에서는 axis_w_in이
        # 아직 None이라 Ry 자동보정이 항상 예외로 빠져 조용히 무시되고 있었음.
        if circles:
            for i, ell in enumerate(circles):
                _mode = ell.get("coord_mode", "pct")
                gx = _coord_clause(ell.get("x", ""), _mode, 0.5)
                gy = _coord_clause(ell.get("y", ""), _mode, 0.5)
                rx_val = (ell.get("rx", "") or "").strip()
                ry_raw = (ell.get("ry", "") or "").strip()
                # [수정 - 버그] "Ry를 비워서 원을 그렸는데 실제로는 타원으로 보임" -
                # size graph/first X,Y는 "축 가로/세로 크기(또는 데이터 범위)에
                # 대한 비율"이라, 축이 정사각형이 아니면(대부분 그럼, 예: Time
                # 대 값) Rx=Ry로 넣어도 실제 물리적 가로/세로 길이가 달라져
                # 타원처럼 보였음. Ry를 비워서 "원"을 의도한 경우, %(pct)와
                # 좌표값(data) 모드 둘 다 축 가로세로 물리 비율을 반영해서
                # Ry를 보정한다(기본값 = 비율 보정된 값, Ry를 직접 입력했으면
                # 그 값으로 덮어씀 - "처음부터 Ry=Rx 두고 입력 있으면 바꾼다").
                if not ry_raw and _mode == "data":
                    try:
                        x_nice = self._nice_axis_range(plotdef, "x")
                        y_nice = self._nice_axis_range(plotdef, "y1")
                        x_lo, x_hi, _ = x_nice
                        y_lo, y_hi, _ = y_nice
                        x_range = x_hi - x_lo
                        y_range = y_hi - y_lo
                        # rx(데이터 단위)를 실제 물리(inch) 크기로 바꾼 뒤, 같은
                        # 물리 크기가 되도록 y축 데이터 단위로 다시 환산한다.
                        rx_phys_in = float(rx_val) * (axis_w_in / x_range)
                        ry_val = str(rx_phys_in / (axis_h_in / y_range))
                    except Exception:
                        ry_val = rx_val
                elif not ry_raw:
                    try:
                        ry_val = str(float(rx_val) * (axis_w_in / max(axis_h_in, 0.01)))
                    except (TypeError, ValueError):
                        ry_val = rx_val
                else:
                    ry_val = ry_raw or rx_val
                grx = _coord_clause(rx_val, _mode, 0.05)
                gry = _coord_clause(ry_val, _mode, 0.05)
                _color = (ell.get("color") or "").strip() or "black"
                lines.append(
                    f'set object {i+1} ellipse at {gx},{gy} size {grx},{gry} '
                    f'front fillstyle empty border lc rgb "{_color}"'
                )

        # Legend box 테두리는 Frame(plot 외곽 border) 두께 이하여야 하므로,
        # 사용자가 더 크게 입력해도 Frame 두께로 제한한다
        _frame_border_lw = 1.5 * border_scale

        # [추가] "legend box W*H를 %뿐 아니라 x,y 좌표값(데이터 단위)으로도
        # 입력 가능하게 - 인터랙티브 창에서 마우스 커서로 좌표를 직접 읽어서
        # 그 차이를 넣기 편하게" - "%"로 끝나면 기존처럼 axis 대비 비율,
        # "%" 없이 그냥 숫자면 실제 X/Y 데이터 값 차이로 해석해서 axis의
        # 전체 데이터 범위(폭/높이) 대비 비율로 환산한다. 범위를 못 구하면
        # (예: 아직 auto인데 데이터가 없음) 좌표값 입력은 조용히 무시되고
        # 기존 자동 추정으로 대체됨(아래 _render_legend_box의 안전한 폴백).
        def _axis_span(axis_name, auto, manual_min, manual_max, is_log):
            if auto:
                nice = self._nice_axis_range(plotdef, axis_name, is_log=is_log)
                if nice:
                    lo, hi, _ = nice
                    return hi - lo
                return None
            lo, hi = self._safe_manual_range(manual_min, manual_max, is_log)
            try:
                return float(hi) - float(lo)
            except (ValueError, TypeError):
                return None
        _legend_x_span = _axis_span("x", plotdef.xauto, plotdef.xmin, plotdef.xmax, getattr(plotdef, "xlog", False))
        _legend_y_span = _axis_span("y1", plotdef.yauto, plotdef.ymin, plotdef.ymax, getattr(plotdef, "y1log", False))

        group1_curves = [c for c in plotdef.curves if getattr(c, "in_legend1", True)]
        if plotdef.legend_on and group1_curves:
            legend_thick_val = min(float(getattr(plotdef, "legend_thick", "1.5") or 1.5), _frame_border_lw)
            self._render_legend_box(
                lines, group1_curves, plotdef.legend_pos, plotdef.legend_box,
                legend_thick_val, 8000, f_scale * legend_scale_boost * _mp_font_fix, line_scale, panel_scale,
                getattr(plotdef, "is_print_mode", False), curve_index_map, getattr(plotdef, "legend_font", plotdef.xlabel_font),
                axis_w_in, legend_size=float(getattr(plotdef, "legend_size", "9") or 9), axis_h_in=axis_h_in,
                box_w_extra_chars_override=legend_width_extra_chars,
                align=getattr(plotdef, "legend_align", "Auto"), fmt=fmt,
                box_w_pct_override=getattr(plotdef, "legend_box_width_pct", ""),
                box_h_pct_override=getattr(plotdef, "legend_box_height_pct", ""),
                axis_x_span=_legend_x_span, axis_y_span=_legend_y_span,
            )

        group2_curves = [c for c in plotdef.curves if getattr(c, "legend_group", 1) == 2]
        if getattr(plotdef, "legend2_on", False) and group2_curves:
            legend2_thick_val = min(float(getattr(plotdef, "legend2_thick", "1.5") or 1.5), _frame_border_lw)
            self._render_legend_box(
                lines, group2_curves, plotdef.legend2_pos, getattr(plotdef, "legend2_box", True),
                legend2_thick_val, 9000, f_scale * legend_scale_boost * _mp_font_fix, line_scale, panel_scale,
                getattr(plotdef, "is_print_mode", False), curve_index_map, getattr(plotdef, "legend_font", plotdef.xlabel_font),
                axis_w_in, legend_size=float(getattr(plotdef, "legend_size", "9") or 9), axis_h_in=axis_h_in,
                box_w_extra_chars_override=legend_width_extra_chars,
                align=getattr(plotdef, "legend2_align", "Auto"), fmt=fmt,
                box_w_pct_override=getattr(plotdef, "legend2_box_width_pct", ""),
                box_h_pct_override=getattr(plotdef, "legend2_box_height_pct", ""),
                axis_x_span=_legend_x_span, axis_y_span=_legend_y_span,
            )


        # Advanced: 화면의 Raw gnuplot 입력창 내용을 plot 직전에 그대로 삽입
        if getattr(plotdef, "extra_gnuplot", ""):
            lines.append("# --- Advanced raw gnuplot (사용자 입력) ---")
            lines.extend(plotdef.extra_gnuplot.splitlines())

        plot_line_idx = len(lines)
        lines.append("plot \\")
        cmd_list = []
        marker_datablocks = []  # (마커 있는 curve용 인라인 데이터블록 텍스트 모음 - plot 앞에 삽입)

        default_x_col = getattr(plotdef, "x_output_no", 0)

        for i, curve in enumerate(plotdef.curves):
            color = curve.color or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
            linestyle = curve.linestyle or DEFAULT_LINESTYLES[i % len(DEFAULT_LINESTYLES)]
            abs_path = curve.dat_file if os.path.isabs(curve.dat_file) else os.path.abspath(curve.dat_file)
            # gnuplot을 실행할 때 cwd를 self.plot_dir로 고정해두므로, 그 기준 상대경로를 씀
            # (다른 드라이브라 상대경로 계산이 안 되면 절대경로로 대체)
            try:
                path = os.path.relpath(abs_path, start=self.plot_dir) if self.plot_dir else abs_path
            except ValueError:
                path = abs_path
            path = path.replace("\\", "/")

            is_y2 = getattr(curve, "axis", "y1") == "y2"
            axis = "x1y2" if is_y2 else "x1y1"
            
            # [수정] 각 곡선별로 개별 지정된 x_output_no가 있다면 이를 우선 반영 (Var no=0인 0번 컬럼도 정상 처리되도록 0 이상 인덱스 지원)
            x_col_idx = curve.x_output_no if getattr(curve, "x_output_no", None) is not None else default_x_col
            x_col_expr = f"${x_col_idx + 1}"
            col_y = curve.output_no + 1
            
            using_expr = f"({x_col_expr}+{curve.x_shift}):{col_y}"
            lw = curve.linewidth * line_scale

            # [수정] Legend1/2 둘 다 이제 set label로 수동으로 그리므로, 실제 plot
            # 명령에서는 gnuplot 네이티브 key용 title이 더 이상 필요 없음 (항상 notitle)
            cmd = f'"{path}" using {using_expr} notitle axes {axis} with lines lw {lw}'

            if color: cmd += f' lc rgb "{color}"'
            _dash_pat_curve = _dash_pattern_for_fmt(linestyle, fmt)
            if _dash_pat_curve:
                cmd += f" dashtype ({_dash_pat_curve})"
                # [삭제] "jpg는 curve line style이 안 나타남" 경고 - 예전엔
                # gnuplot의 jpeg 터미널(libgd 기반)이 dashtype을 무시하고 항상
                # 실선만 그려서 경고가 필요했지만, 이제 JPG는 이 gnuplot 명령을
                # 직접 jpeg 터미널로 안 보내고 PDF로 먼저 그린 뒤 PyMuPDF로
                # 래스터화해서 만듦(create_script 상단 참고) - PDF는 dash를
                # 제대로 그리므로 그 결과가 그대로 JPG에도 남아 이 한계 자체가
                # 없어짐(직접 렌더링해서 dash가 JPG에 남는 것을 확인함).
            cmd_list.append(cmd)

            # [수정] every-N(단순 인덱스 간격) 방식은 log축에서 시각적으로
            # 고르지 않게(한쪽에 몰림) 찍히는 문제가 있었음 - 실제 (x,y) 데이터를
            # 읽어서 log(또는 선형) 공간에서 등간격인 목표값에 가장 가까운 실제
            # 데이터 포인트를 고르고, 그 점들만 담은 인라인 데이터블록으로 그린다
            marker_shape = getattr(curve, "marker_shape", None)
            if marker_shape is not None:
                is_manual_count = bool(getattr(curve, "marker_max_count", None))
                target = curve.marker_max_count if is_manual_count else 25
                is_log_x = getattr(plotdef, "xlog", False)
                # [수정] Auto(개별 지정 없음)일 때만 공통 X범위를 기준으로 삼아
                # curve간 밀도를 맞추고, 사용자가 직접 Max#를 입력한 경우는 그
                # curve 자신의 실제 구간을 기준으로 그 개수만큼 채운다 (예:
                # var_x가 0~1000이고 통합구간이 0~2000이어도, 10개로 지정했으면
                # 0~1000 안에 10개를 그대로 채움)
                effective_shared_range = None if is_manual_count else shared_x_range
                marker_pts = self._select_marker_points(curve, x_col_idx, curve.output_no, target, is_log_x, shared_x_range=effective_shared_range)
                if marker_pts:
                    dbname = f"$Marker{i}"
                    block = [f"{dbname} << EOD"]
                    block.extend(f"{px:.10g} {py:.10g}" for px, py in marker_pts)
                    block.append("EOD")
                    marker_datablocks.append(block)

                    marker_size = getattr(curve, "marker_size", 1.0) * line_scale
                    marker_cmd = f'{dbname} using 1:2 notitle axes {axis} with points pt {marker_shape} ps {marker_size}'
                    if color: marker_cmd += f' lc rgb "{color}"'
                    cmd_list.append(marker_cmd)

        # 마커용 인라인 데이터블록들을 'plot \\' 줄 바로 앞에 삽입
        # (gnuplot은 데이터블록을 plot에서 쓰기 전에 미리 정의해야 함)
        if marker_datablocks:
            insert_lines = []
            for block in marker_datablocks:
                insert_lines.extend(block)
            lines[plot_line_idx:plot_line_idx] = insert_lines

        if not uses_y2 and cmd_list:
            cmd_list.append("NaN axes x1y2 notitle")

        for i, cmd in enumerate(cmd_list):
            if i != len(cmd_list) - 1: cmd += ", \\"
            lines.append(cmd)

        lines.append("")
        if is_multiplot:
            lines.append("unset label")
            lines.append("unset arrow")

    def _get_terminal_cmd(self, fmt, outfile, plotdef=None, size_override=None, panel_scale=1.0):
        fmt = fmt.lower()
        # [추가] gnuplot은 ylabel/xlabel을 tic 숫자로부터 얼마나 띄울지 등의
        # 자동 배치 계산에 (우리가 각 요소마다 개별 font로 덮어써도) 터미널
        # 기본 font 크기를 기준 단위로 쓰는 것으로 실측 확인됨 - 터미널
        # 기본폰트가 항상 11로 고정돼 있어서, panel_scale이 커질수록(예: 큰
        # explicit frame) 실제 표시 폰트(예: 66pt)와 이 기준(11pt)이 크게
        # 벌어져 ylabel/xlabel이 tic 숫자와 심하게 겹쳐 보이는 문제가 있었음
        # (60x50cm에서 실측 확인, 터미널 기본폰트를 66로 바꾸면 해결됨) -
        # 터미널 기본폰트도 같은 비율로 키워서 gnuplot의 자동 배치 계산이
        # 실제 폰트 크기와 일치하게 한다.
        _term_font_pt = max(int(round(11 * (panel_scale or 1.0))), 8)
        _term_font = f"Malgun Gothic,{_term_font_pt}"
        def size_clause(default):
            if size_override: return f"size {size_override}"
            if plotdef is not None and not getattr(plotdef, "frame_auto", True):
                w = (getattr(plotdef, "frame_width", "") or "").strip()
                h = (getattr(plotdef, "frame_height", "") or "").strip()
                unit = (getattr(plotdef, "frame_unit", "in") or "in").strip()
                if w and h: return f"size {w}{unit},{h}{unit}"
            return default

        def size_clause_px(default_px, px_per_in=168):
            # windows/jpeg 터미널은 size에 in/cm 같은 단위를 못 받고 픽셀 숫자만 받으므로
            # (pdfcairo/svg 등 다른 터미널과 달리) 인치/cm 값을 환산해서 넘긴다.
            # 순수 96px/in로 하면 창이 너무 작게 나와서(예: 5in x 4in -> 480x384),
            # 화면에서 보기 좋은 크기가 되도록 1.75배(=168px/in) 키워서 적용.
            # [수정] 이 168px/in은 화면 미리보기용 확대 배율일 뿐인데, emf 포맷도
            # 그대로 재사용하고 있어서 실제 인쇄 물리 크기가 항상 요청한 값의
            # 약 1.75배로 찍히는 문제가 있었음(EMF 헤더의 rclFrame을 gdi32로
            # 직접 읽어 calibration한 결과, gnuplot의 emf 터미널은 항상 약
            # 96.32px/in 기준으로 rclFrame을 기록함 - _print_emf_and_cleanup이
            # 인쇄 시 이 rclFrame을 물리 크기의 기준으로 삼으므로, emf는 168이
            # 아니라 이 값을 써야 요청한 cm/in 그대로 인쇄된다). 화면 전용
            # 포맷(jpg 등)은 기존 168을 그대로 유지.
            PX_PER_IN = px_per_in
            if size_override:
                try:
                    w_str, h_str = size_override.split(",")
                    w_in = float(w_str.replace("in", "").strip())
                    h_in = float(h_str.replace("in", "").strip())
                    return f"size {int(w_in * PX_PER_IN)},{int(h_in * PX_PER_IN)}"
                except (ValueError, IndexError):
                    return default_px
            if plotdef is not None and not getattr(plotdef, "frame_auto", True):
                w = (getattr(plotdef, "frame_width", "") or "").strip()
                h = (getattr(plotdef, "frame_height", "") or "").strip()
                unit = (getattr(plotdef, "frame_unit", "in") or "in").strip()
                if w and h:
                    try:
                        w_val, h_val = float(w), float(h)
                        if unit == "cm":
                            w_val, h_val = w_val / 2.54, h_val / 2.54
                        return f"size {int(w_val * PX_PER_IN)},{int(h_val * PX_PER_IN)}"
                    except ValueError:
                        return default_px
            return default_px

        title = os.path.splitext(os.path.basename(outfile))[0]
        if fmt == "interactive":
            # [수정] 화면(Interactive) 창은 Frame Size(원래 인쇄/저장 물리 크기용
            # 설정) 값과 무관하게 항상 넓은 고정 크기를 쓴다 - 기존엔 Frame Size를
            # 직접 지정(예: 10x8cm, 1.25 비율)하면 그 비율 그대로 화면 창에도
            # 적용되어 "정사각으로 보인다"는 문제가 있었음. 화면 보기 편의와
            # 인쇄/저장 물리 크기는 서로 다른 목적이라 분리한다.
            return f"set terminal windows title '{title}' font 'Malgun Gothic,11' size 1000,700"
        elif fmt == "png":
            # [수정] "PDF랑 완전히 다르다, title/legend 폰트가 너무 작다" - 예전엔
            # size를 단위 없는 순수 픽셀 수(예: 3508,2481 = 인쇄 품질 300dpi 의도)로
            # 직접 지정했는데, gnuplot 매뉴얼에 "size가 cm/in 단위 없이 오면 항상
            # 72dpi로 픽셀 변환한다"고 명시돼 있어서 - 캔버스만 300dpi로 커지고
            # 글자/선/legend는 72dpi 기준 그대로 작게 그려져 PDF와 확연히 달라
            # 보였음. 이를 fontscale 등으로 보정하려면 legend box 폭 추정, 명시적
            # Frame 크기의 마진 계산(_compute_manual_margins_in) 등 문자폭 관련
            # 계산을 전부 같이 손봐야 하고 서로 어긋나기 쉬웠음(실제로 명시적
            # Frame 크기에서 title/label이 겹치는 문제가 생겼었음) - 대신
            # pdfcairo/svg와 완전히 동일하게 "in" 단위로 물리 크기를 그대로 주면
            # (size_clause는 pdfcairo와 공유하는 함수) pngcairo가 항상 정확히
            # 72dpi로 래스터화하므로 PDF와 100% 같은 비율로 나온다(비율은 완전히
            # 정확하고, 해상도만 낮음 - 인쇄 품질 해상도는 create_script에서 저장
            # 직후 Pillow로 300/72배 업스케일해서 확보한다 - _upscale_png_dpi
            # 참고). Frame Auto 여부와 무관하게 이 방식 하나로 통일된다.
            return f"set terminal pngcairo enhanced font '{_term_font}' {size_clause('size 11.7in,8.3in')}"
        elif fmt == "jpg":
            return f"set terminal jpeg {size_clause_px('size 1600,900')} enhanced font '{_term_font}'"
        elif fmt == "svg":
            # [수정] gnuplot의 svg 터미널은 size에 in/cm 같은 단위 접미사를 전혀
            # 받지 못함("undefined variable: cm/in" 에러로 스크립트 실행이 실패함) -
            # size_clause(단위 접미사 버전)를 쓰고 있어서, frame_auto 여부와
            # 무관하게 항상 이 에러가 나고 있었고, gnuplot이 에러 후에도 남은
            # 스크립트를 계속 실행해버려서 결과 svg의 width/height가 완전히
            # 왜곡된 값(예: 10x480)으로 나오는 심각한 문제가 있었음. 다른 픽셀
            # 전용 터미널(windows/emf/jpeg)과 동일하게 픽셀 숫자로 환산해서 넘긴다.
            return f"set terminal svg enhanced {size_clause_px('size 1123,797', px_per_in=96)} font '{_term_font}'"
        elif fmt == "pdf":
            return f"set terminal pdfcairo enhanced color font '{_term_font}' {size_clause('size 11.7in,8.3in')}"
        elif fmt == "eps":
            return f"set terminal postscript eps enhanced color font '{_term_font}' {size_clause('')}"
        elif fmt == "emf":
            # emf 터미널은 windows 터미널과 마찬가지로 in/cm 단위를 못 받고 픽셀 숫자만 받음.
            # 인쇄 물리 크기가 정확해야 하므로 화면용 168px/in이 아니라 EMF_PX_PER_IN을 씀
            return f"set terminal emf enhanced {size_clause_px('size 840,672', px_per_in=EMF_PX_PER_IN)} font '{_term_font}'"
        else:
            raise ValueError(f"Unsupported output format : {fmt}")

    def _compute_size_scale(self, plotdef):
        """plot 내 폰트 크기가 Frame 크기에 비례해서 확대/축소되도록 스케일을
        계산한다 (기준 10x8cm 대비 비율). Frame Size Auto면 기준 그대로(1.0).
        [수정] 예전엔 폭(width)만 기준으로 스케일을 정해서, 가로로 넓고 세로가
        짧은 프레임(예: 30x8cm)에서 실제 세로 공간보다 훨씬 큰 폰트가 배정돼
        ylabel/tic 숫자가 서로 겹쳐버리는 문제가 실측으로 확인됨 - multiplot의
        panel_scale=min(1/cols,1/rows)와 같은 원리로, 폭 비율과 높이 비율 중
        더 작은(더 좁은) 쪽을 따르게 해서 어느 한쪽이 짧아도 그 짧은 쪽 기준으로
        폰트가 안전하게 줄어들게 한다."""
        REFERENCE_WIDTH_IN = 10.0 / 2.54  # 기준 10cm
        REFERENCE_HEIGHT_IN = 8.0 / 2.54  # 기준 8cm
        if getattr(plotdef, "frame_auto", True):
            return 1.0

        unit = (getattr(plotdef, "frame_unit", "in") or "in")

        def _to_in(val_str, default_in):
            val_str = (val_str or "").strip()
            if not val_str:
                return default_in
            try:
                v = float(val_str)
            except ValueError:
                return default_in
            return v / 2.54 if unit == "cm" else v

        fw = _to_in(plotdef.frame_width, REFERENCE_WIDTH_IN)
        fh = _to_in(plotdef.frame_height, REFERENCE_HEIGHT_IN)
        # [수정] baseline(10x8cm)은 가로가 더 긴 모양인데, 이걸 portrait로 회전해서
        # 8x10으로 쓰면 기준(REF)은 그대로 "10 가로/8 세로"라서 같은 baseline을
        # 회전한 것뿐인데도 스케일이 달라짐(portrait가 더 작게 나옴, 0.8배) -
        # landscape에서 legend/폰트가 상대적으로 더 크게 나오던 문제의 원인.
        # 요청한 frame의 가로세로 모양(landscape/portrait)에 맞춰 REF도 같이
        # 돌려써서, 같은 baseline을 회전만 한 경우 항상 scale=1.0이 나오게 한다.
        if fw < fh:
            REFERENCE_WIDTH_IN, REFERENCE_HEIGHT_IN = REFERENCE_HEIGHT_IN, REFERENCE_WIDTH_IN
        width_ratio = fw / REFERENCE_WIDTH_IN
        height_ratio = fh / REFERENCE_HEIGHT_IN
        # [수정 - 버그] 상한이 전혀 없어서 기준(10x8cm)보다 훨씬 큰 Manual
        # 크기(예: 40x30cm)를 입력하면 title 폰트가 배율을 그대로 따라가
        # 100pt 이상으로 폭주해서 title 텍스트가 plot 전체를 뒤덮어버리는
        # 문제가 실측 확인됨(single-plot도 동일하게 재현 - multiplot만의
        # 문제가 아니었음). 실무적으로 쓰는 Manual 크기(20x16cm 이내)는
        # 이 상한 밑이라 영향 없고, 그보다 훨씬 큰 값만 여기서 안전하게
        # 눌러준다.
        _raw_ratio = min(width_ratio, height_ratio)
        if _raw_ratio > 2.0:
            self.warnings.append(
                f"Frame 크기가 기준(10x8cm) 대비 {_raw_ratio:.1f}배로 너무 커서 "
                f"폰트 배율을 2.0배로 제한했습니다. 이보다 작은 Manual 크기를 권장합니다."
            )
        return max(min(width_ratio, height_ratio, 2.0), 0.3)  # 하한 0.3, 상한 2.0

    def _compute_manual_margins_in(self, plotdef, f_scale, is_print_mode, uses_y2, fmt=None):
        """[추가] "Frame(Axis) 크기 = 좌표축(axis) 자체의 크기" - Manual(frame_auto=
        꺼짐)일 때 frame_width/height는 axis 크기이고, 실제 출력 페이지(칸) 크기는
        axis + 이 마진들을 더한 값이어야 한다(예전엔 반대로 frame_width/height를
        페이지 전체로 보고 axis를 그 안에서 빼서 구했음 - "Axis Frame"이라는 이름과
        맞지 않는 설계였음). title/xlabel/ylabel/y2label 존재 여부와 무관하게 항상
        의미 있는 최소값을 반환한다(없으면 tic 숫자만을 위한 작은 여백).
        _build_plot_commands의 fraction 변환 로직과 반드시 같은 값을 써야 하므로
        (터미널 크기를 먼저 정하고 나중에 그 크기 기준 fraction으로 환산), 이
        메서드 하나만 두 군데(create_script, _build_plot_commands)에서 공유한다."""
        xfmt = getattr(plotdef, "xfmt", "Normal")
        y1fmt = getattr(plotdef, "y1fmt", "Normal")
        y2fmt = getattr(plotdef, "y2fmt", "Normal")
        title_lines = 1 + (plotdef.title or "").count("|")
        xlabel_lines = 1 + (plotdef.xlabel or "").count("|")
        ylabel_lines = 1 + (plotdef.ylabel or "").count("|")
        y2label_lines = 1 + (getattr(plotdef, "y2label", "") or "").count("|")

        def _tick_label_chars(axis_name):
            try:
                nice = self._nice_axis_range(plotdef, axis_name)
            except Exception:
                nice = None
            if not nice:
                return 4
            y_lo, y_hi, _ = nice
            max_len = 1
            for v in (y_lo, y_hi, (y_lo + y_hi) / 2.0):
                if abs(v) < 1e-9:
                    s = "0"
                elif float(v).is_integer() and abs(v) < 1e15:
                    s = f"{v:.0f}"
                else:
                    s = f"{v:.3g}"
                max_len = max(max_len, len(s))
            return max_len

        tick_char_width_in = (0.0055 if is_print_mode else 0.0049) * (9 * f_scale)
        tick_char_width_in *= _font_width_ratio(plotdef.ylabel_font)  # 폰트 대체 시 실제 폭 비율로 보정
        BASELINE_TICK_CHARS = 4

        if plotdef.title:
            need_top_in = 0.375 * f_scale * title_lines + 5.0 / 72.0
        else:
            # [수정] "title 없을 때 top margin이 bottom(xlabel 있을 때) 대비 너무
            # 좁다" - 실측(PyMuPDF로 axis border 좌표 직접 비교, Manual 12x9cm)
            # 결과 title 없음(13.4pt)이 xlabel 있음(61.4pt)의 22%에 불과해 위쪽만
            # 유독 답답해 보였음. title/xlabel 둘 다 없는 경우(대칭)까지 건드리지
            # 않으려고 baseline 자체(0.1)는 유지하되, 최소 여유를 그보다 조금 더
            # 줘서(0.18) 캔버스 상단이 축 테두리에 바짝 붙어 보이는 걸 완화한다.
            need_top_in = 0.18 * f_scale

        if plotdef.xlabel:
            need_bottom_in = 0.425 * f_scale + 0.175 * f_scale * (xlabel_lines - 1)
            if xfmt == "Scientific": need_bottom_in += 0.075 * f_scale
            elif xfmt == "Power10": need_bottom_in += 0.04 * f_scale
            need_bottom_in += 6.0 / 72.0
        else:
            need_bottom_in = 0.1 * f_scale

        need_left_in = 0.5 * f_scale + 0.25 * f_scale * (ylabel_lines - 1) if plotdef.ylabel else 0.15 * f_scale
        need_left_in += max(0, _tick_label_chars("y1") - BASELINE_TICK_CHARS) * tick_char_width_in
        if y1fmt == "Scientific": need_left_in += 0.2 * f_scale
        elif y1fmt == "Power10": need_left_in += 0.1 * f_scale
        need_left_in += 3.0 / 72.0

        if uses_y2:
            # [수정] "Manual-1plot에서 y2label을 넣으면 실제로 안 보임(잘림)" -
            # 0.45배는 y2tics 숫자 + 회전된 y2label 텍스트를 함께 담기엔 부족했음
            # (실측: 1.2배부터 정상 표시됨) - 여유를 두고 1.4배로 올린다.
            need_right_in = 0.63 * f_scale + 0.25 * f_scale * (y2label_lines - 1) if getattr(plotdef, "y2label", "") else 0.2 * f_scale
            need_right_in += max(0, _tick_label_chars("y2") - BASELINE_TICK_CHARS) * tick_char_width_in
            if y2fmt == "Scientific": need_right_in += 0.2 * f_scale
            elif y2fmt == "Power10": need_right_in += 0.1 * f_scale
        else:
            need_right_in = 0.15 * f_scale

        # [추가] Axis Frame Auto를 끄고 명시적 크기를 지정한 뒤 png로 저장하면
        # (pdf와 완전히 동일한 스크립트인데도) title이 캔버스 밖으로 밀려나
        # 안 보이는 문제가 실측으로 확인됨 - pngcairo가 pdfcairo와 동일한
        # font "N pt" 지정에도 실제로는 약간 더 크게/넓게 그리는 탓으로
        # 보이며, 마진을 딱 필요한 만큼만 잡으면 이 여유 부족분 때문에 pdf에서는
        # 괜찮던 값이 png에서만 잘림. png일 때만 마진에 15% 안전 여유를 더해서
        # 이 문제를 피한다(pdf/svg/emf는 원래도 문제 없어 그대로 둠).
        _fmt_l2 = (fmt or "").lower()
        if _fmt_l2 == "png":
            # [수정] "10x8cm처럼 작은 Manual 크기 + 축소된 폰트 조합에서 기존
            # 1.35배로도 x/y2 title이 잘리고 legend box가 곡선과 겹치는 문제가
            # 실측 확인됨" - 안전 여유를 1.35 -> 1.6으로 더 키움.
            _png_margin_safety = 1.6
            need_left_in *= _png_margin_safety
            need_right_in *= _png_margin_safety
            need_top_in *= _png_margin_safety
            need_bottom_in *= _png_margin_safety
        elif _fmt_l2 == "emf":
            # [수정 - 버그] "EMF는 Plot 상하 여백을 조금만 더 줄 것(port/land
            # 공통)" - EMF는 png 같은 큰 잘림 문제는 없었지만 위아래가 살짝
            # 빠듯하다는 피드백 - png(1.6배)보다 훨씬 작게, 위/아래만 소폭
            # (1.15배) 늘린다.
            need_top_in *= 1.4
            need_bottom_in *= 1.4
            # [참고] "Y1 title이 tic에 겹침" 문제는 왼쪽 마진(need_left_in) 크기와는
            # 무관했음(마진을 1.4배 늘려도 겹침이 그대로였음 - 직접 렌더링
            # 비교로 확인, 되돌림) - 실제 원인/해결은 ylabel의 offset 값
            # 자체였음(아래 _ylabel_offset 참고).
            # [수정 - 심각한 버그 발견] 위와는 별개의 문제: "Axis Frame Auto로
            # 단일 plot EMF Save하면 Y1/Y2 title이 통째로 안 보임" - 실제
            # GUI의 Save 경로(_compute_auto_frame_size_cm: Auto도 내부적으로
            # frame_auto=False, 10x8cm로 변환됨)를 그대로 재현해서 확인:
            # create_multiplot_script에서 이미 확인한 것과 같은 EMF 렌더러의
            # 한계(margin이 부족하면 겹치는 게 아니라 title을 통째로 누락)가
            # 여기(단일 plot Manual-frame 경로)에도 그대로 있었음 - 여기는
            # 왼쪽/오른쪽 마진을 전혀 안 키우고 있어서 발생. 같은 배율(2배)로
            # 왼쪽/오른쪽도 넉넉히 키운다.
            # [수정] "우측 마진도 많다 - 반으로 줄일 것" - 2.0배는 과했던 것으로
            # 보여 1.6배로 완화(1줄/2줄 모두 title 정상 출력 재확인 후 확정).
            # [수정] "2줄 EMF는 plot 좌우 마진을 지금의 1/3으로 줄일 것(축
            # size는 유지)" - Frame(Axis) 크기는 need_left/right_in과 무관하게
            # 항상 요청한 axis_w_in 그대로 유지되므로(마진은 axis 밖에 더해질
            # 뿐 axis 자체를 줄이지 않음 - create_script의 _total_w_in = axis +
            # 마진 참고) 마진만 줄이면 축 크기는 그대로 유지된다.
            # [주의 - 정확히 1/3(0.53배)은 실측 결과 텍스트가 통째로 사라짐]
            # EMR_EXTTEXTOUTW 텍스트 레코드 존재 여부로 직접 스윕 실측:
            # 1.6→0.53배(1/3) 1줄/2줄 모두 title 소실, 0.8배 2줄 일부 소실,
            # 0.87배 Y2 2번째 줄 소실, 0.92배부터 1줄/2줄 모두 정상 출력 확인
            # (0.95배로 여유를 더 둠). 1줄은 기존 요청(반으로 줄임)으로 이미
            # 정확히 1.6배가 필요한 최소값으로 확정돼 있었으므로 그대로 두고,
            # 2줄일 때만(왼쪽은 ylabel 2줄 여부, 오른쪽은 y2label 2줄 여부로
            # 각각 독립적으로) 추가로 더 낮춘다 - 1/3 요청을 그대로 따르면
            # title이 사라지므로, 안전하게 확인된 최소값(0.95배, 1.6배 대비
            # 약 0.6배 수준)까지만 낮췄다는 점을 명확히 알림.
            _emf_2line_margin_boost = 1.6
            need_left_in *= 1.6 * (_emf_2line_margin_boost / 1.6 if ylabel_lines >= 2 else 1.0)
            need_right_in *= 1.6 * (_emf_2line_margin_boost / 1.6 if y2label_lines >= 2 else 1.0)
        elif _fmt_l2 == "svg":
            # [수정] "2줄 SVG는 plot 좌우 마진을 1/3으로 할 것(이전과 동일한
            # 요청 - 반영 확인)" - 1줄은 기존대로 별도 배율 없이 두고, 2줄
            # (왼쪽은 ylabel, 오른쪽은 y2label 각각)일 때만 낮춘다.
            # [주의 - 정확히 1/3은 실측 결과 title이 사라짐] SVG도 EMF처럼
            # margin이 부족하면 겹치는 게 아니라 title 자체가 통째로 안
            # 그려짐을 이번에 새로 확인함(기존엔 "SVG는 안 사라진다"고
            # 잘못 알고 있었음 - 정정). 실측(PRESS/Test/MFLO/TEST 문자열
            # 존재 여부)으로 나눗값을 스윕: 1.6배(÷1.6)까지는 1줄/2줄/
            # 한쪽만 2줄인 경우 모두 4곳 다 정상 출력, 1.7배부터 Y1
            # 1번째 줄과 Y2 2번째 줄이 사라짐 - 안전한 최대치인 1.6으로
            # 확정(요청한 1/3(÷3)의 절반 수준까지만 줄였다는 점을 알림).
            _svg_2line_div = 1.0
            if ylabel_lines >= 2:
                need_left_in /= _svg_2line_div
                # [수정] "svg 2줄은 title이 약간 잘림 - 좌측 마진을 1자 더" -
                # 위 1.6배 축소가 살짝 과했던 것으로 재확인 - tic 문자폭
                # 1개분(tick_char_width_in)을 다시 더한다.
                need_left_in += 1.0 * tick_char_width_in
            if y2label_lines >= 2:
                need_right_in /= _svg_2line_div
                # [수정] "svg 2줄은 우측 마진을 0.5글자 더" - 왼쪽과 같은
                # 이유, 우측은 절반(0.5자)만 더한다.
                need_right_in += 0.5 * tick_char_width_in
        else:
            # [수정] "2줄 PNG는 plot 좌우 마진을 지금의 반으로" - PNG는 PDF를
            # 그대로 래스터화하므로(위 "png" 분기는 PyMuPDF가 없을 때만 쓰이는
            # fallback이라 실제로는 거의 실행되지 않음 - create_script의 상단
            # png/jpg 재귀 호출 참고) 이 "else"(pdf/jpg 공용) 분기를 고쳐야
            # 실제로 PNG에도 반영된다. 1줄은 그대로 두고 2줄(왼쪽은 ylabel,
            # 오른쪽은 y2label 각각)일 때만 반으로 낮춘다. PDF/PNG는 EMF/SVG와
            # 달리 margin이 부족해도 title이 사라지지 않고 겹치는 정도라
            # 위험이 낮지만(text-presence는 실측으로 정상 확인), 위 y1
            # offset의 1.5배 gap 확대와 함께 겹침(overlap) 여부까지 PyMuPDF로
            # 직접 측정해서 확인(반으로 줄여도 겹치지 않음, gap 7.9pt 유지).
            _png_2line_div = 2.0
            if ylabel_lines >= 2:
                need_left_in /= _png_2line_div
            if y2label_lines >= 2:
                need_right_in /= _png_2line_div
                # [수정] "png 2줄은 plot 우측 마진을 1.5글자 더 키워요(반잘림)" -
                # 반으로 줄인 게 y2쪽엔 과했던 것으로 재확인 - tic 문자폭
                # 1.5개분(tick_char_width_in)을 다시 더한다.
                need_right_in += 1.5 * tick_char_width_in

        return need_left_in, need_right_in, need_top_in, need_bottom_in

    @staticmethod
    def _extract_emf_texts(data):
        """EMF 파일(바이너리)에서 EMR_EXTTEXTOUTA/W(레코드 타입 83/84) 레코드의
        실제 문자열들을 모두 뽑아낸다. lfHeight 실측(font_compare.py)과 동일한
        레코드 구조 해석 - Record Header(Type 4 + Size 4) + Bounds RECTL(16) +
        iGraphicsMode(4) + exScale(4) + eyScale(4) = offset 36에서 EmrText
        {Reference PointL(8) + nChars(4) + offString(4)} 시작."""
        texts = []
        i, n = 0, len(data)
        while i + 8 <= n:
            rt, rs = struct.unpack_from("<II", data, i)
            if rs < 8 or i + rs > n:
                break
            if rt in (83, 84):
                base = i + 8 + 16 + 4 + 4 + 4
                if base + 16 <= i + rs:
                    _rx, _ry, n_chars, off_string = struct.unpack_from("<iiII", data, base)
                    if off_string and n_chars and i + off_string + n_chars * 2 <= n:
                        s = data[i + off_string:i + off_string + n_chars * 2].decode("utf-16-le", errors="replace")
                        texts.append(s)
            i += rs
        return "\n".join(texts)

    def _check_text_loss(self, outfile, fmt, want_texts):
        """[추가 - 요청] "text가 잘리거나 소실되면 경고 띄우고 사용자가 판단하게
        함 (가능성이 아니라 생겼을 때)" - EMF 드라이버는 캔버스 밖으로 나가는
        텍스트 레코드를 통째로 버리는 경우가 있음(PDF/PNG는 잘리기만 하고
        레코드 자체는 남아 실측상 문제 없음 - 이 세션에서 실측 확인됨).
        추측이 아니라 렌더링 "직후" 실제로 만들어진 결과 파일을 검사해서,
        title/xlabel/ylabel/y2label(2줄이면 각 줄) 문자열이 실제로 빠졌는지
        확인하고, 빠진 경우에만 self.warnings에 채운다. 기존 Save/Print
        플로우가 이미 self.warnings/self.last_size_warning이 있으면
        _show_result_preview_and_confirm으로 결과 미리보기 + 계속/취소를
        묻는 구조라(cathplot_gui.py), 여기서 채우기만 하면 새 UI 없이도
        바로 그 "경고, 사용자 판단" 흐름에 자동으로 올라탄다.
        [수정 - 근본 원인 재해결에 따라 SVG 제외] SVG는 이제 PDF를 PyMuPDF로
        직접 변환해서 만들므로(_convert_pdf_to_svg, text_as_path=1) 글자가
        검색 가능한 텍스트가 아니라 도형 윤곽선이 됨 - 이 함수의 "문자열이
        파일에 있는지" 검사 자체가 통하지 않게 됨(항상 오탐으로 "빠짐" 보고).
        SVG의 실제 텍스트 소실 위험은 원본인 PDF와 동일(PDF는 잘리기만 하고
        레코드가 안 빠짐 - 이미 별도로 안전함이 검증됨)하므로 검사 대상에서
        뺀다."""
        fmt_l = (fmt or "").lower()
        if fmt_l not in ("emf",):
            return
        want = [w for w in want_texts if w]
        if not want:
            return
        try:
            if fmt_l == "emf":
                with open(outfile, "rb") as f:
                    found_text = self._extract_emf_texts(f.read())
            else:  # svg
                with open(outfile, "r", encoding="utf-8", errors="replace") as f:
                    found_text = f.read()
        except OSError:
            return

        missing = [w for w in want if found_text.count(w) < 1]
        if missing:
            _missing_disp = ", ".join(f"'{m}'" for m in missing)
            self.warnings.append(
                f"{fmt_l.upper()} 파일에서 일부 텍스트({_missing_disp})가 캔버스 "
                f"밖으로 밀려나 표시되지 않았습니다(실측 확인). Frame 크기를 "
                f"늘리거나 title/label을 줄여 보세요."
            )

    def create_script(self, plotdef, outfile, fmt="pdf", annotations=None, arrows=None, circles=None):
        # [수정] "PNG/JPG를 PDF 기준으로" - gnuplot의 pngcairo/jpeg 터미널을
        # 각각 따로 부르는 대신, 이미 검증된 pdfcairo 결과를 PyMuPDF로
        # 래스터화해서 만든다(포맷 간 legend/폰트 크기 불일치의 근본 원인이던
        # "터미널마다 다른 텍스트 렌더러" 문제를 없앰 - 오늘 직접 확인).
        # [수정 - 근본 원인 재해결] SVG도 같은 이유로 여기 합류 - gnuplot의 svg
        # 터미널이 PDF와 별개 렌더러라 폰트 절대 크기 차이(EMF/SVG 폰트 비율
        # 재보정으로 이미 고침)뿐 아니라 "text-anchor(오른쪽/가운데 정렬)를
        # 렌더러가 지키지 않아 legend가 box 밖으로 밀리고 tic 숫자가 frame과
        # 겹치는" 문제가 실측(fitz get_text로 실제 글자 좌표 확인)으로 새로
        # 드러남 - PyMuPDF의 Page.get_svg_image()로 이미 검증된 PDF를 SVG로
        # 그대로 변환한다(_convert_pdf_to_svg 참고 - text_as_path=1이라 글자가
        # 도형 윤곽선이 되어 검색/선택은 안 되지만, 위치·비율은 PDF와 완전히
        # 동일함이 실측 확인됨). EMF만 대상이 아님(Word에서 벡터+텍스트로 남아야
        # 해서 gnuplot이 직접 그리는 방식 유지 - EMF는 SVG 같은 text-anchor
        # 문제가 실측상 없었음).
        # PyMuPDF가 없는 환경이면 _rasterize_pdf_to_image/_convert_pdf_to_svg가
        # False를 반환하니 그때만 기존 gnuplot 자체 터미널 방식으로 대체
        # (fallback)한다.
        _fmt_l0 = (fmt or "").lower()
        if _fmt_l0 in ("png", "jpg", "jpeg", "svg"):
            plot_dir0 = os.path.dirname(os.path.abspath(outfile))
            os.makedirs(plot_dir0, exist_ok=True)
            _tmp_pdf = os.path.join(plot_dir0, f".cathplot_raster_{uuid.uuid4().hex}.pdf")
            try:
                self.create_script(plotdef, _tmp_pdf, fmt="pdf", annotations=annotations, arrows=arrows, circles=circles)
                if _fmt_l0 == "svg":
                    if _convert_pdf_to_svg(_tmp_pdf, outfile):
                        return outfile
                elif _rasterize_pdf_to_image(_tmp_pdf, outfile, _fmt_l0):
                    return outfile
                # PyMuPDF 없음 등으로 변환 실패 - 기존 방식으로 계속 진행
            finally:
                try:
                    os.remove(_tmp_pdf)
                except OSError:
                    pass

        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)

        _size_scale = self._compute_size_scale(plotdef)
        _manual_size_override = None
        if not getattr(plotdef, "frame_auto", True) and fmt.lower() != "interactive":
            try:
                _axis_w_in = float((plotdef.frame_width or "").strip() or 0)
                _axis_h_in = float((plotdef.frame_height or "").strip() or 0)
                if (plotdef.frame_unit or "in") == "cm":
                    _axis_w_in, _axis_h_in = _axis_w_in / 2.54, _axis_h_in / 2.54
            except ValueError:
                _axis_w_in, _axis_h_in = 0, 0
            if _axis_w_in > 0 and _axis_h_in > 0:
                _uses_y2 = any(getattr(c, "axis", "y1") == "y2" for c in plotdef.curves)
                _is_print = getattr(plotdef, "is_print_mode", False)
                # [수정 - 심각한 버그] "Axis Frame W=10cm로 지정했는데 실제 축이
                # 8.7~9.2cm로 작게 나옴" - 실측(전체 캔버스 크기 vs 실제 axis
                # border 사각형 크기 직접 비교)으로 확인: 여기서는 마진을
                # panel_scale(_size_scale)만으로 계산해서 "축+마진=전체" 크기를
                # 정했는데, 실제 그 마진을 화면비율로 그리는 _build_plot_commands
                # 안에서는 f_scale(PRINT_FONT_SCALE 등이 곱해진 훨씬 큰 값)로
                # 다시 계산해서 - 두 곳이 서로 다른 스케일로 같은 마진을 계산하는
                # 불일치가 있었음. 실제 마진이 여기서 예산 잡은 것보다 커져서
                # 그만큼 축이 지정한 크기보다 작아짐. _compute_f_scale로 두
                # 호출부가 항상 같은 값을 쓰게 통일한다.
                _margin_f_scale = self._compute_f_scale(plotdef, _size_scale, fmt)
                _nl, _nr, _nt, _nb = self._compute_manual_margins_in(plotdef, _margin_f_scale, _is_print, _uses_y2, fmt=fmt)
                _total_w_in = _axis_w_in + _nl + _nr
                _total_h_in = _axis_h_in + _nt + _nb
                _manual_size_override = f"{_total_w_in:.4f}in,{_total_h_in:.4f}in"
        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile, plotdef, size_override=_manual_size_override, panel_scale=_size_scale),
        ]

        if fmt.lower() != "interactive":
            lines.append(f"set output '{outfile.replace(chr(92), '/')}'")

        self._build_plot_commands(plotdef, lines, is_multiplot=False, annotations=annotations, arrows=arrows, circles=circles, panel_scale=_size_scale, fmt=fmt)

        # [추가] "원래(처음) plot으로 되돌리는 기능 - 2D/3D 모두" - 2D도 마우스
        # 휠/드래그로 확대·이동한 뒤 처음 축 범위로 되돌릴 방법이 없었음. 위에서
        # 이미 만들어진 set xrange/yrange/y2range 줄을 그대로 다시 실행하는
        # 키를 추가한다(범위를 따로 재계산하지 않고 그대로 재사용해 항상
        # 일치하게 함). 그런 줄이 없으면(완전 auto) set autoscale로 대체.
        # [삭제] "gnuplot에서 기본으로 p, n, u를 제공하므로 추가한 b, f, R은
        # 삭제해도 됨(중복 필요 없음)" - f/b(n/p 별칭)는 정말 중복이라 제거.
        # [유지] "중복이더라도 2-D의 R키도 살려둬요" - gnuplot 기본 'u'가
        # 실질적으로 같은 결과를 내긴 하지만, 사용자 요청대로 R도 그대로
        # 남겨둔다(같은 동작을 하는 키가 두 개(u/R) 있는 셈).
        if fmt.lower() == "interactive":
            def _find_range_cmd(prefix, autoscale_name):
                for _l in lines:
                    if _l.startswith(prefix):
                        return _l
                return f"set autoscale {autoscale_name}"
            _reset_cmds = [
                _find_range_cmd("set xrange", "x"),
                _find_range_cmd("set yrange", "y"),
                _find_range_cmd("set y2range", "y2"),
                "replot",
            ]
            lines.append("bind 'R' '" + "; ".join(_reset_cmds) + "'")

        if fmt.lower() == "interactive": lines.append("pause mouse close")
        else: lines.append("set output")

        script_text = "\n".join(lines)
        gnuplot_exe = _resolve_gnuplot_exe()

        if fmt.lower() == "interactive":
            # Interactive는 창을 계속 열어둬야 하고, .plt 파일 자체가 Clean Past
            # Plots/Multi Print/Save 목록 등에서 계속 쓰이므로 기존처럼 파일로 저장
            script_path = outfile.rsplit(".", 1)[0] + ".plt"
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script_text)
            # [추가] gnuplot이 스크립트 에러로 죽을 때 실제 에러 메시지를 잡아서
            # 사용자에게 보여줄 수 있도록 stderr를 파이프로 캡처
            self.last_process = subprocess.Popen(
                [gnuplot_exe, "-persist", script_path], cwd=plot_dir, **_no_console_kwargs(),
                stderr=subprocess.PIPE, stdout=subprocess.DEVNULL
            )
        else:
            # [수정] Batch/Save/Print는 결과 파일(pdf/png/emf 등)만 필요하고 스크립트
            # 자체는 안 남겨도 되는 임시 산출물이므로, 디스크에 .plt 파일을 쓰지 않고
            # gnuplot의 표준입력(stdin)으로 스크립트를 바로 넘겨서 디스크 I/O와
            # 매번 임시파일을 만들고 지우는 오버헤드를 줄인다.
            result = subprocess.run(
                [gnuplot_exe],
                input=script_text, text=True, encoding="utf-8", errors="replace",
                capture_output=True, cwd=plot_dir, **_no_console_kwargs()
            )
            if result.returncode != 0:
                # 실패했을 때만 디버깅할 수 있도록 스크립트를 임시 파일로 남겨둔다
                debug_path = os.path.join(plot_dir, f".cathplot_failed_{uuid.uuid4().hex}.plt")
                try:
                    with open(debug_path, "w", encoding="utf-8") as f:
                        f.write(script_text)
                except OSError:
                    debug_path = None
                stderr_text = (result.stderr or "").strip()
                msg = f"gnuplot 실행 실패 (반환 코드 {result.returncode})"
                if stderr_text:
                    msg += f":\n{stderr_text}"
                if debug_path:
                    msg += f"\n\n(스크립트 보존됨: {debug_path})"
                raise RuntimeError(msg)

            if fmt.lower() == "png":
                _upscale_png_dpi(outfile)

            _want_texts = []
            for _raw in (plotdef.title, plotdef.xlabel, plotdef.ylabel, plotdef.y2label):
                _want_texts.extend(_ln.strip() for _ln in (_raw or "").split("|") if _ln.strip())
            self._check_text_loss(outfile, fmt, _want_texts)

        return outfile

    def create_animation_script(self, plotdef, outfile, annotations=None, arrows=None, circles=None,
                                 duration_sec=20.0, gif_path=None):
        """[신규] X변수(보통 Time)가 늘어남에 따라 선택된 Y1/Y2 curve들이 전부
        동시에 실시간으로 그려지는(progress) 애니메이션을 만든다. 기본은
        Interactive 창(화면 전용)이고, gif_path를 주면 대신 그 경로에 애니메이션
        GIF 파일로 저장한다(gnuplot의 gif animate 터미널 - 파일이라 재생 속도는
        저장 시점에 delay로 굳어지므로 Start/Pause/+-/Q 같은 실시간 컨트롤은
        의미가 없어 GIF 모드에서는 뺀다).

        [설계] "한 프레임"을 데이터 행(row) 단위로 하면 행이 수만 개인 파일은
        애니메이션이 끝없이 걸리고, 반대로 행이 적으면 뚝뚝 끊겨 보임 - 대신
        X 전체 범위(xmin~xmax)를 duration_sec(초) 안에 끝내는 것을 고정하고,
        그 사이를 N_FRAMES개로 균등 분할한 "X값 문턱값(threshold)"으로 매
        프레임마다 "X <= threshold인 점만 그리기"를 반복한다(행 개수와 무관 -
        데이터가 100행이든 10만행이든 항상 duration_sec 안에 끝남). 문턱값
        필터는 gnuplot의 표준 "조건 거짓이면 1/0(정의되지 않음)으로 만들어
        그 점을 건너뛰게" 하는 관용구를 씀.

        [컨트롤 - Interactive만] gnuplot bind로 키보드 단축키를 건다 - Space:
        일시정지/재개, Q: 종료, +/-: 속도(프레임당 대기시간)를 반씩 줄이거나
        늘림. 기존 Interactive의 'R'(원래 범위로 리셋) 키와 안 겹치는 키만 골랐다.

        [진행 표시] 현재 X 위치를 가리키는 세로선(playhead)과 진행률(%)/현재
        X값 텍스트를 매 프레임 갱신해서(고정 ID로 set - "추가"가 아니라
        "갱신") 얼마나 진행됐는지 한눈에 보이게 한다.

        [재사용] 축/제목/legend/주석 등은 _build_plot_commands가 만드는 정적
        plot 스크립트를 "그대로 한 번" 먼저 실행해서(그래야 auto range 등이
        기존과 완전히 동일하게 결정됨) GPVAL_X_MIN/MAX로 실제 X 범위를 읽어온
        뒤, 그 curve 명령들을 문턱값 필터가 걸린 버전으로 바꿔 반복문 안에서
        다시 그린다 - 축 계산 로직을 새로 만들지 않고 기존 것을 그대로 씀."""
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)
        is_gif = bool(gif_path)

        _size_scale = self._compute_size_scale(plotdef)
        # [수정 - 버그] "Animate 켜고 PLOT 누르면 일반 정적 plot이 잠깐 떴다가
        # animation으로 바뀐다" - 실제 X 범위(GPVAL_X_MIN/MAX)를 구하려고
        # 아래에서 정적 plot을 한 번 실행하는데, 예전엔 이걸 실제 화면
        # 터미널("windows")을 이미 연 상태에서 실행해서 이 "범위 확정용" plot
        # 자체가 화면에 그대로 그려져 버렸음(그 다음에야 animation 루프가
        # 시작되어 그 위에 덮어 그림 - 이게 "깜빡"거리는 원인). gnuplot의
        # "unknown" 터미널(화면에 아무것도 안 그리면서 GPVAL_* 등 계산은
        # 그대로 수행하는 용도)로 먼저 이 범위 확정용 plot을 실행해 아무것도
        # 안 보이게 하고, 범위를 다 구한 뒤에야 실제 터미널(화면 or GIF)을
        # 연다 - set 명령(label/object/margin 등)은 터미널과 무관하게
        # 세션에 그대로 남으므로 다시 선언할 필요 없음.
        lines = [
            "set encoding utf8",
            "set term unknown",
        ]
        self._build_plot_commands(plotdef, lines, is_multiplot=False, annotations=annotations,
                                   arrows=arrows, circles=circles, panel_scale=_size_scale, fmt="interactive")

        plot_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "plot \\"), None)
        if plot_idx is None:
            raise RuntimeError("애니메이션을 만들 커브가 없습니다(선택된 Y1/Y2 변수를 확인하세요).")

        static_curve_lines = lines[plot_idx:]  # "plot \\" 줄부터 끝까지(마커 데이터블록 참조 포함) - "unknown" 터미널로 이미 실행됨(화면에 안 보임)

        # curve 명령의 "using (X식):Y컬럼" 부분만 문턱값 필터로 감싼다 - 마커
        # 명령("using 1:2", 괄호 없음)은 이 패턴에 안 걸려 그대로 통과(마커는
        # 애니메이션 없이 항상 표시).
        def _wrap_threshold(m):
            expr = m.group(1)
            return f"using (({expr})<=thresh ? ({expr}) : 1/0):{m.group(2)}"
        animated_curve_lines = [re.sub(r"using \(([^)]+)\):(\d+)", _wrap_threshold, ln) for ln in static_curve_lines]

        lines.append("xmin_anim = GPVAL_X_MIN")
        lines.append("xmax_anim = GPVAL_X_MAX")

        n_frames = 150
        try:
            duration_sec = max(float(duration_sec), 0.5)
        except (TypeError, ValueError):
            duration_sec = 20.0
        frame_pause = duration_sec / n_frames

        lines.append(f"n_frames_anim = {n_frames}")
        lines.append(f"frame_pause_anim = {frame_pause:.6f}")

        if is_gif:
            # [GIF 저장] 실시간 재생이 아니라 파일로 프레임을 굽는 것이므로
            # pause/bind(실시간 컨트롤)는 의미가 없음 - 재생 속도는 gif
            # 터미널의 delay(1/100초 단위)에 그대로 반영해서 저장 시점에
            # 고정한다. 위에서는 "unknown" 터미널로 범위만 구했으므로(화면에
            # 아무것도 안 그려짐), 여기서 처음으로 실제 gif 터미널을 연다.
            delay_cs = max(int(round(frame_pause * 100)), 2)  # 최소 2(=0.02초/프레임) - 0이면 일부 뷰어가 "가능한 빨리"로 해석해 재생이 너무 빨라짐
            gif_w, gif_h = 900, 650
            lines.append(f'set terminal gif animate delay {delay_cs} size {gif_w},{gif_h} optimize')
            lines.append(f"set output '{gif_path.replace(chr(92), '/')}'")
            lines.append("do for [_frame_i=0:n_frames_anim] {")
            lines.append("    thresh = xmin_anim + (xmax_anim - xmin_anim) * _frame_i / n_frames_anim")
            lines.append("    set arrow 9999 from thresh, graph 0 to thresh, graph 1 nohead front lw 1.5 lc rgb \"purple\" dashtype 2")
            # [수정] "Progress 문구가 legend/curve와 겹쳐 보임" - graph
            # 좌표(축 안쪽)라 legend 위치나 curve 데이터 범위에 따라 겹칠 수
            # 있었음 - screen 좌표(캔버스 전체 기준 절대 위치)로 바꿔 축 바깥
            # 왼쪽 아래 여백(제목/legend/curve가 올 일이 없는 자리)에 고정한다.
            lines.append("    set label 9998 sprintf(\"Progress %.0f%%  (X=%.4g)\", 100.0*_frame_i/n_frames_anim, thresh) at screen 0.01, screen 0.02 front tc rgb \"purple\" font \",11\"")
            lines.extend(animated_curve_lines)
            lines.append("}")
            lines.append("set output")
        else:
            # [수정 - 버그] 위 "unknown" 터미널 범위 계산이 끝난 뒤에야 실제
            # 화면 터미널을 연다 - 이전엔 이 시점 이전에 이미 화면 터미널이
            # 열려 있어서 범위 확정용 정적 plot 자체가 화면에 잠깐 보이는
            # "깜빡임" 문제가 있었음.
            lines.append(self._get_terminal_cmd("interactive", outfile, plotdef, panel_scale=_size_scale))
            lines.append("paused_anim = 0")
            lines.append("exit_anim = 0")
            # [주의] 'R'(기존 범위 리셋)/'u'·'n'·'p'(gnuplot 기본 확대이력)와 안
            # 겹치는 키만 사용.
            # [수정 - 버그] "space bar가 안 먹힘" - gnuplot의 bind는 특수키
            # 이름을 "Space"처럼 단어로 못 받고(직접 확인: "bind: cannot
            # parse space/Space" 에러) 실제 스페이스바 문자 그 자체(따옴표
            # 안의 빈칸 한 칸)로 지정해야 함 - 잘못된 키 이름이라 조용히
            # 무시되고 있었음(스크립트 에러로 죽지는 않아서 못 알아챘음).
            # [수정] "키 기능 설명이 진행 끝나고 나서야 나타남 - 시작할 때
            # 나타나야 함" - 안내 문구가 루프 종료 후 딱 한 번만 찍혀서
            # 애니메이션이 도는 동안엔 "Progress N%"만 보이고 조작법이 안
            # 보였음 - 매 프레임 갱신하는 라벨 문구에 조작법을 처음부터
            # 같이 넣는다.
            # [수정 - 근본 원인 재설계] "space bar가 계속 안 먹힘" - 지난
            # 세션에서 화면에 "키 입력 감지 횟수"를 실시간 표시해 실측한 결과
            # 이 숫자가 스페이스바를 눌러도 계속 0에서 안 움직이는 것을
            # 확인함(bind 자체가 아예 안 걸림). 원인: gnuplot 창은 CathPlot이
            # 백그라운드(콘솔 숨김) 프로세스로 띄운 별도 창이라, Windows가
            # 배경 프로세스의 SetForegroundWindow 호출을 조용히 무시하는
            # 보안 정책(포커스 스틸링 방지) 때문에 _force_focus_window_by_title이
            # 실제로는 포커스를 못 넘겨주고 있었던 것으로 추정 - 키 입력이
            # 항상 CathPlot(Tk) 창으로 가버려 gnuplot의 bind가 영영 안 걸림.
            # 이건 우리 코드로 뚫을 수 없는 OS 레벨 제약이라, "gnuplot 창이
            # 키보드 포커스를 갖는다"는 전제 자체를 버린다 - 대신 CathPlot(항상
            # 포커스/마우스 클릭이 오는 쪽) 창에 Pause/Speed/Exit 버튼을 만들고,
            # 그 버튼이 작은 제어 파일(ctrl_path)에 원하는 값을 적어두면,
            # 실행 중인 gnuplot이 매 프레임마다 그 파일을 load해서 반영한다
            # (파일 기반 IPC - 키보드 포커스와 완전히 무관하게 항상 동작).
            # bind는 혹시 포커스가 우연히 gnuplot 쪽에 있는 환경(예: 콘솔에서
            # 직접 gnuplot.exe로 연 경우)을 위한 보너스로 그대로 남겨둔다.
            # [수정 - 버그 발견, 제거] "일시정지 중 q를 누르면 창이 사라지고
            # Resume을 눌러야 다시 살아남" - gnuplot의 windows 터미널이 'q'를
            # 우리 custom bind와 별개로 자체적으로도 처리하는(내용을
            # 지우거나 하는) 것으로 추정되는 버그가 실측 확인됨. Exit는 이미
            # Animation Control 창의 버튼(파일 기반, 이 문제와 무관)이
            # 담당하므로 키보드 'q' bind 자체를 없애 이 혼란을 없앤다.
            lines.append("key_hits = 0")
            lines.append('bind " " "paused_anim = !paused_anim; key_hits = key_hits + 1"')
            lines.append('bind "+" "frame_pause_anim = frame_pause_anim*0.5; key_hits = key_hits + 1"')
            lines.append('bind "-" "frame_pause_anim = frame_pause_anim*2.0; key_hits = key_hits + 1"')
            # [추가] 파일 기반 제어 - CathPlot의 Pause/Speed/Exit 버튼이 이
            # 파일에 paused_anim/frame_pause_anim/exit_anim 값을 다시 써주면,
            # 아래 루프가 매 프레임(그리고 일시정지로 대기하는 동안도 0.1초
            # 간격으로) 이 파일을 load해서 그 값을 그대로 받아들인다. 이
            # 시점엔 아직 파일이 없을 수 있어(GUI가 launch 이후에야 만들 수도
            # 있음) - load 대상이 없으면 gnuplot이 에러를 내므로, Python
            # 쪽에서 프로세스를 띄우기 "전에" 반드시 기본값으로 미리 만들어
            # 둔다(아래 Popen 앞부분 참고).
            ctrl_path = outfile.rsplit(".", 1)[0] + "_ctrl.plt"
            _ctrl_path_gp = ctrl_path.replace(chr(92), "/")
            lines.append(f"_anim_ctrl_path = '{_ctrl_path_gp}'")
            # [수정 - 요청] "키 입력 감지 문구는 삭제" - 파일 기반 제어(버튼)로
            # 재설계가 끝나서 진단용 카운터 표시가 더 이상 필요 없음(bind
            # 자체는 여전히 보너스로 남아있고 화면에 굳이 안내할 필요는
            # 없음 - 버튼 사용을 유도).
            # [수정 - 요청] "Space/버튼 안내 문구도 삭제? 필요하면 +/-/Q 정도만" -
            # 뒤이어 "일시정지 중 q를 누르면 창이 사라짐"이 gnuplot 자체의
            # 기본 'q'=창 닫기 동작과 충돌하는 버그로 확인돼 q bind 자체를
            # 없앴으므로(바로 위 참고), 화면 안내에서도 Q는 뺀다 - 실제로
            # 안전하게 동작하는 +/- 속도 조절만 남긴다.
            _help_text = "+/-: 속도"
            lines.append("do for [_frame_i=0:n_frames_anim] {")
            lines.append("    load _anim_ctrl_path")
            lines.append("    if (exit_anim) { break }")
            lines.append("    while (paused_anim && !exit_anim) { load _anim_ctrl_path; pause 0.1 }")
            lines.append("    if (exit_anim) { break }")
            lines.append("    thresh = xmin_anim + (xmax_anim - xmin_anim) * _frame_i / n_frames_anim")
            lines.append("    set arrow 9999 from thresh, graph 0 to thresh, graph 1 nohead front lw 1.5 lc rgb \"purple\" dashtype 2")
            lines.append(f"    set label 9998 sprintf(\"Progress %.0f%%  (X=%.4g)  {_help_text}\", 100.0*_frame_i/n_frames_anim, thresh) at screen 0.01, screen 0.02 front tc rgb \"purple\" font \",11\"")
            lines.extend(animated_curve_lines)
            lines.append("    pause frame_pause_anim")
            lines.append("}")
            lines.append("unset arrow 9999")
            lines.append(f"set label 9998 sprintf(\"Progress 100%%  {_help_text}\") at screen 0.01, screen 0.02 front tc rgb \"purple\" font \",11\"")
            lines.append("replot")
            lines.append("pause mouse close")

        script_text = "\n".join(lines)
        gnuplot_exe = _resolve_gnuplot_exe()

        if is_gif:
            # 파일 산출물이라 Batch/Save와 동일하게 stdin으로 넘겨서 끝내고,
            # 실패 시에만 디버깅용으로 스크립트를 남긴다(create_script 패턴과 동일).
            result = subprocess.run(
                [gnuplot_exe], input=script_text, text=True, encoding="utf-8", errors="replace",
                capture_output=True, cwd=plot_dir, **_no_console_kwargs()
            )
            if result.returncode != 0:
                debug_path = os.path.join(plot_dir, f".cathplot_failed_anim_{uuid.uuid4().hex}.plt")
                try:
                    with open(debug_path, "w", encoding="utf-8") as f:
                        f.write(script_text)
                except OSError:
                    debug_path = None
                stderr_text = (result.stderr or "").strip()
                msg = f"애니메이션 GIF 생성 실패 (반환 코드 {result.returncode})"
                if stderr_text:
                    msg += f":\n{stderr_text}"
                if debug_path:
                    msg += f"\n\n(스크립트 보존됨: {debug_path})"
                raise RuntimeError(msg)
            return gif_path

        script_path = outfile.rsplit(".", 1)[0] + ".plt"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_text)
        # [추가 - space bar 재설계] gnuplot의 루프가 첫 프레임부터 이 파일을
        # load하므로, 프로세스를 띄우기 전에 반드시 기본값으로 미리 만들어
        # 둔다(없으면 load가 에러를 내고 애니메이션이 즉시 죽음). CathPlot의
        # Pause/Speed/Exit 버튼은 이후 이 파일을 다시 써서 실행 중인
        # gnuplot에 값을 전달한다 - self.last_anim_ctrl_path/last_anim_
        # frame_pause를 호출자(GUI)가 읽어가서 버튼을 만든다.
        with open(ctrl_path, "w", encoding="utf-8") as f:
            f.write("paused_anim = 0\nexit_anim = 0\nframe_pause_anim = %.6f\n" % frame_pause)
        self.last_anim_ctrl_path = ctrl_path
        self.last_anim_frame_pause = frame_pause
        self.last_process = subprocess.Popen(
            [gnuplot_exe, "-persist", script_path], cwd=plot_dir, **_no_console_kwargs(),
            stderr=subprocess.PIPE, stdout=subprocess.DEVNULL
        )
        # [수정 - 근본 원인 재설계, 위 참고] "space bar가 안 먹힘" - bind " "는
        # 이미 올바른 문법인데도 실측(키 입력 감지 카운터가 0에서 안 움직임)
        # 결과 gnuplot 창이 실제로 키보드 포커스를 못 받는 것으로 확인됨.
        # 아래 포커스 강제 시도는 (환경에 따라 우연히 통하는 경우를 위해)
        # 부작용 없으니 그대로 남겨두되, 이제 핵심 컨트롤은 위에서 만든
        # ctrl_path 파일 기반 방식(포커스와 무관하게 항상 동작)이 담당한다.
        _force_focus_window_by_title(os.path.splitext(os.path.basename(outfile))[0])
        return outfile

    _3D_PALETTE_MAP = {
        "rainbow": "set palette rgbformulae 33,13,10",
        "grayscale": "set palette gray",
        "bluewhitered": 'set palette defined (0 "blue", 0.5 "white", 1 "red")',
    }
    _3D_STYLE_MAP = {"lines": "lines", "points": "points", "linespoints": "linespoints"}

    def _time_range_cond(self, raw_ref, tmin, tmax):
        """[추가] "splot 입력 자료에서 time 구간 입력 필요(필요 구간 data만 plot)" -
        tmin/tmax 둘 다 없으면 None(조건 없음). gnuplot에서 좌표값을 NaN(0/0)으로
        만들면 그 지점이 통째로 빠져서(선은 끊기고 점은 안 찍힘) 원본 파일을
        건드리지 않고도 원하는 구간만 그릴 수 있음(직접 테스트로 확인)."""
        parts = []
        if tmin is not None and tmin != "":
            parts.append(f"{raw_ref}>=({tmin})")
        if tmax is not None and tmax != "":
            parts.append(f"{raw_ref}<=({tmax})")
        return " && ".join(parts) if parts else None

    def create_3d_script(self, curves_3d, outfile, fmt="interactive",
                          xlabel="", ylabel="", zlabel="", title="",
                          xlog=False, ylog=False, zlog=False,
                          rot_x=60, rot_z=30, style="lines", palette="rainbow",
                          colorbox=True, annotations_3d=None, arrows_3d=None,
                          equal_xyz=False, surfaces=None, time_min=None, time_max=None,
                          y_min=None, y_max=None, z_min=None, z_max=None):
        """[추가] 3D Plot(splot) - "X/Y1/Y2를 X/Y/Z로 매핑, 여러 세트를 같은 화면에
        겹쳐 그리고 Z값 기준 palette(낮음=파랑, 높음=빨강)로 색칠"하는 기능.
        2D curve와 동일하게 gnuplot이 dat 파일을 직접 읽게(using 컬럼 인덱스)
        해서 별도 데이터 추출 파이프라인 없이 재사용한다.
        curves_3d: [{dat_file, x_col, y_col, z_col, x_shift, title, marker_shape,
        marker_size}, ...] (col은 1-based gnuplot $N 컬럼 번호, 즉 output_no+1과
        동일한 규칙). marker_shape/marker_size는 style이 points/linespoints일 때만
        쓰이며, 색은 Z값 palette 전용이라 세트 구분은 이 Marker 모양 + title(legend)로
        한다("Legend 개념 - 그래프 set가 여럿일 때").
        annotations_3d/arrows_3d: 2D Comment/Arrow와 별개로 3D 팝업에서 입력받은
        (X,Y,Z) 좌표값 전용 주석("이때는 좌표값으로 통일") - {"text","x","y","z","color"} /
        {"x1","y1","z1","x2","y2","z2","color","head_size"}.
        Circle은 gnuplot이 3D 타원/구를 기본 지원하지 않아 이번 단계에서는 미지원.
        surfaces: [{dat_file, label}, ...] - gnuplot splot용 CATHENA surface
        출력(모든 헤더 줄에 '#', 데이터가 "time output_no value" 3컬럼씩 블록
        반복). 원본 파일이 이미 gnuplot이 그대로 읽을 수 있는 형식(#/빈 줄은
        gnuplot이 자동 무시)이라 별도 가공 없이 "using 1:2:3 with lines"로
        바로 splot에 추가한다.
        equal_xyz: "set view equal xyz" - X/Y/Z를 데이터 단위 기준으로 동일 비율
        스케일링. CathPlot 축들은 단위가 제각각(예: Y가 X보다 10000배 큰 값)이라
        기본은 OFF - 켜면 값이 작은 축이 거의 한 점/직선으로 눌려 보일 수 있음
        (직접 테스트로 확인됨). 필요할 때만 사용자가 켜도록 옵션으로만 제공.
        time_min/time_max: "splot 입력 자료에서 time 구간 입력 필요(필요 구간
        data만 plot)" - 둘 다 비우면 전체 구간. curve는 x_shift 적용 전 원본
        time 값 기준으로 판단(사용자가 보는 실제 데이터 구간과 일치시키려고).
        y_min/y_max, z_min/z_max: "마우스 스크롤로 Z 범위가 예측 못하게 바뀜 -
        명시적 입력칸으로" - 비우면 auto(gnuplot 기본 자동 범위), 값을 채우면
        그 범위로 고정(set yrange/set zrange). 2D의 Auto Range와 동일한 개념.
        """
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)

        _fmt = (fmt or "interactive").lower()
        is_interactive = _fmt == "interactive"
        title_disp = os.path.splitext(os.path.basename(outfile))[0]
        lines = ["set encoding utf8"]
        # [추가] "3D Plot도 저장/인쇄 지원" - 2D create_script처럼 확장자별로
        # 맞는 gnuplot 터미널을 골라야 하는데, 3D 다이얼로그는 2D의 Frame
        # Auto/Width/Height 설정이 없어 크기는 고정값(2D의 A4 기본값과 비슷한
        # 비율)으로 둔다.
        _3D_TERMINAL_MAP = {
            "png": "set terminal pngcairo enhanced color font 'Malgun Gothic,14' size 11.7in,8.3in",
            "jpg": "set terminal jpeg size 1600,900 enhanced font 'Malgun Gothic,14'",
            "jpeg": "set terminal jpeg size 1600,900 enhanced font 'Malgun Gothic,14'",
            "svg": "set terminal svg enhanced size 1123,797 font 'Malgun Gothic,14'",
            "eps": "set terminal postscript eps enhanced color font 'Malgun Gothic,14'",
            "emf": "set terminal emf enhanced size 1680,1200 font 'Malgun Gothic,14'",
            "pdf": "set terminal pdfcairo enhanced color font 'Malgun Gothic,14' size 10in,8in",
        }
        if is_interactive:
            lines.append(f"set terminal windows title '{title_disp}' font 'Malgun Gothic,11' size 1000,700")
        else:
            lines.append(_3D_TERMINAL_MAP.get(_fmt, _3D_TERMINAL_MAP["pdf"]))
            lines.append(f"set output '{outfile.replace(chr(92), '/')}'")

        lines.append(f"set view {rot_x},{rot_z}")
        if equal_xyz:
            lines.append("set view equal xyz")
        # [추가] "마우스 스크롤에 따라 Y/Z 범위가 예측 못하게 바뀜 - 명시적
        # 입력칸으로" - 비우면 gnuplot 자동 범위 그대로, 값을 채우면 그 범위로
        # 고정. 2D의 Auto Range/Min/Max와 같은 개념.
        def _range_clause(vmin, vmax):
            has_min = vmin is not None and vmin != ""
            has_max = vmax is not None and vmax != ""
            if not has_min and not has_max:
                return None
            return f"[{vmin if has_min else '*'}:{vmax if has_max else '*'}]"
        _yr = _range_clause(y_min, y_max)
        if _yr: lines.append(f"set yrange {_yr}")
        _zr = _range_clause(z_min, z_max)
        if _zr: lines.append(f"set zrange {_zr}")
        # [추가] "z축이 x,y 평면보다 너무 위로 뜸" - gnuplot 기본 ticslevel(0.5)은
        # x,y 바닥면을 z축 최소값보다 z_range*0.5만큼 아래에 그려서 z축이
        # 바닥에서 떠 보이게 만듦. 0으로 두면 바닥면이 z 최소값과 정확히 맞음
        # (실측 확인: ticslevel은 아래 축 회전각(축 title 각도) 계산에는
        # 영향 없음 - 별개 설정).
        lines.append("set ticslevel 0")
        if xlog: lines.append("set logscale x")
        if ylog: lines.append("set logscale y")
        if zlog:
            lines.append("set logscale z")
            lines.append("set logscale cb")  # Z가 log면 색상 스케일도 log로 맞춰야 색이 고르게 분포함
        lines.append(self._3D_PALETTE_MAP.get(palette, self._3D_PALETTE_MAP["rainbow"]))
        if not colorbox:
            lines.append("unset colorbox")
        # [추가] "X/Y축 title 각도도 축 방향에 맞춰 회전" - Z축과 마찬가지로
        # gnuplot은 xlabel/ylabel도 회전 지정이 없으면 항상 가로로 그리는데,
        # rot_x/rot_z에 따라 3D축이 화면에 투영되는 실제 방향은 다름.
        # "각도 계산이 복잡해서 미확정"으로 남겨뒀던 부분 - 실제 gnuplot
        # 렌더링 결과(pngcairo)에서 원점->각 축 끝점 픽셀좌표를 직접 측정해
        # rot_x/rot_z에 대한 화면투영 공식을 역산으로 구해 반영함(추측이 아니라
        # 84개 (rot_x,rot_z) 조합 실측 후 최소제곱으로 적합, 잔차 1픽셀 미만).
        # 측정으로 확인된 gnuplot 3D 투영(기본 ticslevel/뷰 스케일, X/Y/Z 실제
        # 데이터값 크기와는 무관 - 별도로 확인함):
        #   X축 방향 벡터의 화면 각도 = atan2(-R*cos(rot_x)*sin(rot_z), cos(rot_z))
        #   Y축 방향 벡터의 화면 각도 = atan2( R*cos(rot_x)*cos(rot_z), sin(rot_z))
        #   Z축 방향 벡터의 화면 각도 = 항상 90도(수직) - 기존 zlabel 90도 고정과 일치,
        #     rot_x/rot_z 전체 조합에서 화면 X성분이 항상 정확히 0으로 나와 확인됨.
        # R(z축 높이/xy 바닥면 스케일 비율)도 실측값으로, ticslevel과는 무관함
        # (별도로 확인 - ticslevel 0/0.5 양쪽에서 동일한 값이 나옴).
        _R_3D = 0.7625
        _rx_rad = math.radians(rot_x)
        _rz_rad = math.radians(rot_z)

        def _axis_label_rotate_deg(sx, sy):
            """축 방향 화면투영각도(도)를 구해 텍스트가 뒤집혀 보이지 않도록
            -90~90 범위로 접어서 반환("rotate by"는 180도 차이는 같은 직선이므로
            글자가 거꾸로 보이지 않는 쪽을 고른다)."""
            ang = math.degrees(math.atan2(sy, sx))
            while ang > 90:
                ang -= 180
            while ang < -90:
                ang += 180
            return ang

        _xlabel_rot = _axis_label_rotate_deg(math.cos(_rz_rad), -_R_3D * math.cos(_rx_rad) * math.sin(_rz_rad))
        _ylabel_rot = _axis_label_rotate_deg(math.sin(_rz_rad), _R_3D * math.cos(_rx_rad) * math.cos(_rz_rad))
        # [수정 - 실측 확인] gnuplot의 "windows"(대화형) 터미널은 3D 네이티브
        # xlabel의 임의 각도 "rotate by"를 지원하지 않고 그냥 무시(항상 가로로
        # 표시)함 - 실제 라이브 창을 스크린샷으로 직접 캡처해 확인함. zlabel의
        # 90도만 됐던 건 90이 예외적으로 지원되는 값이었을 뿐. pdf/png(pdfcairo)는
        # 임의 각도가 정상 동작함(별도 렌더링 테스트로 확인). 그래서 interactive는
        # xlabel만 0/90/-90 중 가장 가까운 값으로 스냅해서 최소한 가로/세로는 맞춘다.
        # [수정 - 버그] "3D Plot 초기 화면의 Y-title이 축과 평행하지 않고(t를
        # 눌러야 평행해짐)" - 원인: 이 스냅을 ylabel_rot에도 똑같이 걸고 있었는데,
        # ylabel은 (위 주석대로) 네이티브 set ylabel이 아니라 set label로 대체
        # 렌더링해서 interactive에서도 임의 각도 rotate가 정상 동작함 - 그런데도
        # xlabel과 똑같이 0/90/-90으로 스냅해버려서, 초기 화면(스크립트 생성
        # 시점의 rot_x/rot_z 기준 계산값)은 실제 각도가 아닌 엉뚱한 스냅값으로
        # 나오고, 'R'/'u' 등으로 이 초기 상태로 되돌아갈 때도 계속 스냅값이
        # 나옴. 't' 키를 누르면 그 순간의 회전각으로 다시 계산하는 bind(위
        # _bind_parts, yr 계산)는 이 스냅 로직이 전혀 없어서(진짜 각도 그대로
        # 적용) 그제서야 축과 평행하게 보였던 것. xlabel만 스냅하고 ylabel은
        # 계산된 실제 각도를 그대로 쓴다(초기 화면도 't'를 누른 것과 동일한
        # 각도로 나오게 함).
        if is_interactive:
            def _snap90(a):
                return min((0, 90, -90), key=lambda c: abs(a - c))
            _xlabel_rot = _snap90(_xlabel_rot)
        # [수정] "3-D title의 _,^ 첨자 처리 문제, 그리스 문자 가능하게 (2-D처럼
        # 첨자 등 입력 가능하게)" - 예전엔 "_"를 무조건 "\\_"로 이스케이프해서
        # 항상 리터럴로만 나왔는데, 2D는 "_{...}"/"^{...}"(중괄호) 형태일 때만
        # 실제 첨자로 렌더링하고 그 외(맨 "_"만 있는 보통 파일명 등)는 리터럴로
        # 보이게 하는 자체 규칙(_render_text/_has_enhanced_markup)이 이미 있음 -
        # 3D도 그 규칙을 그대로 재사용해서 2D와 동일하게 동작하게 한다. 그리스
        # 문자(Ω 등)는 noenhanced 모드에서도 UTF-8 그대로 통과되어 별도 처리 불필요.
        # [수정] "tic 숫자와 프레임 간격, 숫자와 title 간격이 축마다 다름 - 가능한
        # 조정" - X/Y/Z 세 군데(네이티브 xlabel, set label로 대체한 ylabel, 네이티브
        # zlabel)가 서로 다른 메커니즘이라 같은 offset 값이어도 실제 화면 간격이
        # 달라 보였음. 기본 회전각(60,30) 기준으로 여러 값을 직접 렌더링/비교해서
        # 세 축의 "숫자-title 간격"이 최대한 비슷해 보이는 조합을 골랐다(v1~v6까지
        # 비교 - v2/v3는 오히려 과했다는 피드백으로 되돌려 축소; "X tic 숫자가 축에
        # 너무 붙어 보인다"는 피드백으로 xtics/ytics 자체의 offset도 추가해 숫자를
        # 축에서 살짝 띄움; "Y title-tic 간격 조금 더"라는 마지막 피드백으로 Y만
        # 한 번 더 늘려 v6 확정).
        # 회전각을 크게 바꾸면 이 값들도 다시 맞춰야 할 수 있음(3D 투영 특성상
        # 완전히 일치시키긴 어려움).
        lines.append("set xtics offset 0,-0.6")
        lines.append("set ytics offset 0.3,-0.3")
        if xlabel:
            _xlabel_text, _xlabel_enh = self._render_text(xlabel)
            lines.append(f'set xlabel "{_xlabel_text}" rotate by {_xlabel_rot:.2f} offset 0,-1.0 {_xlabel_enh}')
        # [수정 - 버그] "y-title도 x-title처럼 축 각도에 비례해서 축과 평행하게" -
        # 직접 테스트로 확인: gnuplot(6.0)은 3D splot에서 set ylabel의 "rotate by"만
        # xlabel/zlabel과 달리 항상 무시함(각도를 줘도 그냥 수평으로만 나옴 -
        # pdfcairo/interactive 둘 다 동일). 반면 set label(텍스트 주석)은 3D에서도
        # rotate by가 정상 적용되는 걸 확인했으므로, 네이티브 ylabel 대신 Y축
        # 근처에 직접 배치한 set label로 대체한다. "축이 거꾸로 보여도 title까지
        # 뒤집을 필요 없음"은 _axis_label_rotate_deg가 이미 -90~90으로 접어주므로
        # 그대로 만족됨.
        # [수정 - 버그] "Y축을 회전해서 반대로 두고 t 누르면 y-title이 tic 숫자와
        # 반대편에 찍힌다" - 위치(graph 1.0, 0.5, 0)를 항상 고정해서 썼는데,
        # 실측 확인: gnuplot은 회전각(rot_x/rot_z)이 90도씩 넘어갈 때마다 Y축
        # tic을 반대쪽 벽으로 옮김(예: rot_x=60,rot_z=30→오른쪽, rot_x=120,rot_z=30→
        # 왼쪽 - rot_x/rot_z 둘 다 90도 경계를 넘는 횟수의 홀짝(XOR)으로 결정됨,
        # 여러 조합 직접 렌더링해 확인). 그래서 label의 graph-x 위치(0.0 vs 1.0)도
        # 같은 규칙으로 반대쪽 벽을 따라가게 해야 tic 옆에 제대로 붙는다.
        # [수정 - 버그] "회전에 따라 title 위치가 확 바뀌는 경우 있음(90/180/270
        # 근방)" - 위 90도-bin XOR 규칙은 rot_x=60,rot_z=90처럼 실제로 렌더링해
        # 확인해보니 label이 축 바깥이 아니라 plot 한복판(데이터 위)에 찍히는
        # 명백한 오류가 있었음(원인: 이 XOR는 "90도 경계를 넘은 횟수의 홀짝"만
        # 보는 대략적인 근사였을 뿐, 실제로 어느 쪽 벽이 화면에서 바깥(farther
        # from box center)인지와는 다른 규칙이었음).
        # 대신 기하학적으로 다시 유도: Y축 변(edge)은 X가 0 또는 1인 두 후보
        # 위치 중 하나인데, 두 후보의 화면투영 위치를 박스 중심 기준으로 비교하면
        # "박스 중심에서 더 먼 쪽"이 X_dir·Z_dir(두 축의 화면투영 방향벡터 내적)의
        # 부호로 정리됨(|Xdir-Zdir| vs |Xdir+Zdir| 비교 -> 내적 부호로 귀결).
        # X_dir=(cos rz, -R cos rx sin rz), Z_dir=(0, R sin rx)이므로 내적은
        # -R^2 sin(rx)cos(rx)sin(rz)에 비례 - 내적<0(=X=1이 더 바깥)일 때 anchor=1.
        # rot_x=60,rot_z=30(기존 정상 확인된 값)과 rot_x=60,rot_z=90(신규 재현/
        # 수정 확인) 둘 다 렌더링으로 직접 검증함.
        _dot_xz = -math.sin(_rx_rad) * math.cos(_rx_rad) * math.sin(_rz_rad)
        _y_anchor_x = 1.0 if _dot_xz < 0 else 0.0
        if ylabel:
            _ylabel_text, _ylabel_enh = self._render_text(ylabel)
            lines.append(f'set label 9001 "{_ylabel_text}" at graph {_y_anchor_x}, graph 0.5, graph 0 '
                         f'rotate by {_ylabel_rot:.2f} offset 4.0,-2.1 {_ylabel_enh}')
        # [수정] "3D 축 title 각도가 축 방향과 다름, 특히 Z축은 90도 다름" -
        # gnuplot은 zlabel을 회전 지정 없으면 항상 가로(수평)로 그리는데, Z축은
        # 화면에서 수직으로 보이니 어긋나 보였던 것. Z축 방향에 맞춰 90도 회전
        # (위 실측으로 Z축은 rot_x/rot_z 전체 범위에서 항상 90도임을 확인함).
        if zlabel:
            _zlabel_text, _zlabel_enh = self._render_text(zlabel)
            lines.append(f'set zlabel "{_zlabel_text}" rotate by 90 offset -1.5,0 {_zlabel_enh}')
        # [추가] "회전 후 키 한 번 누르면 즉시 재정렬" - 마우스로 view를 돌리는
        # 동안 실시간으로 title을 따라가게 하는 건 gnuplot이 지원하지 않지만
        # (드래그 종료/유휴 감지 훅이 없음), 키 입력에는 bind로 반응할 수 있고
        # gnuplot이 현재 회전각을 GPVAL_VIEW_ROT_X/GPVAL_VIEW_ROT_Z로 이미 들고
        # 있어서(splot/replot 이후 갱신됨, 직접 확인) "그 순간의 회전각으로 X/Y
        # title 각도를 다시 계산해서 반영"은 가능함. 'r'/'a' 등 자주 쓰는 키는
        # gnuplot 기본 바인딩(ruler/autoscale 등)과 겹쳐서 비어있는 't'를 사용.
        # curve/surface 여부와 무관하게 이 함수 전체에 공통 적용됨.
        # [수정] "저장/인쇄 안내 문구"를 't' 키, Ctrl+P, P/N/J/E/S 저장 키
        # 복귀 시퀀스 등 여러 곳에서 반복 재설정하므로, 문구가 서로 어긋나지
        # 않게 한 곳에서만 정의해 재사용한다(아래에서 쓰기 전에 rx/rz를 항상
        # 먼저 GPVAL_VIEW_ROT_X/Z로 다시 읽어와야 함 - bind별로 독립 실행돼도
        # gnuplot 변수는 전역이라 't'를 먼저 안 눌렀으면 rx/rz가 없을 수 있음).
        # [수정] "줄이 너무 기니까 () 부분은 다음 줄로" 요청 - "\n"이 gnuplot
        # set label 안에서 실제 줄바꿈으로 동작함을 직접 렌더링 테스트로 확인
        # (noenhanced에서도 지원됨) - Rot X/Z 괄호 부분만 두 번째 줄로 내린다.
        _status_label_cmd = (
            'set label 9003 sprintf('
            '"지금 상태 저장/인쇄 가능 - P:PDF N:PNG J:JPG E:EMF S:SVG Ctrl+P:인쇄  '
            't:재정렬  z:Y·Z범위복원  R:전체초기화\\n(Rot X=%.1f Rot Z=%.1f)", rx, rz) '
            'at screen 0.02, screen 0.055 front noenhanced'
        )
        # [추가] "'t' 누르면 메시지 생기는데 없어지지 않네요? Save 단축키 누르면
        # 해당 파일명만 바뀌고..." - 지금까지 label 9003(상태 안내)/9004(저장·
        # 인쇄 완료 안내)는 다른 동작이 있기 전까지 화면에 계속 남아있었음
        # (자동으로 사라지는 로직이 없었음 - 9004는 다음 저장 시 문구만
        # 바뀔 뿐 사라지지 않음). "잠깐" 뜨는 안내가 되도록 일정 시간(3초) 뒤
        # 자동으로 사라지게 pause+unset+replot을 공통으로 정의해 재사용한다
        # (pause 뒤 unset+replot이 정상 동작함을 직접 렌더링 테스트로 확인).
        _AUTO_HIDE_TAIL_CMDS = "pause 3; unset label 9003; unset label 9004; replot"
        if is_interactive:
            # [주의] label 9001은 ylabel이 있을 때만 위에서 만들어지므로, 없는데
            # "set label 9001 rotate by ..."를 호출하면 존재하지 않는 라벨을
            # 건드리게 됨 - xlabel/ylabel 존재 여부에 따라 필요한 부분만 넣는다.
            _bind_parts = [
                "rx=GPVAL_VIEW_ROT_X", "rz=GPVAL_VIEW_ROT_Z",
                "rrz=rz*pi/180.0", "rrx=rx*pi/180.0",
            ]
            if xlabel:
                _bind_parts.append(f"xr=atan2(-{_R_3D}*cos(rrx)*sin(rrz),cos(rrz))*180.0/pi")
                _bind_parts.append("if (xr>90) {xr=xr-180}")
                _bind_parts.append("if (xr<-90) {xr=xr+180}")
                _bind_parts.append("set xlabel rotate by xr")
            if ylabel:
                _bind_parts.append(f"yr=atan2({_R_3D}*cos(rrx)*cos(rrz),sin(rrz))*180.0/pi")
                _bind_parts.append("if (yr>90) {yr=yr-180}")
                _bind_parts.append("if (yr<-90) {yr=yr+180}")
                # [수정 - 버그] xlabel의 "rotate by xr"과 달리 ylabel은 "at graph
                # ..."로 위치까지 고정해서 썼기 때문에, 마우스로 돌린 뒤 't'를
                # 눌러도 각도만 갱신되고 위치(어느 벽에 붙일지)는 그대로였음 -
                # 위 초기 렌더링과 동일한 규칙(rot_x/rot_z 90도 경계를 넘은
                # 횟수의 홀짝 XOR)을 gnuplot 식으로 재계산해서 위치도 같이 갱신.
                _bind_parts.append("posx=rx-360.0*floor(rx/360.0)")
                _bind_parts.append("posz=rz-360.0*floor(rz/360.0)")
                _bind_parts.append("bx=floor(posx/90.0)%2")
                _bind_parts.append("bz=floor(posz/90.0)%2")
                _bind_parts.append("if ((bx+bz)%2==0) {ax=1.0} else {ax=0.0}")
                _bind_parts.append(
                    f'set label 9001 "{_ylabel_text}" at graph ax, graph 0.5, graph 0 '
                    f'rotate by yr offset 4.0,-2.1 {_ylabel_enh}'
                )
            # [수정] "task bar의 view에도 회전각이 나오는데 굳이 따로 찍을
            # 필요 있나? 저장/인쇄 가능하다는 표시+format 안내가 더 유용할 듯" -
            # 예전엔 회전각(Rot X/Z)과 저장 키 안내를 label 9002/9003 두 줄로
            # 나눠서 보여줬는데, 회전각은 taskbar의 "view"에도 이미 나오므로
            # 중복을 줄이고 "지금 상태 저장/인쇄 가능"이라는 안내를 앞에 붙여
            # 한 줄(9003)로 합침. 회전각 숫자는 Rotate X/Z 입력칸에 그대로
            # 옮겨 적을 때 여전히 편해서 완전히 빼지 않고 뒤에 같이 둠.
            # 저장 키(P/N/J/E/S)와 Ctrl+P 인쇄 bind에서 파일로 replot하기 전에
            # 이 라벨(과 9004 저장완료 안내)만 잠깐 unset하고 복귀 후 다시
            # set해서, 화면에는 보이지만 저장되는 파일에는 안 나오게 한다.
            _bind_parts.append(_status_label_cmd)
            _bind_parts.append("replot")
            # [수정] "'t' 누르면 메시지 생기는데 없어지지 않네요?" - 지금까지는
            # 다음 저장/인쇄/t 재입력 등 다른 동작이 있기 전까지 라벨이 화면에
            # 계속 남아 있었음(자동으로 사라지는 로직이 없었음). "잠깐" 뜨는
            # 안내로 보이게 일정 시간(3초) 뒤 자동으로 사라지도록 pause+unset을
            # 이어붙임(pause 뒤 unset+replot이 정상 동작함을 직접 렌더링
            # 테스트로 확인).
            _bind_parts.append(_AUTO_HIDE_TAIL_CMDS)
            lines.append("bind 't' '" + "; ".join(_bind_parts) + "'")

            # [추가] "그래도 휠을 습관적으로 쓸 텐데, Y/Z 범위가 바뀌면 입력값으로
            # 다시 되돌리는 기법 넣자" - 휠 클릭 드래그(scale) 등으로 Y/Z 범위가
            # 뜻하지 않게 틀어졌을 때, 팝업에 입력했던 값(비웠으면 gnuplot 자동
            # 범위 [*:*])으로 즉시 되돌리는 키. 'z' 키 사용(gnuplot 기본 바인딩과
            # 안 겹침, Z축 되돌리기라는 의미로 기억하기 쉬움).
            _reset_yr = _yr or "[*:*]"
            # [수정 - 버그] z가 auto(빈칸)일 때 "[*:*]"로 되돌리면 그 순간의
            # (이미 확대된) x/y 화면 기준으로 다시 auto 계산해버려 원래
            # 전체 데이터 기준으로 안 돌아가는 문제가 있었음 - 위에서 얼려둔
            # _z0min/_z0max(전체 데이터 기준 최초 auto 결과)를 대신 쓴다.
            _reset_zr = _zr or "[_z0min:_z0max]"
            lines.append(
                f"bind 'z' 'set yrange {_reset_yr}; set zrange {_reset_zr}; replot'"
            )
            # [추가] "원래(처음) plot으로 되돌리는 기능 - 키 조작으로" - 회전각+
            # 배율(scale)+X/Y/Z range를 전부 처음(스크립트 생성 시점) 상태로
            # 되돌린다. "set view rotx,rotz"만 쓰면 scale은 그대로 남는 것으로
            # 보여 배율까지 확실히 1,1로 되돌리려고 4개 값을 전부 명시한다.
            # gnuplot 기본 바인딩과 안 겹치는 대문자 'R'(Reset) 사용.
            # [유지] "gnuplot 기본 p/n/u와 중복이라 b/f/R 삭제해도 됨" 요청 -
            # b/f(n/p 별칭)는 정말 중복이라 제거했지만, 3D의 R은 gnuplot
            # 기본 u/n/p가 다루지 않는 회전각(rot_x/rot_z)과 배율(scale)까지
            # 함께 초기화하므로(u는 range만 원복, 회전은 그대로 남음) 그대로
            # 유지한다(2D의 R은 range 외 보존할 상태가 없어 u와 실질적으로
            # 같아서 제거함 - 3D만 다름).
            lines.append(
                f"bind 'R' 'set view {rot_x},{rot_z},1,1; set xrange [*:*]; "
                f"set yrange {_reset_yr}; set zrange {_reset_zr}; replot'"
            )

        # [추가] "회전+재정렬한 지금 상태를 파일로 저장" - gnuplot 안에서
        # 터미널을 잠깐 바꿔 replot한 뒤 원래 터미널로 복귀하는 방식으로 가능함
        # (직접 테스트로 확인). 형식별로 키를 나눠서 바로 고를 수 있게 함 -
        # gnuplot 기본 키(p/n/e 등)와 안 겹치는 것만 사용, 겹치는 자리는
        # 대문자로 피함. 파일명은 창 제목_view_HHMMSS로 자동 생성(같은 초에 같은
        # 형식으로 두 번 누르면 덮어써질 수 있음 - 낮은 확률이라 허용).
        if is_interactive:
            _restore_term = f'windows title "{title_disp}" font "Malgun Gothic,11" size 1000,700'
            # [추가] "저장은 되는데 인쇄가 안 되니 넣는 게 좋겠다 - 저장 파일과
            # 많이 달라지나?" - EMF 저장('E' 키)과 완전히 같은 터미널/설정을
            # 그대로 재사용하고, 목적지만 파일 대신 "PRN"(gnuplot/Windows의
            # 인쇄 리다이렉트 장치)으로 바꾼 것뿐이라 렌더링 품질은 거의 동일함.
            # "set output PRN"이 에러/멈춤 없이 동작하는 것은 직접 테스트로
            # 확인(기본 프린터가 무엇이든 Windows 인쇄 파이프라인을 그대로 탐).
            # 키는 gnuplot 기본 바인딩과 안 겹치고 관용적으로 익숙한 Ctrl+P 사용.
            # [추가] "save 기능이 동작하는지? 저장됐다는 메시지가 없음 - 어떤
            # 이름으로 어디에 저장했는지 표시 필요" - 저장/인쇄 후 화면으로
            # 복귀하면 label 9004에 "저장됨: 파일경로"(인쇄는 "인쇄 완료")를
            # 잠깐 띄운다. 9003과 마찬가지로 파일로 replot하기 전엔 잠깐
            # unset해서 저장되는 파일에는 안 나오게 한다.
            _print_cmd = (
                'unset label 9003; unset label 9004; '
                'set terminal emf enhanced size 1680,1200 font "Malgun Gothic,14"; '
                'set output "PRN"; '
                'replot; '
                'set output; '
                f'set terminal {_restore_term}; '
                'rx=GPVAL_VIEW_ROT_X; rz=GPVAL_VIEW_ROT_Z; '
                f'{_status_label_cmd}; '
                'set label 9004 "인쇄 완료 (기본 프린터로 전송됨)" '
                'at screen 0.02, screen 0.02 front noenhanced; '
                'replot; '
                f'{_AUTO_HIDE_TAIL_CMDS}'
            )
            lines.append(f"bind 'ctrl-p' '{_print_cmd}'")
            # [수정] "저장 키를 통일성 있게 전부 대문자로(P/N/J/E/S), t는 재정렬
            # 기능이라 그대로 소문자 유지" 요청 - j/s만 소문자였던 걸 J/S로 변경.
            _view_formats = [
                ('P', 'pdfcairo enhanced color font "Malgun Gothic,14" size 10in,8in', 'pdf'),
                ('N', 'pngcairo enhanced color font "Malgun Gothic,14" size 11.7in,8.3in', 'png'),
                ('J', 'jpeg size 1600,900 enhanced font "Malgun Gothic,14"', 'jpg'),
                ('E', 'emf enhanced size 1680,1200 font "Malgun Gothic,14"', 'emf'),
                ('S', 'svg enhanced size 1123,797 font "Malgun Gothic,14"', 'svg'),
            ]
            for _key, _term_spec, _ext in _view_formats:
                # [수정] "FilePath도 상대위치로 적어도 무방함" - gnuplot을 이미
                # plot_dir를 cwd로 고정해 실행하므로(2687줄 부근), 저장 시
                # 폴더 절대경로를 안 붙이고 파일명만 써도 같은 위치에 저장되고
                # 알림(label 9004)에도 짧은 상대경로만 표시됨.
                _outexpr = (f'sprintf("{title_disp}_view_%s.{_ext}", '
                            f'strftime("%H%M%S", time(0)))')
                _cmd = (
                    'unset label 9003; unset label 9004; '
                    f'fn9004={_outexpr}; '
                    f'set terminal {_term_spec}; '
                    f'set output fn9004; '
                    f'replot; '
                    f'set output; '
                    f'set terminal {_restore_term}; '
                    'rx=GPVAL_VIEW_ROT_X; rz=GPVAL_VIEW_ROT_Z; '
                    f'{_status_label_cmd}; '
                    'set label 9004 sprintf("저장됨: %s", fn9004) '
                    'at screen 0.02, screen 0.02 front noenhanced; '
                    'replot; '
                    f'{_AUTO_HIDE_TAIL_CMDS}'
                )
                lines.append(f"bind '{_key}' '{_cmd}'")

        # [추가] "x축은 title과 tic 추가 마진 필요" - x축 title이 회전되면서
        # tic 숫자와 겹치기 쉬워져 아래쪽 여백을 기본보다 넉넉히 확보.
        # [수정] xlabel offset을 -1→-2.2로 늘리면서 아래 여백도 같이 넉넉하게.
        lines.append("set bmargin 6.5")
        if title:
            _title_text, _title_enh = self._render_text(title)
            lines.append(f'set title "{_title_text}" {_title_enh}')

        # [추가] "comment, arrow 등은 3D 전용으로 popup 창에서 입력, 이때는
        # 좌표값으로 통일 (x,y,z)" - 2D의 %/좌표값 토글 없이 항상 실제 데이터
        # 좌표값만 받는다.
        if annotations_3d:
            for i, ann in enumerate(annotations_3d):
                ann_text_raw = (ann.get("text") or "").strip()
                if not ann_text_raw:
                    continue
                try:
                    x, y, z = float(ann["x"]), float(ann["y"]), float(ann["z"])
                except (KeyError, TypeError, ValueError):
                    continue
                _color = (ann.get("color") or "").strip()
                _color_clause = f' textcolor rgb "{_color}"' if _color else ""
                # [수정] "Comment 첨자처리도 되게" - 2D Comment와 동일한
                # _render_text 규칙 재사용(_{...}/^{...}만 실제 첨자, 나머지는 리터럴).
                ann_text, ann_enh = self._render_text(ann_text_raw)
                lines.append(f'set label {i+1} "{ann_text}" at {x},{y},{z}{_color_clause} {ann_enh}')

        if arrows_3d:
            for i, arr in enumerate(arrows_3d):
                try:
                    x1, y1, z1 = float(arr["x1"]), float(arr["y1"]), float(arr["z1"])
                    x2, y2, z2 = float(arr["x2"]), float(arr["y2"]), float(arr["z2"])
                except (KeyError, TypeError, ValueError):
                    continue
                _color = (arr.get("color") or "").strip()
                _color_clause = f' lc rgb "{_color}"' if _color else ""
                _head_size = arr.get("head_size")
                _size_clause = f" size graph {_head_size},15" if _head_size else ""
                lines.append(f'set arrow {i+1} from {x1},{y1},{z1} to {x2},{y2},{z2} head{_size_clause}{_color_clause}')

        # [수정] "Style, Marker Size를 세트별로(curve마다 다르게 줄 수 있으면
        # 세트 목록으로 이동)" - 예전엔 style 파라미터 하나로 전체 curve/surface에
        # 똑같이 적용했는데, 이제 각 curve/surface dict의 "style" 키를 우선
        # 쓰고 없을 때만 이 함수의 style 인자를 방어적 기본값으로 쓴다.
        def _resolve_style(item):
            return (item.get("style") or style or "lines")

        # [추가] "Legend 개념 - 그래프 set가 여럿일 때" - 색은 Z값 전용(palette)이라
        # 여러 세트를 색만으로 구분할 수 없음. 세트 구분은 사용자가 고르는 Marker
        # 모양(pt)으로 하고, 이름은 title로 넣어 gnuplot 표준 key(legend)가
        # "모양+이름"을 보여주게 한다. 세트가 2개 이상일 때만 key를 켠다(1개면 불필요).
        # [수정 - 버그] curves_3d만 보고 key(legend) 켤지 판단해서, surface만
        # 여러 개 있을 때는(예: 서로 다른 파일의 splot 4개) title이 있어도
        # key가 전혀 안 켜져서 어떤 선이 어느 surface인지 구분이 안 됐음 -
        # surfaces도 판단에 포함한다.
        _all_titles = [(c.get("title") or "").strip() for c in curves_3d] + \
                      [(s.get("label") or "").strip() for s in (surfaces or [])]
        has_title = any(_all_titles)
        if has_title and len(curves_3d) + len(surfaces or []) > 1:
            lines.append("set key outside right top box")

        # [추가] "s-plot에 pm3d(Color Palette/입체채색) 옵션 필요?" - CATHENA
        # surface(splot) 데이터는 이미 gnuplot의 grid(격자) 형식(빈 줄로 블록
        # 구분)이라 pm3d로 그리면 선(wireframe) 대신 실제 색이 채워진 연속된
        # 면(surface)으로 보임. curve는 격자 데이터가 아니라 pm3d 자체가 의미가
        # 없어 curve에는 이 옵션을 안 보여주고, surface에만 세트별로 선택 가능
        # ("입체채색이 s-plot에만 해당하는지? curve별로 줄 수 있으면 이동, s-plot에만
        # 적용되면 s-plot에서만 활성화" 요청 반영). depthorder는 surface 중 하나라도
        # pm3d를 쓰면 필요.
        _any_pm3d = any(_resolve_style(s).lower() == "pm3d" for s in (surfaces or []))
        if _any_pm3d:
            lines.append("set pm3d depthorder")

        splot_parts = []
        for c in curves_3d:
            abs_path = c["dat_file"] if os.path.isabs(c["dat_file"]) else os.path.abspath(c["dat_file"])
            try:
                path = os.path.relpath(abs_path, start=plot_dir)
            except ValueError:
                path = abs_path
            path = path.replace("\\", "/")
            x_shift = c.get("x_shift", 0.0)
            # [수정 - 버그] x_shift가 0이면 괄호 없이 "$1"만 썼는데, gnuplot의
            # using 절에서 "$N"은 반드시 괄호로 감싼 수식 안에서만 유효함(단독
            # "$1"은 "column() called from invalid context" 에러) - 2D curve와
            # 동일하게 항상 괄호+수식 형태로 통일한다.
            _raw_ref = f"${c['x_col']}"
            _t_cond = self._time_range_cond(_raw_ref, time_min, time_max)
            if _t_cond:
                # [추가] "time 구간만 plot" - 원본 time 값(shift 적용 전) 기준으로
                # 판단하고, 구간 밖이면 NaN(0/0)으로 만들어 그 지점만 빠지게 한다.
                x_expr = f"(({_t_cond}) ? ({_raw_ref}+{x_shift}) : (0/0))"
            else:
                x_expr = f"({_raw_ref}+{x_shift})"
            using_expr = f"{x_expr}:{c['y_col']}:{c['z_col']}:{c['z_col']}"

            # [수정] Style이 세트별로 바뀌면서 이 curve 자신의 style을 쓴다
            # (curve에는 "pm3d"가 애초에 선택지로 안 뜨므로 항상 lines/points/
            # linespoints 중 하나 - 방어적으로 매핑 안 되면 lines로 fallback).
            _c_style = self._3D_STYLE_MAP.get(_resolve_style(c), "lines")
            # [추가] 세트별 Marker(pt)/크기(ps) - style이 points/linespoints일 때만
            # 의미 있음(lines면 점 모양이 안 보이므로 무시).
            _pt_clause = ""
            if _c_style in ("points", "linespoints"):
                marker_pt = c.get("marker_shape")
                marker_size = c.get("marker_size")
                if marker_pt is not None:
                    _pt_clause += f" pt {marker_pt}"
                if marker_size:
                    _pt_clause += f" ps {marker_size}"

            # [수정] "3-D title의 _,^ 첨자 처리 문제" - 2D와 동일한
            # _render_text/noenhanced 규칙 재사용(위 xlabel/ylabel/zlabel/title과 동일).
            # [수정 - 버그] curve 개수만 보고 title을 넣을지 판단해서, curve 1개+
            # surface 1개처럼 "합쳐서 2개 이상"인데 curve만 있는 쪽 기준으로는
            # 1개라서 legend에서 조용히 빠지는 문제(직접 테스트로 확인) - has_title
            # 판단과 동일하게 curve+surface 합산 개수로 판단.
            title_text = (c.get("title") or "").strip()
            if title_text and (len(curves_3d) + len(surfaces or [])) > 1:
                _title_rendered, _title_enh = self._render_text(title_text)
                _title_clause = f'title "{_title_rendered}" {_title_enh}'
            else:
                _title_clause = "notitle"

            splot_parts.append(f'"{path}" using {using_expr} {_title_clause} with {_c_style}{_pt_clause} palette')

        # [추가] "splot에 x-set 4개 넣으니 구분 안됨" - 여러 surface를 겹쳐 그리면
        # 전부 palette(Z값)로만 색칠돼서, 서로 다른 surface(파일)라도 Z값이
        # 비슷한 구간은 색이 같아 보여 구분이 안 됨. 색은 그대로 Z값 팔레트로
        # 유지하되(어느 쪽이 요청/필요할 수도 있어 색 자체는 안 건드림), surface별로
        # dashtype(선 패턴)을 다르게 줘서 최소한 선 자체는 겹쳐도 구분되게 한다.
        _SURFACE_DASH_CYCLE = ["", "6, 3", "1, 2", "8, 3, 1, 3", "3, 2"]  # 첫 surface는 실선
        for _s_idx, s in enumerate(surfaces or []):
            abs_path = s["dat_file"] if os.path.isabs(s["dat_file"]) else os.path.abspath(s["dat_file"])
            try:
                path = os.path.relpath(abs_path, start=plot_dir)
            except ValueError:
                path = abs_path
            path = path.replace("\\", "/")
            _s_title = (s.get("label") or "").strip()
            if _s_title and (len(curves_3d) + len(surfaces or [])) > 1:
                _s_title_rendered, _s_title_enh = self._render_text(_s_title)
                _s_title_clause = f'title "{_s_title_rendered}" {_s_title_enh}'
            else:
                _s_title_clause = "notitle"
            # surface 원본 파일은 이미 gnuplot이 그대로 읽을 수 있는 형식('#'/빈 줄
            # 자동 무시)이라 컬럼 1:2:3(time:output_no:value)을 그대로 쓴다. time
            # 구간 필터만 컬럼 1(원본 그대로, x_shift 없음)에 적용.
            _s_t_cond = self._time_range_cond("$1", time_min, time_max)
            _s_x_using = f"(({_s_t_cond}) ? ($1) : (0/0))" if _s_t_cond else "1"
            # [수정] 이 surface 자신의 style을 쓴다(pm3d는 surface에만 선택지로
            # 나타나므로 여기서만 체크).
            _s_style_raw = _resolve_style(s)
            if _s_style_raw.lower() == "pm3d":
                # pm3d는 면(facet)이라 dashtype/marker가 적용 안 되므로 생략.
                splot_parts.append(f'"{path}" using {_s_x_using}:2:3 {_s_title_clause} with pm3d')
            else:
                # [수정 - 버그] "Marker 안 나옴" - Style을 Points/Linespoints로
                # 골라도 surface는 항상 "with lines"로 하드코딩돼 있어 Marker가
                # 전혀 안 보였음. curve와 동일하게 이 surface의 style/marker
                # pt·ps를 그대로 적용한다(dashtype은 선이 있을 때만 의미 있음).
                _s_style = self._3D_STYLE_MAP.get(_s_style_raw, "lines")
                _s_dash = _SURFACE_DASH_CYCLE[_s_idx % len(_SURFACE_DASH_CYCLE)]
                _s_dash_clause = f" dashtype ({_s_dash})" if _s_dash else ""
                _s_pt_clause = ""
                if _s_style in ("points", "linespoints"):
                    _s_marker_pt = s.get("marker_shape")
                    _s_marker_size = s.get("marker_size")
                    if _s_marker_pt is not None:
                        _s_pt_clause += f" pt {_s_marker_pt}"
                    if _s_marker_size:
                        _s_pt_clause += f" ps {_s_marker_size}"
                splot_parts.append(f'"{path}" using {_s_x_using}:2:3 {_s_title_clause} with {_s_style}{_s_pt_clause} palette{_s_dash_clause}')

        lines.append("splot " + ", \\\n      ".join(splot_parts))

        # [수정 - 버그] "s-plot에서 마우스 휠(확대/이동)을 누르자마자 z-range가
        # 바뀜 - 오류로 보임" - 직접 실측(splot 후 x-range만 줄이고 GPVAL_Z_MIN/
        # MAX 재조회)해서 확인한 결과, Z(min/max)를 입력칸에 안 채워 auto로
        # 두면 gnuplot이 "현재 화면에 보이는 x/y 구간에 실제로 들어오는
        # 점들만" 기준으로 z 자동범위를 매번 다시 계산함(x/y는 서로 영향
        # 없이 자기 자신의 전체 데이터 기준을 유지하는데 z만 이렇게 동작함) -
        # 그래서 마우스로 x/y를 조금만 옮기거나 확대해도(꼭 z를 직접 만지지
        # 않아도) z range가 계속 따라 바뀌어 보임. curve(with lines)와
        # surface(with pm3d) 양쪽 다 동일하게 재현되는 gnuplot 자체 동작이라
        # (일반 3D에서도 원리상 같이 나지만, s-plot의 채널별 z값 편차가 더
        # 커서 더 눈에 띄었을 뿐) z_min/z_max를 안 채운 경우엔, 방금 계산된
        # "전체 데이터 기준" 자동범위를 이 시점(아직 확대/이동 전)에 값으로
        # 얼려서(freeze) 고정 zrange로 다시 설정한다 - 이후 x/y를 아무리
        # 조작해도 z는 더 이상 재계산되지 않음("초기 입력으로 바꿀 것" 요청
        # 그대로 - 최초 auto 결과를 고정값으로 씀). 'z'/'R' 키로 되돌릴 때도
        # 이 얼린 값을 쓴다(그래야 되돌리기 자체가 그 순간의 확대 상태를
        # 기준으로 다시 auto 계산해버리는 같은 문제를 반복하지 않음).
        if _zr is None:
            lines.append("_z0min = GPVAL_Z_MIN")
            lines.append("_z0max = GPVAL_Z_MAX")
            lines.append("set zrange [_z0min:_z0max]")

        if is_interactive:
            lines.append("pause mouse close")
        else:
            lines.append("set output")

        script_text = "\n".join(lines)
        gnuplot_exe = _resolve_gnuplot_exe()

        if is_interactive:
            script_path = outfile.rsplit(".", 1)[0] + ".plt"
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script_text)
            self.last_process = subprocess.Popen(
                [gnuplot_exe, "-persist", script_path], cwd=plot_dir, **_no_console_kwargs(),
                stderr=subprocess.PIPE, stdout=subprocess.DEVNULL
            )
        else:
            result = subprocess.run(
                [gnuplot_exe],
                input=script_text, text=True, encoding="utf-8", errors="replace",
                capture_output=True, cwd=plot_dir, **_no_console_kwargs()
            )
            if result.returncode != 0:
                debug_path = os.path.join(plot_dir, f".cathplot_failed_3d_{uuid.uuid4().hex}.plt")
                try:
                    with open(debug_path, "w", encoding="utf-8") as f:
                        f.write(script_text)
                except OSError:
                    debug_path = None
                stderr_text = (result.stderr or "").strip()
                msg = f"gnuplot 실행 실패 (반환 코드 {result.returncode})"
                if stderr_text:
                    msg += f":\n{stderr_text}"
                if debug_path:
                    msg += f"\n\n(스크립트 보존됨: {debug_path})"
                raise RuntimeError(msg)

        return outfile

    _A4_SIZES = {
        "portrait": ("8.27in", "11.69in"),
        "landscape": ("11.69in", "8.27in"),
    }

    # [추가] A4 기준 좌2cm/우1cm/상3cm/하2cm 여백은 Auto/비Auto 상관없이 항상
    # 지켜야 하는 요구사항 - 용지 가장자리와 실제 그려지는 그림 사이에 이만큼은
    # 반드시 남긴다 (portrait/landscape 둘 다 물리적 페이지의 왼쪽/오른쪽/위/아래에
    # 동일하게 적용)
    PAGE_MARGIN_LEFT_IN = 2.0 / 2.54
    PAGE_MARGIN_RIGHT_IN = 1.0 / 2.54
    PAGE_MARGIN_TOP_IN = 3.0 / 2.54
    PAGE_MARGIN_BOTTOM_IN = 2.0 / 2.54

    # [추가] SAVE(파일 저장)는 실제 프린터의 인쇄 불가 영역 제약이 없으므로,
    # PRINT 때 쓰는 큰 여백(좌2/우1/상3/하2cm)을 그대로 적용할 이유가 없다 -
    # 용지 가장자리에 살짝 여유만 두는 정도의 작은 여백만 사용한다
    SAVE_PAGE_MARGIN_IN = 0.3 / 2.54

    def create_multiplot_script(self, plots, outfile, fmt="pdf", layout_option="Auto", orientation="portrait", margins=None, spacing=None, keep_script=False, frame_auto=True, frame_width="", frame_height="", frame_unit="in", for_print=True):
        # [수정] "PNG/JPG를 PDF 기준으로" - create_script와 동일한 이유로
        # multiplot(Batch)도 PDF를 먼저 만들어 PyMuPDF로 래스터화한다(자세한
        # 설명은 create_script 쪽 주석 참고).
        # [수정 - 근본 원인 재해결] SVG도 create_script와 동일한 이유(gnuplot
        # svg 터미널의 text-anchor 미준수 - 자세한 설명은 create_script 쪽
        # 주석 참고)로 여기 합류. EMF는 대상 아님(Word에서 벡터+텍스트로 남아야
        # 하고, SVG 같은 text-anchor 문제가 실측상 없었음 - print와 직결되는
        # 포맷이라 이번 세션의 M-P 폰트 재보정/margin 수정을 그대로 유지).
        _fmt_l0 = (fmt or "").lower()
        if _fmt_l0 in ("png", "jpg", "jpeg", "svg"):
            plot_dir0 = os.path.dirname(os.path.abspath(outfile))
            os.makedirs(plot_dir0, exist_ok=True)
            _tmp_pdf = os.path.join(plot_dir0, f".cathplot_raster_{uuid.uuid4().hex}.pdf")
            try:
                self.create_multiplot_script(
                    plots, _tmp_pdf, fmt="pdf", layout_option=layout_option, orientation=orientation,
                    margins=margins, spacing=spacing, keep_script=keep_script, frame_auto=frame_auto,
                    frame_width=frame_width, frame_height=frame_height, frame_unit=frame_unit, for_print=for_print,
                )
                if _fmt_l0 == "svg":
                    if _convert_pdf_to_svg(_tmp_pdf, outfile):
                        return outfile
                elif _rasterize_pdf_to_image(_tmp_pdf, outfile, _fmt_l0):
                    return outfile
            finally:
                try:
                    os.remove(_tmp_pdf)
                except OSError:
                    pass

        self.last_size_warning = None  # 이전 호출에서 남은 경고가 있으면 초기화

        # [수정 - 요청] "M-P에서 페이지당 plot을 정하지 않고 print/save 할 때만
        # (Layout=Auto) 용지 가득 사용, Layout을 1/p~6/p로 명시했을 때는 Axis
        # Frame Auto도 single-plot과 똑같이 '고정 default 크기'를 쓰고 그 이후는
        # Manual(명시 크기)과 똑같은 경로(용지에 안 맞으면 축소, 4p/6p는 남으면
        # 확대)를 타야 한다" - Layout이 "Auto"가 아닌데 frame_auto=True로 들어온
        # 경우, 여기서 미리 요청 크기를 default(10x8cm)로 바꿔주고 frame_auto를
        # False로 내려서, 아래의 기존 Manual 처리 경로를 그대로 재사용한다(별도
        # 코드 경로를 새로 만들지 않아 회귀 위험을 최소화). Layout=Auto는 그대로
        # (지금까지와 동일하게) 용지를 채우는 경로를 그대로 쓴다.
        if frame_auto and layout_option != "Auto":
            frame_width, frame_height, frame_unit = "10.00", "8.00", "cm"
            frame_auto = False

        # [추가] Print(물리적 프린터 인쇄)는 큰 여백(좌2/우1/상3/하2cm)이 필요하지만,
        # Save(파일 저장)는 그런 물리적 제약이 없으므로 작은 여백만 사용한다.
        # [수정 - 재확인] Auto(칸 크기를 페이지에 맞춰 알아서 채우는 모드)는 한동안
        # 절대 여백을 전혀 적용하지 않았음("Auto size에는 적용하지 말 것") - Save로
        # Word 등에 넣을 땐 Word 자체 여백에 맡기면 되니 문제 없었지만, 실제
        # 물리 프린터로 직접 Print해 보니 용지 가장자리까지 꽉 차게 나와(대부분의
        # 프린터는 가장자리를 완전히 인쇄 못 하는 하드웨어 여백이 있음) 잘릴 위험이
        # 있다는 피드백 - Manual과 동일하게 Auto도 Print/Save 모두 최소 여백(사방
        # 0.3cm)을 적용하도록 되돌린다(더 이상 Auto/Manual을 구분하지 않음).
        pm_left = pm_right = pm_top = pm_bottom = self.SAVE_PAGE_MARGIN_IN
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)
        nplot = len(plots)

        # [추가 - 요청] "3/p" - 2/p와 같은 사고방식으로 방향에 맞춰 한 줄로
        # 배치한다: Land(가로가 넓은 용지)는 나란히 3칸(1행 3열, 각 칸은
        # 세로가 긴 모양), Port(세로가 긴 용지)는 위아래로 3칸(3행 1열, 각
        # 칸은 가로가 넓은 모양) - 그래야 3장이 용지를 가득 채움(4/p처럼
        # 2x2에 3장만 넣어 한 칸이 비는 것보다 나음).
        if layout_option == "Auto":
            if nplot <= 1: rows, cols = 1, 1
            elif nplot == 2: rows, cols = (1, 2) if orientation == "landscape" else (2, 1)
            elif nplot == 3: rows, cols = (1, 3) if orientation == "landscape" else (3, 1)
            elif nplot <= 4: rows, cols = 2, 2
            # [수정 - 버그] 5·6장(else 버킷)은 6/p와 똑같은 격자를 쓰는데, 여기는
            # 방향(orientation)을 안 보고 항상 (3,2)였음 - 6/p 자체 규칙(land는
            # 가로로 넓은 2행3열, port는 3행2열)과 안 맞았던 것- 통일한다.
            else: rows, cols = (2, 3) if orientation == "landscape" else (3, 2)
        elif layout_option in ["1/p", "1"]: rows, cols = 1, 1
        elif "2/p" in layout_option: rows, cols = (1, 2) if orientation == "landscape" else (2, 1)
        elif "3/p" in layout_option: rows, cols = (1, 3) if orientation == "landscape" else (3, 1)
        elif "4/p" in layout_option: rows, cols = 2, 2
        elif "6/p" in layout_option: rows, cols = (2, 3) if orientation == "landscape" else (3, 2)
        else: rows, cols = 1, 1

        total_cells = rows * cols
        any_legend_outside = any(p.legend_on and p.legend_pos == "outside right" for p in plots)
        any_y2 = any(any(getattr(c, "axis", "y1") == "y2" for c in p.curves) for p in plots)
        any_y2label = any((getattr(p, "y2label", "") or "").strip() for p in plots)
        any_title = any((p.title or "").strip() for p in plots)
        max_title_lines = max((1 + (p.title or "").count("|")) for p in plots) if plots else 1

        aw, ah = self._A4_SIZES.get(orientation, self._A4_SIZES["portrait"])
        page_w, page_h = float(aw.replace("in", "")), float(ah.replace("in", ""))
        # [추가] "2/p Manual(기본 10x8cm)이 경고 없이 들어가야 하는데 92~94%로
        # 줄어든다" - 아래(약 50줄 뒤) shrink-to-fit 판단이, 지금 이 실제 A4
        # 물리 용지 크기가 아니라 몇 줄 뒤(주석 "1/p Manual 페이지 크기 재설정"
        # 참고)에서 frame_width/height로부터 대략적으로 "추정"한 page_w/page_h
        # (부정확해도 된다고 명시된 값)를 기준으로 판단하고 있었음 - 실측 확인:
        # 이 추정치가 실제 A4보다 작게 나와(2/p Land: 추정 10.54in vs 실제
        # A4 사용가능폭 ~10.5in로 비슷하지만, 아래 안쪽 여백 절반공유까지
        # 반영하면 실제로는 들어가는데도 추정치 기준으로는 못 들어간다고
        # 오판) 불필요하게 축소됨. shrink 판단"만" 이 실제 물리 A4 기준으로
        # 하도록 원본값을 따로 저장해 둔다(page_w/page_h 자체는 아래 기존
        # 추정 로직 그대로 - 다른 용도로 계속 쓰이므로 안 건드림).
        _true_page_w, _true_page_h = page_w, page_h
        # [수정 - 버그] "1/p(단일 plot) + Manual"인데도 전체 캔버스(페이지) 크기가
        # 항상 A4로 고정돼 있어서, 지정한 frame_width/height(예: 10x8cm)는 그
        # A4 페이지 안의 축(칸) 크기로만 쓰이고 실제 출력 파일 전체 크기는
        # Auto와 똑같이 A4로 나오는 문제가 있었음("1/p Manual이 Auto와 크기가
        # 같다" 실측 확인) - 단일 plot(rows=cols=1) + Manual일 때는 단일 plot
        # create_script와 동일한 개념("Frame 크기 = 축 크기, 페이지 = 축+여백")
        # 으로, 페이지 크기 자체를 frame_width/height + 여백으로 다시 잡는다.
        # [수정 - 버그] 위 수정이 rows==1 and cols==1 조건 때문에 1/p에만
        # 적용되고 2/p 이상(칸이 여러 개)에는 전혀 적용 안 돼 있었음 - 실측
        # 확인: 2/p는 Manual/Auto 구분 없이 항상 이 A4 기본값 그대로 나옴
        # ("Manual이 지정 크기 유지 안 됨" 재현). "Manual은 지정한 axis
        # 크기를 기준으로 save/print하고, 용지에 안 맞으면 그 다음에 축소"
        # 원칙에 맞춰 칸이 여러 개일 때도 (칸 크기 x 칸 수 + 칸 사이 간격 +
        # 여백)으로 페이지 크기를 다시 잡는다 - 이후의 shrink-to-fit 로직이
        # 이렇게 계산된 페이지가 실제 용지보다 크면 그때 비율 유지하며 축소한다.
        if not frame_auto and frame_width and frame_height:
            try:
                _fw_in = float(frame_width)
                _fh_in = float(frame_height)
                if (frame_unit or "in") == "cm":
                    _fw_in /= 2.54
                    _fh_in /= 2.54
                # [수정 - 불일치 발견] 아래(실제 레이아웃)의 칸 사이 간격은
                # spacing_in = CELL_SPACING_IN * layout_scale로 칸 크기에 비례해
                # 커지는데, 여기(페이지 크기 추정)는 CELL_SPACING_IN을 그대로
                # (배율 없이) 써서 서로 다른 간격 값을 썼음(실제 영향은 작음 -
                # 칸이 2배 커져도 간격 차이는 0.1in 수준). layout_scale은 이
                # 시점에는 아직 계산 전(cell_w_in 등에 의존)이라 그대로 쓸 수
                # 없어, 같은 기준(10x8cm)으로 미리 근사치를 구해 일관되게 한다.
                _early_scale_est = min(_fw_in / (10.0 / 2.54), _fh_in / (8.0 / 2.54), 2.0)
                _early_spacing = CELL_SPACING_IN * max(_early_scale_est, 0.3)
                # [수정 - 근본 원인 발견] "칸(cell) 크기"를 축(axis) 크기와
                # 똑같이 취급해서(margin_left/right/top/bottom을 전혀 안 더함)
                # 페이지 크기를 추정하고 있었음 - 그런데 몇 줄 아래 "실제" 칸
                # 크기(cell_w_in = axis_w + margin_left + margin_right)는 title/
                # tic/xlabel/legend용 여백을 반드시 포함함. 그 결과 이 초기
                # 추정치가 실제보다 항상 작게 나와서(실측: 2/p Manual 10x8cm
                # Land에서 추정 page_h=3.39in인데 실제 필요한 cell_h는 5.29in -
                # margin_top+bottom 2.14in을 통째로 빠뜨림), 아래 shrink-to-fit이
                # "용지가 실제로는 부족하지 않은데도 부족하다"고 오판해 불필요한
                # 큰 축소(예: 64%)를 걸어버림 - 그 축소가 다시 margin_*·offset
                # 등 다른 계산과 맞물려 옆 칸끼리 라벨이 겹치는 문제로 이어짐
                # ("2/p·4/p 오른쪽 열 Y1/Y2 title 겹침" 재현·원인 규명 과정에서
                # 발견). 정확한 margin은 이 시점엔 아직 계산 전(폰트/legend에
                # 의존)이라 그대로 못 쓰므로, 기준 margin 상수(MARGIN_LEFT/RIGHT/
                # TOP/BOTTOM_IN)를 같은 _early_scale_est로 근사해서 더한다 -
                # 정확하지 않아도 되고(최종 배치는 실제 계산이 다시 하므로),
                # 그동안 빠져있던 "여백 몫"만 추정치에 반영되면 충분하다.
                _early_margin_w = (MARGIN_LEFT_IN + MARGIN_RIGHT_IN) * max(_early_scale_est, 0.3)
                _early_margin_h = (MARGIN_TOP_IN + MARGIN_BOTTOM_IN) * max(_early_scale_est, 0.3)
                page_w = (_fw_in + _early_margin_w) * cols + _early_spacing * (cols - 1) + pm_left + pm_right
                page_h = (_fh_in + _early_margin_h) * rows + _early_spacing * (rows - 1) + pm_top + pm_bottom
            except ValueError:
                pass
        printable_w = page_w - pm_left - pm_right
        printable_h = page_h - pm_top - pm_bottom

        # [핵심 재설계] "frame 크기 = legend까지 포함한 낱장 이미지(칸) 전체 크기"로
        # Auto/Manual을 통일한다. 기존엔 Auto는 "칸=이미지 전체"였지만 Manual은
        # "frame_width/height=축(axis)만"이라, 사용자가 입력한 크기보다 실제
        # 출력물이 여백만큼 더 커지고 그 여백이 입력 크기 대비 상대적으로 과도하게
        # 크게 보이는 문제(예: "10x8cm 2/p인데 좌우 마진/간격/legend가 너무 큼")가
        # 있었음. 이제 두 경우 모두 "칸(이미지 한 장) 전체 크기 vs 기준(10x8cm)의
        # 비율"로 폰트/여백/간격을 함께 정하고(한 장의 이미지처럼 확대/축소),
        # 축 크기는 칸에서 여백을 뺀 나머지로 역산한다(단일 plot의 frame 개념과 통일).
        REF_W_IN = 10.0 / 2.54
        REF_H_IN = 8.0 / 2.54

        # [추가] Manual+grow 경로와 동일하게, 칸이 많을 때(4/p 이상)는 용지를
        # 100% 꽉 채우면 바깥쪽이 딱 붙어 보이므로 살짜 못 미치게(가로 95%,
        # 세로 90%) 채운다. 칸이 적을 때(1/p, 2/p)는 비율 유지(contain-fit)
        # 자체가 이미 여유를 만들어주므로 그대로 100% 기준을 쓴다.
        _auto_fill_w = 0.95 if total_cells >= 3 else 1.0
        _auto_fill_h = 0.90 if total_cells >= 3 else 1.0
        if frame_auto:
            cell_w_in = (printable_w * _auto_fill_w - CELL_SPACING_IN * (cols - 1)) / cols
            cell_h_in = (printable_h * _auto_fill_h - CELL_SPACING_IN * (rows - 1)) / rows
        elif frame_width and frame_height:
            try:
                cell_w_in, cell_h_in = float(frame_width), float(frame_height)
            except ValueError:
                cell_w_in, cell_h_in = REF_W_IN, REF_H_IN
            if (frame_unit or "in") == "cm":
                cell_w_in /= 2.54
                cell_h_in /= 2.54
        else:
            cell_w_in, cell_h_in = REF_W_IN, REF_H_IN

        # [수정] 단일 plot과 동일한 이유로, 칸(cell)이 portrait 모양(세로>가로)이면
        # 기준(REF)도 같이 돌려써서 baseline을 회전만 한 경우 항상 scale=1.0이
        # 나오게 한다(안 그러면 landscape 칸이 더 크게 스케일되어 legend/폰트가
        # 상대적으로 커 보이는 문제가 있었음).
        _ref_w, _ref_h = (REF_H_IN, REF_W_IN) if cell_w_in < cell_h_in else (REF_W_IN, REF_H_IN)
        # [수정 - 재검토, 캡 재도입] "M-P 결과의 폰트가 single-plot보다 확연히
        # 커 보임 - single-plot을 기준으로 축소/확대함이 좋겠다" - 실제
        # single-plot Auto(_compute_size_scale)는 frame_auto일 때 항상 scale=
        # 1.0(폰트 고정, 축만 페이지 크기에 맞춰 커짐/작아짐)인데, multiplot
        # Auto는 여기서 칸이 기준(10x8cm)보다 크면(1/p처럼 거의 한 페이지를
        # 다 쓰는 경우 특히) 폰트도 같이 비례해서 키워서, 같은 내용의
        # single-plot Auto보다 글자가 훨씬 크게 나오는 것으로 실측 확인됨(예:
        # 1/p Auto A4 전체 - font_panel_scale이 2배 이상). 예전에 이 상한을
        # 없앤 이유("칸이 커져도 폰트가 안 커지면 비율이 안 맞아 보임")는
        # single-plot과 나란히 비교하지 않은 상태에서의 판단이었던 것으로
        # 보임 - Axis Frame Auto일 때는 single-plot Auto와 동일하게 상한
        # 1.0을 다시 둬서 폰트를 고정하고(Manual만 이전처럼 지정 크기에 비례해
        # 커지게 둔다 - single-plot Manual과 같은 방식).
        # [수정 - 버그] single-plot _compute_size_scale과 동일한 문제 - 상한이
        # 없어서 기준(10x8cm)보다 훨씬 큰 Manual 칸(예: 40x30cm)에서 title이
        # 폭주해 plot을 뒤덮는 문제가 실측 확인됨 - 같은 상한(2.0)을 공유한다.
        # [주의] 이 경고는 Manual일 때만 낸다 - Auto는 1/p A4 전면처럼 정상적
        # 사용에서도 흔히 2배를 넘어가므로(아래 sqrt 완화로 별도 처리됨) 경고
        # 대상이 아님.
        _raw_cell_ratio = min(cell_w_in / _ref_w, cell_h_in / _ref_h)
        if not frame_auto and _raw_cell_ratio > 2.0:
            self.warnings.append(
                f"Frame 크기가 기준(10x8cm) 대비 {_raw_cell_ratio:.1f}배로 너무 커서 "
                f"폰트 배율을 2.0배로 제한했습니다. 이보다 작은 Manual 크기를 권장합니다."
            )
        size_scale = max(min(cell_w_in / _ref_w, cell_h_in / _ref_h, 2.0), 0.3)
        if frame_auto and size_scale > 1.0:
            # [수정 - 재조정] "완전히 고정하면 큰 축에서 폰트가 상대적으로
            # 작아 보임(1.0 상한 실측 피드백)" - 완전 고정(상한 1.0)과 이전의
            # 완전 선형(상한 없음, "너무 커짐") 사이 중간값으로, 기준(10x8cm)
            # 보다 칸이 N배 크면 폰트는 그 절반 배율(√N)만 커지게 한다(예:
            # 축 4배 -> 폰트 2배). size_scale<=1(칸이 기준보다 작은 경우)은
            # 그대로 선형 유지(이 조정과 무관, 원래도 문제 없었음).
            size_scale = size_scale ** 0.5
        font_panel_scale = size_scale
        # [추가 - 근본 원인 수정, 재조정] M-P(멀티플롯)의 margin_left/right/
        # top/bottom·legend_boost 등은 font_panel_scale에서 바로 파생되고
        # _build_plot_commands의 f_scale(단일 plot과 공유하는 CAIRO_FONT_
        # RENDER_FIX 보정)과는 완전히 별개 변수라서, f_scale 쪽만 고쳐서는
        # M-P의 margin이 "커진 실제 폰트 크기"를 따라가지 못해 텍스트가
        # 여백을 침범할 위험이 있었음(font_panel_scale에 이 보정을 적용).
        # [주의 - 재발견한 버그] size_scale 자체에 곱하는 방식을 처음
        # 시도했었는데, Auto에서는 margin_scale/layout_scale이 "size_scale>=1
        # 이면 1.0으로 상한 + 4/p 이상은 추가로 0.5배"로 캡이 걸려 있어서
        # (칸이 커져도 margin/간격이 무한정 커지지 않게 하는 기존 안전장치),
        # size_scale을 아무리 키워도 4/p·6/p의 margin_scale은 항상 이 캡에
        # 걸린 "동일한 고정값"으로 수렴해버려 폰트만 커지고 margin은 그대로인
        # 회귀가 재현됨(실측: 4/p 렌더링에서 Panel 3/4 제목이 위 행의 X
        # title과 겹침 - 1/p, 2/p는 font_panel_scale을 직접 쓰는 경로라
        # 문제 없었지만 4/p, 6/p만 이 캡 때문에 보정이 무력화됨). margin_scale/
        # layout_scale 자체(칸 크기에 따른 캡 로직)는 그대로 두고, 대신
        # 아래 _floor_scale(4/p 이상에서 margin_scale을 그대로 쓰는 지점)에
        # 이 보정을 별도로 곱해서 "캡이 걸린 뒤의 값"에도 이 보정이 항상
        # 반영되게 한다(아래 _floor_scale 정의부 참고).
        if (fmt or "").lower() in ("pdf", "png", "jpg", "jpeg"):
            font_panel_scale *= CAIRO_FONT_RENDER_FIX
        elif (fmt or "").lower() == "emf":
            # [수정 - 근본 원인, cairo와 같은 패턴 적용] EMF도 실제 폰트 크기가
            # (아래 _build_plot_commands의 f_scale에서) PDF/PNG와 다른 배율로
            # 조정되는데, 그 조정이 font_panel_scale에는 전혀 반영이 안 돼서
            # margin_left/right/top/bottom·tick_char_width_in_mp 등(모두
            # font_panel_scale에서 파생)이 "커진 실제 EMF 폰트 크기"를 전혀
            # 모른 채 계산됨 - 그래서 폰트만 키우면 margin이 안 따라와서 tic/
            # legend가 겹치는 회귀가 났었음(오늘 먼저 시도했다가 되돌린 것).
            # cairo와 동일하게 여기(font_panel_scale)에서 미리 반영해서 margin
            # 계산도 같이 커지게 한다. 실측(같은 pt·같은 물리 캔버스에서 title
            # 높이 정규화 비교, 20pt=0.847배/40pt=0.745배)으로 EMF가 PDF/PNG
            # 대비 작게 나옴을 확인 - CAIRO_FONT_RENDER_FIX(1.5)와 같은 목표
            # (EMF/SVG 수준의 절대 크기)에 맞추려면 EMF_FONT_RENDER_FIX(1.8)가
            # 필요.
            font_panel_scale *= EMF_FONT_RENDER_FIX
        # [참고] "작은 Manual 칸(예: 8x6cm)에서 legend/여백이 과도하게 커서 실제
        # axis가 쪼그라든다" - 간격(spacing)을 0으로 해봐도 거의 안 바뀌는 것으로
        # 실측 확인(원인은 spacing이 아니라 margin/legend 자체) - 폰트(글자
        # legibility)는 size_scale에 선형으로 유지하되, margin과 칸 사이 간격은
        # 작은 칸일수록 더 적극적으로(비율 이상으로) 줄어들게 한다.
        # [수정] "1/p, 2/p는 지정 크기를 가급적 그대로 지키고, 4/p, 6/p는 칸이
        # 작아지는 만큼 공간 활용을 위해 더 적극적으로 줄이자" - 칸 수가 많을
        # 때만(4/p 이상) 이 적극적인 축소를 적용하고, 1/p, 2/p는 원래(선형)
        # 방식을 그대로 쓴다.
        # [수정 - 버그] size_scale>=1(칸이 기준보다 큰 경우 - Auto 레이아웃은
        # 보통 이럼)에서 세제곱을 그대로 적용하면 마진이 오히려 폭발적으로
        # 커져서(예: size_scale=2 -> margin_scale=8) 축이 거의 안 남는 심각한
        # 문제가 있었음(Auto 4/p 실측: 축 h=38pt까지 쪼그라듦) - 이 적극적 축소는
        # "칸이 기준보다 작을 때(size_scale<1)"에만 의미가 있으므로, 그 경우에만
        # 적용하고 그 외(size_scale>=1)에는 선형을 유지한다.
        # [수정 - 버그, 3/p 추가 때 놓침] 위 주석은 처음부터 "4/p 이상"이라고
        # 명시했는데 실제 조건은 total_cells>=3이라 3/p까지 이 세제곱 축소를
        # 받고 있었음 - 실측(3/p, Manual 6x4cm)으로 재현: margin_scale이
        # 0.5**3=0.125까지 줄어들어(2/p였다면 0.5**1=0.5) title이 확보된 여백
        # 밖으로 밀려나 PDF에서 완전히 안 그려짐(텍스트 자체는 PDF 안에 있으나
        # 렌더링 가능 영역 밖 - PyMuPDF 좌표로 직접 확인). 주석이 원래부터
        # 뜻했던 대로 4로 바로잡는다(3/p는 1/p·2p와 같은 "지정 크기 최대한
        # 유지" 그룹에 속함 - 단일 행/열 배치라는 점도 1/p·2p와 같음).
        _margin_aggr = 3.0 if total_cells >= 4 else 1.0
        margin_scale = size_scale ** _margin_aggr if size_scale < 1.0 else size_scale
        layout_scale = size_scale ** _margin_aggr if size_scale < 1.0 else size_scale
        # [수정] "plot간 여백/간격이 너무 큼, 좌우 여백도 최소화(절대마진
        # 미적용)" - 폰트/legend(size_scale, font_panel_scale)는 용지가 큰 만큼
        # 커지게 두지만, margin/간격은 그와 같은 비율로 같이 커지면 두 칸의
        # 마진+간격이 합쳐져 눈에 보이는 여백이 지나치게 커진다. Auto는
        # margin_scale/layout_scale만 1.0으로 상한을 둬서 여백/간격은 기준
        # 크기 그대로 유지하고, 남는 공간은 전부 axis(실제 그림 영역)로 가도록
        # 한다 (Manual은 사용자가 지정한 크기이므로 그대로 비례 유지).
        # [수정] 이 캡을 1/p, 2/p에만 걸어뒀었는데, 4/p, 6/p도 size_scale>=1이면
        # (페이지가 기준보다 큰 보통의 경우) 똑같이 margin이 과도하게 커져서
        # "4/p, 6/p도 plot간 간격이 너무 큼" 문제가 재현됐음 - 칸 수 상관없이
        # Auto 전체에 적용한다.
        if frame_auto:
            margin_scale = min(margin_scale, 1.0)
            layout_scale = min(layout_scale, 1.0)
            # [수정 - 되돌림] "4/p, 6/p도 plot간 간격을 최소한으로" 요청으로
            # margin_scale에 추가로 *0.5를 걸었었는데, y1/y2 label(회전 텍스트)
            # 폭에는 이 margin_scale을 더 줄이는 것과 무관한 최소 필요 크기가
            # 있어서 - 그보다 더 줄이면 옆 칸 label과 겹쳐버림(실측 확인: "Pressure
            # (MPa)"/"Temperature (C)"가 옆 칸과 겹침). 대신 아래(margin_left/
            # right 계산부)에 top/bottom과 똑같은 방식의 floor(최소 절대 여백)를
            # 추가해서, 겹치지 않는 한도까지만 최대한 줄어들게 한다.
            if total_cells >= 3:
                margin_scale *= 0.5
                layout_scale *= 0.5
        spacing_in = CELL_SPACING_IN * layout_scale
        # [추가] "Auto는 plot간 아래위 간격을 키우고, 좌우 간격은 title 대문자
        # 기준 약 2자 폭이 되도록만 늘려달라" - 지금까지 spacing_in은 가로/세로
        # 공통이었는데, 방향별로 다르게 늘리기 위해 분리한다(Manual은 요청
        # 대상이 아니므로 그대로 동일하게 둔다).
        _extra_bottom_in = 0.0
        if frame_auto:
            _max_title_size_sp = max((float(p.title_size or 14) for p in plots if (p.title or "").strip()), default=14.0)
            _title_pt_sp = _max_title_size_sp * font_panel_scale
            _title_char_w_in = (0.0055 if for_print else 0.0049) * _title_pt_sp
            _title_font_ratio = max((_font_width_ratio(p.title_font) for p in plots if (p.title or "").strip()), default=1.0)
            _title_char_w_in *= _title_font_ratio  # 폰트 대체 시 실제 폭 비율로 보정
            _title_char_h_in = _title_pt_sp / 72.0  # 대문자 1자 "높이"(요청대로 폭이 아니라 높이)
            # [수정 - 요청] "plot간 간격은 최소로 하든지 없애서 각 plot을 조금이라도
            # 키울 것" - 기존 3.0배/2자 폭은 미관을 위해 일부러 넉넉하게 둔
            # 값인데, 그만큼 axis가 작아지는 대가가 있음(아래 grow 단계가 이
            # 간격을 줄인 만큼 axis를 키워줌) - 절반으로 줄여 axis 확보에
            # 더 쓴다.
            # [수정 - 재축소] "M-P 칸 사이 간격 최소화(2/p~6/p, Auto/Manual 전부)"
            # 요청으로 기존 1.5배/1자 폭을 더 줄임 - 아래에서 2/p~6/p x Port/
            # Land x Y1/Y2 2줄 조합 전부 텍스트 소실/겹침 없음 재확인 후 확정.
            spacing_h_in = spacing_in * 0.5
            spacing_w_in = 0.4 * _title_char_w_in
            # [수정] "2/p 상하 간격을 title 대문자 1자 높이만큼 줄이고, 이를
            # bottom 마진에 넣어달라" - margin_top은 그대로 두고 margin_bottom
            # 에만 더한다(뒤에서 margin_bottom 계산 후 반영, 여기선 줄일 양/
            # 더할 양만 기록). margin_top/bottom을 "똑같이" 늘리면 간격이
            # 상쇄돼버렸던 이전 버그와 달리, bottom에만 넣으면 위쪽 칸-아래쪽
            # 칸 사이 간격은 실제로 줄고 아래쪽 바깥 여백(마지막 행의 bottom)만
            # 커진다.
            # [수정 - 버그 발견] margin_bottom은 모든 칸(패널)이 공유하는 값이라
            # 이 "간격->마진 이전"이 순가치는 0(간격에서 뺀 만큼 마진에 더함)
            # 이어야 하는데, 실제로는 margin_bottom이 "칸 사이"뿐 아니라 그
            # 값을 쓰는 모든 패널(2/p Port면 위/아래 둘 다)의 axis_h를 각자
            # 그만큼 깎아버림 - 그런데 그 여백이 "필요한" 곳은 위 칸 하나뿐
            # (위 칸의 bottom<->아래 칸의 top 사이 간격용)이라, 아래 칸(맨
            # 마지막 행)은 그 여백이 전혀 필요 없는데도 axis_h만 손해를 봄
            # ("2p Port 아래위가 작아짐, 아래 마진을 줄여달라" 피드백과 일치).
            # rows>1(실제로 위아래로 쌓이는 2/p Port)에서만 이 문제가 생기므로
            # 그 경우엔 이 보정 자체를 걷어내(margin_bottom을 원래 값 그대로
            # 둬서 axis_h를 돌려주고, spacing_h_in 축소분만큼 칸 사이 간격도
            # 같이 줄어들게) 둔다. rows==1(2/p Landscape, 칸이 가로로만 나란함)은
            # 이 "칸 사이 세로 간격" 개념 자체가 없어 원래도 실질적 부작용이
            # 없었으므로 기존 동작을 그대로 유지한다.
            if total_cells == 2:
                spacing_h_in = max(spacing_h_in - _title_char_h_in, 0.0)
                if rows == 1:
                    _extra_bottom_in = _title_char_h_in
        else:
            spacing_h_in = spacing_w_in = spacing_in
        if frame_auto:
            # 위에서 base(미scale) spacing으로 어림잡았던 칸 크기를, 실제
            # spacing_in(scale 적용)으로 다시 나눠 정확히 재계산한다
            cell_w_in = (printable_w * _auto_fill_w - spacing_w_in * (cols - 1)) / cols
            cell_h_in = (printable_h * _auto_fill_h - spacing_h_in * (rows - 1)) / rows
            # [수정 - 개념 정정] "x:y 비율"은 칸(cell, 마진/legend 포함 전체)이
            # 아니라 좌표축(axis) 자체의 가로:세로 비율을 말하는 것임(그래서
            # 체크박스도 "Axis Frame Auto") - 예전엔 여기서 칸 자체를 기준(10x8)
            # 비율로 contain-fit했는데, 마진이 가로/세로에 비대칭으로 붙어서
            # (특히 legend가 있는 오른쪽, title이 있는 위쪽) 실제로 보이는 axis
            # 박스는 그 비율과 다르게 나왔음. 마진을 먼저 구한 뒤(아래) axis
            # 자체를 기준 비율로 맞추는 것으로 이동함 - axis_w/axis_h 계산부
            # (아래 "axis_w = max(cell_w_in - margin_left - ...")를 참조.

        # [추가] Y축 tic 숫자 자릿수가 많을수록(예: 10000 이상) 여백이 부족해
        # 잘리거나(왼쪽) title과 겹치던(오른쪽 Y2) 문제 - 실제 플롯들의 Y1/Y2
        # 범위를 미리 계산해서 필요한 자릿수를 추정하고, 기본 가정(3자리)보다
        # 많으면 그만큼 각각(Y1=왼쪽, Y2=오른쪽) 여백을 더 확보한다
        # [수정] "자릿수(peak값 정수부 길이)"만 보면 소수 tic("0.09")나 음수
        # tic("-8500")의 실제 표시 폭을 과소평가함(부호/소수점이 자릿수에는 안
        # 잡힘) - 실제 최소/최대/중간값을 포맷해 tic 라벨 문자열 길이를 직접
        # 재고, 문자 폭(font_panel_scale 기준) 물리 공식으로 여백을 구한다.
        def _tick_label_chars_mp(plotdef_, axis_name):
            try:
                nice = self._nice_axis_range(plotdef_, axis_name)
            except Exception:
                nice = None
            if not nice:
                return 4
            y_lo, y_hi, _ = nice
            max_len = 1
            for v in (y_lo, y_hi, (y_lo + y_hi) / 2.0):
                if abs(v) < 1e-9:
                    s = "0"
                elif float(v).is_integer() and abs(v) < 1e15:
                    s = f"{v:.0f}"
                else:
                    s = f"{v:.3g}"
                max_len = max(max_len, len(s))
            return max_len

        max_y1_chars = 4
        max_y2_chars = 4
        for p in plots:
            max_y1_chars = max(max_y1_chars, _tick_label_chars_mp(p, "y1"))
            max_y2_chars = max(max_y2_chars, _tick_label_chars_mp(p, "y2"))
        # [수정] "Interactive(화면) multiplot에서도 tick 여백 계산이 print
        # 계수(0.0055)로 고정돼 있던 버그" - 바로 위 title 간격 계산(for_print
        # 분기)과 달리 여기는 분기가 빠져 있었음. is_print_mode 인자가 없는
        # 함수라 for_print로 판단(같은 함수 상단에서 이미 이 값을 씀).
        _tick_font_ratio = max(
            (_font_width_ratio(p.ylabel_font) for p in plots if getattr(p, "ylabel_font", None)),
            default=1.0,
        )
        _tick_char_width_in_mp = (0.0055 if for_print else 0.0049) * (9 * font_panel_scale) * _tick_font_ratio
        extra_left_margin_in = max(0, max_y1_chars - 4) * _tick_char_width_in_mp
        extra_right_margin_in = max(0, max_y2_chars - 4) * _tick_char_width_in_mp if any_y2 else 0
        # [추가] Scientific("1.5e+03")/Power10("10^3") 형식은 일반 숫자와 길이가
        # 달라서, 자릿수 기반 계산과 별개로 형식에 따라 추가 여백을 더한다.
        # [수정] 이 함수는 plots 리스트(여러 plot)를 다루므로, 정의되지 않은
        # 단수 plotdef를 참조하면 안 됨 - 리스트 중 어느 하나라도 해당 형식/
        # 2줄 title을 쓰면 그 여백을 확보하도록 max_title_lines와 같은 방식으로 계산
        _y1fmt_label = "Scientific" if any((getattr(p, "y1fmt", "Normal") == "Scientific") for p in plots) else \
                       ("Power10" if any((getattr(p, "y1fmt", "Normal") == "Power10") for p in plots) else "Normal")
        _y2fmt_label = "Scientific" if any((getattr(p, "y2fmt", "Normal") == "Scientific") for p in plots) else \
                       ("Power10" if any((getattr(p, "y2fmt", "Normal") == "Power10") for p in plots) else "Normal")
        _xfmt_label = "Scientific" if any((getattr(p, "xfmt", "Normal") == "Scientific") for p in plots) else \
                      ("Power10" if any((getattr(p, "xfmt", "Normal") == "Power10") for p in plots) else "Normal")
        _any_y1_2line = any("|" in (getattr(p, "ylabel", "") or "") for p in plots)
        _any_y2_2line = any("|" in (getattr(p, "y2label", "") or "") for p in plots)
        _any_x_2line = any("|" in (getattr(p, "xlabel", "") or "") for p in plots)
        if _y1fmt_label == "Scientific": extra_left_margin_in += 0.35
        elif _y1fmt_label == "Power10": extra_left_margin_in += 0.15
        # [수정] "2줄 title 결과 보니 좌우 마진이 제법 크다 - 줄이고" - 0.20in은
        # 과했던 것으로 보여 절반(0.10in)으로 축소. 그래도 용지에 안 맞으면
        # 기존 shrink-to-fit이 그대로 처리함.
        if _any_y1_2line: extra_left_margin_in += 0.10  # Y1 title 2줄 이상
        if any_y2:
            if _y2fmt_label == "Scientific": extra_right_margin_in += 0.35
            elif _y2fmt_label == "Power10": extra_right_margin_in += 0.15
            if _any_y2_2line: extra_right_margin_in += 0.10  # Y2 title 2줄 이상
        # [추가] "2줄 title에서 X축 길이가 줄어드는데 경고창이 필요" - Auto
        # 모드는 페이지를 칸 수로 나눠 항상 꼭 맞기 때문에(위 주석 참고) 기존
        # shrink-to-fit 경고(Manual 전용)가 이 경우엔 안 뜨고 있었음. 2줄
        # title로 여백이 늘어난 만큼 축(axis) 영역이 그만큼 줄어드는 것은
        # 정상 동작이지만, 사용자가 모르고 지나칠 수 있어 별도로 안내한다.
        # [수정 - 요청] "이 경고가 2줄이기만 하면 무조건 뜬다 - 실제로 축소된
        # 경우에만 조건부로 띄워달라(경고가 너무 많음)" - Y1/Y2 2줄로 인한
        # 추가 여백(위에서 더한 0.10in씩)이 칸 폭(cell_w_in) 대비 일정 비율
        # (3%) 이상을 차지할 때만, 즉 실제로 눈에 띄게 축이 줄어들 때만 띄운다.
        _2line_extra_total = (0.10 if _any_y1_2line else 0.0) + (0.10 if _any_y2_2line else 0.0)
        if _2line_extra_total > 0 and cell_w_in > 0 and (_2line_extra_total / cell_w_in) > 0.03:
            self.last_size_warning = (
                "Y1/Y2 title을 2줄로 설정하면 그만큼 좌우 여백이 늘어나서, "
                "축(plot) 가로 폭이 그만큼 줄어듭니다."
            )
        extra_bottom_margin_in = 0.0
        if _xfmt_label == "Scientific": extra_bottom_margin_in = 0.12
        elif _xfmt_label == "Power10": extra_bottom_margin_in = 0.06
        if _any_x_2line: extra_bottom_margin_in += 0.35  # X title 2줄 이상 (아랫줄 잘림 방지로 확대)

        margin_left = MARGIN_LEFT_IN * margin_scale + extra_left_margin_in
        # [수정] "y2 title이 없으면 마진도 줄어야 함" - 단일 plot(_compute_manual_
        # margins_in)과 동일하게, y2 축은 있지만 y2label 문자열이 없으면(tic
        # 숫자만) 더 작은 여백만 쓰도록 함(예전엔 y2 축만 있으면 label 유무와
        # 무관하게 항상 MARGIN_RIGHT_Y2_IN을 다 썼음).
        _y2_margin_in = (MARGIN_RIGHT_Y2_IN if any_y2label else MARGIN_RIGHT_Y2_NO_LABEL_IN) if any_y2 else 0
        margin_right = (MARGIN_RIGHT_IN + (MARGIN_RIGHT_LEGEND_IN if any_legend_outside else 0) + _y2_margin_in) * margin_scale + extra_right_margin_in
        title_margin_base = MARGIN_TOP_IN if any_title else MARGIN_TOP_NO_TITLE_IN
        margin_top = (title_margin_base + MARGIN_TOP_PER_EXTRA_LINE_IN * (max_title_lines - 1)) * margin_scale
        margin_bottom = MARGIN_BOTTOM_IN * margin_scale + extra_bottom_margin_in

        # [추가] margin_top/bottom과 실제 title/xlabel 폰트 크기 사이 간극으로
        # 옆 칸끼리 텍스트가 겹치는 문제 방지 - 실제 폰트 크기 기준 최소 절대
        # 여백을 보장한다(6/p 등에서 실측 확인된 문제).
        # [수정] 이 최소 절대 여백이 font_panel_scale(선형, 축소 안 됨) 기준이면
        # margin_scale을 줄여도 여기서 다시 큰 값으로 덮어써서, 작은 Manual
        # 칸에서 상하 마진이 전혀 안 줄어드는 문제가 있었음(좌우는 이런 절대
        # 바닥값이 없어서 잘 줄어듦) - "1/p, 2/p는 지정 크기를 최대한 지키고
        # (font_panel_scale 기준 그대로 - 겹침 방지 우선), 4/p, 6/p는 공간
        # 활용을 위해 이 바닥값도 margin_scale만큼 같이 줄어들게(옆 칸과 살짝
        # 빡빡해질 수 있음을 감수)" 한다.
        # [수정] "Auto 1/p, 2/p에서 세로축이 너무 짧고 plot간 간격이 너무 큼" -
        # margin_scale/layout_scale은 위에서 이미 1.0으로 상한을 뒀는데, 이
        # 겹침방지 바닥값(_need_top_in/_need_bottom_in)이 여전히 상한 없는
        # font_panel_scale(예: 1.84)을 그대로 써서 margin_top/bottom을 다시
        # 크게 되돌려버렸음(캡을 우회하는 결과) - Auto에서 실측: 칸 높이
        # 5.8in인데 상하 여백만 2.94in을 먹어서 축이 2.85in로 쪼그라듦.
        # [수정] 1.0으로 딱 잘라 캡을 걸었더니 반대로 칸이 아주 커서
        # font_panel_scale이 큰 경우(예: 1/p landscape, 2.6배)엔 실제 title/
        # xlabel 폰트가 그만큼 커졌는데도 여백은 1.0배로 고정돼 xlabel가 페이지
        # 밖으로 밀려 안 보이는 문제가 생김 - 1.0 밑으로는 그대로(선형, "작은
        # plot은 여백도 줄어야") 두고, 1.0 위로는 제곱근(sqrt)으로 완만하게만
        # 커지게 한다(실제 폰트 크기에 맞춰 클리핑은 막으면서도, 선형보다는
        # 덜 커져서 여백이 과하게 크지도 않게).
        # [수정 - 버그] 4/p, 6/p(total_cells>=4)는 margin_scale(칸 크기에 따른
        # 상한 로직 - 위 "Auto는 margin_scale만 1.0 상한" 참고)을 그대로
        # 쓰는데, 이 margin_scale은 CAIRO_FONT_RENDER_FIX 보정 이전의
        # size_scale에서 파생돼 그 보정을 못 담고 있음(반대로 total_cells<4는
        # font_panel_scale을 직접 써서 이미 그 보정이 반영돼 있음) - 그 결과
        # pdf/png/jpg에서 실제 폰트(title/xlabel)는 1.5배 커졌는데 이 겹침
        # 방지 바닥값은 그대로라 4/p에서 아래 행 제목이 위 행 X title과
        # 겹치는 회귀가 실측(렌더링 이미지 직접 확인)으로 발견됨. margin_
        # scale의 "칸 크기에 따른 상한" 로직 자체는 그대로 두고(재도입 위험이
        # 있는 부분 - 위 주석 히스토리 참고), 여기 바닥값에만 이 보정을
        # 추가로 곱한다.
        # [수정 - 근본 원인] font_panel_scale에 EMF도 이제 자체 보정(EMF_FONT_
        # RENDER_FIX)을 받으므로, margin_scale 기반 4/p·6/p 겹침방지 바닥값도
        # 같은 보정을 알아야 한다(cairo와 동일한 이유 - 위 font_panel_scale
        # 주석 참고).
        if (fmt or "").lower() in ("pdf", "png", "jpg", "jpeg"):
            _cairo_fix = CAIRO_FONT_RENDER_FIX
        elif (fmt or "").lower() == "emf":
            _cairo_fix = EMF_FONT_RENDER_FIX
        else:
            _cairo_fix = 1.0
        # [수정 - 재조정] "M-P Auto의 title/축 title 폰트를 single-plot과 거의
        # 동일(완전 고정)하게" 요청으로 실제 title/xlabel/ylabel/y2label
        # 폰트(_title_f_scale, 위 참고)를 이미 1.0 상당(+cairo 배율)으로
        # 고정해뒀는데, 이 겹침 방지 바닥값은 여전히 "커지는 방향(칸이 기준
        # 보다 큰 경우)"에 옛 폰트 크기(sqrt 완화된 값)를 기준으로 여백을
        # 잡고 있어 실제로 필요한 것보다 여백을 더 크게(=axis를 더 작게)
        # 잡고 있었음 - title이 이제 커지지 않으므로, "커지는 방향"의
        # 바닥값도 title과 똑같이 1.0 상당(+cairo 배율)으로 고정한다(axis가
        # 그만큼 커짐 - "M-P 2p PNG y축이 작게 나옴(마진 있음)" 피드백
        # 대응). [주의 - 회귀 방지] 4/p·6/p(total_cells>=4)는 칸이 커도
        # margin_scale 자체에 이미 "칸 수가 많으면 여백을 더 적극적으로
        # 줄인다"는 0.5배가 들어있는데(위 margin_scale 계산부 참고), 이걸
        # 무시하고 무조건 _cairo_fix로만 고정하면 4/p·6/p가 1/p·2p와 똑같은
        # (더 큰) 여백을 갖게 되는 역행이 생김 - 1/p·2p(total_cells<4)만
        # title과 동일하게 1.0 상당으로 고정하고, 4/p·6/p는 기존 margin_scale
        # 기반 로직(칸 수에 따른 추가 축소 포함)을 그대로 유지한다.
        # [수정 - 버그, 3/p 추가 때 놓침] 바로 위 주석이 이미 "total_cells<4"/
        # ">=4"라고 명시했는데 실제 조건은 >=3이었음 - 위 margin_scale/
        # _margin_aggr과 같은 원인의 같은 버그(3/p가 margin_scale 기반(더
        # 작은) 값을 floor로 쓰게 돼 title이 밀려 안 보이는 문제 - 실측
        # 확인). 주석대로 4로 바로잡는다.
        if total_cells >= 4:
            # [수정 - 버그 발견] "Auto 4/p·6/p Land/Port에서 아래 행 Plot Title이
            # 위 행 xlabel/tic과 실제로 겹침(실측: 4/p -8.3pt, 6/p -15.1pt)" -
            # spacing/폰트 확대와 무관하게 어제 첫 커밋(ee2bf43)에도 이미 있던
            # 문제였음(재현 확인). 원인: total_cells>=4는 _need_top_in/
            # _need_bottom_in 계산에 margin_scale 기반 _floor_scale을 쓰는데,
            # 실측(font_panel_scale=0.906, margin_scale=0.371 - 2.4배 차이)
            # 결과 실제 렌더링되는 폰트보다 필요 여백을 과소평가함 - margin_top/
            # margin_bottom 자체가 "그 폰트 하나만 있을 때도" 이미 부족했던 것이라
            # (안쪽 여백 공유/축소와 무관), _row_gap_t/_row_gap_b가 halving 없이
            # 그대로 margin_top/margin_bottom(=_need_top/bottom_in, 서로 같은 값)을
            # 써도 여전히 겹침. _floor_scale이 실제 font_panel_scale보다 작아지지
            #않도록(margin_scale과 font_panel_scale 중 큰 쪽) 떠받친다 - 이 값은
            # margin-need 계산에만 쓰여 "부족했던 여백을 필요한 만큼 키우는" 방향
            # 뿐이라 텍스트 소실 회귀 위험이 없음(오히려 안전 여유가 늘어남).
            # [수정 - 요청] "겹치지만 않으면 되는데 마진이 과도하게 큼, 지금의
            # 반 이하로" - font_panel_scale을 그대로(1.0배) 쓰면 안전 여유가
            # 45~60pt(TB)/40~50pt(LR)로 필요 이상으로 넉넉함 - 이분 탐색 실측
            # 결과 0.7배까지 줄여도(1줄 14~23pt, Y1/Y2 2줄 12~23pt, X 2줄은
            # _need_bottom_in에 별도 가산이 있어 오히려 39~48pt로 더 넉넉해짐)
            # 전부 안전(겹침 없음, 텍스트 소실 없음) - 0.5배부터는 다시 겹침
            # 재현돼 0.7배로 확정.
            _floor_scale = max(margin_scale, font_panel_scale * 0.7) * _cairo_fix
        else:
            _underlying_scale = font_panel_scale / _cairo_fix if _cairo_fix else font_panel_scale
            _floor_scale = _cairo_fix if _underlying_scale > 1.0 else font_panel_scale
        _need_top_in = 0.0
        _need_bottom_in = 0.0
        if any_title:
            _max_title_size = max((float(p.title_size or 14) for p in plots if (p.title or "").strip()), default=14.0)
            _need_top_in = 0.75 * _floor_scale * (_max_title_size / 14.0) * max_title_lines
            margin_top = max(margin_top, _need_top_in)
        if any((p.xlabel or "").strip() for p in plots):
            _max_xlabel_size = max((float(p.xlabel_size or 11) for p in plots if (p.xlabel or "").strip()), default=11.0)
            _need_bottom_in = 0.85 * _floor_scale * (_max_xlabel_size / 11.0) + (0.35 if _any_x_2line else 0)
            margin_bottom = max(margin_bottom, _need_bottom_in)
        margin_bottom += _extra_bottom_in
        # [추가] "4/p Auto에서 옆 칸끼리 y1/y2 label(회전 텍스트)이 겹침" -
        # margin_left/right를 top/bottom과 동일한 이유로 줄이면서도(4/p, 6/p는
        # margin_scale에 추가 축소까지 걸림) 좌우에는 top/bottom 같은 최소
        # 절대 여백(floor)이 없어서, label 폭보다 마진이 더 좁아지면 옆 칸
        # 글자와 그대로 겹쳐버렸음 - 위와 같은 _floor_scale 기준으로 최소
        # 여백을 보장한다.
        # [수정] "그래도 옆 칸끼리 겹침" - label 자체의 회전폭(_floor_scale
        # 기준, 적극적으로 줄어듦)만 보장했더니 여전히 겹쳤음. 실제로는 margin_
        # left/right 안에 y1/y2 "tic 숫자"도 같이 들어가야 하는데(라벨보다 먼저
        # 차지), tic 폰트는 font_panel_scale(캡 없음)로 그리면서 이 floor는
        # tic 몫을 전혀 안 보고 있었음 - tic 숫자 최소 4자리 폭은 축소 없이
        # (실제 그려지는 크기 그대로) 항상 더해서, 진짜 겹치지 않을 최소값을 보장한다.
        # [수정] 4자리 고정 가정 대신 실제 tic 문자 수(max_y1_chars/max_y2_chars,
        # 이미 위에서 실측)를 써서, 짧은 숫자(예: "0","1")일 때는 floor도 더
        # 작게(간격을 더 좁게) 잡히도록 한다.
        _min_left_tic_in = max(1, max_y1_chars) * _tick_char_width_in_mp + 0.03
        _min_right_tic_in = max(1, max_y2_chars) * _tick_char_width_in_mp + 0.03
        # [수정 - 심각한 버그 발견] "EMF만 Multi Print/Batch Set에서 y1/y2 title이
        # 완전히 사라짐" - EMF 바이너리를 직접 파싱해서 확인: offset 문제가
        # 아니라(offset=0으로도 재현) margin_left/right 자체가 부족하면 EMF
        # 렌더러가 (cairo처럼 넘치게 그리는 게 아니라) title을 통째로 그리지
        # 않고 누락시킴 - 실측(같은 조건에서 margin_left를 fraction 0.1645->
        # 0.35로 강제로 키우자 title이 다시 나타남)으로 확인. EMF만 별도로
        # 여백을 넉넉히(2배) 더 준다.
        # [수정] "축 size가 안 맞음, 마진도 이상함" - 2배(_emf_margin_boost)에
        # 2줄 전용 추가분까지 겹쳐서 마진이 좌우 합쳐 74%까지 차지하는 과함이
        # 실측 확인됨. 1.3배로 낮추면 1줄 Y2 title이 다시 사라지고, 1.5배도
        # 2줄 Y2의 2번째 줄이 다시 사라짐(실측) - 1.7배가 전부 정상 출력되는
        # 최소값이라 그대로 확정.
        _emf_margin_boost = 2.0 if (fmt or "").lower() in ("emf", "svg") else 1.0
        # [수정 - 요청] "1p/2p Port EMF/SVG의 축 가로 폭이 single-plot 대비
        # 너무 좁음" - 실측(실제 out111.dat+sample.dat 5-curve, EMF 바이너리
        # rclFrame 직접 측정): 축이 페이지 폭의 57.6%(single-plot 동급은
        # ~78%) - EMF/SVG 전용 2배 마진 부스트는 작은 칸에서 title 소실을
        # 막으려고 필요했던 값인데, 1p/2p Auto처럼 칸이 기준(10x8cm)보다 큰
        # 경우는 절대 공간이 넉넉해서 2배까지는 필요 없음(칸이 작을 때는
        # font_panel_scale<=1이라 이 블록 자체가 적용 안 돼 기존 소실 방지
        # 그대로 유지). 다만 실측으로 낮춰본 결과 1.2배는 Y1 rotated title이
        # 다시 사라짐(EMF 텍스트 레코드로 직접 확인) - 1.4배가 텍스트 소실
        # 없이 확인된 안전한 최소값(축 폭 57.6%->71.4%로 개선).
        # [수정 - 버그 발견] 위 완화(1.4)가 fmt 조건 없이 걸려 있어서, 이 boost가
        # 원래 필요 없는 PDF/PNG(cairo는 여백이 부족해도 텍스트를 "넘치게"
        # 그릴 뿐 통째로 지우지 않음 - EMF/SVG만의 문제)까지 EMF/SVG와 똑같이
        # 1.4배 마진을 먹어서, "2p Land에서 x축(가로)이 너무 좁다" 피드백의
        # 실측 원인 중 하나로 확인됨(PDF/PNG margin_left/right가 EMF/SVG와
        # 완전히 동일한 값으로 나오고 있었음). EMF/SVG에만 이 완화를 적용한다.
        if frame_auto and font_panel_scale > 1.0 and (fmt or "").lower() in ("emf", "svg"):
            _emf_margin_boost = 1.4
        # [수정 - 심각한 버그] "Multi-plot EMF 2줄 title에서 Y2의 2번째 줄만
        # 통째로 안 보임" - EMF 바이너리로 직접 확인: EMF는 회전된 2줄
        # ylabel/y2label을 "세로로 쌓지 않고 가로로 나란히" 그림(gnuplot EMF
        # 드라이버의 한계) - 그래서 2번째 줄은 사실상 "title 폭만큼 더 필요한
        # 별도의 텍스트"에 가까운데, 기존 +0.1in은 세로로 쌓인다고 가정한
        # 값이라 턱없이 부족했음(Y2가 오른쪽 캔버스 경계 바로 앞이라 2번째
        # 줄이 밀려나가 사라짐 - single-plot은 마진이 이미 넉넉해 우연히
        # 괜찮았을 뿐). 2줄이면 label 폭만큼(_floor_scale 기준) 통째로 더
        # 얹어준다(단일 plot 경로와 동일한 사고방식).
        _need_left_in = 0.0
        _need_right_in = 0.0
        if any((p.ylabel or "").strip() for p in plots):
            _max_ylabel_size = max((float(p.ylabel_size or 11) for p in plots if (p.ylabel or "").strip()), default=11.0)
            # [수정] 1줄 title(EMF)이 다시 사라지는 회귀 확인 - 2줄 전용 추가분을
            # emf_margin_boost 곱셈 "안"으로 옮겨서, 1줄일 때는 원래 검증된
            # 2.0배가 그대로 유지되게 하고 2줄 전용분만 별도로(곱해지지 않게)
            # 더한다(실측: 1줄 boost=2.0 필요, 2줄은 그 위에 0.3배 추가로 충분).
            # [수정 - 버그, Multi-plot 전체 레이아웃(1/2/4/6-per-page) x Auto/
            # Manual x PDF/EMF 64가지 조합 회귀 테스트로 새로 발견] "PDF(=PNG
            # 공유)에서 1/p·4/p Auto + Y2 2줄이면 2번째 줄이 통째로 사라짐" -
            # EMF 전용인 줄 알았던 이 실종 버그가 PDF cairo에서도 재현됨
            # (fitz로 텍스트 추출 시 아예 없음, single-plot에서는 마진이
            # 넉넉해 우연히 안 보였을 뿐). 0.3배로는 EMF만 겨우 버티는
            # 수준이라 PDF/SVG는 여전히 부족했던 것 - 0.6배로 올려서
            # 64가지 조합 전부 정상 출력 재확인.
            # [수정 - 버그, 병합 후 재발견] 4/p·6/p Manual + 작은 명시 크기(예:
            # 6x5cm)에서는 margin_scale이 "작은 칸일수록 적극적으로 줄인다"는
            # 세제곱 축소(size_scale**3)를 받아 _floor_scale이 아주 작아지는데,
            # 2번째 줄이 실제로 차지하는 물리적 폭은 이 "여백 편의상 축소"와
            # 무관하게 폰트 크기(EMF_FONT_RENDER_FIX 등이 반영된 font_panel_
            # scale)에 그대로 비례하는 하드 요구치라, _floor_scale 기준으로
            # 구하면 실제 필요량보다 작게 나와 텍스트가 잘림(실측: 4/p·6/p
            # Manual EMF/PDF/SVG 2줄 조합에서 panel2/4/6 텍스트 소실 -
            # 96-combo 회귀로 발견). font_panel_scale(캡 없는 실제 배율) 기준으로
            # 바꿔서, 칸이 작다는 이유로 이 하드 요구치까지 같이 줄지 않게 한다.
            _y1_2line_extra = 0.6 * font_panel_scale * (_max_ylabel_size / 11.0) if _any_y1_2line else 0
            _need_left_in = (0.5 * _floor_scale * (_max_ylabel_size / 11.0) + _min_left_tic_in) * _emf_margin_boost + _y1_2line_extra
            margin_left = max(margin_left, _need_left_in)
        if any_y2 and any_y2label:
            _max_y2label_size = max((float(p.y2label_size or 11) for p in plots if (getattr(p, "y2label", "") or "").strip()), default=11.0)
            _y2_2line_extra = 0.6 * font_panel_scale * (_max_y2label_size / 11.0) if _any_y2_2line else 0
            _need_right_in = (0.5 * _floor_scale * (_max_y2label_size / 11.0) + _min_right_tic_in) * _emf_margin_boost + _y2_2line_extra
            margin_right = max(margin_right, _need_right_in)

        # [추가 - 요청] "3/p~6/p Manual도 절대 마진이 너무 크지 않은지" - 바로
        # 위 margin_left/right(그리고 margin_top/bottom, 4507/4511행)는 "need
        # 보다 작아지지만 않게"만 보장할 뿐, need보다 훨씬 커도 flat 기본값
        # (MARGIN_LEFT_IN=0.9in 등)을 그대로 썼음(예: 2/p Manual 기본
        # 10x8cm에서 need_left=0.73in인데 margin_left는 그대로 0.9in). Manual은
        # "정확한 물리 크기 보장"이 목적이라 이 여유가 클수록 칸 사이가 넓어
        # 보이고 용지에도 덜 들어가므로, 여러 칸(cols>1 또는 rows>1)일 때만
        # need 기준 15% 여유(이 파일 다른 곳의 "_approx_label_in 15% 여유"와
        # 같은 관례)까지만 남기고 초과분을 깎는다. margin_right는 legend가
        # "outside right"로 축 바깥에 자리 잡는 경우 need_right_in 계산에
        # legend 폭이 전혀 안 들어가 있어(Y2 title/tic 폭만 계산) 그대로
        # 깎으면 legend가 잘릴 위험이 있어 그 경우만 제외한다. 1/p은 애초에
        # 문제 제기가 없어 회귀 범위를 최소화하려고 그대로 둔다.
        # [수정 - 버그, 직접 렌더링 재검증으로 발견] 처음엔 1줄/2줄 구분 없이
        # 전부 적용했는데, Y1/Y2 2줄 라벨(회전 텍스트 두 줄) 조합으로 재검증한
        # 결과 두 줄 사이 간격이 0.01pt(사실상 붙어 보임)까지 줄어듦 - need_*_in
        # 자체는 2줄분(_y1_2line_extra 등)을 이미 포함하지만, 그 위에 15% 곱한
        # 정도로는 2줄 텍스트의 실제 줄 간격을 안전하게 보장하기엔 부족했음
        # (기존엔 margin_*이 need보다 더 크게 남아있어서 우연히 여유가 있었던
        # 것). 이 파일에 이미 있는 관례(_any_multiline_margin, single-plot
        # margin 축소 가드)와 동일하게, Y1/Y2/X 중 하나라도 2줄이면 이 축소
        # 자체를 건너뛴다(안전 최우선 - 2줄 조합은 원래도 여백이 빠듯한
        # 경우라 별도 여유가 필요).
        _any_2line_for_cap = _any_y1_2line or _any_y2_2line or _any_x_2line
        if not frame_auto and (cols > 1 or rows > 1) and not _any_2line_for_cap:
            _manual_margin_buffer = 1.15
            if _need_left_in > 0:
                margin_left = min(margin_left, _need_left_in * _manual_margin_buffer)
            if _need_right_in > 0 and not any_legend_outside:
                margin_right = min(margin_right, _need_right_in * _manual_margin_buffer)
            if _need_top_in > 0:
                margin_top = min(margin_top, _need_top_in * _manual_margin_buffer)
            if _need_bottom_in > 0:
                margin_bottom = min(margin_bottom, _need_bottom_in * _manual_margin_buffer)

        # [수정 - 버그, 실제 사용자 docx 재현으로 발견] "M-P Auto/Manual 2/p
        # Landscape에서 축이 캔버스 한복판에 작게(세로형처럼) 쪼그라들어 찍힘" -
        # 실측(디버그 출력)으로 원인 확인: 2/p Landscape처럼 칸(cell)이 기준
        # (10x8cm)보다 훨씬 큰 경우(font_panel_scale>1) margin_left/right
        # 자체(_floor_scale 비례항)도 이미 커지는데, 거기에 EMF 전용
        # _emf_margin_boost(2.0배, 작은 칸에서 title 소실을 막으려고 도입한
        # 값)가 곱해지면서 절대 여백이 칸 폭의 70%까지 먹어버려 축이 거의
        # 안 남았음(margin_left=margin_right=2.07in, cell_w_in=5.72in). 칸이
        # 클수록 이 배율이 과한 것 - 작은 칸(margin 부족 시 title 소실 위험이
        # 큰 경우)에서는 원래대로 배율을 살리고, 큰 칸에서만 margin 합이 칸
        # 크기의 일정 비율을 넘지 않도록 비율을 유지한 채 축소한다.
        # [주의] 0.6으로는 1/p Auto Portrait, 2/p Auto Landscape의 2줄
        # Y2 2번째 줄(EMF)이 다시 사라지는 회귀가 실측 확인됨 - 0.68까지
        # 올려서 1/2/4/6-per-page x portrait/landscape x Auto/Manual x
        # PDF/EMF x 1줄/2줄 128가지 조합 전부 정상 출력(텍스트 소실 없음)
        # 재확인 후 확정.
        # [수정 - 버그, 병합 후 회귀 발견] EMF_FONT_RENDER_FIX(1.8) 도입으로
        # _need_left_in/_need_right_in(2줄 Y1/Y2 라벨이 안 잘리기 위한
        # 최소 필요치)이 커졌는데, 이 0.68 상한이 그 최소치 밑으로까지
        # 눌러버려서(4/p 등 좁은 칸에서) EMF가 여백 부족을 텍스트 통째로
        # 누락으로 처리하는 문제가 재발함(실측: 4/p Auto EMF 2줄 조합에서
        # panel2/4의 Y1/Y2 2번째 줄 소실 - 96-combo 회귀로 발견). 0.68
        # 상한 자체(다른 128가지 조합에서 검증된 값)는 그대로 두고, 축소한
        # 뒤에도 "텍스트 소실을 막기 위한 최소치" 밑으로는 안 내려가게
        # 최종적으로 다시 그 값으로 떠받친다(축이 그만큼 더 좁아질 수
        # 있지만, 텍스트가 조용히 사라지는 것보다는 나음).
        _MAX_MARGIN_FRAC = 0.68
        if cell_w_in > 0 and (margin_left + margin_right) > cell_w_in * _MAX_MARGIN_FRAC:
            _shrink_lr = (cell_w_in * _MAX_MARGIN_FRAC) / (margin_left + margin_right)
            margin_left = max(margin_left * _shrink_lr, _need_left_in)
            margin_right = max(margin_right * _shrink_lr, _need_right_in)
            # [수정 - 버그] 위에서 "텍스트 소실 방지 최소치보다 작아지지
            # 않게" 떠받쳤는데, 두 최소치(_need_left_in+_need_right_in)를
            # 합친 값 자체가 이미 cell_w_in을 넘는 극단적인 경우(칸이 아주
            # 좁은데 Y1+Y2가 둘 다 2줄인 경우 등)에는 이 떠받침이 axis_w를
            # 음수로 만들어버려, gnuplot이 그 칸 전체를 렌더링하지 못해
            # (여백 부족보다 더 나쁜) 텍스트 소실이 남(실측: 4/p Auto EMF
            # 2줄에서 axis_w=-0.94in로 확인). 최소치를 지키는 것보다 axis가
            # 최소한 양수로는 남는 게 우선이므로, 합이 cell_w_in을 넘으면
            # (약간의 여유 0.3in만 axis에 남기고) 두 마진을 각자 비율대로
            # 다시 줄인다 - 이 경우 2번째 줄이 여전히 빠듯할 수 있지만,
            # axis 자체가 사라지는 것보다는 낫다.
            # [수정 - 재조정] 처음엔 최소 0.3in을 강제로 보장하려 했으나, 그러면
            # "축이 음수가 되진 않지만 0.3in보다는 넉넉히 남았을" 경우까지도
            # 불필요하게 0.3in로 깎아버려, 오히려 이전엔(이 안전장치 없이도)
            # 문제없던 조합(예: 8x6cm Manual)까지 새로 텍스트가 사라지는
            # 역행이 생겼음(실측). "축이 진짜로 음수가 되는 것만" 막도록
            # 문턱을 낮춘다(기존 axis_w의 0.05in 하한과 동일한 기준).
            if margin_left + margin_right > cell_w_in - 0.05:
                _budget = max(cell_w_in - 0.05, 0.1)
                _fit_lr = _budget / (margin_left + margin_right)
                margin_left *= _fit_lr
                margin_right *= _fit_lr
        if cell_h_in > 0 and (margin_top + margin_bottom) > cell_h_in * _MAX_MARGIN_FRAC:
            _shrink_tb = (cell_h_in * _MAX_MARGIN_FRAC) / (margin_top + margin_bottom)
            margin_top *= _shrink_tb
            margin_bottom *= _shrink_tb

        # [수정 - 버그] "1/p + Manual은 1줄이어도 '크기 축소됨' 경고가 뜬다" -
        # 위쪽(3389 부근)의 "1/p+Manual 페이지 크기 재설정" 블록은 이 margin_*
        # (tic 숫자/title 자리, 보통 pm_left/right 절대 여백보다 훨씬 큼)이
        # 계산되기 "전"에 page_w/page_h를 pm_left/right(작은 고정값)만으로
        # 미리 정해버렸음 - 그래서 아래 shrink 비교에서 쓰는 실제 필요
        # 크기(axis+margin_*)보다 page_w가 항상 작게 잡혀, 1줄/2줄과 무관하게
        # 매번 "축소됨" 경고가 뜨고 있었음(렌더링 자체는 문제 없었지만 경고가
        # 잘못 뜸). margin_*이 확정된 지금 다시 정확히 재계산한다.
        if rows == 1 and cols == 1 and not frame_auto and frame_width and frame_height:
            page_w = cell_w_in + margin_left + margin_right
            page_h = cell_h_in + margin_top + margin_bottom

        # [수정 - 개념 정정] "Frame(Axis) 크기는 좌표축(axis) 자체의 크기임 -
        # 처음부터 그렇게 강조했음" - Manual에서 frame_width/height는 칸(cell,
        # 마진+legend 포함 전체)이 아니라 axis 자체의 크기다. 그래서 cell_w_in/
        # cell_h_in(지금까지 frame_width/height를 그대로 담고 있던 변수)을 axis
        # 크기로 보고, 마진을 더해서 실제 칸(전체 이미지) 크기를 새로 구한다
        # (이후 아래 shrink-to-fit/grow 단계가 이 "축+마진 = 칸" 크기를 기준으로
        # 용지에 맞추도록, margin 계산 직후/shrink-to-fit 이전에 반영한다).
        axis_w = axis_h = None
        if not frame_auto:
            axis_w = cell_w_in
            axis_h = cell_h_in
            cell_w_in = axis_w + margin_left + margin_right
            cell_h_in = axis_h + margin_top + margin_bottom

        # [수정] "지정 Axis size에서도 지정마진에 plot 자체 마진이 추가되어
        # 마진이 너무 커짐" - 절대(페이지) 여백 pm_*과 plot 자체 여백(margin_*,
        # title/tic 라벨 자리)이 더해져(pm_left + margin_left) 쌓이던 문제.
        # 절대 여백은 plot 자체 여백을 이미 포함하는 것으로 처리한다 - 즉 둘 중
        # 더 큰 쪽만 실제로 적용되고(더하지 않음), 절대 여백이 plot 자체 여백보다
        # 큰 만큼(pm_* - margin_*)만 별도의 바깥쪽 여유로 추가된다.
        pad_left = max(pm_left - margin_left, 0)
        pad_right = max(pm_right - margin_right, 0)
        pad_top = max(pm_top - margin_top, 0)
        pad_bottom = max(pm_bottom - margin_bottom, 0)
        printable_w = page_w - pad_left - pad_right
        printable_h = page_h - pad_top - pad_bottom

        # [추가] Manual(명시적 frame 크기) 지정 시, 칸(이미지 한 장) 전체가 페이지에
        # 안 들어가면 - 가로세로 비율을 바꾸는 게 아니라 - 칸 전체(폰트/여백/간격
        # 포함, "legend 포함 이미지 개념")를 하나의 배율로 균일하게 축소한다.
        # Auto는 애초에 페이지 칸 수로 나눠 계산했으므로 항상 꼭 맞아 축소가 필요 없다.
        # [수정 - 버그] "2/p Manual(기본 10x8cm)이 Land/Port 둘 다 92~94%로
        # 줄어든다는 경고가 뜨는데, 원래 경고 없이 들어가야 하는 것 아닌가" -
        # 실측(좌표 기준)으로 원인 확인: 여기 grid_w/grid_h가 옆 칸과 마주보는
        # "안쪽" 면끼리 마진을 절반만 나눠 쓰는(_interior_k=0.5, 아래 _col_gap_l/r
        # 참고) 실제 렌더링 로직을 전혀 모른 채, 모든 칸에 바깥쪽과 똑같은
        # 전체 margin_left/right/top/bottom을 곱해서 필요 크기를 "실제보다
        # 크게" 추정하고 있었음 - 그래서 실제로는 용지에 들어갈 수 있는데도
        # 불필요하게 축소됨. 아래에서 그 안쪽 절반-공유 여백을 미리 반영해
        # 실제 렌더링과 같은 기준으로 grid_w/grid_h를 계산한다(5장 중앙정렬
        # 특수 배치는 원래 이 절반-공유를 안 쓰므로 제외 - _is_centered5와
        # 동일 조건이지만 그 변수 자체는 아직 이 시점에 없어 조건을 그대로
        # 복사해 씀).
        _is_centered5_early = (layout_option == "Auto" and nplot == 5)
        if not frame_auto:
            if _is_centered5_early or (cols <= 1 and rows <= 1):
                grid_w = cell_w_in * cols + spacing_in * (cols - 1)
                grid_h = cell_h_in * rows + spacing_in * (rows - 1)
            else:
                _interior_k_early = 0.5  # 아래 _interior_k(4917행 부근)와 항상 같은 값 유지할 것
                _interior_l = max(margin_left * _interior_k_early, min(margin_left, _need_left_in)) if cols > 1 else margin_left
                _interior_r = max(margin_right * _interior_k_early, min(margin_right, _need_right_in)) if cols > 1 else margin_right
                _interior_t = max(margin_top * _interior_k_early, min(margin_top, _need_top_in)) if rows > 1 else margin_top
                _interior_b = max(margin_bottom * _interior_k_early, min(margin_bottom, _need_bottom_in)) if rows > 1 else margin_bottom
                _lr_total = margin_left + margin_right + max(cols - 1, 0) * (_interior_l + _interior_r)
                _tb_total = margin_top + margin_bottom + max(rows - 1, 0) * (_interior_t + _interior_b)
                grid_w = axis_w * cols + spacing_in * (cols - 1) + _lr_total
                grid_h = axis_h * rows + spacing_in * (rows - 1) + _tb_total
            # [수정 - 버그] 위와 같은 이유로, 판단 기준(printable_w/h)도 부정확한
            # "추정 page_w/h" 대신 실제 물리 A4(_true_page_w/h)에서 인쇄 안전
            # 여백만 뺀 진짜 사용 가능 크기로 비교한다(page_w/h 자체는 그대로 -
            # shrink 여부 "판단"에만 쓴다).
            _true_printable_w = _true_page_w - pad_left - pad_right
            _true_printable_h = _true_page_h - pad_top - pad_bottom
            shrink = 1.0
            if grid_w > 0:
                shrink = min(shrink, max(_true_printable_w / grid_w, 0.1))
            if grid_h > 0:
                shrink = min(shrink, max(_true_printable_h / grid_h, 0.1))
            if shrink < 0.999:
                _margin_desc = "여백(사방 0.3cm)"
                self.last_size_warning = (
                    f"요청한 Frame 크기({cell_w_in * 2.54:.2f}x{cell_h_in * 2.54:.2f}cm)로는 "
                    f"용지({orientation})에 {_margin_desc}을 두고 들어가지 않아, "
                    f"플롯 크기를 약 {shrink*100:.0f}%로 줄여서 출력했습니다."
                )
                cell_w_in *= shrink
                cell_h_in *= shrink
                axis_w *= shrink
            else:
                # [추가] 축소가 필요 없으면(실제 A4에 들어감), 대략치였던
                # page_w/h를 지금 정확히 계산된 grid_w/h(칸 전체 실제 크기)로
                # 다시 맞춰서, 최종 출력 페이지가 부정확한 추정치 크기로
                # 잘리거나 남지 않게 한다(page_w/h는 몇 줄 뒤부터 실제 배치·
                # 최종 출력 크기 산정에 계속 쓰임).
                page_w = max(grid_w, 0.1)
                page_h = max(grid_h, 0.1)
                printable_w = page_w - pad_left - pad_right
                printable_h = page_h - pad_top - pad_bottom
                axis_h *= shrink
                spacing_in *= shrink
                size_scale *= shrink
                font_panel_scale *= shrink
                margin_scale *= shrink
                margin_left *= shrink
                margin_right *= shrink
                margin_top *= shrink
                margin_bottom *= shrink

            # [추가] "1/p, 2/p는 지정 크기를 그대로, 4/p, 6/p는 공간을 활용해서
            # plot이 너무 작아지는 걸 방지" - 칸이 많을 때(4/p 이상)는 grid가
            # 용지보다 작게 남으면(용지 중앙에 큰 바깥 여백만 남고 plot은 작게
            # 유지) 오히려 반대로 용지를 채우도록 grid 전체를 키운다(비율 유지,
            # 위 축소와 동일한 방식의 반대 방향). 1/p, 2/p는 지정 크기를 그대로
            # 존중하므로 이 확대는 적용하지 않는다.
            if total_cells >= 3:
                grid_w = cell_w_in * cols + spacing_in * (cols - 1)
                grid_h = cell_h_in * rows + spacing_in * (rows - 1)
                # [수정] 100%까지 꽉 채우면 용지에 딱 붙어 보인다는 피드백
                # (landscape 좌우, portrait 상하) - 채우는 목표를 낮춰서 바깥쪽에
                # 약간의 숨 쉴 틈을 남긴다. 4/p는 상하가 특히 더 빡빡하다는
                # 추가 피드백으로 세로 쪽 목표를 조금 더 낮춤(가로 95%, 세로 90%).
                _fill_frac_w = 0.95
                _fill_frac_h = 0.90
                grow = None
                if grid_w > 0 and grid_h > 0:
                    grow = min(printable_w * _fill_frac_w / grid_w, printable_h * _fill_frac_h / grid_h)
                if grow and grow > 1.001:
                    cell_w_in *= grow
                    cell_h_in *= grow
                    axis_w *= grow
                    axis_h *= grow
                    spacing_in *= grow
                    size_scale *= grow
                    font_panel_scale *= grow
                    margin_scale *= grow
                    margin_left *= grow
                    margin_right *= grow
                    margin_top *= grow
                    margin_bottom *= grow

        # [수정] "4/p는 3개만, 2/p는 1개만 저장됨" - margin이 칸 크기보다 커서 axis가
        # 0.5in 바닥에 걸리면, 이 축소된 axis에 margin을 다시 더해 cell_w_in/h_in을
        # "키우고" 있었음. Manual은 이렇게 키운 뒤 바로 위의 균일 shrink 단계에서
        # 다시 페이지에 맞춰 축소되니 안전하지만, Auto는 cell 크기가 처음부터
        # "페이지를 cols x rows로 정확히 나눈 값"이어야 한다는 전제가 깨져서, 칸이
        # 커진 만큼 그리드 전체가 용지 밖으로 밀려나고(특히 원점에서 먼 마지막 칸일수록
        # 심함) gnuplot이 화면 밖(0~1 범위 밖) margin을 받아 그 칸을 못 그리는
        # 문제가 있었음 - Auto는 cell 크기를 그대로 두고 axis만(margin이 넘치면
        # 매우 좁아지더라도) 그 안에서 줄인다.
        # [수정] Manual은 axis_w/axis_h를 이미 위에서(margin 계산 직후) 원래
        # 지정한 axis 크기로 설정해뒀음(그 뒤 shrink/grow도 같이 반영됨) - 여기서
        # cell에서 다시 빼서 덮어쓰면 안 됨(같은 값이 나오는 게 정상이지만,
        # Manual의 "axis = 지정값 그대로"라는 원칙을 코드로도 명확히 하기 위해
        # frame_auto일 때만 이 방식(cell에서 margin을 뺌)으로 axis를 구한다.
        if frame_auto:
            axis_w = max(cell_w_in - margin_left - margin_right, 0.05)
            axis_h = max(cell_h_in - margin_top - margin_bottom, 0.05)
        else:
            axis_w = max(axis_w, 0.5)
            axis_h = max(axis_h, 0.5)
        # [추가] "Multi-plot Auto로 1~2개만 그릴 때 용지 모양(A4 비율) 그대로
        # 늘어나서 x:y(axis 자체의 가로:세로 비율)가 왜곡된다" - 단일 plot
        # Auto와 같은 원칙으로, 칸이 적을 때(1/p, 2/p)는 axis(margin을 뺀 실제
        # 그림 영역) 자체를 기준(10x8) 비율로 맞추고(contain-fit), 칸이 많을 때
        # (4/p 이상)는 지금처럼 용지를 최대로 채운다(비율 무시). margin을 뺀
        # 뒤의 axis를 기준으로 맞춰야, 가로/세로에 비대칭으로 붙는 마진(legend가
        # 있는 오른쪽, title이 있는 위쪽) 때문에 axis 비율이 어긋나는 문제가 없다.
        # [수정 - 요청] "Auto인데 2p Land에서 plot 바깥 상하 여백이 너무 큼" -
        # 원인 확인: 2/p는 rows!=cols(1x2 또는 2x1)인데, 이 contain-fit이
        # 각 axis를 강제로 10:8 비율에 맞추면서 2/p Landscape(1행 2열, 실제
        # 페이지는 훨씬 넓고 낮음)에서 axis 높이가 페이지 높이보다 훨씬
        # 작아져 위아래에 큰 빈 공간이 남았음(실측: 상하 합 7.2cm, 페이지의
        # 34%). rows==cols인 경우(1/p처럼 정사각 그리드)만 이 비율 유지를
        # 적용하고, 2/p처럼 rows!=cols인 경우는 4/p 이상과 동일하게 용지를
        # 최대로 채우도록(비율 무시) 바꾼다 - 실측 확인(2p Land 상하 여백
        # 3.0/4.21cm -> 0.55/1.76cm로 대폭 감소, 2p Port도 문제 없음).
        # [검토 - 되돌림] "Auto 2/p·3/p Landscape(1행 n열)에서 axis가 세로로
        # 길쭉해짐(실측: 3/p Landscape axis_w=2.34in/axis_h=6.67in, 비율
        # 0.35)"을 버그로 보고 rows==1/cols==1도 비율 유지 대상에 넣었었으나,
        # 실제 렌더링을 픽셀 단위로 직접 비교한 결과 두 경우 다 "찌그러짐"이
        # 눈에 띄게 심하지 않았고(gnuplot이 어떤 box든 데이터를 채워 그려서
        # 육안 차이가 크지 않음), 오히려 이게 "Auto는 남는 여백을 그대로
        # axis 확대에 쓴다"는 요청 그 자체였음 - rows==cols(1/p)만 비율
        # 유지로 되돌린다.
        if frame_auto and total_cells <= 2 and rows == cols:
            _ref_w2, _ref_h2 = (REF_H_IN, REF_W_IN) if axis_w < axis_h else (REF_W_IN, REF_H_IN)
            _target_ratio = _ref_w2 / _ref_h2
            if axis_w / axis_h > _target_ratio:
                axis_w = axis_h * _target_ratio
            else:
                axis_h = axis_w / _target_ratio
            cell_w_in = axis_w + margin_left + margin_right
            cell_h_in = axis_h + margin_top + margin_bottom
        elif not frame_auto:
            cell_w_in = axis_w + margin_left + margin_right
            cell_h_in = axis_h + margin_top + margin_bottom

        # [수정 - 요청] "2p Land처럼 옆으로 나란한 칸끼리는 한쪽(패널1의 Y2
        # 여백)+다른쪽(패널2의 Y1 여백)이 마주 보고 그대로 더해져서 그 사이
        # 여백이 지나치게 커 보임 - 큰 쪽 하나만 적용하면 어떨지?" - 각 칸의
        # margin_left/right는 그 칸 "혼자" 있을 때 필요한 값을 그대로 쓰지만
        # (다른 포맷/레이아웃에 영향 없게), 칸과 칸 사이의 실제 간격만 두
        # margin의 합보다 줄여서 마주보는 두 title이 서로의 여백 쪽으로
        # 조금씩 파고들게 한다. [주의] "큰 쪽만 적용"(작은 쪽 전부 뺌)은
        # 실측 결과 두 title이 실제로 겹침(패널1 Y2 title과 패널2 Y1 title이
        # 15pt 정도 겹침, PDF 좌표 직접 확인)이 확인돼 그대로는 못 씀 - 절반
        # (0.5배)은 EMF 마진 부스트를 2.0->1.4로 낮춘 뒤(축이 넓어짐) 다시
        # 겹침이 재현돼(실측 확인), 그보다 더 줄여 0.25배로 확정(1줄/2줄
        # 모두 겹침 없음 재확인).
        # [수정 - 버그, PDF/PNG 텍스트 절대 크기 보정(CAIRO_FONT_RENDER_FIX)
        # 이후 재발견] margin이 커진 만큼 Y1/Y2 rotated label 자체의 실제
        # 폭(protrusion)도 같이 커졌는데, 이 0.25배 감산은 "margin 크기"만
        # 보고 그 안의 실제 글자 폭 변화는 반영을 못 해서, 4/p처럼 칸이 좁고
        # Y1+Y2가 둘 다 있는 경우 서로의 title이 실제로 겹치는 회귀가 실측
        # 확인됨(0.25배는 16.7pt, 0.10배도 8.7pt 겹침 - PDF 좌표 직접 확인).
        # 감산 자체를 걷어내도(0배) 3.5pt 정도 잔여 겹침이 남아, 감산 배율
        # 조정만으로는 근본 해결이 안 됨 - 대신 감산을 아예 없애고(0배,
        # 가장 안전한 값), Y1/Y2 rotated label이 둘 다 있는 좁은 칸(cols>1)
        # 에서만 별도의 고정 여유(0.15in - 위 3.5pt 잔여 겹침보다 넉넉한
        # 값)를 더해 서로 닿지 않게 한다.
        if cols > 1:
            if any_y2 and any((p.ylabel or "").strip() for p in plots):
                # [수정 - 요청] "2p Land에서 패널간 간격이 약간 커짐(0.15in
                # 여유가 필요 이상으로 넉넉함)" - 4/p(가장 좁은 칸, 최악의
                # 경우)에서 0.15in 여유가 7.3pt의 실제 여유 gap을 만드는 것으로
                # 실측 확인돼, 그보다 조금 줄여도(0.08in) 안전한지 재확인 후
                # 적용(아래에서 직접 렌더링 검증).
                spacing_w_in += 0.08

        grid_w = cell_w_in * cols + spacing_w_in * (cols - 1)
        grid_h = cell_h_in * rows + spacing_h_in * (rows - 1)
        origin_left = pad_left + max(0, (printable_w - grid_w) / 2)
        origin_top = (page_h - pad_top) - max(0, (printable_h - grid_h) / 2)
        cell_positions_in = []
        # [추가 - 요청] "Auto로 5장을 그리면 6/p 격자에 1칸이 빈 채로 나오는데,
        # 그보다는 꽉 찬 줄(3장) + 가운데로 맞춘 줄(2장)이 보기 좋다" - 6/p와
        # 같은 칸 크기·격자(rows,cols)는 그대로 쓰되, 이 경우만 배치(row/col
        # 인덱스)를 행렬 순서(row-major) 대신 "꽉 찬 줄을 먼저 순서대로, 남는
        # 줄은 그 줄의 중앙에 오도록 0.5칸씩 어긋난 위치"로 특수 처리한다
        # (다른 개수는 기존 로직 그대로 - nplot==5일 때만 해당). cell_rc는
        # 아래 마주보는 여백 재배분(LR/TB) 계산에서 실제 배치된 row/col을
        # 그대로 참고하도록(단순 i//cols, i%cols로 재계산하면 이 특수
        # 배치와 안 맞아 잘못된 칸에 재배분될 수 있음) 별도로 저장한다.
        cell_rc = []
        if layout_option == "Auto" and nplot == 5:
            if rows == 3:  # Port: 왼쪽 열 3장(row 0,1,2) + 오른쪽 열 2장(가운데)
                _idx_map = [(0, 0), (1, 0), (2, 0), (0.5, 1), (1.5, 1)]
            else:  # Land: 위쪽 행 3장(col 0,1,2) + 아래쪽 행 2장(가운데)
                _idx_map = [(0, 0), (0, 1), (0, 2), (1, 0.5), (1, 1.5)]
            for row_idx, col_idx in _idx_map:
                cell_left_in = origin_left + col_idx * (cell_w_in + spacing_w_in)
                cell_top_in = origin_top - row_idx * (cell_h_in + spacing_h_in)
                cell_positions_in.append((cell_left_in, cell_left_in + cell_w_in, cell_top_in, cell_top_in - cell_h_in))
                cell_rc.append((row_idx, col_idx))
        else:
            for i in range(total_cells):
                row_idx, col_idx = i // cols, i % cols
                cell_left_in = origin_left + col_idx * (cell_w_in + spacing_w_in)
                cell_top_in = origin_top - row_idx * (cell_h_in + spacing_h_in)
                cell_positions_in.append((cell_left_in, cell_left_in + cell_w_in, cell_top_in, cell_top_in - cell_h_in))
                cell_rc.append((row_idx, col_idx))

        size_override = f"{page_w:.3f}in,{page_h:.3f}in"
        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile, None, size_override, panel_scale=font_panel_scale),
            f"set output '{outfile.replace(chr(92), '/')}'"
        ]
        lines.append(f"set multiplot layout {rows},{cols}")

        # [수정 - 요청] "옆으로 나란한 칸끼리 마주보는 안쪽(내부) 여백은 서로
        # 여유를 나눠 쓸 수 있는데(양쪽 다 이미 그 칸 하나만 있어도 필요한
        # 만큼 꽉 채워져 있어 실제로는 남는 공간), 맨 왼쪽/맨 오른쪽 바깥쪽
        # 가장자리는 그런 여유가 전혀 없어(용지 끝) 2줄 Y2 title이 잘리는
        # 사례가 그쪽에서만 남음" - 실측 확인: 내부(패널 사이) 마주보는 합산
        # 여백(margin_right+spacing+margin_left)이 각 칸 axis 폭보다도 커서
        # (예: 4/p 26.7% > axis 25.2%) 과도했음. 내부(다른 칸과 마주보는) 쪽
        # margin은 절반으로 줄이고, 그렇게 아낀 만큼을 맨 왼쪽 칸의 바깥쪽
        # margin_left/맨 오른쪽 칸의 바깥쪽 margin_right에 절반씩 얹어준다
        # (한쪽에만 몰아주면 반대쪽만 계속 여유로워 보이는 것을 막기 위해
        # 반씩 분배 - 사용자 확인). 합계(margin_left+margin_right 총량)는
        # 그대로 보존되므로 전체 grid_w/축소 배율에는 영향이 없다.
        # [수정 - 버그, 3/p 이상에서 재발견] 위 "바깥쪽에 얹어준다"를 맨
        # 왼쪽/맨 오른쪽 칸(col_idx==0/cols-1)에만 적용하고 있어서, 3칸 이상
        # 일 때 가운데 칸(양쪽 다 "안쪽")은 이 보너스를 전혀 못 받아 옆 칸들
        # 보다 눈에 띄게 넓게(margin 총량이 작게) 나옴 - 실측 확인(3/p Manual
        # 6x4cm: 1번째/3번째 칸 axis 폭 0.1984, 가운데 칸 0.2775 - 같은
        # 칸인데 폭이 다름). "여러 칸이 전부 같은 모양이어야 한다"는 요청에
        # 맞춰 "얹어주는 보너스"(합계를 늘리는 부분)는 없애기로 함.
        # [수정 - 심각한 버그, 바로 위 정리로 새로 유발] 보너스뿐 아니라
        # "안쪽처럼 절반으로 줄이는 것"까지 맨 왼쪽/맨 오른쪽(그리고 위아래도
        # 맨 위/맨 아래)에 적용해버려서, 우측 끝 패널의 Y2 title/맨 위 행의
        # Plot Title이 필요한 공간보다 여백이 부족해져 EMF/PDF가 아예 그
        # title을 통째로 안 그림(실측 확인 - 페이지 텍스트 추출로 우측 패널
        # Y2 title이 존재 자체를 안 하는 것, 맨 위 행 title이 페이지 경계
        # 밖으로 밀려 안 보이는 것 둘 다 재현). 결론: 맨 왼쪽/오른쪽(열),
        # 맨 위/아래(행)는 "보너스"는 없어도(합계 보존 목적 포기) "혼자
        # 있을 때 필요한 만큼"(margin_* 그대로, 절반으로 줄이지 않음)은
        # 반드시 유지해야 하고, 오직 두 칸이 서로 마주보는 "진짜 안쪽" 면만
        # 절반(_interior_k)으로 줄인다. 이 경우 가운데 칸(양쪽 다 안쪽)은
        # 옆(바깥쪽 있는) 칸보다 살짜 넓게/크게 남을 수 있지만("완전 균일"
        # 목표에는 못 미침), "title이 안 보이는 것"보다는 훨씬 나은 절충안 -
        # 사용자 확인 후 이 방식으로 확정.
        _interior_k = 0.5

        # [수정 - 버그] 5장 가운데 배치 특수 케이스(row/col이 0.5 등 정수가 아님)는
        # 이 재배분(마주보는 칸끼리 안쪽 여백 절반, 바깥쪽에 얹기) 대상이 아님 -
        # 애초에 "꽉 채운 줄" 옆에 "덜 채운 줄"을 중앙 정렬한 것이라 안쪽 여백이
        # 남는 게 정상(사용자 의도: "아래위 마진은 당연히 많아짐")인데, 정수
        # row/col 기준(==0/==rows-1)에 안 맞아 그대로 두면 "안쪽"으로 잘못
        # 분류돼 오히려 마진이 반으로 줄어버림 - 이 케이스는 재배분 없이 원래
        # margin_left/right/top/bottom을 그대로 쓴다.
        _is_centered5 = (layout_option == "Auto" and nplot == 5)
        # [추가 - 요청] "경고문은 문제 있을 때만, 좌우/위아래 어디인지 포함해서" -
        # 옆 칸/위아래 칸과 마진을 나눠 쓰는 안쪽 면(_interior_k=0.5로 절반만
        # 예약)에서, 실제 라벨이 필요로 하는 물리적 공간(폰트 크기 기반 근사)이
        # 그 절반 예약분보다 크면 겹칠 위험이 있다고 보고 경고한다(전 칸에
        # 무조건 뜨는 게 아니라 실제 위험한 면만) - 같은 방향 문제가 여러
        # 칸에서 반복되면 한 번만 안내(중복 방지).
        _warned_sides = set()
        _fmt_l_chk = (fmt or "").lower()
        if _fmt_l_chk in ("pdf", "png", "jpg", "jpeg"):
            _fix_chk = CAIRO_FONT_RENDER_FIX
        elif _fmt_l_chk == "emf":
            _fix_chk = EMF_FONT_RENDER_FIX
        else:
            _fix_chk = 1.0

        def _approx_label_in(size_input):
            # ylabel/y2label/title 텍스트 한 줄이 차지하는 대략적 물리 폭(회전
            # 라벨은 폭≈글자 높이) - 실제 offset 계산과 동일한 배율(font_panel_
            # scale*PRINT_FONT_SCALE*포맷별 보정)을 근사로 재사용, 15% 여유.
            return (float(size_input or 11) * font_panel_scale * PRINT_FONT_SCALE * _fix_chk / 72.0) * 1.15

        # [수정 - 근본 원인 발견] "M-P 3/p 등 Manual 다중 열/행에서 axis x:y
        # 비율이 single-plot과 달라짐(3/p 10x8cm 실측 비율 1.393, single-plot은
        # 정확히 1.250)" - 원인: 아래 _eff_margin_left/right(안쪽 면끼리 마주보는
        # 쪽은 절반만 예약)로 "아낀" 여백을, 지금까지는 "그 칸의 axis를 그만큼
        # 더 넓힌다"(cell 경계=cell_left_in/cell_right_in은 고정인 채 eff_margin만
        # 줄여 axis_left_in~axis_right_in 사이 폭이 넓어짐)로 써왔음. 3/p처럼
        # rows=1인 레이아웃은 가로(cols>1)만 이렇게 넓어지고 세로는 원래 그대로라
        # 비율이 깨짐(실측: axis_w 3.5834->3.9934in로 커지는데 axis_h는 그대로).
        # "Manual = 지정 크기를 균일 배율로만 유지"라는 원칙에 맞게, 모든 칸의
        # axis 크기는 항상 위에서 정한 공용 axis_w/axis_h(단일 plot과 동일 계산,
        # 비율 유지)로 고정하고, 안쪽 면에서 아낀 여백은 axis를 키우는 대신
        # 옆(위/아래) 칸과의 실제 간격을 줄이는 데만 쓰이도록 누적 위치 방식으로
        # 다시 계산한다(칸을 순서대로 이어붙이며 위치 결정). 부수 효과로, 3칸
        # 이상일 때 가운데 칸만 옆칸보다 살짝 넓게 나오던 잔여 불균일 문제도
        # 함께 해소됨(모든 axis가 완전히 같은 크기가 됨). 5장 중앙정렬 특수
        # 배치(_is_centered5)는 애초에 interior_k를 안 쓰므로(여백 그대로) 이
        # 대상에서 제외 - 기존 cell 기반 계산을 그대로 둔다.
        if not _is_centered5:
            # [수정 - 버그, 위 ratio fix 도입 직후 재발견] "Auto 6/p처럼 칸이
            # 작을 때 안쪽(interior) 면끼리 마주보는 Y1/Y2 title이 완전히
            # 겹쳐 보임" - _interior_k(0.5)로 절반만 예약한 안쪽 여백이,
            # margin_left/right(위에서 이미 "이 라벨이 안 잘리려면 최소
            # 이만큼 필요"로 계산해 둔 _need_left_in/_need_right_in 바닥값)의
            # 절반보다도 작아지는 경우가 있어(Auto는 칸이 작아 margin 자체가
            # 이미 빠듯한 최소치 근처) 실측 확인(좌우 두 title이 거의 같은
            # x좌표에 겹쳐 그려짐). 안쪽 면 예약은 "절반(0.5배)"과 "실제로
            # 안 겹치는 데 필요한 최소치(_need_*_in)" 중 큰 쪽으로 하고(단,
            # 혼자 있을 때 값인 margin_* 자체는 넘지 않음), 그 결과 칸 전체
            # 폭/높이가 용지에 안 들어가면 - 마진이 아니라 - axis(plot 크기)
            # 쪽만 균일 배율로 줄여서 맞춘다(가로/세로 같은 배율 -> 비율 유지,
            # "plot 크기를 줄이되 x:y는 유지"라는 요청과 일치).
            _col_gap_l = [margin_left if (c == 0 or cols == 1) else max(margin_left * _interior_k, min(margin_left, _need_left_in)) for c in range(cols)]
            _col_gap_r = [margin_right if (c == cols - 1 or cols == 1) else max(margin_right * _interior_k, min(margin_right, _need_right_in)) for c in range(cols)]
            # [수정 - 회귀 발견] 위 LR과 똑같이 "최소치 바닥"을 TB에도 적용했더니,
            # margin_top/bottom이 이미 자기 자신의 need 바닥값과 같은(=바닥이
            # 이미 이겨서 정해진) 흔한 경우엔 절반(_interior_k)이 이 바닥값보다
            # 항상 작아 결국 항상 "안 줄임"이 돼버려, 위아래로 여러 칸일 때
            # (예: Auto 3/p Portrait) 칸 사이 간격이 지나치게 커짐(실측: margin_top=
            # need_top=0.75in, margin_bottom=need_bottom=0.85in로 정확히 일치하는
            # 흔한 경우라 절반 축소가 전혀 적용 안 됨). 하지만 이걸 단순
            # 절반으로 되돌려봤더니 - 실측 확인 - Auto 6/p Landscape(2행)에서
            # 아래 행 Plot Title이 위 행 xlabel/tic과 실제로 9.5pt 겹치는
            # 회귀가 재현됨(title은 ylabel/y2label과 달리 margin 축소에 맞춰
            # offset을 같이 줄여주는 장치가 아직 없어서, 절반으로 줄인 여백
            # 안에 안 들어가고 넘침). 그 offset 연동은 아직 구현이 안 돼 있어
            # (추후 별도 보정 필요), 지금은 안전한 최소치 바닥을 다시 쓰고,
            # "간격이 커 보인다"는 원래 불만은 아래 axis 확대(그로우) 단계로
            # 완화한다(칸 자체가 커지면 같은 절대 간격도 상대적으로 덜 커
            # 보임).
            _row_gap_t = [margin_top if (r == 0 or rows == 1) else max(margin_top * _interior_k, min(margin_top, _need_top_in)) for r in range(rows)]
            _row_gap_b = [margin_bottom if (r == rows - 1 or rows == 1) else max(margin_bottom * _interior_k, min(margin_bottom, _need_bottom_in)) for r in range(rows)]

            _row_w_total = sum(axis_w + _col_gap_l[c] + _col_gap_r[c] for c in range(cols)) + spacing_w_in * (cols - 1)
            _col_h_total = sum(axis_h + _row_gap_t[r] + _row_gap_b[r] for r in range(rows)) + spacing_h_in * (rows - 1)
            _axis_fit_scale = 1.0
            if _row_w_total > printable_w > 0:
                _budget_w = printable_w - sum(_col_gap_l) - sum(_col_gap_r) - spacing_w_in * (cols - 1)
                if axis_w * cols > 0:
                    _axis_fit_scale = min(_axis_fit_scale, max(_budget_w, 0.05 * cols) / (axis_w * cols))
            if _col_h_total > printable_h > 0:
                _budget_h = printable_h - sum(_row_gap_t) - sum(_row_gap_b) - spacing_h_in * (rows - 1)
                if axis_h * rows > 0:
                    _axis_fit_scale = min(_axis_fit_scale, max(_budget_h, 0.05 * rows) / (axis_h * rows))
            if _axis_fit_scale < 0.999:
                axis_w *= _axis_fit_scale
                axis_h *= _axis_fit_scale
                _row_w_total = sum(axis_w + _col_gap_l[c] + _col_gap_r[c] for c in range(cols)) + spacing_w_in * (cols - 1)
                _col_h_total = sum(axis_h + _row_gap_t[r] + _row_gap_b[r] for r in range(rows)) + spacing_h_in * (rows - 1)

            # [추가 - 요청] "칸 사이 간격을 줄인 만큼 남는 공간을 그냥 버리지
            # 말고 axis(plot 크기)를 키우는 데 써라" - 안쪽 면 절반 축소로
            # 여백은 줄었는데, Auto는 axis_w/axis_h가 이미 (줄이기 전) margin
            # 기준으로 고정돼 있었고 Manual은 axis를 일부러 고정(비율 버그
            # 수정)해 둬서, 둘 다 이 절약분이 빈 공간으로 남기만 했음(실측:
            # Auto 3/p Portrait에서 위아래 빈 공간이 페이지의 상당 부분).
            # 남는 여백만큼 axis_w/axis_h를 가로세로 같은 배율로 키운다(비율
            # 유지) - Manual의 "1/p, 2/p는 지정 크기 그대로" 원칙은 지켜야 하니
            # 그 둘은 제외하고 3칸 이상(기존 shrink-to-fit도 3칸부터 적용되던
            # 것과 동일 기준)에서만, 그리고 Auto는 애초에 "용지를 채운다"는
            # 원칙이라 칸 수 제한 없이 적용한다. margin/font는 그대로 두고
            # axis(순수 그림 영역)만 키운다.
            if (frame_auto or total_cells >= 3) and cols > 0 and rows > 0 and axis_w > 0 and axis_h > 0:
                _budget_w2 = printable_w - sum(_col_gap_l) - sum(_col_gap_r) - spacing_w_in * (cols - 1)
                _budget_h2 = printable_h - sum(_row_gap_t) - sum(_row_gap_b) - spacing_h_in * (rows - 1)
                _cand_w = (_budget_w2 / (axis_w * cols)) if _budget_w2 > 0 else 0.0
                _cand_h = (_budget_h2 / (axis_h * rows)) if _budget_h2 > 0 else 0.0
                # [수정 - 재활성화] "Auto 4/p·6/p(Land/Port) 캔버스 상하 여유가
                # 너무 큼(실측: 상하 각 10~14%, 합 20~27%가 빈 캔버스로 낭비)" -
                # 이전엔 이 겹침 회귀(맨 위 행 title이 페이지 밖으로 밀림/아래
                # 행 title이 위 행 xlabel과 겹침) 때문에 total_cells>=4+다행
                # 조합의 세로 확대를 막아 뒀었는데, 그 근본 원인은 _floor_scale이
                # margin_scale 기반이라 실제 font_panel_scale보다 작았던 것이었고
                # (바로 위 _floor_scale=max(margin_scale, font_panel_scale*0.7)
                # 로 이미 수정함) - 이제는 세로 확대를 다시 켜도 겹치지 않음을
                # 재검증(4/p +20.2pt, 6/p +12.7pt, Port도 동일, LR도 20pt+ 안전,
                # 2줄 라벨 텍스트 소실 없음, off-page 없음 - 전부 실측 확인) -
                # 다시 켠다(캔버스 여유 10~14% -> 2~3%로 감소).
                _h_grow_safe = True
                # [수정 - 요청] "Auto 3/p Portrait처럼 가로는 이미 꽉 찼는데
                # 세로만 남는 경우, 비율을 지키느라 가로에 발목 잡혀 세로가
                # 거의 안 커짐" - Manual(비율 유지 확정, 오늘 앞선 수정)과
                # Auto 1/p(비율 유지 원칙, rows==cols)는 가로세로를 같은
                # 배율로만 키우지만, Auto 2/p 이상(원래도 "비율 무시하고
                # 채운다"는 기존 원칙 - 사용설명서 5절 참고)은 가로/세로를
                # 각자 남는 만큼 독립적으로 키운다.
                # [검토 - 되돌림] rows==1/cols==1일 때 세로(또는 가로)가
                # 한도 없이 커지는 걸 "비정상"으로 보고 비율 유지 대상에
                # 넣었으나, 실제 렌더링 픽셀 비교 결과 눈에 띄는 문제가
                # 아니었고 "Auto는 남는 여백을 axis 확대에 쓴다"는 의도
                # 그대로였음 - 원래 조건으로 되돌린다.
                _ratio_locked_grow = (not frame_auto) or (total_cells <= 2 and rows == cols)
                if _ratio_locked_grow:
                    if not _h_grow_safe:
                        _cand_h = 1.0
                    _grow_scale = max(1.0, min(_cand_w, _cand_h)) if (_budget_w2 > 0 and _budget_h2 > 0) else 1.0
                    if _grow_scale > 1.001:
                        axis_w *= _grow_scale
                        axis_h *= _grow_scale
                        # [수정 - 요청] "그림(axis)은 커졌는데 폰트/legend는 그대로라
                        # 상대적으로 작아 보임" - margin/font를 그대로 두고 axis만
                        # 키웠더니, 오늘 앞서 힘들게 맞춘 "legend 폭이 axis의
                        # 1/3~1/4" 같은 비율이 axis만 커진 만큼 깨짐(legend/폰트가
                        # 상대적으로 작아 보임 - 사용자 확인). font_panel_scale도
                        # 같은 배율로 키워 폰트·legend가 axis와 함께 커지게 한다.
                        # [주의] margin(_col_gap_l/r, _row_gap_t/b)은 이미 이
                        # 키우기 "전"의(더 작은) font_panel_scale 기준으로 정해져
                        # 있어, 폰트를 키우면 이론적으로 그 여백이 빠듯해질 수
                        # 있음 - 아래에서 2/p, 3/p, 6/p Manual 전부 실측(좌표)
                        # 재검증해서 겹침/잘림 없는 것 확인 후 확정.
                        font_panel_scale *= _grow_scale
                else:
                    _grow_w = _cand_w if (_budget_w2 > 0 and _cand_w > 1.0) else 1.0
                    _grow_h = _cand_h if (_h_grow_safe and _budget_h2 > 0 and _cand_h > 1.0) else 1.0
                    if _grow_w > 1.001:
                        axis_w *= _grow_w
                    if _grow_h > 1.001:
                        axis_h *= _grow_h
                    # [수정 - 요청, 위 ratio_locked 경로와 동일 이유] 가로/세로를
                    # 독립 배율로 키우는 이 경로(Auto 2칸 이상)도 axis만 커지고
                    # 폰트/legend가 그대로면 상대적으로 작아 보이므로 같이
                    # 키운다. 두 방향 배율이 다를 수 있어 기하평균(면적 기준
                    # 중간값)을 폰트 배율로 쓴다 - 더 작은 쪽(_h_grow_safe=False라
                    # 세로가 아예 안 커진 경우 등) 방향에 과하게 맞춰 폰트가
                    # 너무 커지지 않도록.
                    # [주의] _h_grow_safe가 total_cells>=4+다행에서 다시 False로
                    # 돌아갔으므로(위 참고) _grow_h는 그 경우 이미 1.0으로 고정돼
                    # 있음 - 이 식은 그대로 두어도 안전.
                    _font_grow = (_grow_w * _grow_h) ** 0.5
                    if _font_grow > 1.001:
                        font_panel_scale *= _font_grow
                _row_w_total = sum(axis_w + _col_gap_l[c] + _col_gap_r[c] for c in range(cols)) + spacing_w_in * (cols - 1)
                _col_h_total = sum(axis_h + _row_gap_t[r] + _row_gap_b[r] for r in range(rows)) + spacing_h_in * (rows - 1)

            _col_axis_left = [0.0] * cols
            _col_axis_right = [0.0] * cols
            _cx = pad_left + max(0.0, (printable_w - _row_w_total) / 2)
            for c in range(cols):
                _col_axis_left[c] = _cx + _col_gap_l[c]
                _col_axis_right[c] = _col_axis_left[c] + axis_w
                _cx = _col_axis_right[c] + _col_gap_r[c] + spacing_w_in

            _row_axis_top = [0.0] * rows
            _row_axis_bottom = [0.0] * rows
            _cy = (page_h - pad_top) - max(0.0, (printable_h - _col_h_total) / 2)
            for r in range(rows):
                _row_axis_top[r] = _cy - _row_gap_t[r]
                _row_axis_bottom[r] = _row_axis_top[r] - axis_h
                _cy = _row_axis_bottom[r] - _row_gap_b[r] - spacing_h_in

        for i, plotdef in enumerate(plots):
            cell_left_in, cell_right_in, cell_top_in, cell_bottom_in = cell_positions_in[i]
            _row_idx, _col_idx = cell_rc[i]
            if cols > 1 and not _is_centered5:
                # [수정 - 심각한 버그, 방금 위 통일이 유발] "우측 끝 패널의 Y2
                # title이 통째로 안 보임" - 바깥쪽(용지 쪽) 보너스를 없애면서
                # 맨 오른쪽 칸의 margin_right까지 안쪽처럼 절반으로 깎아버려서,
                # Y2 title이 실제로 필요한 공간보다 여백이 부족해져 EMF/PDF가
                # 통째로 안 그림(실측 확인 - 페이지 전체 텍스트 추출로 우측
                # 패널의 Y2 title이 존재 자체를 안 함). 맨 왼쪽/맨 오른쪽은
                # "보너스"(추가로 더 주기)는 없애더라도 "안쪽처럼 절반으로
                # 줄이는 것"까지는 하면 안 됨 - 원래 그 칸 혼자 있을 때 필요한
                # 만큼(margin_left/right 그대로, 보너스 없이)은 유지한다.
                # 그래도 가운데 칸(양쪽 다 진짜 안쪽)은 절반이라 옆(=바깥쪽 있는
                # 칸)보다 조금 넓게 나올 수 있지만, "title이 안 보이는 것"보다는
                # 훨씬 나은 절충안.
                # [수정 - 일관성] 실제 axis 위치 계산에 쓰는 _col_gap_l/r(바로
                # 위, 겹침 방지 최소치로 떠받친 값)과 다른 값을 쓰면 경고 판단/
                # offset 축소 비율이 실제 그려지는 여백과 어긋나므로, 같은
                # 값을 그대로 재사용한다(단일 소스).
                _eff_margin_left = _col_gap_l[_col_idx]
                _eff_margin_right = _col_gap_r[_col_idx]
            else:
                _eff_margin_left = margin_left
                _eff_margin_right = margin_right
            if rows > 1 and not _is_centered5:
                _eff_margin_top = _row_gap_t[_row_idx]
                _eff_margin_bottom = _row_gap_b[_row_idx]
            else:
                _eff_margin_top = margin_top
                _eff_margin_bottom = margin_bottom
            if _is_centered5:
                axis_left_in = cell_left_in + _eff_margin_left
                axis_right_in = cell_right_in - _eff_margin_right
                axis_top_in = cell_top_in - _eff_margin_top
                axis_bottom_in = cell_bottom_in + _eff_margin_bottom
            else:
                # [수정 - 근본 원인 수정] axis 크기를 cell 경계 기준(가변)이 아니라
                # 위에서 미리 계산한 공용 고정 크기(axis_w/axis_h, 모든 칸 동일,
                # single-plot과 같은 비율)로 둔다 - 위 주석 참고.
                axis_left_in = _col_axis_left[_col_idx]
                axis_right_in = _col_axis_right[_col_idx]
                axis_top_in = _row_axis_top[_row_idx]
                axis_bottom_in = _row_axis_bottom[_row_idx]

            if (plotdef.ylabel or "").strip() and "왼쪽" not in _warned_sides:
                if (_eff_margin_left - _min_left_tic_in) < _approx_label_in(plotdef.ylabel_size):
                    _warned_sides.add("왼쪽")
            if (plotdef.y2label or "").strip() and "오른쪽" not in _warned_sides:
                if (_eff_margin_right - _min_right_tic_in) < _approx_label_in(plotdef.y2label_size):
                    _warned_sides.add("오른쪽")
            if (plotdef.title or "").strip() and rows > 1 and "위아래" not in _warned_sides:
                if _eff_margin_top < margin_top * 0.9:
                    _approx_title_in = _approx_label_in(plotdef.title_size) * 0.9  # title은 회전 없이 가로 텍스트라 필요 높이만 비교
                    if _eff_margin_top < _approx_title_in:
                        _warned_sides.add("위아래")

            # [정리] 예전에 여기 있던 "if i > 0: unset title / set xtics auto / ..."
            # 리셋 코드는 실제로는 죽은 코드였음 - 바로 아래 _build_plot_commands가
            # 매 패널마다 title/xtics/ytics/y2tics를 그 plotdef 고유 값으로 무조건
            # 다시 설정하기 때문에, 이 리셋은 최종 출력에 전혀 영향을 주지 못하고
            # 곧바로 덮어써짐. 각 패널의 커스텀 title/축 설정을 잃어버릴 위험도
            # 없었지만(항상 그 패널 고유 값으로 재설정되므로), 혼동을 줄 수 있어 제거함.

            # [추가] 마진 계산이 어떤 경로로든 [0,1] 화면 비율을 벗어나면(예: 그리드가
            # 용지 밖으로 밀려남) gnuplot이 해당 칸을 그리지 못해 "4/p인데 3개만,
            # 2/p인데 1개만 저장됨" 같은 문제가 생겼음 - 원인(위의 cell 크기 재계산)을
            # 고쳤지만, 방어적으로 여기서도 항상 유효한 [0,1] 범위 안으로 clamp한다.
            lm = max(0.0, min(axis_left_in / page_w, 0.98))
            rm = max(lm + 0.01, min(axis_right_in / page_w, 1.0))
            tm = max(0.02, min(axis_top_in / page_h, 1.0))
            bm = max(0.0, min(axis_bottom_in / page_h, tm - 0.01))
            lines.append(f"set lmargin at screen {lm:.4f}")
            lines.append(f"set rmargin at screen {rm:.4f}")
            lines.append(f"set tmargin at screen {tm:.4f}")
            lines.append(f"set bmargin at screen {bm:.4f}")

            # [추가] "6/p 기준 legend를 조금 더 키워달라" - margin/간격을 많이
            # 줄이면서 axis가 커진 만큼, legend(font_panel_scale 그대로)는 상대적으로
            # 작아 보임 - 칸이 많을 때(4/p 이상)만 legend 글자 크기를 별도로
            # 살짜 키운다(축/제목/tic 폰트는 그대로 유지).
            _legend_boost = 1.3 if total_cells >= 3 else 1.0
            # [수정 - 근본 원인 발견] "legend가 축 대비 상대적으로 커 보임(실측:
            # PDF에서 legend box 폭이 axis 폭의 95%+)" - 실제 원인은 legend
            # font가 title/xlabel/ylabel과 달리 font_panel_scale을 그대로(sqrt
            # 완화 없이) 곱해서 커졌기 때문. Axis Frame Auto + 칸이 기준보다
            # 커서(font_panel_scale>1, 1p/2p Auto에서 흔함) title 등은 sqrt로
            # 완화됐는데 legend는 그대로 선형으로 커져 있었음 - legend도 같은
            # sqrt 완화가 적용된 것처럼 보이도록 _legend_boost에 보정 계수를
            # 곱해 상쇄한다(margin_scale은 이미 1.0 상한이 있어 축은 그대로,
            # legend만 커졌던 불균형을 없앤다).
            # [수정 - 재조정] "legend가 지금의 2배는 돼야 적절해 보임" - title 등
            # 폰트는 완전 고정(1.0)이 아니라 sqrt로 "일부만" 완화됐는데(직전
            # 커밋), legend는 font_panel_scale로 나눠서 완전히(1.0으로) 고정해
            # 버려서 title/xlabel보다도 오히려 더 작아졌음(실측 확인) - title과
            # 같은 sqrt 완화 수준으로 맞춘다(완전히 상쇄하지 않고 절반만).
            # [수정 - 재조정] title은 이후 요청으로 "거의 완전 고정(1.0)"으로
            # 더 줄었지만(_title_f_scale 참고), legend는 반대로 "EMF/SVG에서
            # 계속 작게 나온다"는 피드백이라 title과 반대 방향으로 더
            # 키워야 함 - title 변경과 무관하게 legend만 독립적으로 나눗셈
            # 지수를 0.5(제곱근)에서 0.3으로 낮춰(나누는 값이 작아짐 ->
            # legend가 더 커짐) 추가로 키운다.
            if frame_auto and font_panel_scale > 1.0:
                _legend_boost /= font_panel_scale ** 0.3
            if os.environ.get("_CATHPLOT_DEBUG_SCALE") and i == 0:
                print(f"[DEBUG] fmt={fmt} layout={layout_option} orient={orientation} rows={rows} cols={cols} "
                      f"font_panel_scale={font_panel_scale:.4f} legend_boost={_legend_boost:.4f} "
                      f"axis_w_in={axis_right_in-axis_left_in:.4f} axis_h_in={axis_top_in-axis_bottom_in:.4f} "
                      f"cell_w_in={cell_w_in:.4f} cell_h_in={cell_h_in:.4f} "
                      f"margin_left={margin_left:.4f} margin_right={margin_right:.4f} "
                      f"margin_top={margin_top:.4f} margin_bottom={margin_bottom:.4f} "
                      f"spacing_w_in={spacing_w_in:.4f} spacing_h_in={spacing_h_in:.4f} "
                      f"page_w={page_w:.4f} page_h={page_h:.4f}", file=sys.stderr)
            # [수정] "2/p는 legend box 좌우길이를 1자 정도 키우고, 4/p, 6/p는
            # 2자 줄이고" - print 기준 여유분(0.7자)에서 레이아웃별로 가감한다.
            # [수정 - 버그, 오늘 legend box_chars 재보정 후 재검증 안 함] "3/p
            # 이상에서 legend title이 box 왼쪽 테두리를 넘어 삐져나옴" - 이
            # "-2.0자" 감산은 CAIRO_FONT_RENDER_FIX(폰트가 실제보다 크게
            # 부풀려지던 시절)에 맞춰 정한 값인데, 그 폰트 확대 버그를 이미
            # 제거하고 box_chars(테두리-텍스트 여백)도 최댓값 문자열 기준으로
            # 다시 보정해서 지금은 여유가 거의 없음 - 여기 추가 감산까지 겹치면
            # 실제로 넘침(실측: PDF 좌표로 텍스트 시작점이 box 왼쪽 테두리보다
            # 7.15pt 더 왼쪽에서 시작 = 겹쳐 나옴). 3개 이상 칸에서 box를 좁혀야
            # 할 근거가 지금은 없으므로(재측정 필요해지면 그때 다시 조정)
            # 감산을 없앤다.
            # [수정 - 버그] "Land-2/p, 3/p·Port-4/p, 6/p에서 legend 안 margin이
            # font 대문자 1자가 아니라 2~3자로 보임(box가 plot을 더 차지함)" -
            # 실측(PyMuPDF, box 좌측 테두리<->실제 렌더된 텍스트 좌측 끝 간격을
            # 렌더된 legend font 크기 기준 "글자 수"로 환산)해서 재현: 3/p·4/p·
            # 6/p(다 여기 else 분기, 0.7자)는 정확히 1.0자로 딱 맞았는데, 2/p만
            # (이 위 total_cells<=2 분기, 0.7+1.0=1.7자) 2.5자로 나와 확실히
            # 과함. 원인: 이 "+1.0자" 가산은 max_label_len을 대략적인 문자
            # 가중치로 추정하던 시절(실제 폭보다 부정확)에 넣은 안전 여유였는데,
            # 그 뒤 max_label_len이 PIL 실측(_measure_text_width_in) 기준으로
            # 정확해져서(3/p 이상에서 검증되듯 0.7자만으로 이미 정확히 1자) 이
            # 가산이 그대로 남아 2/p에서만 불필요한 1자만큼 여백이 남았던 것 -
            # total_cells<=2 특례를 없애고 모든 레이아웃이 동일한 0.7자를 쓰게
            # 통일한다(재검증: 1/p·2/p 모두 box 밖으로 삐져나오는 것 없이 여전히
            # 안전, 여백만 정확히 1자로 줄어듦).
            _legend_w_extra = 0.7
            # [수정 - 심각한 버그 발견] "EMF만 y1/y2 title이 사라짐(Multi Print/
            # Batch Set 등 멀티플롯 경로에서만)" - 실제 EMF 바이너리를 직접
            # 파싱해서 확인: 원인은 title이 잘못된 위치에 그려진 게 아니라, 이
            # 호출에 fmt가 전혀 전달되지 않아 _build_plot_commands 안의 모든
            # fmt 분기(_is_emf, cairo dash 부스트, 포맷별 legend/tic 보정 등)가
            # 멀티플롯에서는 늘 fmt=None(일반 분기)으로 동작하고 있었음 - EMF
            # 전용 offset(-3/3)도 적용이 안 돼 cairo용 비율식이 EMF에 잘못
            # 쓰이면서 (margin이 EMF의 실측값과 달라) title이 캔버스 밖으로
            # 밀려 사라진 것. fmt를 그대로 전달해서 단일 plot(create_script)과
            # 동일한 포맷별 분기가 항상 적용되게 한다.
            # [추가 - 근본 원인 수정] "옆 칸끼리 Y1/Y2 title 겹침" - 위
            # _eff_margin_left/right(이 칸이 실제로 받은 여백, 안쪽 면은
            # _interior_k=0.5로 절반만)를, offset 계산이 가정하는 "혼자 있을
            # 때" 기준값(margin_left/margin_right)과 비교한 비율로 넘겨서
            # _build_plot_commands가 offset도 같이 줄이게 한다(바깥쪽 면/
            # 1열·1행뿐인 레이아웃은 비율≈1.0이라 기존과 동일 - 회귀 없음).
            _y1_margin_ratio = (_eff_margin_left / margin_left) if margin_left > 1e-6 else 1.0
            _y2_margin_ratio = (_eff_margin_right / margin_right) if margin_right > 1e-6 else 1.0
            # [추가 - 요청] "Auto 4칸 이상 + 다행 레이아웃 세로 확대" 재활성화 대비 -
            # ylabel/y2label과 동일한 개념을 Plot Title(margin_top)/xlabel(margin_bottom)
            # 에도 적용해서, 안쪽 면 축소로 margin이 줄어들 때 title/xlabel도 축 쪽으로
            # 당겨지게 한다(위 y1/y2와 동일한 비율 계산 방식).
            _title_margin_ratio = (_eff_margin_top / margin_top) if margin_top > 1e-6 else 1.0
            _xlabel_margin_ratio = (_eff_margin_bottom / margin_bottom) if margin_bottom > 1e-6 else 1.0
            self._build_plot_commands(
                plotdef, lines, is_multiplot=True, panel_scale=font_panel_scale,
                annotations=getattr(plotdef, "annotations", None),
                arrows=getattr(plotdef, "arrows", None),
                circles=getattr(plotdef, "circles", None),
                axis_w_in=axis_right_in - axis_left_in,
                axis_h_in=axis_top_in - axis_bottom_in,
                fmt=fmt,
                legend_scale_boost=_legend_boost,
                legend_width_extra_chars=_legend_w_extra,
                frame_auto=frame_auto,
                ylabel_margin_ratio=_y1_margin_ratio,
                y2label_margin_ratio=_y2_margin_ratio,
                title_margin_ratio=_title_margin_ratio,
                xlabel_margin_ratio=_xlabel_margin_ratio,
            )

        if "왼쪽" in _warned_sides or "오른쪽" in _warned_sides:
            _side_txt = "/".join(s for s in ("왼쪽", "오른쪽") if s in _warned_sides)
            self.warnings.append(
                f"{_side_txt} Y title이 옆 칸의 title과 겹쳐 보일 수 있습니다(칸이 "
                f"여러 개라 그쪽 여백을 나눠 씁니다). 겹쳐 보이면 Y2 title을 "
                f"비우거나(tic 숫자만 표시), Plot Title을 지우거나, 칸 수를 "
                f"줄이는 걸 권장합니다."
            )
        if "위아래" in _warned_sides:
            self.warnings.append(
                "Plot Title이 위 행(row)의 X title/tic과 겹쳐 보일 수 있습니다"
                "(위아래로 여러 칸이라 그쪽 여백을 나눠 씁니다). 겹쳐 보이면 "
                "Plot Title을 지우거나 행 수를 줄이는 걸 권장합니다."
            )

        lines.append("unset multiplot")
        lines.append("set output")

        script_text = "\n".join(lines)
        gnuplot_exe = _resolve_gnuplot_exe()

        if keep_script:
            # Save 모드: 스크립트 파일 자체를 남겨서 나중에 열람/재사용할 수 있게 함
            script_path = outfile.rsplit(".", 1)[0] + ".plt"
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script_text)

            result = subprocess.run(
                [gnuplot_exe, script_path], capture_output=True, text=True,
                encoding="utf-8", errors="replace", cwd=plot_dir, **_no_console_kwargs()
            )
            if result.returncode != 0:
                raise RuntimeError(f"gnuplot 실행 실패 (스크립트 보존됨: {script_path})\n{result.stderr.strip()}")
        else:
            # Batch/Print(임시 산출물): 디스크에 스크립트 파일을 쓰지 않고 stdin으로 바로 전달
            result = subprocess.run(
                [gnuplot_exe],
                input=script_text, text=True, encoding="utf-8", errors="replace",
                capture_output=True, cwd=plot_dir, **_no_console_kwargs()
            )
            if result.returncode != 0:
                debug_path = os.path.join(plot_dir, f".cathplot_failed_{uuid.uuid4().hex}.plt")
                try:
                    with open(debug_path, "w", encoding="utf-8") as f:
                        f.write(script_text)
                except OSError:
                    debug_path = None
                msg = f"gnuplot 실행 실패 (반환 코드 {result.returncode})"
                stderr_text = (result.stderr or "").strip()
                if stderr_text:
                    msg += f":\n{stderr_text}"
                if debug_path:
                    msg += f"\n\n(스크립트 보존됨: {debug_path})"
                raise RuntimeError(msg)

        if fmt.lower() == "png":
            _upscale_png_dpi(outfile)

        _want_texts = []
        for _pd in plots:
            for _raw in (_pd.title, _pd.xlabel, _pd.ylabel, _pd.y2label):
                _want_texts.extend(_ln.strip() for _ln in (_raw or "").split("|") if _ln.strip())
        self._check_text_loss(outfile, fmt, _want_texts)

        return outfile
