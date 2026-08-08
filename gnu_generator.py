# -*- coding: utf-8 -*-

from data_parser import CathenaDatParser  # 파서 모듈 임포트
from dataclasses import dataclass, field
import math
import os
import re
import shutil
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
        import fitz
    except ImportError:
        return False
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
        doc.close()
        return True
    except Exception:
        return False

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
_CAIRO_DASH_BOOST_THRESHOLD = 2.0  # 이 값보다 작은 세그먼트가 있는 패턴만 대상("dash"처럼
                                    # 세그먼트가 이미 충분히 긴 패턴은 그대로 둔다)
def _dash_pattern_for_fmt(linestyle, fmt):
    base = DASH_PATTERNS.get(linestyle)
    if base is None:
        return None
    if (fmt or "").lower() not in ("pdf", "png", "jpg", "jpeg"):
        return base
    try:
        nums = [float(v.strip()) for v in base.split(",")]
    except ValueError:
        return base
    if min(nums) >= _CAIRO_DASH_BOOST_THRESHOLD:
        return base
    nums = [v * _CAIRO_DASH_BOOST for v in nums]
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
PRINT_TIC_MAJOR_SCALE = 1.0
PRINT_TIC_MINOR_SCALE = 0.5

#----------------------------------------------------------
# Page (physical paper) absolute margins - PRINT/SAVE 공통
# (나중에 조정하기 쉽도록 파일 앞쪽에 파라미터로 배치)
#----------------------------------------------------------
PAGE_MARGIN_LEFT_CM = 2.0
PAGE_MARGIN_RIGHT_CM = 1.0
PAGE_MARGIN_TOP_CM = 3.0
PAGE_MARGIN_BOTTOM_CM = 2.0
SAVE_PAGE_MARGIN_CM = 0.3  # Save(파일 저장)는 물리적 인쇄 불가 영역 제약이 없어 최소 여백만 사용

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
CELL_SPACING_IN = 0.10        

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
        self.last_size_warning = None  # 종이 여백 부족으로 plot 크기를 자동 축소했을 때 메시지가 여기 담김
        self.warnings = []  # create_script/create_multiplot_script 호출 중 발견된 경고 메시지 목록(legend 폰트 과대 등)

    @staticmethod
    def _format_number(value):
        return format(value, ".12g")

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
        if is_log_x and ref_max > 0:
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
        if is_print_mode and (fmt or "").lower() in ("pdf", "png", "jpg", "jpeg"):
            _legend_font_extra *= 1.1
        font_pt = (legend_size if legend_size else 9) * f_scale * _legend_font_extra
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
        _FORMAT_TUNING = {
            "png": {"row_mult": 2.0,           "box_chars": 14.0, "sample_mult": 2 / 3,   "text_corr": 1.0},
            "pdf": {"row_mult": 2.0 * 0.5,      "box_chars": 1.5, "sample_mult": (2/3)**2, "text_corr": 2 / 3},
            "emf": {"row_mult": 2.0 * (2 / 3),  "box_chars": -2.25, "sample_mult": (2 / 3) * 0.8, "text_corr": 1.0},
            "jpg": {"row_mult": 2.0 * (2 / 3),  "box_chars": 1.5, "sample_mult": 2 / 3,   "text_corr": 1.0},
            "jpeg": {"row_mult": 2.0 * (2 / 3), "box_chars": 1.5, "sample_mult": 2 / 3,   "text_corr": 1.0},
            "svg": {"row_mult": 2.0 * (2 / 3) * 0.8, "box_chars": -5.0, "sample_mult": 0.5, "text_corr": 1.0},
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
        _legend_tuning = (_FORMAT_TUNING.get(_fmt_l, {"row_mult": 1.2, "box_chars": 2.0, "sample_mult": 1.0, "text_corr": 1.0})
                          if is_print_mode else {"row_mult": 1.2, "box_chars": -0.5, "sample_mult": 1.0, "text_corr": 1.0})
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
        if box_w > 0.5 or box_h > 0.5:
            self.warnings.append(
                f"Legend box가 axis 크기의 절반을 넘습니다(가로 {box_w*100:.0f}%, "
                f"세로 {box_h*100:.0f}%). Legend Font 크기, curve title 길이, "
                f"curve 개수를 줄이거나 Frame 크기를 키워보세요."
            )

        if "right" in corner:
            box_right, box_left = ax, ax - box_w
        elif "left" in corner:
            box_left, box_right = ax, ax + box_w
        else:
            box_left, box_right = ax - box_w / 2, ax + box_w / 2

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
                symbol_pt = font_pt * MARKER_SIZE_SCALE.get(marker_shape, 1.0)
                lines.append(
                    f'set label {id_offset + 5000 + row_i + 1} "{MARKER_SYMBOL_MAP[marker_shape]}" '
                    f'at graph {sample_mid_x:.4f},{symbol_y:.4f} center front '
                    f'font "{font_name},{int(round(symbol_pt))}" textcolor rgb "{color}"'
                )
            lbl_text, lbl_enh = self._render_text(curve.title)
            lines.append(
                f'set label {id_offset + row_i + 1} "{lbl_text}" at graph {label_x:.4f},{row_y:.4f} '
                f'{label_just} front font "{font_name},{int(font_pt)}" {lbl_enh}'
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
                f_scale *= 0.75
        else:
            f_scale = SCREEN_FONT_SCALE * (panel_scale or 1.0)
        return f_scale

    def _build_plot_commands(self, plotdef, lines, is_multiplot=False, annotations=None, arrows=None, circles=None, panel_scale=1.0, axis_w_in=None, axis_h_in=None, fmt=None, legend_scale_boost=1.0, legend_width_extra_chars=None):
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
            # [수정 - 버그] "EMF는 PDF보다 폰트가 크지만, 그래도 1.5배 더
            # 키워달라(PDF/PNG/JPG를 2배로 키운 것과 맞춰서)" - EMF는 이미
            # 자체적으로 더 크게 보이던 포맷이라 PDF와 똑같이 2배를 다 주면
            # 과할 것으로 보여, 원래(오늘 수정 전) 기준 0.80의 1.5배인 1.2
            # 상당(=지금 전역값 1.60의 0.75배)만 적용한다.
            if (fmt or "").lower() == "emf":
                f_scale *= 0.75
        else:
            f_scale = SCREEN_FONT_SCALE * panel_scale
            line_scale = SCREEN_LINE_SCALE * panel_scale
            border_scale = SCREEN_BORDER_SCALE * panel_scale

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
        if plotdef.yauto:
            nice_y1 = self._nice_axis_range(plotdef, "y1", is_log=getattr(plotdef, "y1log", False))
            if nice_y1:
                ymin, ymax, y1_auto_tics = nice_y1
                lines.append(f"set yrange [{self._format_number(ymin)}:{self._format_number(ymax)}]")
            else:
                lines.append("set autoscale y")
        else:
            _ymin, _ymax = self._safe_manual_range(plotdef.ymin, plotdef.ymax, getattr(plotdef, "y1log", False))
            lines.append(f"set yrange [{_ymin}:{_ymax}]")

        uses_y2 = uses_y2_for_log

        y2_auto_tics = ""
        if uses_y2 and not getattr(plotdef, "y2auto", True):
            _y2min, _y2max = self._safe_manual_range(plotdef.y2min, plotdef.y2max, getattr(plotdef, "y2log", False))
            lines.append(f"set y2range [{_y2min}:{_y2max}]")
        elif uses_y2:
            nice_y2 = self._nice_axis_range(plotdef, "y2", is_log=getattr(plotdef, "y2log", False))
            if nice_y2:
                y2min, y2max, y2_auto_tics = nice_y2
                lines.append(f"set y2range [{self._format_number(y2min)}:{self._format_number(y2max)}]")
            else:
                lines.append("set autoscale y2")
        else:
            lines.append("set link y2")

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
            lines.append(f"set grid {' '.join(grid_parts)} lw 1.5, lw 1.0")
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
            # [수정] "전부 2줄"로 겹쳐 테스트하면 네 방향이 동시에 커져 체감상
            # 과하다는 피드백으로, 화면에서는 2줄 증가분을 절반으로 줄임(print는
            # 그대로 유지 - 이미 확인됨)
            if "|" in (plotdef.ylabel or ""): _lmargin_base += 0.05 if _is_print else 0.025  # Y1 title 2줄 이상이면 여백 추가
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
                if "|" in (plotdef.y2label or ""): _rmargin_base -= 0.05 if _is_print else 0.025  # Y2 title 2줄 이상이면 여백 추가(화면은 절반)

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
                        self._compute_manual_margins_in(plotdef, f_scale, _is_print, uses_y2, fmt=fmt)
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

        tic_size = int(9 * f_scale)
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

        title_size = int(float(plotdef.title_size) * f_scale)
        xlabel_size = int(float(plotdef.xlabel_size) * f_scale)
        ylabel_size = int(float(plotdef.ylabel_size) * f_scale)
        y2label_size = int(float(plotdef.y2label_size) * f_scale)

        title_text, title_enh = self._render_text(plotdef.title)
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
        lines.append(f'set xlabel "{xlabel_text}" font "{plotdef.xlabel_font},{xlabel_size}" offset 0,0.15 {xlabel_enh}')

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
        _term_font_pt_ref = max(int(round(11 * (panel_scale or 1.0))), 8)
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
            _ylabel_offset = 0.5
        elif _is_emf:
            _ylabel_offset = 8
        else:
            _ylabel_offset = 0.88 - 1.119 * (ylabel_size / _term_font_pt_ref)
        ylabel_text, ylabel_enh = self._render_text(plotdef.ylabel)
        lines.append(f'set ylabel "{ylabel_text}" font "{plotdef.ylabel_font},{ylabel_size}" offset {_ylabel_offset:.2f},0 {ylabel_enh}')

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
                # [수정] "y2는 반글자나 1글자 줄이고" 후속 피드백 - 2에서 1.5로
                # 한 번 더 축소.
                _y2label_offset = 1.5
            elif _is_emf:
                # [수정 - 버그] Y1과 같은 이유(위 y1 EMF 분기 주석 참고) - EMF는
                # 비율 공식을 적용하지 않고 기존 검증된 고정값(3) 유지.
                _y2label_offset = 3
            elif (fmt or "").lower() == "svg":
                # [수정] "SVG는 y2 title 1글자 폭을 줄일 것" - 공통 비율식보다
                # SVG만 1칸 더 타이트하게.
                _y2label_offset = (-0.881 + 1.299 * (y2label_size / _term_font_pt_ref)) - 1.0
            else:
                _y2label_offset = -0.881 + 1.299 * (y2label_size / _term_font_pt_ref)
            y2label_text, y2label_enh = self._render_text(plotdef.y2label)
            lines.append(f'set y2label "{y2label_text}" font "{plotdef.y2label_font},{y2label_size}" offset {_y2label_offset:.2f},0 {y2label_enh}')

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
                legend_thick_val, 8000, f_scale * legend_scale_boost, line_scale, panel_scale,
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
                legend2_thick_val, 9000, f_scale * legend_scale_boost, line_scale, panel_scale,
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
        return max(min(width_ratio, height_ratio), 0.3)  # 너무 작아지지 않게 하한

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
            need_top_in = 0.1 * f_scale

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
            need_top_in *= 1.15
            need_bottom_in *= 1.15
            # [참고] "Y1 title이 tic에 겹침" 문제는 왼쪽 마진(need_left_in) 크기와는
            # 무관했음(마진을 1.4배 늘려도 겹침이 그대로였음 - 직접 렌더링
            # 비교로 확인, 되돌림) - 실제 원인/해결은 ylabel의 offset 값
            # 자체였음(아래 _ylabel_offset 참고).

        return need_left_in, need_right_in, need_top_in, need_bottom_in

    def create_script(self, plotdef, outfile, fmt="pdf", annotations=None, arrows=None, circles=None):
        # [수정] "PNG/JPG를 PDF 기준으로" - gnuplot의 pngcairo/jpeg 터미널을
        # 각각 따로 부르는 대신, 이미 검증된 pdfcairo 결과를 PyMuPDF로
        # 래스터화해서 만든다(포맷 간 legend/폰트 크기 불일치의 근본 원인이던
        # "터미널마다 다른 텍스트 렌더러" 문제를 없앰 - 오늘 직접 확인).
        # EMF/SVG는 대상이 아니므로(EMF는 Word에서 벡터로 남아야 해서, SVG는
        # PDF→SVG 변환 수단이 이 환경에 없어서) 그대로 gnuplot이 직접 그린다.
        # PyMuPDF가 없는 환경이면 _rasterize_pdf_to_image가 False를 반환하니
        # 그때만 기존 gnuplot 자체 터미널 방식으로 대체(fallback)한다.
        _fmt_l0 = (fmt or "").lower()
        if _fmt_l0 in ("png", "jpg", "jpeg"):
            plot_dir0 = os.path.dirname(os.path.abspath(outfile))
            os.makedirs(plot_dir0, exist_ok=True)
            _tmp_pdf = os.path.join(plot_dir0, f".cathplot_raster_{uuid.uuid4().hex}.pdf")
            try:
                self.create_script(plotdef, _tmp_pdf, fmt="pdf", annotations=annotations, arrows=arrows, circles=circles)
                if _rasterize_pdf_to_image(_tmp_pdf, outfile, _fmt_l0):
                    return outfile
                # PyMuPDF 없음 등으로 래스터화 실패 - 기존 방식으로 계속 진행
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
        # [수정 - 실측 확인] gnuplot의 "windows"(대화형) 터미널은 3D xlabel/ylabel의
        # 임의 각도 "rotate by"를 지원하지 않고 그냥 무시(항상 가로로 표시)함 -
        # 실제 라이브 창을 스크린샷으로 직접 캡처해 확인함. zlabel의 90도만
        # 됐던 건 90이 예외적으로 지원되는 값이었을 뿐. pdf/png(pdfcairo)는
        # 임의 각도가 정상 동작함(별도 렌더링 테스트로 확인). 그래서 interactive는
        # 0/90/-90 중 가장 가까운 값으로 스냅해서 최소한 가로/세로는 맞춘다.
        if is_interactive:
            def _snap90(a):
                return min((0, 90, -90), key=lambda c: abs(a - c))
            _xlabel_rot = _snap90(_xlabel_rot)
            _ylabel_rot = _snap90(_ylabel_rot)
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
        def _side_bin(a):
            pos = a - 360.0 * math.floor(a / 360.0)  # 0~360으로 접기(정수 아닌 값도 처리)
            return int(math.floor(pos / 90.0)) % 2
        _y_anchor_x = 0.0 if (_side_bin(rot_x) ^ _side_bin(rot_z)) else 1.0
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
        # 설명은 create_script 쪽 주석 참고). EMF/SVG는 대상 아님.
        _fmt_l0 = (fmt or "").lower()
        if _fmt_l0 in ("png", "jpg", "jpeg"):
            plot_dir0 = os.path.dirname(os.path.abspath(outfile))
            os.makedirs(plot_dir0, exist_ok=True)
            _tmp_pdf = os.path.join(plot_dir0, f".cathplot_raster_{uuid.uuid4().hex}.pdf")
            try:
                self.create_multiplot_script(
                    plots, _tmp_pdf, fmt="pdf", layout_option=layout_option, orientation=orientation,
                    margins=margins, spacing=spacing, keep_script=keep_script, frame_auto=frame_auto,
                    frame_width=frame_width, frame_height=frame_height, frame_unit=frame_unit, for_print=for_print,
                )
                if _rasterize_pdf_to_image(_tmp_pdf, outfile, _fmt_l0):
                    return outfile
            finally:
                try:
                    os.remove(_tmp_pdf)
                except OSError:
                    pass

        self.last_size_warning = None  # 이전 호출에서 남은 경고가 있으면 초기화

        # [추가] Print(물리적 프린터 인쇄)는 큰 여백(좌2/우1/상3/하2cm)이 필요하지만,
        # Save(파일 저장)는 그런 물리적 제약이 없으므로 작은 여백만 사용한다.
        # [수정] Auto(칸 크기를 페이지에 맞춰 알아서 채우는 모드)는 인쇄용 물리
        # 여백을 강제로 크게 두지 않고, 최소 여백만 두고 자동으로 채운다("여백을
        # 강제하지 말고 자동에 맡기는" 사용자 요청) - Print/Save든 동일하게 최소
        # 여백만 사용
        if frame_auto:
            # [수정] Auto는 절대 여백을 전혀 적용하지 않는다("Auto size에는 적용하지
            # 말 것") - 페이지를 실제로 다 채우는 건 어차피 plot 자체 여백
            # (margin_left 등, title/tic 라벨 자리)뿐이므로, 여기서 별도로 더할
            # 필요가 없음
            pm_left = pm_right = pm_top = pm_bottom = 0.0
        elif for_print:
            pm_left, pm_right = self.PAGE_MARGIN_LEFT_IN, self.PAGE_MARGIN_RIGHT_IN
            pm_top, pm_bottom = self.PAGE_MARGIN_TOP_IN, self.PAGE_MARGIN_BOTTOM_IN
        else:
            pm_left = pm_right = pm_top = pm_bottom = self.SAVE_PAGE_MARGIN_IN
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)
        nplot = len(plots)

        if layout_option == "Auto":
            if nplot <= 1: rows, cols = 1, 1
            elif nplot == 2: rows, cols = (1, 2) if orientation == "landscape" else (2, 1)
            elif nplot <= 4: rows, cols = 2, 2
            else: rows, cols = 3, 2
        elif layout_option in ["1/p", "1"]: rows, cols = 1, 1
        elif "2/p" in layout_option: rows, cols = (1, 2) if orientation == "landscape" else (2, 1)
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
        # [수정 - 버그] "1/p(단일 plot) + Manual"인데도 전체 캔버스(페이지) 크기가
        # 항상 A4로 고정돼 있어서, 지정한 frame_width/height(예: 10x8cm)는 그
        # A4 페이지 안의 축(칸) 크기로만 쓰이고 실제 출력 파일 전체 크기는
        # Auto와 똑같이 A4로 나오는 문제가 있었음("1/p Manual이 Auto와 크기가
        # 같다" 실측 확인) - 단일 plot(rows=cols=1) + Manual일 때는 단일 plot
        # create_script와 동일한 개념("Frame 크기 = 축 크기, 페이지 = 축+여백")
        # 으로, 페이지 크기 자체를 frame_width/height + 여백으로 다시 잡는다.
        if rows == 1 and cols == 1 and not frame_auto and frame_width and frame_height:
            try:
                _fw_in = float(frame_width)
                _fh_in = float(frame_height)
                if (frame_unit or "in") == "cm":
                    _fw_in /= 2.54
                    _fh_in /= 2.54
                page_w = _fw_in + pm_left + pm_right
                page_h = _fh_in + pm_top + pm_bottom
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
        _auto_fill_w = 0.95 if total_cells >= 4 else 1.0
        _auto_fill_h = 0.90 if total_cells >= 4 else 1.0
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
        # [수정 - 캡 철회] "x:y 비율은 유지하되, Auto는 용지 최대치까지 확대해서
        # 쓰자" - 1.0 상한을 두면 칸이 커져도 폰트/마진이 기준(10x8) 크기에
        # 고정돼 축만 커지고 글자/legend는 비율에 안 맞게 작아 보임. 대신 비율
        # 유지(contain-fit, 아래 total_cells<=2 블록)로 칸 자체를 기준 비율에
        # 맞추고 나면, 그 커진 칸에 맞춰 폰트/마진도 함께(선형) 커지게 둔다.
        size_scale = max(min(cell_w_in / _ref_w, cell_h_in / _ref_h), 0.3)
        font_panel_scale = size_scale
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
            if total_cells >= 4:
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
            spacing_h_in = spacing_in * 3.0
            spacing_w_in = 2 * _title_char_w_in
            # [수정] "2/p 상하 간격을 title 대문자 1자 높이만큼 줄이고, 이를
            # bottom 마진에 넣어달라" - margin_top은 그대로 두고 margin_bottom
            # 에만 더한다(뒤에서 margin_bottom 계산 후 반영, 여기선 줄일 양/
            # 더할 양만 기록). margin_top/bottom을 "똑같이" 늘리면 간격이
            # 상쇄돼버렸던 이전 버그와 달리, bottom에만 넣으면 위쪽 칸-아래쪽
            # 칸 사이 간격은 실제로 줄고 아래쪽 바깥 여백(마지막 행의 bottom)만
            # 커진다.
            if total_cells == 2:
                spacing_h_in = max(spacing_h_in - _title_char_h_in, 0.0)
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
        if _any_y1_2line: extra_left_margin_in += 0.20  # Y1 title 2줄 이상
        if any_y2:
            if _y2fmt_label == "Scientific": extra_right_margin_in += 0.35
            elif _y2fmt_label == "Power10": extra_right_margin_in += 0.15
            if _any_y2_2line: extra_right_margin_in += 0.20  # Y2 title 2줄 이상
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
        _floor_scale = margin_scale if total_cells >= 4 else (
            font_panel_scale if font_panel_scale <= 1.0 else font_panel_scale ** 0.5
        )
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
        if any((p.ylabel or "").strip() for p in plots):
            _max_ylabel_size = max((float(p.ylabel_size or 11) for p in plots if (p.ylabel or "").strip()), default=11.0)
            _need_left_in = 0.5 * _floor_scale * (_max_ylabel_size / 11.0) + (0.2 if _any_y1_2line else 0) + _min_left_tic_in
            margin_left = max(margin_left, _need_left_in)
        if any_y2 and any_y2label:
            _max_y2label_size = max((float(p.y2label_size or 11) for p in plots if (getattr(p, "y2label", "") or "").strip()), default=11.0)
            _need_right_in = 0.5 * _floor_scale * (_max_y2label_size / 11.0) + (0.2 if _any_y2_2line else 0) + _min_right_tic_in
            margin_right = max(margin_right, _need_right_in)

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
        if not frame_auto:
            grid_w = cell_w_in * cols + spacing_in * (cols - 1)
            grid_h = cell_h_in * rows + spacing_in * (rows - 1)
            shrink = 1.0
            if grid_w > 0:
                shrink = min(shrink, max(printable_w / grid_w, 0.1))
            if grid_h > 0:
                shrink = min(shrink, max(printable_h / grid_h, 0.1))
            if shrink < 0.999:
                _margin_desc = "여백(좌2/우1/상3/하2cm)" if for_print else "여백(사방 0.3cm)"
                self.last_size_warning = (
                    f"요청한 Frame 크기({cell_w_in * 2.54:.2f}x{cell_h_in * 2.54:.2f}cm)로는 "
                    f"용지({orientation})에 {_margin_desc}을 두고 들어가지 않아, "
                    f"플롯 크기를 약 {shrink*100:.0f}%로 줄여서 출력했습니다."
                )
                cell_w_in *= shrink
                cell_h_in *= shrink
                axis_w *= shrink
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
            if total_cells >= 4:
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
        if frame_auto and total_cells <= 2:
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

        grid_w = cell_w_in * cols + spacing_w_in * (cols - 1)
        grid_h = cell_h_in * rows + spacing_h_in * (rows - 1)
        origin_left = pad_left + max(0, (printable_w - grid_w) / 2)
        origin_top = (page_h - pad_top) - max(0, (printable_h - grid_h) / 2)
        cell_positions_in = []
        for i in range(total_cells):
            row_idx, col_idx = i // cols, i % cols
            cell_left_in = origin_left + col_idx * (cell_w_in + spacing_w_in)
            cell_top_in = origin_top - row_idx * (cell_h_in + spacing_h_in)
            cell_positions_in.append((cell_left_in, cell_left_in + cell_w_in, cell_top_in, cell_top_in - cell_h_in))

        size_override = f"{page_w:.3f}in,{page_h:.3f}in"
        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile, None, size_override, panel_scale=font_panel_scale),
            f"set output '{outfile.replace(chr(92), '/')}'"
        ]
        lines.append(f"set multiplot layout {rows},{cols}")

        for i, plotdef in enumerate(plots):
            cell_left_in, cell_right_in, cell_top_in, cell_bottom_in = cell_positions_in[i]
            axis_left_in = cell_left_in + margin_left
            axis_right_in = cell_right_in - margin_right
            axis_top_in = cell_top_in - margin_top
            axis_bottom_in = cell_bottom_in + margin_bottom

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
            _legend_boost = 1.3 if total_cells >= 4 else 1.0
            # [수정] "2/p는 legend box 좌우길이를 1자 정도 키우고, 4/p, 6/p는
            # 2자 줄이고" - print 기준 여유분(0.7자)에서 레이아웃별로 가감한다.
            _legend_w_extra = (0.7 + 1.0) if total_cells <= 2 else (0.7 - 2.0)
            self._build_plot_commands(
                plotdef, lines, is_multiplot=True, panel_scale=font_panel_scale,
                annotations=getattr(plotdef, "annotations", None),
                arrows=getattr(plotdef, "arrows", None),
                circles=getattr(plotdef, "circles", None),
                axis_w_in=axis_right_in - axis_left_in,
                axis_h_in=axis_top_in - axis_bottom_in,
                legend_scale_boost=_legend_boost,
                legend_width_extra_chars=_legend_w_extra,
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

        return outfile
