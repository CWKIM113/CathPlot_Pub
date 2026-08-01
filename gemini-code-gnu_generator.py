import os
import math
from dataclasses import dataclass, field
from typing import List

@dataclass
class CurveDefinition:
    path: str = ""
    x_col: int = 0
    y_col: int = 1
    axis: str = "Y1"          # "Y1" or "Y2"
    color: str = "blue"
    style: str = "lines"
    legend_mode: str = "Integrated (Default)"  # Integrated, Show Y1 Only, Show Y2 Only, Hide All
    title: str = ""

@dataclass
class PlotDefinition:
    curves: List[CurveDefinition] = field(default_factory=list)
    xlabel: str = "X"
    ylabel: str = "Y1"
    y2label: str = "Y2"
    xmin: str = ""
    xmax: str = ""
    ymin: str = ""
    ymax: str = ""
    
    # 레전드 설정
    legend_on: bool = True
    legend_pos: str = "right top"
    legend_custom_pos: bool = False
    legend_x: str = "0.8"
    legend_y: str = "0.8"
    legend_box: bool = True

class GnuplotGenerator:
    def __init__(self, plotdef: PlotDefinition):
        self.plotdef = plotdef

    def _nice_axis_range(self, values: List[float]):
        """전체 데이터 min, max를 기반으로 여유 공간과 범위 계산"""
        if not values:
            return None, None
        vmin = min(values)
        vmax = max(values)
        if vmin == vmax:
            vmin -= 1.0
            vmax += 1.0
        span = vmax - vmin
        margin = span * 0.05
        return vmin - margin, vmax + margin

    def _collect_column_data(self, file_path: str, col_idx: int) -> List[float]:
        """지정된 열(col_idx)의 유효한 숫자 데이터를 안전하게 수집 (col_no = 0 포함)"""
        values = []
        if not file_path or not os.path.exists(file_path):
            return values
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    if len(parts) > col_idx:
                        try:
                            val = float(parts[col_idx])
                            if math.isfinite(val):
                                values.append(val)
                        except ValueError:
                            continue
        except Exception:
            pass
        return values

    def _build_plot_commands(self) -> str:
        lines = []
        plotdef = self.plotdef

        lines.append("reset")
        lines.append('set terminal qt enhanced font "Sans,10"')
        lines.append('set mouse')
        # 마우스 이동 시 좌표를 콘솔에 출력하는 바인딩 추가
        lines.append('bind all \'Motion\' \'print "Cursor: x = ", sprintf("%.4f", MOUSE_X), ", y = ", sprintf("%.4f", MOUSE_Y)\'')

        lines.append(f'set xlabel "{plotdef.xlabel}"')
        lines.append(f'set ylabel "{plotdef.ylabel}"')
        if any(c.axis == "Y2" for c in plotdef.curves):
            lines.append('set y2tics')
            lines.append(f'set y2label "{plotdef.y2label}"')

        # Auto Range (전체 min, max 고려) 처리
        x_vals = []
        for curve in plotdef.curves:
            x_vals.extend(self._collect_column_data(curve.path, curve.x_col))
        
        if x_vals and not plotdef.xmin and not plotdef.xmax:
            xmin, xmax = self._nice_axis_range(x_vals)
            if xmin is not None:
                lines.append(f"set xrange [{xmin}:{xmax}]")
        elif plotdef.xmin or plotdef.xmax:
            lines.append(f"set xrange [{plotdef.xmin}:{plotdef.xmax}]")

        # 레전드(Key) 설정
        if plotdef.legend_on:
            box = "box linewidth 1.5" if plotdef.legend_box else "nobox"
            opaque = "opaque" if plotdef.legend_box else ""

            if plotdef.legend_custom_pos:
                pos = f"at graph {plotdef.legend_x}, {plotdef.legend_y}"
            elif plotdef.legend_pos == "outside right":
                pos = "outside right center"
            else:
                pos = f"inside {plotdef.legend_pos}"

            lines.append(f'set key enhanced {pos} {box} {opaque} samplen 2.5 spacing 1.2')
        else:
            lines.append("unset key")

        # Plot 명령어 구성
        plot_items = []
        for curve in plotdef.curves:
            if not curve.path or not os.path.exists(curve.path):
                continue
            
            # 레전드 모드 분기 (Hide All 또는 축별 전용 필터링)
            show_title = True
            if curve.legend_mode == "Hide All":
                show_title = False
            elif curve.legend_mode == "Show Y1 Only" and curve.axis != "Y1":
                show_title = False
            elif curve.legend_mode == "Show Y2 Only" and curve.axis != "Y2":
                show_title = False

            title_clause = f'title "{curve.title}"' if show_title and curve.title else 'notitle'
            using_expr = f"({curve.x_col + 1}):({curve.y_col + 1})"
            axis_clause = "axes x1y2" if curve.axis == "Y2" else "axes x1y1"
            
            item = f'"{curve.path}" using {using_expr} {axis_clause} with {curve.style} lc rgb "{curve.color}" {title_clause}'
            plot_items.append(item)

        if plot_items:
            lines.append("plot " + ", \\\n     ".join(plot_items))

        return "\n".join(lines)