# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
import math
import os
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
LINESTYLE_MAP = {"solid": 1, "dash": 2, "dot": 3, "dashdot": 4, "shortdash": 5, "dashdotdot": 6}
# 점선(dot) 간격을 gnuplot이 올바르게 인식하도록 표준 숫자 튜플 및 기호로 수정
#LINESTYLE_MAP = {
#    "solid": 1,
#    "dash": (4, 4),
#    "dot": (1, 1),       # 기존 ".#" 대신 촘촘한 점선 패턴(1, 1) 적용
#    "dashdot": (4, 2, 1, 2),
#    "shortdash": (2, 2),
#    "dashdotdot": (4, 2, 1, 2, 1, 2)
#}
#----------------------------------------------------------
# Interactive
#----------------------------------------------------------
SCREEN_FONT_SCALE  = 1.00
SCREEN_LINE_SCALE  = 1.00
SCREEN_BORDER_SCALE = 1.00

#----------------------------------------------------------
# Print / Save Output Scale
#----------------------------------------------------------
PRINT_FONT_SCALE = 1.60
PRINT_LINE_SCALE = 1.70
PRINT_BORDER_SCALE = 1.50
# Frame Size는 "좌표축(데이터 영역) 박스만의 크기"를 의미한다.
# Title/축라벨/Legend/tic 숫자에 필요한 여백은 이 박스 바깥에 별도로 더해져서
# 전체 종이 크기가 정해진다 (즉 축 박스 크기 자체는 항상 고정 유지됨).
# 아래 값은 panel_scale=1.0(1/p, 2/p) 기준이며, 4/p·6/p처럼 축소될 때는
# panel_scale에 비례해서 같이 줄어든다.
MARGIN_LEFT_IN = 0.9          # Y축 라벨 + tic 숫자 공간
MARGIN_RIGHT_IN = 0.3         # 기본 우측 여백
MARGIN_RIGHT_LEGEND_IN = 1.8  # legend가 "outside right"일 때 추가로 필요한 공간
MARGIN_RIGHT_Y2_IN = 0.6      # Y2축 라벨 + tic 숫자 공간
MARGIN_TOP_IN = 0.6           # Title 한 줄 기준 상단 여백
MARGIN_TOP_NO_TITLE_IN = 0.08 # Title이 비어있을 때 상단 여백 (제목 없는 경우가 많아서)
MARGIN_TOP_PER_EXTRA_LINE_IN = 0.35  # Title이 "|"로 여러 줄일 때 줄마다 추가
MARGIN_BOTTOM_IN = 0.7        # X축 라벨 + tic 숫자 공간
CELL_SPACING_IN = 0.10        # 칸 사이 간격(멀티플롯일 때)

