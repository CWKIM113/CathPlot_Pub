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

DEFAULT_COLORS = ["black", "red", "blue", "green", "magenta", "cyan", "orange", "brown", "purple", "gray"]
DEFAULT_LINESTYLES = ["solid", "dash", "dot", "dashdot", "shortdash", "dashdotdot"]
DASH_PATTERNS = {
    "dash": "6,3",
    "dot": "1,2",
    "dashdot": "8,3,1,3",       # dash를 길게(6->8), dot과의 틈새도 넓힘(2->3)
    "shortdash": "3,2",
    "dashdotdot": "8,3,1,3,1,3",  # 위와 동일하게 확대
}

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
PRINT_FONT_SCALE = 1.00     # 화면과 동일 비율로 나오도록 통일 (기존 1.60 → print만 유독 크게 나오던 원인)
PRINT_LINE_SCALE = 1.00     # 기존 1.70
PRINT_BORDER_SCALE = 1.00   # 기존 1.50
PRINT_TIC_MAJOR_SCALE = 1.0
PRINT_TIC_MINOR_SCALE = 0.5

MARGIN_LEFT_IN = 0.9          
MARGIN_RIGHT_IN = 0.3         
MARGIN_RIGHT_LEGEND_IN = 1.8  
MARGIN_RIGHT_Y2_IN = 0.6      
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
    legend_thick: str = "1.5"  # legend box 테두리 두께
    legend_font: str = "Malgun Gothic"  # Legend 전용 폰트 (Comment도 같이 씀)
    legend_size: str = "9"  # Legend 전용 크기 (Comment도 같이 씀)

    legend2_on: bool = False
    legend2_box: bool = True
    legend2_pos: str = "right bottom"
    legend2_thick: str = "1.5"

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
                            axis_w_in=5.0, legend_size=None):
        """gnuplot 네이티브 key 대신, set object(박스)+set arrow(샘플선)+set label(텍스트)를
        직접 조합해서 legend box를 그린다. Legend1/Legend2 둘 다 이 함수로 통일해서
        그린다 (네이티브 key의 정렬/여백이 예측하기 어려워서, 완전히 직접 제어하는
        방식으로 변경). id_offset은 Legend1(8000대)/Legend2(9000대)가 서로
        set object/arrow/label 번호가 겹치지 않도록 구분하기 위함."""
        if not curves:
            return

        ROW_H = 0.048 * (PRINT_FONT_SCALE if is_print_mode else SCREEN_FONT_SCALE) * panel_scale
        ROW_MARGIN = 0.06 * ROW_H  # 박스 위/아래 내부 여백 (추가 축소)
        FRAME_MARGIN = 0.35 * ROW_H  # plot 테두리(frame)와 박스 사이 여백 (major tic의 절반이었던 걸, major tic보다 조금 크게 조정)

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
                return 1.0 - FRAME_MARGIN + 0.02, 0.5, "left top"
            h = "right" if "right" in pos_raw else ("left" if "left" in pos_raw else "center")
            v = "top" if "top" in pos_raw else ("bottom" if "bottom" in pos_raw else "center")
            # [추가] 화면(Interactive) 창은 1000x700(가로가 더 긴 비율)이라, 같은
            # 비율의 FRAME_MARGIN이라도 세로 방향 실제 픽셀 여백이 가로보다
            # 작게 보이는 문제가 있었음 - 세로 전용 마진에 창 비율(10:7≈1.43배)을
            # 보정해서 실제 픽셀 여백이 가로와 비슷하게 보이도록 함 (인쇄/저장은
            # 사용자가 지정하는 Frame 비율이 제각각이라 보정하지 않음)
            _frame_margin_v = FRAME_MARGIN * (1000.0 / 700.0) if not is_print_mode else FRAME_MARGIN
            ax = (1.0 - FRAME_MARGIN) if h == "right" else (FRAME_MARGIN if h == "left" else 0.5)
            ay = (1.0 - _frame_margin_v) if v == "top" else (_frame_margin_v if v == "bottom" else 0.5)
            corner = f"{h} {v}".strip() if not (h == "center" and v == "center") else "center"
            return ax, ay, corner

        ax, ay, corner = _resolve_anchor(pos_raw)
        # 좌표(%,graph) 입력일 때 corner가 "left bottom"으로 고정되어 있어도,
        # 실제 ax(0~1) 값으로 좌/우를 직접 판단해서 미러링 방향을 정한다
        is_right_side = ax >= 0.5

        SAMPLE_W = 1.3 * ROW_H  # style(샘플선) 크기 추가 축소(1.6->1.3)
        max_label_len = max((len(c.title or "") for c in curves), default=1)
        # [수정] 글자 폭 추정을 실제 물리 단위(인치)로 계산한 뒤 axis_w_in(축의
        # 실제 폭)으로 나눠 그래프 비율로 환산한다 - 기존엔 축 크기를 무시한 채
        # 고정 비율로 추정해서, 축이 큰 명시적 레이아웃에서 title이 실제보다
        # 넓은데도 좁게 계산되어 box를 벗어나는 문제가 있었다.
        font_pt = (legend_size if legend_size else 9) * f_scale
        # [수정] Print/Save에서 18자 제목 기준 살짝 선 밖으로 나온다는 피드백 -
        # 화면(Interactive)은 그대로 두고 Print/Save만 여유를 좀 더 준다
        char_width_in = (0.0055 if is_print_mode else 0.0049) * font_pt  # 문자 하나당 대략적인 폭(인치), 폰트 크기(pt)에 비례
        char_width_frac = char_width_in / max(axis_w_in, 0.5)
        box_w = SAMPLE_W + char_width_frac * max(max_label_len - 2, 1) + 0.015  # 13자 기준 box 내 마진 2자 정도 축소
        box_h = ROW_H * len(curves) + 2 * ROW_MARGIN

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
                sample_x2 = box_right - 0.015
                sample_x1 = sample_x2 - SAMPLE_W
                label_x = sample_x1 - 0.01
                label_just = "right"
            else:
                sample_x1 = box_left + 0.015
                sample_x2 = sample_x1 + SAMPLE_W
                label_x = sample_x2 + 0.01
                label_just = "left"

            idx = curve_index_map.get(id(curve), row_i)
            color = curve.color or DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]
            linestyle = curve.linestyle or DEFAULT_LINESTYLES[idx % len(DEFAULT_LINESTYLES)]
            lw2 = curve.linewidth * line_scale
            dt_clause = f" dashtype ({DASH_PATTERNS[linestyle]})" if linestyle in DASH_PATTERNS else ""
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
                # [수정] 기호 폰트의 수직 정렬 기준점이 일반 텍스트보다 낮아서
                # row_y 그대로 쓰면 살짝 아래로 찍혀 보이는 문제 - 위로 살짝 보정
                symbol_y = row_y  # 샘플선과 정확히 같은 높이 (ROW_H가 커지면서 이전 보정 오프셋이 과도해짐)
                lines.append(
                    f'set label {id_offset + 5000 + row_i + 1} "{MARKER_SYMBOL_MAP[marker_shape]}" '
                    f'at graph {sample_mid_x:.4f},{symbol_y:.4f} center front '
                    f'font "{font_name},{int(font_pt)}" textcolor rgb "{color}"'
                )
            lbl_text, lbl_enh = self._render_text(curve.title)
            lines.append(
                f'set label {id_offset + row_i + 1} "{lbl_text}" at graph {label_x:.4f},{row_y:.4f} '
                f'{label_just} front font "{font_name},{int(font_pt)}" {lbl_enh}'
            )

    def _build_plot_commands(self, plotdef, lines, is_multiplot=False, annotations=None, arrows=None, panel_scale=1.0, axis_w_in=None):

        if getattr(plotdef, "is_print_mode", False):
            f_scale = PRINT_FONT_SCALE * panel_scale
            line_scale = PRINT_LINE_SCALE * panel_scale
            border_scale = PRINT_BORDER_SCALE * panel_scale
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

        def _tic_fmt_clause(fmt_label):
            if fmt_label == "Scientific":
                return "%.1e"
            elif fmt_label == "Power10":
                return "10^{%L}"
            return None  # Normal - 별도 지정 안 함(기본 표시)

        _xfmt = _tic_fmt_clause(getattr(plotdef, "xfmt", "Normal"))
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
        _y1fmt = _tic_fmt_clause(getattr(plotdef, "y1fmt", "Normal"))
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
            _y2fmt = _tic_fmt_clause(getattr(plotdef, "y2fmt", "Normal"))
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
            _lmargin_base = 0.15 if _is_print else 0.12
            _y1fmt_label = getattr(plotdef, "y1fmt", "Normal")
            if _y1fmt_label == "Scientific": _lmargin_base += 0.07
            elif _y1fmt_label == "Power10": _lmargin_base += 0.03
            if "|" in (plotdef.ylabel or ""): _lmargin_base += 0.05  # Y1 title 2줄 이상이면 여백 추가
            lines.append(f"set lmargin at screen {_lmargin_base}")
            # [추가] Plot Title이 '|'로 2줄 이상이면 상단 여백을 추가로 확보
            # (Multi-Print는 이미 반영되어 있었는데 단일 plot은 빠져 있었음)
            _title_lines = 1 + (plotdef.title or "").count("|")
            _tmargin_ref = 0.88 if _is_print else 0.895  # 화면 여백을 조금 더 늘림(이전 증가분 대비 30% 추가)
            _tmargin_base = _tmargin_ref - 0.09 * (_title_lines - 1)
            lines.append(f"set tmargin at screen {_tmargin_base}")
            _bmargin_base = 0.12 if _is_print else 0.16  # X title 아래 마진 0.16으로 재조정
            _xfmt_label = getattr(plotdef, "xfmt", "Normal")
            if _xfmt_label == "Scientific": _bmargin_base += 0.03
            elif _xfmt_label == "Power10": _bmargin_base += 0.015
            if "|" in (plotdef.xlabel or ""): _bmargin_base += 0.09  # X title 2줄 이상이면 여백 추가(0.05->0.09, 아랫줄 잘림 방지)
            lines.append(f"set bmargin at screen {_bmargin_base}")
            if _is_print:
                _rmargin_base = 0.85 if uses_y2 else 0.90
            else:
                _rmargin_base = 0.88 if uses_y2 else 0.93
            _y2fmt_label = getattr(plotdef, "y2fmt", "Normal")
            if uses_y2:
                if _y2fmt_label == "Scientific": _rmargin_base -= 0.07
                elif _y2fmt_label == "Power10": _rmargin_base -= 0.03
                if "|" in (plotdef.y2label or ""): _rmargin_base -= 0.05  # Y2 title 2줄 이상이면 여백 추가
            lines.append(f"set rmargin at screen {_rmargin_base}")

        def _pct_to_frac(value, default=0.5):
            try: return float(value) / 100.0
            except (TypeError, ValueError): return default

        if annotations:
            _ann_font = getattr(plotdef, "legend_font", None) or plotdef.xlabel_font
            _ann_size = int(float(getattr(plotdef, "legend_size", "9") or 9) * f_scale)
            for i, ann in enumerate(annotations):
                ann_text, ann_enh = self._render_text(ann["text"])
                gx = _pct_to_frac(ann["x"])
                gy = _pct_to_frac(ann["y"])
                try: angle_val = float(ann.get("angle", "0") or 0)
                except (TypeError, ValueError): angle_val = 0
                rotate_clause = f"rotate by {angle_val}" if angle_val else "norotate"
                lines.append(f'set label {i+1} "{ann_text}" at graph {gx},graph {gy} {rotate_clause} font "{_ann_font},{_ann_size}" {ann_enh}')

        if arrows:
            head_map = {"No head": "nohead", "Forward": "head", "Backhead": "backhead", "Both heads": "heads"}
            for i, arr in enumerate(arrows):
                head = head_map.get(arr.get("head", "Forward"), "head")
                gx1 = _pct_to_frac(arr["x1"], 0.1)
                gy1 = _pct_to_frac(arr["y1"], 0.1)
                gx2 = _pct_to_frac(arr["x2"], 0.5)
                gy2 = _pct_to_frac(arr["y2"], 0.5)
                lines.append(f'set arrow {i+1} from graph {gx1},graph {gy1} to graph {gx2},graph {gy2} {head}')

        tic_size = int(9 * f_scale)
        if getattr(plotdef, "is_print_mode", False):
            tic_major_scale, tic_minor_scale = PRINT_TIC_MAJOR_SCALE, PRINT_TIC_MINOR_SCALE
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

        effective_xlabel = plotdef.xlabel
        xlabel_text, xlabel_enh = self._render_text(effective_xlabel)
        lines.append(f'set xlabel "{xlabel_text}" font "{plotdef.xlabel_font},{xlabel_size}" {xlabel_enh}')

        ylabel_text, ylabel_enh = self._render_text(plotdef.ylabel)
        lines.append(f'set ylabel "{ylabel_text}" font "{plotdef.ylabel_font},{ylabel_size}" {ylabel_enh}')

        if plotdef.y2label:
            y2label_text, y2label_enh = self._render_text(plotdef.y2label)
            lines.append(f'set y2label "{y2label_text}" font "{plotdef.y2label_font},{y2label_size}" {y2label_enh}')

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
            # [수정] 기존엔 "frame_width - 1.5in" 식으로 대충 뺐는데, 실제 단일
            # plot에서 쓰는 margin 비율(lmargin=0.15, rmargin=0.85~0.90)과 안
            # 맞아서 legend box 계산이 부정확했음 - 실제 margin 비율로 정확히
            # 계산한다. frame_auto인 경우 실제 interactive 터미널 기본 크기(5in)를
            # 기준으로 한다.
            try:
                if not getattr(plotdef, "frame_auto", True):
                    fw = float((plotdef.frame_width or "5").strip() or 5.0)
                    if (plotdef.frame_unit or "in") == "cm":
                        fw /= 2.54
                else:
                    fw = 1000.0 / 168  # interactive 기본 터미널 크기(1000px/168px_per_in)
            except ValueError:
                fw = 5.0
            _rmargin_frac = 0.85 if any(getattr(c, "axis", "y1") == "y2" for c in plotdef.curves) else 0.90
            axis_w_in = max(fw * (_rmargin_frac - 0.15), 1.0)

        # Legend box 테두리는 Frame(plot 외곽 border) 두께 이하여야 하므로,
        # 사용자가 더 크게 입력해도 Frame 두께로 제한한다
        _frame_border_lw = 1.5 * border_scale

        group1_curves = [c for c in plotdef.curves if getattr(c, "in_legend1", True)]
        if plotdef.legend_on and group1_curves:
            legend_thick_val = min(float(getattr(plotdef, "legend_thick", "1.5") or 1.5), _frame_border_lw)
            self._render_legend_box(
                lines, group1_curves, plotdef.legend_pos, plotdef.legend_box,
                legend_thick_val, 8000, f_scale, line_scale, panel_scale,
                getattr(plotdef, "is_print_mode", False), curve_index_map, getattr(plotdef, "legend_font", plotdef.xlabel_font),
                axis_w_in, legend_size=float(getattr(plotdef, "legend_size", "9") or 9)
            )

        group2_curves = [c for c in plotdef.curves if getattr(c, "legend_group", 1) == 2]
        if getattr(plotdef, "legend2_on", False) and group2_curves:
            legend2_thick_val = min(float(getattr(plotdef, "legend2_thick", "1.5") or 1.5), _frame_border_lw)
            self._render_legend_box(
                lines, group2_curves, plotdef.legend2_pos, getattr(plotdef, "legend2_box", True),
                legend2_thick_val, 9000, f_scale, line_scale, panel_scale,
                getattr(plotdef, "is_print_mode", False), curve_index_map, getattr(plotdef, "legend_font", plotdef.xlabel_font),
                axis_w_in, legend_size=float(getattr(plotdef, "legend_size", "9") or 9)
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
            if linestyle in DASH_PATTERNS: cmd += f" dashtype ({DASH_PATTERNS[linestyle]})"
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

    def _get_terminal_cmd(self, fmt, outfile, plotdef=None, size_override=None):
        fmt = fmt.lower()
        def size_clause(default):
            if size_override: return f"size {size_override}"
            if plotdef is not None and not getattr(plotdef, "frame_auto", True):
                w = (getattr(plotdef, "frame_width", "") or "").strip()
                h = (getattr(plotdef, "frame_height", "") or "").strip()
                unit = (getattr(plotdef, "frame_unit", "in") or "in").strip()
                if w and h: return f"size {w}{unit},{h}{unit}"
            return default

        def size_clause_px(default_px):
            # windows 터미널은 size에 in/cm 같은 단위를 못 받고 픽셀 숫자만 받으므로
            # (pdfcairo/svg 등 다른 터미널과 달리) 인치/cm 값을 환산해서 넘긴다.
            # 순수 96px/in로 하면 창이 너무 작게 나와서(예: 5in x 4in -> 480x384),
            # 화면에서 보기 좋은 크기가 되도록 1.75배(=168px/in) 키워서 적용.
            PX_PER_IN = 168
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
            return f"set terminal pngcairo {size_clause('size 11.7in,8.3in')} enhanced font 'Malgun Gothic,11'"
        elif fmt == "jpg":
            return f"set terminal jpeg {size_clause_px('size 1600,900')} enhanced font 'Malgun Gothic,11'"
        elif fmt == "svg":
            return f"set terminal svg enhanced {size_clause('size 11.7in,8.3in')} font 'Malgun Gothic,11'"
        elif fmt == "pdf":
            return f"set terminal pdfcairo enhanced color font 'Malgun Gothic,11' {size_clause('size 11.7in,8.3in')}"
        elif fmt == "eps":
            return f"set terminal postscript eps enhanced color font 'Malgun Gothic,11' {size_clause('')}"
        elif fmt == "emf":
            # emf 터미널은 windows 터미널과 마찬가지로 in/cm 단위를 못 받고 픽셀 숫자만 받음
            return f"set terminal emf enhanced {size_clause_px('size 840,672')} font 'Malgun Gothic,11'"
        else:
            raise ValueError(f"Unsupported output format : {fmt}")

    def _compute_size_scale(self, plotdef):
        """plot 내 폰트 크기가 Frame 크기에 비례해서 확대/축소되도록 스케일을
        계산한다 (기준 10cm 대비 비율). Frame Size Auto면 기준 그대로(1.0)."""
        REFERENCE_WIDTH_IN = 10.0 / 2.54  # 기준 10cm
        if getattr(plotdef, "frame_auto", True):
            return 1.0
        fw_str = (plotdef.frame_width or "").strip()
        if not fw_str:
            # frame_width가 비어있으면 기준(10cm)과 동일하게 취급 - 비율 1.0
            return 1.0
        try:
            fw = float(fw_str)
            if (getattr(plotdef, "frame_unit", "in") or "in") == "cm":
                fw /= 2.54
        except ValueError:
            fw = REFERENCE_WIDTH_IN
        return max(fw / REFERENCE_WIDTH_IN, 0.3)  # 너무 작아지지 않게 하한

    def create_script(self, plotdef, outfile, fmt="pdf", annotations=None, arrows=None):
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)

        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile, plotdef),
        ]

        if fmt.lower() != "interactive":
            lines.append(f"set output '{outfile.replace(chr(92), '/')}'")

        _size_scale = self._compute_size_scale(plotdef)
        self._build_plot_commands(plotdef, lines, is_multiplot=False, annotations=annotations, arrows=arrows, panel_scale=_size_scale)

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
        self.last_size_warning = None  # 이전 호출에서 남은 경고가 있으면 초기화

        # [추가] Print(물리적 프린터 인쇄)는 큰 여백(좌2/우1/상3/하2cm)이 필요하지만,
        # Save(파일 저장)는 그런 물리적 제약이 없으므로 작은 여백만 사용한다
        if for_print:
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
        any_title = any((p.title or "").strip() for p in plots)
        max_title_lines = max((1 + (p.title or "").count("|")) for p in plots) if plots else 1

        panel_scale = min(1.0 / cols, 1.0 / rows)

        # [핵심 재설계] "1/p, 2/p, 4/p, 6/p는 개별 plot 크기(폰트/여백 포함)가
        # 전부 동일해야 하고, 배치(및 페이지에 안 들어갈 때의 부득이한 축소)만
        # 다르다"는 요구사항 반영. Auto 레이아웃은 정반대로 "한 페이지에 맞춰
        # 알아서 채우는" 목적이므로 기존처럼 panel_scale로 계속 나눠서 줄인다.
        # → 즉 폰트/여백 스케일을 frame_auto 여부에 따라 다르게 가져간다:
        #   - Auto: panel_scale 기반(칸이 많을수록 작아짐, 하한선 있음)
        #   - 명시적 레이아웃: 항상 1.0 고정 (칸 수와 무관하게 동일한 폰트/여백)
        # [수정] Auto 레이아웃 폰트가 칸 수가 늘수록 너무 작아진다는 피드백
        # ("plot이 절반으로 줄면 폰트도 절반 정도여야 하는데 1/4 수준으로 줄어듦")
        # - 원인은 MULTIPLOT_FONT_BOOST를 total_cells==1에만 적용하고 그 외에는
        # 하한선(MIN_FONT_PANEL_SCALE)만 적용해서, 1칸일 때만 유독 커 보이고
        # 나머지는 상대적으로 훨씬 작아 보였던 것 - 이제 모든 칸 수에 동일한
        # 배율을 곱해서(panel_scale에 선형 비례) 1칸 대비 비율이 일관되게 함
        MULTIPLOT_FONT_BOOST = 2.6
        if not frame_auto:
            # [추가] "plot 크기에 비례해서 폰트/마커도 확대·축소" 원칙을 명시적
            # 레이아웃에도 적용 - 기존엔 1.0 고정이라 1/p=2/p 크기는 동일하게
            # 유지됐지만, 사용자가 지정한 실제 Frame 크기(기준 10cm 대비)에는
            # 비례하지 않고 있었음
            REFERENCE_WIDTH_IN = 10.0 / 2.54
            if frame_width:
                try:
                    _fw_for_scale = float(frame_width)
                    if (frame_unit or "in") == "cm":
                        _fw_for_scale /= 2.54
                except ValueError:
                    _fw_for_scale = REFERENCE_WIDTH_IN
            else:
                # frame_width가 비어있으면(axis_w_ref의 기본값과 동일하게) 기준(10cm)과
                # 같은 것으로 취급 - 비율 1.0
                _fw_for_scale = REFERENCE_WIDTH_IN
            font_panel_scale = max(_fw_for_scale / REFERENCE_WIDTH_IN, 0.3)
            margin_scale = 1.0
            layout_scale = 1.0  # margin/spacing에 쓸 스케일도 고정
        else:
            font_panel_scale = panel_scale * MULTIPLOT_FONT_BOOST
            # [추가] 여백이 폰트 부스트를 그대로 따라가면 칸이 많은 Auto
            # 레이아웃에서 여백이 축 크기 대비 과도하게 커 보이는 문제가 있었음
            # - 폰트는 선형으로 키우되(가독성), 여백은 그보다 완만하게(제곱근에
            # 가깝게) 커지도록 분리
            margin_scale = font_panel_scale ** 0.65
            layout_scale = panel_scale

        # [추가] Y축 tic 숫자 자릿수가 많을수록(예: 10000 이상) 여백이 부족해
        # 잘리거나(왼쪽) title과 겹치던(오른쪽 Y2) 문제 - 실제 플롯들의 Y1/Y2
        # 범위를 미리 계산해서 필요한 자릿수를 추정하고, 기본 가정(3자리)보다
        # 많으면 그만큼 각각(Y1=왼쪽, Y2=오른쪽) 여백을 더 확보한다
        max_y1_digits = 3
        max_y2_digits = 3
        for p in plots:
            for axis_name, digit_holder in (("y1", "y1"), ("y2", "y2")):
                try:
                    nice = self._nice_axis_range(p, axis_name)
                except Exception:
                    nice = None
                if nice:
                    y_lo, y_hi, _ = nice
                    peak = max(abs(y_lo), abs(y_hi))
                    digits = len(f"{peak:.0f}") if peak >= 1 else 1
                    if digit_holder == "y1":
                        max_y1_digits = max(max_y1_digits, digits)
                    else:
                        max_y2_digits = max(max_y2_digits, digits)
        extra_left_margin_in = max(0, max_y1_digits - 3) * 0.09  # 자릿수 하나당 약 0.09in 추가
        extra_right_margin_in = max(0, max_y2_digits - 3) * 0.09 if any_y2 else 0
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
        margin_right = (MARGIN_RIGHT_IN + (MARGIN_RIGHT_LEGEND_IN if any_legend_outside else 0) + (MARGIN_RIGHT_Y2_IN if any_y2 else 0)) * margin_scale + extra_right_margin_in
        title_margin_base = MARGIN_TOP_IN if any_title else MARGIN_TOP_NO_TITLE_IN
        margin_top = (title_margin_base + MARGIN_TOP_PER_EXTRA_LINE_IN * (max_title_lines - 1)) * margin_scale
        margin_bottom = MARGIN_BOTTOM_IN * margin_scale + extra_bottom_margin_in
        spacing_in = CELL_SPACING_IN * layout_scale

        if frame_auto:
            aw, ah = self._A4_SIZES.get(orientation, self._A4_SIZES["portrait"])
            page_w, page_h = float(aw.replace("in", "")), float(ah.replace("in", ""))
            # [재수정] "종이 여백 = 축(axis) 시작점까지의 거리"로 해석했다가, title/
            # tic 라벨처럼 축보다 바깥쪽에 있는 요소가 오히려 지정한 여백보다 더
            # 바깥으로(심하면 용지 밖으로) 밀려나는 문제가 있었음 - Word 등 일반적인
            # 문서 여백 개념과 동일하게, "종이 여백 = 가장 바깥쪽 보이는 요소(제목,
            # tic 숫자 등을 포함한 셀 전체)까지의 거리"로 되돌린다. 축 자체는 그
            # 안쪽에서 자연스럽게 시작된다(margin_left/top만큼 더 안쪽).
            printable_w = page_w - pm_left - pm_right
            printable_h = page_h - pm_top - pm_bottom
            cell_w_in = (printable_w - spacing_in * (cols - 1)) / cols
            cell_h_in = (printable_h - spacing_in * (rows - 1)) / rows
            axis_w = max(cell_w_in - margin_left - margin_right, 0.5)
            axis_h = max(cell_h_in - margin_top - margin_bottom, 0.5)
            cell_w_in = axis_w + margin_left + margin_right
            cell_h_in = axis_h + margin_top + margin_bottom

            grid_left = pm_left
            grid_top = page_h - pm_top
            cell_positions_in = []
            for i in range(total_cells):
                row_idx, col_idx = i // cols, i % cols
                cell_left_in = grid_left + col_idx * (cell_w_in + spacing_in)
                cell_top_in = grid_top - row_idx * (cell_h_in + spacing_in)
                cell_positions_in.append((cell_left_in, cell_left_in + cell_w_in, cell_top_in, cell_top_in - cell_h_in))
        else:
            axis_w_ref, axis_h_ref = (float(frame_width), float(frame_height)) if (frame_width and frame_height) else (10.0 / 2.54, 8.0 / 2.54)
            if frame_unit == "cm":
                axis_w_ref /= 2.54
                axis_h_ref /= 2.54
            # [핵심 수정] 전엔 여기서 axis_w_ref에 panel_scale을 곱해 칸이 많을수록
            # 개별 plot이 계속 작아졌음(1/p와 2/p 크기가 달라지는 원인) - 이제
            # 요청한 frame 크기를 칸 수와 무관하게 그대로 사용하고, 페이지에
            # 안 들어갈 때만 부득이하게 축소(+경고)한다
            axis_w, axis_h = axis_w_ref, axis_h_ref

            # [수정] 1/p, 2/p 등 명시적 레이아웃은 frame 크기를 기준으로 그리되,
            # 항상 표준 용지(orientation에 맞는 A4) 안에 고정 여백(좌2/우1/상3/하2cm)을
            # 두고 들어가야 한다. 여백이 부족하거나 아예 없어지면(요청한 크기가
            # 용지보다 크면) 경고를 남기고 종횡비를 유지한 채 자동으로 축소한다.
            aw, ah = self._A4_SIZES.get(orientation, self._A4_SIZES["portrait"])
            page_w, page_h = float(aw.replace("in", "")), float(ah.replace("in", ""))
            # [재수정] Auto 브랜치와 동일하게, 종이 여백은 셀(title/tic 라벨 포함
            # 가장 바깥 요소)까지의 거리로 되돌린다 - 축만 여백에 맞추면 title/tic
            # 라벨이 그보다 더 바깥으로 밀려나는 문제가 있었음
            printable_w = page_w - pm_left - pm_right
            printable_h = page_h - pm_top - pm_bottom

            cell_w_in = axis_w + margin_left + margin_right
            cell_h_in = axis_h + margin_top + margin_bottom

            # [수정] 축소가 필요할 때 axis_w/axis_h만 줄이고 spacing(칸 사이 간격)은
            # 그대로 둬서, 축소가 클수록 간격이 plot 크기 대비 상대적으로 훨씬
            # 커 보이는 문제가 있었음 - margin(제목/tic 라벨 자리, 폰트 크기와
            # 맞물려 있어 그대로 둬야 함)은 고정하고, axis와 spacing을 함께
            # 비례 축소하도록 재계산해서 간격 비율을 유지하고 plot 자체도 더 크게 나오게 함
            scale = 1.0
            if axis_w > 0:
                k_w = (printable_w - (margin_left + margin_right) * cols) / (axis_w * cols + spacing_in * (cols - 1))
                scale = min(scale, max(k_w, 0.1))
            if axis_h > 0:
                k_h = (printable_h - (margin_top + margin_bottom) * rows) / (axis_h * rows + spacing_in * (rows - 1))
                scale = min(scale, max(k_h, 0.1))

            if scale < 0.999:
                _margin_desc = "여백(좌2/우1/상3/하2cm)" if for_print else "여백(사방 0.3cm)"
                self.last_size_warning = (
                    f"요청한 Frame 크기({axis_w_ref:.2f}x{axis_h_ref:.2f}{frame_unit})로는 "
                    f"용지({orientation})에 {_margin_desc}을 두고 들어가지 않아, "
                    f"플롯 크기를 약 {scale*100:.0f}%로 줄여서 출력했습니다."
                )
                axis_w *= scale
                axis_h *= scale
                spacing_in *= scale
                # [수정] 축(axis)만 줄이고 폰트/margin은 그대로 두면, 좁아진 축
                # 안에 원래 크기의 글자·tic들이 그대로 들어가려다 서로 겹쳐서
                # "깨진" 것처럼 보이는 문제가 있었음 - 폰트도 축소 비율만큼
                # 같이 줄이고, margin(글자 크기에 맞물려 있음)도 다시 계산한다
                font_panel_scale *= scale
                extra_left_margin_in *= scale
                extra_right_margin_in *= scale
                extra_bottom_margin_in *= scale
                margin_left = MARGIN_LEFT_IN * font_panel_scale + extra_left_margin_in
                margin_right = (MARGIN_RIGHT_IN + (MARGIN_RIGHT_LEGEND_IN if any_legend_outside else 0) + (MARGIN_RIGHT_Y2_IN if any_y2 else 0)) * font_panel_scale + extra_right_margin_in
                margin_top = (title_margin_base + MARGIN_TOP_PER_EXTRA_LINE_IN * (max_title_lines - 1)) * font_panel_scale
                margin_bottom = MARGIN_BOTTOM_IN * font_panel_scale + extra_bottom_margin_in
                cell_w_in = axis_w + margin_left + margin_right
                cell_h_in = axis_h + margin_top + margin_bottom

            # [복원] 좌상단 고정 배치에서 다시 가운데 정렬로 되돌림 (사용자 요청)
            grid_w = cell_w_in * cols + spacing_in * (cols - 1)
            grid_h = cell_h_in * rows + spacing_in * (rows - 1)
            origin_left = pm_left + max(0, (printable_w - grid_w) / 2)
            origin_top = (page_h - pm_top) - max(0, (printable_h - grid_h) / 2)
            cell_positions_in = []
            for i in range(total_cells):
                row_idx, col_idx = i // cols, i % cols
                cell_left_in = origin_left + col_idx * (cell_w_in + spacing_in)
                cell_top_in = origin_top - row_idx * (cell_h_in + spacing_in)
                cell_positions_in.append((cell_left_in, cell_left_in + cell_w_in, cell_top_in, cell_top_in - cell_h_in))

        size_override = f"{page_w:.3f}in,{page_h:.3f}in"
        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile, None, size_override),
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

            lines.append(f"set lmargin at screen {axis_left_in / page_w:.4f}")
            lines.append(f"set rmargin at screen {axis_right_in / page_w:.4f}")
            lines.append(f"set tmargin at screen {axis_top_in / page_h:.4f}")
            lines.append(f"set bmargin at screen {axis_bottom_in / page_h:.4f}")

            self._build_plot_commands(
                plotdef, lines, is_multiplot=True, panel_scale=font_panel_scale,
                annotations=getattr(plotdef, "annotations", None),
                arrows=getattr(plotdef, "arrows", None),
                axis_w_in=axis_right_in - axis_left_in,
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

        return outfile
