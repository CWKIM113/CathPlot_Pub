# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
import os

DEFAULT_COLORS = ["black", "red", "blue", "green", "magenta", "cyan", "orange", "brown", "purple", "gray"]
DEFAULT_LINESTYLES = ["solid", "dash", "dot", "dashdot", "shortdash", "dashdotdot"]
LINESTYLE_MAP = {"solid": 1, "dash": 2, "dot": 3, "dashdot": 4, "shortdash": 5, "dashdotdot": 6}

@dataclass
class CurveDefinition:
    dat_file: str
    output_no: int
    title: str
    time_shift: float = 0.0
    color: str | None = None
    linestyle: str | None = None
    linewidth: float = 2.0

@dataclass
class PlotDefinition:
    title: str = "CathPlot"
    xlabel: str = "Time (s)"
    ylabel: str = ""
    curves: list = field(default_factory=list)
    output_format: str = "Interactive"
    xauto: bool = True
    yauto: bool = True
    xmin: str = ""
    xmax: str = ""
    ymin: str = ""
    ymax: str = ""
    plot_id: int = 0
    xtics: str = ""
    ytics: str = ""
    mxtics: str = ""
    mytics: str = ""
    minor_grid: bool = False

    legend_box: bool = True
    legend_pos: str = "right top"
    title_font: str = "Malgun Gothic"
    title_size: str = "14"
    xlabel_font: str = "Malgun Gothic"
    xlabel_size: str = "11"
    ylabel_font: str = "Malgun Gothic"
    ylabel_size: str = "11"
    is_print_mode: bool = False