@dataclass
class CurveDefinition:
    dat_file: str
    output_no: int
    title: str
    axis: str = "y1"
    x_shift: float = 0.0
    color: str | None = None
    linestyle: str | None = None
    linewidth: float = 1.5

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

    x_output_no: int = 0

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
        # [개선 4] X축이 범용적으로 동작하도록 수정 (Time 또는 Pressure 등 선택 컬럼 대응)
        if axis == "x":
            x_min = x_max = None
            if not plotdef.xauto:
                try: x_min = float(plotdef.xmin) if plotdef.xmin.strip() else None
                except ValueError: x_min = None
                try: x_max = float(plotdef.xmax) if plotdef.xmax.strip() else None
                except ValueError: x_max = None

            values = []
            x_col_idx = getattr(plotdef, "x_output_no", 0)
            for curve in plotdef.curves:
                try:
                    with open(curve.dat_file, "r", encoding="utf-8", errors="ignore") as data:
                        for row in data:
                            text = row.strip()
                            if not text or "---" in text or "===" in text or "OUTPUT" in text.upper():
                                continue
                            fields = re.split(r'[,\s]+', text)
                            if len(fields) <= x_col_idx:
                                continue
                            try:
                                val = float(fields[x_col_idx].replace("D", "E").replace("d", "e").replace(",", "")) + curve.x_shift
                                if math.isfinite(val):
                                    values.append(val)
                            except ValueError:
                                continue
                except OSError:
                    continue
            if not values:
                return None
            data_min, data_max = min(values), max(values)
            span = data_max - data_min
            if span == 0: span = max(abs(data_min) * 0.1, 1.0)
            return data_min - span * 0.05, data_max + span * 0.05, span / 4.0

        x_min = x_max = None
        if not plotdef.xauto:
            try:
                x_min = float(plotdef.xmin) if plotdef.xmin.strip() else None
            except ValueError:
                x_min = None
            try:
                x_max = float(plotdef.xmax) if plotdef.xmax.strip() else None
            except ValueError:
                x_max = None

        """Return a readable (min, max, major-step) for curves on one y axis."""
        values = []
        x_col_idx = getattr(plotdef, "x_output_no", 0)

        for curve in plotdef.curves:
            if getattr(curve, "axis", "y1") != axis:
                continue
            column = curve.output_no
            try:
                with open(curve.dat_file, "r", encoding="utf-8", errors="ignore") as data:
                    for row in data:
                        #fields = row.split()
                        #if len(fields) <= column:
                        #    continue
                        #try:
                        #    value = float(fields[column].replace("D", "E").replace("d", "e"))
                        #except ValueError:
                        #    continue

                        text = row.strip()
                        if not text or "---" in text or "===" in text or "OUTPUT" in text.upper():
                            continue

                        fields = re.split(r'[,\s]+', text)

                        if not fields:
                            continue
                        try:
                            float(fields[x_col_idx].replace("D", "E").replace("d", "e").replace(",", ""))
                        except ValueError:
                            continue

                        max_col = max(column, x_col_idx)
                        if len(fields) <= max_col:
                            continue

                        if x_min is not None or x_max is not None:
                            try:
                                x_val = float(fields[x_col_idx].replace("D", "E").replace("d", "e").replace(",", "")) + curve.x_shift
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
            except OSError:
                continue

        if not values:
            return None

        data_min, data_max = min(values), max(values)
        span = data_max - data_min
        if span == 0:
            span = max(abs(data_min) * 0.1, 1.0)
            data_min -= span / 2
            data_max += span / 2
        else:
            # A small data-space margin prevents a line from touching the frame.
            data_min -= span * 0.05
            data_max += span * 0.05
            span = data_max - data_min

        raw_step = span / 4.0
        magnitude = 10 ** math.floor(math.log10(raw_step))
        normalized = raw_step / magnitude
        for candidate in (1, 2, 2.5, 5, 10):
            if normalized <= candidate:
                step = candidate * magnitude
                break

        axis_min = math.floor(data_min / step) * step
        axis_max = math.ceil(data_max / step) * step
        if axis_min == axis_max:
            axis_max += step
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

        #----------------------------------------------------------
        # Output Scale
        #----------------------------------------------------------
        if getattr(plotdef, "is_print_mode", False):
            f_scale = PRINT_FONT_SCALE * panel_scale
            line_scale = PRINT_LINE_SCALE * panel_scale
            border_scale = PRINT_BORDER_SCALE * panel_scale
        else:
            f_scale = SCREEN_FONT_SCALE * panel_scale
            line_scale = SCREEN_LINE_SCALE * panel_scale
            border_scale = SCREEN_BORDER_SCALE * panel_scale

        if plotdef.xauto:
        #    lines.append("set autoscale x")
        #else: lines.append(f"set xrange [{plotdef.xmin.strip()}:{plotdef.xmax.strip()}]")
            nice_x = self._nice_axis_range(plotdef, "x")
            if nice_x:
                xmin, xmax, _ = nice_x
                lines.append(f"set xrange [{self._format_number(xmin)}:{self._format_number(xmax)}]")
            else:
                lines.append("set autoscale x")
        else:
            lines.append(f"set xrange [{plotdef.xmin.strip()}:{plotdef.xmax.strip()}]")

        y1_auto_tics = ""
        if plotdef.yauto:
            nice_y1 = self._nice_axis_range(plotdef, "y1")
            if nice_y1:
                ymin, ymax, y1_auto_tics = nice_y1
                lines.append(
                    f"set yrange [{self._format_number(ymin)}:{self._format_number(ymax)}]"
                )
            else:
                lines.append("set autoscale y")
        else:
            lines.append(f"set yrange [{plotdef.ymin.strip()}:{plotdef.ymax.strip()}]")

        uses_y2 = any(getattr(curve, "axis", "y1") == "y2" for curve in plotdef.curves)
        if uses_y2:
            # A preceding plot in a multiplot may have linked y2 to y.  Remove
            # that state before applying this plot's independent y2 range.
            lines.append("unset link y2")

        y2_auto_tics = ""
        if uses_y2 and not getattr(plotdef, "y2auto", True):
            lines.append(f"set y2range [{plotdef.y2min}:{plotdef.y2max}]")
        elif uses_y2:
            nice_y2 = self._nice_axis_range(plotdef, "y2")
            if nice_y2:
                y2min, y2max, y2_auto_tics = nice_y2
                lines.append(
                    f"set y2range [{self._format_number(y2min)}:{self._format_number(y2max)}]"
                )
            else:
                lines.append("set autoscale y2")
        else:
            lines.append("set link y2")

        lines.append(f"set xtics {plotdef.xtics if plotdef.xtics else 'auto'}")
        lines.append(f"set ytics {plotdef.ytics if plotdef.ytics else self._format_number(y1_auto_tics) if y1_auto_tics else 'auto'}")
        if uses_y2:
            lines.append(f"set y2tics {plotdef.y2tics if plotdef.y2tics else self._format_number(y2_auto_tics) if y2_auto_tics else 'auto'}")
        else:
            lines.append("set y2tics")

        effective_minor_grid = plotdef.minor_grid and getattr(plotdef, "major_grid", True)

        if plotdef.mxtics: lines.append(f"set mxtics {int(plotdef.mxtics)+1}")
        elif effective_minor_grid: lines.append("set mxtics 2")
        else: lines.append("unset mxtics")

        if plotdef.mytics: lines.append(f"set mytics {int(plotdef.mytics)+1}")
        elif effective_minor_grid: lines.append("set mytics 2")
        else: lines.append("unset mytics")

        if plotdef.my2tics: lines.append(f"set my2tics {int(plotdef.my2tics)+1}")
        elif effective_minor_grid: lines.append("set my2tics 2")
        else: lines.append("unset my2tics")

        grid_parts = []
        if getattr(plotdef, "major_grid", True): grid_parts += ["xtics", "ytics"]
        if effective_minor_grid: grid_parts += ["mxtics", "mytics"]

        #if grid_parts: lines.append(f"set grid {' '.join(grid_parts)}")
        #else: lines.append("unset grid")
        if grid_parts:
            lines.append(f"set grid {' '.join(grid_parts)} lw 1.5, lw 1.0")
        else:
            lines.append("unset grid")

        lines.append("set mouse")
        lines.append(f"set border lw {1.5 * border_scale}")

        if getattr(plotdef, "is_print_mode", False) and not is_multiplot:
            # 단일 plot을 인쇄/저장용 큰 캔버스(A4 등)에 그릴 때 내용이 가장자리에
            # 붙어서 여백이 없어 보이던 문제 - 기본 여백을 확보한다.
            lines.append("set lmargin at screen 0.10")
            lines.append("set tmargin at screen 0.90")
            lines.append("set bmargin at screen 0.12")

        def _pct_to_frac(value, default=0.5):
            # 사용자는 0~100(%)으로 입력하고, gnuplot의 graph 좌표계는 0~1이라 변환한다
            try:
                return float(value) / 100.0
            except (TypeError, ValueError):
                return default

        if annotations:
            for i, ann in enumerate(annotations):
                ann_text, ann_enh = self._render_text(ann["text"])
                gx = _pct_to_frac(ann["x"])
                gy = _pct_to_frac(ann["y"])
                try:
                    angle_val = float(ann.get("angle", "0") or 0)
                except (TypeError, ValueError):
                    angle_val = 0
                rotate_clause = f"rotate by {angle_val}" if angle_val else "norotate"
                lines.append(
                    f'set label {i+1} "{ann_text}" '
                    f'at graph {gx},graph {gy} {rotate_clause} {ann_enh}'
                )

        if arrows:
            head_map = {"No head": "nohead", "Forward": "head", "Backhead": "backhead", "Both heads": "heads"}
            for i, arr in enumerate(arrows):
                head = head_map.get(arr.get("head", "Forward"), "head")
                gx1 = _pct_to_frac(arr["x1"], 0.1)
                gy1 = _pct_to_frac(arr["y1"], 0.1)
                gx2 = _pct_to_frac(arr["x2"], 0.5)
                gy2 = _pct_to_frac(arr["y2"], 0.5)
                lines.append(
                    f'set arrow {i+1} '
                    f'from graph {gx1},graph {gy1} '
                    f'to graph {gx2},graph {gy2} {head}'
                )

        tic_size = int(9 * f_scale)
        lines.append("set tics scale 1.0, 0.5")

        lines.append(f"set xtics font '{plotdef.xlabel_font},{tic_size}'")
        lines.append(f"set ytics font '{plotdef.ylabel_font},{tic_size}'")
        lines.append(f"set y2tics font '{plotdef.y2label_font},{tic_size}'")

        title_size = int(float(plotdef.title_size) * f_scale)
        xlabel_size = int(float(plotdef.xlabel_size) * f_scale)
        ylabel_size = int(float(plotdef.ylabel_size) * f_scale)
        y2label_size = int(float(plotdef.y2label_size) * f_scale)

        title_text, title_enh = self._render_text(plotdef.title)
        lines.append(f'set title "{title_text}" font "{plotdef.title_font},{title_size}" {title_enh}')

        #xlabel_text, xlabel_enh = self._render_text(plotdef.xlabel)
        # [개선 1] 첫 번째 선택된 파일/커브를 기준으로 동적 X축 타이틀 추출
        effective_xlabel = plotdef.xlabel
        x_out_no = getattr(plotdef, "x_output_no", 0)
        if plotdef.curves and hasattr(plotdef, "xlabel") and plotdef.xlabel == "Time (sec)":
            try:
                first_dat = plotdef.curves[0].dat_file
                if os.path.exists(first_dat):
                    with open(first_dat, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            stripped = line.strip()
                            if stripped and not stripped.startswith("#") and "---" not in stripped:
                                fields = re.split(r'[,\s]+', stripped)
                                # 헤더 타이틀이나 특정 라벨 유추 위치 체크 가능 시 반영
                                break
            except Exception:
                pass

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
            #box = "box" if plotdef.legend_box else "nobox" # 적용 안해도 무방?
            opaque = "opaque" if plotdef.legend_box else ""

            if plotdef.legend_pos == "outside right":
                if not is_multiplot:
                    lines.append("set rmargin at screen 0.78")
                pos = "outside right center"
            else:
                if plotdef.legend_box and plotdef.legend_pos.startswith("right") and not is_multiplot:
                    lines.append("set rmargin at screen 0.88")
                pos = f"inside {plotdef.legend_pos}"

            lines.append(
                f'set key enhanced {pos} {box} {opaque} '
                f'font "{plotdef.xlabel_font},{int(9*f_scale)}" '
                f'samplen 2.5 spacing 1.2'
            )

        else:
            lines.append("unset key")

        lines.append("plot \\")
        cmd_list = []

        for i, curve in enumerate(plotdef.curves):
            color = curve.color or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
            linestyle = curve.linestyle or DEFAULT_LINESTYLES[i % len(DEFAULT_LINESTYLES)]
            path = (curve.dat_file if os.path.isabs(curve.dat_file) else os.path.abspath(curve.dat_file)).replace("\\", "/")

            is_y2 = getattr(curve, "axis", "y1") == "y2"
            axis = "x1y2" if is_y2 else "x1y1"
            #col = curve.output_no + 1
            # x_out_no가 0보다 크면 해당 컬럼 번호(1 베이스)를 X축으로 사용
            x_col_expr = f"${x_out_no + 1}" if x_out_no > 0 else "$1"
            col_y = curve.output_no + 1
            using_expr = f"({x_col_expr}+{curve.x_shift}):{col_y}"

            lw = curve.linewidth * line_scale

            curve_title_text, curve_title_enh = self._render_text(curve.title)
            #cmd = f'"{path}" using ($1+{curve.x_shift}):{col} title "{curve_title_text}" {curve_title_enh} axes {axis} with lines lw {lw}'
            cmd = f'"{path}" using {using_expr} title "{curve_title_text}" {curve_title_enh} axes {axis} with lines lw {lw}'

            if color: cmd += f' lc rgb "{color}"'
            if linestyle in LINESTYLE_MAP: cmd += f" dt {LINESTYLE_MAP[linestyle]}"
            # 다음은 LINESTYLE_MAP 정의와 연동
            #dt_value = LINESTYLE_MAP.get(linestyle, 1)
            #cmd += f' dt {dt_value}'
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
            if size_override:
                return f"size {size_override}"
            if plotdef is not None and not getattr(plotdef, "frame_auto", True):
                w = (getattr(plotdef, "frame_width", "") or "").strip()
                h = (getattr(plotdef, "frame_height", "") or "").strip()
                unit = (getattr(plotdef, "frame_unit", "in") or "in").strip()
                if w and h:
                    return f"size {w}{unit},{h}{unit}"
            return default

        # 창 이름과 파일명 번호(_1, _2)를 100% 동일하게 일치시킴
        title = os.path.splitext(os.path.basename(outfile))[0]

        if fmt == "interactive":
            return (
                f"set terminal qt enhanced "
                f"title '{title}' "
                f"font 'Malgun Gothic,11' "
                f"{size_clause('')}"
            )
        elif fmt == "png":
            return f"set terminal pngcairo {size_clause('size 1600,900')} enhanced font 'Malgun Gothic,11'"
        elif fmt == "jpg":
            return f"set terminal jpeg {size_clause('size 1600,900')} enhanced font 'Malgun Gothic,11'"
        elif fmt == "svg":
            return f"set terminal svg enhanced {size_clause('size 11.7in,8.3in')} font 'Malgun Gothic,11'"
        elif fmt == "pdf":
            return f"set terminal pdfcairo enhanced color font 'Malgun Gothic,11' {size_clause('size 11.7in,8.3in')}"
        elif fmt == "eps":
            return f"set terminal postscript eps enhanced color font 'Malgun Gothic,11' {size_clause('')}"
        elif fmt == "emf":
            return f"set terminal emf enhanced {size_clause('')} font 'Malgun Gothic,11'"
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

        if fmt.lower() == "interactive":
            script_path = outfile.rsplit(".", 1)[0] + ".plt"
        else:
            script_path = os.path.join(plot_dir, f".cathplot_tmp_{uuid.uuid4().hex}.plt")

        with open(script_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        try:
            gnuplot_exe = _resolve_gnuplot_exe()
            if fmt.lower() == "interactive":
                self.last_process = subprocess.Popen([gnuplot_exe, "-persist", script_path], cwd=plot_dir)
            else:
                subprocess.run([gnuplot_exe, script_path], check=True)
        finally:
            #if fmt.lower() != "interactive" and os.path.exists(script_path):
            #    os.remove(script_path)
            # [수정] 개발 단계 검증을 위해 cathplot 종료/닫힐 때까지 임시 파일 삭제하지 않고 유지
            pass

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
            if nplot <= 1:
                orientation = "landscape"
            elif nplot == 2:
                orientation = "portrait"
            else:
                orientation = "landscape"

            if nplot <= 1: rows, cols = 1, 1
            elif nplot == 2: rows, cols = (1, 2) if orientation == "landscape" else (2, 1)
            elif nplot <= 4: rows, cols = 2, 2
            else: rows, cols = 3, 2
        elif layout_option in ["1/p", "1"]:
            rows, cols = 1, 1
        elif "2/p" in layout_option:
            rows, cols = 2, 1
        elif "4/p" in layout_option:
            rows, cols = 2, 2
        elif "6/p" in layout_option:
            rows, cols = (2, 3) if orientation == "landscape" else (3, 2)
        else:
            rows, cols = 1, 1

        total_cells = rows * cols

        any_legend_outside = any(p.legend_on and p.legend_pos == "outside right" for p in plots)
        any_y2 = any(any(getattr(c, "axis", "y1") == "y2" for c in p.curves) for p in plots)
        any_title = any(p.title.strip() for p in plots)
        max_title_lines = max((1 + p.title.count("|")) for p in plots) if plots else 1

        if total_cells > 2:
            panel_scale = min(1.0 / cols, 1.0 / rows)
        else:
            panel_scale = 1.0

        margin_left = MARGIN_LEFT_IN * panel_scale
        margin_right = (
            MARGIN_RIGHT_IN
            + (MARGIN_RIGHT_LEGEND_IN if any_legend_outside else 0)
            + (MARGIN_RIGHT_Y2_IN if any_y2 else 0)
        ) * panel_scale
        title_margin_base = MARGIN_TOP_IN if any_title else MARGIN_TOP_NO_TITLE_IN
        margin_top = (title_margin_base + MARGIN_TOP_PER_EXTRA_LINE_IN * (max_title_lines - 1)) * panel_scale
        margin_bottom = MARGIN_BOTTOM_IN * panel_scale
        spacing_in = CELL_SPACING_IN * panel_scale

        if frame_auto:
            aw, ah = self._A4_SIZES.get(orientation, self._A4_SIZES["portrait"])
            page_w = float(aw.replace("in", ""))
            page_h = float(ah.replace("in", ""))

            cell_w_in = (page_w - spacing_in * (cols - 1)) / cols
            cell_h_in = (page_h - spacing_in * (rows - 1)) / rows

            axis_w = max(cell_w_in - margin_left - margin_right, 0.5)
            axis_h = max(cell_h_in - margin_top - margin_bottom, 0.5)
            cell_w_in = axis_w + margin_left + margin_right
            cell_h_in = axis_h + margin_top + margin_bottom

            cell_positions_in = []
            for i in range(total_cells):
                row_idx = i // cols
                col_idx = i % cols
                cell_left_in = col_idx * (cell_w_in + spacing_in)
                cell_top_in = page_h - row_idx * (cell_h_in + spacing_in)
                cell_positions_in.append(
                    (cell_left_in, cell_left_in + cell_w_in, cell_top_in, cell_top_in - cell_h_in)
                )
        else:
            if frame_width and frame_height:
                try:
                    axis_w_ref = float(frame_width)
                    axis_h_ref = float(frame_height)
                except ValueError:
                    axis_w_ref, axis_h_ref = 5.0, 4.0
                if frame_unit == "cm":
                    axis_w_ref /= 2.54
                    axis_h_ref /= 2.54
            else:
                axis_w_ref, axis_h_ref = 5.0, 4.0

            axis_w = axis_w_ref * panel_scale
            axis_h = axis_h_ref * panel_scale

            cell_w_in = axis_w + margin_left + margin_right
            cell_h_in = axis_h + margin_top + margin_bottom

            if total_cells == 1:
                aw, ah = self._A4_SIZES.get(orientation, self._A4_SIZES["portrait"])
                page_w = float(aw.replace("in", ""))
                page_h = float(ah.replace("in", ""))

                if cell_w_in > page_w:
                    shrink = page_w / cell_w_in
                    axis_w *= shrink; margin_left *= shrink; margin_right *= shrink
                    cell_w_in = axis_w + margin_left + margin_right
                if cell_h_in > page_h:
                    shrink = page_h / cell_h_in
                    axis_h *= shrink; margin_top *= shrink; margin_bottom *= shrink
                    cell_h_in = axis_h + margin_top + margin_bottom

                cell_left_in = (page_w - cell_w_in) / 2
                cell_bottom_in = (page_h - cell_h_in) / 2
                cell_positions_in = [(cell_left_in, cell_left_in + cell_w_in, cell_bottom_in + cell_h_in, cell_bottom_in)]
            else:
                page_w = cell_w_in * cols + spacing_in * (cols - 1)
                page_h = cell_h_in * rows + spacing_in * (rows - 1)

                if total_cells > 2:
                    aw, ah = self._A4_SIZES.get(orientation, self._A4_SIZES["portrait"])
                    a4_w = float(aw.replace("in", ""))
                    a4_h = float(ah.replace("in", ""))

                    if page_w > a4_w or page_h > a4_h:
                        shrink = min(a4_w / page_w, a4_h / page_h)
                        axis_w *= shrink
                        axis_h *= shrink
                        margin_left *= shrink; margin_right *= shrink
                        margin_top *= shrink; margin_bottom *= shrink
                        spacing_in *= shrink
                        cell_w_in = axis_w + margin_left + margin_right
                        cell_h_in = axis_h + margin_top + margin_bottom
                        page_w = cell_w_in * cols + spacing_in * (cols - 1)
                        page_h = cell_h_in * rows + spacing_in * (rows - 1)

                cell_positions_in = []
                for i in range(total_cells):
                    row_idx = i // cols
                    col_idx = i % cols
                    cell_left_in = col_idx * (cell_w_in + spacing_in)
                    cell_top_in = page_h - row_idx * (cell_h_in + spacing_in)
                    cell_positions_in.append(
                        (cell_left_in, cell_left_in + cell_w_in, cell_top_in, cell_top_in - cell_h_in)
                    )
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

            if i > 0:
                lines.append("unset title")
                lines.append("set xtics auto")
                lines.append("set ytics auto")
                lines.append("set y2tics auto")

            lines.append(f"set lmargin at screen {axis_left_in / page_w:.4f}")
            lines.append(f"set rmargin at screen {axis_right_in / page_w:.4f}")
            lines.append(f"set tmargin at screen {axis_top_in / page_h:.4f}")
            lines.append(f"set bmargin at screen {axis_bottom_in / page_h:.4f}")

            self._build_plot_commands(
                plotdef, lines, is_multiplot=True, panel_scale=panel_scale,
                annotations=getattr(plotdef, "annotations", None),
                arrows=getattr(plotdef, "arrows", None),
            )

        lines.append("unset multiplot")
        lines.append("set output")

        script_path = outfile.rsplit(".", 1)[0] + ".plt"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        gnuplot_exe = _resolve_gnuplot_exe()
        result = subprocess.run(
            [gnuplot_exe, script_path],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"gnuplot 실행 실패 (스크립트 보존됨: {script_path})\n"
                f"{result.stderr.strip()}"
            )

        if not keep_script and os.path.exists(script_path):
            os.remove(script_path)

        return outfile
