# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
import os
import subprocess

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

class GnuplotGenerator:

    def __init__(self, plot_dir=None):
        self.plot_dir = plot_dir
        self.use_default_colors = True
        self.use_default_styles = True
        self.custom_export_path = None

    def _sanitize(self, text):
        if not text:
            return ""

        result = []
        i = 0
        n = len(text)

        while i < n:
            ch = text[i]

            if ch == "_":
                if i + 1 < n and text[i + 1] == "{":
                    result.append("_")
                else:
                    result.append(r"\_")

            elif ch == "^":
                if i + 1 < n and text[i + 1] == "{":
                    result.append("^")
                else:
                    result.append(r"\^")

            else:
                result.append(ch)

            i += 1

        return "".join(result)

    def _get_data_range(self, dat_file, col):
        #데이터 파일의 특정 열에서 실제 min/max를 계산
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
        return 0, 1000 # 데이터 읽기 실패 시 기본값

    def _build_plot_commands(
        self,
        plotdef,
        lines,
        is_multiplot=False,
        annotations=None,
        arrows=None
    ):
        #
        # Range
        #
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

        #
        # Tics
        #
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

        #
        # Mouse / Border
        #
        lines.append("set mouse")
        lines.append("set border lw 1.5")

        #
        # Grid
        #
        if plotdef.minor_grid:
            lines.append("set grid xtics ytics mxtics mytics")
        else:
            lines.append("set grid xtics ytics")

        #
        # Annotation
        #
        if annotations:
            for i, ann in enumerate(annotations):
                lines.append(
                    f'set label {i+1} "{self._sanitize(ann["text"])}" '
                    f'at {ann["x"]},{ann["y"]}'
                )

        #
        # Arrow
        #
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

        #
        # Font scale
        #
        f_scale = 1.4 if getattr(plotdef, "is_print_mode", False) else 1.0

        title_size = int(float(plotdef.title_size) * f_scale)
        xlabel_size = int(float(plotdef.xlabel_size) * f_scale)
        ylabel_size = int(float(plotdef.ylabel_size) * f_scale)

        #
        # Title / Label
        #
        lines.append(
            f'set title "{self._sanitize(plotdef.title)}" '
            f'font "{plotdef.title_font},{title_size}"'
        )

        lines.append(
            f'set xlabel "{self._sanitize(plotdef.xlabel)}" '
            f'font "{plotdef.xlabel_font},{xlabel_size}"'
        )

        lines.append(
            f'set ylabel "{self._sanitize(plotdef.ylabel)}" '
            f'font "{plotdef.ylabel_font},{ylabel_size}"'
        )

        if plotdef.y2label:
            lines.append(
                f'set y2label "{self._sanitize(plotdef.y2label)}" '
                f'font "{plotdef.y2label_font},{plotdef.y2label_size}"'
            )

        lines.append("set ytics nomirror")

        #
        # Legend
        #
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

        #
        # Plot
        #
        lines.append("plot \\")

        n = len(plotdef.curves)

        for i, curve in enumerate(plotdef.curves):

            #------------------------------------------
            # Default color / linestyle
            #------------------------------------------
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

            cmd = (
                f'"{path}" '
                f'using ($1+{curve.x_shift}):{col} '
                f'title "{self._sanitize(curve.title)}" '
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
        #
        # Output folder
        #
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        if not os.path.exists(plot_dir):
            os.makedirs(plot_dir)

        #
        # Script
        #
        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile),
        ]

        if fmt.lower() != "interactive":
            lines.append(
                f"set output '{outfile.replace(chr(92), '/')}'"
            )

        #
        # Plot commands
        #
        self._build_plot_commands(
            plotdef,
            lines,
            is_multiplot=False,
            annotations=annotations,
            arrows=arrows
        )

        #
        # Interactive
        #
        if fmt.lower() == "interactive":
            lines.append("pause mouse close")
        else:
            lines.append("set output")

        #
        # Write script
        #
        script_path = outfile.rsplit(".", 1)[0] + ".plt"

        with open(script_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        #
        # Execute gnuplot
        #
        try:

            if fmt.lower() == "interactive":
                subprocess.Popen(
                    ["gnuplot", "-persist", script_path],
                    cwd=plot_dir
                )

            else:
                subprocess.run(
                    ["gnuplot", script_path],
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
        #"""
        #plots : list[PlotDefinition]
        #"""

        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)

        lines = [
            "set encoding utf8",
            self._get_terminal_cmd(fmt, outfile),
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

            if fmt.lower() == "interactive":
                subprocess.Popen(
                    ["gnuplot", "-persist", script_path],
                    cwd=plot_dir
                )

            else:
                subprocess.run(
                    ["gnuplot", script_path],
                    check=True
                )

        finally:

            if fmt.lower() != "interactive":
                if os.path.exists(script_path):
                    os.remove(script_path)

        return outfile


    # 폰트 및 출력 형식 처리 로직 (create_script/create_multiplot_script 공통)
    # format 변수를 받아 {'pdf', 'png', 'svg', 'jpg', 'emf', 'eps'} 처리
    #def _get_terminal_cmd(self, fmt, outfile):
    #    # 폰트 설정: 'Malgun Gothic,11'
    #    font_cmd = "font 'Malgun Gothic,11'"
    #    if fmt == 'pdf': return f"set terminal pdfcairo {font_cmd} size 5,4"
    #    if fmt == 'emf': return f"set terminal emf {font_cmd} size 5,4"
    #    if fmt == 'svg': return f"set terminal svg {font_cmd} size 500,400"
    #    if fmt == 'png': return f"set terminal pngcairo {font_cmd} size 800,600"
    #    if fmt == 'jpg': return f"set terminal jpeg {font_cmd} size 800,600"
    #    if fmt == 'postscript': return f"set terminal postscript eps enhanced {font_cmd}" # 인쇄용 최고 화질'EPS'
    #    return ""

    def _get_terminal_cmd(self, fmt, outfile):

        fmt = fmt.lower()

        if fmt == "interactive":
            title = os.path.splitext(
                os.path.basename(outfile)
            )[0]
            return (
                f"set terminal qt enhanced "
                f"title '{title}' "
                f"font 'Malgun Gothic,11'"
            )

        elif fmt == "png":
            return (
                "set terminal pngcairo "
                "size 1600,900 enhanced "
                "font 'Malgun Gothic,11'"
            )

        elif fmt == "jpg":
            return (
                "set terminal jpeg "
                "size 1600,900 enhanced "
                "font 'Malgun Gothic,11'"
            )

        elif fmt == "svg":
            return (
                "set terminal svg enhanced "
                "font 'Malgun Gothic,11'"
            )

        elif fmt == "pdf":
            return (
                "set terminal pdfcairo enhanced "
                "color font 'Malgun Gothic,11' "
                "size 11.7in,8.3in"
            )

        elif fmt == "eps":
            return (
                "set terminal postscript eps enhanced "
                "color font 'Malgun Gothic,11'"
            )

        elif fmt == "emf":
            return (
                "set terminal emf enhanced "
                "font 'Malgun Gothic,11'"
            )

        else:
            raise ValueError(f"Unsupported output format : {fmt}")
