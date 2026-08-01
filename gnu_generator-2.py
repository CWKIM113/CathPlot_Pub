# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
import os
import shutil
import subprocess

# "gnuplot" 이 PATH에 등록되어 있지 않은 Windows 환경이 흔해서(설치는 됐지만 PATH
# 미등록), PATH에서 못 찾으면 흔히 설치되는 경로들을 순서대로 확인한다.
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

    _gnuplot_exe_cache = found or "gnuplot"  # 못 찾으면 기존처럼 "gnuplot"으로 시도(에러 메시지 유지)
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

    # Frame(=출력 캔버스) 크기: auto면 포맷별 기본값 사용, 아니면 width/height(unit) 사용
    frame_auto: bool = True
    frame_width: str = ""
    frame_height: str = ""
    frame_unit: str = "in"   # "in" 또는 "cm"

class GnuplotGenerator:

    def __init__(self, plot_dir=None):
        self.plot_dir = plot_dir
        self.use_default_colors = True
        self.use_default_styles = True
        self.custom_export_path = None

    def _has_enhanced_markup(self, text):
        # text 안에 짝이 맞는 _{...} 또는 ^{...} 첨자 마크업이 실제로 있는지 검사
        if not text:
            return False
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch in ("_", "^") and i + 1 < n and text[i + 1] == "{":
                depth = 1
                j = i + 2
                while j < n and depth > 0:
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                    j += 1
                if depth == 0:
                    return True
                i = j
                continue
            i += 1
        return False

    def _render_text(self, text):
        # (문자열, enhanced/noenhanced 키워드) 반환.
        # 실제 _{...}/^{...} 첨자 마크업이 있을 때만 enhanced를 켜고, 그 외의
        # 평범한 텍스트는 noenhanced로 완전히 리터럴 출력한다. noenhanced에서는
        # _, ^ 에 특수한 의미가 없어 이스케이프가 아예 필요 없으므로, qt/pdfcairo
        # 등 터미널마다 backslash+큰따옴표 처리 방식이 미묘하게 달라서 생기는
        # 불일치(예: PDF에서만 글자가 세로로 쌓이는 현상)를 원천적으로 피한다.
        if self._has_enhanced_markup(text):
            return self._sanitize(text), "enhanced"
        else:
            safe = (text or "").replace("\\", "\\\\").replace('"', '\\"')
            return safe, "noenhanced"

    def _sanitize(self, text):
        if not text:
            return ""

        result = []
        i = 0
        n = len(text)

        while i < n:
            ch = text[i]

            if ch in ("_", "^") and i + 1 < n and text[i + 1] == "{":
                depth = 1
                j = i + 2
                while j < n and depth > 0:
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                    j += 1

                if depth == 0:
                    result.append(text[i:j])
                    i = j
                    continue
                else:
                    result.append("\\\\" + ch)
                    i += 1
                    continue

            elif ch in ("_", "^"):
                result.append("\\\\" + ch)
                i += 1

            elif ch == "\\":
                result.append("\\\\")
                i += 1

            else:
                result.append(ch)
                i += 1

        return "".join(result)

    def _get_data_range(self, dat_file, col):
        try:
            with open(dat_file, 'r') as f:
                vals = []
                for line in f:
                    if line.startswith("#"): continue
                    parts = line.split()
                    if len(parts) >= col:
                        try: vals.append(float(parts[col-1]))
                        except: continue
                if vals: return min(vals), max(vals)
        except: pass
        return 0, 1000

    def _build_plot_commands(
        self,
        plotdef,
        lines,
        is_multiplot=False,
        annotations=None,
        arrows=None
    ):
        if plotdef.xauto:
            lines.append("set autoscale x")
        else:
            lines.append(
                f"set xrange [{plotdef.xmin.strip()}:{plotdef.xmax.strip()}]"
            )

        if plotdef.yauto:
            lines.append("set autoscale y")
        else:
            lines.append(
                f"set yrange [{plotdef.ymin.strip()}:{plotdef.ymax.strip()}]"
            )

        lines.append("set y2tics")

        if getattr(plotdef, "y2auto", True):
            lines.append("set autoscale y2")
        else:
            lines.append(
                f"set y2range [{plotdef.y2min}:{plotdef.y2max}]"
            )

        lines.append(
            f"set xtics {plotdef.xtics if plotdef.xtics else 'auto'}"
        )

        lines.append(
            f"set ytics {plotdef.ytics if plotdef.ytics else 'auto'}"
        )

        if plotdef.mxtics:
            lines.append(f"set mxtics {int(plotdef.mxtics)+1}")
        else:
            lines.append("unset mxtics")

        if plotdef.mytics:
            lines.append(f"set mytics {int(plotdef.mytics)+1}")
            lines.append(f"set my2tics {int(plotdef.mytics)+1}")
        else:
            lines.append("unset mytics")
            lines.append("unset my2tics")

        lines.append("set mouse")
        lines.append("set border lw 1.5")

        if plotdef.minor_grid:
            lines.append("set grid xtics ytics mxtics mytics")
        else:
            lines.append("set grid xtics ytics")

        if annotations:
            for i, ann in enumerate(annotations):
                ann_text, ann_enh = self._render_text(ann["text"])
                lines.append(
                    f'set label {i+1} "{ann_text}" '
                    f'at {ann["x"]},{ann["y"]} {ann_enh}'
                )

        if arrows:
            head_map = {
                "No head": "nohead",
                "Forward": "head",
                "Backhead": "backhead",
                "Both heads": "heads",
            }

            for i, arr in enumerate(arrows):
                head = head_map.get(arr.get("head", "Forward"), "head")

                lines.append(
                    f'set arrow {i+1} '
                    f'from {arr["x1"]},{arr["y1"]} '
                    f'to {arr["x2"]},{arr["y2"]} '
                    f'{head}'
                )

        f_scale = 1.4 if getattr(plotdef, "is_print_mode", False) else 1.0

        title_size = int(float(plotdef.title_size) * f_scale)
        xlabel_size = int(float(plotdef.xlabel_size) * f_scale)
        ylabel_size = int(float(plotdef.ylabel_size) * f_scale)
        y2label_size = int(float(plotdef.y2label_size) * f_scale)

        title_text, title_enh = self._render_text(plotdef.title)
        lines.append(
            f'set title "{title_text}" '
            f'font "{plotdef.title_font},{title_size}" {title_enh}'
        )

        xlabel_text, xlabel_enh = self._render_text(plotdef.xlabel)
        lines.append(
            f'set xlabel "{xlabel_text}" '
            f'font "{plotdef.xlabel_font},{xlabel_size}" {xlabel_enh}'
        )

        ylabel_text, ylabel_enh = self._render_text(plotdef.ylabel)
        lines.append(
            f'set ylabel "{ylabel_text}" '
            f'font "{plotdef.ylabel_font},{ylabel_size}" {ylabel_enh}'
        )

        if plotdef.y2label:
            y2label_text, y2label_enh = self._render_text(plotdef.y2label)
            lines.append(
                f'set y2label "{y2label_text}" '
                f'font "{plotdef.y2label_font},{y2label_size}" {y2label_enh}'
            )

        lines.append("set ytics nomirror")

        if plotdef.legend_on:

            box = "box" if plotdef.legend_box else "nobox"
            opaque = "opaque" if plotdef.legend_box else ""

            if plotdef.legend_pos == "outside right":

                lines.append(
                    "set rmargin at screen 0.78"
                )

                pos = "outside right center"

            else:
                if plotdef.legend_box and plotdef.legend_pos.startswith("right"):
                    lines.append(
                        "set rmargin at screen 0.88"
                    )

                pos = f"inside {plotdef.legend_pos}"

            lines.append(
                f'set key enhanced {pos} {box} {opaque} '
                f'font "{plotdef.xlabel_font},{int(9*f_scale)}" '
                f'samplen 2.5 spacing 1.2'
            )

        else:
            lines.append("unset key")

        lines.append("plot \\")

        n = len(plotdef.curves)

        for i, curve in enumerate(plotdef.curves):

            color = curve.color
            if self.use_default_colors and not color:
                color = DEFAULT_COLORS[
                    i % len(DEFAULT_COLORS)
                ]

            linestyle = curve.linestyle
            if self.use_default_styles and not linestyle:
                linestyle = DEFAULT_LINESTYLES[
                    i % len(DEFAULT_LINESTYLES)
                ]

            path = (
                curve.dat_file
                if os.path.isabs(curve.dat_file)
                else os.path.abspath(curve.dat_file)
            ).replace("\\", "/")

            axis = (
                "x1y2"
                if getattr(curve, "axis", "y1") == "y2"
                else "x1y1"
            )

            col = curve.output_no + 1

            lw = (
                curve.linewidth * 1.5
                if getattr(plotdef, "is_print_mode", False)
                else curve.linewidth
            )

            curve_title_text, curve_title_enh = self._render_text(curve.title)

            cmd = (
                f'"{path}" '
                f'using ($1+{curve.x_shift}):{col} '
                f'title "{curve_title_text}" {curve_title_enh} '
                f'axes {axis} '
                f'with lines lw {lw}'
            )

            if color:
                cmd += f' lc rgb "{color}"'

            if (
                linestyle
                and linestyle in LINESTYLE_MAP
            ):
                cmd += f" dt {LINESTYLE_MAP[linestyle]}"

            if i != n - 1:
                cmd += ", \\"

            lines.append(cmd)

        lines.append("")

        if is_multiplot:
            lines.append("unset label")
            lines.append("unset arrow")


    def create_script(
        self,
        plotdef,
        outfile,
        fmt="pdf",
        annotations=None,
        arrows=None
    ):
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        if not os.path.exists(plot_dir):
            os.makedirs(plot_dir)

        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile, plotdef),
        ]

        if fmt.lower() != "interactive":
            lines.append(
                f"set output '{outfile.replace(chr(92), '/')}'"
            )

        self._build_plot_commands(
            plotdef,
            lines,
            is_multiplot=False,
            annotations=annotations,
            arrows=arrows
        )

        if fmt.lower() == "interactive":
            lines.append("pause mouse close")
        else:
            lines.append("set output")

        script_path = outfile.rsplit(".", 1)[0] + ".plt"

        with open(script_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        try:

            gnuplot_exe = _resolve_gnuplot_exe()

            if fmt.lower() == "interactive":
                subprocess.Popen(
                    [gnuplot_exe, "-persist", script_path],
                    cwd=plot_dir
                )

            else:
                subprocess.run(
                    [gnuplot_exe, script_path],
                    check=True
                )

        finally:

            if fmt.lower() != "interactive":
                if os.path.exists(script_path):
                    os.remove(script_path)

        return outfile

    def create_multiplot_script(
        self,
        plots,
        outfile,
        fmt="pdf"
    ):
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)

        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile, plots[0] if plots else None),
            f"set output '{outfile.replace(chr(92), '/')}'"
        ]

        nplot = len(plots)

        if nplot <= 1:
            rows, cols = 1, 1
        elif nplot == 2:
            rows, cols = 2, 1
        else:
            rows, cols = 2, 2

        lines.append(f"set multiplot layout {rows},{cols}")

        for plot in plots:
            self._build_plot_commands(
                plot,
                lines,
                is_multiplot=True,
                annotations=getattr(plot, "annotations", None),
                arrows=getattr(plot, "arrows", None),
            )

        lines.append("unset multiplot")

        if fmt.lower() == "interactive":
            lines.append("pause mouse close")
        else:
            lines.append("set output")

        script_path = outfile.rsplit(".", 1)[0] + ".plt"

        with open(script_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        try:

            gnuplot_exe = _resolve_gnuplot_exe()

            if fmt.lower() == "interactive":
                subprocess.Popen(
                    [gnuplot_exe, "-persist", script_path],
                    cwd=plot_dir
                )

            else:
                subprocess.run(
                    [gnuplot_exe, script_path],
                    check=True
                )

        except FileNotFoundError:
            raise FileNotFoundError(
                "gnuplot 실행 파일을 찾을 수 없습니다. gnuplot이 설치되어 있는지, "
                "PATH에 등록되어 있는지 확인하세요. (시도한 경로: "
                f"{gnuplot_exe})"
            )

        finally:

            if fmt.lower() != "interactive":
                if os.path.exists(script_path):
                    os.remove(script_path)

        return outfile

    def _get_terminal_cmd(self, fmt, outfile, plotdef=None):

        fmt = fmt.lower()

        def size_clause(default):
            if plotdef is not None and not getattr(plotdef, "frame_auto", True):
                w = (getattr(plotdef, "frame_width", "") or "").strip()
                h = (getattr(plotdef, "frame_height", "") or "").strip()
                unit = (getattr(plotdef, "frame_unit", "in") or "in").strip()
                if w and h:
                    return f"size {w}{unit},{h}{unit}"
            return default

        if fmt == "interactive":
            title = os.path.splitext(
                os.path.basename(outfile)
            )[0]
            return (
                f"set terminal qt enhanced "
                f"title '{title}' "
                f"font 'Malgun Gothic,11' "
                f"{size_clause('')}"
            )

        elif fmt == "png":
            return (
                "set terminal pngcairo "
                f"{size_clause('size 1600,900')} enhanced "
                "font 'Malgun Gothic,11'"
            )

        elif fmt == "jpg":
            return (
                "set terminal jpeg "
                f"{size_clause('size 1600,900')} enhanced "
                "font 'Malgun Gothic,11'"
            )

        elif fmt == "svg":
            return (
                "set terminal svg enhanced "
                f"{size_clause('')} "
                "font 'Malgun Gothic,11'"
            )

        elif fmt == "pdf":
            return (
                "set terminal pdfcairo enhanced "
                "color font 'Malgun Gothic,11' "
                f"{size_clause('size 11.7in,8.3in')}"
            )

        elif fmt == "eps":
            return (
                "set terminal postscript eps enhanced "
                f"color font 'Malgun Gothic,11' "
                f"{size_clause('')}"
            )

        elif fmt == "emf":
            return (
                "set terminal emf enhanced "
                f"{size_clause('')} "
                "font 'Malgun Gothic,11'"
            )

        else:
            raise ValueError(f"Unsupported output format : {fmt}")
            