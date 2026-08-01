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
        """Return a readable (min, max, major-step) for curves on one y axis."""
        values = []
        for curve in plotdef.curves:
            if getattr(curve, "axis", "y1") != axis:
                continue
            column = curve.output_no
            try:
                with open(curve.dat_file, "r", encoding="utf-8", errors="ignore") as data:
                    for row in data:
                        fields = row.split()
                        if len(fields) <= column:
                            continue
                        try:
                            value = float(fields[column].replace("D", "E").replace("d", "e"))
                        except ValueError:
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

    def _build_plot_commands(self, plotdef, lines, is_multiplot=False, annotations=None, arrows=None):
        if plotdef.xauto: lines.append("set autoscale x")
        else: lines.append(f"set xrange [{plotdef.xmin.strip()}:{plotdef.xmax.strip()}]")

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
            lines.append("unset y2tics")

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

        if grid_parts: lines.append(f"set grid {' '.join(grid_parts)}")
        else: lines.append("unset grid")

        lines.append("set mouse")
        lines.append(f"set border lw {1.5 * (1.5 if getattr(plotdef, 'is_print_mode', False) else 1.0)}")

        if getattr(plotdef, "is_print_mode", False) and not is_multiplot:
            # 단일 plot을 인쇄/저장용 큰 캔버스(A4 등)에 그릴 때 내용이 가장자리에
            # 붙어서 여백이 없어 보이던 문제 - 기본 여백을 확보한다.
            lines.append("set lmargin at screen 0.10")
            lines.append("set tmargin at screen 0.90")
            lines.append("set bmargin at screen 0.12")

        # Range: 0 ~ 1
        #if annotations:
        #    for i, ann in enumerate(annotations):
        #        ann_text, ann_enh = self._render_text(ann["text"])
        #        # graph 좌표계(0~1) 사용: 0,0=plot 왼쪽 아래 / 1,1=오른쪽 위.
        #        # 실제 데이터 값 범위를 몰라도 위치를 잡을 수 있어서 화면 밖으로
        #        # 벗어나 안 보이는 문제를 피할 수 있다.
        #        lines.append(f'set label {i+1} "{ann_text}" at graph {ann["x"]},graph {ann["y"]} {ann_enh}')
        #
        #if arrows:
        #    head_map = {"No head": "nohead", "Forward": "head", "Backhead": "backhead", "Both heads": "heads"}
        #    for i, arr in enumerate(arrows):
        #        head = head_map.get(arr.get("head", "Forward"), "head")
        #        lines.append(
        #            f'set arrow {i+1} '
        #            f'from graph {arr["x1"]},graph {arr["y1"]} '
        #            f'to graph {arr["x2"]},graph {arr["y2"]} {head}'
        #        )
        #        
        
        # Range: 0 ~ 100
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
        # 1.4 -> 1.8 or 2.2 etc
        f_scale = 1.8 if getattr(plotdef, "is_print_mode", False) else 1.0

        title_size = int(float(plotdef.title_size) * f_scale)
        xlabel_size = int(float(plotdef.xlabel_size) * f_scale)
        ylabel_size = int(float(plotdef.ylabel_size) * f_scale)
        y2label_size = int(float(plotdef.y2label_size) * f_scale)

        title_text, title_enh = self._render_text(plotdef.title)
        lines.append(f'set title "{title_text}" font "{plotdef.title_font},{title_size}" {title_enh}')

        xlabel_text, xlabel_enh = self._render_text(plotdef.xlabel)
        lines.append(f'set xlabel "{xlabel_text}" font "{plotdef.xlabel_font},{xlabel_size}" {xlabel_enh}')

        ylabel_text, ylabel_enh = self._render_text(plotdef.ylabel)
        lines.append(f'set ylabel "{ylabel_text}" font "{plotdef.ylabel_font},{ylabel_size}" {ylabel_enh}')

        if plotdef.y2label:
            y2label_text, y2label_enh = self._render_text(plotdef.y2label)
            lines.append(f'set y2label "{y2label_text}" font "{plotdef.y2label_font},{y2label_size}" {y2label_enh}')

        lines.append("set ytics nomirror")

        if plotdef.legend_on:
            box = "box" if plotdef.legend_box else "nobox"
            opaque = "opaque" if plotdef.legend_box else ""
            if plotdef.legend_pos == "outside right":
                if not is_multiplot:
                    # "at screen" 은 페이지 전체 기준 절대좌표라, 멀티플롯의
                    # 서브플롯 칸 안에서 쓰면 모든 서브플롯이 같은 위치로
                    # 겹쳐버린다. 단일(1/p) plot일 때만 사용한다.
                    lines.append("set rmargin at screen 0.78")
                pos = "outside right center"
            else:
                if plotdef.legend_box and plotdef.legend_pos.startswith("right") and not is_multiplot:
                    lines.append("set rmargin at screen 0.88")
                pos = f"inside {plotdef.legend_pos}"
            lines.append(f'set key enhanced {pos} {box} {opaque} font "{plotdef.xlabel_font},{int(9*f_scale)}" samplen 2.5 spacing 1.2')
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
            col = curve.output_no + 1
            lw = curve.linewidth * 1.5 if getattr(plotdef, "is_print_mode", False) else curve.linewidth

            curve_title_text, curve_title_enh = self._render_text(curve.title)
            cmd = f'"{path}" using ($1+{curve.x_shift}):{col} title "{curve_title_text}" {curve_title_enh} axes {axis} with lines lw {lw}'
            if color: cmd += f' lc rgb "{color}"'
            if linestyle in LINESTYLE_MAP: cmd += f" dt {LINESTYLE_MAP[linestyle]}"
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
        #base = os.path.splitext(os.path.basename(outfile))[0]
        #title = base.replace("_Temp", "").replace("Print_Job_", "")
        #title = title.replace(" (", "_").replace(")", "")

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
            # Interactive는 화면/목록에 보여줄 이름이 필요하므로 outfile 기준 이름 유지
            script_path = outfile.rsplit(".", 1)[0] + ".plt"
        else:
            # Batch(Save/Print)는 사용자에게 안 보이는 임시 스크립트라, outfile
            # 이름과 절대 겹치지 않는 고유 이름을 쓴다. (같은 제목으로 이미
            # 열려있는 Interactive 창이 그 .plt 파일을 -persist로 붙잡고 있으면
            # 같은 이름으로 쓰다가 PermissionError가 났었다)
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
            if fmt.lower() != "interactive" and os.path.exists(script_path):
                os.remove(script_path)

        return outfile

    _A4_SIZES = {
        "portrait": ("8.27in", "11.69in"),
        "landscape": ("11.69in", "8.27in"),
    }

    def create_multiplot_script(self, plots, outfile, fmt="pdf", layout_option="Auto", orientation="portrait", margins=(0.08, 0.94, 0.06, 0.94), spacing=(0.09, 0.10)):
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)

        nplot = len(plots)
        rows, cols = 1, 1
        
        if layout_option == "Auto":
            if nplot <= 1: rows, cols = 1, 1
            elif nplot == 2: rows, cols = (1, 2) if orientation == "landscape" else (2, 1)
            elif nplot <= 4: rows, cols = 2, 2
            else: rows, cols = 3, 2
        elif layout_option in ["1/p", "1"]: rows, cols = 1, 1
        elif "2/p" in layout_option: rows, cols = 2, 1
        elif "4/p" in layout_option: rows, cols = 2, 2
        elif "6/p" in layout_option: rows, cols = 3, 2

        w, h = self._A4_SIZES.get(orientation, self._A4_SIZES["portrait"])
        size_override = f"{w},{h}"

        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile, None, size_override),
            f"set output '{outfile.replace(chr(92), '/')}'"
        ]

        l, r, b, t = margins
        sx, sy = spacing

        if rows * cols > 1:
            lines.append(f"set multiplot layout {rows},{cols} margins {l},{r},{b},{t} spacing {sx},{sy}")
        else:
            lines.append(f"set multiplot layout {rows},{cols}")

        for i, plotdef in enumerate(plots):
            # 다중 플롯 시 앞선 그림의 잔상(축/margin)이 남아 겹치거나 밀리는 현상 방지
            if i > 0:
                lines.append("unset title")
                lines.append("set xtics auto")
                lines.append("set ytics auto")
                lines.append("set y2tics auto")
            lines.append("set lmargin")
            lines.append("set rmargin")
            lines.append("set tmargin")
            lines.append("set bmargin")
            self._build_plot_commands(plotdef, lines, is_multiplot=True)

        lines.append("unset multiplot")
        lines.append("set output")

        script_path = outfile.rsplit(".", 1)[0] + ".plt"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        try:
            gnuplot_exe = _resolve_gnuplot_exe()
            subprocess.run([gnuplot_exe, script_path], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        finally:
            if os.path.exists(script_path):
                os.remove(script_path)

        return outfile
            
            
