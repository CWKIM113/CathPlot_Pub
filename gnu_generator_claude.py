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
    #uses_y2: bool = False  #cwk add

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
        self.last_process = None

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

    _LINEBREAK_MARKER = "\x01"

    def _render_text(self, text):
        # (문자열, enhanced/noenhanced 키워드) 반환.
        # 실제 _{...}/^{...} 첨자 마크업이 있을 때만 enhanced를 켜고, 그 외의
        # 평범한 텍스트는 noenhanced로 완전히 리터럴 출력한다. noenhanced에서는
        # _, ^ 에 특수한 의미가 없어 이스케이프가 아예 필요 없으므로, qt/pdfcairo
        # 등 터미널마다 backslash+큰따옴표 처리 방식이 미묘하게 달라서 생기는
        # 불일치(예: PDF에서만 글자가 세로로 쌓이는 현상)를 원천적으로 피한다.
        # |가 파이프 문자라 title에 실제로 쓸 일이 거의 없어서 오히려 \n보다 타이핑하기 편하고 안전.
        # 마커에 밑줄(_)이 들어가 있어서 enhanced 모드( _{...} 같은 진짜 첨자가 같이 있는 문자열)일 때 
        # _sanitize()가 마커 자체를 건드려버리는 문제해결을 위해 마커를 특수문자 하나로 변경.

        text = (text or "").replace("|", self._LINEBREAK_MARKER)

        if self._has_enhanced_markup(text):
            rendered, mode = self._sanitize(text), "enhanced"
        else:
            safe = text.replace("\\", "\\\\").replace('"', '\\"')
            rendered, mode = safe, "noenhanced"

        rendered = rendered.replace(self._LINEBREAK_MARKER, "\\n")
        return rendered, mode

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

        uses_y2 = any(
            getattr(curve, "axis", "y1") == "y2"
            for curve in plotdef.curves
        )
              
        if not getattr(plotdef, "y2auto", True):
            lines.append(
                f"set y2range [{plotdef.y2min}:{plotdef.y2max}]"
            )
        elif uses_y2:
            lines.append("set autoscale y2")
        else:
            # y2 커브가 없으면 y1 범위를 그대로 따라가도록 링크한다 (gnuplot 내장 기능).
            # y1이 auto든 수동 지정이든 상관없이 항상 y1 범위와 동일하게 맞춰진다.
            lines.append("set link y2")

        lines.append(
            f"set xtics {plotdef.xtics if plotdef.xtics else 'auto'}"
        )

        lines.append(
            f"set ytics {plotdef.ytics if plotdef.ytics else 'auto'}"
        )

        # Minor Grid는 Major Grid가 켜져 있을 때만 유효하다 (major_grid=False면 무조건 False)
        effective_minor_grid = plotdef.minor_grid and getattr(plotdef, "major_grid", True)

        if plotdef.mxtics:
            lines.append(f"set mxtics {int(plotdef.mxtics)+1}")
        elif effective_minor_grid:
            lines.append("set mxtics 2")
        else:
            lines.append("unset mxtics")

        if plotdef.mytics:
            lines.append(f"set mytics {int(plotdef.mytics)+1}")
        elif effective_minor_grid:
            lines.append("set mytics 2")
        else:
            lines.append("unset mytics")

        if plotdef.my2tics:
            lines.append(f"set my2tics {int(plotdef.my2tics)+1}")
        elif effective_minor_grid:
            lines.append("set my2tics 2")
        else:
            lines.append("unset my2tics")

        #
        # Grid
        #
        grid_parts = []
        if getattr(plotdef, "major_grid", True):
            grid_parts += ["xtics", "ytics"]
        if effective_minor_grid:
            grid_parts += ["mxtics", "mytics"]

        if grid_parts:
            lines.append(f"set grid {' '.join(grid_parts)}")
        else:
            lines.append("unset grid")

        #
        # Mouse / Border
        #
        lines.append("set mouse")
        lines.append("set border lw 1.5")


        #
        # Annotations / Arrows
        #
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

        cmd_list = []
        #uses_y2 = False

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

            is_y2 = getattr(curve, "axis", "y1") == "y2"
            if is_y2:
                uses_y2 = True
            axis = "x1y2" if is_y2 else "x1y1"

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

            cmd_list.append(cmd)

        if not uses_y2 and cmd_list:
            cmd_list.append("NaN axes x1y2 notitle")

        for i, cmd in enumerate(cmd_list):
            if i != len(cmd_list) - 1:
                cmd += ", \\"
            lines.append(cmd)

        lines.append("")

        if is_multiplot:
            lines.append("unset label")
            lines.append("unset arrow")

        # -------------------------------------------------------------
        # [수정 위치] y2축(우측축) 눈금 및 경고 방지 설정
        # -------------------------------------------------------------
        # 개별 선(curve/line)들 중 우측 y2축을 사용하도록 체크된 항목이 있는지 확인합니다.
        # (객체 구조에 따라 curve.axis == "x1y2" 형태 등으로 확인 가능)
        #has_y2_data = any(
        #    getattr(curve, "axis", "x1y1") == "x1y2" or getattr(curve, "use_y2", False)
        #    for curve in getattr(plotdef, "curves", [])
        #)
        #
        #if has_y2_data:
        #    # [A] 실제로 y2 데이터를 사용하는 경우
        #    # 왼쪽 y1과 독립된 y2 고유의 눈금과 자동 범위를 적용합니다.
        #    lines.append("set y2tics")
        #    lines.append("set autoscale y2")
        #    lines.append("unset link") 
        #else:
        #    # [B] 일반적인 경우 (y2 데이터가 없을 때)
        #    # 오른쪽 축에 왼쪽 y1 눈금을 대칭(mirror)으로 표시하고,
        #    # 'range undefined' 경고를 완전히 차단하기 위해 스케일을 동기화시킵니다.
        #    lines.append("set y2tics mirror")
        #    lines.append("set link y2")
        ## -------------------------------------------------------------



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
                self.last_process = subprocess.Popen(
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

#    def create_multiplot_script(
#        self,
#        plots,
#        outfile,
#        fmt="pdf",
#        layout_option="Auto"
#    ):
#        plot_dir = os.path.dirname(os.path.abspath(outfile))
#        os.makedirs(plot_dir, exist_ok=True)
#
#        lines = [
#            "set encoding utf8",
#            self._get_terminal_cmd(fmt, outfile, plots[0] if plots else None),
#            f"set output '{outfile.replace(chr(92), '/')}'"
#        ]

    _A4_SIZES = {
        "portrait": ("8.27in", "11.69in"),
        "landscape": ("11.69in", "8.27in"),
    }

    def create_multiplot_script(
        self,
        plots,
        outfile,
        fmt="pdf",
        rows=None,
        cols=None,
        orientation="portrait",
        margins=(0.08, 0.94, 0.06, 0.94),   # left, right, bottom, top (screen 0~1)
        spacing=(0.09, 0.10)                # x, y spacing between subplots
    ):
        plot_dir = os.path.dirname(os.path.abspath(outfile))
        os.makedirs(plot_dir, exist_ok=True)

        nplot = len(plots)

        if not rows or not cols:  #why 3? cwk
            if nplot <= 1:
                rows, cols = 1, 1
            elif nplot == 2:
                rows, cols = 2, 1
                rows, cols = 2, 1
            elif nplot <= 4:
                rows, cols = 2, 2
            else:
                rows, cols = 3, 2

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
            lines.append(
                f"set multiplot layout {rows},{cols} "
                f"margins {l},{r},{b},{t} "
                f"spacing {sx},{sy}"
            )
        else:
            lines.append(f"set multiplot layout {rows},{cols}")

#        lines.append(f"set multiplot layout {rows},{cols}")
# 시작
#        # -------------------------------------------------------------
#        # [정밀 복원] 선택 레이아웃에 따른 행/열 및 마진(여백) 제어
#        # -------------------------------------------------------------
#        rows, cols = 1, 1
#        margin_cmds = []
#
#        if layout_option == "Auto":
#            # 전체 플롯 수에 맞추어 격자 크기를 자동 조율
#            n = len(plots)
#            if n <= 1:
#                rows, cols = 1, 1
#            elif n == 2:
#                rows, cols = 2, 1
#            elif n <= 4:
#                rows, cols = 2, 2
#            else:
#                rows, cols = 3, 2
# 여기부터?
#        elif layout_option == "1/p":
#            rows, cols = 1, 1
#            # 1페이지 한가운데 균형 있게 안착되도록 사방 여백을 넉넉히 설정
#            margin_cmds = [
#                "set lmargin at screen 0.15",
#                "set rmargin at screen 0.85",
#                "set tmargin at screen 0.85",
#                "set bmargin at screen 0.15"
#            ]
#
#        elif layout_option == "2/p (V)":
#            rows, cols = 2, 1  # 세로로 2개 배치
#            # 세로 배치 시 위아래 간격을 정교하게 제어하기 위해 기본 마진 적용
#
#        elif layout_option == "4/p (H)":
#            rows, cols = 2, 2  # 바둑판식 2x2 배치
#
#        elif layout_option == "6/p (V)":
#            rows, cols = 3, 2  # 세로가 긴 3행 2열 배치
#
#        else:
#            rows, cols = 1, 1
#
#        # 멀티플롯 모드 진입
#        lines.append(f"set multiplot layout {rows},{cols}")
#
#        # 개별 여백 명령어 주입 (1/p 옵션 등에서 작동)
#        if margin_cmds:
#            lines.extend(margin_cmds)
# 여기까지?

        # 수집된 개별 plotdef 사양을 순서대로 커맨드로 빌드하여 추가
        for plot in plots:
            self._build_plot_commands(
                plot,
                lines,
                is_multiplot=True,
                annotations=getattr(plot, "annotations", None),
                arrows=getattr(plot, "arrows", None),
            )

        lines.append("unset multiplot")
        # -------------------------------------------------------------

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
                self.last_process = subprocess.Popen(
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
                "PATH에 등록되어 있는지 확인하세요."
            )

        finally:
            if fmt.lower() != "interactive":
                if os.path.exists(script_path):
                    os.remove(script_path)

        return outfile

    def _get_terminal_cmd(self, fmt, outfile, plotdef=None, size_override=None):

        fmt = fmt.lower()

        # [보완 및 정밀 매핑 적용된 size_clause]
        def size_clause(default):
            if size_override:
                return f"size {size_override}"
            if plotdef is not None and not getattr(plotdef, "frame_auto", True):
                w = (getattr(plotdef, "frame_width", "") or "").strip()
                h = (getattr(plotdef, "frame_height", "") or "").strip()
                unit = (getattr(plotdef, "frame_unit", "in") or "in").strip()
                if w and h:
                    #if unit:
                    #    return f"size {w}{unit},{h}{unit} "
                    #else:
                    return f"size {w}{unit},{h}{unit}"
            return default

        if fmt == "interactive":
            title = os.path.splitext(
                os.path.basename(outfile)
            )[0]
            title = title.replace("_Temp", "") # "_Temp"를 제거하여 "PlotTitle_1" 형태로 깔끔하게 표시
            # 화면 출력 시에는 GUI의 final_frame_auto가 항상 True이므로 size_clause가 무시(기본 창 크기 적용)됩니다.
            return (
                f"set terminal qt enhanced "
                f"toolbar "
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
            # SVG는 기본 단위가 픽셀이므로 사용자가 지정한 물리 단위(in, cm)를 유지할 수 있도록 그대로 적용합니다.
            return (
                "set terminal svg enhanced "
                f"{size_clause('size 11.7in,8.3in')} " # 기본은 A4 landscape 비율
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
            
            