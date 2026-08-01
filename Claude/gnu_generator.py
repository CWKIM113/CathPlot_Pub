# -*- coding: utf-8 -*-

from data_parser import CathenaDatParser  # 파서 모듈 임포트
from dataclasses import dataclass, field
import math
import os
import re
import shutil
import subprocess
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
    "dash": "8,4",
    "dot": "2,3",
    "dashdot": "10,3,2,3",
    "shortdash": "4,2",
    "dashdotdot": "10,3,2,3,2,3",
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
PRINT_FONT_SCALE = 1.60
PRINT_LINE_SCALE = 1.70
PRINT_BORDER_SCALE = 1.50
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

class GnuplotGenerator:

    def __init__(self, plot_dir=None):
        self.plot_dir = plot_dir
        self.use_default_colors = True
        self.use_default_styles = True
        self.custom_export_path = None
        self.last_process = None

    @staticmethod
    def _format_number(value):
        return format(value, ".12g")

    def _nice_axis_range(self, plotdef, axis):
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
            
            # 현재 함수가 계산 중인 대상 축(axis: 'x', 'y1', 'y2')과 곡선의 축이 다르면 건너뜁니다.
            if curve_axis != axis:
                continue
                
            column = curve.output_no
            x_col_idx = curve.x_output_no if getattr(curve, "x_output_no", None) is not None else default_x_col

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

        axis_min = data_min - span * 0.05
        axis_max = data_max + span * 0.05
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

    def _build_plot_commands(self, plotdef, lines, is_multiplot=False, annotations=None, arrows=None, panel_scale=1.0):

        if getattr(plotdef, "is_print_mode", False):
            f_scale = PRINT_FONT_SCALE * panel_scale
            line_scale = PRINT_LINE_SCALE * panel_scale
            border_scale = PRINT_BORDER_SCALE * panel_scale
        else:
            f_scale = SCREEN_FONT_SCALE * panel_scale
            line_scale = SCREEN_LINE_SCALE * panel_scale
            border_scale = SCREEN_BORDER_SCALE * panel_scale

        if plotdef.xauto:
            nice_x = self._nice_axis_range(plotdef, "x")
            if nice_x:
                xmin, xmax, _ = nice_x
                lines.append(f"set xrange [{self._format_number(xmin)}:{self._format_number(xmax)}]")
            else:
                lines.append("set autoscale x")
        else:
            lines.append(f"set xrange [{(plotdef.xmin or '').strip()}:{(plotdef.xmax or '').strip()}]")

        y1_auto_tics = ""
        if plotdef.yauto:
            nice_y1 = self._nice_axis_range(plotdef, "y1")
            if nice_y1:
                ymin, ymax, y1_auto_tics = nice_y1
                lines.append(f"set yrange [{self._format_number(ymin)}:{self._format_number(ymax)}]")
            else:
                lines.append("set autoscale y")
        else:
            lines.append(f"set yrange [{(plotdef.ymin or '').strip()}:{(plotdef.ymax or '').strip()}]")

        uses_y2 = any(getattr(curve, "axis", "y1") == "y2" for curve in plotdef.curves)
        if uses_y2:
            lines.append("unset link y2")

        y2_auto_tics = ""
        if uses_y2 and not getattr(plotdef, "y2auto", True):
            lines.append(f"set y2range [{plotdef.y2min}:{plotdef.y2max}]")
        elif uses_y2:
            nice_y2 = self._nice_axis_range(plotdef, "y2")
            if nice_y2:
                y2min, y2max, y2_auto_tics = nice_y2
                lines.append(f"set y2range [{self._format_number(y2min)}:{self._format_number(y2max)}]")
            else:
                lines.append("set autoscale y2")
        else:
            lines.append("set link y2")

        lines.append(f"set xtics {plotdef.xtics if plotdef.xtics else 'auto'}")
        lines.append(f"set ytics {plotdef.ytics if plotdef.ytics else self._format_number(y1_auto_tics) if y1_auto_tics else 'auto'}")
        if uses_y2:
            lines.append(f"set y2tics {plotdef.y2tics if plotdef.y2tics else self._format_number(y2_auto_tics) if y2_auto_tics else 'auto'}")
        else:
            # Y2 미사용 시 range는 'set link y2'로 이미 Y1과 연동되지만,
            # tic 간격(step)은 따로 지정 안 하면 gnuplot이 Y2용으로 별도 계산해서
            # Y1과 다른 간격(예: 2배)이 나올 수 있으므로 Y1과 동일한 간격을 명시적으로 지정
            y1_tic_value = plotdef.ytics if plotdef.ytics else (self._format_number(y1_auto_tics) if y1_auto_tics else None)
            if y1_tic_value:
                lines.append(f"set y2tics {y1_tic_value}")
            else:
                lines.append("set y2tics")
            lines.append('set format y2 ""')

        effective_minor_grid = plotdef.minor_grid and getattr(plotdef, "major_grid", True)

        if plotdef.mxtics: lines.append(f"set mxtics {int(plotdef.mxtics)+1}")
        elif effective_minor_grid: lines.append("set mxtics 2")
        else: lines.append("unset mxtics")

        if plotdef.mytics: lines.append(f"set mytics {int(plotdef.mytics)+1}")
        elif effective_minor_grid: lines.append("set mytics 2")
        else: lines.append("unset mytics")

        if uses_y2:
            if plotdef.my2tics: lines.append(f"set my2tics {int(plotdef.my2tics)+1}")
            elif effective_minor_grid: lines.append("set my2tics 2")
            else: lines.append("unset my2tics")
        else:
            # Y2 미사용 시 보조눈금(minor tic) 개수도 Y1(mytics)과 동일하게 맞춰서
            # Y1만 있을 때와 같은 모양이 되도록 함 (my2tics를 별도로 계산하지 않음)
            if plotdef.mytics: lines.append(f"set my2tics {int(plotdef.mytics)+1}")
            elif effective_minor_grid: lines.append("set my2tics 2")
            else: lines.append("unset my2tics")

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
            lines.append("set lmargin at screen 0.15")
            lines.append("set tmargin at screen 0.88")
            lines.append("set bmargin at screen 0.12")
            if uses_y2:
                # Y2 라벨이 들어갈 공간을 기본으로 확보 (범례가 우측에 있으면 아래 legend 블록에서 다시 조정됨)
                lines.append("set rmargin at screen 0.85")
            else:
                lines.append("set rmargin at screen 0.90")

        def _pct_to_frac(value, default=0.5):
            try: return float(value) / 100.0
            except (TypeError, ValueError): return default

        if annotations:
            for i, ann in enumerate(annotations):
                ann_text, ann_enh = self._render_text(ann["text"])
                gx = _pct_to_frac(ann["x"])
                gy = _pct_to_frac(ann["y"])
                try: angle_val = float(ann.get("angle", "0") or 0)
                except (TypeError, ValueError): angle_val = 0
                rotate_clause = f"rotate by {angle_val}" if angle_val else "norotate"
                lines.append(f'set label {i+1} "{ann_text}" at graph {gx},graph {gy} {rotate_clause} {ann_enh}')

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

        if plotdef.legend_on:
            box = f"box linewidth {1.5 * border_scale}" if plotdef.legend_box else "nobox"
            opaque = "opaque" if plotdef.legend_box else ""

            legend_pos_raw = (plotdef.legend_pos or "").strip()
            is_raw_coord = legend_pos_raw.startswith("graph ") or legend_pos_raw.startswith("screen ") or legend_pos_raw.startswith("at ")
            # 'X,Y' 형태(순수 숫자 두 개, 쉼표 구분)인지 확인 - annotation/arrow와
            # 동일하게 0~100(%) 좌표로 입력받기 위함
            is_pct_coord = False
            if not is_raw_coord and "," in legend_pos_raw:
                parts = [p.strip() for p in legend_pos_raw.split(",")]
                if len(parts) == 2:
                    try:
                        float(parts[0]); float(parts[1])
                        is_pct_coord = True
                    except ValueError:
                        is_pct_coord = False

            # legend box의 X좌표(0~1 비율)를 추정해서, 50%보다 왼쪽이면 기본 순서
            # (샘플선 먼저, 텍스트가 오른쪽/안쪽으로 자람), 오른쪽이면 순서를
            # 반전(reverse, 텍스트 먼저, 샘플선이 왼쪽/안쪽으로 자람)해서 legend box가
            # 어느 쪽에 있든 항상 plot 중심 방향으로 텍스트/샘플선이 자라도록 함
            x_frac = 0.5
            if is_pct_coord:
                try:
                    x_frac = float(legend_pos_raw.split(",")[0].strip()) / 100.0
                except ValueError:
                    x_frac = 0.5
            elif is_raw_coord:
                nums = re.findall(r"[-+]?\d*\.?\d+", legend_pos_raw)
                if nums:
                    try:
                        x_frac = float(nums[0])
                    except ValueError:
                        x_frac = 0.5
            elif plotdef.legend_pos == "outside right":
                x_frac = 1.0
            elif "right" in plotdef.legend_pos:
                x_frac = 1.0
            elif "left" in plotdef.legend_pos:
                x_frac = 0.0
            reverse_kw = "reverse" if x_frac > 0.5 else "noreverse"

            if is_raw_coord:
                # 고급 입력: 'graph 0.7,0.9' / 'screen ...' 같은 gnuplot 원본 비율(0~1)을 그대로 사용
                pos = legend_pos_raw if legend_pos_raw.startswith("at ") else f"at {legend_pos_raw}"
            elif is_pct_coord:
                # 기본 입력: annotation/arrow와 동일하게 0~100(%) 좌표로 입력받아 graph 비율로 변환
                px, py = legend_pos_raw.split(",")
                gx = _pct_to_frac(px)
                gy = _pct_to_frac(py)
                pos = f"at graph {gx},{gy}"
            elif plotdef.legend_pos == "outside right":
                if not is_multiplot: lines.append(f"set rmargin at screen {0.75 if uses_y2 else 0.78}")
                pos = "outside right center"
            else:
                if plotdef.legend_box and plotdef.legend_pos.startswith("right") and not is_multiplot:
                    lines.append(f"set rmargin at screen {0.85 if uses_y2 else 0.88}")
                # 범례 상자와 축 테두리(border) 사이 간격 - 기존 대비 약 0.6배로 축소
                dx = -0.6 if "right" in plotdef.legend_pos else (0.6 if "left" in plotdef.legend_pos else 0)
                dy = -0.6 if "top" in plotdef.legend_pos else (0.6 if "bottom" in plotdef.legend_pos else 0)
                pos = f"inside {plotdef.legend_pos} offset {dx},{dy}"

            lines.append(f'set key enhanced {pos} {reverse_kw} {box} {opaque} font "{plotdef.xlabel_font},{int(9*f_scale)}" samplen 3.5 spacing 1.2')
        else:
            lines.append("unset key")

        lines.append("plot \\")
        cmd_list = []

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

            curve_title_text, curve_title_enh = self._render_text(curve.title)
            cmd = f'"{path}" using {using_expr} title "{curve_title_text}" {curve_title_enh} axes {axis} with lines lw {lw}'

            if color: cmd += f' lc rgb "{color}"'
            if linestyle in DASH_PATTERNS: cmd += f" dashtype ({DASH_PATTERNS[linestyle]})"
            cmd_list.append(cmd)

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
            return f"set terminal windows title '{title}' font 'Malgun Gothic,11' {size_clause_px('size 840,672')}"
        elif fmt == "png":
            return f"set terminal pngcairo {size_clause('size 1600,900')} enhanced font 'Malgun Gothic,11'"
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

    def create_script(self, plotdef, outfile, fmt="pdf", annotations=None, arrows=None):
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)

        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile, plotdef),
        ]

        if fmt.lower() != "interactive":
            lines.append(f"set output '{outfile.replace(chr(92), '/')}'")

        self._build_plot_commands(plotdef, lines, is_multiplot=False, annotations=annotations, arrows=arrows)

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
            self.last_process = subprocess.Popen([gnuplot_exe, "-persist", script_path], cwd=plot_dir)
        else:
            # [수정] Batch/Save/Print는 결과 파일(pdf/png/emf 등)만 필요하고 스크립트
            # 자체는 안 남겨도 되는 임시 산출물이므로, 디스크에 .plt 파일을 쓰지 않고
            # gnuplot의 표준입력(stdin)으로 스크립트를 바로 넘겨서 디스크 I/O와
            # 매번 임시파일을 만들고 지우는 오버헤드를 줄인다.
            result = subprocess.run(
                [gnuplot_exe],
                input=script_text, text=True, encoding="utf-8", errors="replace",
                capture_output=True, cwd=plot_dir
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

    def create_multiplot_script(self, plots, outfile, fmt="pdf", layout_option="Auto", orientation="portrait", margins=None, spacing=None, keep_script=False, frame_auto=True, frame_width="", frame_height="", frame_unit="in"):
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
        # [수정] Multi-Print는 캔버스가 이미 A4에 가까운 큰 크기라, 실제 인쇄 시
        # (원본 비율을 유지해 페이지에 맞추는 과정에서) 거의 확대가 안 되는 반면,
        # 단일 PRINT는 작은 캔버스를 인쇄용 페이지 크기로 크게 확대해서 찍기 때문에
        # 같은 폰트 크기라도 Multi-Print 쪽이 상대적으로 작게 보임 - 폰트에만 보정
        # 배율을 적용 (margin 계산에 쓰이는 panel_scale 자체는 그대로 둬야 레이아웃이
        # 안 깨짐)
        MULTIPLOT_FONT_BOOST = 1.7
        font_panel_scale = panel_scale * (MULTIPLOT_FONT_BOOST if total_cells == 1 else 1.0)

        margin_left = MARGIN_LEFT_IN * panel_scale
        margin_right = (MARGIN_RIGHT_IN + (MARGIN_RIGHT_LEGEND_IN if any_legend_outside else 0) + (MARGIN_RIGHT_Y2_IN if any_y2 else 0)) * panel_scale
        title_margin_base = MARGIN_TOP_IN if any_title else MARGIN_TOP_NO_TITLE_IN
        margin_top = (title_margin_base + MARGIN_TOP_PER_EXTRA_LINE_IN * (max_title_lines - 1)) * panel_scale
        margin_bottom = MARGIN_BOTTOM_IN * panel_scale
        spacing_in = CELL_SPACING_IN * panel_scale

        if frame_auto:
            aw, ah = self._A4_SIZES.get(orientation, self._A4_SIZES["portrait"])
            page_w, page_h = float(aw.replace("in", "")), float(ah.replace("in", ""))
            cell_w_in = (page_w - spacing_in * (cols - 1)) / cols
            cell_h_in = (page_h - spacing_in * (rows - 1)) / rows
            axis_w = max(cell_w_in - margin_left - margin_right, 0.5)
            axis_h = max(cell_h_in - margin_top - margin_bottom, 0.5)
            cell_w_in = axis_w + margin_left + margin_right
            cell_h_in = axis_h + margin_top + margin_bottom

            cell_positions_in = []
            for i in range(total_cells):
                row_idx, col_idx = i // cols, i % cols
                cell_left_in = col_idx * (cell_w_in + spacing_in)
                cell_top_in = page_h - row_idx * (cell_h_in + spacing_in)
                cell_positions_in.append((cell_left_in, cell_left_in + cell_w_in, cell_top_in, cell_top_in - cell_h_in))
        else:
            axis_w_ref, axis_h_ref = (float(frame_width), float(frame_height)) if (frame_width and frame_height) else (5.0, 4.0)
            if frame_unit == "cm":
                axis_w_ref /= 2.54
                axis_h_ref /= 2.54
            axis_w, axis_h = axis_w_ref * panel_scale, axis_h_ref * panel_scale
            cell_w_in = axis_w + margin_left + margin_right
            cell_h_in = axis_h + margin_top + margin_bottom

            if total_cells == 1:
                aw, ah = self._A4_SIZES.get(orientation, self._A4_SIZES["portrait"])
                page_w, page_h = float(aw.replace("in", "")), float(ah.replace("in", ""))
                cell_left_in, cell_bottom_in = (page_w - cell_w_in) / 2, (page_h - cell_h_in) / 2
                cell_positions_in = [(cell_left_in, cell_left_in + cell_w_in, cell_bottom_in + cell_h_in, cell_bottom_in)]
            else:
                page_w = cell_w_in * cols + spacing_in * (cols - 1)
                page_h = cell_h_in * rows + spacing_in * (rows - 1)
                cell_positions_in = []
                for i in range(total_cells):
                    row_idx, col_idx = i // cols, i % cols
                    cell_left_in = col_idx * (cell_w_in + spacing_in)
                    cell_top_in = page_h - row_idx * (cell_h_in + spacing_in)
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
                encoding="utf-8", errors="replace", cwd=plot_dir
            )
            if result.returncode != 0:
                raise RuntimeError(f"gnuplot 실행 실패 (스크립트 보존됨: {script_path})\n{result.stderr.strip()}")
        else:
            # Batch/Print(임시 산출물): 디스크에 스크립트 파일을 쓰지 않고 stdin으로 바로 전달
            result = subprocess.run(
                [gnuplot_exe],
                input=script_text, text=True, encoding="utf-8", errors="replace",
                capture_output=True, cwd=plot_dir
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