class GnuplotGenerator:

    #def __init__(self):
    #    self.use_default_colors = True
    #    self.use_default_styles = True
    #    self.custom_export_path = None
    def __init__(self, plot_dir=None):
        self.plot_dir = plot_dir # 전달받은 경로 저장
        self.use_default_colors = True
        self.use_default_styles = True
        self.custom_export_path = None

    def _sanitize(self, text):
        if not text:
            return ""
        result = []
        i, n = 0, len(text)
        while i < n:
            if text[i] == '_':
                if i + 1 < n and text[i+1] == '{': result.append('_')
                else: result.append('\\\\_')
            elif text[i] == '^':
                if i + 1 < n and text[i+1] == '{': result.append('^')
                else: result.append('\\\\^')
            else:
                result.append(text[i])
            i += 1
        return "".join(result)

    def _build_plot_commands(self, plotdef, lines, is_multiplot=False):
        lines.append("set size ratio 0.8") # 또는 set size ratio 0.8 or square
        lines.append("set origin 0,0")  # 원점을 고정

        if not plotdef.xauto: lines.append(f"set xrange [{plotdef.xmin.strip()}:{plotdef.xmax.strip()}]")
        else: lines.append("set xrange [*:*]")

        if not plotdef.yauto: lines.append(f"set yrange [{plotdef.ymin.strip()}:{plotdef.ymax.strip()}]")
        else: lines.append("set yrange [*:*]")

        if plotdef.xtics: lines.append(f"set xtics {plotdef.xtics}")
        else: lines.append("set xtics auto")

        if plotdef.ytics: lines.append(f"set ytics {plotdef.ytics}")
        else: lines.append("set ytics auto")

        if plotdef.mxtics:
            try: lines.append(f"set mxtics {int(plotdef.mxtics) + 1}")
            except ValueError: lines.append("unset mxtics")
        else: lines.append("unset mxtics")

        if plotdef.mytics:
            try: lines.append(f"set mytics {int(plotdef.mytics) + 1}")
            except ValueError: lines.append("unset mytics")
        else: lines.append("unset mytics")

        if plotdef.minor_grid: lines.append("set grid xtics ytics mxtics mytics")
        else: lines.append("set grid xtics ytics")

        lines.append("set mouse")
        lines.append("set border lw 1.5")

        f_scale = 1.4 if getattr(plotdef, 'is_print_mode', False) else 1.0
        t_sz = int(float(plotdef.title_size) * f_scale)
        x_sz = int(float(plotdef.xlabel_size) * f_scale)
        y_sz = int(float(plotdef.ylabel_size) * f_scale)

        lines.append(f'set title "{self._sanitize(plotdef.title)}" font "{plotdef.title_font},{t_sz}"')
        lines.append(f'set xlabel "{self._sanitize(plotdef.xlabel)}" font "{plotdef.xlabel_font},{x_sz}"')
        lines.append(f'set ylabel "{self._sanitize(plotdef.ylabel)}" font "{plotdef.ylabel_font},{y_sz}"')

        lg_box_str = "box" if plotdef.legend_box else "nobox"

        if plotdef.legend_pos == "outside right":
            pos_str = "outside right top"
        else:
            pos_str = f"inside {plotdef.legend_pos}"

        lines.append(
            f"set key enhanced {pos_str} {lg_box_str} "
            f"font \"{plotdef.xlabel_font},{int(9 * f_scale)}\" "
            f"samplen 3.0 vertical spacing 1.1 maxrows 10" #samplen=line style space
        )

        has_legend = any(c.title.strip() for c in plotdef.curves)
        if has_legend:
            lines.append("set lmargin 12")
            lines.append("set rmargin 18") # Legend용 오른쪽 여백
        else:
            lines.append("set lmargin 10")

        lines.append("plot \\")

        n = len(plotdef.curves)
        for i, curve in enumerate(plotdef.curves):
            if self.use_default_colors and curve.color is None:
                curve.color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]

            column = curve.output_no + 1

            # [핵심 변경] CWD가 src가 아닐 때 데이터 참조가 터지지 않도록 절대경로 맵핑 우선권 적용
            if os.path.isabs(curve.dat_file):
                gnu_file = curve.dat_file.replace("\\", "/")
            else:
                gnu_file = os.path.abspath(curve.dat_file).replace("\\", "/")

            lw_val = curve.linewidth * 1.5 if getattr(plotdef, 'is_print_mode', False) else curve.linewidth
            cmd = f'"{gnu_file}" using ($1+{curve.time_shift}):{column} title "{self._sanitize(curve.title)}" with lines lw {lw_val}'

            if curve.color: cmd += f' lc rgb "{curve.color}"'

            if self.use_default_styles and curve.linestyle is None:
                curve.linestyle = DEFAULT_LINESTYLES[i % len(DEFAULT_LINESTYLES)]

           # if curve.linestyle:
           #     dt = LINESTYLE_MAP[curve.linestyle]
           #     if isinstance(dt, str): cmd += f" dt {dt}"
           #     else: cmd += f" dt {dt}"
            if curve.linestyle and curve.linestyle in LINESTYLE_MAP:
                dt_val = LINESTYLE_MAP[curve.linestyle]
                cmd += f" dt {dt_val}"

            if i != n - 1: cmd += ", \\"
            lines.append(cmd)
        lines.append("")

    def create_script(self, plotdef, outfile):
        lines = []
        output_format = getattr(plotdef, "output_format", "Interactive")
        pid = getattr(plotdef, "plot_id", 0)

        lines.append("set encoding utf8")

        if self.custom_export_path:
            target_file = self.custom_export_path.replace("\\", "/")
        else:
            file_base = "".join([c for c in plotdef.title if c.isalnum() or c in ("_", "-")]).strip()
            if not file_base: file_base = "CathPlot_Result"
            # 기본 경로 계산 안전 보정
            #script_dir = os.path.dirname(os.path.abspath(__file__))
            #target_file = os.path.abspath(os.path.join(script_dir, f"../plot/{file_base}.pdf")).replace("\\", "/")

            # self.plot_dir을 우선 사용하도록 수정
            base_dir = self.plot_dir if self.plot_dir else os.path.dirname(os.path.abspath(__file__))
            # 수정: 하드코딩된 ../plot/ 대신 self.plot_dir 사용 (클래스 생성 시 전달받아야 함)
            target_file = os.path.abspath(os.path.join(base_dir, f"{file_base}.pdf")).replace("\\", "/")

        if output_format == "Interactive":
            clean_title = plotdef.title.replace("_", "\\_").replace('"', '\\"')
            lines.append(f"set terminal qt {pid} title \"{clean_title}_{pid}\" enhanced raise font \"{plotdef.title_font},10\"")
        elif output_format == "PNG":
            lines.append(f"set terminal pngcairo size 1200,800 enhanced font \"{plotdef.title_font},11\"")
            lines.append("set tmargin 8\nset bmargin 5\nset lmargin 12\nset rmargin 15")
            lines.append(f"set output '{target_file}'")
        elif output_format == "PDF":
            lines.append(f"set terminal pdfcairo size 7.5,5.0 enhanced font \"{plotdef.title_font},10\"")
            lines.append("set tmargin 6.5\nset bmargin 4.5\nset lmargin 11\nset rmargin 14")
            lines.append(f"set output '{target_file}'")
        elif output_format == "SVG":
            lines.append(f"set terminal svg size 1200,800 dynamic enhanced font \"{plotdef.title_font},11\"")
            lines.append("set tmargin 8\nset bmargin 5\nset lmargin 12\nset rmargin 15")
            lines.append(f"set output '{target_file}'")
        elif output_format == "JPG":
            lines.append(f"set terminal jpeg size 1200,800 enhanced font \"{plotdef.title_font},11\"")
            lines.append("set tmargin 8\nset bmargin 5\nset lmargin 12\nset rmargin 15")
            lines.append(f"set output '{target_file}'")
        elif output_format == "EMF":
            lines.append(f"set terminal emf color solid enhanced size 1024,768 \"{plotdef.title_font}\" 10")
            lines.append("set tmargin 8\nset bmargin 5\nset lmargin 12\nset rmargin 15")
            lines.append(f"set output '{target_file}'")

        self._build_plot_commands(plotdef, lines, is_multiplot=False)

        if output_format == "Interactive": lines.append("pause mouse close")
        else: lines.append("set output")

        with open(outfile, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def create_multiplot_script(self, plotdef_list, layout_option, outfile):
        lines = []
        lines.append("set encoding utf8")

        if self.custom_export_path: target_file = self.custom_export_path.replace("\\", "/")
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            target_file = os.path.abspath(os.path.join(script_dir, "../plot/Combined_Plots.pdf")).replace("\\", "/")

        ext = os.path.splitext(target_file)[1].lower().replace(".", "")
        num_plots = len(plotdef_list)
        pdef0 = plotdef_list[0]

        if layout_option == "2/p (Portrait)":
            rows, cols = 2, 1
            canvas_w, canvas_h = (7.5, 10.0) if ext in ("pdf", "eps") else (900, 1200)
        elif layout_option == "4/p (Landscape)":
            rows, cols = 2, 2
            canvas_w, canvas_h = (11.0, 8.0) if ext in ("pdf", "eps") else (1200, 900)
        elif layout_option == "6/p (Portrait)":
            rows, cols = 3, 2
            canvas_w, canvas_h = (9.0, 12.0) if ext in ("pdf", "eps") else (1000, 1300)
        else:
            if num_plots <= 1:
                rows, cols = 1, 1
                canvas_w, canvas_h = (7.5, 5.0) if ext in ("pdf", "eps") else (1000, 650)
            elif num_plots == 2:
                rows, cols = 2, 1
                canvas_w, canvas_h = (7.5, 10.0) if ext in ("pdf", "eps") else (900, 1200)
            elif num_plots <= 4:
                rows, cols = 2, 2
                canvas_w, canvas_h = (11.0, 8.0) if ext in ("pdf", "eps") else (1200, 900)
            else:
                rows, cols = 3, 2
                canvas_w, canvas_h = (9.0, 12.0) if ext in ("pdf", "eps") else (1000, 1300)

        if ext == "png": lines.append(f"set terminal pngcairo size {canvas_w},{canvas_h} enhanced font \"{pdef0.title_font},10\"")
        elif ext == "svg": lines.append(f"set terminal svg size {canvas_w},{canvas_h} dynamic enhanced font \"{pdef0.title_font},10\"")
        elif ext in ("jpg", "jpeg"): lines.append(f"set terminal jpeg size {canvas_w},{canvas_h} enhanced font \"{pdef0.title_font},10\"")
        elif ext == "emf": lines.append(f"set terminal emf portrait color solid enhanced size {canvas_w},{canvas_h} \"{pdef0.title_font}\" 9")
        else: lines.append(f"set terminal pdfcairo size {canvas_w},{canvas_h} enhanced font \"{pdef0.title_font},9.5\"")

        lines.append(f"set output '{target_file}'")
        lines.append(f"set multiplot layout {rows},{cols} columnsfirst rowsfirst")

        for pdef in plotdef_list:
            lines.append("set tmargin 7")
            lines.append("set bmargin 5")
            lines.append("set lmargin 12")
            lines.append("set rmargin 16")
            self._build_plot_commands(pdef, lines, is_multiplot=True)

        lines.append("unset multiplot")
        lines.append("set output")

        with open(outfile, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))