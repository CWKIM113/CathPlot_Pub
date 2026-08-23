# -*- coding: utf-8 -*-

import tkinter as tk
import os
import subprocess
_NO_CONSOLE_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # taskkill 등 호출 시 콘솔 창이 깜빡이지 않도록
# [수정] creationflags만으로는 일부 Windows 환경에서 콘솔 창 숨김이 불완전하게
# 동작하는 경우가 있다는 PyInstaller 이슈가 확인됨 - STARTUPINFO(SW_HIDE)를
# 같이 지정해서 더 확실하게 숨긴다.
def _no_console_kwargs():
    kwargs = {"creationflags": _NO_CONSOLE_FLAG}
    if hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback
import time
import glob
import re
import uuid
import hashlib

from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import font as tkfont
from pathlib import Path

# [수정 - 요청] "창은 tkinter만 있으면 바로 뜰 수 있는데 무거운 게 다 로딩된
# 후에야 뜬다" - win32con/win32ui/win32api/win32print/pywintypes/pythoncom은
# 전부 PRINT 관련 함수(_pick_printer_dialog/_print_emf_and_cleanup/
# _print_and_cleanup)에서만 쓰이고 창을 띄우는 데는 전혀 필요 없는데, 예전엔
# 모듈 맨 위에서 즉시 import해서 메인 창이 뜨기 전에 매번 그 로딩 비용을
# 치렀음(실측: python -X importtime 기준 win32ui만 143ms, pywintypes
# 47ms, pythoncom 35ms, win32api 12ms - 합쳐서 cathplot_gui 전체 import
# 시간의 약 1/3). 실제 쓰는 함수 쪽으로 각각 지연 import를 옮겨서, 인쇄
# 기능을 한 번도 안 쓰면 이 비용 자체가 안 든다(기능은 완전히 동일 -
# win32gui는 실제로는 주석 처리된 죽은 코드에서만 참조돼 아예 삭제).

from data_parser import CathenaDatParser, save_json
from gnu_generator import PlotDefinition, CurveDefinition, GnuplotGenerator

# [추가] Batch Set/Queue - 항목마다 독립적인 gnuplot 프로세스를 순차로 하나씩
# 기다리던 것을 병렬로 처리해 속도를 높인다. "무제한 동시 실행"은 gnuplot
# 프로세스를 한꺼번에 너무 많이 띄워 메모리/핸들을 과하게 쓸 수 있어, CPU
# 코어 수 기준으로 적당히 상한을 둔다(최대 4개 - 대부분의 PC에서 안전한
# 선이면서도 순차 대비 체감 속도 개선은 확실함).
_BATCH_MAX_WORKERS = min(4, os.cpu_count() or 2)

COLOR_MAP = {
    "Auto": "",
    "Black": "black",
    "Red": "red",
    "Blue": "blue",
    "Green": "green",
    "Magenta": "magenta",
    "Cyan": "cyan",
    "Orange": "orange",
    "Brown": "brown",
    "Purple": "purple",
    "Gray": "gray",
}

STYLE_MAP = {
    "Auto": "",
    "Solid": "solid",
    "Dash": "dash",
    "Dot": "dot",
    "Dash-D": "dashdot",       # Dash-Dot (일점쇄선)
    "Short-Dash": "shortdash",
    "Dash-2D": "dashdotdot",  # Dash-Dot-Dot (이점쇄선)
}

# Marker(점 마커) 모양 - 표시 라벨 -> (속 빈 pointtype, 채운 pointtype)
# Cross/Star는 gnuplot에 채운/빈 구분이 따로 없어 동일값 사용
MARKER_SHAPE_MAP = {
    "None": (None, None),
    "Circle": (6, 7),
    "Square": (4, 5),
    "Triangle": (8, 9),
    "Tri-Down": (10, 11),
    "Diamond": (12, 13),
    "Cross": (1, 1),
    "Star": (3, 3),
}
MARKER_SHAPE_LIST = list(MARKER_SHAPE_MAP.keys())

# Marker 크기 - 표시 라벨 -> gnuplot pointsize 값
MARKER_SIZE_MAP = {
    "XS": 0.5,
    "S": 0.75,
    "M": 1.0,
    "L": 1.5,
    "XL": 2.0,
}
MARKER_SIZE_LIST = list(MARKER_SIZE_MAP.keys())

COLOR_LIST = list(COLOR_MAP.keys())
STYLE_LIST = list(STYLE_MAP.keys())

# [수정] "pm3d 옵션 이름을 'color palette' 또는 '입체채색'으로" - 내부적으로는
# gnu_generator.create_3d_script가 "pm3d" 문자열을 그대로 판별하므로 그대로 두고,
# 화면에 보여주는 표시명만 사용자가 알아보기 쉬운 이름으로 매핑한다.
STYLE_3D_DISPLAY_MAP = {
    "lines": "Lines",
    "points": "Points",
    "linespoints": "Linespoints",
    "pm3d": "Color Palette",
}
STYLE_3D_INTERNAL_MAP = {v: k for k, v in STYLE_3D_DISPLAY_MAP.items()}

class CathPlotGUI:

    def __init__(self, root):
        self.root = root
        self.root.title("CathPlot V1.0      by C.W.Kim @2026.08.18")
        # [수정] 노트북처럼 시스템 DPI가 다른 환경에서 초기 창이 작게 보인다는
        # 피드백으로 창 크기(아래 geometry)만 20% 키움
        self.root.geometry("1200x1030")
        self.root.tk.call('tk', 'windowingsystem')

        self.parser = CathenaDatParser()
        self.file_rows = []
        self.comment_list = []
        self.arrow_list = []
        self.circle_list = []

        self.selected_x_key = tk.StringVar(value="")
        self.prev_x_key = ""

        # X축 변수 재정렬용 임시파일 캐시: {(dat_file, x_output_no): 임시파일경로}
        self.sorted_dat_cache = {}

        # [추가] Batch Set/Queue 병렬화 대비 - resort_dat_file이 같은 정렬 캐시
        # 파일(sorted_filepath)에 대해 "존재 확인 -> 없으면 새로 쓰기"를 하는데,
        # 같은 dat 파일+X축을 쓰는 템플릿 여러 개가 동시에 처리되면 두 스레드가
        # 동시에 같은 파일에 써서 깨질 수 있음 - 파일 경로별로 잠금을 나눠서
        # (파일마다 다른 lock, 같은 파일끼리만 서로 기다림) 이 경쟁을 막는다.
        # _resort_locks 자체(dict)에 새 lock을 추가하는 순간도 여러 스레드가
        # 동시에 건드릴 수 있어 그 자체를 보호하는 작은 guard lock을 둔다.
        self._resort_locks = {}
        self._resort_locks_guard = threading.Lock()

        self.selected_y1_vars = {}
        self.selected_y2_vars = {}
        self.legend_vars = {}
        self.file_xshift_vars = {}  # 파일당 하나의 X Shift (그 파일의 모든 curve에 공통 적용)
        self.marker_shape_vars = {}   # key_str -> StringVar (기본 "None" - 마커 없음)
        self.marker_size_vars = {}    # key_str -> StringVar (기본 "M")
        self.marker_maxcount_vars = {}  # key_str -> StringVar (빈 문자열 = Auto)
        self.marker_fill_vars = {}      # key_str -> BooleanVar (기본 False = 속 빔)

        self.color_vars = {}
        self.linestyle_vars = {}
        self.linewidth_vars = {}
        self.legend_group_vars = {}
        self.in_legend1_vars = {}  # Legend1에 이 curve를 넣을지 (기본 전체 포함)

        self.active_entry = None
        self.last_opened_dir = None
        self.title_counters = {}
        self.multi_counters = {}
        self.active_plots_cache = {}
        self.plot_processes = []
        self.history_plots = []  # 멀티플롯 이력 바인딩용 배열 생성

        self.y1_title_auto = True
        self.y2_title_auto = True
        self.x_title_auto = True

        self._updating_y1 = False
        self._updating_y2 = False
        self._updating_x = False

        self.layout_var = tk.StringVar(value="Auto")  # 미선언으로 인한 에러 차단
        self.orientation_var = tk.StringVar(value="portrait")

        self.cwd = os.getcwd()
        self.plot_dir = os.path.join(self.cwd, "plot")
        self.warning_log_path = os.path.join(self.plot_dir, "cathplot_warnings.log")
        os.makedirs(self.plot_dir, exist_ok=True)

        self._setup_theme()
        self.create_widgets()
        self._warmup_proc = None  # [추가 - 버그 수정] 아래 _warmup_gnuplot 참고
        self.root.after(10, self.update_plot_file_list)
        self.root.after(50, self._warmup_gnuplot)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _setup_theme(self):
        # [추가] "CathPlot 화면을 채색 등을 고려해서 이쁘게 해달라" - 과학
        # 계산도구(CATHENA 열수력 데이터)라는 성격에 맞게 차분하지만 또렷한
        # "슬레이트 블루 + 앰버 포인트" 팔레트로 정리한다. Windows 기본 ttk
        # 테마(vista/xpnative)는 버튼 배경색을 대부분 무시하는 것으로 이미
        # 확인돼 있어서(아래 Batch Set/Queue 버튼이 tk.Button을 쓰는 이유 -
        # 기존 주석 참고), 배경색까지 확실히 반영되는 'clam' 테마로 바꾸고
        # 그 위에 팔레트를 입힌다. 폰트 크기는 그대로 둬서(키우면 목록에
        # 보이는 줄 수가 줄어드는 부작용이 있었음 - 위 geometry 주석 참고)
        # 색상/여백 중심으로만 다듬는다.
        self.PALETTE = {
            "bg": "#eef1f6",           # 창 전체 배경(옅은 슬레이트)
            "panel": "#f8f9fb",        # LabelFrame/입력 영역 배경
            "border": "#c7cddb",       # 테두리
            "text": "#1f2937",         # 기본 글자색
            "heading": "#2b3a67",      # LabelFrame 제목(진한 슬레이트 블루)
            "accent": "#3457a8",       # 주 강조색(PLOT 등 1차 동작)
            "accent_dark": "#26407e",
            "accent2": "#0e7c86",      # 보조 강조색(SAVE)
            "accent2_dark": "#0b626a",
            "accent3": "#7a4fb5",      # 보조 강조색(PRINT)
            "accent3_dark": "#623d92",
            "amber": "#c9791b",        # 포인트색(Multi Print/Save)
            "amber_dark": "#a5620f",
            "danger": "#b3462c",
            "danger_dark": "#8f3620",
            "secondary": "#5b6b8c",    # 보조 강조색(Curves/Marker/Browse/Clean Past Plots)
            "secondary_dark": "#48557a",
            "grey": "#8a94a6",         # Template Save/Load(회색 바탕)
            "grey_dark": "#6d7690",
            # [추가 - 요청] "Available Variables Selection을 붉은 계열로 - 아래
            # *.dat 헤드 색과 구분이 잘 안 됨" - danger(#b3462c, 갈색 계열 red)와는
            # 겹치지 않게 좀 더 선명한 빨강으로 새로 추가.
            "red": "#c0392b",
            "red_dark": "#a5301f",
        }
        pal = self.PALETTE
        self.root.configure(bg=pal["bg"])
        style = ttk.Style(self.root)
        # [되돌림] theme_use("clam")을 쓰면 Checkbutton/Radiobutton의 표시(indicator)
        # 크기가 Windows 기본 테마(vista)보다 작게 그려짐 - "radio, check box가
        # 작아졌다" + "Dat list의 X/Y1/Y2 헤더와 그 아래 라디오/체크박스 열이
        # 안 맞는다"는 두 증상 모두 이 때문(라디오/체크 크기가 vista 기준으로
        # 맞춰 놓은 헤더 폭과 어긋남). 색상 버튼은 이미 전부 tk.Button으로
        # 바꿔서 clam이 필요 없으므로, 테마 전환은 하지 않고 기본 테마 위에
        # 색상/폰트만 얹는다.
        style.configure(".", background=pal["bg"], foreground=pal["text"])
        style.configure("TFrame", background=pal["bg"])
        style.configure("TLabel", background=pal["bg"], foreground=pal["text"])
        style.configure(
            "TLabelframe", background=pal["panel"], bordercolor=pal["border"],
            relief="groove",
        )
        style.configure(
            "TLabelframe.Label", background=pal["bg"], foreground=pal["heading"],
            font=("Malgun Gothic", 9, "bold"),
        )
        # [추가] "각 구역(block)의 Title을 다른 색으로 구분, box line 색도"
        # - 기존엔 모든 LabelFrame(DAT Files/Plot Setting/Multi Annotations 등)
        # 제목이 전부 같은 색(heading)이라 화면을 훑어볼 때 구역 경계가 잘
        # 안 드러났음. 이미 있는 팔레트(버튼에 쓰는 것과 같은 색 계열이라
        # "슬레이트 블루+앰버 포인트" 톤이 유지됨)에서 구역마다 하나씩
        # 배정해서, 제목 글자색과 테두리색을 함께 그 색으로 물들인다(완전히
        # 새 색을 추가하지 않고 버튼 팔레트를 재사용해 전체 화면 톤을
        # 통일감 있게 유지).
        def _section_style(name, color):
            style.configure(
                f"{name}.TLabelframe", background=pal["panel"], bordercolor=color,
                relief="groove", borderwidth=2,
            )
            style.configure(
                f"{name}.TLabelframe.Label", background=pal["bg"], foreground=color,
                font=("Malgun Gothic", 9, "bold"),
            )
            return f"{name}.TLabelframe"

        self.SECTION_STYLE = {
            "dat_files": _section_style("DatFiles", pal["accent"]),
            "variables": _section_style("Variables", pal["red"]),
            "plot_setting": _section_style("PlotSetting", pal["accent3"]),
            "annotations": _section_style("Annotations", pal["amber"]),
            "advanced": _section_style("Advanced", pal["danger"]),
        }
        style.configure("TCheckbutton", background=pal["bg"], foreground=pal["text"])
        style.configure("TRadiobutton", background=pal["bg"], foreground=pal["text"])
        style.configure("TNotebook", background=pal["bg"])
        style.configure("TNotebook.Tab", background=pal["panel"], foreground=pal["text"], padding=(10, 4))
        style.map("TNotebook.Tab", background=[("selected", pal["accent"])], foreground=[("selected", "white")])
        style.configure(
            "TButton", background=pal["panel"], foreground=pal["text"],
            bordercolor=pal["border"], focusthickness=1, padding=4,
        )
        style.map("TButton", background=[("active", "#e3e7ef")])
        # [추가] "Browse/Annotation 줄의 X(삭제) 버튼이 너무 높아 보임" - 기본
        # TButton padding(4)이 옆의 Entry/Combobox보다 위아래로 두꺼워서, 그
        # 버튼이 포함된 줄 전체 높이가 늘어나 줄 사이 간격도 커 보이는
        # 원인이었음. X 버튼 전용으로 위아래 padding을 최소화한 스타일을
        # 따로 둔다(가로 폭은 기존 width=2/3 그대로 유지 - "크게 하지 말
        # 것"이므로 폭은 안 건드림).
        style.configure("Compact.TButton", padding=(4, 0))
        # [수정 - 요청] "각 block 내 입력 box에 color line" - 입력칸 테두리를
        # 눈에 띄는 강조색 계열로(중립 회색 대신). ttk TEntry의 bordercolor는
        # Windows 기본(vista/winnative) 테마에서 반영이 안 되는 조합이 있을 수
        # 있음(이 파일에서 버튼 배경색이 같은 이유로 ttk를 포기하고 tk.Button
        # 으로 바꾼 전례가 있음) - 우선 style만 바꿔보고, 실제 화면에서 안
        # 보이면 tk.Entry(highlightthickness 기반)로 교체가 필요함.
        style.configure("TEntry", fieldbackground="white", bordercolor=pal["accent"], focuscolor=pal["accent"])
        style.configure("TCombobox", fieldbackground="white", background=pal["panel"], bordercolor=pal["accent"])

        # [추가] 주요 동작 버튼(PLOT/SAVE/PRINT/Multi Print/Save)용 강조 스타일 -
        # 각각 다른 강조색을 둬서 한눈에 구분되게 한다(Batch Set/Queue의
        # 기존 초록색과도 겹치지 않는 팔레트로 골랐음).
        def _accent_style(name, base, active):
            style.configure(
                name, background=base, foreground="white",
                bordercolor=base, focusthickness=1, padding=6,
                font=("Malgun Gothic", 9, "bold"),
            )
            style.map(name, background=[("active", active), ("pressed", active)])

        _accent_style("Plot.Accent.TButton", pal["accent"], pal["accent_dark"])
        _accent_style("Save.Accent.TButton", pal["accent2"], pal["accent2_dark"])
        _accent_style("Print.Accent.TButton", pal["accent3"], pal["accent3_dark"])
        _accent_style("Multi.Accent.TButton", pal["amber"], pal["amber_dark"])
        _accent_style("Danger.Accent.TButton", pal["danger"], pal["danger_dark"])

        # [추가] "Setting 앞부분의 title(Plot Title 등)들을 bold/글자색으로" -
        # ttk.Label의 foreground/font는 ttk.Button의 background와 달리 Windows
        # 기본 테마에서도 대체로 잘 반영되는 편이라 ttk 스타일로 처리한다.
        style.configure(
            "RowHead.TLabel", background=pal["bg"], foreground=pal["heading"],
            font=("Malgun Gothic", 9, "bold"),
        )

    def _mk_btn(self, parent, text, command, color="secondary", fg="white", **pack_kw):
        # [추가] "Curves/Marker/Browse/Template/Clean Past Plots 버튼도
        # 구별·강조" - ttk.Button은 배경색이 잘 안 먹는 환경이 확인돼서, 색을
        # 주는 모든 버튼을 이 헬퍼(tk.Button 기반)로 통일한다. color는
        # self.PALETTE의 키 이름(예: "secondary", "amber", "accent")이고,
        # 그 키+"_dark"가 hover/눌림 색으로 자동 쓰인다.
        pal = self.PALETTE
        bg = pal.get(color, pal["secondary"])
        dark = pal.get(color + "_dark", bg)
        # [수정] "Browse/Curves/Marker 등 색 버튼이 입력줄(Entry)보다 너무 높아
        # 보임" - bd=2(3D 입체 테두리)와 기본 내부 pady가 합쳐져 옆 Entry/
        # Combobox보다 눈에 띄게 두꺼워 보였음. bd를 1로, pady를 명시적으로
        # 작게 줘서 줄 높이를 옆 위젯들과 비슷하게 맞춘다(버튼 자체 크기/
        # 강조색은 그대로 유지 - "크게 하지 말 것"이지 "작게 하지 말 것"은
        # 아니므로 폭(padx)은 건드리지 않음).
        # [수정 - 요청] "Browse 버튼도 X버튼(Compact.TButton, padding=(4,0))과
        # 같은 높이로, DAT File 줄 사이 간격도 최소화" - pady=1도 여전히
        # X버튼(ttk, 세로 padding 0)보다 살짝 높아 줄 전체 높이가 그만큼
        # 커 보였음 - pady를 0으로 더 줄인다(bd=1은 테두리 표시를 위한
        # 최소값이라 더 줄이지 않음). DAT File 행 자체는 이미 pady=0으로
        # 붙어 있어서(add_file_row), 버튼 높이가 줄어드는 만큼 행 사이
        # 간격도 그만큼 줄어듦.
        b = tk.Button(
            parent, text=text, command=command,
            font=("Malgun Gothic", 9, "bold"), bg=bg, fg=fg,
            activebackground=dark, activeforeground=fg,
            relief="raised", bd=1, padx=8, pady=0,
        )
        b.pack(**pack_kw)
        return b

    def _get_check_images(self, color="accent", size=15):
        # [추가 - 근본 원인 수정] "체크박스 20곳을 강조색으로 통일했더니 체크
        # 표시(흰 체크마크)가 안 보이고 그냥 색칠된 상자만 보임" - 기존
        # selectcolor 방식은 Windows의 네이티브 체크박스 인디케이터 테마가
        # "상자를 채우는 색"과 "체크마크를 그리는 색"을 어떻게 조합할지 전부
        # OS 테마에 맡기는데, 이미 한 번(주석 참고) 테마별로 selectcolor 전환
        # 자체가 안 먹는 문제를 겪었을 만큼 신뢰할 수 없음 - 대신 PIL로 상자+
        # 체크마크를 직접 그린 비트맵 두 장(선택/미선택)을 만들어 image/
        # selectimage로 넘기고 indicatoron=False로 네이티브 인디케이터를 완전히
        # 대체한다(테마 영향을 전혀 안 받음, 항상 동일하게 보장됨). color별로
        # 한 번만 만들어 캐시(self._check_img_cache)에 재사용.
        # [수정 - 요청] "Var list의 Y1/Y2 체크박스 크기를 이전처럼 키워줘요" - size를
        # 호출부에서 지정할 수 있게 파라미터화(기본 15 유지, 캐시 키에 size도
        # 포함해서 크기별로 따로 캐시).
        cache_key = (color, size)
        if not hasattr(self, "_check_img_cache"):
            self._check_img_cache = {}
        if cache_key in self._check_img_cache:
            return self._check_img_cache[cache_key]

        from PIL import Image, ImageDraw, ImageTk

        pal = self.PALETTE
        fill_color = pal.get(color, pal["accent"])
        border_color = pal.get(color + "_dark", pal["border"])
        scale = 4  # 안티앨리어싱 흉내 - 크게 그린 뒤 축소
        big = size * scale

        def _box(fill, outline):
            im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            m = scale  # 여백
            d.rounded_rectangle([m, m, big - 1 - m, big - 1 - m], radius=2 * scale, fill=fill, outline=outline, width=scale)
            return im

        unchecked_im = _box("white", pal["border"])
        checked_im = _box(fill_color, border_color)
        # 체크마크(흰색 굵은 선, 짧은 다운스트로크 + 긴 업스트로크)
        d = ImageDraw.Draw(checked_im)
        pts = [(big * 0.22, big * 0.52), (big * 0.42, big * 0.72), (big * 0.78, big * 0.28)]
        d.line(pts, fill="white", width=int(scale * 1.6), joint="curve")
        unchecked_im = unchecked_im.resize((size, size), Image.LANCZOS)
        checked_im = checked_im.resize((size, size), Image.LANCZOS)

        imgs = (ImageTk.PhotoImage(unchecked_im), ImageTk.PhotoImage(checked_im))
        self._check_img_cache[cache_key] = imgs
        return imgs

    def _mk_check(self, parent, text, variable, color="accent", command=None, no_pack=False, size=15, bold=False, **pack_kw):
        # [추가] "Auto X Range 등 체크박스 체크시 색상도 넣어 강조" - color는
        # self.PALETTE의 키 이름. bg는 부모(ttk.Frame 등)와 어울리도록 앱 배경색으로
        # 맞추고, 테두리는 없앤다(Windows 기본 tk.Checkbutton의 두꺼운 포커스
        # 테두리가 이질적으로 보이는 것을 방지).
        # [수정 - 근본 원인 수정] "체크(강조색) 상태에서 흰 체크마크가 안 보임" -
        # selectcolor(OS 테마에 맡기는 방식) 대신 _get_check_images로 직접 그린
        # 비트맵(상자+흰 체크마크)을 image/selectimage로 지정하고
        # indicatoron=False로 네이티브 인디케이터를 대체한다 - 테마와 무관하게
        # 항상 동일하게 보장됨.
        pal = self.PALETTE
        img_unchecked, img_checked = self._get_check_images(color, size=size)
        _font = ("Malgun Gothic", 9, "bold") if bold else ("Malgun Gothic", 9)
        c = tk.Checkbutton(
            parent, text=text, variable=variable, command=command,
            bg=pal["bg"], activebackground=pal["bg"], fg=pal["text"], font=_font,
            image=img_unchecked, selectimage=img_checked, indicatoron=False,
            compound="left", highlightthickness=0, bd=0, relief="flat",
            selectcolor=pal["bg"],
        )
        # PhotoImage는 참조가 없으면 GC돼서 사라지므로 위젯에 직접 붙여서 유지
        c._img_unchecked = img_unchecked
        c._img_checked = img_checked
        if not no_pack:
            c.pack(**pack_kw)
        return c

    def _mk_entry(self, parent, textvariable, width=10, color="accent"):
        # [추가 - 근본 원인 수정] "Plot Setting/Multi Annotations/Advanced의
        # 입력 box에 커서를 눌러도 테두리 색 구분이 안 됨" - ttk.Entry의
        # bordercolor는 Windows 기본(vista) 테마가 자체 테두리를 그리고 이
        # 스타일 속성을 무시해서(이 파일에서 버튼/체크박스가 같은 이유로
        # ttk를 포기한 전례와 동일한 문제) 반영이 안 됨 - tk.Entry(테마와
        # 무관하게 항상 동작하는 highlightbackground/highlightcolor)로
        # 교체한다. color는 self.PALETTE의 키 이름(그 입력칸이 속한 구역의
        # 제목색과 맞추면 어느 block 소속인지도 한눈에 드러남).
        pal = self.PALETTE
        line = pal.get(color, pal["accent"])
        return tk.Entry(
            parent, textvariable=textvariable, width=width, bg="white", fg=pal["text"],
            relief="flat", highlightthickness=1, highlightbackground=line, highlightcolor=line,
        )

    def create_widgets(self):
        self.file_frame = ttk.LabelFrame(self.root, text="DAT Files", style=self.SECTION_STYLE["dat_files"])
        self.file_frame.pack(fill="x", padx=10, pady=0)

        self.file_canvas = tk.Canvas(self.file_frame, height=85, width=120)
        self.file_scrollbar = ttk.Scrollbar(
            self.file_frame, orient="vertical", command=self.file_canvas.yview
        )
        self.file_scrollable_frame = ttk.Frame(self.file_canvas)

        self.file_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.file_canvas.configure(
                scrollregion=self.file_canvas.bbox("all")
            )
        )
        self.file_canvas.create_window(
            (0, 0), window=self.file_scrollable_frame, anchor="nw"
        )
        self.file_canvas.configure(yscrollcommand=self.file_scrollbar.set)

        self.file_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=0)
        self.file_scrollbar.pack(side="right", fill="y")

        self.add_file_btn = ttk.Button(
            self.file_frame, text="+", width=3, command=self.add_file_row
        )
        self.add_file_btn.pack(side="right", padx=5, pady=0)

        btn_container = ttk.Frame(self.root)
        btn_container.pack(fill="x", padx=10, pady=0)

        # [수정] "오메가 표식을 눈에 확 띄게" - ttk.Button은 Windows 기본
        # 테마에서 배경색이 잘 안 먹혀서(clam 테마로 바꿔도 사용자 확인상
        # 눈에 띄는 변화가 없었음), Batch Set/Queue와 동일하게 확실히 색이
        # 반영되는 tk.Button으로 바꾸고 크고 굵게 키운다.
        self.var_symbol_btn = tk.Button(
            btn_container, text=chr(937), width=3,
            font=("Malgun Gothic", 13, "bold"),
            bg=self.PALETTE["amber"], fg="white",
            activebackground=self.PALETTE["amber_dark"], activeforeground="white",
            relief="raised", bd=2,
            command=self.open_permanent_symbol_window
        )
        self.var_symbol_btn.pack(side="right", padx=5, pady=2)

        # [수정] "Batch Set이 많이 쓰일 테니까" - Batch Set <-> Batch Queue 위치 교체
        # (Batch Set을 먼저/왼쪽에), 둘 다 색상+굵은 글씨로 강조. 3D-PLOT은 줄
        # 가운데에 위아래 간격 없이 꽉 차는 더 큰 버튼으로 강조(ttk 대신 tk.Button을
        # 써야 Windows에서도 배경색이 실제로 적용됨).
        _emph_font = ("Malgun Gothic", 10, "bold")

        batch_set_btn = tk.Button(
            btn_container, text="Batch Set", command=self.open_batch_set_dialog,
            font=_emph_font, bg="#2e7d32", fg="white",
            activebackground="#256428", activeforeground="white",
            relief="raised", padx=10,
        )
        batch_set_btn.pack(side="left", padx=5, pady=2)

        batch_queue_btn = tk.Button(
            btn_container, text="Batch Queue", command=self.open_batch_queue_dialog,
            font=_emph_font, bg="#2e7d32", fg="white",
            activebackground="#256428", activeforeground="white",
            relief="raised", padx=10,
        )
        batch_queue_btn.pack(side="left", padx=5, pady=2)

        # [수정] "Template 글자를 흰색으로, 3D Template와 색상 통일" - 기존
        # #1f2937(짙은 남색) 텍스트를 다른 버튼들과 동일하게 흰색으로 바꾸고,
        # 아래 3D Template Save/Load(4231행 부근)도 같은 grey 팔레트로
        # 맞춘다(기존엔 amber를 썼는데, amber는 Multi Print/Save 전용 강조색이라
        # 의미가 겹쳤음).
        self._mk_btn(btn_container, "Template Save", self.save_template,
                     color="grey", fg="white", side="left", padx=5)
        self._mk_btn(btn_container, "Template Load", self.load_template,
                     color="grey", fg="white", side="left", padx=5)

        # [수정] "좌우로 늘리지 말고 줄 중앙에 배치" - fill+expand로 버튼 자체가
        # 늘어졌던 걸, 양옆에 빈 스페이서(expand=True)를 둬서 버튼 크기는
        # 그대로 두고 남는 공간의 중앙에 오도록 바꿈(세로 크기는 font/pady로
        # 키운 것 그대로 유지).
        tk.Frame(btn_container).pack(side="left", fill="x", expand=True)
        plot3d_btn = tk.Button(
            btn_container, text="3D-PLOT", command=self.open_3d_plot_dialog,
            font=("Malgun Gothic", 11, "bold"), bg="#1565c0", fg="white",
            activebackground="#0d4c96", activeforeground="white",
            relief="raised", padx=14, pady=4,
        )
        plot3d_btn.pack(side="left")
        tk.Frame(btn_container).pack(side="left", fill="x", expand=True)

        self.var_frame = ttk.LabelFrame(self.root, text="Available Variables Selection", style=self.SECTION_STYLE["variables"])
        self.var_frame.pack(fill="x", expand=False, padx=10, pady=0)

        self.canvas = tk.Canvas(self.var_frame, height=290)
        self.scrollbar = ttk.Scrollbar(
            self.var_frame, orient="vertical", command=self.canvas.yview
        )
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )
        self.canvas.create_window(
            (0, 0), window=self.scrollable_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.plot_container = ttk.LabelFrame(self.root, text="Plot Setting", style=self.SECTION_STYLE["plot_setting"])
        self.plot_container.pack(fill="x", padx=10, pady=0)

        self.plot_canvas = tk.Canvas(self.plot_container, height=330, highlightthickness=0)
        self.plot_canvas.pack(side="left", fill="both", expand=True)

        self.plot_scrollbar = ttk.Scrollbar(self.plot_container, orient="vertical", command=self.plot_canvas.yview)
        self.plot_scrollbar.pack(side="right", fill="y")
        self.plot_canvas.configure(yscrollcommand=self.plot_scrollbar.set)

        self.plot_frame = ttk.Frame(self.plot_canvas)
        self.canvas_window = self.plot_canvas.create_window((0, 0), window=self.plot_frame, anchor="nw")

        self.plot_frame.bind(
            "<Configure>",
            lambda e: self.plot_canvas.configure(scrollregion=self.plot_canvas.bbox("all"))
        )
        self.plot_canvas.bind(
            "<Configure>",
            lambda e: self.plot_canvas.itemconfig(self.canvas_window, width=e.width)
        )

        self.title_var = tk.StringVar(value="Plot Title")
        self.xlabel_var = tk.StringVar(value="")
        self.ylabel_var = tk.StringVar(value="")
        self.y2label_var = tk.StringVar(value="")

        self.xauto_var = tk.BooleanVar(value=True)
        self.yauto_var = tk.BooleanVar(value=True)
        self.y2auto_var = tk.BooleanVar(value=True)

        self.legend_on_var = tk.BooleanVar(value=True)
        self.legend_box_var = tk.BooleanVar(value=True)
        self.legend_pos_var = tk.StringVar(value="right top")
        # [추가] 기존엔 legend 안 샘플선/title의 좌/우 정렬이 pos의 x값(50% 기준)으로만
        # 자동 결정됐는데, 그 기준과 다르게 정렬하고 싶다는 요청으로 명시 선택지를
        # 추가한다. "Auto"면 기존 방식(x>=50%면 우측 정렬) 그대로 유지.
        self.legend_align_var = tk.StringVar(value="Auto")
        self.legend_thick_var = tk.StringVar(value="1.5")  # legend box 테두리 두께
        self.legend_font_var = tk.StringVar(value="Malgun Gothic")  # Legend 전용 폰트(Comment도 같이 씀)
        self.legend_size_var = tk.StringVar(value="9")  # Legend 전용 크기(Comment도 같이 씀)
        # [추가] "자동 추정이 안 맞는 경우만 사용자 입력(axis 대비 %)으로 직접
        # 지정" - 비워두면(기본) 기존처럼 폰트 기반 자동 추정을 그대로 쓰고,
        # 값을 넣으면(axis width/height 대비 %) 그 크기로 고정한다. Print/
        # Save처럼 포맷별 렌더링 차이로 자동 추정이 어긋나는 경우의 예외
        # 처리용이라 평소엔 비워두는 게 기본.
        self.legend_box_width_pct_var = tk.StringVar(value="")
        self.legend_box_height_pct_var = tk.StringVar(value="")

        # Legend2 (보조 legend box) - 기본은 꺼져 있음
        self.legend2_on_var = tk.BooleanVar(value=False)
        self.legend2_box_var = tk.BooleanVar(value=True)
        self.legend2_pos_var = tk.StringVar(value="right bottom")
        self.legend2_align_var = tk.StringVar(value="Auto")  # Legend1과 동일한 개념(Align 참고)
        self.legend2_box_width_pct_var = tk.StringVar(value="")   # Legend1과 동일한 개념(Box W/H% 참고)
        self.legend2_box_height_pct_var = tk.StringVar(value="")

        self.title_font_var = tk.StringVar(value="Malgun Gothic")
        self.title_size_var = tk.StringVar(value="14")
        self.xlabel_font_var = tk.StringVar(value="Malgun Gothic")
        self.xlabel_size_var = tk.StringVar(value="11")
        # X/Y1/Y2 축 제목은 공용 폰트+크기를 씀 (X 것을 그대로 공유) - 별도
        # 입력칸을 없애고 X 줄의 것 하나로 통일
        self.ylabel_font_var = self.xlabel_font_var
        self.ylabel_size_var = self.xlabel_size_var
        self.y2label_font_var = self.xlabel_font_var
        self.y2label_size_var = self.xlabel_size_var

        font_list = ["Malgun Gothic", "Arial", "Times New Roman", "Courier New", "Consolas"]
        size_list = ["6", "8", "9", "10", "11", "12", "14", "16", "18", "20"]
        thick_list = ["0.8","1.0","1.2","1.5","2.0","2.5","3.0","4.0"]
        pos_list = ["right top", "right bottom", "left top", "left bottom", "center top", "center bottom", "center center", "outside right"]

        # Row 0
        ttk.Label(self.plot_frame, text="Plot Title", style="RowHead.TLabel").grid(row=0, column=0, padx=5, pady=0, sticky="w")
        self.title_entry = self._mk_entry(self.plot_frame, self.title_var, width=30, color="accent3")
        self.title_entry.grid(row=0, column=1, padx=5, pady=0, sticky="w")
        self.title_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.title_entry))

        t_font_frame = ttk.Frame(self.plot_frame)
        t_font_frame.grid(row=0, column=2, padx=(5, 0), pady=0, sticky="w")
        ttk.Combobox(t_font_frame, textvariable=self.title_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(t_font_frame, textvariable=self.title_size_var, values=size_list, width=2, state="readonly").pack(side="left", padx=2)

        def _add_legend_pos_hint(combo):
            def _show(event):
                tw = tk.Toplevel(combo)
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 8}")
                tk.Label(
                    tw, text="프리셋 선택 또는 좌표 직접 입력 가능\n예: 70,90 (X,Y 0~100%, annotation과 동일)\n고급: graph 0.7,0.9 / screen 0.5,0.95",
                    background="#ffffe0", relief="solid", borderwidth=1, font=("Consolas", 9),
                    padx=4, pady=2, justify="left"
                ).pack()
                combo._hint_win = tw
            def _hide(event):
                if getattr(combo, "_hint_win", None) is not None:
                    combo._hint_win.destroy()
                    combo._hint_win = None
            combo.bind("<Enter>", _show)
            combo.bind("<Leave>", _hide)

        # [추가] "Legend box 크기 직접 입력칸은 screen용이 아님을 팝업으로
        # 알려달라" - _add_legend_pos_hint와 같은 마우스오버 툴팁 패턴을
        # 위젯 종류에 상관없이 재사용할 수 있게 일반화한 버전.
        def _add_hint(widget, text):
            def _show(event):
                tw = tk.Toplevel(widget)
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 8}")
                tk.Label(
                    tw, text=text, background="#ffffe0", relief="solid", borderwidth=1,
                    font=("Consolas", 9), padx=4, pady=2, justify="left"
                ).pack()
                widget._hint_win = tw
            def _hide(event):
                if getattr(widget, "_hint_win", None) is not None:
                    widget._hint_win.destroy()
                    widget._hint_win = None
            widget.bind("<Enter>", _show)
            widget.bind("<Leave>", _hide)

        # --- Legend1 줄 (Plot Title 줄 우측) ---
        legend1_row = ttk.Frame(self.plot_frame)
        legend1_row.grid(row=0, column=3, columnspan=3, padx=3, pady=0, sticky="we")
        self._mk_check(legend1_row, "Legend1 On", self.legend_on_var, side="left", padx=3)
        self._mk_check(legend1_row, "Box", self.legend_box_var, side="left", padx=3)
        ttk.Label(legend1_row, text="Pos1:").pack(side="left", padx=2)
        legend_pos_combo = ttk.Combobox(legend1_row, textvariable=self.legend_pos_var, values=pos_list, width=10)
        legend_pos_combo.pack(side="left", padx=2)
        _add_legend_pos_hint(legend_pos_combo)
        ttk.Label(legend1_row, text="Align:").pack(side="left", padx=(4, 1))
        ttk.Combobox(legend1_row, textvariable=self.legend_align_var, values=["Auto", "Left", "Right"],
                     width=5, state="readonly").pack(side="left", padx=1)
        # [추가] "자동 추정이 안 맞을 때만 쓰는 Legend box 크기 직접 입력(axis
        # 대비 %) - 비우면 기존처럼 자동" - 위치 입력칸(Pos1/Align) 바로
        # 옆에 배치. Print/Save 전용(화면엔 적용 안 됨)임을 마우스오버
        # 팝업으로 알려준다.
        # [수정 - 요청] "Box W/H%에서 %가 이상함(항상 %인 것처럼 보이는데 실제로는
        # 숫자만 넣으면 좌표값 차이, %를 붙여야 비율)" - 라벨을 실제 동작(둘 다
        # 가능)에 맞게 "%"를 빼고 "Box W/H:"로 표기(자세한 규칙은 마우스오버
        # 힌트에 이미 있음).
        ttk.Label(legend1_row, text="Box W/H:").pack(side="left", padx=(4, 1))
        _l1_boxw_entry = self._mk_entry(legend1_row, self.legend_box_width_pct_var, width=4, color="accent3")
        _l1_boxw_entry.pack(side="left", padx=1)
        _l1_boxh_entry = self._mk_entry(legend1_row, self.legend_box_height_pct_var, width=4, color="accent3")
        _l1_boxh_entry.pack(side="left", padx=1)
        _box_size_hint = ("Print/Save 전용(화면 미리보기엔 적용 안 됨)\n"
                           "비우면 폰트 기준 자동 추정(기본) - 자동 추정이\n"
                           "안 맞을 때만 직접 지정\n"
                           "숫자만: X/Y 데이터 좌표값 차이(인터랙티브 창에서\n"
                           "  커서로 읽은 값 참고- 예: 200)\n"
                           "%로 끝나면: axis 대비 비율 - 예: 30%\n"
                           "(좌표값은 axis 범위가 나중에 바뀌면 비율도 같이 바뀜)")
        _add_hint(_l1_boxw_entry, _box_size_hint)
        _add_hint(_l1_boxh_entry, _box_size_hint)

        def _legend1_get(key):
            if key not in self.in_legend1_vars:
                self.in_legend1_vars[key] = tk.BooleanVar(value=True)
            return self.in_legend1_vars[key].get()

        def _legend1_set(key, val):
            if key not in self.in_legend1_vars:
                self.in_legend1_vars[key] = tk.BooleanVar(value=True)
            self.in_legend1_vars[key].set(val)

        legend1_curves_btn = tk.Button(
            legend1_row, text="Curves", width=7, font=("Malgun Gothic", 9, "bold"),
            bg=self.PALETTE["secondary"], fg="white",
            activebackground=self.PALETTE["secondary_dark"], activeforeground="white",
            relief="raised", bd=1, pady=1,
        )
        # [수정 - 요청] "Curves와 Marker 버튼을 우측 맞춤" - legend1_row/
        # legend2_row/row2_f가 전부 같은 grid 칸(row=0~2, column=3~5)에
        # 쌓여 있어서, 셋 다 sticky="we"로 칸 전체 폭을 채우게 하고 버튼을
        # side="right"로 packing하면 항상 같은 오른쪽 경계에서 맞춰진다.
        legend1_curves_btn.pack(side="right", padx=(1, 3))
        legend1_curves_btn.configure(
            command=lambda: self._open_curve_select_popup(
                legend1_curves_btn, "Legend1 Curves", _legend1_get, _legend1_set
            )
        )

        # [수정] "입력 줄들이 너무 길다" - Box Thick/Font/Marker를 아래
        # frame_row2(원래 Axis Frame Auto 있던 자리)로 옮겨서 이 줄을 줄임.

        # --- Legend2 줄 (X Axis Title 줄 우측, 보조 legend box, 기본 꺼짐) ---
        # Box Thick는 Legend1/2가 같은 값을 공유함 (따로 둘 필요 없어서 Box Thick2는 없앰)
        # 어느 curve가 Legend1/2 중 어디에 나타날지는 아래 "Available Variables Selection"
        # 표의 Leg 열(1 또는 2)에서 변수별로 고른다
        legend2_row = ttk.Frame(self.plot_frame)
        legend2_row.grid(row=1, column=3, columnspan=3, padx=3, pady=0, sticky="we")
        self._mk_check(legend2_row, "Legend2 On", self.legend2_on_var, side="left", padx=3)
        self._mk_check(legend2_row, "Box", self.legend2_box_var, side="left", padx=3)
        ttk.Label(legend2_row, text="Pos2:").pack(side="left", padx=2)
        legend2_pos_combo = ttk.Combobox(legend2_row, textvariable=self.legend2_pos_var, values=pos_list, width=10)
        legend2_pos_combo.pack(side="left", padx=2)
        _add_legend_pos_hint(legend2_pos_combo)
        ttk.Label(legend2_row, text="Align:").pack(side="left", padx=(4, 1))
        ttk.Combobox(legend2_row, textvariable=self.legend2_align_var, values=["Auto", "Left", "Right"],
                     width=5, state="readonly").pack(side="left", padx=1)
        ttk.Label(legend2_row, text="Box W/H:").pack(side="left", padx=(4, 1))
        _l2_boxw_entry = self._mk_entry(legend2_row, self.legend2_box_width_pct_var, width=4, color="accent3")
        _l2_boxw_entry.pack(side="left", padx=1)
        _l2_boxh_entry = self._mk_entry(legend2_row, self.legend2_box_height_pct_var, width=4, color="accent3")
        _l2_boxh_entry.pack(side="left", padx=1)
        _add_hint(_l2_boxw_entry, _box_size_hint)
        _add_hint(_l2_boxh_entry, _box_size_hint)
        def _legend2_get(key):
            if key not in self.legend_group_vars:
                self.legend_group_vars[key] = tk.StringVar(value="2")
            return self.legend_group_vars[key].get() == "2"

        def _legend2_set(key, val):
            if key not in self.legend_group_vars:
                self.legend_group_vars[key] = tk.StringVar(value="2")
            self.legend_group_vars[key].set("2" if val else "1")

        legend2_curves_btn = tk.Button(
            legend2_row, text="Curves", width=7, font=("Malgun Gothic", 9, "bold"),
            bg=self.PALETTE["secondary"], fg="white",
            activebackground=self.PALETTE["secondary_dark"], activeforeground="white",
            relief="raised", bd=1, pady=1,
        )
        legend2_curves_btn.pack(side="right", padx=(1, 3))
        legend2_curves_btn.configure(
            command=lambda: self._open_curve_select_popup(
                legend2_curves_btn, "Legend2 Curves", _legend2_get, _legend2_set
            )
        )

        # [수정] "입력 줄들이 너무 길다" - Font(legend_font_var/legend_size_var)를
        # 아래 frame_row2(원래 Axis Frame Auto 있던 자리)로 옮겨서 이 줄을 줄임.

        # Row 1
        ttk.Label(self.plot_frame, text="X Axis Title", style="RowHead.TLabel").grid(row=1, column=0, padx=5, pady=0, sticky="w")
        self.xlabel_entry = self._mk_entry(self.plot_frame, self.xlabel_var, width=30, color="accent3")
        self.xlabel_entry.grid(row=1, column=1, padx=5, pady=0, sticky="w")
        self.xlabel_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.xlabel_entry))

        x_font_frame = ttk.Frame(self.plot_frame)
        x_font_frame.grid(row=1, column=2, padx=5, pady=0, sticky="w")
        ttk.Combobox(x_font_frame, textvariable=self.xlabel_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(x_font_frame, textvariable=self.xlabel_size_var, values=size_list, width=2, state="readonly").pack(side="left", padx=2)

        # [수정] "입력 줄들이 너무 길다" - Axis Frame Auto 줄(원래 row=2)을
        # Plot File Name 자리(row=3)로 내리고, Plot File Name은 같은 줄
        # 우측으로 옮김. 비어진 row=2 자리엔 legend1/2 줄에서 뺀 Box Thick/
        # Font/Marker를 옮겨와 배치한다(각 줄 길이를 줄이기 위한 재배치).
        row2_f = ttk.Frame(self.plot_frame)
        row2_f.grid(row=2, column=3, columnspan=3, sticky="we", padx=3, pady=0)

        ttk.Label(row2_f, text="Box Thick:").pack(side="left", padx=(3, 1))
        ttk.Combobox(row2_f, textvariable=self.legend_thick_var, values=thick_list, width=3, state="readonly").pack(side="left", padx=2)

        ttk.Label(row2_f, text="Font:").pack(side="left", padx=(8, 1))
        legend_font_combo = ttk.Combobox(row2_f, textvariable=self.legend_font_var, values=font_list, width=12, state="readonly")
        legend_font_combo.pack(side="left", padx=1)
        self._disable_combobox_wheel(legend_font_combo)
        legend_size_combo = ttk.Combobox(row2_f, textvariable=self.legend_size_var, values=size_list, width=2, state="readonly")
        legend_size_combo.pack(side="left", padx=1)
        self._disable_combobox_wheel(legend_size_combo)

        # Marker는 줄 우측 끝에 정렬(끝 맞춤) - Curves 버튼(Legend1/2, width=7)과
        # 크기를 통일해 달라는 요청으로 width=7 지정.
        marker_settings_btn = tk.Button(
            row2_f, text="Marker", width=7, font=("Malgun Gothic", 9, "bold"),
            bg=self.PALETTE["secondary"], fg="white",
            activebackground=self.PALETTE["secondary_dark"], activeforeground="white",
            relief="raised", bd=1, pady=1,
        )
        marker_settings_btn.pack(side="right", padx=(1, 3))
        marker_settings_btn.configure(command=self._open_marker_settings_popup)

        # Row 2
        ttk.Label(self.plot_frame, text="Y Left Title (Y1)", style="RowHead.TLabel").grid(row=2, column=0, padx=5, pady=0, sticky="w")
        self.ylabel_entry = self._mk_entry(self.plot_frame, self.ylabel_var, width=30, color="accent3")
        self.ylabel_entry.grid(row=2, column=1, padx=5, pady=0, sticky="w")
        self.ylabel_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.ylabel_entry))

        # Row 3
        ttk.Label(self.plot_frame, text="Y Right Title (Y2)", style="RowHead.TLabel").grid(row=3, column=0, padx=5, pady=0, sticky="w")
        self.y2label_entry = self._mk_entry(self.plot_frame, self.y2label_var, width=30, color="accent3")
        self.y2label_entry.grid(row=3, column=1, padx=5, pady=0, sticky="w")
        self.y2label_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.y2label_entry))

        # [수정] 기본값을 Auto로 변경 - 화면에서는 항상 검증된 scale=1.0 기준으로
        # 뜨게 하고, 인쇄/저장 시 특정 물리 크기가 필요할 때만 꺼서 W/H를 쓰도록 함
        self.frame_auto_var = tk.BooleanVar(value=True)
        self.frame_width_var = tk.StringVar(value="10")
        self.frame_height_var = tk.StringVar(value="8")
        self.frame_unit_var = tk.StringVar(value="cm")

        row3_f = ttk.Frame(self.plot_frame)
        row3_f.grid(row=3, column=3, columnspan=3, sticky="we", padx=3, pady=0)

        frame_size_f = ttk.Frame(row3_f)
        frame_size_f.pack(side="left")

        self._mk_check(
            frame_size_f, "Axis Frame Auto", self.frame_auto_var, bold=True,
            command=self.toggle_frame_size_state, side="left", padx=5
        )

        ttk.Label(frame_size_f, text="W:").pack(side="left", padx=(8, 2))
        self.frame_width_entry = self._mk_entry(frame_size_f, self.frame_width_var, width=6, color="accent3")
        self.frame_width_entry.pack(side="left")

        ttk.Label(frame_size_f, text="H:").pack(side="left", padx=(6, 2))
        self.frame_height_entry = self._mk_entry(frame_size_f, self.frame_height_var, width=6, color="accent3")
        self.frame_height_entry.pack(side="left")

        self.frame_unit_combo = ttk.Combobox(
            frame_size_f, textvariable=self.frame_unit_var,
            values=["in", "cm"], width=4, state="readonly"
        )
        self.frame_unit_combo.pack(side="left", padx=(6, 0))
        self.toggle_frame_size_state()

        # [수정] "Plot File Name은 우측 끝으로(right align)" - 같은 줄(row3_f)
        # 안에서 Axis Frame Auto 묶음 오른쪽에 배치.
        filename_f = ttk.Frame(row3_f)
        filename_f.pack(side="right", padx=(10, 0))
        self.filename_var = tk.StringVar(value="CathPlot")
        ttk.Label(filename_f, text="Plot File Name", font=("Malgun Gothic", 9, "bold")).pack(side="left", padx=(0, 3))
        self.filename_entry = self._mk_entry(filename_f, self.filename_var, width=20, color="accent3")
        self.filename_entry.pack(side="left")

        # Row 4
        self.xlog_var = tk.BooleanVar(value=False)
        self.y1log_var = tk.BooleanVar(value=False)
        self.y2log_var = tk.BooleanVar(value=False)
        self.xfmt_var = tk.StringVar(value="Normal")
        self.y1fmt_var = tk.StringVar(value="Normal")
        self.y2fmt_var = tk.StringVar(value="Normal")
        FMT_LIST = ["Normal", "Scientific", "Power10"]

        x_auto_f = ttk.Frame(self.plot_frame)
        x_auto_f.grid(row=4, column=0, sticky="w", padx=5, pady=2)
        self._mk_check(x_auto_f, "Auto X Range", self.xauto_var, color="accent", side="left")

        x_log_f = ttk.Frame(self.plot_frame)
        x_log_f.grid(row=4, column=1, sticky="w", padx=5, pady=2)
        self._mk_check(x_log_f, "Log", self.xlog_var, side="left")
        xfmt_combo = ttk.Combobox(x_log_f, textvariable=self.xfmt_var, values=FMT_LIST, width=7, state="readonly")
        xfmt_combo.pack(side="left", padx=(2, 0))
        self._disable_combobox_wheel(xfmt_combo)

        y1_auto_f = ttk.Frame(self.plot_frame)
        y1_auto_f.grid(row=4, column=2, sticky="w", padx=5, pady=2)
        self._mk_check(y1_auto_f, "Auto Y1 (Left) Range", self.yauto_var, color="accent", side="left")

        y1_log_f = ttk.Frame(self.plot_frame)
        y1_log_f.grid(row=4, column=3, sticky="w", padx=2, pady=2)
        self._mk_check(y1_log_f, "Log", self.y1log_var, side="left")
        y1fmt_combo = ttk.Combobox(y1_log_f, textvariable=self.y1fmt_var, values=FMT_LIST, width=7, state="readonly")
        y1fmt_combo.pack(side="left", padx=(2, 0))
        self._disable_combobox_wheel(y1fmt_combo)

        y2_auto_f = ttk.Frame(self.plot_frame)
        y2_auto_f.grid(row=4, column=4, sticky="w", padx=2, pady=2)
        self._mk_check(y2_auto_f, "Auto Y2 (Right) Range", self.y2auto_var, color="accent", side="left")

        y2_log_f = ttk.Frame(self.plot_frame)
        y2_log_f.grid(row=4, column=5, sticky="w", padx=2, pady=2)
        self._mk_check(y2_log_f, "Log", self.y2log_var, side="left")
        y2fmt_combo = ttk.Combobox(y2_log_f, textvariable=self.y2fmt_var, values=FMT_LIST, width=7, state="readonly")
        y2fmt_combo.pack(side="left", padx=(2, 0))
        self._disable_combobox_wheel(y2fmt_combo)

        # Row 5
        ttk.Label(self.plot_frame, text="X Min/Max", style="RowHead.TLabel").grid(row=5, column=0, sticky="w", padx=5, pady=2)
        self.xmin_var = tk.StringVar()
        self.xmax_var = tk.StringVar()
        x_limit_f = ttk.Frame(self.plot_frame)
        x_limit_f.grid(row=5, column=1, sticky="w", padx=5)
        self._mk_entry(x_limit_f, self.xmin_var, width=9, color="accent3").pack(side="left")
        ttk.Label(x_limit_f, text="~").pack(side="left", padx=2)
        self._mk_entry(x_limit_f, self.xmax_var, width=9, color="accent3").pack(side="left")

        ttk.Label(self.plot_frame, text="Y1 Min/Max", style="RowHead.TLabel").grid(row=5, column=2, sticky="w", padx=5, pady=2)
        self.ymin_var = tk.StringVar()
        self.ymax_var = tk.StringVar()
        y1_limit_f = ttk.Frame(self.plot_frame)
        y1_limit_f.grid(row=5, column=3, sticky="w", padx=5)
        self._mk_entry(y1_limit_f, self.ymin_var, width=9, color="accent3").pack(side="left")
        ttk.Label(y1_limit_f, text="~").pack(side="left", padx=2)
        self._mk_entry(y1_limit_f, self.ymax_var, width=9, color="accent3").pack(side="left")

        ttk.Label(self.plot_frame, text="Y2 Min/Max", style="RowHead.TLabel").grid(row=5, column=4, sticky="w", padx=5, pady=2)
        self.y2min_var = tk.StringVar()
        self.y2max_var = tk.StringVar()
        y2_limit_f = ttk.Frame(self.plot_frame)
        y2_limit_f.grid(row=5, column=5, sticky="w", padx=5)
        self._mk_entry(y2_limit_f, self.y2min_var, width=9, color="accent3").pack(side="left")
        ttk.Label(y2_limit_f, text="~").pack(side="left", padx=2)
        self._mk_entry(y2_limit_f, self.y2max_var, width=9, color="accent3").pack(side="left")

        # Row 6
        ttk.Label(self.plot_frame, text="X Tics/Minor", style="RowHead.TLabel").grid(row=6, column=0, sticky="w", padx=5, pady=2)
        self.xtics_var = tk.StringVar()
        self.mxtics_var = tk.StringVar()
        x_tick_f = ttk.Frame(self.plot_frame)
        x_tick_f.grid(row=6, column=1, sticky="w", padx=5)
        self._mk_entry(x_tick_f, self.xtics_var, width=9, color="accent3").pack(side="left")
        self._mk_entry(x_tick_f, self.mxtics_var, width=5, color="accent3").pack(side="left", padx=(5, 0))

        ttk.Label(self.plot_frame, text="Y Left (Y1) Tics", style="RowHead.TLabel").grid(row=6, column=2, sticky="w", padx=5, pady=2)
        self.ytics_var = tk.StringVar()
        self.mytics_var = tk.StringVar()
        y1_tick_f = ttk.Frame(self.plot_frame)
        y1_tick_f.grid(row=6, column=3, sticky="w", padx=5)
        self._mk_entry(y1_tick_f, self.ytics_var, width=9, color="accent3").pack(side="left")
        self._mk_entry(y1_tick_f, self.mytics_var, width=5, color="accent3").pack(side="left", padx=(5, 0))

        ttk.Label(self.plot_frame, text="Y Right (Y2) Tics", style="RowHead.TLabel").grid(row=6, column=4, sticky="w", padx=5, pady=2)
        self.y2tics_var = tk.StringVar()
        self.my2tics_var = tk.StringVar()
        y2_tick_f = ttk.Frame(self.plot_frame)
        y2_tick_f.grid(row=6, column=5, sticky="w", padx=5)
        self._mk_entry(y2_tick_f, self.y2tics_var, width=9, color="accent3").pack(side="left")
        self._mk_entry(y2_tick_f, self.my2tics_var, width=5, color="accent3").pack(side="left", padx=(5, 0))

        # Row 7
        self.major_grid_var = tk.BooleanVar(value=True)
        self.minor_grid_var = tk.BooleanVar(value=False)

        major_grid_f = ttk.Frame(self.plot_frame)
        major_grid_f.grid(row=7, column=0, sticky="w", padx=5, pady=2)
        self._mk_check(
            major_grid_f, "Major Grid", self.major_grid_var,
            command=self.on_major_grid_toggled, side="left"
        )

        minor_grid_f = ttk.Frame(self.plot_frame)
        minor_grid_f.grid(row=7, column=1, sticky="w", padx=5, pady=2)
        self.minor_grid_check = self._mk_check(
            minor_grid_f, "Minor Grid", self.minor_grid_var, side="left"
        )

        # Annotations Area
        self.anno_frame = ttk.LabelFrame(self.plot_frame, text="Multi Annotations", style=self.SECTION_STYLE["annotations"])
        self.anno_frame.grid(row=8, column=0, columnspan=6, sticky="ew", padx=5, pady=2)

        self.c_list_frame = ttk.Frame(self.anno_frame)
        self.c_list_frame.pack(fill="x", padx=5)
        self.a_list_frame = ttk.Frame(self.anno_frame)
        self.a_list_frame.pack(fill="x", padx=5)
        self.e_list_frame = ttk.Frame(self.anno_frame)
        self.e_list_frame.pack(fill="x", padx=5)

        self.comment_on_var = tk.BooleanVar(value=True)
        self.arrow_on_var = tk.BooleanVar(value=True)
        self.circle_on_var = tk.BooleanVar(value=True)

        btn_f = ttk.Frame(self.anno_frame)
        #self.anno_btn_f = ttk.Frame(self.anno_frame)
        #btn_f = self.anno_btn_f

        btn_f.pack(fill="x", pady=0)

        comment_btn_col = ttk.Frame(btn_f)
        comment_btn_col.pack(side="left", padx=5)
        ttk.Button(comment_btn_col, text="+ Add Comment", command=self.add_comment_row).pack(side="top", anchor="w")
        self._mk_check(comment_btn_col, "Enable Comments", self.comment_on_var, side="top", anchor="w")

        arrow_btn_col = ttk.Frame(btn_f)
        arrow_btn_col.pack(side="left", padx=15)
        ttk.Button(arrow_btn_col, text="+ Add Line/Arrow", command=self.add_arrow_row).pack(side="top", anchor="w")
        self._mk_check(arrow_btn_col, "Enable Arrows", self.arrow_on_var, side="top", anchor="w")

        # [추가] "Arrow 옆에 Circle(중심축 2개 타원 - 반지름 1개만 입력하면 원)"
        circle_btn_col = ttk.Frame(btn_f)
        circle_btn_col.pack(side="left", padx=15)
        ttk.Button(circle_btn_col, text="+ Add Circle", command=self.add_circle_row).pack(side="top", anchor="w")
        self._mk_check(circle_btn_col, "Enable Circles", self.circle_on_var, side="top", anchor="w")

        # [수정] "Comment/Arrow 입력창이 안 보임 - 항상 빈 칸이 하나씩 나오게
        # 해야 함(어차피 안 지워지는 빈 칸이니 기본으로 둠)" - 시작할 때 매번
        # "+"를 눌러 추가하지 않아도 바로 입력할 수 있게, 빈 행을 하나씩
        # 미리 만들어둔다(모두 지웠을 때도 remove_row에서 다시 하나 채워줌).
        self.add_comment_row()
        self.add_arrow_row()
        self.add_circle_row()

        # 고급: raw gnuplot 명령어 직접 입력 (여기 적은 내용은 생성되는 .plt 파일에 그대로 삽입됨)
        self.raw_gnuplot_frame = ttk.LabelFrame(self.plot_frame, text="Advanced: Raw gnuplot commands", style=self.SECTION_STYLE["advanced"])
        self.raw_gnuplot_frame.grid(row=9, column=0, columnspan=6, sticky="ew", padx=5, pady=2)
        # [수정 - 요청] "Advanced block 입력에도 색 구분 테두리" - tk.Text는
        # 원래도 ttk가 아니라 highlightbackground/highlightcolor가 항상
        # 동작함(테마 영향 없음) - Advanced 섹션색(danger)으로 맞춤.
        self.raw_gnuplot_text = tk.Text(
            self.raw_gnuplot_frame, height=3, wrap="none",
            highlightthickness=1, highlightbackground=self.PALETTE["danger"], highlightcolor=self.PALETTE["danger"],
        )
        self.raw_gnuplot_text.pack(fill="x", padx=5, pady=3)

        self.button_frame = ttk.Frame(self.root)
        self.button_frame.pack(side="bottom", fill="x", padx=10, pady=4)

        # [수정 - 재조정] "화면이 눈에 띄게 안 바뀌었다" - ttk.Style의
        # Accent 스타일들은 Windows 기본 테마/일부 환경에서 배경색이 실제로
        # 안 반영되는 것으로 사용자 확인됨 - Batch Set/Queue와 똑같이 확실히
        # 색이 먹는 tk.Button으로 주요 동작 버튼들을 전부 바꾼다.
        def _accent_btn(parent, text, bg, dark, command, **pack_kw):
            b = tk.Button(
                parent, text=text, command=command,
                font=("Malgun Gothic", 10, "bold"), bg=bg, fg="white",
                activebackground=dark, activeforeground="white",
                relief="raised", bd=2, padx=10,
            )
            b.pack(**pack_kw)
            return b

        pal = self.PALETTE
        _accent_btn(self.button_frame, "PLOT", pal["accent"], pal["accent_dark"],
                    lambda: self.execute_plot_pipeline("Interactive"), side="left", pady=2)

        # [추가 - 요청] "X변수 변화에 따른 Y변수들의 progress를 시각화" - PLOT
        # 옆에 Animate 체크박스(기본 꺼짐 - 평소엔 지금처럼 정적으로 뜸)와
        # 재생 시간(초) 입력칸을 둔다. 체크하고 PLOT을 누르면 화면(Interactive)
        # 창이 이 재생 시간 안에 X 전체 범위를 끝내는 애니메이션으로 뜬다
        # (실행 중 Space=일시정지/재개, +/-=속도, Q=종료 - 진행률/현재 X값도
        # 화면에 표시됨). 체크한 채 SAVE를 누르면(현재 화면 설정 선택 시)
        # SAVE 버튼 자체가 애니메이션 GIF 저장으로 동작한다(execute_save_dialog
        # 참고) - 별도 버튼을 만드는 대신 기존 SAVE를 그대로 재사용.
        self.animate_var = tk.BooleanVar(value=False)
        self.animate_duration_var = tk.StringVar(value="20")
        animate_f = ttk.Frame(self.button_frame)
        animate_f.pack(side="left", padx=(8, 0))
        self._mk_check(animate_f, "Animate", self.animate_var, color="accent", side="left")
        ttk.Label(animate_f, text="Time(s):").pack(side="left", padx=(4, 1))
        self._mk_entry(animate_f, self.animate_duration_var, width=4, color="accent").pack(side="left")

        _accent_btn(self.button_frame, "SAVE", pal["accent2"], pal["accent2_dark"],
                    self.execute_save_dialog, side="left", padx=5, pady=2)
        _accent_btn(self.button_frame, "PRINT", pal["accent3"], pal["accent3_dark"],
                    self.execute_print_dialog, side="left", padx=5, pady=2)
        _accent_btn(self.button_frame, "Close All Plots", pal["danger"], pal["danger_dark"],
                    self.close_all_plot_windows, side="right", padx=5, pady=2)
        _accent_btn(self.button_frame, "Multi-Plot", pal["amber"], pal["amber_dark"],
                    self.open_multi_plot_dialog, side="left", padx=15, pady=2)
        self._mk_btn(self.button_frame, "Clean Past Plots", self.open_delete_dialog,
                     color="secondary", side="right", padx=5, pady=2)

        self.add_file_row()

        self.ylabel_var.trace_add("write", lambda *args: self.on_y1_title_changed(*args))
        self.y2label_var.trace_add("write", lambda *args: self.on_y2_title_changed(*args))
        self.xlabel_var.trace_add("write", lambda *args: self.on_x_title_changed(*args))

        # [수정] content_height(Text 위젯이 포함된 raw_gnuplot_frame 때문에
        # winfo_reqheight()가 실제보다 작게 잡히는 경우가 있어, 맨 아래 행
        # (Advanced: Raw gnuplot commands)이 절반만 보이고 잘리는 문제가 있었음
        # ("세로가 문제임") - 더 이상 content_height로 축소하지 않고, 항상
        # 이 고정 높이를 그대로 사용한다(여유 공간이 남아도 감수).
        self.plot_canvas.configure(height=390)

        # [기능 추가] 스크롤바에 마우스를 직접 올리지 않아도, 해당 스크롤 영역(파일 목록/
        # 변수 선택/Plot Setting) 위에서 마우스 휠을 굴리면 바로 스크롤되도록 바인딩
        self._bind_mousewheel(self.file_frame, self.file_canvas)
        self._bind_mousewheel(self.var_frame, self.canvas)
        self._bind_mousewheel(self.plot_container, self.plot_canvas)

        # [수정] PLOT/PRINT/SAVE 버튼 줄 바로 위에 생기던 빈 공간의 실제 원인은
        # Plot Setting 캔버스가 아니라, 창 전체 고정 높이(초기 지정값)가 각 위젯들의
        # 실제 필요 높이 합계보다 커서 남는 여백이었음. 모든 위젯을 배치한 뒤
        # 실제 필요한 높이로 창 크기를 다시 맞춰서 여백을 없앤다.
        self.root.update_idletasks()
        required_height = self.root.winfo_reqheight()
        # [수정] Plot Setting 캔버스를 고정 높이(390)로 키운 뒤로는 이 required_height
        # 자체가 이미 그만큼 커져서, 예전처럼 추가 버퍼(+70px)를 더하면 PLOT 버튼
        # 위에 불필요한 빈 공간이 남았음("PLOT 버튼 위가 3줄 정도 빔") - 버퍼 없이
        # 필요한 높이 그대로 사용한다.
        # [되돌림] "가로 길이가 너무 크다"는 요청으로 winfo_reqwidth() 기반 자동
        # 계산을 시도했는데, 실제로는 가로폭이 절반으로 줄어들며 우측 내용이
        # 통째로 잘리는 심각한 문제가 발생함(실측 확인) - file/var 목록이
        # 가로 스크롤 가능한 캔버스라 reqwidth가 실제 필요한 편안한 너비보다
        # 훨씬 작게 잡히는 것으로 추정됨(세로는 이런 스크롤 캔버스가 없어
        # winfo_reqheight가 문제없이 동작했던 것과 대조적). 자동 계산 대신
        # 검증된 고정값을 쓰되, "노트북 화면에 맞게 넓혀달라"는 요청으로
        # 1150 -> 1200으로 조정(초기 self.root.geometry 호출과 동일한 값으로 유지).
        self.root.geometry(f"1200x{required_height}")

    def _disable_combobox_wheel(self, combo):
        """콤보박스(Color/Style 등) 위에서 마우스 휠을 굴리면 그 콤보박스의 값이
        Auto->Black->Red...처럼 바뀌어버리는 Tkinter 기본 동작을 막는다. 대신
        휠 이벤트를 변수 목록(캔버스) 스크롤로 넘긴다. 'return "break"'로
        콤보박스 자체의 기본 휠 처리(값 순환)가 이어서 실행되지 않도록 한다."""
        def _on_wheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"
        combo.bind("<MouseWheel>", _on_wheel)

    def _bind_mousewheel(self, region_widget, target_canvas):
        """region_widget(과 그 안의 모든 자식 위젯) 위에서 마우스 휠을 굴리면
        target_canvas가 스크롤되도록 한다.
        [수정] "마우스 scroll이 가끔 안 됨" 버그 - 이전에는 region_widget에만
        <Enter>/<Leave>로 bind_all을 붙였다 뗐다 했는데, Tk는 마우스가
        region_widget의 배경에서 그 안의 자식 위젯(버튼/콤보박스/체크박스/
        엔트리 등) 위로 넘어가는 순간 그 자식 위젯을 "현재 포인터 위젯"으로
        보고 부모(region_widget)에 <Leave>를 보냄(자식 쪽엔 이 바인딩이 없음).
        그러면 곧바로 unbind_all이 실행돼 버려서, 목록 안의 배경(빈 여백)
        위에서는 휠이 되는데 그 안에 촘촘히 들어찬 버튼/콤보박스/체크박스
        위에서는 휠이 안 먹는 현상이 생겼던 것("가끔 안 되는" 것처럼 보인
        이유). 자식 하나하나에 다시 바인딩하는 대신, bind_all은 한 번만 걸어
        두고, 이벤트가 실제로 전달된 위젯(event.widget)에서 조상(master)
        방향으로 올라가며 어느 region_widget에 속하는지 찾아 그 target_canvas를
        스크롤하는 전역 핸들러 하나로 통일한다 - 자식이 몇 겹이든 항상 동작함."""
        if not hasattr(self, "_wheel_regions"):
            self._wheel_regions = []
            self.root.bind_all("<MouseWheel>", self._on_global_mousewheel)
        self._wheel_regions.append((region_widget, target_canvas))

    def _on_global_mousewheel(self, event):
        w = event.widget
        while w is not None:
            for region_widget, target_canvas in self._wheel_regions:
                if w is region_widget:
                    target_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                    return "break"
            w = getattr(w, "master", None)
        return None

    def open_delete_dialog(self):
        files = glob.glob(os.path.join(self.plot_dir, "*.plt"))
        if not files:
            messagebox.showinfo("Clean Info", "No past plot files found.")
            return

        del_win = tk.Toplevel(self.root)
        del_win.title("Delete Plot Files")
        del_win.geometry("400x300")

        listbox = tk.Listbox(del_win, selectmode=tk.EXTENDED)
        listbox.pack(fill="both", expand=True, padx=10, pady=10)
        for f in files:
            listbox.insert(tk.END, os.path.basename(f))

        def confirm_delete():
            selected_indices = listbox.curselection()
            if not selected_indices: return
            if messagebox.askyesno("Confirm", "Selected files will be deleted. Proceed?"):
                failed = []
                for i in selected_indices:
                    filename = listbox.get(i)
                    try:
                        os.remove(os.path.join(self.plot_dir, filename))
                    except Exception as e:
                        failed.append(f"{filename}: {e}")
                del_win.destroy()
                self.update_plot_file_list()
                if failed:
                    messagebox.showerror(
                        "Delete Error",
                        "일부 파일을 삭제하지 못했습니다 (다른 프로그램에서 열려있을 수 있습니다):\n" + "\n".join(failed)
                    )

        ttk.Button(del_win, text="Delete Selected", command=confirm_delete).pack(pady=5)

    def on_major_grid_toggled(self):
        if self.major_grid_var.get():
            self.minor_grid_check.config(state="normal")
        else:
            self.minor_grid_var.set(False)
            self.minor_grid_check.config(state="disabled")

    def _next_interactive_plot_id(self, raw_title, safe_title):
        """Choose an unused plot/window number, including plots from past runs."""
        known_ids = [self.title_counters.get(raw_title, 0)]
        #pattern = re.compile(rf"^{re.escape(safe_title)}_Temp_(\d+)\.plt$", re.IGNORECASE)
        pattern = re.compile(rf"^{re.escape(safe_title)}_(\d+)\.plt$", re.IGNORECASE)
        for path in glob.glob(os.path.join(self.plot_dir, f"{safe_title}_Temp_*.plt")):
            match = pattern.match(os.path.basename(path))
            if match:
                known_ids.append(int(match.group(1)))

        window_pattern = re.compile(rf"^{re.escape(safe_title)}_(\d+)$")
        for window_name in self.active_plots_cache:
            match = window_pattern.match(window_name)
            if match:
                known_ids.append(int(match.group(1)))

        return max(known_ids) + 1

    LAYOUT_GRID = {
        "1/p": (1, 1),
        "2/p": (2, 1),
        "3/p": (1, 3),
        "4/p": (2, 2),
        "6/p": (3, 2),
    }

    def open_multi_plot_dialog(self):
        if not self.active_plots_cache:
            messagebox.showinfo(
                "Multi Print/Save",
                "먼저 PLOT으로 그림을 하나 이상 그려주세요.\n"
                "(Interactive PLOT으로 그린 창들만 목록에 나타납니다.)"
            )
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Multi Save / Print")
        dialog.geometry("420x520")
        dialog.transient(self.root)

        ttk.Label(dialog, text="Select plots:").pack(anchor="w", padx=10, pady=(10, 0))

        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        plot_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, exportselection=False)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=plot_listbox.yview)
        plot_listbox.config(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        plot_listbox.pack(side="left", fill="both", expand=True)

        # [수정] plt 파일이 삭제된 뒤에도 캐시에 남아 목록에 계속 뜨던 문제 수정
        self._cleanup_stale_plot_cache()

        available_names = sorted(self.active_plots_cache.keys())
        available_plots = [self.active_plots_cache[name] for name in available_names]
        for name in available_names:
            plot_listbox.insert("end", name)

        # [추가 - 요청] "여러 개를 한꺼번에 선택하는 게 아니라 하나씩 골랐을
        # 때, 고른 순서대로 배치할 수 있는지" - 기본은 기존처럼 이름순
        # (알파벳순)이고, 이 체크박스를 켜면 Ctrl+클릭으로 하나씩 고른
        # "선택한 순서"대로 배치한다. 리스트박스 자체에는 "몇 번째로
        # 골랐는지"를 알려주는 방법이 없어서(curselection은 항상 인덱스
        # 오름차순), 선택이 바뀔 때마다 직접 순서를 추적하고 선택된 항목
        # 앞에 [1],[2].. 번호를 붙여 눈으로 바로 확인할 수 있게 한다(범위
        # 선택/드래그로 여러 개가 한 번에 늘어나면 그 안에서는 인덱스
        # 순서로 번호를 매김 - "한 번의 클릭 = 한 순번"이라는 취지에는
        # 영향 없음, 한 번에 여러 개를 고르는 제스처는 원래도 순서를 알
        # 수 없음).
        order_mode_var = tk.BooleanVar(value=False)
        _selection_order = []  # plot_listbox 인덱스, 선택된 순서대로
        _updating = [False]  # selection_set()이 다시 <<ListboxSelect>>를 유발해 재귀 호출되는 것을 막는 가드

        def _refresh_listbox_display():
            _updating[0] = True
            try:
                cur_sel = set(plot_listbox.curselection())
                for idx, name in enumerate(available_names):
                    if order_mode_var.get() and idx in _selection_order:
                        text = f"[{_selection_order.index(idx) + 1}] {name}"
                    else:
                        text = name
                    if plot_listbox.get(idx) != text:
                        plot_listbox.delete(idx)
                        plot_listbox.insert(idx, text)
                for idx in cur_sel:
                    plot_listbox.selection_set(idx)
            finally:
                _updating[0] = False

        def _on_listbox_select(event=None):
            if _updating[0]:
                return
            cur = set(plot_listbox.curselection())
            prev = set(_selection_order)
            for idx in prev - cur:
                _selection_order.remove(idx)
            for idx in sorted(cur - prev):
                _selection_order.append(idx)
            _refresh_listbox_display()

        plot_listbox.bind("<<ListboxSelect>>", _on_listbox_select)
        self._mk_check(
            dialog, "선택 순서대로 배치 (Ctrl+클릭으로 하나씩 선택)", order_mode_var,
            command=_refresh_listbox_display, side="left"
        )

        ttk.Label(dialog, text="Layout:").pack(anchor="w", padx=10, pady=(10, 0))
        layout_combo = ttk.Combobox(
            dialog, textvariable=self.layout_var,
            values=["Auto", "1/p", "2/p", "3/p", "4/p", "6/p"], state="readonly"
        )
        layout_combo.pack(fill="x", padx=10, pady=5)

        orient_row = ttk.Frame(dialog)
        orient_row.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Label(orient_row, text="Orientation:").pack(side="left")
        orient_combo = ttk.Combobox(
            orient_row, textvariable=self.orientation_var,
            values=["portrait", "landscape"], state="readonly", width=12
        )
        orient_combo.pack(side="left", padx=(8, 0))

        # [추가 - 버그 수정] "M-P(Multi Print/Save) 버튼 눌러도 Axis Frame Auto/
        # Manual을 고르는 UI가 안 보임" - 실제 "M-P" 버튼은 이 open_multi_plot_
        # dialog였음(앞서 손댄 show_multiplot_dialog는 어디서도 호출되지 않는
        # 죽은 코드였음 - 정정). execute_multi_plot_pipeline은 항상 메인 창의
        # self.frame_auto_var/frame_width_var 등을 그대로 읽어가는데, 이
        # 다이얼로그엔 그 값을 보거나 바꿀 UI가 없어서 Auto/Manual 비교 테스트가
        # 매번 같은 설정으로 나갔을 수 있음 - 메인 창과 같은 tk 변수를 그대로
        # 재사용해서 여기서도 직접 보고 바꿀 수 있게 한다.
        mp_frame_size_f = ttk.Frame(dialog)
        mp_frame_size_f.pack(fill="x", padx=10, pady=(5, 5))
        mp_width_entry = ttk.Entry(mp_frame_size_f, textvariable=self.frame_width_var, width=6)
        mp_height_entry = ttk.Entry(mp_frame_size_f, textvariable=self.frame_height_var, width=6)

        def _mp_toggle_frame_size_state():
            state = "disabled" if self.frame_auto_var.get() else "normal"
            mp_width_entry.config(state=state)
            mp_height_entry.config(state=state)

        self._mk_check(
            mp_frame_size_f, "Axis Frame Auto", self.frame_auto_var, bold=True,
            command=_mp_toggle_frame_size_state, side="left"
        )
        ttk.Label(mp_frame_size_f, text="W:").pack(side="left", padx=(8, 2))
        mp_width_entry.pack(side="left")
        ttk.Label(mp_frame_size_f, text="H:").pack(side="left", padx=(6, 2))
        mp_height_entry.pack(side="left")
        ttk.Combobox(
            mp_frame_size_f, textvariable=self.frame_unit_var,
            values=["in", "cm"], width=4, state="readonly"
        ).pack(side="left", padx=(6, 0))
        _mp_toggle_frame_size_state()

        # [핵심 수정] 예전엔 Layout을 바꿀 때마다 이미 선택해둔 Orientation을 그
        # 레이아웃의 "기본값"으로 조용히 덮어썼음 (고정 orientation이 있는 레이아웃이
        # 하나도 없는데도 매번 else 분기를 타서 초기화됨) - "1/p인데 land를 골랐더니
        # port로 나온다"처럼 여러 orientation 불일치 리포트의 실제 원인이었을 가능성이
        # 큼. 이제 Layout을 바꿔도 Orientation 선택은 그대로 유지된다.

        def on_execute(mode):
            selected_indices = plot_listbox.curselection()
            if not selected_indices:
                messagebox.showwarning("Warning", "Please select at least one plot from the list.", parent=dialog)
                return

            # [수정 - 요청] "선택 순서대로 배치" 체크박스가 켜져 있으면
            # curselection()의 인덱스 오름차순(=항상 이름순) 대신, 위에서
            # 추적해둔 실제 클릭 순서(_selection_order)를 그대로 쓴다.
            # cell_rc(gnu_generator.create_multiplot_script)가 이 리스트
            # 순서 그대로 왼쪽→오른쪽, 위→아래로 채우므로, 여기서 순서만
            # 바꿔주면 배치 순서도 그대로 따라간다.
            if order_mode_var.get() and _selection_order:
                ordered_indices = [i for i in _selection_order if i in selected_indices]
            else:
                ordered_indices = selected_indices

            selected_names = [available_names[i] for i in ordered_indices]
            selected_defs = [available_plots[i] for i in ordered_indices]

            layout = self.layout_var.get()
            rows, cols = self.LAYOUT_GRID.get(layout, (1, 1))
            orientation = self.orientation_var.get()

            if layout != "Auto" and len(selected_defs) > rows * cols:
                messagebox.showwarning(
                    "Warning",
                    f"'{layout}' 레이아웃은 최대 {rows*cols}개까지만 담을 수 있습니다.\n"
                    f"지금 {len(selected_defs)}개를 선택하셨습니다 - 개수를 줄이거나 "
                    f"더 큰 레이아웃(또는 Auto)을 선택해주세요.",
                    parent=dialog
                )
                return

            import re
            base_title = re.sub(r"_\d+$", "", selected_names[0])

            self.multi_counters[base_title] = self.multi_counters.get(base_title, 0) + 1
            base_name = f"{base_title}_mul_{self.multi_counters[base_title]}"

            if mode == "Save":
                # [수정] "이미지 sample 순서는 png, pdf, jpg, svg, emf, eps 순으로" -
                # Word 등에 넣기 좋은 png를 기본/최우선으로.
                file_types = [
                    ("PNG Image (*.png)", "*.png"),
                    ("Portable Document Format (*.pdf)", "*.pdf"),
                    ("JPEG Image (*.jpg)", "*.jpg"),
                    ("SVG Vector Graphic (*.svg)", "*.svg"),
                    ("Enhanced Metafile (*.emf)", "*.emf"),
                    ("Encapsulated PostScript (*.eps)", "*.eps"),
                ]
                filepath = filedialog.asksaveasfilename(
                    parent=dialog,
                    initialdir=self.plot_dir,
                    initialfile=base_name,
                    defaultextension=".png",
                    filetypes=file_types,
                    title="Save Multiplot As..."
                )
                if not filepath:
                    return

                fmt = os.path.splitext(filepath)[1].replace(".", "").lower()

                _result_path = self.execute_multi_plot_pipeline(
                    selected_defs, mode, filepath, fmt
                )

                dialog.destroy()
                # [수정] 경고 미리보기에서 취소하면 execute_multi_plot_pipeline이
                # None을 반환하고 파일도 이미 지운 상태 - 이때는 "저장됨" 메시지를
                # 띄우면 안 됨(실제로 저장이 취소됐으므로).
                if _result_path:
                    messagebox.showinfo("Success", f"Saved: {os.path.basename(filepath)}")

            else:
                idx = 1
                while True:
                    temp_emf = os.path.join(self.plot_dir, f"MultiPlot_Print_{idx}.emf")
                    if not os.path.exists(temp_emf):
                        break
                    idx += 1

                dialog.destroy()

                try:
                    self.execute_multi_plot_pipeline(
                        selected_defs, "Batch", temp_emf, "emf"
                    )
                    if os.path.exists(temp_emf):
                        printer_name = self._pick_printer_dialog()
                        if printer_name:
                            threading.Thread(
                                target=self._print_emf_and_cleanup,
                                args=(temp_emf, "CathPlot Multi Plot", printer_name, self.orientation_var.get()),
                                daemon=True
                            ).start()
                        else:
                            try:
                                os.remove(temp_emf)
                            except OSError:
                                pass
                except Exception as e:
                    messagebox.showerror("Print Error", str(e))

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", pady=15)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=15)
        ttk.Button(btn_frame, text="Print", command=lambda: on_execute("Print")).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Save", command=lambda: on_execute("Save")).pack(side="right", padx=5)

    # ------------------------------------------------------------------
    # 템플릿 저장 / 불러오기
    # "화면 입력이 기본" 방향에 맞춰, 파일/변수 선택(어떤 dat 파일의 몇 번 output_no를
    # Y1/Y2/X로 쓸지)만 제외하고 화면에 보이는 나머지 입력값은 전부 포함한다:
    # 폰트/크기, 범례, 그리드, tics 배수, 프레임 크기 (기존 스타일 항목)
    # + title/label 텍스트, X/Y1/Y2 auto 여부와 min/max, xtics/ytics/y2tics 값,
    #   annotation(코멘트)/arrow(화살표) 목록
    # ------------------------------------------------------------------
    def _template_dict(self):
        return {
            "_readme": (
                "이 파일은 직접 텍스트 편집기로 열어 수정할 수 있습니다. "
                "file_assignments의 filename을 다른 dat 파일(CATHENA/Generic 섞여도 무방)로 "
                "바꾸거나, x_output_no/y1_output_nos/y2_output_nos의 숫자를 바꾸면 다른 변수를 "
                "가리키게 됩니다."
            ),
            # --- 스타일 (폰트/범례/그리드/프레임) ---
            "title_font": self.title_font_var.get(),
            "title_size": self.title_size_var.get(),
            "xlabel_font": self.xlabel_font_var.get(),
            "xlabel_size": self.xlabel_size_var.get(),
            "ylabel_font": self.ylabel_font_var.get(),
            "ylabel_size": self.ylabel_size_var.get(),
            "y2label_font": self.y2label_font_var.get(),
            "y2label_size": self.y2label_size_var.get(),
            "legend_on": self.legend_on_var.get(),
            "legend_box": self.legend_box_var.get(),
            "legend_pos": self.legend_pos_var.get(),
            "legend_align": self.legend_align_var.get(),
            "legend_thick": self.legend_thick_var.get(),
            "legend_font": self.legend_font_var.get(), "legend_size": self.legend_size_var.get(),
            "legend_box_width_pct": self.legend_box_width_pct_var.get(),
            "legend_box_height_pct": self.legend_box_height_pct_var.get(),
            "legend2_on": self.legend2_on_var.get(),
            "legend2_box": self.legend2_box_var.get(),
            "legend2_pos": self.legend2_pos_var.get(),
            "legend2_align": self.legend2_align_var.get(),
            "legend2_thick": self.legend_thick_var.get(),
            "legend2_box_width_pct": self.legend2_box_width_pct_var.get(),
            "legend2_box_height_pct": self.legend2_box_height_pct_var.get(),
            "major_grid": self.major_grid_var.get(),
            "minor_grid": self.minor_grid_var.get(),
            "mxtics": self.mxtics_var.get(),
            "mytics": self.mytics_var.get(),
            "my2tics": self.my2tics_var.get(),
            "frame_auto": self.frame_auto_var.get(),
            "frame_width": self.frame_width_var.get(),
            "frame_height": self.frame_height_var.get(),
            "frame_unit": self.frame_unit_var.get(),

            # --- title/label 텍스트 ---
            "title": self.title_var.get(),
            "xlabel": self.xlabel_var.get(),
            "ylabel": self.ylabel_var.get(),
            "y2label": self.y2label_var.get(),

            # --- X/Y1/Y2 auto 여부 + min/max ---
            "xauto": self.xauto_var.get(),
            "yauto": self.yauto_var.get(),
            "y2auto": self.y2auto_var.get(),
            "xlog": self.xlog_var.get(), "y1log": self.y1log_var.get(), "y2log": self.y2log_var.get(),
            "xfmt": self.xfmt_var.get(), "y1fmt": self.y1fmt_var.get(), "y2fmt": self.y2fmt_var.get(),
            "xmin": self.xmin_var.get(), "xmax": self.xmax_var.get(),
            "ymin": self.ymin_var.get(), "ymax": self.ymax_var.get(),
            "y2min": self.y2min_var.get(), "y2max": self.y2max_var.get(),

            # --- X/Y1/Y2 tics 값 (major, 문자열) ---
            "xtics": self.xtics_var.get(),
            "ytics": self.ytics_var.get(),
            "y2tics": self.y2tics_var.get(),

            # --- annotation(코멘트) / arrow(화살표) / circle(원,타원) ---
            "comment_on": self.comment_on_var.get(),
            "arrow_on": self.arrow_on_var.get(),
            "circle_on": self.circle_on_var.get(),
            "annotations": [
                {"txt": c['txt'].get(), "x": c['x'].get(), "y": c['y'].get(), "ang": c['ang'].get(),
                 "coord_mode": c['coord_mode'].get(), "color": c['color'].get()}
                for c in self.comment_list
            ],
            "arrows": [
                {"x1": a['x1'].get(), "y1": a['y1'].get(), "x2": a['x2'].get(), "y2": a['y2'].get(), "type": a['type'].get(),
                 "coord_mode": a['coord_mode'].get(), "color": a['color'].get(), "size": a['size'].get()}
                for a in self.arrow_list
            ],
            "circles": [
                {"x": e['x'].get(), "y": e['y'].get(), "rx": e['rx'].get(), "ry": e['ry'].get(),
                 "coord_mode": e['coord_mode'].get(), "color": e['color'].get()}
                for e in self.circle_list
            ],

            # --- var_no(output_no) 기준 curve 스타일: Color/Linestyle/Linewidth/Shift ---
            # (어떤 dat 파일인지와 무관하게, output_no 기준으로 저장 - Batch Queue의
            #  레시피 개념과 동일. 지금 화면에서 Y1/Y2로 선택된 변수들만 저장됨)
            "curve_styles": self._capture_curve_recipe()[0],

            # --- Plot File Name (Batch Set에서 출력 파일명 기본값으로 사용) ---
            "filename": self.filename_var.get(),

            # --- 실제 파일별 X/Y1/Y2 변수 지정 (Batch Set에서 이 Template 하나만으로
            #     완전히 같은 plot을 재현할 수 있도록, dat 파일명 자체도 포함) ---
            "file_assignments": self._capture_file_assignments(),

            # [추가] "3D도 Batch에 연동" - surface(splot) 파일은 Y1/Y2 선택이 없어
            # file_assignments에는 안 잡히므로(변수 선택 UI 자체가 없음), 3D Batch가
            # 이 Template만으로 surface도 재현할 수 있게 경로를 별도로 저장한다.
            "surface_files": self._capture_surface_files(),

            # --- Advanced: Raw gnuplot 입력창 내용 ---
            "extra_gnuplot": self.raw_gnuplot_text.get("1.0", "end-1c"),
        }

    def _capture_file_assignments(self):
        """현재 로드된 각 dat 파일의 X/Y1/Y2 변수 지정(output_no)을 파일명과 함께
        캡처한다. Template을 '완전한 plot 사양'으로 만들어 Batch Set에서 그대로
        재현할 수 있게 하기 위함 (파일명은 cwd 기준 상대경로로 저장).
        output_no는 순수 숫자로만 저장한다 (사람이 직접 JSON을 수정할 때 단순하게)."""
        assignments = []
        for info in self.file_rows:
            datfile = info.get("filename")
            if not datfile or info.get("meta") is None:
                continue
            try:
                rel_path = os.path.relpath(datfile, self.cwd)
            except ValueError:
                rel_path = datfile

            x_output_no = None
            x_val = info["x_var"].get()
            if x_val and "||" in x_val:
                try:
                    x_output_no = int(x_val.split("||")[1])
                except (ValueError, IndexError):
                    x_output_no = None

            y1_nos = [
                int(k.split("||")[1]) for k, v in self.selected_y1_vars.items()
                if v.get() and k.startswith(f"{datfile}||")
            ]
            y2_nos = [
                int(k.split("||")[1]) for k, v in self.selected_y2_vars.items()
                if v.get() and k.startswith(f"{datfile}||")
            ]

            if x_output_no is None and not y1_nos and not y2_nos:
                continue  # 아무것도 선택 안 된 파일은 저장 안 함

            assignments.append({
                "filename": rel_path,
                "x_output_no": x_output_no,
                "y1_output_nos": y1_nos,
                "y2_output_nos": y2_nos,
                "x_shift": self.file_xshift_vars[datfile].get() if datfile in self.file_xshift_vars else "0",
            })
        return assignments

    def _capture_surface_files(self):
        """[추가] "3D도 Batch에 연동" - 현재 로드된 surface(splot) 파일들의
        경로(cwd 기준 상대경로)만 저장한다. surface는 Y1/Y2 선택이 없어
        _capture_file_assignments에는 안 잡히므로 따로 캡처."""
        paths = []
        for info in self.file_rows:
            datfile = info.get("filename")
            meta = info.get("meta")
            if not datfile or meta is None or not getattr(meta, "is_surface", False):
                continue
            try:
                rel_path = os.path.relpath(datfile, self.cwd)
            except ValueError:
                rel_path = datfile
            paths.append(rel_path)
        return paths

    def _build_3d_curves_from_template_data(self, data):
        """[추가] "3D도 Batch에 연동" - 2D Template JSON의 file_assignments만으로
        (화면 상태를 전혀 안 건드리고) 3D curve 목록을 만든다. _collect_3d_curves와
        동일한 적격 조건(파일당 Y1 1개+Y2 1개)을 그대로 적용 - Batch Set과 같은
        이유로 백그라운드 스레드에서 호출해도 안전함."""
        eligible = []
        skipped = []
        for fa in data.get("file_assignments", []):
            rel_path = fa["filename"]
            abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(self.cwd, rel_path)
            bn = os.path.basename(abs_path)

            def _nos(items):
                return [(v["output_no"] if isinstance(v, dict) else v) for v in (items or [])]
            y1s = _nos(fa.get("y1_output_nos"))
            y2s = _nos(fa.get("y2_output_nos"))

            if len(y1s) == 1 and len(y2s) == 1:
                if not os.path.exists(abs_path):
                    skipped.append(f"{bn}: 파일 없음")
                    continue
                x_output_no = fa.get("x_output_no") or 0
                try:
                    target_dat_file = self.resort_dat_file(abs_path, x_output_no)
                except Exception:
                    target_dat_file = abs_path
                x_shift = float(fa.get("x_shift") or 0.0)
                eligible.append({
                    "dat_file": target_dat_file,
                    "x_col": x_output_no + 1,
                    "y_col": y1s[0] + 1,
                    "z_col": y2s[0] + 1,
                    "x_shift": x_shift,
                    "label": bn,
                })
            elif not y1s and not y2s:
                continue
            else:
                reason = []
                if len(y1s) != 1: reason.append(f"Y1 {len(y1s)}개")
                if len(y2s) != 1: reason.append(f"Y2 {len(y2s)}개")
                skipped.append(f"{bn}: {', '.join(reason)}")
        return eligible, skipped

    def _build_3d_surfaces_from_template_data(self, data):
        """[추가] "3D도 Batch에 연동" - Template JSON의 surface_files만으로
        (화면 상태를 전혀 안 건드리고) 3D surface 목록을 만든다.
        _collect_3d_surfaces와 동일한 형식으로 반환."""
        surfaces = []
        for rel_path in data.get("surface_files", []):
            abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(self.cwd, rel_path)
            if not os.path.exists(abs_path):
                continue
            try:
                meta = self.parser.parse(abs_path)
            except Exception:
                continue
            if not getattr(meta, "is_surface", False):
                continue
            _disp = os.path.basename(abs_path)
            surfaces.append({
                "dat_file": abs_path,
                "label": _disp,
                "n_outputs": meta.n_outputs,
                "z_label": meta.surface_base_name or _disp,
            })
        return surfaces

    def save_template(self):
        template_dir = os.path.join(self.cwd, "template")
        os.makedirs(template_dir, exist_ok=True)

        # 기본 파일명: plot 파일명(Plot File Name 입력창) 규칙과 동일하게 "이름_다음번호"
        raw_title = self.filename_var.get().strip() or "CathPlot"
        safe_title = "".join(c for c in raw_title if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"
        next_id = self.title_counters.get(safe_title, 0) + 1
        default_name = f"{safe_title}_{next_id}"

        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("CathPlot Template", "*.json")],
            initialdir=template_dir,
            initialfile=default_name,
            title="Save Template"
        )
        if not filepath:
            return
        try:
            import json
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self._template_dict(), f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Template", f"템플릿을 저장했습니다:\n{filepath}")
        except Exception as e:
            messagebox.showerror("Template", f"템플릿 저장 실패: {e}")

    def load_template(self):
        template_dir = os.path.join(self.cwd, "template")
        os.makedirs(template_dir, exist_ok=True)

        filepath = filedialog.askopenfilename(
            filetypes=[("CathPlot Template", "*.json"), ("All files", "*.*")],
            initialdir=template_dir,
            title="Load Template"
        )
        if not filepath:
            return
        try:
            import json
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 각 항목이 파일에 없어도 에러 없이 기존 값 유지 (구버전 템플릿과도 호환)
            self.title_font_var.set(data.get("title_font", self.title_font_var.get()))
            self.title_size_var.set(data.get("title_size", self.title_size_var.get()))
            self.xlabel_font_var.set(data.get("xlabel_font", self.xlabel_font_var.get()))
            self.xlabel_size_var.set(data.get("xlabel_size", self.xlabel_size_var.get()))
            self.ylabel_font_var.set(data.get("ylabel_font", self.ylabel_font_var.get()))
            self.ylabel_size_var.set(data.get("ylabel_size", self.ylabel_size_var.get()))
            self.y2label_font_var.set(data.get("y2label_font", self.y2label_font_var.get()))
            self.y2label_size_var.set(data.get("y2label_size", self.y2label_size_var.get()))
            self.legend_on_var.set(data.get("legend_on", self.legend_on_var.get()))
            self.legend_box_var.set(data.get("legend_box", self.legend_box_var.get()))
            self.legend_pos_var.set(data.get("legend_pos", self.legend_pos_var.get()))
            self.legend_align_var.set(data.get("legend_align", self.legend_align_var.get()))
            self.legend_thick_var.set(data.get("legend_thick", self.legend_thick_var.get()))
            self.legend_font_var.set(data.get("legend_font", self.legend_font_var.get()))
            self.legend_size_var.set(data.get("legend_size", self.legend_size_var.get()))
            self.legend_box_width_pct_var.set(data.get("legend_box_width_pct", self.legend_box_width_pct_var.get()))
            self.legend_box_height_pct_var.set(data.get("legend_box_height_pct", self.legend_box_height_pct_var.get()))
            self.legend2_on_var.set(data.get("legend2_on", self.legend2_on_var.get()))
            self.legend2_box_var.set(data.get("legend2_box", self.legend2_box_var.get()))
            self.legend2_pos_var.set(data.get("legend2_pos", self.legend2_pos_var.get()))
            self.legend2_align_var.set(data.get("legend2_align", self.legend2_align_var.get()))
            self.legend2_box_width_pct_var.set(data.get("legend2_box_width_pct", self.legend2_box_width_pct_var.get()))
            self.legend2_box_height_pct_var.set(data.get("legend2_box_height_pct", self.legend2_box_height_pct_var.get()))
            self.major_grid_var.set(data.get("major_grid", self.major_grid_var.get()))
            self.minor_grid_var.set(data.get("minor_grid", self.minor_grid_var.get()))
            self.mxtics_var.set(data.get("mxtics", self.mxtics_var.get()))
            self.mytics_var.set(data.get("mytics", self.mytics_var.get()))
            self.my2tics_var.set(data.get("my2tics", self.my2tics_var.get()))
            self.frame_auto_var.set(data.get("frame_auto", self.frame_auto_var.get()))
            self.frame_width_var.set(data.get("frame_width", self.frame_width_var.get()))
            self.frame_height_var.set(data.get("frame_height", self.frame_height_var.get()))
            self.frame_unit_var.set(data.get("frame_unit", self.frame_unit_var.get()))

            if "extra_gnuplot" in data:
                self.raw_gnuplot_text.delete("1.0", "end")
                self.raw_gnuplot_text.insert("1.0", data["extra_gnuplot"])

            # title/label 텍스트: set()하면 기존 trace(on_x_title_changed 등)가
            # 자동으로 실행되어 "자동/수동" 여부(x_title_auto 등)도 같이 맞춰짐
            if "title" in data:
                self.title_var.set(data["title"])
            if "xlabel" in data:
                self.xlabel_var.set(data["xlabel"])
            if "ylabel" in data:
                self.ylabel_var.set(data["ylabel"])
            if "y2label" in data:
                self.y2label_var.set(data["y2label"])

            # X/Y1/Y2 auto 여부 + min/max
            self.xauto_var.set(data.get("xauto", self.xauto_var.get()))
            self.xlog_var.set(data.get("xlog", self.xlog_var.get()))
            self.y1log_var.set(data.get("y1log", self.y1log_var.get()))
            self.y2log_var.set(data.get("y2log", self.y2log_var.get()))
            self.xfmt_var.set(data.get("xfmt", self.xfmt_var.get()))
            self.y1fmt_var.set(data.get("y1fmt", self.y1fmt_var.get()))
            self.y2fmt_var.set(data.get("y2fmt", self.y2fmt_var.get()))
            self.yauto_var.set(data.get("yauto", self.yauto_var.get()))
            self.y2auto_var.set(data.get("y2auto", self.y2auto_var.get()))
            self.xmin_var.set(data.get("xmin", self.xmin_var.get()))
            self.xmax_var.set(data.get("xmax", self.xmax_var.get()))
            self.ymin_var.set(data.get("ymin", self.ymin_var.get()))
            self.ymax_var.set(data.get("ymax", self.ymax_var.get()))
            self.y2min_var.set(data.get("y2min", self.y2min_var.get()))
            self.y2max_var.set(data.get("y2max", self.y2max_var.get()))

            # X/Y1/Y2 tics 값
            self.xtics_var.set(data.get("xtics", self.xtics_var.get()))
            self.ytics_var.set(data.get("ytics", self.ytics_var.get()))
            self.y2tics_var.set(data.get("y2tics", self.y2tics_var.get()))

            # annotation/arrow/circle: 템플릿 파일에 해당 항목이 있을 때만 기존 행을
            # 전부 지우고 저장된 내용으로 다시 생성 (없는 구버전 템플릿을 불러올 땐
            # 기존 목록 유지)
            if "annotations" in data or "arrows" in data or "circles" in data:
                for item in list(self.comment_list):
                    item['frame'].destroy()
                self.comment_list.clear()
                for item in list(self.arrow_list):
                    item['frame'].destroy()
                self.arrow_list.clear()
                for item in list(self.circle_list):
                    item['frame'].destroy()
                self.circle_list.clear()

                for c in data.get("annotations", []):
                    self.add_comment_row(initial=c)
                for a in data.get("arrows", []):
                    self.add_arrow_row(initial=a)
                for e in data.get("circles", []):
                    self.add_circle_row(initial=e)

                # 템플릿에 저장된 annotation/arrow/circle이 하나도 없으면(빈 리스트),
                # 목록이 완전히 비지 않도록 기본 빈 줄을 하나씩 채워 넣는다.
                if not self.comment_list:
                    self.add_comment_row()
                if not self.arrow_list:
                    self.add_arrow_row()
                if not self.circle_list:
                    self.add_circle_row()

                self.comment_on_var.set(data.get("comment_on", self.comment_on_var.get()))
                self.arrow_on_var.set(data.get("arrow_on", self.arrow_on_var.get()))
                self.circle_on_var.set(data.get("circle_on", self.circle_on_var.get()))

            # var_no(output_no) 기준 curve 스타일(Color/Linestyle/Linewidth/Shift + 축)을
            # 현재 로드된 파일들 중 output_no가 일치하는 변수에 적용 (Batch Queue의
            # 레시피와 동일한 개념 - 어떤 dat 파일인지와 무관하게 output_no로 매칭)
            curve_styles = data.get("curve_styles", [])
            if curve_styles:
                style_by_no = {item["output_no"]: item for item in curve_styles}
                for info in self.file_rows:
                    if not info.get("filename") or info.get("meta") is None:
                        continue
                    datfile = info["filename"]
                    for pv in info["meta"].variables:
                        style = style_by_no.get(pv.output_no)
                        if not style:
                            continue
                        key_str = f"{datfile}||{pv.output_no}"
                        if key_str in self.color_vars:
                            self.color_vars[key_str].set(style.get("color", self.color_vars[key_str].get()))
                        if key_str in self.linestyle_vars:
                            self.linestyle_vars[key_str].set(style.get("linestyle", self.linestyle_vars[key_str].get()))
                        if key_str in self.linewidth_vars:
                            self.linewidth_vars[key_str].set(style.get("linewidth", self.linewidth_vars[key_str].get()))
                        if key_str in self.legend_group_vars:
                            self.legend_group_vars[key_str].set(str(style.get("legend_group", 2)))
                        if key_str not in self.in_legend1_vars:
                            self.in_legend1_vars[key_str] = tk.BooleanVar(value=True)
                        self.in_legend1_vars[key_str].set(style.get("in_legend1", True))
                        if key_str not in self.marker_shape_vars:
                            self.marker_shape_vars[key_str] = tk.StringVar(value="None")
                        self.marker_shape_vars[key_str].set(style.get("marker_shape_label", "None"))
                        if key_str not in self.marker_size_vars:
                            self.marker_size_vars[key_str] = tk.StringVar(value="M")
                        self.marker_size_vars[key_str].set(style.get("marker_size_label", "M"))
                        if key_str not in self.marker_maxcount_vars:
                            self.marker_maxcount_vars[key_str] = tk.StringVar(value="")
                        self.marker_maxcount_vars[key_str].set(str(style.get("marker_max_count", "") or ""))
                        if key_str not in self.marker_fill_vars:
                            self.marker_fill_vars[key_str] = tk.BooleanVar(value=False)
                        self.marker_fill_vars[key_str].set(style.get("marker_fill", False))
                        axis = style.get("axis")
                        if axis == "y1" and key_str in self.selected_y1_vars:
                            self.selected_y1_vars[key_str].set(True)
                            if key_str in self.selected_y2_vars:
                                self.selected_y2_vars[key_str].set(False)
                        elif axis == "y2" and key_str in self.selected_y2_vars:
                            self.selected_y2_vars[key_str].set(True)
                            if key_str in self.selected_y1_vars:
                                self.selected_y1_vars[key_str].set(False)
                self.sync_axis_labels()

            messagebox.showinfo("Template", "템플릿을 불러왔습니다.")
        except Exception as e:
            messagebox.showerror("Template", f"템플릿 불러오기 실패: {e}")

    def _build_plotdef_from_template_data(self, data):
        """템플릿 JSON(파일/변수 지정 + 스타일 전부 포함)만으로, 화면 상태를 전혀
        건드리지 않고 완전한 PlotDefinition을 직접 만든다. self.xxx_var.get() 같은
        Tkinter 위젯 접근을 전혀 하지 않으므로 백그라운드 스레드에서 호출해도 안전함
        (Batch Set에서 여러 템플릿을 순차 처리할 때 사용)."""
        file_assignments = data.get("file_assignments", [])
        if not file_assignments:
            raise ValueError("이 템플릿에는 파일/변수 지정(file_assignments)이 없습니다 "
                              "(Template Save 시 화면에 dat 파일이 로드되어 있지 않았을 수 있음).")

        style_by_no = {item["output_no"]: item for item in data.get("curve_styles", [])}

        curves = []
        default_x_output_no = 0
        for fa in file_assignments:
            rel_path = fa["filename"]
            abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(self.cwd, rel_path)
            if not os.path.exists(abs_path):
                raise FileNotFoundError(f"파일을 찾을 수 없습니다: {rel_path}")

            dat_info = self.parser.parse(abs_path)
            var_by_no = {v.output_no: v for v in dat_info.variables}

            x_output_no = fa.get("x_output_no") or 0
            default_x_output_no = x_output_no

            target_dat_file = abs_path
            try:
                # [수정 - 효율] 이미 위에서 parse()한 dat_info 재사용 - Batch Set이
                # 템플릿마다 이 함수를 호출하므로 파일당 중복 파싱이 누적됨.
                target_dat_file = self.resort_dat_file(abs_path, x_output_no, dat_info=dat_info)
            except Exception:
                target_dat_file = abs_path

            file_x_shift = float(fa.get("x_shift") or 0.0)

            for axis, var_list in (("y1", fa.get("y1_output_nos") or []),
                                    ("y2", fa.get("y2_output_nos") or [])):
                for var_item in var_list:
                    # 숫자(output_no) 형식이 기본이지만, 혹시 남아있는 예전 dict 형식도 방어적으로 지원
                    output_no = var_item["output_no"] if isinstance(var_item, dict) else var_item
                    style = style_by_no.get(output_no, {})
                    var_obj = var_by_no.get(output_no)
                    legend_text = var_obj.display_name if var_obj else f"var_{output_no}"
                    try:
                        curves.append(CurveDefinition(
                            dat_file=target_dat_file, output_no=output_no, title=legend_text, axis=axis,
                            x_shift=file_x_shift,
                            color=COLOR_MAP.get(style.get("color", ""), None),
                            linestyle=STYLE_MAP.get(style.get("linestyle", ""), None),
                            linewidth=float(style.get("linewidth") or 1.5),
                            x_output_no=x_output_no,
                            legend_group=int(style.get("legend_group", 1) or 1),
                            in_legend1=style.get("in_legend1", True),
                            marker_shape=self._resolve_marker_shape(style.get("marker_shape_label", "None"), style.get("marker_fill", False)),
                            marker_size=MARKER_SIZE_MAP.get(style.get("marker_size_label", "M"), 1.0),
                            marker_max_count=(int(style["marker_max_count"]) if str(style.get("marker_max_count", "")).strip() else None),
                        ))
                    except ValueError:
                        continue  # X/Y 번호가 같은 경우 등은 건너뜀

        if not curves:
            raise ValueError("이 템플릿에는 그릴 변수(Y1/Y2)가 없습니다.")

        head_label_map = {"nohead": "No head", "head": "Forward", "backhead": "Backhead", "heads": "Both heads"}

        return PlotDefinition(
            title=data.get("title", ""),
            xlabel=data.get("xlabel", ""), ylabel=data.get("ylabel", ""), y2label=data.get("y2label", ""),
            output_format="Batch",
            xauto=data.get("xauto", True), yauto=data.get("yauto", True), y2auto=data.get("y2auto", True),
            xlog=data.get("xlog", False), y1log=data.get("y1log", False), y2log=data.get("y2log", False),
            xfmt=data.get("xfmt", "Normal"), y1fmt=data.get("y1fmt", "Normal"), y2fmt=data.get("y2fmt", "Normal"),
            xmin=data.get("xmin", ""), xmax=data.get("xmax", ""),
            ymin=data.get("ymin", ""), ymax=data.get("ymax", ""),
            y2min=data.get("y2min", ""), y2max=data.get("y2max", ""),
            xtics=data.get("xtics", ""), ytics=data.get("ytics", ""), y2tics=data.get("y2tics", ""),
            mxtics=data.get("mxtics", ""), mytics=data.get("mytics", ""), my2tics=data.get("my2tics", ""),
            major_grid=data.get("major_grid", True), minor_grid=data.get("minor_grid", False),
            legend_on=data.get("legend_on", True), legend_box=data.get("legend_box", True),
            legend_pos=data.get("legend_pos", "right top"),
            legend_align=data.get("legend_align", "Auto"),
            legend_thick=data.get("legend_thick", "1.5"),
            legend_font=data.get("legend_font", "Malgun Gothic"), legend_size=data.get("legend_size", "9"),
            legend_box_width_pct=data.get("legend_box_width_pct", ""),
            legend_box_height_pct=data.get("legend_box_height_pct", ""),
            legend2_on=data.get("legend2_on", False), legend2_box=data.get("legend2_box", True),
            legend2_pos=data.get("legend2_pos", "right bottom"), legend2_thick=data.get("legend2_thick", "1.5"),
            legend2_align=data.get("legend2_align", "Auto"),
            legend2_box_width_pct=data.get("legend2_box_width_pct", ""),
            legend2_box_height_pct=data.get("legend2_box_height_pct", ""),
            title_font=data.get("title_font", "Malgun Gothic"), title_size=data.get("title_size", "14"),
            xlabel_font=data.get("xlabel_font", "Malgun Gothic"), xlabel_size=data.get("xlabel_size", "11"),
            ylabel_font=data.get("ylabel_font", "Malgun Gothic"), ylabel_size=data.get("ylabel_size", "11"),
            y2label_font=data.get("y2label_font", "Malgun Gothic"), y2label_size=data.get("y2label_size", "11"),
            frame_auto=data.get("frame_auto", True), frame_width=data.get("frame_width", ""),
            frame_height=data.get("frame_height", ""), frame_unit=data.get("frame_unit", "in"),
            curves=curves,
            annotations=(
                [{"text": c["txt"], "x": c["x"], "y": c["y"], "angle": c["ang"],
                  "coord_mode": c.get("coord_mode", "pct"), "color": COLOR_MAP.get(c.get("color", "Auto"), "")}
                 for c in data.get("annotations", [])]
                if data.get("comment_on", True) else []
            ),
            arrows=(
                [{"x1": a["x1"], "y1": a["y1"], "x2": a["x2"], "y2": a["y2"],
                  "head": head_label_map.get(a["type"], "Forward"),
                  "coord_mode": a.get("coord_mode", "pct"), "color": COLOR_MAP.get(a.get("color", "Auto"), ""),
                  "head_size": self.ARROW_SIZE_MAP.get(a.get("size", "M"), self.ARROW_SIZE_MAP["M"])}
                 for a in data.get("arrows", [])]
                if data.get("arrow_on", True) else []
            ),
            circles=(
                [{"x": e["x"], "y": e["y"], "rx": e["rx"], "ry": e.get("ry", ""),
                  "coord_mode": e.get("coord_mode", "pct"), "color": COLOR_MAP.get(e.get("color", "Auto"), "")}
                 for e in data.get("circles", [])]
                if data.get("circle_on", True) else []
            ),
            is_print_mode=True,
            x_output_no=default_x_output_no,
            extra_gnuplot=data.get("extra_gnuplot", ""),
        )

    def open_batch_set_dialog(self):
        """여러 개의 '완전한' Template(*.json - dat 파일명+변수 지정까지 포함)을
        모아서, 순서대로 각각 이미지로 저장하는 배치. Batch Queue(하나의 레시피를
        여러 파일에 적용)와 달리, 여기서는 각 Template 자체가 이미 파일까지
        지정된 완전한 plot 하나씩을 의미한다."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Batch Set - 여러 Template을 순서대로 이미지로")
        dlg.geometry("640x480")

        ttk.Label(
            dlg,
            text="각 Template(*.json)에는 dat 파일명과 X/Y1/Y2 변수 지정, 스타일이\n"
                 "전부 들어있어야 합니다 (파일을 불러온 상태에서 Template Save로 생성).\n"
                 "목록 순서대로 처리되며, 결과는 각 Template의 Plot File Name 기준으로 저장됩니다.",
            justify="left"
        ).pack(fill="x", padx=10, pady=(10, 5))

        template_dir = os.path.join(self.cwd, "template")
        os.makedirs(template_dir, exist_ok=True)

        queue_list = []
        listbox = tk.Listbox(dlg, width=90, height=14)
        listbox.pack(fill="both", expand=True, padx=10, pady=5)

        def add_files():
            paths = filedialog.askopenfilenames(
                initialdir=template_dir,
                filetypes=[("CathPlot Template", "*.json"), ("All files", "*.*")],
                title="Batch Set에 추가할 Template 파일 선택 (여러 개 선택 가능)"
            )
            for p in paths:
                queue_list.append(p)
                listbox.insert("end", os.path.basename(p))

        def remove_selected():
            for idx in reversed(listbox.curselection()):
                listbox.delete(idx)
                del queue_list[idx]

        def move(delta):
            sel = listbox.curselection()
            if not sel:
                return
            i = sel[0]
            j = i + delta
            if j < 0 or j >= len(queue_list):
                return
            queue_list[i], queue_list[j] = queue_list[j], queue_list[i]
            text_i, text_j = listbox.get(i), listbox.get(j)
            listbox.delete(min(i, j), max(i, j))
            first, second = (text_j, text_i) if i < j else (text_i, text_j)
            listbox.insert(min(i, j), first)
            listbox.insert(max(i, j), second)
            listbox.selection_set(j)

        # [추가 - 요청] "Batch Set 순서를 txt 파일로 저장/불러오기, 필요하면
        # 직접 수정해서 재사용" - 지금까지는 Batch Set을 열 때마다 매번
        # Template을 수동으로 다시 추가/재정렬해야 했음. 한 줄에 Template
        # 파일 하나씩(template 폴더 기준 상대경로 - 메모장 등으로 직접 열어
        # 고치기 쉽도록) 적은 평범한 txt로 저장해서, 다음에 그 파일을
        # 불러오면 같은 순서로 순식간에 복원된다.
        def save_list():
            if not queue_list:
                messagebox.showwarning("Batch Set", "저장할 Template이 없습니다.", parent=dlg)
                return
            path = filedialog.asksaveasfilename(
                parent=dlg, initialdir=template_dir, defaultextension=".txt",
                filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
                title="Batch Set 순서를 파일로 저장"
            )
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as f:
                    for p in queue_list:
                        try:
                            rel = os.path.relpath(p, template_dir)
                            # template 폴더 밖으로 나가는 상대경로(..으로 시작)면
                            # 나중에 다른 PC/폴더에서 깨지기 쉬우니 절대경로로 남김
                            line = rel if not rel.startswith("..") else p
                        except ValueError:
                            line = p  # 드라이브가 달라 relpath 자체가 안 되는 경우
                        f.write(line + "\n")
            except OSError as e:
                messagebox.showerror("Batch Set", f"저장 실패:\n{e}", parent=dlg)

        def load_list():
            path = filedialog.askopenfilename(
                parent=dlg, initialdir=template_dir,
                filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
                title="Batch Set 순서 파일 불러오기 (기존 목록 뒤에 추가됨)"
            )
            if not path:
                return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = [ln.strip() for ln in f if ln.strip()]
            except OSError as e:
                messagebox.showerror("Batch Set", f"불러오기 실패:\n{e}", parent=dlg)
                return
            missing = []
            for line in lines:
                p = line if os.path.isabs(line) else os.path.join(template_dir, line)
                p = os.path.normpath(p)
                if os.path.exists(p):
                    queue_list.append(p)
                    listbox.insert("end", os.path.basename(p))
                else:
                    missing.append(line)
            if missing:
                messagebox.showwarning(
                    "Batch Set",
                    "다음 항목은 파일을 찾을 수 없어 건너뛰었습니다:\n" + "\n".join(missing),
                    parent=dlg
                )

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=10, pady=5)
        ttk.Button(btn_row, text="+ Add Templates...", command=add_files).pack(side="left", padx=5)
        ttk.Button(btn_row, text="Remove Selected", command=remove_selected).pack(side="left", padx=5)
        ttk.Button(btn_row, text="▲", width=3, command=lambda: move(-1)).pack(side="left", padx=2)
        ttk.Button(btn_row, text="▼", width=3, command=lambda: move(1)).pack(side="left", padx=2)

        # [추가 - 요청] "저장해둔 순서 목록 파일을 메모장으로 열어 직접
        # 고칠 수 있게" - 평범한 txt라 메모장으로 바로 열어 손으로 순서를
        # 바꾸거나 항목을 지울 수 있음(고친 뒤엔 Load List로 다시 불러오면
        # 됨 - 자동 반영은 아님, 새로 여닫는 흐름을 그대로 따르는 게
        # 단순함).
        def edit_list_notepad():
            path = filedialog.askopenfilename(
                parent=dlg, initialdir=template_dir,
                filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
                title="Batch Set 순서 파일을 메모장으로 열기"
            )
            if not path:
                return
            try:
                subprocess.Popen(["notepad.exe", path])
            except OSError as e:
                messagebox.showerror("Batch Set", f"메모장 실행 실패:\n{e}", parent=dlg)

        btn_row2 = ttk.Frame(dlg)
        btn_row2.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Button(btn_row2, text="Save List...", command=save_list).pack(side="left", padx=5)
        ttk.Button(btn_row2, text="Load List...", command=load_list).pack(side="left", padx=5)
        ttk.Button(btn_row2, text="Edit in Notepad...", command=edit_list_notepad).pack(side="left", padx=5)

        ttk.Label(btn_row, text="Format:").pack(side="left", padx=(20, 2))
        # [수정] "Word 등에 이미지로 넣으려면 pdf는 안 되고, 가볍고 품질 좋은
        # png가 default여야 함" - 기본 포맷을 png로 변경, jpg 추가, 순서를
        # png/pdf/jpg/svg/emf/eps로 통일.
        fmt_var = tk.StringVar(value="png")
        ttk.Combobox(
            btn_row, textvariable=fmt_var, values=["png", "pdf", "jpg", "svg", "emf", "eps"],
            width=6, state="readonly"
        ).pack(side="left")

        # [추가] "3D도 Batch에 연동" - 2D Template 각각에 3D curve/surface 적격
        # 조건(Y1 1개+Y2 1개, 또는 surface)이 있으면, 여기서 고른 3D Template(회전각/
        # Style/Marker 등)을 그대로 적용해서 3D 이미지도 같이 만든다. 3D Template은
        # 파일/변수 지정을 안 담고 있어서(3D 팝업에서 그때그때 로드된 걸 쓰는 방식) 여기
        # 목록의 모든 항목에 공통으로 적용되는 "하나"만 고르게 한다(항목별로 다른 3D
        # Template을 쓰려면 나중에 필요시 확장).
        td3_row = ttk.Frame(dlg)
        td3_row.pack(fill="x", padx=10, pady=(0, 5))
        td3_path_var = tk.StringVar(value="")
        ttk.Label(td3_row, text="3D Template(선택하면 3D도 같이 렌더링):").pack(side="left")
        td3_label = ttk.Label(td3_row, text="(3D Template 없음)", foreground="#555555")
        td3_label.pack(side="left", padx=5)

        def pick_3d_template():
            p = filedialog.askopenfilename(
                initialdir=template_dir,
                filetypes=[("CathPlot 3D Template", "*.json"), ("All files", "*.*")],
                title="3D Template 선택 (Batch Set 전체 항목에 공통 적용)"
            )
            if p:
                td3_path_var.set(p)
                td3_label.config(text=os.path.basename(p), foreground="black")

        ttk.Button(td3_row, text="선택...", command=pick_3d_template).pack(side="left", padx=5)
        ttk.Button(td3_row, text="해제", command=lambda: (td3_path_var.set(""), td3_label.config(text="(3D Template 없음)", foreground="#555555"))).pack(side="left")

        def run_batch_set():
            if not queue_list:
                messagebox.showwarning("Batch Set", "먼저 Template 파일을 추가하세요.")
                return
            dlg.destroy()
            self._run_batch_set_async(list(queue_list), fmt_var.get(), td3_path_var.get() or None)

        run_row = ttk.Frame(dlg)
        run_row.pack(fill="x", padx=10, pady=10)
        ttk.Button(run_row, text="취소", command=dlg.destroy).pack(side="right", padx=5)
        ttk.Button(run_row, text="Run Batch Set", command=run_batch_set).pack(side="right", padx=5)

    def _render_3d_from_template_data(self, data, td3_data, outfile, fmt):
        """[추가] "3D도 Batch에 연동" - 2D Template의 data(file_assignments/
        surface_files)로 3D curve/surface를 derive하고, 3D Template(td3_data)의
        설정(회전각/Style/Palette/Marker/Comment 등)을 그대로 적용해서 3D 이미지를
        만든다. Tkinter 위젯 접근이 없어 백그라운드 스레드에서 호출해도 안전함.
        curve/surface가 하나도 없으면(적격 조건 안 맞음) 조용히 스킵(None 반환)."""
        eligible, _skipped = self._build_3d_curves_from_template_data(data)
        surfaces = self._build_3d_surfaces_from_template_data(data)
        if not eligible and not surfaces:
            return None

        # [수정] "Marker Size, Style을 세트별로" - 3D Template의 marker_shapes와
        # 같은 방식(label 기준 dict)으로 저장된 marker_sizes/styles를 그대로 씀
        # (예전 템플릿에 있던 전역 marker_size/style 키는 없으면 기본값으로 대체).
        shapes = td3_data.get("marker_shapes", {})
        sizes = td3_data.get("marker_sizes", {})
        styles = td3_data.get("styles", {})
        _legacy_size = MARKER_SIZE_MAP.get(td3_data.get("marker_size", "M"), 1.0)
        _legacy_style = STYLE_3D_INTERNAL_MAP.get(td3_data.get("style", "Lines"), "lines")

        def _with_marker(item):
            item = dict(item)
            hollow_pt, _ = MARKER_SHAPE_MAP.get(shapes.get(item["label"], "Circle"), (None, None))
            item["marker_shape"] = hollow_pt
            item["marker_size"] = MARKER_SIZE_MAP.get(sizes.get(item["label"], ""), _legacy_size)
            item["style"] = STYLE_3D_INTERNAL_MAP.get(styles.get(item["label"], ""), _legacy_style)
            item["title"] = item["label"]
            return item

        curves_final = [_with_marker(c) for c in eligible]
        surfaces_final = [_with_marker(s) for s in surfaces]

        def _parse_opt_float(s):
            s = (s or "").strip()
            if not s:
                return None
            try:
                return float(s)
            except ValueError:
                return None

        annotations_3d = [
            {"text": a["txt"], "x": a["x"], "y": a["y"], "z": a["z"], "color": COLOR_MAP.get(a.get("color", "Auto"), "")}
            for a in td3_data.get("annotations_3d", []) if a.get("txt", "").strip()
        ]
        arrows_3d = [
            {"x1": a["x1"], "y1": a["y1"], "z1": a["z1"], "x2": a["x2"], "y2": a["y2"], "z2": a["z2"],
             "color": COLOR_MAP.get(a.get("color", "Auto"), ""),
             "head_size": self.ARROW_SIZE_MAP.get(a.get("size", "M"), self.ARROW_SIZE_MAP["M"])}
            for a in td3_data.get("arrows_3d", [])
        ]

        zlabel = td3_data.get("zlabel3d", "")
        if not zlabel and surfaces_final:
            zlabel = surfaces_final[0].get("z_label", "")

        try:
            rot_x = float(td3_data.get("rot_x") or 60)
        except (TypeError, ValueError):
            rot_x = 60
        try:
            rot_z = float(td3_data.get("rot_z") or 30)
        except (TypeError, ValueError):
            rot_z = 30

        generator = GnuplotGenerator(self.plot_dir)
        generator.create_3d_script(
            curves_final, outfile, fmt=fmt,
            xlabel=td3_data.get("xlabel3d") or "Time", ylabel=td3_data.get("ylabel3d") or "Data_No", zlabel=zlabel,
            title=td3_data.get("plot_title") or "CathPlot",
            xlog=data.get("xlog", False), ylog=data.get("y1log", False), zlog=data.get("y2log", False),
            rot_x=rot_x, rot_z=rot_z,
            style=_legacy_style,
            palette=td3_data.get("palette", "rainbow"), colorbox=td3_data.get("colorbox", True),
            annotations_3d=annotations_3d, arrows_3d=arrows_3d, equal_xyz=td3_data.get("equal_xyz", False),
            surfaces=surfaces_final,
            time_min=_parse_opt_float(td3_data.get("time_min", "")), time_max=_parse_opt_float(td3_data.get("time_max", "")),
            y_min=_parse_opt_float(td3_data.get("y_min", "")), y_max=_parse_opt_float(td3_data.get("y_max", "")),
            z_min=_parse_opt_float(td3_data.get("z_min", "")), z_max=_parse_opt_float(td3_data.get("z_max", "")),
        )
        return outfile

    def _process_one_batch_set_item(self, tpath, fmt, td3_data):
        """_run_batch_set의 항목 하나(템플릿 1개)를 처리해서 결과를 dict로
        반환한다(공유 리스트에 직접 쓰지 않음 - ThreadPoolExecutor로 여러
        항목을 동시에 처리해도, 결과 취합은 항상 메인(관리) 스레드의
        as_completed 루프 한 곳에서만 일어나 경쟁이 없다)."""
        import json
        tname = os.path.basename(tpath)
        res = {"tname": tname, "saved": False, "saved_3d": False, "warnings": [], "errors": []}

        try:
            with open(tpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            res["errors"].append(f"{tname}: 템플릿 읽기 실패 ({e})")
            return res

        try:
            plotdef = self._build_plotdef_from_template_data(data)
        except Exception as e:
            res["errors"].append(f"{tname}: {e}")
            return res

        raw_name = (data.get("filename") or "").strip() or os.path.splitext(tname)[0]
        safe_name = "".join(c for c in raw_name if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"
        outfile = os.path.join(self.plot_dir, f"{safe_name}_batchset.{fmt}")

        try:
            plotdef, font_warn = self._check_and_fix_fonts(plotdef)
            generator = GnuplotGenerator(self.plot_dir)
            generator.create_script(plotdef, outfile, fmt=fmt,
                                     annotations=plotdef.annotations, arrows=plotdef.arrows,
                                     circles=getattr(plotdef, "circles", []))
            res["saved"] = True
            for w in font_warn + generator.warnings:
                res["warnings"].append(f"{tname}: {w}")
        except Exception as e:
            res["errors"].append(f"{tname}: 저장 실패 ({e})")

        if td3_data is not None:
            outfile_3d = os.path.join(self.plot_dir, f"{safe_name}_batchset_3D.{fmt}")
            try:
                result = self._render_3d_from_template_data(data, td3_data, outfile_3d, fmt)
                if result:
                    res["saved_3d"] = True
                else:
                    res["warnings"].append(f"{tname}: 3D 적격 조건(Y1 1개+Y2 1개, 또는 surface)에 맞는 파일이 없어 3D는 스킵")
            except Exception as e:
                res["errors"].append(f"{tname}: 3D 저장 실패 ({e})")

        return res

    def _run_batch_set(self, template_paths, fmt, progress_callback=None, td3_path=None):
        """template_paths(각각 완전한 plot 사양이 담긴 *.json)를 병렬로 처리해서
        이미지로 저장한다. self.xxx_var.get() 같은 Tkinter 접근을 안 하므로
        백그라운드 스레드에서 호출해도 안전함.
        [추가] td3_path가 있으면(3D Template *.json), 각 항목의 file_assignments/
        surface_files로 derive한 3D curve/surface에 그 3D Template 설정을 적용해서
        3D 이미지도 같이 만든다(적격 조건 안 맞는 항목은 조용히 스킵).
        [수정 - 효율] 항목마다 완전히 독립적인 gnuplot 프로세스라 순차 실행이
        불필요했음 - ThreadPoolExecutor(_BATCH_MAX_WORKERS)로 동시에 처리한다.
        진행률/경고/오류 리스트는 각 작업자가 직접 건드리지 않고 결과 dict만
        반환하며, 취합은 아래 as_completed 루프(이 함수를 부르는 스레드 하나)
        에서만 일어나 경쟁이 없다. resort_dat_file의 정렬 캐시 파일 경쟁은
        _get_resort_lock(파일별 lock)으로 별도 보호된다."""
        import json

        saved_count = 0
        saved_3d_count = 0
        errors = []
        warnings = []
        total = len(template_paths)

        td3_data = None
        if td3_path:
            try:
                with open(td3_path, "r", encoding="utf-8") as f:
                    td3_data = json.load(f)
            except Exception as e:
                errors.append(f"3D Template 읽기 실패 ({os.path.basename(td3_path)}): {e} - 3D 렌더링 없이 계속 진행")
                td3_path = None
                td3_data = None

        done = 0
        with ThreadPoolExecutor(max_workers=_BATCH_MAX_WORKERS) as executor:
            futures = {
                executor.submit(self._process_one_batch_set_item, tpath, fmt, td3_data): tpath
                for tpath in template_paths
            }
            for future in as_completed(futures):
                done += 1
                tpath = futures[future]
                try:
                    res = future.result()
                except Exception as e:
                    res = {"tname": os.path.basename(tpath), "saved": False, "saved_3d": False,
                           "warnings": [], "errors": [f"{os.path.basename(tpath)}: 처리 실패 ({e})"]}
                if res["saved"]:
                    saved_count += 1
                if res["saved_3d"]:
                    saved_3d_count += 1
                warnings.extend(res["warnings"])
                errors.extend(res["errors"])
                if progress_callback:
                    progress_callback(done, total, res["tname"])

        msg = f"{saved_count}개 Template 처리 완료. (plot_dir: {self.plot_dir})"
        if td3_path:
            msg += f"\n3D 이미지 {saved_3d_count}개 추가 생성됨."
        if errors:
            msg += "\n\n오류:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n... 외 {len(errors) - 10}개"
        log_path = self._log_batch_warnings(warnings)
        if log_path:
            msg += f"\n\n경고 {len(warnings)}건이 로그에 기록되었습니다: {log_path}"
        self.root.after(0, lambda m=msg: messagebox.showinfo("Batch Set", m))

    def _run_batch_set_async(self, template_paths, fmt, td3_path=None):
        """Batch Set을 백그라운드 스레드에서 실행하며 진행창을 보여준다."""
        progress_win = tk.Toplevel(self.root)
        progress_win.title("Batch Set 처리 중")
        progress_win.transient(self.root)

        total = len(template_paths)
        label_var = tk.StringVar(value=f"준비 중... (0/{total})")
        ttk.Label(progress_win, textvariable=label_var, padding=15, width=55).pack()
        progress_bar = ttk.Progressbar(progress_win, length=340, maximum=max(total, 1))
        progress_bar.pack(padx=15, pady=(0, 15))

        def progress_callback(done, total_n, current_name):
            def _update():
                if progress_win.winfo_exists():
                    label_var.set(f"처리 중: {current_name}  ({done}/{total_n})")
                    progress_bar["value"] = done
            self.root.after(0, _update)

        # [수정 - 버그] "_run_batch_set는 self.xxx_var.get()을 안 써서 백그라운드
        # 스레드에서 안전하다"는 docstring이 있었지만, 그 안에서 부르는
        # _check_and_fix_fonts -> _get_installed_font_names가 캐시가 비어있으면
        # (앱 켜자마자 바로 Batch Set부터 누른 경우) tkfont.families(self.root)로
        # 실제 Tcl 호출을 해서 메인 스레드가 아닌 곳에서 Tk와 통신하는 위반이
        # 있었음 - 스레드 시작 "전" 메인 스레드에서 미리 한 번 불러 캐시를
        # 채워두면 백그라운드 쪽은 항상 캐시 히트만 타서 안전해진다.
        self._get_installed_font_names()

        def worker():
            self._run_batch_set(template_paths, fmt, progress_callback=progress_callback, td3_path=td3_path)
            self.root.after(0, lambda: progress_win.destroy() if progress_win.winfo_exists() else None)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Batch Queue: 화면에서 지금 선택된 Y1/Y2/X (output_no=var_no 기준) 구성을
    # "레시피"로 캡처해서, 여러 dat 파일(상대경로)에 동일하게 적용하며
    # 각각 별도의 plot을 자동으로 만들어 저장한다.
    # ------------------------------------------------------------------
    def _capture_curve_recipe(self):
        """현재 화면에서 선택된 Y1/Y2 output_no(var_no) + 스타일과, X로 선택된 output_no를
        특정 파일명과 무관하게 레시피 형태로 추출한다."""
        recipe = []
        for key, var in self.selected_y1_vars.items():
            if var.get():
                _, out_no = key.split("||")
                recipe.append({
                    "output_no": int(out_no),
                    "axis": "y1",
                    "color": self.color_vars[key].get() if key in self.color_vars else "",
                    "linestyle": self.linestyle_vars[key].get() if key in self.linestyle_vars else "",
                    "linewidth": self.linewidth_vars[key].get() if key in self.linewidth_vars else "1.5",
                    "legend_group": int(self.legend_group_vars[key].get()) if key in self.legend_group_vars else 1,
                    "in_legend1": self.in_legend1_vars[key].get() if key in self.in_legend1_vars else True,
                    "marker_shape_label": self.marker_shape_vars[key].get() if key in self.marker_shape_vars else "None",
                    "marker_size_label": self.marker_size_vars[key].get() if key in self.marker_size_vars else "M",
                    "marker_max_count": (self.marker_maxcount_vars[key].get() if key in self.marker_maxcount_vars else ""),
                    "marker_fill": (self.marker_fill_vars[key].get() if key in self.marker_fill_vars else False),
                })
        for key, var in self.selected_y2_vars.items():
            if var.get():
                _, out_no = key.split("||")
                recipe.append({
                    "output_no": int(out_no),
                    "axis": "y2",
                    "color": self.color_vars[key].get() if key in self.color_vars else "",
                    "linestyle": self.linestyle_vars[key].get() if key in self.linestyle_vars else "",
                    "linewidth": self.linewidth_vars[key].get() if key in self.linewidth_vars else "1.5",
                    "legend_group": int(self.legend_group_vars[key].get()) if key in self.legend_group_vars else 1,
                    "in_legend1": self.in_legend1_vars[key].get() if key in self.in_legend1_vars else True,
                    "marker_shape_label": self.marker_shape_vars[key].get() if key in self.marker_shape_vars else "None",
                    "marker_size_label": self.marker_size_vars[key].get() if key in self.marker_size_vars else "M",
                    "marker_max_count": (self.marker_maxcount_vars[key].get() if key in self.marker_maxcount_vars else ""),
                    "marker_fill": (self.marker_fill_vars[key].get() if key in self.marker_fill_vars else False),
                })

        # X 선택: 화면에서 실제로 X가 선택된 파일이 있으면 그 output_no(var_no)를 사용, 없으면 0(Time)
        x_output_no = 0
        for info in self.file_rows:
            x_var_obj = info.get("x_var")
            if x_var_obj and hasattr(x_var_obj, "get"):
                val = x_var_obj.get()
                if val and "||" in val:
                    try:
                        x_output_no = int(val.split("||")[1])
                        break
                    except (ValueError, IndexError):
                        pass
        return recipe, x_output_no

    def _open_marker_settings_popup(self):
        """Marker 설정 팝업 - Y1/Y2로 선택된 각 curve마다 한 행씩, Shape(모양)/
        Size(크기)/Fill/Max Count(최대 마커 개수, 비우면 Auto)를 보여준다.
        헤더와 입력칸 정렬은 고정 픽셀 폭 프레임으로 맞춘다(변수 표의 Color/
        Style과 동일한 방식)."""
        popup = tk.Toplevel(self.root)
        popup.title("Marker Settings")
        popup.transient(self.root)

        CURVE_PX, SHAPE_PX, SIZE_PX, FILL_PX, MAX_PX = 160, 90, 55, 50, 65

        def _cell(parent, px, height=20):
            f = tk.Frame(parent, width=px, height=height)
            f.pack_propagate(False)
            f.pack(side="left")
            return f

        header_f = ttk.Frame(popup)
        header_f.pack(fill="x", padx=10, pady=(10, 2))
        ttk.Label(_cell(header_f, CURVE_PX), text="Curve", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, SHAPE_PX), text="Shape", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, SIZE_PX), text="Size", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, FILL_PX), text="Fill", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, MAX_PX), text="Max#", font=("Consolas", 9, "bold")).pack(side="left")

        list_frame = ttk.Frame(popup)
        list_frame.pack(fill="both", expand=True, padx=10)

        # Max# 칸에는 정수만 입력되도록 (빈 값은 허용 - Auto 의미)
        vcmd = (popup.register(lambda s: s == "" or s.isdigit()), "%P")

        seen = set()
        any_added = False
        for key, var in list(self.selected_y1_vars.items()) + list(self.selected_y2_vars.items()):
            if not var.get() or key in seen:
                continue
            seen.add(key)
            any_added = True

            if key not in self.marker_shape_vars:
                self.marker_shape_vars[key] = tk.StringVar(value="None")
            if key not in self.marker_size_vars:
                self.marker_size_vars[key] = tk.StringVar(value="M")
            if key not in self.marker_maxcount_vars:
                self.marker_maxcount_vars[key] = tk.StringVar(value="")
            if key not in self.marker_fill_vars:
                self.marker_fill_vars[key] = tk.BooleanVar(value=False)

            label = self.legend_vars[key].get() if key in self.legend_vars else key
            row_f = ttk.Frame(list_frame)
            row_f.pack(fill="x", pady=1)

            curve_cell = _cell(row_f, CURVE_PX)
            ttk.Label(curve_cell, text=label).pack(side="left")

            shape_cell = _cell(row_f, SHAPE_PX)
            shape_combo = ttk.Combobox(shape_cell, textvariable=self.marker_shape_vars[key],
                                        values=MARKER_SHAPE_LIST, state="readonly")
            shape_combo.pack(side="left", fill="both", expand=True)
            self._disable_combobox_wheel(shape_combo)

            size_cell = _cell(row_f, SIZE_PX)
            size_combo = ttk.Combobox(size_cell, textvariable=self.marker_size_vars[key],
                                       values=MARKER_SIZE_LIST, state="readonly")
            size_combo.pack(side="left", fill="both", expand=True)
            self._disable_combobox_wheel(size_combo)

            fill_cell = _cell(row_f, FILL_PX)
            self._mk_check(fill_cell, "", self.marker_fill_vars[key], side="left")

            max_cell = _cell(row_f, MAX_PX)
            ttk.Entry(max_cell, textvariable=self.marker_maxcount_vars[key],
                      validate="key", validatecommand=vcmd).pack(side="left", fill="both", expand=True)

        if not any_added:
            ttk.Label(list_frame, text="(선택된 Y1/Y2 변수 없음)").pack(padx=5, pady=10)

        ttk.Label(
            popup, text="Shape=None이면 마커 없음. Max#를 비우면 자동(대략 20~30개, 데이터가 적으면 전부 표시). M 크기 = pointsize 1.0",
            foreground="#555555"
        ).pack(padx=10, pady=(4, 0), anchor="w")

        btn_row = ttk.Frame(popup)
        btn_row.pack(fill="x", padx=10, pady=8)
        ttk.Button(btn_row, text="완료", command=popup.destroy).pack(side="right")

    def _open_curve_select_popup(self, anchor_widget, title, get_checked, set_checked):
        """Legend1/Legend2 공용 curve 선택 팝업. get_checked(key)/set_checked(key, bool)로
        체크 상태를 읽고 쓴다 - Legend1은 in_legend1_vars(bool), Legend2는
        legend_group_vars(문자열 "1"/"2")를 각각 다르게 저장하지만 이 함수는
        그 차이를 신경 안 쓰고 동일하게 다룬다. tk.Menu와 달리 항목을 체크해도
        창이 안 닫혀서 여러 개를 한 번에 고를 수 있다."""
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.transient(self.root)
        x = anchor_widget.winfo_rootx()
        y = anchor_widget.winfo_rooty() + anchor_widget.winfo_height()
        popup.geometry(f"+{x}+{y}")

        list_frame = ttk.Frame(popup)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        keys = []
        seen = set()
        for key, var in list(self.selected_y1_vars.items()) + list(self.selected_y2_vars.items()):
            if not var.get() or key in seen:
                continue
            seen.add(key)
            keys.append(key)

        if not keys:
            ttk.Label(list_frame, text="(선택된 Y1/Y2 변수 없음)").pack(padx=5, pady=10)
        else:
            for key in keys:
                label = self.legend_vars[key].get() if key in self.legend_vars else key
                check_var = tk.BooleanVar(value=get_checked(key))

                def _toggle(cv=check_var, k=key):
                    set_checked(k, cv.get())

                self._mk_check(list_frame, label, check_var, command=_toggle, anchor="w", pady=1)

        def select_all():
            for key in keys:
                set_checked(key, True)
            popup.destroy()
            self._open_curve_select_popup(anchor_widget, title, get_checked, set_checked)

        def select_none():
            for key in keys:
                set_checked(key, False)
            popup.destroy()
            self._open_curve_select_popup(anchor_widget, title, get_checked, set_checked)

        btn_row = ttk.Frame(popup)
        btn_row.pack(fill="x", padx=10, pady=8)
        ttk.Button(btn_row, text="전체 선택", command=select_all).pack(side="left", padx=(0, 5))
        ttk.Button(btn_row, text="전체 해제", command=select_none).pack(side="left")
        ttk.Button(btn_row, text="닫기", command=popup.destroy).pack(side="right")

    def open_batch_queue_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Batch Queue - 여러 파일 자동 처리")
        dlg.geometry("640x420")

        ttk.Label(
            dlg,
            text="지금 화면에서 선택된 Y1/Y2/X (var_no 기준)와 스타일이 아래 파일들에 그대로 적용됩니다.\n"
                 "경로는 CathPlot 실행 폴더 기준 상대경로로 표시됩니다.\n"
                 "팁: 먼저 'Template Load...'로 스타일을 불러온 뒤 Run Batch 하면 그 스타일 그대로 적용됩니다.",
            justify="left"
        ).pack(fill="x", padx=10, pady=(10, 5))

        queue_list = []
        listbox = tk.Listbox(dlg, width=90, height=14)
        listbox.pack(fill="both", expand=True, padx=10, pady=5)

        def add_files():
            paths = filedialog.askopenfilenames(
                initialdir=self.cwd,
                filetypes=[("DAT files", "*.dat"), ("All files", "*.*")],
                title="Batch 처리할 dat 파일 선택 (여러 개 선택 가능)"
            )
            for p in paths:
                try:
                    rel = os.path.relpath(p, self.cwd)
                except ValueError:
                    rel = p  # 다른 드라이브 등으로 relpath 불가한 경우 절대경로 유지
                queue_list.append(rel)
                listbox.insert("end", rel)

        def remove_selected():
            for idx in reversed(listbox.curselection()):
                listbox.delete(idx)
                del queue_list[idx]

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=10, pady=5)
        ttk.Button(btn_row, text="+ Add Files...", command=add_files).pack(side="left", padx=5)
        ttk.Button(btn_row, text="Remove Selected", command=remove_selected).pack(side="left", padx=5)
        ttk.Button(btn_row, text="Template Load", command=self.load_template).pack(side="left", padx=5)

        ttk.Label(btn_row, text="Format:").pack(side="left", padx=(20, 2))
        # [수정] "Word 등에 이미지로 넣으려면 pdf는 안 되고, 가볍고 품질 좋은
        # png가 default여야 함" - 기본 포맷을 png로 변경, jpg 추가, 순서를
        # png/pdf/jpg/svg/emf/eps로 통일.
        fmt_var = tk.StringVar(value="png")
        ttk.Combobox(
            btn_row, textvariable=fmt_var, values=["png", "pdf", "jpg", "svg", "emf", "eps"],
            width=6, state="readonly"
        ).pack(side="left")

        def run_batch():
            if not queue_list:
                messagebox.showwarning("Batch Queue", "처리할 파일을 먼저 추가하세요.")
                return
            dlg.destroy()
            self._run_batch_queue_async(list(queue_list), fmt_var.get())

        run_row = ttk.Frame(dlg)
        run_row.pack(fill="x", padx=10, pady=10)
        ttk.Button(run_row, text="취소", command=dlg.destroy).pack(side="right", padx=5)
        ttk.Button(run_row, text="Run Batch", command=run_batch).pack(side="right", padx=5)

    def _capture_batch_queue_settings(self):
        """Batch Queue 실행에 필요한 화면 설정을 전부 미리 읽어서 일반 dict로
        캡처한다. _run_batch_queue는 백그라운드 스레드에서 실행되는데, Tkinter는
        스레드 안전하지 않아 변수(.get())는 반드시 메인 스레드에서 먼저 읽어둬야
        한다 - 그래서 스레드를 시작하기 전에(메인 스레드에서) 이 함수를 호출한다."""
        recipe, x_output_no = self._capture_curve_recipe()
        return {
            "recipe": recipe,
            "x_output_no": x_output_no,
            "xlabel": self.xlabel_var.get(),
            "ylabel": self.ylabel_var.get(),
            "y2label": self.y2label_var.get(),
            "xauto": self.xauto_var.get(), "yauto": self.yauto_var.get(), "y2auto": self.y2auto_var.get(),
            "xlog": self.xlog_var.get(), "y1log": self.y1log_var.get(), "y2log": self.y2log_var.get(),
            "xfmt": self.xfmt_var.get(), "y1fmt": self.y1fmt_var.get(), "y2fmt": self.y2fmt_var.get(),
            "xmin": self.xmin_var.get(), "xmax": self.xmax_var.get(),
            "ymin": self.ymin_var.get(), "ymax": self.ymax_var.get(),
            "y2min": self.y2min_var.get(), "y2max": self.y2max_var.get(),
            "xtics": self.xtics_var.get(), "ytics": self.ytics_var.get(), "y2tics": self.y2tics_var.get(),
            "mxtics": self.mxtics_var.get(), "mytics": self.mytics_var.get(), "my2tics": self.my2tics_var.get(),
            "major_grid": self.major_grid_var.get(), "minor_grid": self.minor_grid_var.get(),
            "legend_on": self.legend_on_var.get(), "legend_box": self.legend_box_var.get(),
            "legend_pos": self.legend_pos_var.get(),
            "legend_align": self.legend_align_var.get(),
            "legend_thick": self.legend_thick_var.get(),
            "legend_font": self.legend_font_var.get(), "legend_size": self.legend_size_var.get(),
            "legend_box_width_pct": self.legend_box_width_pct_var.get(),
            "legend_box_height_pct": self.legend_box_height_pct_var.get(),
            "legend2_on": self.legend2_on_var.get(), "legend2_box": self.legend2_box_var.get(),
            "legend2_pos": self.legend2_pos_var.get(), "legend2_thick": self.legend_thick_var.get(),
            "legend2_align": self.legend2_align_var.get(),
            "legend2_box_width_pct": self.legend2_box_width_pct_var.get(),
            "legend2_box_height_pct": self.legend2_box_height_pct_var.get(),
            "title_font": self.title_font_var.get(), "title_size": self.title_size_var.get(),
            "xlabel_font": self.xlabel_font_var.get(), "xlabel_size": self.xlabel_size_var.get(),
            "ylabel_font": self.ylabel_font_var.get(), "ylabel_size": self.ylabel_size_var.get(),
            "y2label_font": self.y2label_font_var.get(), "y2label_size": self.y2label_size_var.get(),
            "frame_auto": self.frame_auto_var.get(), "frame_width": self.frame_width_var.get(),
            "frame_height": self.frame_height_var.get(), "frame_unit": self.frame_unit_var.get(),
            "extra_gnuplot": self.raw_gnuplot_text.get("1.0", "end-1c"),
        }

    def _process_one_batch_queue_item(self, rel_path, fmt, recipe, x_output_no, settings):
        """_run_batch_queue의 항목 하나(dat 파일 1개)를 처리해서 결과를 dict로
        반환한다 - _process_one_batch_set_item과 동일한 이유(ThreadPoolExecutor로
        병렬 처리해도 결과 취합은 as_completed 루프 한 곳에서만 하기 위함)."""
        res = {"rel_path": rel_path, "saved": False, "warnings": [], "errors": []}

        abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(self.cwd, rel_path)
        if not os.path.exists(abs_path):
            res["errors"].append(f"{rel_path}: 파일 없음")
            return res

        try:
            dat_info = self.parser.parse(abs_path)
        except Exception as e:
            res["errors"].append(f"{rel_path}: 파싱 실패 ({e})")
            return res

        target_dat_file = abs_path
        try:
            # [수정 - 효율] 위에서 이미 parse()한 dat_info를 그대로 넘겨서
            # resort_dat_file 내부의 중복 파싱(+세 번째 전체 읽기)을 없앤다.
            target_dat_file = self.resort_dat_file(abs_path, x_output_no, dat_info=dat_info)
        except Exception:
            target_dat_file = abs_path

        var_by_no = {v.output_no: v for v in dat_info.variables}

        curves = []
        for item in recipe:
            var_obj = var_by_no.get(item["output_no"])
            legend_text = var_obj.display_name if var_obj else f"var_{item['output_no']}"
            try:
                curves.append(CurveDefinition(
                    dat_file=target_dat_file,
                    output_no=item["output_no"],
                    title=legend_text,
                    axis=item["axis"],
                    x_shift=float(item.get("x_shift") or 0.0),
                    color=COLOR_MAP.get(item["color"], None),
                    linestyle=STYLE_MAP.get(item["linestyle"], None),
                    linewidth=float(item["linewidth"] or 1.5),
                    x_output_no=x_output_no,
                    legend_group=int(item.get("legend_group", 1) or 1),
                    in_legend1=item.get("in_legend1", True),
                    marker_shape=self._resolve_marker_shape(item.get("marker_shape_label", "None"), item.get("marker_fill", False)),
                    marker_size=MARKER_SIZE_MAP.get(item.get("marker_size_label", "M"), 1.0),
                    marker_max_count=(int(item["marker_max_count"]) if str(item.get("marker_max_count", "")).strip() else None),
                ))
            except ValueError:
                continue  # X/Y 번호가 같은 경우 등은 건너뜀

        if not curves:
            res["errors"].append(f"{rel_path}: 매칭되는 var_no가 이 파일에 없음")
            return res

        plotdef = PlotDefinition(
            title="",  # Batch Queue에서는 title 기본 blank
            xlabel=settings["xlabel"],
            ylabel=settings["ylabel"],
            y2label=settings["y2label"],
            output_format="Batch",
            xauto=settings["xauto"], yauto=settings["yauto"], y2auto=settings["y2auto"],
            xlog=settings.get("xlog", False), y1log=settings.get("y1log", False), y2log=settings.get("y2log", False),
            xfmt=settings.get("xfmt", "Normal"), y1fmt=settings.get("y1fmt", "Normal"), y2fmt=settings.get("y2fmt", "Normal"),
            xmin=settings["xmin"], xmax=settings["xmax"],
            ymin=settings["ymin"], ymax=settings["ymax"],
            y2min=settings["y2min"], y2max=settings["y2max"],
            xtics=settings["xtics"], ytics=settings["ytics"], y2tics=settings["y2tics"],
            mxtics=settings["mxtics"], mytics=settings["mytics"], my2tics=settings["my2tics"],
            major_grid=settings["major_grid"], minor_grid=settings["minor_grid"],
            legend_on=settings["legend_on"], legend_box=settings["legend_box"],
            legend_pos=settings["legend_pos"],
            legend_align=settings.get("legend_align", "Auto"),
            legend_thick=settings.get("legend_thick", "1.5"),
            legend_font=settings.get("legend_font", "Malgun Gothic"), legend_size=settings.get("legend_size", "9"),
            legend_box_width_pct=settings.get("legend_box_width_pct", ""),
            legend_box_height_pct=settings.get("legend_box_height_pct", ""),
            legend2_on=settings.get("legend2_on", False), legend2_box=settings.get("legend2_box", True),
            legend2_pos=settings.get("legend2_pos", "right bottom"),
            legend2_align=settings.get("legend2_align", "Auto"),
            legend2_thick=settings.get("legend2_thick", "1.5"),
            legend2_box_width_pct=settings.get("legend2_box_width_pct", ""),
            legend2_box_height_pct=settings.get("legend2_box_height_pct", ""),
            title_font=settings["title_font"], title_size=settings["title_size"],
            xlabel_font=settings["xlabel_font"], xlabel_size=settings["xlabel_size"],
            ylabel_font=settings["ylabel_font"], ylabel_size=settings["ylabel_size"],
            y2label_font=settings["y2label_font"], y2label_size=settings["y2label_size"],
            frame_auto=settings["frame_auto"], frame_width=settings["frame_width"],
            frame_height=settings["frame_height"], frame_unit=settings["frame_unit"],
            curves=curves,
            annotations=[],  # Batch Queue에서는 annotation/arrow/circle 리셋
            arrows=[],
            circles=[],
            is_print_mode=True,
            x_output_no=x_output_no,
            extra_gnuplot=settings.get("extra_gnuplot", ""),
        )

        base_stem = os.path.splitext(os.path.basename(abs_path))[0]
        outfile = os.path.join(self.plot_dir, f"{base_stem}_batch.{fmt}")

        try:
            plotdef, font_warn = self._check_and_fix_fonts(plotdef)
            generator = GnuplotGenerator(self.plot_dir)
            generator.create_script(plotdef, outfile, fmt=fmt)
            res["saved"] = True
            for w in font_warn + generator.warnings:
                res["warnings"].append(f"{rel_path}: {w}")
        except Exception as e:
            res["errors"].append(f"{rel_path}: 저장 실패 ({e})")

        return res

    def _run_batch_queue(self, relative_paths, fmt, settings, progress_callback=None):
        """[수정 - 효율] _run_batch_set과 동일한 이유로 ThreadPoolExecutor로
        병렬 처리 - 자세한 설명은 _run_batch_set 및 _process_one_batch_set_item
        참고."""
        recipe = settings["recipe"]
        x_output_no = settings["x_output_no"]
        if not recipe:
            self.root.after(0, lambda: messagebox.showwarning(
                "Batch Queue",
                "먼저 화면에서 Y1/Y2 변수를 하나 이상 선택해두세요.\n(그 선택이 var_no 기준으로 각 파일에 그대로 적용됩니다.)"
            ))
            return

        saved_count = 0
        errors = []
        warnings = []
        total = len(relative_paths)

        done = 0
        with ThreadPoolExecutor(max_workers=_BATCH_MAX_WORKERS) as executor:
            futures = {
                executor.submit(self._process_one_batch_queue_item, rel_path, fmt, recipe, x_output_no, settings): rel_path
                for rel_path in relative_paths
            }
            for future in as_completed(futures):
                done += 1
                rel_path = futures[future]
                try:
                    res = future.result()
                except Exception as e:
                    res = {"rel_path": rel_path, "saved": False, "warnings": [], "errors": [f"{rel_path}: 처리 실패 ({e})"]}
                if res["saved"]:
                    saved_count += 1
                warnings.extend(res["warnings"])
                errors.extend(res["errors"])
                if progress_callback:
                    progress_callback(done, total, res["rel_path"])

        msg = f"{saved_count}개 파일 처리 완료. (plot_dir: {self.plot_dir})"
        if errors:
            msg += "\n\n오류:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n... 외 {len(errors) - 10}개"
        log_path = self._log_batch_warnings(warnings)
        if log_path:
            msg += f"\n\n경고 {len(warnings)}건이 로그에 기록되었습니다: {log_path}"
        self.root.after(0, lambda m=msg: messagebox.showinfo("Batch Queue", m))

    def _run_batch_queue_async(self, relative_paths, fmt):
        """Batch Queue를 백그라운드 스레드에서 실행하면서, 작은 진행창으로
        진행 상황(몇 번째 파일 처리 중인지)을 보여준다. 이렇게 하면 Run Batch를
        누른 뒤 전체 작업이 끝날 때까지 창이 응답 없이 붙잡혀 있지 않는다.
        화면 설정은 스레드를 시작하기 전에(메인 스레드에서) 미리 캡처해둔다."""
        settings = self._capture_batch_queue_settings()

        progress_win = tk.Toplevel(self.root)
        progress_win.title("Batch Queue 처리 중")
        progress_win.transient(self.root)

        total = len(relative_paths)
        label_var = tk.StringVar(value=f"준비 중... (0/{total})")
        ttk.Label(progress_win, textvariable=label_var, padding=15, width=50).pack()
        progress_bar = ttk.Progressbar(progress_win, length=320, maximum=max(total, 1))
        progress_bar.pack(padx=15, pady=(0, 15))

        def progress_callback(done, total_n, current_name):
            def _update():
                if progress_win.winfo_exists():
                    label_var.set(f"처리 중: {current_name}  ({done}/{total_n})")
                    progress_bar["value"] = done
            self.root.after(0, _update)

        # [수정 - 버그] _run_batch_set_async와 같은 이유 - _run_batch_queue도
        # _check_and_fix_fonts를 거치므로, 스레드 시작 전에 폰트 캐시를 미리
        # 채워 백그라운드에서 Tcl 호출(tkfont.families)이 일어나지 않게 한다.
        self._get_installed_font_names()

        def worker():
            self._run_batch_queue(relative_paths, fmt, settings, progress_callback=progress_callback)
            self.root.after(0, lambda: progress_win.destroy() if progress_win.winfo_exists() else None)

        threading.Thread(target=worker, daemon=True).start()

    def close_all_plot_windows(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Close All Plots")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(
            dlg,
            text="어떻게 닫으시겠습니까?",
            padding=15
        ).pack()

        def do_close(mode):
            dlg.destroy()

            if mode == "cancel":
                return

            if mode == "system_all":
                check = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq gnuplot.exe"],
                    capture_output=True, text=True, **_no_console_kwargs()
                )
                has_any = "gnuplot.exe" in check.stdout

                subprocess.run(["taskkill", "/F", "/IM", "gnuplot_qt.exe"], capture_output=True, **_no_console_kwargs())
                subprocess.run(["taskkill", "/F", "/IM", "gnuplot.exe"], capture_output=True, **_no_console_kwargs())
                self.plot_processes = []

                if has_any:
                    messagebox.showinfo("Close All Plots", "시스템의 모든 gnuplot 창을 닫았습니다.")
                else:
                    messagebox.showinfo("Close All Plots", "닫을 gnuplot 창이 없습니다.")
                return

            if mode == "keep_latest":
                targets = self.plot_processes[:-1]
                keep = self.plot_processes[-1:]
            else:
                targets = list(self.plot_processes)
                keep = []

            closed = 0
            still_alive = list(keep)
            for proc in targets:
                if proc.poll() is not None:
                    continue
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True, **_no_console_kwargs()
                    )
                    closed += 1
                except Exception:
                    still_alive.append(proc)

            self.plot_processes = still_alive

            if closed:
                messagebox.showinfo("Close All Plots", f"{closed}개의 plot 창을 닫았습니다.")
            else:
                messagebox.showinfo("Close All Plots", "닫을 plot 창이 없습니다.")

        btn_f = ttk.Frame(dlg, padding=10)
        btn_f.pack(fill="x")

        ttk.Button(
            btn_f, text="최신 창은 남기고 나머지만 닫기",
            command=lambda: do_close("keep_latest")
        ).pack(fill="x", pady=2)

        ttk.Button(
            btn_f, text="이 프로그램에서 연 창 전부 닫기",
            command=lambda: do_close("all_mine")
        ).pack(fill="x", pady=2)

        ttk.Button(
            btn_f, text="시스템의 모든 gnuplot 창 닫기",
            command=lambda: do_close("system_all")
        ).pack(fill="x", pady=2)

        ttk.Button(
            btn_f, text="취소", command=lambda: do_close("cancel")
        ).pack(fill="x", pady=(8, 2))

    def toggle_frame_size_state(self):
        state = "disabled" if self.frame_auto_var.get() else "normal"
        self.frame_width_entry.config(state=state)
        self.frame_height_entry.config(state=state)

    def add_file_row(self):
        var = tk.StringVar()
        #기존 idx = len(self.file_rows) vs file_x_var
        file_x_var = tk.StringVar(value="")  # 파일별 고유 X축(Time) 변수 생성
        row = ttk.Frame(self.file_scrollable_frame)
        info = {
            "frame": row, "var": var, "filename": "", "meta": None,
            "x_var": file_x_var  # <-- 파일별 딕셔너리에 X축 변수 장착
        }
        self.file_rows.append(info)
        row.pack(fill="x", padx=5, pady=0)

        ttk.Entry(row, textvariable=var, width=60).pack(side="left", padx=5)
        self._mk_btn(
            row, "Browse",
            lambda v=var, r_info=info: self.load_dat_file(v, r_info),
            color="secondary", side="left",
        )

        # [수정 - 요청] "Browse 버튼 높이는 X버튼과 같이 맞출 것" - ttk.Button
        # (Compact.TButton)과 tk.Button(_mk_btn)은 서로 다른 위젯 종류라 padding
        # 값만으로는 완전히 같은 높이를 보장할 수 없음(테마별 내부 chrome이
        # 다름) - X버튼도 Browse와 똑같이 _mk_btn(tk.Button, 동일한 bd/padx/
        # pady/font)으로 만들어 두 버튼이 항상 정확히 같은 높이가 되도록 함
        # (danger 색으로 삭제 버튼임을 표시).
        self._mk_btn(
            row, "X",
            lambda r_info=info: self.delete_dat_file_row(r_info),
            color="danger", side="left", padx=3,
        )

    def _purge_file_vars(self, datfile):
        # [추가 - 버그 수정] load_dat_file(파일 교체)과 delete_dat_file_row(행 삭제)가
        # 각자 따로 "{datfile}||"로 시작하는 키를 지우고 있었는데, delete_dat_file_row
        # 쪽이 legend_vars/selected_y1_vars/selected_y2_vars 3개만 지우고 나머지
        # 9개(color/linestyle/linewidth/legend_group/in_legend1/marker_*)는 안 지워서,
        # 삭제 후 같은 경로를 다시 불러오면 예전 Color/Linestyle 등이 유령처럼
        # 되살아나는 문제가 있었음 - 하나의 목록으로 통일해서 재사용한다.
        prefix = f"{datfile}||"
        for d in (
            self.legend_vars,
            self.selected_y1_vars,
            self.selected_y2_vars,
            self.color_vars,
            self.linestyle_vars,
            self.linewidth_vars,
            self.legend_group_vars,
            self.in_legend1_vars,
            self.marker_shape_vars,
            self.marker_size_vars,
            self.marker_maxcount_vars,
            self.marker_fill_vars,
        ):
            for key in list(d.keys()):
                if key.startswith(prefix):
                    del d[key]
        self.file_xshift_vars.pop(datfile, None)

    def load_dat_file(self, var, r_info):
        init_dir = self.last_opened_dir if (hasattr(self, 'last_opened_dir') and self.last_opened_dir) else self.cwd

        filename = filedialog.askopenfilename(
            initialdir=init_dir, title="Select DAT File",
            filetypes=[("DAT files", "*.dat"), ("All files", "*.*")]
        )
        if not filename:
            return
        filename = os.path.abspath(filename)
        self.last_opened_dir = os.path.dirname(filename)

        datfile = r_info["filename"]
        prefix = f"{datfile}||"

        self._purge_file_vars(datfile)

        # 파일별 X축 변수 초기화
        if r_info["x_var"].get().startswith(prefix):
            r_info["x_var"].set("")

        var.set(filename)
        r_info["filename"] = filename

        # 1. 파서 수행
        r_info["meta"] = self.parser.parse(filename)

        # 2. JSON 파일 생성 및 덮어쓰기 확인 팝업 로직
        jsonfile = Path(filename).with_suffix(".json")
        #if jsonfile.exists():
        #    if not messagebox.askyesno("File Exists", f"'{jsonfile.name}' already exists.\nDo you want to overwrite it?"):
        #        return
        save_json(r_info["meta"], jsonfile)

        # 3. 변수 리스트 UI 연동 로직 호출
        self.load_variables_to_ui(filename, r_info["meta"])

        self.update_title_from_first_file()
        self.show_variables()

    def load_variables_to_ui(self, dat_filepath, dat_info=None):
        if dat_info is None:
            parser = CathenaDatParser()
            dat_info = parser.parse(dat_filepath)

        if hasattr(self, 'var_listbox') and self.var_listbox:
            self.var_listbox.delete(0, tk.END)

            for var in dat_info.variables:
                col_no = getattr(var, 'output_no', getattr(var, 'data_column', 0))

                name_str = "Time" if col_no == 0 else f"OUTPUT {col_no}"
                if hasattr(var, 'display_name') and var.display_name and not var.display_name.startswith("var_"):
                    name_str = var.display_name
                elif hasattr(var, 'signals') and var.signals and var.signals[0].name:
                    name_str = var.signals[0].name

                display_text = f"[{col_no}] {name_str}"
                self.var_listbox.insert(tk.END, display_text)

    def delete_dat_file_row(self, r_info):
        if "frame" in r_info and r_info["frame"].winfo_exists():
            r_info["frame"].destroy()
        if r_info in self.file_rows:
            self.file_rows.remove(r_info)

        datfile = r_info["filename"]
        prefix = f"{datfile}||"

        self._purge_file_vars(datfile)

        if r_info["x_var"].get().startswith(prefix):
            r_info["x_var"].set("")

        self.update_title_from_first_file()
        self.show_variables()

    def update_title_from_first_file(self):
        # [수정] "s-plot dat를 먼저 불러 읽으면 2-D는 2-D관련 첫 dat file로부터
        # title을 정해야(일반 3-D 포함)" - surface(splot) 파일이 로드 순서상
        # 가장 먼저면 무조건 그 파일명을 title/filename_var로 썼는데, surface는
        # 2D 곡선과 무관한 완전히 다른 데이터라 2D(그리고 curve 기반 "일반 3D"의
        # Plot Title 기본값도 이 filename_var를 그대로 물려받음)에는 부적절함 -
        # surface가 아닌 첫 파일을 우선으로 찾고, 전부 surface일 때만(2D 관련
        # 파일이 하나도 없을 때) 첫 파일(=첫 surface) 그대로 사용한다.
        valid_files = [info for info in self.file_rows if info["filename"] and info["meta"]]
        non_surface_files = [info for info in valid_files if not getattr(info["meta"], "is_surface", False)]
        target_files = non_surface_files or valid_files
        if target_files:
            first_filename = target_files[0]["filename"]
            base_name = os.path.splitext(os.path.basename(first_filename))[0]
            self.title_var.set(base_name)
            self.filename_var.set(base_name)
        else:
            self.title_var.set("CathPlot")
            self.filename_var.set("CathPlot")

    # [추가] "%"(0~100 graph 비율)와 "좌표값"(실제 데이터 값, 화면 좌하단
    # 커서 좌표 그대로 입력) 두 모드를 각 행에서 토글로 고를 수 있게 한다 -
    # 대략적인 위치를 %로 어림잡기 어렵다는 요청으로 추가.
    COORD_MODE_DISPLAY = {"pct": "%", "data": "좌표값"}
    COORD_MODE_FROM_DISPLAY = {v: k for k, v in COORD_MODE_DISPLAY.items()}

    def _make_xyz_combo_entry(self, parent, x_var, y_var, z_var, init_x, init_y, init_z, width=14):
        """"(x,y,z)" 한 칸짜리 입력 - 3D Comment/Arrow 좌표용. _make_xy_combo_entry와
        같은 방식이나 3개 값을 다룬다."""
        xyz_var = tk.StringVar(value=f"{init_x},{init_y},{init_z}" if (init_x or init_y or init_z) else "")

        def _sync_from_xyz(*_):
            parts = xyz_var.get().split(",")
            x_var.set(parts[0].strip() if len(parts) > 0 else "")
            y_var.set(parts[1].strip() if len(parts) > 1 else "")
            z_var.set(parts[2].strip() if len(parts) > 2 else "")

        xyz_var.trace_add("write", _sync_from_xyz)
        entry = ttk.Entry(parent, textvariable=xyz_var, width=width)
        return entry, xyz_var

    def _make_xy_combo_entry(self, parent, x_var, y_var, init_x, init_y, width=10):
        """"(x,y)" 한 칸짜리 입력을 만들고, x_var/y_var(내부 저장용 StringVar)와
        서로 동기화한다. 입력칸이 너무 많다는 요청으로 X/Y 두 칸을 하나로
        합침 - 저장 포맷(개별 x/y 키)은 템플릿 호환을 위해 그대로 유지."""
        xy_var = tk.StringVar(value=f"{init_x},{init_y}" if (init_x or init_y) else "")

        def _sync_to_xy(*_):
            xy_var.set(f"{x_var.get()},{y_var.get()}")

        def _sync_from_xy(*_):
            parts = xy_var.get().split(",")
            x_var.set(parts[0].strip() if len(parts) > 0 else "")
            y_var.set(parts[1].strip() if len(parts) > 1 else "")

        xy_var.trace_add("write", _sync_from_xy)
        entry = self._mk_entry(parent, xy_var, width=width, color="amber")
        return entry, xy_var

    def add_comment_row(self, initial=None):
        init = initial or {}
        row = ttk.Frame(self.c_list_frame)
        row.pack(fill="x", pady=0)

        data = {
            'txt': tk.StringVar(value=init.get('txt', "")),
            'x': tk.StringVar(value=init.get('x', "")),
            'y': tk.StringVar(value=init.get('y', "")),
            'ang': tk.StringVar(value=init.get('ang', "0")),
            'coord_mode': tk.StringVar(value=init.get('coord_mode', "data")),
            'color': tk.StringVar(value=init.get('color', "Auto")),
            'frame': row,
        }
        self.comment_list.append(data)

        ttk.Button(row, text="X", width=3, style="Compact.TButton", command=lambda: self.remove_row(self.comment_list, row)).pack(side="right", padx=5)
        ttk.Combobox(row, textvariable=data['color'], values=COLOR_LIST, width=6, state="readonly").pack(side="right", padx=(2, 5))

        ttk.Label(row, text="[Comment]", foreground="blue").pack(side="left", padx=(0, 5))
        ttk.Label(row, text="Txt:").pack(side="left")
        txt_entry = self._mk_entry(row, data['txt'], width=20, color="amber")
        txt_entry.pack(side="left", padx=2)
        # [추가] "Comment창에도 Ω창에서 입력 가능하게" - Title류 입력칸과 동일하게
        # 포커스될 때 active_entry로 기록해서 Ω 심볼 창이 여기에 삽입할 수 있게 함.
        txt_entry.bind("<FocusIn>", lambda e: self.set_active_entry(txt_entry))
        ttk.Label(row, text="(X,Y):").pack(side="left")
        xy_entry, _ = self._make_xy_combo_entry(row, data['x'], data['y'], init.get('x', ''), init.get('y', ''))
        xy_entry.pack(side="left", padx=2)
        mode_display_var = tk.StringVar(value=self.COORD_MODE_DISPLAY.get(data['coord_mode'].get(), "%"))
        def _on_mode_changed(*_):
            data['coord_mode'].set(self.COORD_MODE_FROM_DISPLAY.get(mode_display_var.get(), "pct"))
        mode_display_var.trace_add("write", _on_mode_changed)
        ttk.Combobox(row, textvariable=mode_display_var, values=["%", "좌표값"], width=5, state="readonly").pack(side="left", padx=(1, 2))
        ttk.Label(row, text="Angle(0~360°):").pack(side="left")
        self._mk_entry(row, data['ang'], width=6, color="amber").pack(side="left", padx=2)

    ARROW_HEAD_DISPLAY_MAP = {
        "No Head": "nohead",
        "ForwHead": "head",
        "BackHead": "backhead",
        "Both Heads": "heads",
    }

    # [추가] "화살표 크기 옵션도 넣어달라(각도는 auto)" - Marker Size(XS~XL)와
    # 같은 프리셋 방식. 값은 gnuplot arrow head size의 "길이"(graph 비율,
    # 축 크기와 무관하게 항상 같은 시각적 크기로 보이게)이고, 각도는 15도
    # 고정(화살촉 모양이 자연스러운 기본값)으로 자동 적용한다.
    ARROW_SIZE_MAP = {"S": 0.015, "M": 0.03, "L": 0.05, "XL": 0.08}
    ARROW_HEAD_ANGLE = 15

    def add_arrow_row(self, initial=None):
        init = initial or {}
        row = ttk.Frame(self.a_list_frame)
        row.pack(fill="x", pady=0)

        saved_type = init.get('type', "head")
        data = {'x1': tk.StringVar(value=init.get('x1', "")), 'y1': tk.StringVar(value=init.get('y1', "")),
                'x2': tk.StringVar(value=init.get('x2', "")), 'y2': tk.StringVar(value=init.get('y2', "")),
                'type': tk.StringVar(value=saved_type),
                'coord_mode': tk.StringVar(value=init.get('coord_mode', "data")),
                'color': tk.StringVar(value=init.get('color', "Auto")),
                'size': tk.StringVar(value=init.get('size', "M")),
                'frame': row}
        self.arrow_list.append(data)

        ttk.Button(row, text="X", width=3, style="Compact.TButton", command=lambda: self.remove_row(self.arrow_list, row)).pack(side="right", padx=5)
        ttk.Combobox(row, textvariable=data['color'], values=COLOR_LIST, width=6, state="readonly").pack(side="right", padx=(2, 5))
        ttk.Combobox(row, textvariable=data['size'], values=list(self.ARROW_SIZE_MAP.keys()), width=4, state="readonly").pack(side="right", padx=(2, 2))

        # 저장된 type("head"/"nohead"/...) 값에 맞는 콤보박스 표시 라벨을 역매핑해서 초기값으로 사용
        inverse_head_map = {v: k for k, v in self.ARROW_HEAD_DISPLAY_MAP.items()}
        head_display_var = tk.StringVar(value=inverse_head_map.get(saved_type, "ForwHead"))

        def on_head_changed(*_):
            data['type'].set(self.ARROW_HEAD_DISPLAY_MAP.get(head_display_var.get(), "head"))

        head_combo = ttk.Combobox(
            row, textvariable=head_display_var,
            values=list(self.ARROW_HEAD_DISPLAY_MAP.keys()),
            width=9, state="readonly"
        )
        head_combo.pack(side="right", padx=(10, 2))
        head_combo.bind("<<ComboboxSelected>>", on_head_changed)

        ttk.Label(row, text="[Arrow]", foreground="darkred").pack(side="left", padx=(0, 5))

        ttk.Label(row, text="(X1,Y1):").pack(side="left")
        xy1_entry, _ = self._make_xy_combo_entry(row, data['x1'], data['y1'], init.get('x1', ''), init.get('y1', ''), width=9)
        xy1_entry.pack(side="left", padx=1)
        ttk.Label(row, text="→ (X2,Y2):").pack(side="left")
        xy2_entry, _ = self._make_xy_combo_entry(row, data['x2'], data['y2'], init.get('x2', ''), init.get('y2', ''), width=9)
        xy2_entry.pack(side="left", padx=1)
        mode_display_var = tk.StringVar(value=self.COORD_MODE_DISPLAY.get(data['coord_mode'].get(), "%"))
        def _on_mode_changed(*_):
            data['coord_mode'].set(self.COORD_MODE_FROM_DISPLAY.get(mode_display_var.get(), "pct"))
        mode_display_var.trace_add("write", _on_mode_changed)
        ttk.Combobox(row, textvariable=mode_display_var, values=["%", "좌표값"], width=5, state="readonly").pack(side="left", padx=(1, 2))

    def add_circle_row(self, initial=None):
        """[추가] Circle/Ellipse 주석 - 중심(X,Y) + 반지름(Rx,Ry). Ry를 비워두면
        Rx를 그대로 써서 원이 된다(반지름 1개만 입력하면 원). 좌표값/% 모드와
        색상은 Comment/Arrow와 동일한 방식을 재사용. 두께는 Arrow처럼 별도
        지정하지 않아 gnuplot 기본값으로 서로 같게 맞춘다."""
        init = initial or {}
        row = ttk.Frame(self.e_list_frame)
        row.pack(fill="x", pady=0)

        data = {
            'x': tk.StringVar(value=init.get('x', "")),
            'y': tk.StringVar(value=init.get('y', "")),
            'rx': tk.StringVar(value=init.get('rx', "")),
            'ry': tk.StringVar(value=init.get('ry', "")),
            'coord_mode': tk.StringVar(value=init.get('coord_mode', "data")),
            'color': tk.StringVar(value=init.get('color', "Auto")),
            'frame': row,
        }
        self.circle_list.append(data)

        ttk.Button(row, text="X", width=3, style="Compact.TButton", command=lambda: self.remove_row(self.circle_list, row)).pack(side="right", padx=5)
        ttk.Combobox(row, textvariable=data['color'], values=COLOR_LIST, width=6, state="readonly").pack(side="right", padx=(2, 5))

        ttk.Label(row, text="[Circle]", foreground="darkgreen").pack(side="left", padx=(0, 5))
        ttk.Label(row, text="Center(X,Y):").pack(side="left")
        c_entry, _ = self._make_xy_combo_entry(row, data['x'], data['y'], init.get('x', ''), init.get('y', ''), width=9)
        c_entry.pack(side="left", padx=1)
        ttk.Label(row, text="Radius(Rx,Ry):").pack(side="left")
        r_entry, _ = self._make_xy_combo_entry(row, data['rx'], data['ry'], init.get('rx', ''), init.get('ry', ''), width=9)
        r_entry.pack(side="left", padx=1)
        ttk.Label(row, text="(Ry 비우면 원)", foreground="gray").pack(side="left", padx=(0, 5))
        mode_display_var = tk.StringVar(value=self.COORD_MODE_DISPLAY.get(data['coord_mode'].get(), "%"))
        def _on_mode_changed(*_):
            data['coord_mode'].set(self.COORD_MODE_FROM_DISPLAY.get(mode_display_var.get(), "pct"))
        mode_display_var.trace_add("write", _on_mode_changed)
        ttk.Combobox(row, textvariable=mode_display_var, values=["%", "좌표값"], width=5, state="readonly").pack(side="left", padx=(1, 2))

    def remove_row(self, target_list, frame):
        frame.destroy()
        for item in target_list:
            if item['frame'] == frame:
                target_list.remove(item)
                break
        # [수정] "모두 지우면 처음처럼 빈 입력칸이 하나씩 보이게" - 목록이
        # 완전히 비면 빈 행을 하나 다시 채워준다.
        if not target_list:
            if target_list is self.comment_list:
                self.add_comment_row()
            elif target_list is self.arrow_list:
                self.add_arrow_row()
            elif target_list is self.circle_list:
                self.add_circle_row()

    #def remove_row(self, target_list, frame):
    #    container = frame.master  # c_list_frame 또는 a_list_frame
    #    frame.destroy()
    #    for item in target_list:
    #        if item['frame'] == frame:
    #            target_list.remove(item)
    #            break
    #
    #    if target_list:
    #        # 남은 행이 있으면, 순서대로 강제로 다시 pack해서 재정렬한다.
    #        for item in target_list:
    #            item['frame'].pack_forget()
    #            item['frame'].pack(fill="x", pady=2)
    #    else:
    #        # 마지막 남은 한 줄까지 지워서 목록이 완전히 비면, 다시 pack할
    #        # 대상이 없어서 위 방법이 안 통한다 - 이 경우엔 컨테이너 자체를
    #        # 뗐다 다시 붙여서 크기를 0으로 강제로 재계산시킨다.
    #        # before=로 원래 순서(Comment 목록 -> Arrow 목록 -> 버튼 줄)를 유지한다.
    #        if container is self.c_list_frame:
    #            container.pack_forget()
    #            container.pack(fill="x", padx=5, before=self.a_list_frame)
    #        elif container is self.a_list_frame:
    #            container.pack_forget()
    #            container.pack(fill="x", padx=5, before=self.anno_btn_f)
    #        else:
    #            container.pack_forget()
    #            container.pack(fill="x", padx=5)
    #
    #    self.plot_frame.update_idletasks()
    #    self.plot_canvas.configure(scrollregion=self.plot_canvas.bbox("all"))

    def clear_file_selections(self, target_df):
        # all var color/style to "Auto"
        #for k in list(self.selected_y1_vars.keys()):
        #    if k.startswith(target_df):
        #        self.selected_y1_vars[k].set(False)
        #        self.selected_y2_vars[k].set(False)
        #        if k in self.color_vars:
        #            self.color_vars[k].set("Auto")
        #        if k in self.linestyle_vars:
        #            self.linestyle_vars[k].set("Auto")
        #if self.selected_x_key.get().startswith(target_df):
        #    self.selected_x_key.set("")
        #    self.prev_x_key = ""
        #self.sync_axis_labels()

        # color/style to "Auto": selected var only
        for k in list(self.selected_y1_vars.keys()):
            if k.startswith(target_df):
                was_selected = self.selected_y1_vars[k].get() or self.selected_y2_vars[k].get()
                self.selected_y1_vars[k].set(False)
                self.selected_y2_vars[k].set(False)
                if was_selected:
                    if k in self.color_vars:
                        self.color_vars[k].set("Auto")
                    if k in self.linestyle_vars:
                        self.linestyle_vars[k].set("Auto")
        if self.selected_x_key.get().startswith(target_df):
            self.selected_x_key.set("")
            self.prev_x_key = ""
        self.sync_axis_labels()


    def _dedup_display_name(self, target_filename):
        """[정리] 같은 basename을 가진 dat 파일이 여러 개 로드됐을 때, 로드된
        등장 순서대로 "파일명-#.ext" 형식으로 구분한 표시용 이름을 반환한다
        (겹치지 않는 보통 경우는 그대로 basename만 표시). Dat list 섹션 제목과
        3D legend가 항상 같은 번호를 쓰도록 공용 함수로 뽑음.
        [수정] "filename.dat-# 대신 filename-#.dat로" - 확장자 뒤가 아니라
        이름과 확장자 사이에 번호를 끼워 넣는 형태로 통일."""
        target_bn = os.path.basename(target_filename)
        _basename_counts = {}
        for info in self.file_rows:
            if info.get("meta") is None:
                continue
            bn = os.path.basename(info["filename"])
            _basename_counts[bn] = _basename_counts.get(bn, 0) + 1
        if _basename_counts.get(target_bn, 0) <= 1:
            return target_bn
        seen = 0
        for info in self.file_rows:
            if info.get("meta") is None:
                continue
            bn = os.path.basename(info["filename"])
            if bn != target_bn:
                continue
            seen += 1
            if os.path.abspath(info["filename"]) == os.path.abspath(target_filename):
                name_root, ext = os.path.splitext(target_bn)
                return f"{name_root}-{seen}{ext}"
        return target_bn

    def show_variables(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        container = ttk.Frame(self.scrollable_frame)
        container.pack(fill="both", expand=True, padx=0)

        valid_file_count = 0

        for idx, info in enumerate(self.file_rows):
            if info["meta"] is None:
                continue
            datfile = info["filename"]
            meta = info["meta"]

            file_x_var = info["x_var"]  # <-- 해당 파일 전용 X축 변수
            _display_name = self._dedup_display_name(datfile)
            frame = ttk.LabelFrame(container, text=_display_name)

            frame.grid(row=valid_file_count // 3, column=valid_file_count % 3, sticky="nw", padx=2, pady=2)
            valid_file_count += 1

            # [추가] gnuplot splot용 CATHENA surface 파일(is_surface)은 일반
            # Y1/Y2 변수 선택이 의미가 없는 구조(한 파일 전체가 격자 하나)라,
            # 안내 문구만 보여주고 나머지 변수 선택 UI는 건너뛴다. 실제 3D
            # surface로 쓰려면 "3D Plot" 버튼을 누르면 자동으로 목록에 뜬다.
            if getattr(meta, "is_surface", False):
                ttk.Label(
                    frame,
                    text=f"Surface(splot) 데이터 - 채널 {meta.n_outputs}개\n"
                         f"Z: {meta.surface_base_name or '(이름 없음)'}\n"
                         f"'3D Plot' 버튼에서 바로 사용 가능",
                    foreground="darkgreen", justify="left"
                ).pack(anchor="w", padx=4, pady=4)
                continue

            header_f = ttk.Frame(frame)
            header_f.pack(fill="x", padx=2)
            ttk.Label(header_f, text="No.  Variable", font=("Arial", 9, "bold"), width=24).pack(side="left")

            # [수정 - 버그] "Y2, Color, Style이 조금씩 우측으로 밀림" - 헤더의
            # X/Y1/Y2 라벨은 문자수(width=2/3, Consolas 10 bold) 기준으로 폭을
            # 잡았는데, 그 아래 실제 데이터 행의 Radiobutton/Checkbutton은
            # 그 폭과 정확히 대응한다는 보장이 없는 별개 위젯(글꼴이 아니라
            # 테마 indicator 크기로 결정됨)이라 아주 조금씩 어긋나고, 그
            # 오차가 오른쪽으로 갈수록(X -> Y1 -> Y2 -> Color -> Style) 누적돼
            # 보였음. Color/Style처럼 고정 픽셀 폭 Frame(pack_propagate(False))
            # 으로 감싸서, 안의 위젯이 무엇이든(라벨이든 체크박스든) 항상 같은
            # 폭을 쓰게 통일한다(아래 데이터 행의 X/Y1/Y2 칸도 동일하게 적용).
            X_COL_PX = 26
            Y1_COL_PX = 30
            Y2_COL_PX = 30
            # [수정 - 버그] "X/Y1/Y2 헤더가 그 아래 입력 박스(Radio/Checkbutton)
            # 대비 우측으로 밀림" - 프레임/위젯의 요청 폭 자체는 정중앙에 오게
            # 맞춰놨는데도(place relx=0.5) 여전히 어긋나 보임 - 실측 확인:
            # vista 테마의 Radiobutton/Checkbutton은 도형(indicator) 자체가
            # OS 네이티브 렌더링(UxTheme)이라 그 도형이 위젯 박스 내부에서
            # 정확히 중앙이 아니라 왼쪽으로 치우쳐 그려짐(ttk layout/style로는
            # 손댈 수 없는 부분) - Label 텍스트는 진짜 중앙에 오는데 그 아래
            # 도형은 왼쪽에 있어서 "헤더가 우측으로 밀린 것처럼" 보였던 것.
            # ttk 쪽을 고칠 수 없으니 Label을 도형 위치에 맞춰 같은 만큼(약
            # 1글자, 7px) 왼쪽으로 옮겨서 맞춘다.
            # 대문자 1자 폭 실측(Consolas 10pt, PIL 기준) = 5.5px. 처음 -7px(약
            # 1.3자)이 과했다는 피드백으로 반 글자(~2.75px) 되돌려 보정.
            _HDR_NUDGE_PX = -4
            x_hdr_f = tk.Frame(header_f, width=X_COL_PX, height=22)
            x_hdr_f.pack_propagate(False)
            x_hdr_f.pack(side="left")
            ttk.Label(x_hdr_f, text="X", font=("Consolas", 10, "bold")).place(relx=0.5, x=_HDR_NUDGE_PX, rely=0.5, anchor="center")
            y1_hdr_f = tk.Frame(header_f, width=Y1_COL_PX, height=22)
            y1_hdr_f.pack_propagate(False)
            y1_hdr_f.pack(side="left")
            ttk.Label(y1_hdr_f, text="Y1", font=("Consolas", 10, "bold")).place(relx=0.5, x=_HDR_NUDGE_PX, rely=0.5, anchor="center")
            y2_hdr_f = tk.Frame(header_f, width=Y2_COL_PX, height=22)
            y2_hdr_f.pack_propagate(False)
            y2_hdr_f.pack(side="left")
            ttk.Label(y2_hdr_f, text="Y2", font=("Consolas", 10, "bold")).place(relx=0.5, x=_HDR_NUDGE_PX, rely=0.5, anchor="center")
            COLOR_COL_PX = 65   # 최장 옵션(Magenta/Purple/Orange, 7자) 기준
            STYLE_COL_PX = 70   # 최장 옵션(Short-Dash, 10자) 기준
            # [수정] height=18이 "Color"/"Style" 글자(Consolas 10 bold) 높이보다
            # 낮아서 아래쪽이 잘리고 X/Y1/Y2보다 낮게 보이던 문제 - 데이터 행
            # 셀(height=22)과 맞춰서 헤더도 22로 통일
            color_hdr_f = tk.Frame(header_f, width=COLOR_COL_PX, height=22)
            color_hdr_f.pack_propagate(False)
            color_hdr_f.pack(side="left")
            ttk.Label(color_hdr_f, text="Color", font=("Consolas",10,"bold")).pack(side="left")
            style_hdr_f = tk.Frame(header_f, width=STYLE_COL_PX, height=22)
            style_hdr_f.pack_propagate(False)
            style_hdr_f.pack(side="left")
            ttk.Label(style_hdr_f, text="Style", font=("Consolas",10,"bold")).pack(side="left")

            for pv in meta.variables:
                title = pv.signals[0].name if pv.signals else f"OUTPUT {pv.output_no}"
                key_str = f"{datfile}||{pv.output_no}"

                if key_str not in self.color_vars:
                    self.color_vars[key_str] = tk.StringVar(value="Auto")
                if key_str not in self.linestyle_vars:
                    self.linestyle_vars[key_str] = tk.StringVar(value="Auto")
                if key_str not in self.legend_vars:
                    self.legend_vars[key_str] = tk.StringVar(value=title)

                if key_str not in self.selected_y1_vars:
                    self.selected_y1_vars[key_str] = tk.BooleanVar(value=False)
                if key_str not in self.selected_y2_vars:
                    self.selected_y2_vars[key_str] = tk.BooleanVar(value=False)
                if key_str not in self.linewidth_vars:
                    self.linewidth_vars[key_str] = tk.DoubleVar(value=1.5)
                if key_str not in self.legend_group_vars:
                    self.legend_group_vars[key_str] = tk.StringVar(value="2")

                row_frame = ttk.Frame(frame)
                row_frame.pack(anchor="w", fill="x", padx=0, pady=0)

                no_label = ttk.Label(row_frame, text=f"{pv.output_no:>2}", width=3, anchor="e")
                no_label.pack(side="left")
                entry = ttk.Entry(row_frame, textvariable=self.legend_vars[key_str], width=20)
                entry.pack(side="left", padx=(1,0))
                entry.bind("<FocusIn>", lambda e, ent=entry: self.set_active_entry(ent))
                # [수정] row_frame 전체에 걸면 그 안의 Shift/Color/Style 등 자식 위젯들
                # 사이를 오갈 때 Enter/Leave가 불안정하게 발생해서 툴팁이 안 지워지고
                # 잔상처럼 남는 문제가 있었음 - "변수 박스"에 해당하는 No.라벨과
                # 변수명 입력칸에만 정확히 바인딩
                self._bind_var_tooltip([no_label, entry], info, pv.output_no)

                # --- X축 선택 시 동일 행의 Y1, Y2를 자동으로 해제하는 배타적 핸들러 ---
                def make_x_cmd(target_key=key_str, f_x_var=file_x_var):
                    def x_handler():
                        # 만약 현재 이 변수가 X축으로 선택되었다면, 동일 행의 Y1과 Y2 체크를 해제함
                        if f_x_var.get() == target_key:
                            self.selected_y1_vars[target_key].set(False)
                            self.selected_y2_vars[target_key].set(False)
                        self.sync_axis_labels()
                    return x_handler

                # 이미 선택된 X 라디오버튼을 다시 클릭했을 때 무선택(토글 해제)되도록 처리하는 이벤트
                def on_x_radio_click(event, target_key=key_str, f_x_var=file_x_var):
                    if f_x_var.get() == target_key:
                        f_x_var.set("")  # 토글 해제
                        self.sync_axis_labels()
                        return "break"  # 기본 라디오버튼 동작 방지

                def make_y_excl_cmd(target_key=key_str, clicked_axis="Y1", f_x_var=file_x_var):
                    def y_excl_handler():
                        if clicked_axis == "Y1":
                            if self.selected_y1_vars[target_key].get():
                                self.selected_y2_vars[target_key].set(False)
                                if f_x_var.get() == target_key:
                                    f_x_var.set("")
                        elif clicked_axis == "Y2":
                            if self.selected_y2_vars[target_key].get():
                                self.selected_y1_vars[target_key].set(False)
                                if f_x_var.get() == target_key:
                                    f_x_var.set("")
                        self.sync_axis_labels()
                    return y_excl_handler

                # [수정 - 버그] 위 헤더(X/Y1/Y2)와 폭을 정확히 맞추기 위해
                # 헤더와 동일한 고정 픽셀 폭 Frame으로 감싼다(위 X_COL_PX/
                # Y1_COL_PX/Y2_COL_PX 참고 - Color/Style과 같은 방식).
                x_cell_f = tk.Frame(row_frame, width=X_COL_PX, height=22)
                x_cell_f.pack_propagate(False)
                x_cell_f.pack(side="left")
                r_x = ttk.Radiobutton(x_cell_f, value=key_str, variable=file_x_var, command=make_x_cmd(key_str, file_x_var))
                r_x.place(relx=0.5, rely=0.5, anchor="center")
                # 이미 선택된 라디오버튼을 다시 클릭했을 때 해제되도록 마우스 이벤트 가로채기
                r_x.bind("<Button-1>", on_x_radio_click)

                y1_cell_f = tk.Frame(row_frame, width=Y1_COL_PX, height=22)
                y1_cell_f.pack_propagate(False)
                y1_cell_f.pack(side="left")
                # [수정 - 요청] "Var list의 Y1/Y2 체크 크기를 이전처럼 키워줘요" -
                # 기본(15px)보다 크게(19px, 셀 높이 22px 안에 여유 있게 들어감).
                c_y1 = self._mk_check(y1_cell_f, "", self.selected_y1_vars[key_str], size=19, command=make_y_excl_cmd(key_str, "Y1", file_x_var), no_pack=True)
                c_y1.place(relx=0.5, rely=0.5, anchor="center")

                y2_cell_f = tk.Frame(row_frame, width=Y2_COL_PX, height=22)
                y2_cell_f.pack_propagate(False)
                y2_cell_f.pack(side="left")
                c_y2 = self._mk_check(y2_cell_f, "", self.selected_y2_vars[key_str], size=19, command=make_y_excl_cmd(key_str, "Y2", file_x_var), no_pack=True)
                c_y2.place(relx=0.5, rely=0.5, anchor="center")

                color_cell_f = tk.Frame(row_frame, width=COLOR_COL_PX, height=22)
                color_cell_f.pack_propagate(False)
                color_cell_f.pack(side="left", padx=(2,0))
                color_combo = ttk.Combobox(color_cell_f, textvariable=self.color_vars[key_str], values=COLOR_LIST, state="readonly")
                color_combo.pack(side="left", fill="both", expand=True)
                self._disable_combobox_wheel(color_combo)

                style_cell_f = tk.Frame(row_frame, width=STYLE_COL_PX, height=22)
                style_cell_f.pack_propagate(False)
                style_cell_f.pack(side="left", padx=0)
                style_combo = ttk.Combobox(style_cell_f, textvariable=self.linestyle_vars[key_str], values=STYLE_LIST, state="readonly")
                style_combo.pack(side="left", fill="both", expand=True)
                self._disable_combobox_wheel(style_combo)

            if datfile not in self.file_xshift_vars:
                self.file_xshift_vars[datfile] = tk.StringVar(value="0")

            clear_btn_f = ttk.Frame(frame)
            clear_btn_f.pack(fill="x", anchor="e", padx=2)
            ttk.Button(clear_btn_f, text="Clear All", width=9, command=lambda tf=datfile: self.clear_file_selections(tf)).pack(side="right", padx=0, pady=2)
            ttk.Entry(clear_btn_f, textvariable=self.file_xshift_vars[datfile], width=7).pack(side="right", padx=(0, 5), pady=2)
            ttk.Label(clear_btn_f, text="X Shift:").pack(side="right", pady=2)

        self.scrollable_frame.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.sync_axis_labels()

    def on_x_title_changed(self, *args):
        if self._updating_x: return
        self.x_title_auto = (self.xlabel_var.get().strip() == "")

    def on_y1_title_changed(self, *args):
        if self._updating_y1: return
        self.y1_title_auto = (self.ylabel_var.get().strip() == "")

    def on_y2_title_changed(self, *args):
        if self._updating_y2: return
        self.y2_title_auto = (self.y2label_var.get().strip() == "")

    def sync_axis_labels(self):
        # X title은 Y1/Y2와 동일하게 "실제로 X가 선택된 파일들 중 맨 처음 것"을 따라간다.
        # (파일별 x_var 기본값은 빈 문자열 "" = 미선택이므로, 비어있으면 건너뛰고
        #  다음 파일을 계속 확인해서 실제 선택이 있는 첫 파일을 찾는다)
        x_key = ""
        for info in self.file_rows:
            if info.get("filename") and info.get("meta") is not None:
                candidate = info["x_var"].get()
                if candidate:
                    x_key = candidate
                    break

        if self.x_title_auto:
            self._updating_x = True
            self.xlabel_var.set(self.legend_vars[x_key].get() if x_key in self.legend_vars else "")
            self._updating_x = False

        y1_selected = [self.legend_vars[k].get() for k, v in self.selected_y1_vars.items() if v.get()]
        y2_selected = [self.legend_vars[k].get() for k, v in self.selected_y2_vars.items() if v.get()]

        if self.y1_title_auto:
            self._updating_y1 = True
            self.ylabel_var.set(y1_selected[0] if y1_selected else "")
            self._updating_y1 = False

        if self.y2_title_auto:
            self._updating_y2 = True
            self.y2label_var.set(y2_selected[0] if y2_selected else "")
            self._updating_y2 = False

    def clean_past_plots(self):
        """임시 파일 및 캐시 정리"""
        # 1. 처음 한 번만 삭제 확인 박스를 띄웁니다.
        if not messagebox.askyesno("Confirm", "Do you really want to clean all past temporary plot files and caches?"):
            return

        deleted_count = 0

        # 2. temp_sorted 임시 폴더 통째로 삭제
        try:
            temp_dir = os.path.join(self.plot_dir, "temp_sorted")
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
                deleted_count += 1
        except Exception:
            pass

        # 3. 디렉토리 내의 임시 플롯 파일 패턴들 (*.plt, *.gnu) 수집 및 삭제
        try:
            import glob
            patterns = [
                os.path.join(self.plot_dir, "*.plt"),
                os.path.join(self.plot_dir, "*.gnu"),
            ]

            for pattern in patterns:
                for filepath in glob.glob(pattern):
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                            deleted_count += 1
                        except:
                            pass

            # 리스트 뷰 및 파일 리스트 새로고침
            self.update_plot_file_list()
            messagebox.showinfo("Success", "Successfully cleaned up past temporary files and caches.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to clean past plots: {e}")

    # [삭제 - 죽은 코드] clear_all_plots/reset_history - grep 결과 이 파일 안에
    # 호출부(버튼/메뉴)가 전혀 없어(0 call sites) 화면 어디서도 실행될 수
    # 없었음. 실제로 쓰이는 "전체 초기화"는 clean_past_plots 하나뿐이라,
    # 이 둘은 clean_past_plots와 거의 같은 내용을 중복 구현한 채 방치돼
    # 있었을 뿐(git 히스토리에 남아있으니 필요하면 복원 가능).

    def _collect_annotations(self):
        if not self.comment_on_var.get():
            return []
        annotations = []
        for item in self.comment_list:
            text = item['txt'].get().strip()
            x = item['x'].get().strip()
            y = item['y'].get().strip()
            angle = item['ang'].get().strip() or "0"
            coord_mode = item.get('coord_mode', tk.StringVar(value="pct")).get()
            color = COLOR_MAP.get(item.get('color', tk.StringVar(value="Auto")).get(), "")
            if text and x and y:
                annotations.append({"text": text, "x": x, "y": y, "angle": angle, "coord_mode": coord_mode, "color": color})
        return annotations

    def _collect_arrows(self):
        if not self.arrow_on_var.get():
            return []

        head_label_map = {
            "nohead": "No head", "head": "Forward",
            "backhead": "Backhead", "heads": "Both heads"
        }
        arrows = []
        for item in self.arrow_list:
            x1 = item['x1'].get().strip()
            y1 = item['y1'].get().strip()
            x2 = item['x2'].get().strip()
            y2 = item['y2'].get().strip()
            if not (x1 and y1 and x2 and y2):
                continue

            head = head_label_map.get(item['type'].get(), "Forward")
            coord_mode = item.get('coord_mode', tk.StringVar(value="pct")).get()
            color = COLOR_MAP.get(item.get('color', tk.StringVar(value="Auto")).get(), "")
            head_size = self.ARROW_SIZE_MAP.get(item.get('size', tk.StringVar(value="M")).get(), self.ARROW_SIZE_MAP["M"])
            arrows.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "head": head, "coord_mode": coord_mode, "color": color, "head_size": head_size})
        return arrows

    def _collect_circles(self):
        if not self.circle_on_var.get():
            return []
        circles = []
        for item in self.circle_list:
            x = item['x'].get().strip()
            y = item['y'].get().strip()
            rx = item['rx'].get().strip()
            ry = item['ry'].get().strip()
            if not (x and y and rx):
                continue
            coord_mode = item.get('coord_mode', tk.StringVar(value="pct")).get()
            color = COLOR_MAP.get(item.get('color', tk.StringVar(value="Auto")).get(), "")
            circles.append({"x": x, "y": y, "rx": rx, "ry": ry, "coord_mode": coord_mode, "color": color})
        return circles

    # ===================== 3D Plot (splot) =====================
    def _collect_3d_curves(self):
        """[추가] 3D Plot - "X,Y1,Y2 -> X,Y,Z로 매핑, 여러 세트(파일)를 같은
        화면에". 파일마다 Y1 1개 + Y2 1개가 선택되어 있어야 그 파일이 3D curve
        하나가 됨(짝이 안 맞으면 제외하고 이유를 알려줌 - 한 파일에 여러 개면
        어느 것끼리 짝지어야 할지 알 수 없어서)."""
        from collections import defaultdict
        y1_by_file = defaultdict(list)
        y2_by_file = defaultdict(list)
        for key, var in self.selected_y1_vars.items():
            if var.get():
                d_file, out_no = key.split("||")
                y1_by_file[d_file].append(int(out_no))
        for key, var in self.selected_y2_vars.items():
            if var.get():
                d_file, out_no = key.split("||")
                y2_by_file[d_file].append(int(out_no))

        all_files = set(y1_by_file.keys()) | set(y2_by_file.keys())
        eligible = []
        skipped = []
        for d_file in sorted(all_files):
            y1s = y1_by_file.get(d_file, [])
            y2s = y2_by_file.get(d_file, [])
            # [수정] "3D legend에서도 동일 filename들을 filename-#로 구분 표기" -
            # Dat list 섹션 제목과 항상 같은 번호를 쓰도록 공용 dedup 함수 재사용.
            bn = self._dedup_display_name(d_file)
            if len(y1s) == 1 and len(y2s) == 1:
                file_x_output_no = 0
                x_key_val = ""
                for info in self.file_rows:
                    if info.get("filename") == d_file:
                        x_var_obj = info.get("x_var")
                        if x_var_obj and hasattr(x_var_obj, 'get'):
                            x_key_val = x_var_obj.get()
                            if x_key_val and "||" in x_key_val:
                                _, x_out_no_str = x_key_val.split("||")
                                try:
                                    file_x_output_no = int(x_out_no_str)
                                except (ValueError, AttributeError):
                                    pass
                        break
                try:
                    target_dat_file = self.resort_dat_file(d_file, file_x_output_no)
                except Exception:
                    target_dat_file = d_file
                x_shift = float(self.file_xshift_vars[d_file].get() or 0.0) if d_file in self.file_xshift_vars else 0.0
                # [추가 - 버그] "선택 해제되면 차순위 file의 x,y,z(y2) title을
                # 읽어와야지" - X/Y1/Y2 title도 Plot Title처럼 "체크된 첫
                # curve"를 따라가려면, 그 curve가 실제로 어떤 변수(legend 이름)를
                # 쓰는지 알아야 함 - sync_axis_labels()와 동일하게 legend_vars에서
                # 실제 변수명을 가져와 같이 저장해둔다(2D의 xlabel_var 등 화면에
                # 지금 떠 있는 값이 아니라, 이 curve 고유의 X/Y1/Y2 변수명).
                y1_key = f"{d_file}||{y1s[0]}"
                y2_key = f"{d_file}||{y2s[0]}"
                x_title = self.legend_vars.get(x_key_val).get() if x_key_val in self.legend_vars else ""
                y_title = self.legend_vars.get(y1_key).get() if y1_key in self.legend_vars else ""
                y2_title = self.legend_vars.get(y2_key).get() if y2_key in self.legend_vars else ""
                eligible.append({
                    "dat_file": target_dat_file,
                    "x_col": file_x_output_no + 1,
                    "y_col": y1s[0] + 1,
                    "z_col": y2s[0] + 1,
                    "x_shift": x_shift,
                    "label": bn,
                    "x_title": x_title,
                    "y_title": y_title,
                    "y2_title": y2_title,
                })
            elif not y1s and not y2s:
                continue  # 아예 선택 안 한 파일은 조용히 무시
            else:
                reason = []
                if len(y1s) == 0: reason.append("Y1 없음")
                elif len(y1s) > 1: reason.append(f"Y1 {len(y1s)}개(어느 것끼리 짝지을지 모호)")
                if len(y2s) == 0: reason.append("Y2 없음")
                elif len(y2s) > 1: reason.append(f"Y2 {len(y2s)}개(어느 것끼리 짝지을지 모호)")
                skipped.append(f"{bn}: {', '.join(reason)}")
        return eligible, skipped

    def _collect_3d_surfaces(self):
        """[추가] gnuplot splot용 CATHENA surface 파일(is_surface) 목록을 모은다.
        일반 3D curve(여러 2D 값을 X/Y/Z로 매핑)와 달리, 이 파일들은 원본
        그대로 "using 1:2:3"으로 바로 splot 가능한 격자 데이터라 별도 목록으로
        수집한다(Y1/Y2 선택 여부와 무관하게, 로드된 순간부터 바로 사용 가능)."""
        surfaces = []
        for info in self.file_rows:
            meta = info.get("meta")
            if meta is not None and getattr(meta, "is_surface", False):
                # [수정] "3D legend에서도 동일 filename들을 filename-#로 구분 표기"
                _disp = self._dedup_display_name(info["filename"])
                surfaces.append({
                    "dat_file": info["filename"],
                    "label": _disp,
                    "n_outputs": meta.n_outputs,
                    "z_label": meta.surface_base_name or _disp,
                })
        return surfaces

    def open_3d_plot_dialog(self):
        eligible, skipped = self._collect_3d_curves()
        surfaces = self._collect_3d_surfaces()
        if not eligible and not surfaces:
            msg = "3D로 그릴 수 있는 파일이 없습니다.\n(파일마다 Y1 1개 + Y2 1개가 선택되어 있어야 합니다.\nSurface(splot) 파일은 로드만 하면 바로 사용 가능합니다.)"
            if skipped:
                msg += "\n\n제외된 파일:\n" + "\n".join(skipped)
            messagebox.showwarning("3D Plot", msg)
            return
        if skipped:
            proceed = messagebox.askyesno(
                "3D Plot",
                "다음 파일은 Y1/Y2 짝이 맞지 않아 3D에서 제외됩니다:\n\n" + "\n".join(skipped) +
                "\n\n나머지 파일로 계속할까요?"
            )
            if not proceed:
                return

        dialog = tk.Toplevel(self.root)
        dialog.configure(bg=self.PALETTE["bg"])
        dialog.title("3D Plot Options")
        dialog.transient(self.root)

        # [수정 - 버그] "선택하지 않은 curve의 title 대신, 선택한 curve 중
        # 먼저 것의 title을 default로" - 예전엔 curve가 하나라도 있으면
        # (아래 포함할 Set 목록에서 실제 체크돼 있는지와 무관하게) 항상
        # self.filename_var(2D 메인 창에서 지금 보고 있는 파일)를 기본값으로
        # 썼는데, 여러 파일을 로드해둔 상태에서 지금 보고 있는 파일이 3D에
        # 포함 안 시킨(또는 체크 해제한) 파일일 수 있어 엉뚱한 이름이 나왔음.
        # "포함할 Set" 체크박스들이 아래에서 만들어지므로, 일단 임시값으로 두고
        # 그 체크박스들을 다 만든 뒤 실제로 체크된 첫 항목 기준으로 다시 채운다
        # (아래 _sync_default_titles 참고). 체크박스를 껐다 켰다 할 때도 같은
        # 함수가 다시 불려 반영됨 - 단, 사용자가 직접 고친 값은 덮어쓰지 않음.
        plot_title_var = tk.StringVar(value="CathPlot")

        title_row = ttk.Frame(dialog)
        title_row.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(title_row, text="Plot Title:").pack(side="left")
        plot_title_entry = ttk.Entry(title_row, textvariable=plot_title_var, width=30)
        plot_title_entry.pack(side="left", padx=(2, 10))
        # [수정] "Title 박스 입력이 안되어서 오메가(Ω) 문자창 입력 되게 하라" -
        # 기존 "Ω" 심볼 창(open_permanent_symbol_window)은 항상 self.active_entry에
        # 삽입하는데, 2D의 title/xlabel/ylabel/y2label Entry만 <FocusIn>에서
        # set_active_entry를 해뒀고 이 3D 팝업의 새 입력칸들은 안 돼 있어서 Ω 창을
        # 열어도 여기 포커스로는 아무 데도 안 들어갔던 것 - 2D와 동일하게 바인딩.
        plot_title_entry.bind("<FocusIn>", lambda e: self.set_active_entry(plot_title_entry))
        # [추가] "Ω 선택 창은 떠 있으면 2D/3D 모두 사용 가능, 없으면 띄우고 사용" -
        # open_permanent_symbol_window가 이미 그 로직(떠 있으면 앞으로, 없으면 새로
        # 열기)이라 그대로 재사용. 메인 창 툴바에만 버튼이 있어 3D 팝업을 띄운
        # 상태에서는 손이 안 갈 수 있으니 이 팝업 안에도 같은 버튼을 둔다.
        # [수정] "3D 창의 Ω버튼이 상대적으로 너무 큼(Plot Title 입력칸 높이의
        # 1.5배 정도가 적당, 지금은 2배로 보임)" - font 12->10, bd 2->1,
        # pady 명시(1)로 줄여 옆 Plot Title Entry와 비슷한 비율로 맞춘다.
        tk.Button(
            title_row, text=chr(937), width=3,
            font=("Malgun Gothic", 10, "bold"),
            bg=self.PALETTE["amber"], fg="white",
            activebackground=self.PALETTE["amber_dark"], activeforeground="white",
            relief="raised", bd=1, pady=1,
            command=self.open_permanent_symbol_window
        ).pack(side="left", padx=(0, 10))

        # [추가] "X,Y,Z title 입력박스 필요" - 2D의 xlabel/ylabel/y2label을 그대로
        # 재사용하지 않고 3D 전용으로 따로 입력받는다(3D는 Z가 y2label 자리를
        # 대신 쓰는 등 2D와 축 의미가 달라서 같은 값을 강제로 공유하면 어색함).
        # 기존 기본값(Time/Output #)은 그대로 두되, "splot에서 y-title에
        # Output #는 부적절함" 피드백으로 기본값을 Data_No로 바꿈.
        # [수정] "splot만 그릴 때 z-title이 비어 있는 대신 Dat list의 title을
        # 활용" - curve 없이 surface만 있으면(2D Y2 label을 그대로 물려받는 게
        # 의미 없음) Z title 기본값을 surface의 표시명으로 채운다.
        # [수정 - 버그] "x,y,z 선택 안 하고 s-plot 파일만 읽으면 축 title이
        # 2D title로 나타남" - self.xlabel_var/ylabel_var/y2label_var는 "완전히
        # 빈 문자열"일 때만 기본값(Time/Data_No)으로 대체했는데, 이전에 2D 작업
        # 하면서 이미 값을 채워둔 상태라면 그 값이 surface 전용 3D에도 그대로
        # 새어 들어옴(2D의 xlabel/y2label은 curve 데이터 의미라 surface의 raw
        # time/output_no/value 컬럼과는 전혀 무관함) - eligible(curve)이 있을
        # 때만 2D 값을 물려받고, 없으면(surface만) 항상 Time/Data_No/surface
        # 표시명을 쓴다.
        row0 = ttk.Frame(dialog)
        row0.pack(fill="x", padx=10, pady=5)
        if eligible:
            xlabel3d_var = tk.StringVar(value=self.xlabel_var.get() or "Time")
            ylabel3d_var = tk.StringVar(value=self.ylabel_var.get() or "Data_No")
            _default_zlabel = self.y2label_var.get()
            if not _default_zlabel and surfaces:
                _default_zlabel = surfaces[0].get("z_label", "")
        else:
            xlabel3d_var = tk.StringVar(value="Time")
            ylabel3d_var = tk.StringVar(value="Data_No")
            _default_zlabel = surfaces[0].get("z_label", "") if surfaces else ""
        zlabel3d_var = tk.StringVar(value=_default_zlabel)
        ttk.Label(row0, text="X title:").pack(side="left")
        xlabel3d_entry = ttk.Entry(row0, textvariable=xlabel3d_var, width=14)
        xlabel3d_entry.pack(side="left", padx=(2, 10))
        xlabel3d_entry.bind("<FocusIn>", lambda e: self.set_active_entry(xlabel3d_entry))
        ttk.Label(row0, text="Y title:").pack(side="left")
        ylabel3d_entry = ttk.Entry(row0, textvariable=ylabel3d_var, width=14)
        ylabel3d_entry.pack(side="left", padx=(2, 10))
        ylabel3d_entry.bind("<FocusIn>", lambda e: self.set_active_entry(ylabel3d_entry))
        ttk.Label(row0, text="Z title:").pack(side="left")
        zlabel3d_entry = ttk.Entry(row0, textvariable=zlabel3d_var, width=14)
        zlabel3d_entry.pack(side="left", padx=(2, 10))
        zlabel3d_entry.bind("<FocusIn>", lambda e: self.set_active_entry(zlabel3d_entry))

        row1 = ttk.Frame(dialog)
        row1.pack(fill="x", padx=10, pady=5)
        rot_x_var = tk.StringVar(value="60")
        rot_z_var = tk.StringVar(value="30")
        ttk.Label(row1, text="Rotate X:").pack(side="left")
        ttk.Entry(row1, textvariable=rot_x_var, width=5).pack(side="left", padx=(2, 10))
        ttk.Label(row1, text="Rotate Z:").pack(side="left")
        ttk.Entry(row1, textvariable=rot_z_var, width=5).pack(side="left", padx=(2, 10))

        # [수정] "X(Time) range 입력칸들을 Z-range 입력들과 세로 정렬" - 예전엔
        # Time range가 Rotate X/Z와 같은 줄(row1)에, Y/Z range는 다음 줄(row1b)에
        # 있어서 앞쪽 라벨 폭이 서로 달라(Rotate X: vs Y range Min:) 입력칸
        # 가로 위치가 줄마다 어긋나 보였음 - X/Y/Z range를 전부 한 줄로 모아
        # 라벨 형식을 통일하면 애초에 어긋날 일이 없어짐. "Time"이라는 이름도
        # X/Y/Z 표기와 안 맞아 헷갈렸던 것 - splot의 X축이라는 의미가 분명하도록
        # "X range"로 통일한다(내부 변수명은 time_min_var/time_max_var 그대로 유지).
        # [추가] "splot 입력 자료에서 time 구간 입력 필요(필요 구간 data만 plot)"
        # - 셋 다(X/Y/Z) 비우면 전체 구간(제한 없음), 2D의 Auto Range/Min/Max와
        # 같은 개념.
        row1b = ttk.Frame(dialog)
        row1b.pack(fill="x", padx=10, pady=(0, 5))
        time_min_var = tk.StringVar(value="")
        time_max_var = tk.StringVar(value="")
        y_min_var = tk.StringVar(value="")
        y_max_var = tk.StringVar(value="")
        z_min_var = tk.StringVar(value="")
        z_max_var = tk.StringVar(value="")
        ttk.Label(row1b, text="X range Min:").pack(side="left")
        ttk.Entry(row1b, textvariable=time_min_var, width=8).pack(side="left", padx=(2, 5))
        ttk.Label(row1b, text="Max:").pack(side="left")
        ttk.Entry(row1b, textvariable=time_max_var, width=8).pack(side="left", padx=(2, 10))
        ttk.Label(row1b, text="Y range Min:").pack(side="left")
        ttk.Entry(row1b, textvariable=y_min_var, width=8).pack(side="left", padx=(2, 5))
        ttk.Label(row1b, text="Max:").pack(side="left")
        ttk.Entry(row1b, textvariable=y_max_var, width=8).pack(side="left", padx=(2, 10))
        ttk.Label(row1b, text="Z range Min:").pack(side="left")
        ttk.Entry(row1b, textvariable=z_min_var, width=8).pack(side="left", padx=(2, 5))
        ttk.Label(row1b, text="Max:").pack(side="left")
        ttk.Entry(row1b, textvariable=z_max_var, width=8).pack(side="left", padx=(2, 0))

        row2 = ttk.Frame(dialog)
        row2.pack(fill="x", padx=10, pady=5)
        palette_var = tk.StringVar(value="rainbow")
        colorbox_var = tk.BooleanVar(value=True)
        ttk.Label(row2, text="Palette:").pack(side="left")
        ttk.Combobox(row2, textvariable=palette_var, values=["rainbow", "grayscale", "bluewhitered"],
                     width=12, state="readonly").pack(side="left", padx=(2, 10))
        self._mk_check(row2, "Colorbox", colorbox_var, side="left", padx=(10, 0))
        equal_xyz_var = tk.BooleanVar(value=False)
        self._mk_check(row2, "Equal XYZ scale", equal_xyz_var, side="left", padx=(10, 0))

        # [수정] "Marker Size를 세트 선택 줄로 이동(모양 앞에), Style도 세트별로
        # (curve마다 다르게 줄 수 있으므로) 이동 - Color Palette(입체채색)는
        # s-plot(surface)에만 의미가 있으니 curve 행에는 그 옵션 자체를 빼서
        # s-plot에서만 선택 가능하게 함" - curve/surface 체크박스, Style,
        # Marker Size, Marker 모양을 한 줄에서 같이 고른다.
        set_frame = ttk.LabelFrame(dialog, text="포함할 Set (체크 해제로 제외, Style·Size·Marker 모양을 세트별로 지정)")
        set_frame.pack(fill="x", padx=10, pady=5)
        _shape_choices = [s for s in MARKER_SHAPE_LIST if s != "None"]
        _style_choices_curve = [v for k, v in STYLE_3D_DISPLAY_MAP.items() if k != "pm3d"]
        _style_choices_surface = list(STYLE_3D_DISPLAY_MAP.values())
        _set_idx = 0
        curve_check_vars = []    # [(BooleanVar, curve_dict, shape_StringVar, size_StringVar, style_StringVar), ...]
        surface_check_vars = []  # [(BooleanVar, surface_dict, shape_StringVar, size_StringVar, style_StringVar), ...]
        for c in eligible:
            srow = ttk.Frame(set_frame)
            srow.pack(fill="x", pady=1)
            v = tk.BooleanVar(value=True)
            self._mk_check(srow, f"[Curve] {c['label']}", v, color="accent", side="left")
            shape_var = tk.StringVar(value=_shape_choices[_set_idx % len(_shape_choices)])
            size_var = tk.StringVar(value="M")
            style_var_row = tk.StringVar(value=STYLE_3D_DISPLAY_MAP["lines"])
            ttk.Combobox(srow, textvariable=shape_var, values=MARKER_SHAPE_LIST,
                         width=10, state="readonly").pack(side="right", padx=4)
            ttk.Combobox(srow, textvariable=size_var, values=MARKER_SIZE_LIST,
                         width=4, state="readonly").pack(side="right", padx=4)
            ttk.Combobox(srow, textvariable=style_var_row, values=_style_choices_curve,
                         width=13, state="readonly").pack(side="right", padx=4)
            curve_check_vars.append((v, c, shape_var, size_var, style_var_row))
            _set_idx += 1
        for s in surfaces:
            srow = ttk.Frame(set_frame)
            srow.pack(fill="x", pady=1)
            v = tk.BooleanVar(value=True)
            self._mk_check(srow, f"[Surface] {s['label']} (채널 {s['n_outputs']}개, Z={s['z_label']})", v,
                            color="amber", side="left")
            shape_var = tk.StringVar(value=_shape_choices[_set_idx % len(_shape_choices)])
            size_var = tk.StringVar(value="M")
            style_var_row = tk.StringVar(value=STYLE_3D_DISPLAY_MAP["lines"])
            ttk.Combobox(srow, textvariable=shape_var, values=MARKER_SHAPE_LIST,
                         width=10, state="readonly").pack(side="right", padx=4)
            ttk.Combobox(srow, textvariable=size_var, values=MARKER_SIZE_LIST,
                         width=4, state="readonly").pack(side="right", padx=4)
            ttk.Combobox(srow, textvariable=style_var_row, values=_style_choices_surface,
                         width=13, state="readonly").pack(side="right", padx=4)
            surface_check_vars.append((v, s, shape_var, size_var, style_var_row))
            _set_idx += 1

        # [수정 - 버그] "선택 여부에 따라 Plot Title/Z title의 default가 바뀌게" -
        # 위 체크박스들이 이제서야 다 만들어졌으니, 실제로 체크된 첫 curve(없으면
        # 첫 surface)를 기준으로 Plot Title/Z title 기본값을 다시 채운다. 체크를
        # 켰다 껐다 할 때마다 다시 계산해서 반영하되, 사용자가 이미 손으로 값을
        # 고쳐놨으면(=마지막으로 자동으로 채워준 값과 다르면) 덮어쓰지 않는다.
        _auto_title = {"plot": plot_title_var.get(), "z": zlabel3d_var.get()}

        def _first_checked_curve():
            for v, item, *_ in curve_check_vars:
                if v.get():
                    return item
            return None

        def _first_checked_surface():
            for v, item, *_ in surface_check_vars:
                if v.get():
                    return item
            return None

        _auto_title["x"] = xlabel3d_var.get()
        _auto_title["y"] = ylabel3d_var.get()

        def _sync_default_titles(*_args):
            # [수정 - 버그] "3-D Plot Title 기본값이 2-D의 Plot Title(파일명)로
            # 새어 들어옴 - 체크된 첫 curve/surface 이름이 없으면 그냥 blank여야
            # 함" - self.filename_var(2D 메인 창이 보고 있는 파일)로 떨어지는
            # 폴백과 "CathPlot" 폴백을 없애서, 체크된 게 하나도 없으면(전부
            # 체크 해제) 3D와 무관한 값 대신 빈 문자열이 되게 한다.
            # [수정 - 버그] "Plot Title은 filename만(확장자는 지우고) 사용" -
            # label(예: out111.dat, 중복시 out111-1.dat)에서 확장자만 뗀다
            # (Dat list/legend 표시용 label 자체는 확장자 포함 그대로 유지 -
            # 여기 Plot Title 기본값에만 적용).
            # [수정 - 버그] "1번 file 체크 해제해도 axis-title은 여전히 1번
            # file 것 - 차순위 file(또는 s-plot)의 X/Y1/Y2(Z)로 바뀌어야 함" -
            # Plot Title처럼 X/Y title도 체크된 첫 curve의 실제 변수명(legend
            # 이름, _collect_3d_curves에서 미리 담아둔 x_title/y_title)을
            # 따라가게 한다. curve가 없고 surface만 체크됐으면(surface는 raw
            # CATHENA 포맷이라 X=Time, Y=Data_No가 항상 맞음) 기존처럼 고정값.
            _cur = _first_checked_curve()
            _surf = _first_checked_surface()
            new_plot_title = os.path.splitext((_cur or _surf or {}).get("label") or "")[0]
            if plot_title_var.get() == _auto_title["plot"]:
                plot_title_var.set(new_plot_title)
            _auto_title["plot"] = new_plot_title

            if _cur is not None:
                new_xlabel = _cur.get("x_title") or "Time"
                new_ylabel = _cur.get("y_title") or "Data_No"
            else:
                new_xlabel = "Time"
                new_ylabel = "Data_No"
            if xlabel3d_var.get() == _auto_title["x"]:
                xlabel3d_var.set(new_xlabel)
            _auto_title["x"] = new_xlabel
            if ylabel3d_var.get() == _auto_title["y"]:
                ylabel3d_var.set(new_ylabel)
            _auto_title["y"] = new_ylabel

            if _surf is not None:
                new_zlabel = _surf.get("z_label", "") or _surf.get("label", "")
            elif _cur is not None:
                new_zlabel = _cur.get("y2_title") or ""
            else:
                new_zlabel = ""
            if zlabel3d_var.get() == _auto_title["z"]:
                zlabel3d_var.set(new_zlabel)
            _auto_title["z"] = new_zlabel

        for v, *_rest in curve_check_vars:
            v.trace_add("write", _sync_default_titles)
        for v, *_rest in surface_check_vars:
            v.trace_add("write", _sync_default_titles)
        _sync_default_titles()  # 다이얼로그를 처음 열 때도 한 번 반영(전부 체크된 초기 상태 기준)

        # [추가] "comment, arrow 등은 3D 전용으로 popup 창에서 입력, 이때는
        # 좌표값으로 통일 (x,y,z)" - 2D 입력과 완전히 별개로, 이 팝업 안에서만
        # 쓰이는 3D 전용 목록.
        anno3d_list = []
        arrow3d_list = []

        anno3d_frame = ttk.LabelFrame(dialog, text="3D Comment/Arrow (좌표값 X,Y,Z)")
        anno3d_frame.pack(fill="x", padx=10, pady=5)
        c3d_list_frame = ttk.Frame(anno3d_frame)
        c3d_list_frame.pack(fill="x")
        a3d_list_frame = ttk.Frame(anno3d_frame)
        a3d_list_frame.pack(fill="x")

        def add_3d_comment_row():
            row = ttk.Frame(c3d_list_frame)
            row.pack(fill="x", pady=0)
            data = {'txt': tk.StringVar(), 'x': tk.StringVar(), 'y': tk.StringVar(), 'z': tk.StringVar(),
                    'color': tk.StringVar(value="Auto"), 'frame': row}
            anno3d_list.append(data)
            ttk.Button(row, text="X", width=2, style="Compact.TButton", command=lambda: (row.destroy(), anno3d_list.remove(data))).pack(side="right", padx=3)
            ttk.Combobox(row, textvariable=data['color'], values=COLOR_LIST, width=6, state="readonly").pack(side="right", padx=2)
            ttk.Label(row, text="[Comment]", foreground="blue").pack(side="left", padx=(0, 3))
            txt3d_entry = ttk.Entry(row, textvariable=data['txt'], width=14)
            txt3d_entry.pack(side="left", padx=2)
            # [추가] "Comment창에도 Ω창에서 입력 가능하게" - 2D Comment와 동일.
            txt3d_entry.bind("<FocusIn>", lambda e: self.set_active_entry(txt3d_entry))
            ttk.Label(row, text="(X,Y,Z):").pack(side="left")
            xyz_entry, _ = self._make_xyz_combo_entry(row, data['x'], data['y'], data['z'], "", "", "")
            xyz_entry.pack(side="left", padx=2)

        def add_3d_arrow_row():
            row = ttk.Frame(a3d_list_frame)
            row.pack(fill="x", pady=0)
            data = {'x1': tk.StringVar(), 'y1': tk.StringVar(), 'z1': tk.StringVar(),
                    'x2': tk.StringVar(), 'y2': tk.StringVar(), 'z2': tk.StringVar(),
                    'color': tk.StringVar(value="Auto"), 'size': tk.StringVar(value="M"), 'frame': row}
            arrow3d_list.append(data)
            ttk.Button(row, text="X", width=2, style="Compact.TButton", command=lambda: (row.destroy(), arrow3d_list.remove(data))).pack(side="right", padx=3)
            ttk.Combobox(row, textvariable=data['color'], values=COLOR_LIST, width=6, state="readonly").pack(side="right", padx=2)
            ttk.Combobox(row, textvariable=data['size'], values=list(self.ARROW_SIZE_MAP.keys()), width=4, state="readonly").pack(side="right", padx=2)
            ttk.Label(row, text="[Arrow]", foreground="darkred").pack(side="left", padx=(0, 3))
            ttk.Label(row, text="(X1,Y1,Z1):").pack(side="left")
            xyz1_entry, _ = self._make_xyz_combo_entry(row, data['x1'], data['y1'], data['z1'], "", "", "", width=12)
            xyz1_entry.pack(side="left", padx=2)
            ttk.Label(row, text="→ (X2,Y2,Z2):").pack(side="left")
            xyz2_entry, _ = self._make_xyz_combo_entry(row, data['x2'], data['y2'], data['z2'], "", "", "", width=12)
            xyz2_entry.pack(side="left", padx=2)

        btn3d_row = ttk.Frame(anno3d_frame)
        btn3d_row.pack(fill="x", pady=2)
        ttk.Button(btn3d_row, text="+ Add 3D Comment", command=add_3d_comment_row).pack(side="left", padx=5)
        ttk.Button(btn3d_row, text="+ Add 3D Arrow", command=add_3d_arrow_row).pack(side="left", padx=5)

        def _collect_3d_state():
            """Plot/Save/Print 버튼이 공통으로 쓰는 다이얼로그 입력값 수집(중복 방지)."""
            try:
                rot_x = float(rot_x_var.get() or 60)
            except ValueError:
                rot_x = 60
            try:
                rot_z = float(rot_z_var.get() or 30)
            except ValueError:
                rot_z = 30

            annotations_3d = []
            for d in anno3d_list:
                if d['txt'].get().strip() and d['x'].get().strip() and d['y'].get().strip() and d['z'].get().strip():
                    annotations_3d.append({
                        "text": d['txt'].get(), "x": d['x'].get(), "y": d['y'].get(), "z": d['z'].get(),
                        "color": COLOR_MAP.get(d['color'].get(), ""),
                    })
            arrows_3d = []
            for d in arrow3d_list:
                if all(d[k].get().strip() for k in ('x1', 'y1', 'z1', 'x2', 'y2', 'z2')):
                    arrows_3d.append({
                        "x1": d['x1'].get(), "y1": d['y1'].get(), "z1": d['z1'].get(),
                        "x2": d['x2'].get(), "y2": d['y2'].get(), "z2": d['z2'].get(),
                        "color": COLOR_MAP.get(d['color'].get(), ""),
                        "head_size": self.ARROW_SIZE_MAP.get(d['size'].get(), self.ARROW_SIZE_MAP["M"]),
                    })

            # [수정] "Marker Size를 세트별로, Style도 세트별로(curve마다 다르게
            # 줄 수 있으므로) 이동" - 예전엔 전체 공용 하나였는데, 이제 각 행의
            # size_var/style_var_row를 그대로 쓴다. 체크 해제된 set은 제외.
            curves_final = []
            for v, c, shape_var, size_var, style_var_row in curve_check_vars:
                if not v.get():
                    continue
                c2 = dict(c)
                hollow_pt, _filled_pt = MARKER_SHAPE_MAP.get(shape_var.get(), (None, None))
                c2["marker_shape"] = hollow_pt
                c2["marker_size"] = MARKER_SIZE_MAP.get(size_var.get(), 1.0)
                c2["style"] = STYLE_3D_INTERNAL_MAP.get(style_var_row.get(), "lines")
                c2["title"] = c["label"]
                curves_final.append(c2)

            surfaces_final = []
            for v, s, shape_var, size_var, style_var_row in surface_check_vars:
                if not v.get():
                    continue
                s2 = dict(s)
                hollow_pt, _filled_pt = MARKER_SHAPE_MAP.get(shape_var.get(), (None, None))
                s2["marker_shape"] = hollow_pt
                s2["marker_size"] = MARKER_SIZE_MAP.get(size_var.get(), 1.0)
                s2["style"] = STYLE_3D_INTERNAL_MAP.get(style_var_row.get(), "lines")
                surfaces_final.append(s2)

            # [추가] "time 구간 입력" - 비우면 제한 없음(None).
            def _parse_opt_float(s):
                s = (s or "").strip()
                if not s:
                    return None
                try:
                    return float(s)
                except ValueError:
                    return None
            time_min = _parse_opt_float(time_min_var.get())
            time_max = _parse_opt_float(time_max_var.get())
            y_min = _parse_opt_float(y_min_var.get())
            y_max = _parse_opt_float(y_max_var.get())
            z_min = _parse_opt_float(z_min_var.get())
            z_max = _parse_opt_float(z_max_var.get())

            # [수정] Style이 세트별로 바뀌면서 여기서 쓰던 전역 style은 없어짐 -
            # create_3d_script의 style 파라미터는 이제 "세트에 style이 없을 때"의
            # 방어적 기본값 역할만 하므로 고정값 "lines"만 넘긴다.
            return (curves_final, rot_x, rot_z, "lines", palette_var.get(),
                    colorbox_var.get(), annotations_3d, arrows_3d, equal_xyz_var.get(), surfaces_final,
                    xlabel3d_var.get(), ylabel3d_var.get(), zlabel3d_var.get(),
                    plot_title_var.get(), time_min, time_max, y_min, y_max, z_min, z_max)

        def do_plot():
            # [수정] "3D Plot 추가 창은 plot 후에도 닫지 말 것" - rot_x/rot_z를
            # 조금씩 바꿔가며 여러 번 그려보는 용도가 많아서, 매번 다이얼로그를
            # 다시 열고 curve/comment/arrow 설정을 새로 고르는 게 번거로웠음.
            args = _collect_3d_state()
            self._execute_3d_plot(*args)

        def _close_3d_dialog():
            # [수정] "3D plot 창을 닫고 나면 Dat list에서 splot 파일 설명이
            # 없어짐(다시 3D Plot을 누르면 정상 복귀)" - 코드상 3D 다이얼로그가
            # file_rows/meta를 건드리는 곳은 없어서 데이터 자체가 사라지는 건
            # 아니고, 자식 Toplevel이 닫힐 때 부모 캔버스(scrollable_frame)가
            # 제대로 다시 그려지지 않는 Tk의 재도장(repaint) 지연 증상으로 보임 -
            # 다이얼로그를 닫을 때마다 Dat list를 강제로 다시 그려서 항상 최신
            # 상태로 보이게 한다(show_variables는 그리기만 다시 하는 거라
            # 데이터가 이미 정상이면 아무 부작용 없음).
            dialog.destroy()
            self.show_variables()

        dialog.protocol("WM_DELETE_WINDOW", _close_3d_dialog)

        def do_save():
            args = _collect_3d_state()
            _close_3d_dialog()
            self._save_3d_plot(*args)

        def do_print():
            args = _collect_3d_state()
            _close_3d_dialog()
            self._print_3d_plot(*args)

        # [추가] "3D template는 따로 3D 창에서 save/load" - 2D Template
        # Save/Load(메인 창 버튼)와는 완전히 별개로, 이 팝업 자체의 설정(회전각,
        # Style, Palette, Marker 모양, Comment/Arrow 등)만 저장/복원한다. curve/
        # surface 목록은 그때그때 로드된 파일 기준으로 다시 만들어지므로 저장 안
        # 하고, Marker 모양만 label(파일명) 기준으로 매칭해서 복원한다.
        def _3d_template_dict():
            # [수정] "Marker Size, Style을 세트별로" - marker_shapes와 같은 방식
            # (label 기준 dict)으로 세트별 크기/스타일도 같이 저장한다.
            _shapes, _sizes, _styles = {}, {}, {}
            for v, c, shape_var, size_var, style_var_row in curve_check_vars:
                _shapes[c["label"]] = shape_var.get()
                _sizes[c["label"]] = size_var.get()
                _styles[c["label"]] = style_var_row.get()
            for v, s, shape_var, size_var, style_var_row in surface_check_vars:
                _shapes[s["label"]] = shape_var.get()
                _sizes[s["label"]] = size_var.get()
                _styles[s["label"]] = style_var_row.get()
            return {
                "type": "cathplot_3d_template",
                "plot_title": plot_title_var.get(),
                "xlabel3d": xlabel3d_var.get(), "ylabel3d": ylabel3d_var.get(), "zlabel3d": zlabel3d_var.get(),
                "rot_x": rot_x_var.get(), "rot_z": rot_z_var.get(),
                "time_min": time_min_var.get(), "time_max": time_max_var.get(),
                "y_min": y_min_var.get(), "y_max": y_max_var.get(),
                "z_min": z_min_var.get(), "z_max": z_max_var.get(),
                "palette": palette_var.get(),
                "colorbox": colorbox_var.get(),
                "equal_xyz": equal_xyz_var.get(),
                "marker_shapes": _shapes, "marker_sizes": _sizes, "styles": _styles,
                "annotations_3d": [
                    {"txt": d['txt'].get(), "x": d['x'].get(), "y": d['y'].get(), "z": d['z'].get(),
                     "color": d['color'].get()}
                    for d in anno3d_list
                ],
                "arrows_3d": [
                    {"x1": d['x1'].get(), "y1": d['y1'].get(), "z1": d['z1'].get(),
                     "x2": d['x2'].get(), "y2": d['y2'].get(), "z2": d['z2'].get(),
                     "color": d['color'].get(), "size": d['size'].get()}
                    for d in arrow3d_list
                ],
            }

        def do_save_3d_template():
            # [수정] "저장할 때 default로 plottitle_3d_...가 좋겠다" - 3D Plot
            # 이미지 저장(_execute_3d_plot의 base_name)과 동일한 규칙(이름_3D_번호).
            template_dir = os.path.join(self.cwd, "template")
            os.makedirs(template_dir, exist_ok=True)
            raw_title = plot_title_var.get().strip() or "CathPlot"
            safe_title = "".join(c for c in raw_title if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"
            next_id = self.title_counters.get(safe_title, 0) + 1
            default_name = f"{safe_title}_3D_{next_id}"
            filepath = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("CathPlot 3D Template", "*.json")],
                initialdir=template_dir, initialfile=default_name,
                title="Save 3D Template"
            )
            if not filepath:
                return
            self.title_counters[safe_title] = next_id
            try:
                import json
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(_3d_template_dict(), f, indent=2, ensure_ascii=False)
                messagebox.showinfo("3D Template", f"3D 템플릿을 저장했습니다:\n{filepath}")
            except Exception as e:
                messagebox.showerror("3D Template", f"3D 템플릿 저장 실패: {e}")

        def do_load_3d_template():
            template_dir = os.path.join(self.cwd, "template")
            filepath = filedialog.askopenfilename(
                filetypes=[("CathPlot 3D Template", "*.json"), ("All files", "*.*")],
                initialdir=template_dir if os.path.isdir(template_dir) else self.cwd,
                title="Load 3D Template"
            )
            if not filepath:
                return
            try:
                import json
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                messagebox.showerror("3D Template", f"3D 템플릿 불러오기 실패: {e}")
                return

            plot_title_var.set(data.get("plot_title", plot_title_var.get()))
            xlabel3d_var.set(data.get("xlabel3d", xlabel3d_var.get()))
            ylabel3d_var.set(data.get("ylabel3d", ylabel3d_var.get()))
            zlabel3d_var.set(data.get("zlabel3d", zlabel3d_var.get()))
            rot_x_var.set(data.get("rot_x", rot_x_var.get()))
            rot_z_var.set(data.get("rot_z", rot_z_var.get()))
            time_min_var.set(data.get("time_min", ""))
            time_max_var.set(data.get("time_max", ""))
            y_min_var.set(data.get("y_min", ""))
            y_max_var.set(data.get("y_max", ""))
            z_min_var.set(data.get("z_min", ""))
            z_max_var.set(data.get("z_max", ""))
            palette_var.set(data.get("palette", palette_var.get()))
            colorbox_var.set(data.get("colorbox", True))
            equal_xyz_var.set(data.get("equal_xyz", False))

            # [수정] "Marker Size, Style을 세트별로" - label 기준으로 각 행에
            # 복원(예전 템플릿의 "marker_size"/"style" 전역 키는 없으면 무시됨).
            _shapes = data.get("marker_shapes", {})
            _sizes = data.get("marker_sizes", {})
            _styles = data.get("styles", {})
            for v, c, shape_var, size_var, style_var_row in curve_check_vars:
                if c["label"] in _shapes:
                    shape_var.set(_shapes[c["label"]])
                if c["label"] in _sizes:
                    size_var.set(_sizes[c["label"]])
                if c["label"] in _styles:
                    style_var_row.set(_styles[c["label"]])
            for v, s, shape_var, size_var, style_var_row in surface_check_vars:
                if s["label"] in _shapes:
                    shape_var.set(_shapes[s["label"]])
                if s["label"] in _sizes:
                    size_var.set(_sizes[s["label"]])
                if s["label"] in _styles:
                    style_var_row.set(_styles[s["label"]])

            for d in list(anno3d_list):
                d['frame'].destroy()
            anno3d_list.clear()
            for ad in data.get("annotations_3d", []):
                add_3d_comment_row()
                last = anno3d_list[-1]
                last['txt'].set(ad.get("txt", ""))
                last['x'].set(ad.get("x", "")); last['y'].set(ad.get("y", "")); last['z'].set(ad.get("z", ""))
                last['color'].set(ad.get("color", "Auto"))

            for d in list(arrow3d_list):
                d['frame'].destroy()
            arrow3d_list.clear()
            for ar in data.get("arrows_3d", []):
                add_3d_arrow_row()
                last = arrow3d_list[-1]
                last['x1'].set(ar.get("x1", "")); last['y1'].set(ar.get("y1", "")); last['z1'].set(ar.get("z1", ""))
                last['x2'].set(ar.get("x2", "")); last['y2'].set(ar.get("y2", "")); last['z2'].set(ar.get("z2", ""))
                last['color'].set(ar.get("color", "Auto")); last['size'].set(ar.get("size", "M"))

            messagebox.showinfo("3D Template", "3D 템플릿을 불러왔습니다.")

        # [수정] "3D popup 창도 채색?" - 메인 화면과 같은 팔레트/방식(tk.Button
        # + 명시적 bg/fg)으로 이 팝업의 주요 동작 버튼도 색을 입힌다.
        def _dlg_accent_btn(parent, text, bg, dark, command):
            b = tk.Button(
                parent, text=text, command=command,
                font=("Malgun Gothic", 9, "bold"), bg=bg, fg="white",
                activebackground=dark, activeforeground="white",
                relief="raised", bd=2, padx=8,
            )
            b.pack(side="left", padx=5)
            return b

        pal = self.PALETTE
        template3d_row = ttk.Frame(dialog)
        template3d_row.pack(fill="x", padx=10, pady=(0, 5))
        _dlg_accent_btn(template3d_row, "3D Template Save", pal["grey"], pal["grey_dark"], do_save_3d_template)
        _dlg_accent_btn(template3d_row, "3D Template Load", pal["grey"], pal["grey_dark"], do_load_3d_template)

        ok_row = ttk.Frame(dialog)
        ok_row.pack(fill="x", padx=10, pady=10)
        _dlg_accent_btn(ok_row, "Plot", pal["accent"], pal["accent_dark"], do_plot)
        _dlg_accent_btn(ok_row, "Save", pal["accent2"], pal["accent2_dark"], do_save)
        _dlg_accent_btn(ok_row, "Print", pal["accent3"], pal["accent3_dark"], do_print)
        _dlg_accent_btn(ok_row, "Cancel", pal["danger"], pal["danger_dark"], _close_3d_dialog)

    def _execute_3d_plot(self, curves, rot_x, rot_z, style, palette, colorbox, annotations_3d, arrows_3d,
                          equal_xyz=False, surfaces=None, xlabel3d="", ylabel3d="", zlabel3d="",
                          plot_title="", time_min=None, time_max=None,
                          y_min=None, y_max=None, z_min=None, z_max=None):
        os.makedirs(self.plot_dir, exist_ok=True)
        # [수정 - 버그] "Plot Title/axis title을 blank로 두면 plot에도 blank로
        # 나와야 하는데, 선택도 안 한 첫 파일명이 뜸" - 팝업의 Plot Title
        # 입력값을 그대로 쓰되(filename_var를 무조건 쓰지 않음), 저장 파일명
        # 생성용(safe_title/base_name)에만 빈 값일 때 대체값을 쓰고, 실제
        # 그래프에 찍히는 title(title_for_plot)은 사용자가 비웠으면 그대로
        # 빈 채로 create_3d_script에 넘긴다(create_3d_script는 title이
        # falsy면 "set title" 자체를 안 씀 - 완전히 안 나옴).
        title_for_plot = (plot_title or "").strip()
        raw_title = title_for_plot or self.filename_var.get().strip() or "CathPlot"
        safe_title = "".join(c for c in raw_title if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"
        next_id = self.title_counters.get(safe_title, 0) + 1
        base_name = f"{safe_title}_3D_{next_id}"
        outfile = os.path.join(self.plot_dir, f"{base_name}.plt")
        self.title_counters[safe_title] = next_id

        generator = GnuplotGenerator(self.plot_dir)
        try:
            generator.create_3d_script(
                curves, outfile, fmt="interactive",
                # [수정 - 버그] X/Y/Z title도 같은 이유로 "or 기본값" 폴백을
                # 없앤다 - 사용자가 비웠으면 축 title 없이 그대로 나와야 함.
                # 기본값(Time/Data_No/surface 이름)은 다이얼로그가 열릴 때
                # _sync_default_titles가 이미 채워주므로, 여기서 다시 덮어쓸
                # 필요가 없다(오히려 사용자가 일부러 비운 걸 되돌리는 버그였음).
                xlabel=xlabel3d, ylabel=ylabel3d, zlabel=zlabel3d,
                title=title_for_plot,
                xlog=self.xlog_var.get(), ylog=self.y1log_var.get(), zlog=self.y2log_var.get(),
                rot_x=rot_x, rot_z=rot_z, style=style, palette=palette, colorbox=colorbox,
                annotations_3d=annotations_3d, arrows_3d=arrows_3d, equal_xyz=equal_xyz,
                surfaces=surfaces, time_min=time_min, time_max=time_max,
                y_min=y_min, y_max=y_max, z_min=z_min, z_max=z_max,
            )
        except Exception as e:
            messagebox.showerror("3D Plot Error", str(e))

    def _generate_3d_file(self, outfile, fmt, curves, rot_x, rot_z, style, palette, colorbox,
                           annotations_3d, arrows_3d, equal_xyz, surfaces, xlabel3d="", ylabel3d="", zlabel3d="",
                           plot_title="", time_min=None, time_max=None,
                           y_min=None, y_max=None, z_min=None, z_max=None):
        """Save/Print가 공통으로 쓰는, 파일로 직접 렌더링하는 부분만 뽑은 버전
        (_execute_3d_plot의 화면(interactive) 전용 코드와 outfile/fmt만 다름)."""
        # [수정 - 버그] blank Plot Title/axis title이 폴백값으로 되돌아가던
        # 문제 - _execute_3d_plot과 동일하게 수정(위 주석 참고).
        title_for_plot = (plot_title or "").strip()
        generator = GnuplotGenerator(self.plot_dir)
        generator.create_3d_script(
            curves, outfile, fmt=fmt,
            xlabel=xlabel3d, ylabel=ylabel3d, zlabel=zlabel3d,
            title=title_for_plot,
            xlog=self.xlog_var.get(), ylog=self.y1log_var.get(), zlog=self.y2log_var.get(),
            rot_x=rot_x, rot_z=rot_z, style=style, palette=palette, colorbox=colorbox,
            annotations_3d=annotations_3d, arrows_3d=arrows_3d, equal_xyz=equal_xyz,
            surfaces=surfaces, time_min=time_min, time_max=time_max,
            y_min=y_min, y_max=y_max, z_min=z_min, z_max=z_max,
        )

    def _save_3d_plot(self, curves, rot_x, rot_z, style, palette, colorbox, annotations_3d, arrows_3d,
                       equal_xyz=False, surfaces=None, xlabel3d="", ylabel3d="", zlabel3d="",
                       plot_title="", time_min=None, time_max=None,
                       y_min=None, y_max=None, z_min=None, z_max=None):
        """[추가] "3D Plot도 저장 지원" - 2D SAVE와 동일한 포맷 선택 방식,
        방향/Frame 크기 선택 등 2D의 복잡한 캐시 선택 로직 없이 지금 다이얼로그
        입력값 그대로 바로 파일로 렌더링한다."""
        os.makedirs(self.plot_dir, exist_ok=True)
        # [수정 - 버그] 저장 파일명(safe_title/default_name) 생성용 폴백은
        # 그대로 두되(빈 파일명은 말이 안 되므로), 실제 그래프 title은
        # plot_title을 그대로 _generate_3d_file에 넘겨서 비웠으면 비운 채로
        # 나가게 한다(아래 self._generate_3d_file(... plot_title ...) 참고).
        raw_title = (plot_title or "").strip() or self.filename_var.get().strip() or "CathPlot"
        safe_title = "".join(c for c in raw_title if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"
        next_id = self.title_counters.get(safe_title, 0) + 1
        default_name = f"{safe_title}_3D_{next_id}"
        file_types = [
            ("PNG Image (*.png)", "*.png"),
            ("Portable Document Format (*.pdf)", "*.pdf"),
            ("JPEG Image (*.jpg)", "*.jpg"),
            ("SVG Vector Graphic (*.svg)", "*.svg"),
            ("Enhanced Metafile (*.emf)", "*.emf"),
            ("Encapsulated PostScript (*.eps)", "*.eps"),
        ]
        selected_path = filedialog.asksaveasfilename(
            initialdir=self.plot_dir, initialfile=default_name,
            title="Save 3D Plot As...", filetypes=file_types, defaultextension=".png")
        if not selected_path:
            return
        self.title_counters[safe_title] = next_id
        ext = os.path.splitext(selected_path)[1].lower().replace(".", "") or "png"
        try:
            self._generate_3d_file(os.path.abspath(selected_path), ext, curves, rot_x, rot_z, style, palette,
                                    colorbox, annotations_3d, arrows_3d, equal_xyz, surfaces,
                                    xlabel3d, ylabel3d, zlabel3d, plot_title, time_min, time_max,
                                    y_min, y_max, z_min, z_max)
        except Exception as e:
            messagebox.showerror("Save Error", f"3D Plot 저장 중 오류가 발생했습니다:\n{e}")
            return
        self.update_plot_file_list()
        messagebox.showinfo("Success", f"Saved: {os.path.basename(selected_path)}")

    def _print_3d_plot(self, curves, rot_x, rot_z, style, palette, colorbox, annotations_3d, arrows_3d,
                        equal_xyz=False, surfaces=None, xlabel3d="", ylabel3d="", zlabel3d="",
                        plot_title="", time_min=None, time_max=None,
                        y_min=None, y_max=None, z_min=None, z_max=None):
        """[추가] "3D Plot도 인쇄 지원" - 2D PRINT와 동일하게 EMF를 만들어
        프린터로 직접 그린다(_print_emf_and_cleanup/_pick_printer_dialog 재사용).
        2D처럼 어떤 plot을 고를지/용지 방향을 다시 묻는 절차는 3D 다이얼로그가
        이미 그 자리에서 설정을 받은 뒤라 생략하고 프린터만 고른다."""
        os.makedirs(self.plot_dir, exist_ok=True)
        idx = 1
        while True:
            temp_emf = os.path.join(self.plot_dir, f"Print_Job_Temp_3D_{idx}.emf")
            if not os.path.exists(temp_emf):
                break
            idx += 1
        try:
            self._generate_3d_file(temp_emf, "emf", curves, rot_x, rot_z, style, palette,
                                    colorbox, annotations_3d, arrows_3d, equal_xyz, surfaces,
                                    xlabel3d, ylabel3d, zlabel3d, plot_title, time_min, time_max,
                                    y_min, y_max, z_min, z_max)
        except Exception as e:
            messagebox.showerror("Print Error", f"인쇄용 파일 생성 중 오류가 발생했습니다:\n{e}")
            return
        if not os.path.exists(temp_emf):
            return
        printer_name = self._pick_printer_dialog()
        if not printer_name:
            try:
                os.remove(temp_emf)
            except OSError:
                pass
            return
        raw_title = (plot_title or "").strip() or self.filename_var.get().strip() or "CathPlot"
        threading.Thread(
            target=self._print_emf_and_cleanup, args=(temp_emf, raw_title, printer_name, "landscape"), daemon=True
        ).start()

    def get_temp_dir(self):
        temp_dir = os.path.join(self.cwd, "temp_sorted")
        os.makedirs(temp_dir, exist_ok=True)
        return temp_dir

    def _get_resort_lock(self, sorted_filepath):
        """resort_dat_file의 "확인 후 없으면 생성" 구간을 파일 경로별로 잠근다
        (Batch 병렬화 대비 - 같은 정렬 캐시 파일을 여러 스레드가 동시에 만드는
        경쟁 방지). 다른 파일끼리는 서로 안 기다리게 lock을 파일마다 나눈다."""
        with self._resort_locks_guard:
            lock = self._resort_locks.get(sorted_filepath)
            if lock is None:
                lock = threading.Lock()
                self._resort_locks[sorted_filepath] = lock
            return lock

    def resort_dat_file(self, dat_file, x_col, dat_info=None):
        """
        Cathena/Generic 여부와 무관하게, 이미 통합되어 있는 CathenaDatParser의
        data_start_line을 그대로 활용해 헤더/데이터 경계를 판단한다.
        지정된 X축(x_col=output_no, 0-based, Time인 0도 포함) 기준으로 정렬된
        _sortedX#.dat 임시 파일을 생성하고 그 경로를 반환한다. (이미 존재하면 재사용)

        [파일 형식]
        1번째 줄: 각 컬럼의 변수명(head title)을 컬럼 순서대로 tab 구분 나열
                  (data_parser가 읽은 display_name 재사용 - Cathena에서 0번 컬럼에
                   이름이 없으면 data_parser가 자동으로 붙인 'Time' 등도 그대로 사용)
        2번째 줄부터: 정렬된 순수 숫자 데이터 (tab 구분, 원본 헤더/주석 줄은 없음)
        이렇게 저장해두면 이 파일을 나중에 다시 쓸 때 변수명을 알기 위해 원본을
        다시 훑어 파싱할 필요 없이 1번째 줄만 읽으면 되어 시간이 절약된다.

        [추가 - 효율] dat_info(선택): 호출부가 이 dat_file을 이미 self.parser.parse()로
        파싱해둔 결과가 있으면 그대로 넘겨서, 아래에서 또 파싱하는 중복을 없앤다
        (예: Batch Queue가 recipe 매칭을 위해 미리 parse()해둔 결과를 재사용 -
        큰 파일을 캐시 미스마다 두 번 파싱/세 번 읽던 낭비를 줄임). 안 넘기면
        기존처럼 여기서 직접 파싱한다(하위 호환).
        """
        if not os.path.exists(dat_file):
            return dat_file

        try:
            if not hasattr(self, 'plot_dir') or not self.plot_dir:
                self.plot_dir = os.path.join(os.path.dirname(os.path.abspath(dat_file)), "plot")

            temp_dir = os.path.join(self.plot_dir, "temp_sorted")
            os.makedirs(temp_dir, exist_ok=True)

            # [수정 - 버그] 파일명(base_name)만으로 임시 정렬 파일 이름을 정해서,
            # 서로 다른 폴더에 있는 "같은 이름"의 dat 파일(예: A/out111.dat와
            # B/out111.dat)을 같은 세션에서 같이 쓰면 temp_sorted 캐시가 서로
            # 덮어써서 경고 없이 잘못된 데이터를 plot에 쓰는 심각한 문제가
            # 있었음("파일명이 같을 때 sorted 파일이 덮어써진다" 실측 확인) -
            # 겹칠 때만(보통은 그대로) "파일명-N_해시6자"로 구분한다. N은
            # update_variable_selection_ui의 LabelFrame 제목에 붙는 "-1,-2"와
            # 정확히 같은 계산(등장 순서)을 재사용해서 화면 목록과 캐시 파일명이
            # 서로 맞아떨어지게 한다. 해시(경로 기준, 항상 결정적)는 N이 로드
            # 순서에 따라 달라져도 실제 데이터 매칭은 항상 정확하도록 보장하는
            # 안전장치 - N만으론 이전 세션의 다른 순서로 생긴 캐시와 헷갈릴 수
            # 있지만, 해시가 다르면 그 캐시를 재사용하지 않고 새로 만든다.
            base_name = os.path.basename(dat_file)
            name_root, ext = os.path.splitext(base_name)
            abs_dat_path = os.path.abspath(dat_file)

            _basename_counts = {}
            for _info in getattr(self, "file_rows", []):
                if _info.get("meta") is None:
                    continue
                _basename_counts[os.path.basename(_info["filename"])] = \
                    _basename_counts.get(os.path.basename(_info["filename"]), 0) + 1

            if _basename_counts.get(base_name, 0) > 1:
                _seen = 0
                _n = None
                for _info in getattr(self, "file_rows", []):
                    if _info.get("meta") is None:
                        continue
                    if os.path.basename(_info["filename"]) != base_name:
                        continue
                    _seen += 1
                    if os.path.abspath(_info["filename"]) == abs_dat_path:
                        _n = _seen
                        break
                path_hash = hashlib.md5(abs_dat_path.encode("utf-8")).hexdigest()[:6]
                sorted_filename = f"{name_root}-{_n if _n else 1}_{path_hash}_sortedX{x_col}{ext}"
            else:
                sorted_filename = f"{name_root}_sortedX{x_col}{ext}"
            sorted_filepath = os.path.join(temp_dir, sorted_filename)

            # [추가 - Batch 병렬화 대비] 같은 sorted_filepath를 동시에 여러
            # 스레드가 만들려고 하면(같은 dat 파일+X축을 쓰는 템플릿이 배치
            # 안에 여러 개일 때) 파일이 깨질 수 있어, 파일 경로별 lock으로
            # "확인 후 없으면 생성"을 원자적으로 만든다.
            with self._get_resort_lock(sorted_filepath):
                # [수정 - 버그] 캐시 존재 여부만 보고 재사용해서, 원본 dat_file이
                # 캐시 생성 이후에 덮어써지면(예: 같은 경로로 시뮬레이션을 다시
                # 돌린 경우) 낡은 정렬 파일을 계속 돌려줘 plot에 옛날 데이터가
                # 조용히 나오는 문제가 있었음 - 원본이 캐시보다 최신이면 무효화
                # 하고 다시 만든다.
                if os.path.exists(sorted_filepath) and os.path.getmtime(sorted_filepath) >= os.path.getmtime(dat_file):
                    return sorted_filepath

                # 파서로 Cathena/Generic 여부와 무관하게 데이터 시작 줄과 변수명을 동일한 방식으로 판단
                # (호출부가 이미 파싱해둔 결과를 넘겼으면 재사용 - 위 dat_info 파라미터 참고)
                if dat_info is None:
                    dat_info = self.parser.parse(dat_file)

                with open(dat_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                data_rows = []
                for line in lines[dat_info.data_start_line:]:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = re.split(r'[,\s]+', stripped)
                    try:
                        vals = [float(p.replace("D", "E").replace("d", "e").replace(",", "")) for p in parts]
                        if len(vals) >= 2:
                            data_rows.append(vals)
                    except ValueError:
                        continue

                if not data_rows:
                    return dat_file

                col_idx = x_col
                max_col_available = len(data_rows[0]) - 1
                if not (0 <= col_idx <= max_col_available):
                    return dat_file

                data_rows.sort(key=lambda r: r[col_idx])

                # 각 컬럼의 head title 목록 구성 (data_parser의 display_name 재사용,
                # 혹시 변수 목록에 없는 컬럼이 있으면 var_# 로 대체)
                var_by_no = {v.output_no: v for v in dat_info.variables}
                n_cols = len(data_rows[0])
                head_titles = [
                    var_by_no[i].display_name if i in var_by_no else f"var_{i}"
                    for i in range(n_cols)
                ]

                with open(sorted_filepath, 'w', encoding='utf-8') as f_out:
                    f_out.write("\t".join(head_titles) + "\n")
                    for r in data_rows:
                        f_out.write("\t".join(map(str, r)) + "\n")

                return sorted_filepath

        except Exception as e:
            self._log_warning(f"[resort_dat_file 실패] {dat_file} (x_col={x_col}): {e}\n{traceback.format_exc()}")
            return dat_file

    def _read_column_values(self, dat_file, col_idx):
        """
        dat_file에서 지정된 컬럼(col_idx, 0-based)의 실수 값 목록을 읽어온다.
        헤더/데이터 경계는 각자 라인을 다시 훑으며 추측하지 않고, 이미 통합되어
        있는 CathenaDatParser의 data_start_line을 그대로 재사용한다
        (resort_dat_file, gnu_generator._nice_axis_range와 동일한 방식).
        """
        values = []
        try:
            dat_info = self.parser.parse(dat_file)
        except Exception:
            return values

        try:
            with open(dat_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except OSError:
            return values

        for line in lines[dat_info.data_start_line:]:
            text = line.strip()
            if not text:
                continue
            parts = re.split(r'[,\s]+', text)
            if len(parts) <= col_idx:
                continue
            try:
                values.append(float(parts[col_idx].replace("D", "E").replace("d", "e").replace(",", "")))
            except ValueError:
                continue

        return values

    def _read_column_with_x(self, dat_file, col_idx, x_idx):
        """dat_file에서 (x_idx, col_idx) 두 컬럼을 같은 행끼리 짝지어 (x값, y값)
        쌍의 목록으로 읽어온다. min/max가 실제로 어느 X값에서 발생했는지
        알아내기 위한 용도 (변수 툴팁에서 사용)."""
        pairs = []
        try:
            dat_info = self.parser.parse(dat_file)
        except Exception:
            return pairs

        try:
            with open(dat_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except OSError:
            return pairs

        max_col = max(col_idx, x_idx)
        for line in lines[dat_info.data_start_line:]:
            text = line.strip()
            if not text:
                continue
            parts = re.split(r'[,\s]+', text)
            if len(parts) <= max_col:
                continue
            try:
                y_val = float(parts[col_idx].replace("D", "E").replace("d", "e").replace(",", ""))
                x_val = float(parts[x_idx].replace("D", "E").replace("d", "e").replace(",", ""))
            except ValueError:
                continue
            pairs.append((x_val, y_val))

        return pairs

    def _bind_var_tooltip(self, widgets, file_info, output_no):
        """widgets(하나 또는 여러 개 - 보통 No.라벨과 변수명 입력칸) 위에 마우스를
        올리면 그 변수의 min/max와, 각각이 발생한 X값을 'min=A@X1, max=B@X2'
        형태로 보여준다 (X변수는 그 파일의 현재 X변수, 지정 안 했으면 Time=0번
        기준). X변수로 지정된 변수 자신이면 군더더기 없이 'min=.. max=..'만
        보여준다. X 선택은 나중에 바뀔 수 있으므로 호버할 때마다 다시 확인한다.
        계산 결과 자체는 (dat_file, output_no, x_output_no)별로 캐시해서 반복
        호버 시 매번 파일을 다시 읽지 않는다.
        [수정] widgets 여러 개를 하나의 그룹으로 취급해서 툴팁 상태를 공유하고,
        Leave 시 바로 지우지 않고 잠깐 뒤 마우스가 정말로 그룹 밖으로 나갔는지
        확인한다 - 인접한 위젯(예: No.라벨 → Entry) 사이를 오갈 때 깜빡이거나
        지워지지 않고 잔상처럼 남는 문제를 방지하기 위함."""
        widget_list = list(widgets) if isinstance(widgets, (list, tuple)) else [widgets]
        anchor = widget_list[0]

        if not hasattr(self, "_var_minmax_cache"):
            self._var_minmax_cache = {}

        dat_file = file_info.get("filename")
        state = {"win": None}

        def current_x_output_no():
            x_val = file_info["x_var"].get()
            if x_val and "||" in x_val:
                try:
                    return int(x_val.split("||")[1])
                except (ValueError, IndexError):
                    pass
            return 0  # X를 따로 지정 안 했으면 Time(0번) 기준

        def compute_min_max_at_x(col, x_idx):
            cache_key = (dat_file, col, x_idx)
            if cache_key not in self._var_minmax_cache:
                pairs = self._read_column_with_x(dat_file, col, x_idx)
                if pairs:
                    min_pair = min(pairs, key=lambda p: p[1])
                    max_pair = max(pairs, key=lambda p: p[1])
                    self._var_minmax_cache[cache_key] = (min_pair, max_pair)
                else:
                    self._var_minmax_cache[cache_key] = None
            return self._var_minmax_cache[cache_key]

        def is_pointer_in_group():
            try:
                x, y = anchor.winfo_pointerxy()
                under = anchor.winfo_containing(x, y)
            except Exception:
                return False
            return under in widget_list

        def on_enter(event):
            if state["win"] is not None:
                return  # 이미 떠 있으면(인접 위젯으로 옮겨간 경우) 새로 안 만듦
            x_no = current_x_output_no()
            result = compute_min_max_at_x(output_no, x_no)
            if result is None:
                text = "(데이터 없음)"
            else:
                (min_x, min_y), (max_x, max_y) = result
                if output_no == x_no:
                    text = f"min={min_y:.6g}  max={max_y:.6g}"
                else:
                    text = f"min={min_y:.6g}@{min_x:.6g}, max={max_y:.6g}@{max_x:.6g}"
            tw = tk.Toplevel(anchor)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 8}")
            tk.Label(
                tw, text=text, background="#ffffe0", relief="solid", borderwidth=1,
                font=("Consolas", 9), padx=4, pady=1
            ).pack()
            state["win"] = tw

        def on_leave(event):
            def _check():
                if not is_pointer_in_group() and state["win"] is not None:
                    state["win"].destroy()
                    state["win"] = None
            anchor.after(30, _check)

        for w in widget_list:
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

    FALLBACK_FONT = "Arial"  # 지정된 폰트가 시스템에 없을 때 대체할 폰트(Windows에 기본 내장)
    # [수정] "일본 문자처럼 깨져 보인다"는 피드백 확인 결과, 실제로는 코드에
    # 일본어 텍스트가 있던 게 아니라 이 대화 창(화면)에서 내가 설명한 내용에
    # 관한 얘기였음("코드 문제가 아니고 화면에 구상한 이야기") - 즉 대체
    # 로직 자체는 문제가 아니었고, 사용자도 "Arial 등으로 대체하는 방식은
    # 괜찮다, 한글은 고딕/바탕체 등으로"라고 확인해줌. 다만 원래 FALLBACK_FONT를
    # 무조건 Arial로만 쓰면 Arial엔 한글 글리프가 없어 한글 라벨이 깨지므로,
    # 대체 대상 텍스트에 한글이 섞여 있으면 한글 지원 폰트(맑은 고딕/굴림/바탕
    # 등)를 우선 후보로 시도한다.
    _HANGUL_RE = re.compile(r"[가-힣ㄱ-ㆎ]")
    _KOREAN_FALLBACK_CANDIDATES = ["맑은 고딕", "Malgun Gothic", "굴림", "Gulim", "바탕", "Batang", "돋움", "Dotum"]
    # [수정 - 버그] "프린트/저장할 때마다 맑은 고딕 폰트가 없다고 나옴" - 실측
    # 확인: 한글 Windows에서는 tkinter font.families()가 이 폰트를 영문 이름
    # "Malgun Gothic"이 아니라 한글 이름("맑은 고딕")으로만 돌려줌(실제로는
    # 당연히 설치돼 있고, gnuplot 자체도 "Malgun Gothic"으로 문제없이 찾아서
    # 그려짐 - 별도 gnuplot 직접 렌더링 테스트로 확인). 그런데 아래
    # _check_and_fix_fonts는 plotdef에 박혀 있는 영문 이름 그대로만 설치
    # 목록에서 찾아서, 매번 "못 찾음"으로 오판하고 (결과적으로 똑같은 폰트인)
    # "맑은 고딕"으로 "대체"했다는 경고를 헛되이 띄우고 있었음. 영문/한글 이름이
    # 같은 폰트의 다른 표기일 뿐인 경우를 서로 동의어로 인식하게 한다.
    _FONT_NAME_ALIASES = {
        "malgun gothic": ["맑은 고딕"],
        "gulim": ["굴림"],
        "batang": ["바탕"],
        "dotum": ["돋움"],
    }

    def _font_is_installed(self, name, installed):
        """installed(소문자 폰트 이름 집합)에 name이 있는지, 영문/한글 이름이
        서로 다른 별칭(_FONT_NAME_ALIASES)인 경우까지 포함해서 확인한다."""
        n = (name or "").strip().lower()
        if not n:
            return True
        if n in installed:
            return True
        return any(alias.lower() in installed for alias in self._FONT_NAME_ALIASES.get(n, []))

    def _pick_fallback_font(self, installed, sample_text):
        """installed(설치된 폰트 이름 소문자 집합)에서 sample_text 표시에 쓸
        대체 폰트를 고른다. sample_text에 한글이 있으면 한글 지원 폰트 후보를
        먼저 찾고, 못 찾으면(설치 목록 조회가 신뢰 못 할 수도 있으므로) 그래도
        가장 흔한 한글 폰트(맑은 고딕)를 기본값으로 쓴다. 한글이 없으면 Arial."""
        if self._HANGUL_RE.search(sample_text or ""):
            for cand in self._KOREAN_FALLBACK_CANDIDATES:
                if cand.lower() in installed:
                    return cand
            return self._KOREAN_FALLBACK_CANDIDATES[0]
        return self.FALLBACK_FONT

    def _get_installed_font_names(self):
        """설치된 폰트 이름 집합을 반환한다(세션 중 최초 1회만 조회해서 캐싱).
        tkinter가 이미 OS 폰트 시스템(Windows GDI 포함)에 접근하고 있으므로
        별도 win32 API 호출 없이 tkinter.font.families()로 조회한다. 조회
        자체가 실패하면(예: 디스플레이 없는 환경) None을 반환해서 호출부가
        검사를 통째로 건너뛰게 한다."""
        if getattr(self, "_installed_font_cache", None) is not None:
            return self._installed_font_cache
        try:
            names = {f.strip().lower() for f in tkfont.families(self.root)}
        except Exception:
            names = None
        self._installed_font_cache = names
        return names

    def _check_and_fix_fonts(self, plotdef):
        """plotdef에 지정된 폰트(Title/X/Y/Y2 label, Legend)가 실제로 설치돼
        있는지 확인해서, 없는 폰트는 대체 폰트(한글 텍스트면 한글 지원 폰트,
        아니면 Arial)로 바꾼 복사본과 경고 메시지 목록을 함께 반환한다."""
        installed = self._get_installed_font_names()
        if not installed:
            return plotdef, []

        import dataclasses
        legend_sample = " ".join((c.title or "") for c in getattr(plotdef, "curves", []) or [])
        font_fields = [
            ("title_font", "Title", getattr(plotdef, "title", "")),
            ("xlabel_font", "X Label", getattr(plotdef, "xlabel", "")),
            ("ylabel_font", "Y Label", getattr(plotdef, "ylabel", "")),
            ("y2label_font", "Y2 Label", getattr(plotdef, "y2label", "")),
            ("legend_font", "Legend", legend_sample),
        ]
        changes = {}
        warnings = []
        reported = set()
        for field, label, sample_text in font_fields:
            name = (getattr(plotdef, field, "") or "").strip()
            if name and not self._font_is_installed(name, installed):
                fallback = self._pick_fallback_font(installed, sample_text)
                changes[field] = fallback
                key = (name, field)
                if key not in reported:
                    warnings.append(f"'{name}' 폰트를 찾을 수 없어 '{fallback}'(으)로 대체했습니다. ({label})")
                    reported.add(key)

        if changes:
            plotdef = dataclasses.replace(plotdef, **changes)
        # [수정] "screen(Interactive)에는 폰트 대체 메시지가 불필요하다"는 요청 -
        # 대체 자체(changes)는 화면에서도 그대로 적용하되(그래야 화면도 정상
        # 렌더링됨), 경고 팝업은 Print/Save(is_print_mode)일 때만 보여준다.
        if not getattr(plotdef, "is_print_mode", True):
            return plotdef, []
        return plotdef, warnings

    def _log_batch_warnings(self, warnings, log_name="batch_warnings.log"):
        """Batch(Queue/Set) 실행 중 모인 경고 메시지를(파일명 prefix 포함) 로그
        파일에 남긴다. 반환값은 로그 파일 경로(기록 실패 시 None)."""
        if not warnings:
            return None
        log_path = os.path.join(self.plot_dir, log_name)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                for w in warnings:
                    f.write(w + "\n")
            return log_path
        except OSError:
            return None

    def _find_window_rect(self, title, timeout_sec=2.0):
        """title로 창을 찾아 (hwnd, (left,top,right,bottom))을 반환. 못 찾으면
        (None, None). Windows 전용(ctypes) - 다른 OS/실패 시 조용히 None."""
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return None, None
        try:
            user32 = ctypes.windll.user32
        except AttributeError:
            return None, None
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                rect = wintypes.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return hwnd, (rect.left, rect.top, rect.right, rect.bottom)
                return hwnd, None
            time.sleep(0.1)
        return None, None

    def _raise_window_no_activate(self, hwnd):
        """[추가 - 요청] "Animation 창이 CathPlot 뒤로 숨어버림, Ani 컨트롤
        패널과 겹치지 않게 맨 위로" - gnuplot plot 창을 새로 띄운 뒤
        CathPlot 쪽에서 Animation Control 패널(Toplevel)을 새로 만들면,
        Windows가 "새로 만들어진 창"인 Toplevel(그리고 그 소유 프로세스인
        CathPlot 메인 창까지)을 앞으로 올려버려서, 정작 진행 상황을
        보여주는 gnuplot plot 창이 CathPlot 메인 창 뒤에 가려지는 문제가
        있었음 - Control 패널을 띄우기 "직전"에 plot 창을 Z-order상 맨
        위로 올려두면(SWP_NOACTIVATE로 키보드 포커스는 건드리지 않음 -
        마우스 포커스가 계속 CathPlot 쪽에 남도록), 그 직후 만들어지는
        Control 패널이 다시 맨 위로 올라가면서 자연스럽게 "Control 패널이
        맨 위, plot 창이 바로 그 아래"가 된다."""
        if not hwnd:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # HWND_TOP(0), SWP_NOMOVE(0x0002)|SWP_NOSIZE(0x0001)|SWP_NOACTIVATE(0x0010)
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010)
        except Exception:
            pass

    def _move_window_no_activate(self, hwnd, x, y):
        """[추가 - 요청] "Ani 창은 좌상단에 작게, plot 창은 화면 중앙에" -
        gnuplot plot 창을 (x,y)로 옮긴다(크기는 그대로 - SWP_NOSIZE).
        포커스는 안 뺏는다(SWP_NOACTIVATE)."""
        if not hwnd:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # SWP_NOSIZE(0x0001)|SWP_NOACTIVATE(0x0010)|SWP_NOZORDER(0x0004)
            user32.SetWindowPos(hwnd, 0, int(x), int(y), 0, 0, 0x0001 | 0x0010 | 0x0004)
        except Exception:
            pass

    def _write_anim_ctrl(self, ctrl_path, paused, frame_pause, click_seq, exit_flag=0):
        """[추가 - space bar 재설계] 실행 중인 애니메이션(gnuplot)에 값을
        전달하는 작은 제어 파일을 다시 쓴다. gnuplot이 파일을 읽는 도중에
        걸려 절반만 써진 내용을 읽지 않도록, 임시 파일에 먼저 쓰고
        os.replace로 원자적으로 교체한다(같은 드라이브 안에서는 Windows도
        원자적 교체가 보장됨).
        [추가 - 요청] "progress 100% 이후 Resume 누르면 처음부터 다시
        시작하게" - click_seq는 버튼을 누를 때마다 1씩 증가하는 값으로,
        gnuplot 쪽은 "애니메이션이 다 끝난 시점의 click_seq"보다 큰 값을
        보면(=그 뒤로 버튼이 한 번 더 눌렸다는 뜻) 처음부터 다시 재생한다."""
        try:
            tmp_path = ctrl_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(
                    f"paused_anim = {1 if paused else 0}\n"
                    f"exit_anim = {1 if exit_flag else 0}\n"
                    f"frame_pause_anim = {frame_pause:.6f}\n"
                    f"click_seq = {int(click_seq)}\n"
                )
            os.replace(tmp_path, ctrl_path)
        except OSError:
            pass

    def _open_animation_control_panel(self, ctrl_path, initial_frame_pause, status_path=None, proc=None, plot_window_title=None):
        """[추가 - 근본 원인 재설계] "Animation 창에서 space bar가 안 먹힘" -
        이전엔 gnuplot 자체의 키보드 bind(Space=일시정지, +/-=속도, Q=종료)에
        의존했는데, 실측(화면에 키 입력 감지 횟수를 표시해 직접 확인)으로
        gnuplot 창이 실제로 키보드 포커스를 못 받는 것이 확정됨 - Windows가
        배경(콘솔 숨김) 프로세스가 다른 창에 SetForegroundWindow로 포커스를
        강제로 넘기는 것을 보안상 막고 있어서(포커스 스틸링 방지), 키 입력이
        항상 CathPlot(Tk) 창으로 가버리고 gnuplot의 bind는 영영 안 걸림.
        이건 우리 코드로 못 뚫는 OS 제약이라 "gnuplot 창이 포커스를 가진다"는
        전제 자체를 버리고, 항상 포커스/클릭이 오는 CathPlot 쪽에 이 작은
        컨트롤 창을 띄운다 - 버튼을 누르면 gnu_generator.create_animation_
        script가 만들어둔 제어 파일(ctrl_path)에 값을 써주고, 실행 중인
        gnuplot이 매 프레임 그 파일을 load해서 반영한다(키보드 포커스와
        완전히 무관 - 실측으로 pause/exit 둘 다 정상 동작 확인됨).
        [수정 - 코드 리뷰로 발견, proc 매개변수 추가] 이전엔 이 패널이 실제
        gnuplot 프로세스를 전혀 몰라서 (1) Exit을 눌러도 제어 파일에 신호만
        쓰고 창은 그대로 남아있었고(gnuplot이 스스로 확인하고 끝내주길
        기다릴 뿐 - "pause mouse close"로 넘어가 계속 떠 있음), (2) 사용자가
        창을 직접 닫거나 gnuplot이 죽어도 패널은 그걸 알 방법이 없어 버튼을
        눌러도 계속 조용히 실패하는 파일 쓰기만 반복했음 - 이제 Popen
        핸들을 받아 둘 다 고친다."""
        state = {"paused": False, "frame_pause": initial_frame_pause, "seq": 0, "finished": False, "dead": False}

        def _bump():
            # [추가 - 요청] 버튼을 누를 때마다 1씩 증가 - gnuplot이 "끝난
            # 시점 이후로 버튼이 한 번 더 눌렸는지"를 이 값으로 감지해서
            # Progress 100% 뒤에 Resume을 누르면 처음부터 재생하게 한다.
            state["seq"] += 1
            return state["seq"]

        panel = tk.Toplevel(self.root)
        panel.title("Animation Control")
        panel.resizable(False, False)
        # [수정 - 버그, 요청] "Ani 창은 좌상단에 작게, plot 창은 화면 중앙에" -
        # plot 창이 어디서 열릴지(OS가 정함)에 맞춰 패널 위치를 계산하던
        # 이전 방식 대신, 더 예측 가능하게 패널은 항상 화면 좌상단 구석에
        # 작게 고정하고, plot 창 쪽을 화면 중앙으로 옮긴다 - 둘 다 서로
        # 절대 겹치지 않고 위치도 매번 같아서 찾기 쉬움. 열려 있는 패널이
        # 여러 개면 좌상단에서 살짝씩 어긋나게 띄운다.
        _n_open = getattr(self, "_anim_panel_open_count", 0)
        self._anim_panel_open_count = _n_open + 1
        try:
            panel.geometry(f"+{20 + 24 * _n_open}+{20 + 24 * _n_open}")
        except Exception:
            pass

        # plot 창을 제목으로 찾아 화면 중앙으로 옮기고, Z-order도 맨 위로
        # 올려둔다(포커스는 안 뺏음 - SWP_NOACTIVATE) - 패널 자신도 새로
        # 만들어지며 다시 맨 위로 올라가므로, 결과적으로 "패널이 맨 위,
        # plot 창이 그 바로 아래, 화면 중앙"이 되어 CathPlot 메인 창에
        # 가려지지 않는다.
        # [수정 - 지적] "Animate plot을 여러 개 열면 전부 정확히 같은
        # 중앙 좌표라 서로 완전히 겹쳐서 몇 개가 떠 있는지 구분이 안 됨" -
        # 패널과 같은 개수(_n_open) 기준으로 중앙 위치도 대각선으로 조금씩
        # 어긋나게 한다(패널과 같은 간격으로 같이 움직여서, 몇 번째로 연
        # animate든 "패널 바로 아래에 그 plot"이라는 대응 관계는 유지됨).
        _plot_hwnd, _plot_rect = (None, None)
        if plot_window_title:
            _plot_hwnd, _plot_rect = self._find_window_rect(plot_window_title, timeout_sec=1.5)
        if _plot_hwnd and _plot_rect:
            try:
                _w = _plot_rect[2] - _plot_rect[0]
                _h = _plot_rect[3] - _plot_rect[1]
                _cx = max((panel.winfo_screenwidth() - _w) // 2, 0) + 24 * _n_open
                _cy = max((panel.winfo_screenheight() - _h) // 2, 0) + 24 * _n_open
                self._move_window_no_activate(_plot_hwnd, _cx, _cy)
            except Exception:
                pass
        if _plot_hwnd:
            self._raise_window_no_activate(_plot_hwnd)

        def _on_panel_destroy():
            self._anim_panel_open_count = max(getattr(self, "_anim_panel_open_count", 1) - 1, 0)
        panel.bind("<Destroy>", lambda e: _on_panel_destroy() if e.widget is panel else None)

        status_label = ttk.Label(panel, text="애니메이션 실행 중 - 아래 버튼으로 직접 제어",
                                  font=("Malgun Gothic", 9))
        status_label.pack(padx=12, pady=(10, 6))

        btn_row = ttk.Frame(panel)
        btn_row.pack(padx=12, pady=2)

        pause_btn = tk.Button(btn_row, text="Pause", width=9, font=("Malgun Gothic", 9, "bold"))

        def toggle_pause():
            if state["finished"]:
                # [추가 - 요청] "재생이 끝나면 Pause가 아니라 Resume 버튼이
                # 나오게" - 다 끝난 뒤에는 이 버튼이 "일시정지 토글"이 아니라
                # "처음부터 다시 재생"이어야 하므로 paused를 뒤집지 않고,
                # 항상 재생 상태(paused=False)로 click_seq만 올려서 gnuplot
                # 쪽 재시작 대기 루프를 깨운다(gnu_generator.py의 while(1)
                # 재시작 로직 참고).
                state["finished"] = False
                state["paused"] = False
                pause_btn.config(text="Pause")
                self._write_anim_ctrl(ctrl_path, False, state["frame_pause"], _bump())
                return
            state["paused"] = not state["paused"]
            pause_btn.config(text="Resume" if state["paused"] else "Pause")
            self._write_anim_ctrl(ctrl_path, state["paused"], state["frame_pause"], _bump())

        pause_btn.config(command=toggle_pause)
        pause_btn.pack(side="left", padx=3)

        # [추가 - 요청] gnuplot은 do-for 루프가 자연스럽게(Exit이 아니라) 다
        # 끝나면 별도 "상태" 파일(status_path)에 "finished=<그 시점의
        # click_seq>"를 적어둔다(gnu_generator.create_animation_script 참고) -
        # 이 값이 지금 GUI가 마지막으로 보낸 seq와 같으면 "방금 막 다
        # 끝났다"는 뜻이므로, 버튼 표시를 Resume으로 바꿔서 다시 누르면
        # 재생이 아니라 재시작이라는 걸 알려준다. 주기적으로(0.3초) 파일을
        # 다시 읽어 확인한다(패널이 닫히면 스스로 멈춤).
        def _poll_finished():
            if not panel.winfo_exists():
                return
            # [추가 - 코드 리뷰로 발견] 패널이 실행 중인 gnuplot 프로세스의
            # 생사를 전혀 몰라서, 사용자가 plot 창을 직접 닫거나 gnuplot이
            # 죽어도 버튼들이 계속 살아있는 것처럼 보이며 조용히 파일 쓰기만
            # 반복했음 - 매 폴링마다 프로세스 생존 여부도 같이 확인해서,
            # 죽었으면 버튼을 비활성화하고 안내 문구로 바꾼 뒤 폴링을 멈춘다.
            if proc is not None and proc.poll() is not None and not state["dead"]:
                state["dead"] = True
                status_label.config(text="애니메이션 창이 닫혔거나 gnuplot이 종료됨 - 이 패널도 닫아주세요")
                for _btn in (pause_btn, slower_btn, faster_btn):
                    _btn.config(state="disabled")
                return
            if status_path and not state["finished"]:
                try:
                    with open(status_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if content.startswith("finished="):
                        fin_seq = int(content.split("=", 1)[1])
                        if fin_seq == state["seq"]:
                            state["finished"] = True
                            pause_btn.config(text="Resume")
                except (OSError, ValueError):
                    pass
            panel.after(300, _poll_finished)

        panel.after(300, _poll_finished)

        def _clear_finished_if_needed():
            # [추가 - 요청] Resume/Pause 버튼이 아니라 Slower/Faster로도
            # click_seq가 올라가 재생이 재시작될 수 있으므로(gnuplot은 어느
            # 버튼이든 seq만 오르면 재시작함), 그 경우에도 "Resume" 표시가
            # 그대로 남아 실제로는 재생 중인데 버튼만 안 맞는 상태가 되는
            # 것을 막는다.
            if state["finished"]:
                state["finished"] = False
                pause_btn.config(text="Pause")

        def speed_down():
            _clear_finished_if_needed()
            # [수정 - 버그, 코드 리뷰로 발견] speed_up은 0.001초로 하한이
            # 있는데 speed_down은 상한이 없어서, 계속 누르면 프레임당
            # 대기시간이 몇 시간 단위로 불어날 수 있었음 - gnuplot 쪽
            # "pause frame_pause_anim"은 그 프레임 동안은 끊어서 다시 읽지
            # 않는 한 번의 대기라서, 한 번 이렇게 커지면 그 시간이 다 지날
            # 때까지 Faster를 눌러도 반응이 없어 사실상 멈춘 것처럼 보임 -
            # 상한(5초/프레임 - 이 정도면 충분히 느리게 볼 수 있음)을 둔다.
            state["frame_pause"] = min(state["frame_pause"] * 2.0, 5.0)
            self._write_anim_ctrl(ctrl_path, state["paused"], state["frame_pause"], _bump())

        def speed_up():
            _clear_finished_if_needed()
            state["frame_pause"] = max(state["frame_pause"] * 0.5, 0.001)
            self._write_anim_ctrl(ctrl_path, state["paused"], state["frame_pause"], _bump())

        slower_btn = tk.Button(btn_row, text="- Slower", width=9, command=speed_down)
        slower_btn.pack(side="left", padx=3)
        faster_btn = tk.Button(btn_row, text="+ Faster", width=9, command=speed_up)
        faster_btn.pack(side="left", padx=3)

        def do_exit():
            # [수정 - 버그, 코드 리뷰로 발견] "즉시 종료함(창이 닫힘)"이라고
            # 설명서에 적혀 있는데 실제로는 exit_flag만 파일에 써서
            # gnuplot이 스스로 루프를 빠져나가 "pause mouse close"로
            # 넘어갈 뿐, 창은 계속 떠 있었음 - 제어 파일 신호는 그대로
            # 남겨두되(혹시 gnuplot이 마침 그 시점을 확인 중이면 깔끔하게
            # 빠져나가도록), 프로세스를 직접 종료해 실제로 창이 닫히게 한다.
            self._write_anim_ctrl(ctrl_path, False, state["frame_pause"], _bump(), exit_flag=1)
            if proc is not None:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                except Exception:
                    pass
            panel.destroy()

        pal = self.PALETTE
        tk.Button(
            panel, text="Exit Animation", width=16, font=("Malgun Gothic", 9, "bold"),
            bg=pal.get("danger", "#c0392b"), fg="white",
            activebackground=pal.get("danger_dark", "#962d22"), activeforeground="white",
            command=do_exit,
        ).pack(pady=(6, 10))

        # 패널을 그냥 닫아도(X) gnuplot 애니메이션 자체는 원래 진행 시간대로
        # 계속 돌아가게 둔다(패널=제어 편의 도구일 뿐, 닫는다고 애니메이션이
        # 강제 종료되면 오히려 불편함) - 기본 동작 그대로 두고 별도 처리 없음.

    def execute_plot_pipeline(self, mode="Interactive", custom_filepath=None, custom_format=None):
        # 연타(더블클릭)로 인해 gnuplot 창이 동시에 여러 개 뜨는 것을 방지하기 위한 디바운스 가드
        import time
        now = time.monotonic()
        last = getattr(self, "_last_plot_time", 0)
        if now - last < 0.7:
            return
        self._last_plot_time = now

        try:
            # 활성화된 Y1, Y2 키 목록 가져오기
            #active_y1_keys = [k for k, var in self.y1_vars.items() if var.get()]
            #active_y2_keys = [k for k, var in self.y2_vars.items() if var.get()]
            active_y1_keys = [k for k, var in self.selected_y1_vars.items() if var.get()]
            active_y2_keys = [k for k, var in self.selected_y2_vars.items() if var.get()]

            if not active_y1_keys and not active_y2_keys:
                messagebox.showwarning("Warning", "Please select at least one Y variable to plot.")
                return

            curves = []
            temp_curves_info = []

            for key in active_y1_keys:
                d_file, out_no = key.split("||")
                temp_curves_info.append((d_file, int(out_no), self.legend_vars[key].get(), "y1", key))

            for key in active_y2_keys:
                d_file, out_no = key.split("||")
                temp_curves_info.append((d_file, int(out_no), self.legend_vars[key].get(), "y2", key))

            # 1. 각 파일별 선택된 X축을 확인하고 temp_sorted 폴더에 정렬 파일 생성
            for d_file, out_no, title, axis, key in temp_curves_info:
                file_x_output_no = 0  # 기본값: 0 (선택되지 않았거나 첫 번째 컬럼 가정)

                if hasattr(self, 'file_rows'):
                    for info in self.file_rows:
                        if info.get("filename") == d_file:
                            x_var_obj = info.get("x_var")
                            if x_var_obj and hasattr(x_var_obj, 'get'):
                                x_key_val = x_var_obj.get()
                                if x_key_val and "||" in x_key_val:
                                    _, x_out_no_str = x_key_val.split("||")
                                    try:
                                        file_x_output_no = int(x_out_no_str)
                                    except (ValueError, AttributeError):
                                        file_x_output_no = 0
                            break

                target_dat_file = d_file
                try:
                    target_dat_file = self.resort_dat_file(d_file, file_x_output_no)
                except Exception:
                    target_dat_file = d_file

                _marker_shape, _marker_size, _marker_max_count = self._get_marker_fields(key)
                curves.append(CurveDefinition(
                    dat_file=target_dat_file,
                    output_no=out_no,
                    title=title,
                    axis=axis,
                    x_shift=float(self.file_xshift_vars[d_file].get() or 0.0) if d_file in self.file_xshift_vars else 0.0,
                    color=COLOR_MAP.get(self.color_vars[key].get(), None),
                    linestyle=STYLE_MAP.get(self.linestyle_vars[key].get(), None),
                    linewidth=float(self.linewidth_vars[key].get() if key in self.linewidth_vars else 1.5),
                    x_output_no=file_x_output_no,   # ← 추가: 파일별로 선택된 X변수 컬럼을 곡선에도 전달
                    legend_group=int(self.legend_group_vars[key].get()) if key in self.legend_group_vars else 1,
                    in_legend1=self.in_legend1_vars[key].get() if key in self.in_legend1_vars else True,
                    marker_shape=_marker_shape, marker_size=_marker_size, marker_max_count=_marker_max_count,
                ))

            # 2. Auto Range 미리보기 값을 Min/Max 입력창에 표시 - 실제 렌더링(플롯
            # 생성)에 쓰는 것과 완전히 같은 계산 함수(_nice_axis_range)를 그대로
            # 재사용한다. [수정] 예전엔 여기서 별도로(중복) 5% 뺄셈 계산을 하고
            # 있었는데, nice-rounding도 없고 log scale도 전혀 고려 안 해서 화면에
            # 보이는 값과 실제 그려지는 축 범위가 서로 다르게 나오는 문제가 있었다.
            _range_generator = GnuplotGenerator(self.plot_dir)
            _range_pd = PlotDefinition(curves=curves)

            if self.xauto_var.get():
                nice_x = _range_generator._nice_axis_range(_range_pd, "x", is_log=self.xlog_var.get())
                if nice_x:
                    xmin, xmax, _ = nice_x
                    self.xmin_var.set(str(xmin))
                    self.xmax_var.set(str(xmax))

            if self.yauto_var.get():
                nice_y1 = _range_generator._nice_axis_range(_range_pd, "y1", is_log=self.y1log_var.get())
                if nice_y1:
                    ymin, ymax, _ = nice_y1
                    self.ymin_var.set(str(ymin))
                    self.ymax_var.set(str(ymax))

            if self.y2auto_var.get():
                nice_y2 = _range_generator._nice_axis_range(_range_pd, "y2", is_log=self.y2log_var.get())
                if nice_y2:
                    y2min, y2max, _ = nice_y2
                    self.y2min_var.set(str(y2min))
                    self.y2max_var.set(str(y2max))

            # 3. 출력 대상/포맷 및 출력 파일 경로 결정 (execute_multi_plot_pipeline과 동일한 방식)
            os.makedirs(self.plot_dir, exist_ok=True)
            target = "screen" if mode == "Interactive" else "file"
            fmt = (custom_format or "png").lower() if target == "file" else "interactive"

            raw_title = self.filename_var.get().strip() or "CathPlot"
            safe_title = "".join(c for c in raw_title if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"

            if custom_filepath:
                outfile = custom_filepath
            else:
                next_id = self.title_counters.get(safe_title, 0) + 1
                base_name = f"{safe_title}_{next_id}"
                outfile = os.path.join(
                    self.plot_dir,
                    f"{base_name}.plt" if target == "screen" else f"{base_name}.{fmt}"
                )
                # [수정] title_counters는 메모리에만 있어서 프로그램을 재시작하면
                # 1번부터 다시 세는데, 폴더에 이전 세션(또는 이전 실행)이 만든 같은
                # 이름 파일이 남아있으면 조용히 처리하지 않고 사용자에게 물어본다
                if os.path.exists(outfile):
                    choice = self._ask_file_conflict(os.path.basename(outfile))
                    if choice == "cancel":
                        return
                    elif choice == "add":
                        while os.path.exists(outfile):
                            next_id += 1
                            base_name = f"{safe_title}_{next_id}"
                            outfile = os.path.join(
                                self.plot_dir,
                                f"{base_name}.plt" if target == "screen" else f"{base_name}.{fmt}"
                            )
                    # choice == "overwrite"면 outfile 그대로 사용 (덮어쓰기)
                self.title_counters[safe_title] = next_id

            # 4. 플롯 정의 객체 생성
            # Axis Frame Auto가 켜진 채로 파일 출력(Save/Print/Batch)하는 경우, 포맷마다
            # 서로 다른 임의의 기본값을 쓰는 대신 항상 기준 10x8cm(frame_width/height
            # 입력칸 기본값과 동일)로 일관되게 계산한다 - _compute_auto_frame_size_cm
            # 참고. [주의] 이건 Multi-plot의 1/p Auto(A4 용지 - 절대 여백, 페이지를
            # 최대한 채움)와는 의도적으로 다른 기준이다 - 1-plot/Batch는 "한 장의
            # 적당한 크기 이미지"가 목적이고, Multi-plot Auto는 "용지를 채우는 인쇄물"이
            # 목적이라 서로 다른 크기 기준을 쓴다. 화면에 그냥 띄우는 Interactive는
            # 해당 없음(용지 개념이 없으므로 그대로 둠).
            if self.frame_auto_var.get() and mode != "Interactive":
                _resolved_frame_auto = False
                _resolved_frame_width, _resolved_frame_height = self._compute_auto_frame_size_cm(for_print=(mode != "Save"))
                _resolved_frame_unit = "cm"
            else:
                _resolved_frame_auto = self.frame_auto_var.get()
                _resolved_frame_width = self.frame_width_var.get()
                _resolved_frame_height = self.frame_height_var.get()
                _resolved_frame_unit = self.frame_unit_var.get()

            plotdef = PlotDefinition(
                title=self.title_var.get(),
                xlabel=self.xlabel_var.get(),
                ylabel=self.ylabel_var.get(),
                y2label=self.y2label_var.get(),
                output_format=mode,
                xauto=self.xauto_var.get(),
                xlog=self.xlog_var.get(), y1log=self.y1log_var.get(), y2log=self.y2log_var.get(),
                xfmt=self.xfmt_var.get(), y1fmt=self.y1fmt_var.get(), y2fmt=self.y2fmt_var.get(),
                yauto=self.yauto_var.get(),
                y2auto=self.y2auto_var.get(),
                xmin=self.xmin_var.get(),
                xmax=self.xmax_var.get(),
                ymin=self.ymin_var.get(),
                ymax=self.ymax_var.get(),
                y2min=self.y2min_var.get(),
                y2max=self.y2max_var.get(),
                xtics=self.xtics_var.get(),
                ytics=self.ytics_var.get(),
                y2tics=self.y2tics_var.get(),
                mxtics=self.mxtics_var.get(),
                mytics=self.mytics_var.get(),
                my2tics=self.my2tics_var.get(),
                major_grid=self.major_grid_var.get(),
                minor_grid=self.minor_grid_var.get(),
                legend_on=self.legend_on_var.get(),
                legend_box=self.legend_box_var.get(),
                legend_pos=self.legend_pos_var.get(),
                legend_align=self.legend_align_var.get(),
                legend_thick=self.legend_thick_var.get(),
                legend_font=self.legend_font_var.get(), legend_size=self.legend_size_var.get(),
                legend_box_width_pct=self.legend_box_width_pct_var.get(),
                legend_box_height_pct=self.legend_box_height_pct_var.get(),
                legend2_on=self.legend2_on_var.get(),
                legend2_box=self.legend2_box_var.get(),
                legend2_pos=self.legend2_pos_var.get(),
                legend2_align=self.legend2_align_var.get(),
                legend2_thick=self.legend_thick_var.get(),
                legend2_box_width_pct=self.legend2_box_width_pct_var.get(),
                legend2_box_height_pct=self.legend2_box_height_pct_var.get(),
                title_font=self.title_font_var.get(),
                title_size=self.title_size_var.get(),
                xlabel_font=self.xlabel_font_var.get(),
                xlabel_size=self.xlabel_size_var.get(),
                ylabel_font=self.ylabel_font_var.get(),
                ylabel_size=self.ylabel_size_var.get(),
                y2label_font=self.y2label_font_var.get(),
                y2label_size=self.y2label_size_var.get(),
                frame_auto=_resolved_frame_auto,
                frame_width=_resolved_frame_width,
                frame_height=_resolved_frame_height,
                frame_unit=_resolved_frame_unit,
                curves=curves,
                annotations=self._collect_annotations(),
                arrows=self._collect_arrows(),
                circles=self._collect_circles(),
                is_print_mode=(mode == "Batch"),
                extra_gnuplot=self.raw_gnuplot_text.get("1.0", "end-1c"),
            )

            # 5. Gnuplot 스크립트 생성 및 실행 (GnuplotGenerator의 실제 API인 create_script 사용)
            if mode == "Interactive":
                # [수정] 예전엔 새 창을 열기 전에 추적 중이던 이전 interactive 창들을
                # 무조건 강제로 닫았는데, 여러 케이스를 화면에 나란히 띄워 비교하고
                # 싶을 때도 있어서 이제는 그냥 두고 개수만 추적한다. 다만 너무 많이
                # 쌓이면(gnuplot_qt.exe 공유 드라이버 폰트 캐시가 느려지는 문제가
                # 있었으므로) 10개 이상이면 가장 먼저 연 창을 닫을지 물어본다.
                alive = [p for p in getattr(self, "plot_processes", []) if p.poll() is None]
                self.plot_processes = alive
                if len(alive) >= 10:
                    if messagebox.askyesno(
                        "Plot 창 정리",
                        f"현재 열려있는 plot 창이 {len(alive)}개입니다.\n"
                        "너무 많아지면 gnuplot이 느려질 수 있어요.\n"
                        "가장 먼저 연 창을 닫을까요? ('아니오'를 누르면 그대로 두고 계속 엽니다)"
                    ):
                        oldest = alive[0]
                        try:
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(oldest.pid)], capture_output=True, **_no_console_kwargs())
                        except Exception:
                            pass
                        self.plot_processes = alive[1:]

            plotdef, _font_warn = self._check_and_fix_fonts(plotdef)
            generator = GnuplotGenerator(self.plot_dir)
            # [추가 - 요청] "X변수 변화에 따른 Y변수들의 progress를 시각화" -
            # Animate 체크박스가 켜져 있고 화면(Interactive)일 때만 애니메이션
            # 모드로 생성 - 파일 저장(fmt != interactive)에는 의미가 없으므로
            # 그 경우는 체크돼 있어도 무시하고 기존처럼 정적으로 그린다.
            # [추가] "Save GIF" 버튼(execute_save_animation_gif)이 이 함수를
            # custom_format="gif"로 불러서 재사용 - 애니메이션 GIF 파일로 저장.
            if fmt == "gif":
                try:
                    duration_sec = float((self.animate_duration_var.get() or "20").strip())
                except ValueError:
                    duration_sec = 20.0
                _tmp_plt = os.path.join(self.plot_dir, f".cathplot_anim_{uuid.uuid4().hex}.plt")
                generator.create_animation_script(
                    plotdef, _tmp_plt,
                    annotations=plotdef.annotations, arrows=plotdef.arrows,
                    circles=getattr(plotdef, "circles", []), duration_sec=duration_sec, gif_path=outfile,
                )
            elif getattr(self, "animate_var", None) is not None and self.animate_var.get() and fmt == "interactive":
                try:
                    duration_sec = float((self.animate_duration_var.get() or "20").strip())
                except ValueError:
                    duration_sec = 20.0
                generator.create_animation_script(
                    plotdef, outfile,
                    annotations=plotdef.annotations, arrows=plotdef.arrows,
                    circles=getattr(plotdef, "circles", []), duration_sec=duration_sec,
                )
            else:
                generator.create_script(
                    plotdef, outfile, fmt=fmt,
                    annotations=plotdef.annotations, arrows=plotdef.arrows,
                    circles=getattr(plotdef, "circles", [])
                )
            _all_warn = _font_warn + generator.warnings
            if _all_warn:
                messagebox.showwarning("PLOT 경고", "\n\n".join(_all_warn))

            # [추가] gnuplot 스크립트에 에러가 있으면(예: log축 관련 문제) 창이
            # 아예 안 뜨고 프로세스가 바로 죽는데, 그래도 Popen 자체는 성공해서
            # last_process가 None이 아니므로 그동안 캐시에 계속 남아 Multi
            # Print/Save 목록에 "유령 항목"으로 뜨는 문제가 있었음 - 대기 후
            # 프로세스가 이미 종료됐는지 확인해서, 종료됐으면 캐시에 넣지 않고
            # 사용자에게 알린다
            # [수정] 0.4초 딱 한 번만 확인하던 게, 데이터가 많아서 크래시까지
            # 시간이 더 걸리는 경우(0.4초 시점엔 아직 안 죽어서) 놓치는 문제가
            # 있었음 - 최대 2초까지 짧은 간격으로 반복 확인하도록 개선. 또한
            # gnuplot의 실제 stderr 에러 메시지를 잡아서 같이 보여준다
            if mode == "Interactive" and generator.last_process is not None:
                import time as _time
                _crashed = False
                for _ in range(10):  # 0.2초 간격으로 최대 2초
                    _time.sleep(0.2)
                    if generator.last_process.poll() is not None:
                        _crashed = True
                        break
                if _crashed:
                    _err_detail = ""
                    try:
                        if generator.last_process.stderr:
                            _err_detail = generator.last_process.stderr.read().decode("utf-8", errors="ignore").strip()
                    except Exception:
                        _err_detail = ""
                    _msg = "gnuplot이 그래프를 그리지 못하고 바로 종료됐습니다.\n축 설정(특히 Log Scale)이나 데이터 범위를 확인해주세요."
                    if _err_detail:
                        _msg += f"\n\ngnuplot 오류 내용:\n{_err_detail[:500]}"
                    messagebox.showwarning("PLOT", _msg)
                    generator.last_process = None
                elif getattr(generator, "last_anim_ctrl_path", None):
                    # [추가 - space bar 재설계] 애니메이션이 정상적으로 떠 있으면
                    # (크래시 아님) Pause/Speed/Exit 컨트롤 패널을 띄운다.
                    # [수정 - 코드 리뷰로 발견] 패널이 실제 gnuplot 프로세스
                    # 핸들을 전혀 몰라서 (1)Exit을 눌러도 파일에 신호만 쓰고
                    # 창을 직접 안 닫았고 (2)사용자가 창을 직접 닫거나
                    # gnuplot이 죽어도 패널이 그걸 알 방법이 없었음 - 핸들을
                    # 넘겨서 두 가지 다 고친다.
                    self._open_animation_control_panel(
                        generator.last_anim_ctrl_path, generator.last_anim_frame_pause,
                        status_path=getattr(generator, "last_anim_status_path", None),
                        proc=generator.last_process,
                        # [추가 - 요청] plot 창을 제목으로 찾아 겹치지 않게
                        # 배치하고 Z-order를 맞추기 위해 창 제목을 같이 넘김
                        # (gnu_generator._get_terminal_cmd와 동일한 규칙으로
                        # 제목을 만듦 - 파일명에서 확장자만 뗀 것).
                        plot_window_title=os.path.splitext(os.path.basename(outfile))[0],
                    )

            # [수정] self.current_dataset_id는 어디서도 설정되지 않아 항상 'default'로
            # 고정되던 버그. 같은 Plot Title로 Interactive PLOT을 여러 번 누르면
            # active_plots_cache가 매번 같은 키("...+_default")로 덮어써져서,
            # 이전 창들이 실제로는 열려있는데도 Multi Print/Save 목록에서 사라지는
            # 문제가 있었음. 위에서 이미 파일명용으로 계산해둔 next_id(1,2,3...)를
            # 그대로 재사용해서 매번 고유한 키가 되도록 함.
            # [주의] next_id는 custom_filepath가 없을 때(Interactive)만 위에서 계산되므로,
            # Batch/Save/Print(=custom_filepath 지정)에서는 여기서 참조하면 안 됨 -
            # Interactive 분기 안에서만 curr_id를 계산하도록 함.
            if mode == "Interactive" and generator.last_process is not None:
                curr_id = next_id
                # [수정] Plot Title은 비어있을 수 있어서(Batch Queue 등에서는 의도적으로
                # 비워둠) 그걸로 표시 이름을 만들면 "_31"처럼 제목 없이 번호만 남는
                # 문제가 있었음 - 실제 저장되는 plt 파일명(safe_title)을 그대로 사용
                self.plot_processes.append(generator.last_process)
                self.active_plots_cache[f"{safe_title}_{curr_id}"] = plotdef

            if plotdef not in self.history_plots:
                self.history_plots.append(plotdef)

            self.update_plot_file_list()
            return outfile

        except Exception as e:
            messagebox.showerror("Error", f"Failed to execute plot pipeline: {e}")


    def show_multiplot_dialog(self, mode="Batch", default_format="png"):
        dialog = tk.Toplevel(self.root)  # self -> self.root 교정
        dialog.title("Multi-Plot Layout Settings")
        dialog.geometry("450x400")
        dialog.grab_set()

        ttk.Label(dialog, text="Select plots to merge and choose layout:", font=("Malgun Gothic", 10, "bold")).pack(anchor="w", padx=15, pady=10)

        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill="both", expand=True, padx=15, pady=5)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        plot_listbox = tk.Listbox(list_frame, selectmode=tk.MULTIPLE, yscrollcommand=scrollbar.set, font=("Malgun Gothic", 9))
        scrollbar.config(command=plot_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        plot_listbox.pack(side="left", fill="both", expand=True)

        available_plots = getattr(self, "history_plots", [])
        for i, p_def in enumerate(available_plots):
            plot_listbox.insert(tk.END, f"[{i+1}] {p_def.title or 'Unnamed Plot'}")

        layout_frame = ttk.Frame(dialog)
        layout_frame.pack(fill="x", padx=15, pady=10)
        ttk.Label(layout_frame, text="Pages per Sheet (Layout):").pack(side="left", padx=5)

        layout_cmb_var = tk.StringVar(value="Auto")
        cmb_layout = ttk.Combobox(layout_frame, textvariable=layout_cmb_var, values=["Auto", "1/p", "2/p (V)", "4/p (H)", "6/p (V)"], width=12, state="readonly")
        cmb_layout.pack(side="left", padx=5)

        # [참고] 이 함수(show_multiplot_dialog)는 코드베이스 어디서도 호출되지
        # 않는 죽은 코드로 확인됨(실제 "Multi Print/Save" 버튼은
        # open_multi_plot_dialog에 연결돼 있음) - Axis Frame Auto/Manual 컨트롤
        # 추가는 그쪽에 반영했다(해당 함수 참고).

        def on_execute():
            selected_indices = plot_listbox.curselection()
            if not selected_indices:
                messagebox.showwarning("Warning", "Please select at least one plot from the list.", parent=dialog)
                return

            selected_defs = [available_plots[idx] for idx in selected_indices]
            fmt = default_format

            if mode == "Save":
                file_types = [("PNG image", "*.png"), ("PDF cairo", "*.pdf"), ("SVG vector", "*.svg")]
                filepath = filedialog.asksaveasfilename(parent=dialog, defaultextension=f".{default_format}", filetypes=file_types, title="Save Multiplot File")
                if not filepath: return
                fmt = os.path.splitext(filepath)[1].replace(".", "").lower()
            else:
                # 인쇄 시 임시 파일명 규칙 동기화 및 고정
                #filepath = os.path.join(self.plot_dir, "MultiPlot_Print_Temp_1.emf")
                filepath = os.path.join(self.plot_dir, "MultiPlot_Print_1.emf")
                fmt = "emf"

            self.layout_var.set(layout_cmb_var.get())

            # 1. 먼저 멀티플롯 이미지/PDF 파일을 생성합니다.
            _result_path = self.execute_multi_plot_pipeline(selected_defs, mode, filepath, fmt)

            # 2. 인쇄(Print) 모드일 때만 프린터를 고른 뒤 인쇄합니다
            # (EMF로 만들었으니 PDF 뷰어를 거치는 ShellExecute 대신 EMF 전용 헬퍼 사용)
            if mode != "Save":
                if os.path.exists(filepath):
                    printer_name = self._pick_printer_dialog()
                    if printer_name:
                        threading.Thread(
                            target=self._print_emf_and_cleanup,
                            args=(filepath, "CathPlot Multi Plot", printer_name, self.orientation_var.get()),
                            daemon=True
                        ).start()
                    else:
                        try:
                            os.remove(filepath)
                        except OSError:
                            pass

            dialog.destroy()

            # Save일 때만 성공 메시지를 띄웁니다 (인쇄 시에는 윈도우 시스템 창이 뜨므로 생략)
            # [수정] 경고 미리보기에서 취소하면 _result_path가 None(파일도 이미
            # 삭제됨) - 이때는 "성공" 메시지를 띄우지 않는다.
            if mode == "Save" and _result_path:
                messagebox.showinfo("Success", f"Successfully generated multiplot: {os.path.basename(filepath)}")

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", pady=15)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=15)
        ttk.Button(btn_frame, text="Run Plot", command=on_execute).pack(side="right", padx=5)

    def execute_multi_plot_pipeline(self, selected_plot_defs, mode, custom_filepath=None, custom_format=None):
        if not selected_plot_defs:
            messagebox.showwarning("Warning", "No plots selected for multi-plot execution.")
            return None

        os.makedirs(self.plot_dir, exist_ok=True)
        target = "screen" if mode == "Interactive" else "file"
        fmt = (custom_format or "png").lower() if target == "file" else "interactive"

        if custom_filepath:
            outfile = custom_filepath
        else:
            #outfile = os.path.join(self.plot_dir, f"MultiPlot_Temp.gnu" if target == "screen" else f"MultiPlot_Output.{fmt}")
            outfile = os.path.join(self.plot_dir, f"MultiPlot.gnu" if target == "screen" else f"MultiPlot_Output.{fmt}")

        layout_opt = self.layout_var.get()
        is_auto = self.frame_auto_var.get()
        w_str = self.frame_width_var.get().strip()
        h_str = self.frame_height_var.get().strip()
        unit = self.frame_unit_var.get()

        final_frame_width, final_frame_height, final_frame_unit, final_frame_auto = "", "", "", True

        if target == "file" and not is_auto and w_str and h_str:
            try:
                #float(w_str)
                #float(h_str)
                #final_frame_width = w_str
                #final_frame_height = h_str
                #final_frame_unit = unit
                w_val = float(w_str)
                h_val = float(h_str)
                if fmt in ("png", "jpg"):
                    if unit == "cm":
                        w_val /= 2.54
                        h_val /= 2.54
                    final_frame_width = str(int(w_val * 300))
                    final_frame_height = str(int(h_val * 300))
                    final_frame_unit = ""
                else:
                    final_frame_width = w_str
                    final_frame_height = h_str
                    final_frame_unit = unit

                final_frame_auto = False
            except ValueError:
                final_frame_auto = True

        # [수정] Layout이 "Auto"일 때는 Axis Frame Auto 체크박스나 입력된
        # frame_width/height와 무관하게 항상 자동(A4 기반) 크기로 그린다 -
        # Auto 레이아웃은 굳이 frame 입력값에 맞출 필요 없이 알아서 적절히
        # 그리면 된다는 방향으로 정리함 (종횡비도 A4 기준으로 자유롭게 결정)
        # [수정 - 버그] "1개만 골라서 Multi Print/Save 하면 Layout을 따로 "1/p"로
        # 바꾸지 않는 한 기본값 "Auto"라서, Manual(Frame Size)로 지정해도 항상
        # Auto와 똑같이 나오는 문제가 있었음 - plot이 1개일 때는 "레이아웃(칸
        # 배치)"이라는 개념 자체가 의미 없으므로, 이 강제 Auto 규칙은 plot이
        # 2개 이상일 때만 적용한다(1개면 "1/p"를 고른 것과 동일하게 Manual을
        # 그대로 존중).
        if layout_opt == "Auto" and len(selected_plot_defs) > 1:
            final_frame_auto = True
            final_frame_width, final_frame_height, final_frame_unit = "", "", ""

        import dataclasses
        # [수정] is_print_mode는 "실제 프린터로 보내는지"가 아니라 "화면(screen) vs
        # 파일출력(print/save)" 폰트·마진·legend 산정 방식을 가르는 값인데, mode=="Batch"
        # (Multi Print)만 True로 처리하고 mode=="Save"(Multi Save)는 빠져 있어서
        # Save 결과가 화면용 legend 크기 공식으로 그려져 legend box가 과도하게
        # 커지는 문제가 있었음 - Interactive(화면)만 False, 나머지(Batch/Save)는 True로 처리
        # 캐시에 저장된 원본 plotdef를 직접 고치는 대신 복사본을 만들어 적용한다.
        run_plot_defs = [
            dataclasses.replace(pd, is_print_mode=(mode != "Interactive"))
            for pd in selected_plot_defs
        ]
        _font_warn = []
        _fixed_defs = []
        for pd in run_plot_defs:
            pd, w = self._check_and_fix_fonts(pd)
            _fixed_defs.append(pd)
            _font_warn.extend(w)
        run_plot_defs = _fixed_defs

        generator = GnuplotGenerator(self.plot_dir)
        generator.create_multiplot_script(
            plots=run_plot_defs, outfile=outfile, fmt=fmt,
            layout_option=layout_opt, orientation=self.orientation_var.get(),
            keep_script=(mode == "Save"),
            frame_auto=final_frame_auto, frame_width=final_frame_width,
            frame_height=final_frame_height, frame_unit=final_frame_unit,
            # [수정 - 버그] "Print/Save가 왜 다르게 나오나" - 바로 위
            # is_print_mode=(mode != "Interactive")와 개념적으로 같은 값(화면 vs
            # 파일출력)인데 for_print=(mode != "Save")로 서로 다른 로직을 쓰고
            # 있었음 - Save일 때만 False가 돼서 create_multiplot_script 내부의
            # 0.0055(파일)/0.0049(화면) 글자폭 계수 분기에서 Save만 "화면용"
            # 계수를 잘못 쓰게 됨(Print는 0.0055, Save는 0.0049) - is_print_mode와
            # 동일한 기준으로 통일한다.
            for_print=(mode != "Interactive"),
        )

        # [수정 - 요청] "문제 있을 때 창에 결과를 보여줄 순 없나요? 저장/인쇄
        # 전에" - 기존엔 경고 텍스트만 띄우고 그대로 진행됐음(파일은 이미
        # 써진 뒤). 경고가 하나라도 있으면 실제 결과를 미리보기로 보여주고
        # 진행/취소를 다시 묻는다 - 취소하면 방금 만든 파일을 지우고 None을
        # 반환해서, 호출부(Save의 "Success" 메시지, Print의 프린터 전송 단계)가
        # 자연스럽게 건너뛰어지게 한다(Print 쪽은 이미 "if os.path.exists(...)"
        # 로 게이트돼 있어 파일 삭제만으로 충분 - 코드 변경 불필요).
        _all_warn = ([generator.last_size_warning] if generator.last_size_warning else []) + _font_warn + generator.warnings
        if _all_warn and not self._show_result_preview_and_confirm(outfile, _all_warn):
            return None

        self.update_plot_file_list()
        return outfile

    def update_plot_file_list(self):
        if not hasattr(self, 'plot_dir') or not self.plot_dir: return
        files = glob.glob(os.path.join(self.plot_dir, "*.plt"))
        files.sort(key=os.path.getctime)
        if hasattr(self, 'file_listbox'):
            self.file_listbox.delete(0, 'end')
            for f in files: self.file_listbox.insert('end', os.path.basename(f))

    #def execute_print_dialog(self):
    #    idx = 1
    #    while True:
    #        temp_pdf = os.path.join(self.plot_dir, f"Print_Job_Temp_{idx}.pdf")
    #        if not os.path.exists(temp_pdf):
    #            break
    #        idx += 1
    #
    #    success_path = self.execute_plot_pipeline("Batch", custom_filepath=temp_pdf, custom_format="PDF")
    #
    #    if success_path and os.path.exists(success_path):
    #        threading.Thread(
    #            target=self._print_and_cleanup, args=(success_path,), daemon=True
    #        ).start()

    def execute_print_dialog(self):
        """PDF를 만들어 외부 PDF 뷰어 앱을 거쳐 인쇄하던 방식 대신, EMF를 만들어
        직접 프린터로 인쇄한다.
        - PDF 뷰어가 설치되어 있는지와 무관하게 항상 동작함
        - 외부 앱이 파일을 여는 걸 기다릴 필요가 없어(임시파일을 우리가 직접 프린터로
          그려버리므로), 너무 일찍 지워서 생기던 경쟁 상태 문제도 원천적으로 없음
        - 네이티브 win32 프린터 선택 대화상자(win32ui.CreatePrintDialog)가 일부
          환경(한글 프린터명 등)에서 내부 인코딩 오류를 일으켜서, 대신 프린터
          목록을 직접 열거해 우리 자체 선택창으로 고르게 함
        - 저장된(Interactive로 그렸던) plot이 있으면, 무조건 현재 화면 설정으로만
          찍지 않고 어떤 것을 인쇄할지 + 용지 방향(세로/가로)을 먼저 물어봄
          (Multi Print/Save는 자체 orientation 선택이 있어서 여기서는 중복으로
          다시 안 물어봄 - 프린터 선택창은 프린터만 고름)
        """
        # [추가 - 요청] "Animate 체크 상태에서 Print를 누르면?" - 인쇄는
        # 물리 종이라 애니메이션 자체가 불가능함(항상 정적 1장) - 사용자가
        # Animate를 켜둔 걸 잊고 눌렀을 때 "왜 안 움직이지"로 헷갈리지 않게
        # 한 번 알려준다(진행은 그대로, 취소 아님 - 정적 인쇄로 계속됨).
        if getattr(self, "animate_var", None) is not None and self.animate_var.get():
            messagebox.showinfo(
                "Animate 켜짐",
                "Print는 애니메이션을 지원하지 않아 현재 화면(정적) 기준으로 인쇄됩니다.\n"
                "애니메이션을 파일로 남기려면 'Save GIF' 버튼을 이용하세요."
            )
        chosen_plotdef, orientation = self._pick_plot_to_print_dialog()
        if chosen_plotdef is False:
            return  # 사용자가 취소함
        # chosen_plotdef가 None이면 "현재 화면 설정"을 고른 것 - 아래 기존 방식 그대로 진행

        idx = 1
        while True:
            temp_emf = os.path.join(self.plot_dir, f"Print_Job_Temp_{idx}.emf")
            if not os.path.exists(temp_emf):
                break
            idx += 1

        try:
            import dataclasses

            def _apply_orientation_to_plotdef(pd, orientation):
                """PRINT 시 실제 인쇄될 frame 크기를 정한다.
                [수정] 화면(Interactive)은 frame 설정이 렌더링에 아무 영향도 없어
                (캔버스가 항상 1000x700 고정) 캐시된 plot이 들고 있는 frame_auto/
                width/height는 그 plot을 그릴 때 의도적으로 고른 값이 아니라 그
                시점 GUI에 우연히 남아있던 값일 수 있음 - "크기는 항상 인쇄
                시점의 현재 GUI Frame 설정을 따른다"로 통일한다(Multi-Print/
                Save, '현재 화면 설정'과 동일 원칙). 고른 plot은 내용(curve 등)만
                제공하고, 크기는 pd가 아니라 현재 GUI 상태에서 가져온다."""
                if self.frame_auto_var.get():
                    w_str, h_str = self._compute_auto_frame_size_cm(for_print=True, orientation=orientation)
                    w, h = float(w_str), float(h_str)
                    unit = "cm"
                else:
                    try:
                        w = float((self.frame_width_var.get() or "10").strip() or 10.0)
                        h = float((self.frame_height_var.get() or "8").strip() or 8.0)
                    except ValueError:
                        w, h = 10.0, 8.0
                    unit = self.frame_unit_var.get()
                    # [수정 - 재검토] "가로/세로는 그대로 두고 위치만 가로세로로
                    # 두면 어떨까"라는 지적으로 여기 있던 orientation 기반 w/h
                    # 스왑을 없앰 - Manual로 지정한 축 크기의 x:y는 orientation
                    # 선택과 무관하게 항상 그대로 유지된다(_compute_auto_frame_size_cm
                    # 주석 참고 - 실제 인쇄 단계가 EMF 비율은 유지한 채 페이지만
                    # 돌리므로 스왑이 애초에 불필요했음).
                return dataclasses.replace(pd, frame_auto=False, frame_width=str(w), frame_height=str(h), frame_unit=unit)

            if chosen_plotdef is not None:
                print_plotdef = dataclasses.replace(chosen_plotdef, is_print_mode=True)
                print_plotdef = _apply_orientation_to_plotdef(print_plotdef, orientation)
                print_plotdef, _font_warn = self._check_and_fix_fonts(print_plotdef)
                generator = GnuplotGenerator(self.plot_dir)
                generator.create_script(print_plotdef, temp_emf, fmt="emf",
                                         annotations=print_plotdef.annotations, arrows=print_plotdef.arrows,
                                         circles=getattr(print_plotdef, "circles", []))
                _all_warn = _font_warn + generator.warnings
                if _all_warn:
                    messagebox.showwarning("PRINT 경고", "\n\n".join(_all_warn))
                success_path = temp_emf
            else:
                # 현재 화면 설정 그대로 인쇄하는 경우 - GUI 변수를 임시로 방향에 맞게
                # 바꿔서 생성한 뒤 원래 값으로 되돌린다
                _orig_auto = self.frame_auto_var.get()
                _orig_w = self.frame_width_var.get()
                _orig_h = self.frame_height_var.get()
                _orig_unit = self.frame_unit_var.get()
                # [수정] Auto가 켜져 있으면 여기서 5x4in라는 임의의 작은 고정값으로
                # 대체해버려서, 실제 용지를 거의 다 채워야 할 Auto 인쇄가 그보다
                # 훨씬 작게(약 1/3 크기) 나오는 문제가 있었음 - Multi-Print의 1/p
                # Auto/Save의 Auto와 동일하게 _compute_auto_frame_size_cm으로
                # 용지 크기 기준 값을 계산해서 써야 함
                if _orig_auto:
                    w_str, h_str = self._compute_auto_frame_size_cm(for_print=True, orientation=orientation)
                    w, h = float(w_str), float(h_str)
                    unit = "cm"
                else:
                    try:
                        w = float((_orig_w or "10").strip() or 10.0)
                        h = float((_orig_h or "8").strip() or 8.0)
                    except ValueError:
                        w, h = 10.0, 8.0
                    unit = _orig_unit
                # [수정 - 재검토] orientation 기반 w/h 스왑 제거 (위
                # _apply_orientation_to_plotdef 주석과 동일한 이유).
                self.frame_auto_var.set(False)
                self.frame_width_var.set(str(w))
                self.frame_height_var.set(str(h))
                self.frame_unit_var.set(unit)
                try:
                    success_path = self.execute_plot_pipeline("Batch", custom_filepath=temp_emf, custom_format="EMF")
                finally:
                    self.frame_auto_var.set(_orig_auto)
                    self.frame_width_var.set(_orig_w)
                    self.frame_height_var.set(_orig_h)
                    self.frame_unit_var.set(_orig_unit)
        except Exception as e:
            messagebox.showerror("Print Error", f"인쇄용 파일 생성 중 오류가 발생했습니다:\n{e}")
            return

        if not (success_path and os.path.exists(success_path)):
            return

        # 프린터 선택창은 Tkinter 창이라 메인 스레드에서 열어야 함(모달 대기)
        printer_name = self._pick_printer_dialog()
        if not printer_name:
            try:
                os.remove(success_path)
            except OSError:
                pass
            return  # 사용자가 취소함

        raw_title = self.filename_var.get().strip() or "CathPlot"
        threading.Thread(
            target=self._print_emf_and_cleanup, args=(success_path, raw_title, printer_name, orientation), daemon=True
        ).start()

    def _pick_plot_to_print_dialog(self):
        """PRINT 버튼을 눌렀을 때 무엇을 인쇄할지, 어떤 용지 방향으로 인쇄할지 고르는 창.
        (Multi Print/Save는 이미 자체 orientation 선택이 있어서 중복이라, 단일
        PRINT 전용으로 여기서 방향까지 같이 물어봄)
        반환값: (choice, orientation) 튜플.
          choice: None = '현재 화면 설정'을 고름(기존 방식), False = 취소,
                  그 외 = 선택된 PlotDefinition 객체
          orientation: "portrait" 또는 "landscape" (취소 시 의미 없음)"""
        CURRENT_SCREEN_LABEL = "현재 화면 설정"
        self._cleanup_stale_plot_cache()
        names = [CURRENT_SCREEN_LABEL] + sorted(self.active_plots_cache.keys())

        result = {"choice": False, "orientation": self.orientation_var.get()}
        dlg = tk.Toplevel(self.root)
        dlg.title("인쇄할 Plot 선택")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="인쇄할 대상을 선택하세요:").pack(padx=15, pady=(15, 5))
        choice_var = tk.StringVar(value=CURRENT_SCREEN_LABEL)
        ttk.Combobox(
            dlg, textvariable=choice_var, values=names, width=35, state="readonly"
        ).pack(padx=15, pady=5)

        ttk.Label(dlg, text="용지 방향:").pack(padx=15, pady=(5, 2))
        orient_var = tk.StringVar(value=self.orientation_var.get())
        ttk.Combobox(
            dlg, textvariable=orient_var, values=["portrait", "landscape"], width=15, state="readonly"
        ).pack(padx=15, pady=5)

        def do_ok():
            picked = choice_var.get()
            result["choice"] = None if picked == CURRENT_SCREEN_LABEL else self.active_plots_cache.get(picked)
            result["orientation"] = orient_var.get()
            dlg.destroy()

        btn_row = ttk.Frame(dlg)
        btn_row.pack(pady=10)
        ttk.Button(btn_row, text="취소", command=dlg.destroy).pack(side="right", padx=5)
        ttk.Button(btn_row, text="확인", command=do_ok).pack(side="right", padx=5)

        self.root.wait_window(dlg)
        return result["choice"], result["orientation"]

    def _ask_file_conflict(self, filename):
        """같은 이름의 출력 파일이 이미 있을 때 어떻게 할지 물어본다.
        반환값: 'overwrite'(덮어쓰기) / 'add'(번호를 올려 새로 추가) / 'cancel'(취소).
        참고: 이미 쌓인 예전 파일들을 한꺼번에 정리하고 싶으면 "Clean Past Plots"
        버튼을 사용하면 된다."""
        result = {"choice": "cancel"}
        dlg = tk.Toplevel(self.root)
        dlg.title("파일 존재")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(
            dlg, text=f"'{filename}' 파일이 이미 존재합니다.\n어떻게 할까요?",
            padding=15, justify="left"
        ).pack()

        def pick(choice):
            result["choice"] = choice
            dlg.destroy()

        btn_row = ttk.Frame(dlg)
        btn_row.pack(pady=(0, 15))
        ttk.Button(btn_row, text="번호를 올려 추가", command=lambda: pick("add")).pack(side="left", padx=5)
        ttk.Button(btn_row, text="덮어쓰기", command=lambda: pick("overwrite")).pack(side="left", padx=5)
        ttk.Button(btn_row, text="취소", command=lambda: pick("cancel")).pack(side="left", padx=5)

        self.root.wait_window(dlg)
        return result["choice"]

    def _load_preview_image(self, filepath):
        """Save/Print 결과 파일(pdf/png/jpg/emf)을 미리보기용 PIL Image로 연다.
        [추가] "문제 있을 때 창에 결과를 보여줄 순 없나요? 저장/인쇄 전에" 요청으로
        신설 - PIL/PyMuPDF(fitz) 둘 다 지연 import(이미 hiddenimports에 등록돼
        있어 exe에서도 정상 동작 - CathPlot.spec 참고). 실패하면 None(호출부가
        "미리보기 없이 경고 텍스트만" 으로 대체)."""
        ext = os.path.splitext(filepath)[1].lower()
        try:
            from PIL import Image
            if ext == ".pdf":
                import pymupdf as fitz  # [수정] "fitz API is deprecated" 경고 제거 - pymupdf가 정식 이름
                doc = fitz.open(filepath)
                pix = doc[0].get_pixmap(dpi=150)
                return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            elif ext == ".emf":
                im = Image.open(filepath)
                im.load(dpi=(150, 150))
                return im.convert("RGB")
            elif ext in (".png", ".jpg", ".jpeg", ".bmp"):
                return Image.open(filepath).convert("RGB")
        except Exception:
            pass
        return None  # svg 등 미지원 포맷 또는 로드 실패 - 미리보기 생략

    def _show_result_preview_and_confirm(self, filepath, warnings_list):
        """[추가 - 요청] "문제 있을 때(경고) 창에 결과를 보여줄 순 없나요? 저장/
        인쇄 전에" - Save/Print가 실제로 파일에 쓰기 직전이 아니라 이미 쓴
        "직후"(파일이 있어야 미리보기가 가능하므로)에, 경고가 있는 경우에만
        그 결과 파일을 그대로 렌더링해서 보여주고 진행/취소를 다시 확인받는다.
        취소하면 방금 만든 파일을 지우고 False를 반환해서(호출부가 이 반환값을
        보고 이후 단계 - 성공 메시지, 프린터로 전송 등 - 를 건너뛰게 함) 마치
        저장/인쇄가 아예 없었던 것처럼 되돌린다. 경고가 없으면 미리보기 없이
        바로 True(항상 뜨면 매번 확인창이라 번거로움 - 사용자 확인)."""
        if not warnings_list:
            return True
        win = tk.Toplevel(self.root)
        win.title("저장/인쇄 결과 확인 - 경고 있음")
        win.transient(self.root)
        win.grab_set()
        result = {"proceed": False}

        img = self._load_preview_image(filepath)
        if img is not None:
            _max_w, _max_h = 760, 480
            _scale = min(_max_w / img.width, _max_h / img.height, 1.0)
            _disp = img.resize((max(1, int(img.width * _scale)), max(1, int(img.height * _scale))))
            from PIL import ImageTk
            _photo = ImageTk.PhotoImage(_disp)
            img_label = ttk.Label(win, image=_photo)
            img_label.image = _photo  # GC 방지(참조 유지 안 하면 즉시 사라짐)
            img_label.pack(padx=10, pady=(10, 0))
        else:
            ttk.Label(win, text="(이 포맷은 미리보기를 지원하지 않습니다 - 경고 내용만 확인하세요)").pack(padx=10, pady=(10, 0))

        warn_frame = ttk.Frame(win)
        warn_frame.pack(fill="x", padx=10, pady=10)
        ttk.Label(warn_frame, text="\n\n".join(warnings_list), wraplength=740, foreground="#a05a00", justify="left").pack(anchor="w")

        def _on_proceed():
            result["proceed"] = True
            win.destroy()

        def _on_cancel():
            result["proceed"] = False
            win.destroy()

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="취소(다시 설정)", command=_on_cancel).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="이대로 진행", command=_on_proceed).pack(side="right", padx=5)
        win.protocol("WM_DELETE_WINDOW", _on_cancel)
        win.wait_window()

        if not result["proceed"]:
            try:
                os.remove(filepath)
            except OSError:
                pass
        return result["proceed"]

    def _pick_printer_dialog(self):
        """설치된 프린터 목록을 직접 열거해서 자체 선택창으로 고르게 한다
        (네이티브 win32 프린트 대화상자를 대체 - 반드시 메인 스레드에서 호출해야 함).
        용지 방향은 여기서 다시 묻지 않음 - 단일 PRINT는 _pick_plot_to_print_dialog에서,
        Multi Print/Save는 자체 orientation_var에서 이미 정해져서 넘어옴 (중복 방지).
        반환값: printer_name, 취소 시 None"""
        import win32print  # [수정 - 지연 import] 파일 위 설명 참고
        try:
            printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
            names = [p[2] for p in printers]
        except Exception as e:
            messagebox.showerror("Print Error", f"프린터 목록을 가져오지 못했습니다: {e}")
            return None

        if not names:
            messagebox.showerror("Print Error", "설치된 프린터를 찾을 수 없습니다.")
            return None

        try:
            default_name = win32print.GetDefaultPrinter()
        except Exception:
            default_name = names[0]

        result = {"name": None}
        dlg = tk.Toplevel(self.root)
        dlg.title("프린터 선택")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="프린터를 선택하세요:").pack(padx=15, pady=(15, 5))
        printer_var = tk.StringVar(value=default_name if default_name in names else names[0])
        ttk.Combobox(
            dlg, textvariable=printer_var, values=names, width=45, state="readonly"
        ).pack(padx=15, pady=5)

        def do_ok():
            result["name"] = printer_var.get()
            dlg.destroy()

        btn_row = ttk.Frame(dlg)
        btn_row.pack(pady=10)
        ttk.Button(btn_row, text="취소", command=dlg.destroy).pack(side="right", padx=5)
        ttk.Button(btn_row, text="인쇄", command=do_ok).pack(side="right", padx=5)

        self.root.wait_window(dlg)
        return result["name"]

    def _print_emf_and_cleanup(self, filepath, document_name, printer_name, orientation="portrait"):
        """PDF 뷰어를 거치지 않고, 지정된 프린터로 EMF를 직접 그려서 인쇄한다
        (PDF 앱 설치 여부와 무관하게 동작하며, 일부 환경에서 오류를 일으키는
        네이티브 win32 프린트 대화상자 대신 이미 골라둔 프린터 이름을 그대로 사용).
        EMF 핸들 관련 함수(GetEnhMetaFile 등)는 pywin32 빌드에 따라 win32gui에
        없는 경우가 있어, pywin32 래퍼 대신 gdi32.dll을 ctypes로 직접 호출한다
        (Windows에 항상 존재하는 API라 pywin32 버전에 영향받지 않음).
        [수정] 페이지 전체 크기에 맞춰 무조건 늘려 그리면 원본 가로세로 비율이
        깨져 글자가 늘어나거나 눌려 보이는 문제가 있어, EMF 헤더에 저장된
        원본 비율(rclFrame)을 읽어 비율을 유지한 채 페이지 중앙에 배치한다."""
        import ctypes
        import pythoncom, win32ui, win32print, win32con, pywintypes  # [수정 - 지연 import] 파일 위 설명 참고

        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class _ENHMETAHEADER(ctypes.Structure):
            # 필요한 앞부분 필드(rclFrame까지)만 정의 - 뒤쪽 필드는 안 읽으므로 불필요
            _fields_ = [
                ("iType", ctypes.c_uint32),
                ("nSize", ctypes.c_uint32),
                ("rclBounds", _RECT),
                ("rclFrame", _RECT),
            ]

        gdi32 = ctypes.windll.gdi32
        # 64비트 Windows에서 HANDLE/HDC가 기본 c_int(32비트)로 잘리지 않도록
        # 명시적으로 포인터 크기(c_void_p)로 지정
        gdi32.GetEnhMetaFileW.argtypes = [ctypes.c_wchar_p]
        gdi32.GetEnhMetaFileW.restype = ctypes.c_void_p
        gdi32.PlayEnhMetaFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_RECT)]
        gdi32.PlayEnhMetaFile.restype = ctypes.c_int
        gdi32.DeleteEnhMetaFile.argtypes = [ctypes.c_void_p]
        gdi32.DeleteEnhMetaFile.restype = ctypes.c_int
        gdi32.GetEnhMetaFileHeader.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        gdi32.GetEnhMetaFileHeader.restype = ctypes.c_uint32

        pythoncom.CoInitialize()
        dc = None
        emf_handle = None
        step = "프린터 DC 만들기"
        try:
            dc = win32ui.CreateDC()
            try:
                # 용지 방향을 DEVMODE에 지정해서 실제로 용지를 회전시켜 인쇄
                # (지정 안 하면 프린터 기본값 - 보통 세로 - 로만 나감)
                hprinter = win32print.OpenPrinter(printer_name)
                try:
                    # [수정] "완전한 DEVMODE를 먼저 조회"하는 2단계 방식이 일부
                    # 프린터 드라이버에서 항상 매개변수 오류(87)로 실패하는 것으로
                    # 확인됨 - 불필요한 에러 로그만 남기므로 제거하고, GetPrinter의
                    # DEVMODE를 바로 사용한다. (실제 방향이 안 맞아도 아래 수동
                    # 회전 fallback이 콘텐츠를 올바르게 돌려주는 것으로 확인됨)
                    devmode = win32print.GetPrinter(hprinter, 2)["pDevMode"]

                    devmode.Orientation = (
                        win32con.DMORIENT_LANDSCAPE if orientation == "landscape" else win32con.DMORIENT_PORTRAIT
                    )
                    devmode.Fields |= win32con.DM_ORIENTATION
                    # [핵심 수정] DEVMODE.Orientation만 바꿔서 바로 CreateDC에 넘기면
                    # 일부 프린터 드라이버가 이 변경을 무시하고 계속 세로로 인쇄하는
                    # 문제가 있었음(Windows GDI의 잘 알려진 함정) - DocumentProperties를
                    # 거쳐 드라이버가 실제로 그 변경을 검증/병합하게 해야 방향이 확실히
                    # 반영됨
                    try:
                        new_devmode = win32print.DocumentProperties(
                            0, hprinter, printer_name, devmode, devmode,
                            win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER
                        )
                        if new_devmode:
                            devmode = new_devmode
                        else:
                            self._log_warning(
                                "DocumentProperties가 빈 값을 반환함 - 방향 변경이 "
                                "적용 안 됐을 수 있음(원래 devmode로 계속 진행)."
                            )
                    except Exception as e:
                        # [수정] 예전엔 여기서 조용히 무시(pass)해서, 이 호출이
                        # 실패해도 아무 신호 없이 원래(미수정) devmode로 계속
                        # 진행되고 있었음 - 실패 이유를 로그에 남겨서 다음
                        # 테스트에서 원인을 확인할 수 있게 함
                        self._log_warning(f"DocumentProperties(적용) 실패: {e} - 원래 devmode로 계속 진행")
                finally:
                    win32print.ClosePrinter(hprinter)
                dc.CreateDC("WINSPOOL", printer_name, None, devmode)
            except Exception:
                # 방향 지정에 실패하면 프린터 기본 방향으로라도 진행
                dc.CreatePrinterDC(printer_name)

            step = "EMF 파일 열기"
            emf_handle = gdi32.GetEnhMetaFileW(os.path.abspath(filepath))
            if not emf_handle:
                raise RuntimeError("EMF 파일을 열 수 없습니다 (파일이 손상되었거나 없음).")

            step = "인쇄 페이지 크기 조회"
            width = dc.GetDeviceCaps(win32con.HORZRES)
            height = dc.GetDeviceCaps(win32con.VERTRES)
            # [추가] 인쇄 크기를 지정한 물리적 크기 그대로 맞추기 위해 프린터
            # DPI를 조회해둔다 (아래 "EMF 그리기" 단계에서 사용)
            dpi_x = dc.GetDeviceCaps(win32con.LOGPIXELSX)
            dpi_y = dc.GetDeviceCaps(win32con.LOGPIXELSY)

            # [추가] DEVMODE 방향 변경이 실제로 프린터 DC에 반영됐는지 검증 -
            # 요청한 방향과 실제 페이지 가로/세로 비율이 안 맞으면, 경고만 남기고
            # 끝내는 대신 GDI 좌표 변환(world transform)으로 콘텐츠를 90도 회전시켜
            # 올바른 방향으로 나오도록 한다 (드라이버가 물리적 용지 급지 방향
            # 자체를 못 바꾸더라도, 최소한 인쇄되는 내용은 의도한 방향으로 보이게)
            actual_is_landscape = width > height
            wants_landscape = (orientation == "landscape")
            need_manual_rotate = actual_is_landscape != wants_landscape
            if need_manual_rotate:
                self._log_warning(
                    f"이 프린터는 용지 자체 방향({orientation}) 변경은 지원 안 하는 것으로 "
                    f"보임 (width={width}, height={height} - {'가로' if actual_is_landscape else '세로'} 용지). "
                    f"콘텐츠를 90도 회전해서 인쇄합니다 (정상 동작 - 용지는 세로, 내용만 회전됨)."
                )

            step = "EMF 원본 비율 조회"
            frame_w, frame_h = None, None
            try:
                req_size = gdi32.GetEnhMetaFileHeader(emf_handle, 0, None)
                if req_size:
                    buf = ctypes.create_string_buffer(req_size)
                    gdi32.GetEnhMetaFileHeader(emf_handle, req_size, buf)
                    header = _ENHMETAHEADER.from_buffer(buf)
                    frame_w = header.rclFrame.right - header.rclFrame.left
                    frame_h = header.rclFrame.bottom - header.rclFrame.top
            except Exception:
                frame_w, frame_h = None, None  # 실패하면 그냥 페이지 전체 사용(기존 방식)로 대체

            step = "인쇄 작업 시작"
            dc.StartDoc(document_name)
            dc.StartPage()

            step = "EMF 그리기"
            # 회전이 필요하면, 그리기 좌표계 기준을 (height x width)로 스왑해서
            # 계산한다 - world transform이 이 좌표계를 실제 페이지(width x height)로
            # 90도 돌려서 매핑해준다
            fit_w, fit_h = (height, width) if need_manual_rotate else (width, height)
            if frame_w and frame_h and dpi_x > 0 and dpi_y > 0 and fit_w > 0 and fit_h > 0:
                # [수정] "인쇄 가능 영역에 최대한 크게 맞추기"는 프린터 하드웨어의
                # 인쇄 불가 여백 때문에 지정한 물리 크기보다 항상 조금 작게
                # 나오는 문제가 있었음 - 대신 EMF 헤더의 rclFrame(0.01mm 단위,
                # 실제 물리 크기)을 프린터 DPI로 직접 변환해서, 지정한 크기
                # 그대로 인쇄되게 한다. 인쇄 가능 영역을 벗어날 때만(용지보다 큰
                # 크기를 요청한 경우) 부득이하게 비율 유지하며 축소한다.
                # dpi/인쇄가능영역이 비정상(0 이하)이면 이 계산을 아예 안 타고
                # 기존 방식(전체 영역에 맞추기)으로 안전하게 폴백한다.
                dest_w = max(int(frame_w / 100.0 / 25.4 * dpi_x), 1)  # 0.01mm -> inch -> px
                dest_h = max(int(frame_h / 100.0 / 25.4 * dpi_y), 1)
                if dest_w > fit_w or dest_h > fit_h:
                    shrink = min(fit_w / dest_w, fit_h / dest_h)
                    dest_w = max(int(dest_w * shrink), 1)
                    dest_h = max(int(dest_h * shrink), 1)
                dest_left = (fit_w - dest_w) // 2
                dest_top = (fit_h - dest_h) // 2
                rect = _RECT(dest_left, dest_top, dest_left + dest_w, dest_top + dest_h)
            else:
                rect = _RECT(0, 0, fit_w, fit_h)

            hdc = dc.GetSafeHdc()
            rotation_applied = False
            if need_manual_rotate:
                try:
                    class _XFORM(ctypes.Structure):
                        _fields_ = [("eM11", ctypes.c_float), ("eM12", ctypes.c_float),
                                    ("eM21", ctypes.c_float), ("eM22", ctypes.c_float),
                                    ("eDx", ctypes.c_float), ("eDy", ctypes.c_float)]
                    GM_ADVANCED = 2
                    gdi32.SetGraphicsMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    gdi32.SetGraphicsMode.restype = ctypes.c_int
                    gdi32.SetWorldTransform.argtypes = [ctypes.c_void_p, ctypes.POINTER(_XFORM)]
                    gdi32.SetWorldTransform.restype = ctypes.c_int
                    if gdi32.SetGraphicsMode(hdc, GM_ADVANCED):
                        # (x,y) -> (width - y, x) : 90도 회전 후 실제 페이지 폭만큼 이동
                        xform = _XFORM(0.0, 1.0, -1.0, 0.0, float(width), 0.0)
                        if gdi32.SetWorldTransform(hdc, ctypes.byref(xform)):
                            rotation_applied = True
                        else:
                            self._log_warning("SetWorldTransform 실패 - 회전 없이 그대로 인쇄합니다.")
                    else:
                        self._log_warning("SetGraphicsMode(GM_ADVANCED) 실패 - 회전 없이 그대로 인쇄합니다.")
                except Exception as e:
                    self._log_warning(f"수동 회전 적용 중 오류: {e} - 회전 없이 그대로 인쇄합니다.")
                if not rotation_applied:
                    # 회전 적용 실패 - 원래(비회전) 좌표계로 되돌려서 그린다
                    fit_w, fit_h = width, height
                    if frame_w and frame_h:
                        # [수정 - 버그] frame_aspect가 정의된 적이 없어 이 분기(회전
                        # 실패 시 폴백)에 들어오면 NameError로 인쇄 자체가 실패했음.
                        fit_aspect = fit_w / fit_h
                        frame_aspect = frame_w / frame_h
                        if frame_aspect > fit_aspect:
                            dest_w, dest_h = fit_w, int(fit_w / frame_aspect)
                        else:
                            dest_h, dest_w = fit_h, int(fit_h * frame_aspect)
                        dest_left, dest_top = (fit_w - dest_w) // 2, (fit_h - dest_h) // 2
                        rect = _RECT(dest_left, dest_top, dest_left + dest_w, dest_top + dest_h)
                    else:
                        rect = _RECT(0, 0, fit_w, fit_h)

            gdi32.PlayEnhMetaFile(hdc, emf_handle, ctypes.byref(rect))

            if rotation_applied:
                # 이후 그리기(있다면)에 영향 없도록 항등 변환으로 복구
                try:
                    identity = _XFORM(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
                    gdi32.SetWorldTransform(hdc, ctypes.byref(identity))
                except Exception:
                    pass

            step = "인쇄 작업 마무리"
            dc.EndPage()
            dc.EndDoc()
            self.root.after(0, lambda: messagebox.showinfo("Print", "인쇄 작업을 프린터로 전송했습니다."))
        except pywintypes.error as e:
            # pywin32의 Windows 시스템 에러 메시지(FormatMessage 결과)는 한글 코드페이지라
            # 그 메시지 문자열 자체를 다시 다루다 인코딩 에러가 나는 경우가 있어서,
            # 문자열 대신 항상 안전한 에러 코드(숫자)만 사용해서 표시한다.
            try:
                code = e.args[0] if e.args else "?"
            except Exception:
                code = "?"
            err_msg = f"[{step}] 중 Windows 인쇄 오류 (오류 코드: {code})"
            self.root.after(0, lambda msg=err_msg: messagebox.showerror("Print Error", msg))
        except Exception as e:
            try:
                err_msg = f"[{step}] 중 오류: {e}"
            except Exception:
                err_msg = f"[{step}] 중 알 수 없는 오류 (메시지를 표시할 수 없음)"
            self.root.after(0, lambda msg=err_msg: messagebox.showerror("Print Error", msg))
        finally:
            if emf_handle:
                gdi32.DeleteEnhMetaFile(emf_handle)
            if dc:
                dc.DeleteDC()
            pythoncom.CoUninitialize()
            # 외부 뷰어 앱이 파일을 붙잡고 있는 게 아니라 우리가 직접 프린터로 그린
            # 것이므로, 대화상자가 끝난 시점에 바로 지워도 안전함
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except OSError:
                pass

#    def _print_emf_and_cleanup_OLD(self, filepath, document_name):
#        """Show the native print dialog and spool an EMF without a PDF viewer."""
#        try:
#            dialog = win32ui.CreatePrintDialog(0)
#            if dialog.DoModal() != win32con.IDOK:
#                return False
#
#            dc = dialog.GetPrinterDC()
#            emf = None
#            try:
#                emf = win32gui.GetEnhMetaFile(os.path.abspath(filepath))
#                width = dc.GetDeviceCaps(win32con.HORZRES)
#                height = dc.GetDeviceCaps(win32con.VERTRES)
#                dc.StartDoc(document_name)
#                dc.StartPage()
#                win32gui.PlayEnhMetaFile(dc.GetSafeHdc(), emf, (0, 0, width, height))
#                dc.EndPage()
#                dc.EndDoc()
#            finally:
#                if emf:
#                    win32gui.DeleteEnhMetaFile(emf)
#                if dc:
#                    dc.DeleteDC()
#            return True
#        finally:
#            # No viewer has the EMF open, so cleanup is immediate and reliable.
#            try:
#                if os.path.exists(filepath):
#                    os.remove(filepath)
#            except OSError:
#                pass

    def _print_and_cleanup(self, filepath):
        # ShellExecute는 내부적으로 COM을 쓰기 때문에, 새로 만든 스레드에서
        # 바로 호출하면 COM이 초기화되어 있지 않아 멈추거나(hang) 심하면
        # 프로세스 자체가 죽는 네이티브 크래시가 날 수 있다. 이 스레드
        # 전용으로 COM을 초기화/정리해준다.
        import pythoncom, win32api  # [수정 - 지연 import] 파일 위 설명 참고
        pythoncom.CoInitialize()
        try:
            result = win32api.ShellExecute(0, "print", os.path.abspath(filepath), None, ".", 0)
            if result > 32:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Print", "인쇄 작업을 프린터로 전송했습니다."
                ))
            if result <= 32:
                # "print" verb가 이 PDF 뷰어에서 지원 안 되는 경우 - 그냥 열어서
                # 사용자가 직접 Ctrl+P로 인쇄하도록 안내
                win32api.ShellExecute(0, "open", os.path.abspath(filepath), None, ".", 0)
                self.root.after(0, lambda: messagebox.showinfo(
                    "Print",
                    "이 PDF 뷰어는 자동 인쇄를 지원하지 않아 파일을 열기만 했습니다.\n"
                    "열린 창에서 Ctrl+P로 직접 인쇄해주세요."
                ))
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, lambda msg=err_msg: messagebox.showerror("Print Error", msg))
        finally:
            pythoncom.CoUninitialize()

        # 인쇄 스풀/뷰어가 파일을 읽어갈 시간을 준 뒤 삭제 (메인 스레드 안 막음)
        # [수정] ShellExecute(..., "print", ...)는 프린터 전송이 끝난 게 아니라 연결된
        # PDF 뷰어 앱을 비동기로 띄우는 것뿐이라, 그 앱이 뜨는 데 시간이 걸리면(특히
        # 해당 세션에서 처음 실행되는 경우) 예전의 10초 대기로는 부족해서 앱이 파일을
        # 열기도 전에 지워버리는 경우가 있었음. 첫 대기를 60초로 늘리고, 그래도 파일이
        # 잠겨있으면(뷰어가 계속 열어둔 상태) 무리하게 지우지 않고 몇 번 더 시도 후 포기함
        # (남은 임시파일은 "Clean Past Plots"로 나중에 정리 가능)
        def _delayed_delete():
            for _ in range(6):
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    break
                except Exception:
                    time.sleep(10.0)

        threading.Timer(60.0, _delayed_delete).start()

    def execute_save_dialog(self):
        """SAVE도 PRINT처럼, 저장된(Interactive로 그렸던) plot이 있으면 무조건
        현재 화면 설정으로만 저장하지 않고 어떤 것을 + 어떤 용지 방향으로
        저장할지 먼저 물어본다 (_pick_plot_to_save_dialog 참고 - PRINT의
        _pick_plot_to_print_dialog와 동일한 패턴).
        [추가 - 요청] "Animation 모드에서 SAVE 누르면 GIF로 저장" - 별도 버튼을
        새로 만드는 대신, Animate 체크박스가 켜져 있고 "현재 화면 설정"을
        고른 경우엔 이 SAVE 버튼 자체가 애니메이션 GIF 저장으로 동작한다
        (파일명은 기본값 제시, 확장자도 .gif 하나만 - PDF/PNG 등 정적
        포맷 선택 자체가 애니메이션에는 의미 없으므로)."""
        chosen_plotdef, orientation = self._pick_plot_to_save_dialog()
        if chosen_plotdef is False:
            return  # 사용자가 취소함
        # chosen_plotdef가 None이면 "현재 화면 설정"을 고른 것 - 아래 기존 방식 그대로 진행

        _animate_on = getattr(self, "animate_var", None) is not None and self.animate_var.get()
        if _animate_on and chosen_plotdef is not None:
            # 캐시된(이전에 Interactive로 그려둔) plot을 고른 경우는 "지금"의
            # Animate/재생시간 설정과 그 plot이 안 맞을 수 있어 혼동을 피하려고
            # 이 경우만 기존처럼 정적 저장으로 안내한다(현재 화면 설정을
            # 고르면 위 애니메이션 저장이 그대로 적용됨).
            messagebox.showinfo(
                "Animate 켜짐",
                "고르신 것은 예전에 그려둔 화면이라 지금의 Animate 설정과 안 맞을 수 있어\n"
                "정적으로 저장됩니다. 애니메이션 GIF는 '현재 화면 설정'을 고른 상태에서\n"
                "저장해 주세요."
            )

        raw_title = self.filename_var.get().strip() or "CathPlot"
        next_id = self.title_counters.get(raw_title, 0) or 1
        safe_title = "".join([c for c in raw_title if c.isalnum() or c in ("_", "-")]).strip() or "CathPlot"
        default_name = f"{safe_title}_{next_id}"

        if _animate_on and chosen_plotdef is None:
            default_name += "_anim"
            file_types = [("Animated GIF (*.gif)", "*.gif")]
            selected_path = filedialog.asksaveasfilename(initialdir=self.plot_dir, initialfile=default_name, title="Save Animation As...", filetypes=file_types, defaultextension=".gif")
            if not selected_path: return
            fmt = "GIF"
        else:
            # [수정] "이미지 sample 순서는 png, pdf, jpg, svg, emf, eps 순으로"
            file_types = [
                ("PNG Image (*.png)", "*.png"),
                ("Portable Document Format (*.pdf)", "*.pdf"),
                ("JPEG Image (*.jpg)", "*.jpg"),
                ("SVG Vector Graphic (*.svg)", "*.svg"),
                ("Enhanced Metafile (*.emf)", "*.emf"),
                ("Encapsulated PostScript (*.eps)", "*.eps"),
            ]
            selected_path = filedialog.asksaveasfilename(initialdir=self.plot_dir, initialfile=default_name, title="Save Plot As...", filetypes=file_types, defaultextension=".png")
            if not selected_path: return

            ext = os.path.splitext(selected_path)[1].lower().replace(".", "")
            fmt_map = {"pdf": "PDF", "png": "PNG", "svg": "SVG", "jpg": "JPG", "jpeg": "JPG", "emf": "EMF", "eps": "EPS"}
            fmt = fmt_map.get(ext, "PNG")

        if chosen_plotdef is None:
            # 현재 화면 설정 - PRINT와 동일하게, 선택한 방향에 맞춰 GUI의 frame
            # 값을 잠깐 덮어써서 생성한 뒤 원래 값으로 되돌린다
            import dataclasses
            _orig_auto = self.frame_auto_var.get()
            _orig_w = self.frame_width_var.get()
            _orig_h = self.frame_height_var.get()
            _orig_unit = self.frame_unit_var.get()
            if _orig_auto:
                w_cm, h_cm = self._compute_auto_frame_size_cm(for_print=False, orientation=orientation)
                w, h = float(w_cm), float(h_cm)
                unit = "cm"
            else:
                try:
                    w = float((_orig_w or "10").strip() or 10.0)
                    h = float((_orig_h or "8").strip() or 8.0)
                except ValueError:
                    w, h = 10.0, 8.0
                # [수정 - 재검토] orientation 기반 w/h 스왑 제거 - Save는
                # "페이지" 개념이 없어(캔버스=frame 그 자신) 스왑하면 Manual로
                # 지정한 x:y가 orientation 선택만으로 뒤집혀버림(왜곡). 사용자
                # 확인 후 Print와 동일하게 스왑 없이 그대로 유지하기로 함.
                unit = _orig_unit
            self.frame_auto_var.set(False)
            self.frame_width_var.set(str(w))
            self.frame_height_var.set(str(h))
            self.frame_unit_var.set(unit)
            try:
                self.execute_plot_pipeline("Batch", custom_filepath=os.path.abspath(selected_path), custom_format=fmt)
            finally:
                self.frame_auto_var.set(_orig_auto)
                self.frame_width_var.set(_orig_w)
                self.frame_height_var.set(_orig_h)
                self.frame_unit_var.set(_orig_unit)
            return

        # 캐시된(Interactive) plot을 골랐을 때 - 화면 전용이던 plotdef를 파일
        # 출력용으로 변환해서 직접 생성한다 (execute_print_dialog의 캐시-선택
        # 분기와 동일한 방식) - 선택한 용지 방향에 맞춰 W/H를 정한다
        # [수정] chosen_plotdef.frame_auto/width/height 대신 항상 현재 GUI의
        # Frame 설정을 쓴다 - 화면에는 frame 크기가 아무 영향이 없어서, 캐시된
        # plot이 들고 있는 값은 의도적으로 고른 값이 아닐 수 있기 때문("크기는
        # 항상 저장 시점의 현재 GUI 설정을 따른다"로 PRINT와 통일).
        import dataclasses
        if self.frame_auto_var.get():
            w_cm, h_cm = self._compute_auto_frame_size_cm(for_print=False, orientation=orientation)
            w, h = float(w_cm), float(h_cm)
            unit_out = "cm"
        else:
            try:
                w = float((self.frame_width_var.get() or "10").strip() or 10.0)
                h = float((self.frame_height_var.get() or "8").strip() or 8.0)
            except ValueError:
                w, h = 10.0, 8.0
            unit_out = self.frame_unit_var.get()
            # [수정 - 재검토] orientation 기반 w/h 스왑 제거 (위 두 곳과 동일한
            # 이유 - Save도 Manual 지정 x:y를 orientation과 무관하게 유지).
        save_plotdef = dataclasses.replace(
            chosen_plotdef, is_print_mode=True, frame_auto=False,
            frame_width=str(w), frame_height=str(h), frame_unit=unit_out,
        )
        try:
            save_plotdef, _font_warn = self._check_and_fix_fonts(save_plotdef)
            generator = GnuplotGenerator(self.plot_dir)
            generator.create_script(save_plotdef, os.path.abspath(selected_path), fmt=fmt.lower(),
                                     annotations=save_plotdef.annotations, arrows=save_plotdef.arrows,
                                     circles=getattr(save_plotdef, "circles", []))
        except Exception as e:
            messagebox.showerror("Save Error", f"파일 저장 중 오류가 발생했습니다:\n{e}")
            return
        _all_warn = _font_warn + generator.warnings
        if _all_warn:
            messagebox.showwarning("SAVE 경고", "\n\n".join(_all_warn))
        self.update_plot_file_list()
        messagebox.showinfo("Success", f"Saved: {os.path.basename(selected_path)}")

    def _pick_plot_to_save_dialog(self):
        """SAVE 버튼을 눌렀을 때 무엇을 + 어떤 용지 방향으로 저장할지 고르는 창
        (PRINT의 _pick_plot_to_print_dialog와 동일한 패턴).
        반환값: (choice, orientation) 튜플.
          choice: None = '현재 화면 설정'을 고름(기존 방식), False = 취소,
                  그 외 = 선택된 PlotDefinition 객체
          orientation: "portrait" 또는 "landscape" (취소 시 의미 없음)"""
        CURRENT_SCREEN_LABEL = "현재 화면 설정"
        self._cleanup_stale_plot_cache()
        names = [CURRENT_SCREEN_LABEL] + sorted(self.active_plots_cache.keys())

        result = {"choice": False, "orientation": self.orientation_var.get()}
        dlg = tk.Toplevel(self.root)
        dlg.title("저장할 Plot 선택")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="저장할 대상을 선택하세요:").pack(padx=15, pady=(15, 5))
        choice_var = tk.StringVar(value=CURRENT_SCREEN_LABEL)
        ttk.Combobox(
            dlg, textvariable=choice_var, values=names, width=35, state="readonly"
        ).pack(padx=15, pady=5)

        ttk.Label(dlg, text="용지 방향:").pack(padx=15, pady=(5, 2))
        orient_var = tk.StringVar(value=self.orientation_var.get())
        ttk.Combobox(
            dlg, textvariable=orient_var, values=["portrait", "landscape"], width=15, state="readonly"
        ).pack(padx=15, pady=5)

        def do_ok():
            picked = choice_var.get()
            result["choice"] = None if picked == CURRENT_SCREEN_LABEL else self.active_plots_cache.get(picked)
            result["orientation"] = orient_var.get()
            dlg.destroy()

        btn_row = ttk.Frame(dlg)
        btn_row.pack(pady=10)
        ttk.Button(btn_row, text="취소", command=dlg.destroy).pack(side="right", padx=5)
        ttk.Button(btn_row, text="확인", command=do_ok).pack(side="right", padx=5)

        self.root.wait_window(dlg)
        return result["choice"], result["orientation"]

    def set_active_entry(self, entry):
        self.active_entry = entry

    #def cleanup_sorted_cache(self):
    #    for cached_path in self.sorted_dat_cache.values():
    #        if os.path.exists(cached_path):
    #            try:
    #                os.remove(cached_path)
    #            except Exception:
    #                pass
    #    self.sorted_dat_cache.clear()

    def _compute_auto_frame_size_cm(self, for_print=True, orientation="portrait"):
        """Axis Frame Auto가 켜진 채로 1장짜리 PRINT/SAVE를 할 때 쓸 크기.
        [수정] 이전엔 "A4 용지 - 절대 여백"으로 페이지를 꽉 채우는 크기를 썼는데,
        그러면 종이 모양(세로로 긴 비율)에 축(x:y)이 그대로 맞춰져 심하게
        왜곡됐음("Auto size는 좌우상하 비율을 너무 많이 왜곡시킴") - 대신 항상
        기본(Default) 크기(10x8cm, frame_width/height 입력칸의 기본값과 동일)를
        그대로 쓴다.
        [수정 - 재검토] 그 다음엔 "선택한 용지 방향에 맞춰 가로/세로를 맞바꿔서"
        고쳤었는데, 이러면 orientation 선택 하나로 plot 자신의 x:y 비율이
        10:8 <-> 8:10으로 뒤집혀버려 똑같은 데이터가 방향 선택에 따라 다르게
        보이는(왜곡) 문제가 다시 생김("가로/세로는 그대로 두고 위치만
        가로세로로 두면 어떨까"라는 지적으로 재확인). 실제 인쇄 단계
        (_print_emf_and_cleanup)를 보면 EMF 자신의 rclFrame 비율은 그대로
        유지한 채 인쇄 페이지 중앙에 배치하고, 용지 방향은 DEVMODE로 페이지
        자체를 돌리는 것으로 이미 처리되고 있어(스왑이 여기서는 애초에
        불필요) - Save(파일로 직접 저장, "페이지" 개념이 없어 캔버스=frame
        가로세로 그 자체)도 사용자 확인 결과 동일하게 스왑을 없애기로 함.
        이제 orientation은 이 함수의 반환값에 영향을 주지 않는다(인쇄 페이지
        회전에만 쓰임 - 호출부 참고). 파라미터는 호출부 시그니처를 유지하기
        위해 남겨둔다. (cm, cm) 튜플의 문자열을 반환한다."""
        return "10.00", "8.00"

    @staticmethod
    def _resolve_marker_shape(shape_label, fill_on):
        """Shape 라벨(예: "Circle")과 fill 여부로부터 실제 gnuplot pointtype을 고른다."""
        hollow_pt, filled_pt = MARKER_SHAPE_MAP.get(shape_label, (None, None))
        return filled_pt if fill_on else hollow_pt

    def _get_marker_fields(self, key):
        """CurveDefinition 생성 시 공통으로 쓰는 marker 필드 3종(shape/size/max_count)을
        GUI 변수에서 읽어온다. 값이 없으면 기본(마커 없음/Auto).
        Shape는 (속빈,채운) pointtype 쌍으로 저장되어 있어, fill 여부에 맞는 쪽을 고른다."""
        shape_label = self.marker_shape_vars[key].get() if key in self.marker_shape_vars else "None"
        hollow_pt, filled_pt = MARKER_SHAPE_MAP.get(shape_label, (None, None))
        fill_on = self.marker_fill_vars[key].get() if key in self.marker_fill_vars else False
        marker_shape = filled_pt if fill_on else hollow_pt
        size_label = self.marker_size_vars[key].get() if key in self.marker_size_vars else "M"
        marker_size = MARKER_SIZE_MAP.get(size_label, 1.0)
        maxcount_str = (self.marker_maxcount_vars[key].get() if key in self.marker_maxcount_vars else "").strip()
        try:
            marker_max_count = int(maxcount_str) if maxcount_str else None
        except ValueError:
            marker_max_count = None
        return marker_shape, marker_size, marker_max_count

    def _cleanup_stale_plot_cache(self):
        """plt 파일이 삭제된 뒤에도 active_plots_cache에 남아 목록에 계속
        뜨던 문제 수정 - 실제 파일이 아직 존재하는지 확인해서, 없으면
        캐시에서도 같이 제거한다. (Multi Print/Save, 1장 PRINT 선택 목록
        양쪽에서 공통으로 사용)"""
        for stale_name in [
            name for name in list(self.active_plots_cache.keys())
            if not os.path.exists(os.path.join(self.plot_dir, f"{name}.plt"))
        ]:
            del self.active_plots_cache[stale_name]

    def _log_warning(self, message):
        """팝업을 띄우기엔 너무 사소하거나 자주 발생할 수 있는 경고를, 화면 방해
        없이 로그 파일(plot_dir/cathplot_warnings.log)에 시각과 함께 조용히
        남긴다. 필요할 때 그 파일을 열어서 확인할 수 있다."""
        try:
            os.makedirs(self.plot_dir, exist_ok=True)
            with open(self.warning_log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
        except Exception:
            pass  # 로그 기록 자체가 실패해도 무시 (앱 동작에 영향 주지 않음)

    def _warmup_gnuplot(self):
        """gnuplot의 첫 실행이 유독 느린 경우가 있어(터미널 드라이버/폰트 캐시 초기화
        비용으로 추정), 프로그램이 뜨자마자 백그라운드에서 조용히 한 번 실행해서
        미리 데워둔다. 사용자가 실제로 PLOT을 누를 즈음엔 이미 초기화가 끝나있어
        더 빠르게 반응한다. 화면에 아무것도 안 보이는 무음 백그라운드 작업이라
        실패해도 무시한다 (그냥 예열 안 된 상태로 첫 PLOT이 조금 느릴 뿐)."""
        def _run():
            try:
                from gnu_generator import _resolve_gnuplot_exe
                gnuplot_exe = _resolve_gnuplot_exe()
                warmup_out = os.path.join(self.plot_dir, f".cathplot_warmup_{uuid.uuid4().hex}.png")
                script = (
                    "set encoding utf8\n"
                    f"set terminal pngcairo size 100,100\n"
                    f"set output '{warmup_out.replace(chr(92), '/')}'\n"
                    "plot sin(x)\n"
                    "set output\n"
                )
                # [수정 - 버그] "Dat file도 안 열고 바로 X로 닫으면 '다른 gnuplot
                # 프로세스가 남아있다'는 메시지가 뜬다(체크도 없이) - Plot을 하나라도
                # 그리고 닫으면 안 뜸" - 원인 확인: subprocess.run은 예열용
                # gnuplot.exe가 완전히 끝날 때까지 이 스레드 안에서 기다리는데,
                # 그 사이(수백ms~1초 남짓)엔 tasklist에 gnuplot.exe가 실제로 잡힘.
                # 앱을 켜자마자(50ms 후) 바로 닫으면 이 예열 프로세스가 아직 안
                # 끝났을 시점과 겹쳐서, on_closing의 "남은 gnuplot 프로세스" 검사가
                # 이 예열 프로세스를(우리가 만든 걸 뻔히 알면서도) "다른 프로그램이
                # 열었을 수도 있는 알 수 없는 프로세스"로 오인해 확인창을 띄웠음
                # - Popen으로 바꿔 핸들을 self._warmup_proc에 저장해두면, on_closing이
                # 닫히기 직전에 이 핸들로 직접 종료시켜서(확인창 없이) 애초에
                # tasklist 검사 시점엔 이미 안 잡히게 한다.
                proc = subprocess.Popen(
                    [gnuplot_exe], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                    **_no_console_kwargs()
                )
                self._warmup_proc = proc
                try:
                    proc.communicate(input=script, timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                self._warmup_proc = None
                if os.path.exists(warmup_out):
                    os.remove(warmup_out)
            except Exception:
                self._warmup_proc = None

        threading.Thread(target=_run, daemon=True).start()

    def _count_running_processes(self, image_name):
        """tasklist로 특정 실행파일 이름의 프로세스가 몇 개 떠 있는지 센다.
        (taskkill /IM은 "누가 띄웠는지" 구분을 못 해서, 죽이기 전에 실제로
        몇 개나 남아있는지부터 확인하는 용도 - psutil 없이 Windows 내장
        tasklist만으로 구현)."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                **_no_console_kwargs()
            )
            lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
            # 매칭되는 프로세스가 없으면 tasklist가 "정보: ... 없습니다" 안내문 한 줄만 출력함(CSV 형식이 아님)
            return sum(1 for ln in lines if ln.startswith('"'))
        except Exception:
            return 0  # 확인 자체가 안 되면 안전하게 "없음"으로 보고 기존처럼 조용히 넘어감

    def on_closing(self):
        """GUI 창이 닫힐 때 temp_sorted 임시 폴더와 gnuplot 프로세스를 정리하고 프로그램을 종료합니다."""
        # 0. [추가 - 버그 수정] 앱을 켜자마자(예열이 끝나기 전에) 바로 닫으면,
        # 아직 실행 중인 예열용 gnuplot.exe가 곧바로 아래 "남은 gnuplot 프로세스"
        # 검사에 걸려서 "다른 프로그램일 수도 있다"는 확인창이 떴었음 - 우리가
        # 띄운 걸 정확히 아는 프로세스이므로, 검사하기 전에 먼저 조용히
        # 종료시켜서(확인 불필요) 애초에 걸리지 않게 한다.
        try:
            _wp = getattr(self, "_warmup_proc", None)
            if _wp is not None and _wp.poll() is None:
                _wp.kill()
                try:
                    _wp.wait(timeout=1.0)
                except Exception:
                    pass
        except Exception:
            pass

        # 1. 이번 세션에서 추적 중인 gnuplot(-persist) 프로세스 종료 시도
        try:
            for proc in getattr(self, "plot_processes", []):
                if proc.poll() is None:
                    try:
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, **_no_console_kwargs())
                    except Exception:
                        pass
            self.plot_processes = []
        except Exception:
            pass

        # 2. -persist로 뜬 gnuplot 창은 부모(CathPlot)와 분리되어 있어 위 방법으로 못 잡을 수 있으므로,
        #    시스템에 남은 gnuplot_qt.exe(공유 드라이버)/gnuplot.exe도 함께 정리한다.
        # [수정 - 버그] taskkill /IM은 "누가 띄웠는지" 구분 없이 이름이 같은
        # 프로세스를 전부 죽여서, 사용자가 직접 연 gnuplot 콘솔이나 다른
        # 프로그램의 gnuplot.exe까지 같이 죽이던 문제가 있었음 - 죽이기 전에
        # 먼저 몇 개나 남아있는지 세어서, 하나도 없으면(가장 흔한 경우) 조용히
        # 넘어가고, 남아있으면(이 프로그램이 놓친 창일 수도, 완전히 남의
        # 프로세스일 수도 있음을 명시) 사용자에게 물어서 종료 여부를 맡긴다.
        try:
            n_left = self._count_running_processes("gnuplot.exe") + self._count_running_processes("gnuplot_qt.exe")
            if n_left > 0:
                do_kill = messagebox.askyesno(
                    "gnuplot 프로세스 남음",
                    f"gnuplot 관련 프로세스가 {n_left}개 아직 실행 중입니다.\n"
                    "이 프로그램이 미처 못 닫은 창일 수도, 다른 프로그램이나 직접 연\n"
                    "gnuplot일 수도 있습니다(어느 쪽인지 구분이 안 됩니다).\n\n"
                    "전부 강제 종료할까요? (아니오를 누르면 그대로 두고 CathPlot만 닫습니다)"
                )
                if do_kill:
                    subprocess.run(["taskkill", "/F", "/IM", "gnuplot_qt.exe"], capture_output=True, **_no_console_kwargs())
                    subprocess.run(["taskkill", "/F", "/IM", "gnuplot.exe"], capture_output=True, **_no_console_kwargs())
        except Exception:
            pass

        try:
            temp_dir = os.path.join(self.plot_dir, "temp_sorted")
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
        except Exception:
            pass
        self.root.destroy()

    def insert_symbol_to_active(self, symbol):
        if hasattr(self, 'active_entry') and self.active_entry is not None:
            try:
                if self.active_entry.winfo_exists():
                    self.active_entry.insert(tk.INSERT, symbol)
                    self.active_entry.focus_set()
            except: pass

    def open_permanent_symbol_window(self):
        if hasattr(self, 'sym_win') and self.sym_win.winfo_exists():
            self.sym_win.attributes("-topmost", True)
            self.sym_win.lift()
            self.sym_win.focus_force()
            return

        self.sym_win = tk.Toplevel(self.root)
        self.sym_win.title("Symbols")
        self.sym_win.geometry("300x300+1000+100")
        self.sym_win.attributes("-topmost", True)

        symbols = [
            chr(176), chr(8451), chr(8457), chr(945), chr(946), chr(947), chr(948),
            chr(949), chr(950), chr(951), chr(952), chr(954), chr(955), chr(956),
            chr(958), chr(960), chr(961), chr(963), chr(964), chr(966), chr(967),
            chr(968), chr(969), chr(915), chr(916), chr(920), chr(923), chr(928),
            chr(931), chr(934), chr(936), chr(937), chr(177), chr(215), chr(247),
            chr(8804), chr(8805), chr(8800), chr(185), chr(178), chr(179), chr(8736),
            chr(8592), chr(8593), chr(8594), chr(8595), chr(216), chr(8706), chr(8711),
            chr(8747), chr(8730), chr(8733), chr(8734), chr(8721), chr(8719), chr(8720),
            chr(8745), chr(8746), chr(8869), chr(8486)
        ]

        for i, sym in enumerate(symbols):
            btn = ttk.Button(
                self.sym_win, text=sym, width=4,
                command=lambda s=sym: self.insert_symbol_to_active(s)
            )
            btn.grid(row=i // 7, column=i % 7, padx=2, pady=2)

def _check_gnuplot_installed(root):
    """gnuplot이 설치되어 있는지, 버전 5 이상인지 확인한다. 설치 위치는 PATH 등록
    여부나 설치 경로가 사람마다 다를 수 있으므로, PATH 우선 확인 후 흔한 설치
    경로들도 같이 확인한다. gnuplot을 아예 못 찾았을 때만, 또는 버전이 5 미만으로
    확실히 낮게 확인됐을 때만 경고를 띄운다 (exe는 찾았는데 --version 응답이
    느려서 확인만 실패한 경우는 정상 설치일 가능성이 높으므로 조용히 넘어간다).
    [수정] 이 확인 자체가 몇 초 걸릴 수 있는데, 예전엔 이게 끝날 때까지 앱 창이
    아예 안 뜨고 멈춰 있었음 - 이제 백그라운드 스레드에서 조용히 처리하고,
    경고가 필요한 경우에만 나중에(root.after로 메인 스레드에서) 메시지를 띄운다."""
    def _run():
        import shutil
        import re as _re

        exe = shutil.which("gnuplot") or shutil.which("wgnuplot")
        if not exe:
            for candidate in (
                r"C:\Program Files\gnuplot\bin\gnuplot.exe",
                r"C:\Program Files\gnuplot\bin\wgnuplot.exe",
                r"C:\Program Files (x86)\gnuplot\bin\gnuplot.exe",
                r"C:\Program Files (x86)\gnuplot\bin\wgnuplot.exe",
            ):
                if os.path.exists(candidate):
                    exe = candidate
                    break

        if not exe:
            root.after(0, lambda: messagebox.showwarning(
                "gnuplot 확인 필요",
                "gnuplot을 찾을 수 없습니다.\n\n"
                "CathPlot은 gnuplot 5.0 이상이 설치되어 있어야 정상 동작합니다.\n\n"
                "설치 방법:\n"
                "1. http://www.gnuplot.info 에서 Windows용 gnuplot(5.4 이상 권장)을 다운로드\n"
                "2. 설치 중 'Add application directory to your PATH environment variable'\n"
                "   옵션을 반드시 체크하세요 (꺼져 있으면 CathPlot이 gnuplot을 못 찾습니다)\n"
                "3. 설치 후 CathPlot을 다시 시작하세요\n\n"
                "이미 설치하셨는데 이 메시지가 뜬다면, gnuplot 설치 폴더의 bin 경로를\n"
                "직접 시스템 환경변수 PATH에 추가해보세요."
            ))
            return

        # exe는 찾았음 - 버전 확인은 시도만 하고, 타임아웃 등으로 실패해도 경고하지 않음
        # (백그라운드에서 도니 타임아웃을 넉넉하게 잡아도 체감 지연이 없음)
        try:
            result = subprocess.run(
                [exe, "--version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=25,
                **_no_console_kwargs()
            )
            out = (result.stdout or "") + (result.stderr or "")
            m = _re.search(r"gnuplot\s+(\d+)\.(\d+)", out, _re.IGNORECASE)
            if m and int(m.group(1)) < 5:
                ver = f"{m.group(1)}.{m.group(2)}"
                root.after(0, lambda: messagebox.showwarning(
                    "gnuplot 버전 확인",
                    f"감지된 gnuplot 버전: {ver}\n\n"
                    "CathPlot은 gnuplot 5.0 이상이 필요합니다. "
                    "http://www.gnuplot.info 에서 최신 버전(5.4 이상 권장)으로 업데이트해주세요."
                ))
        except Exception:
            pass  # 버전 확인 실패는 무시 (exe는 이미 찾았으므로 대부분 정상 설치)

    threading.Thread(target=_run, daemon=True).start()


def _format_exception(exc_type, exc_value, exc_tb):
    return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))


def _install_global_error_handlers(root):
    """--noconsole로 패키징한 exe는 콘솔 창 자체가 없어서, 지금까지 콘솔에만
    찍히던 에러/경고가 아예 안 보이게 된다 ('조용히 죽는' 상태). 메인 스레드에서
    Tkinter 콜백(버튼 클릭 등) 중 발생한 예외와, 백그라운드 스레드에서 발생한
    예외를 둘 다 Tkinter 메시지 박스로 보여주도록 전역 핸들러를 등록한다."""

    def show_error_popup(exc_type, exc_value, exc_tb):
        detail = _format_exception(exc_type, exc_value, exc_tb)
        win = tk.Toplevel(root)
        win.title("예상치 못한 오류")
        win.geometry("640x360")
        ttk.Label(
            win, text="예상치 못한 오류가 발생했습니다. 아래 내용을 참고해주세요.",
            padding=10
        ).pack(anchor="w")
        text_frame = ttk.Frame(win)
        text_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        text_box = tk.Text(text_frame, wrap="word")
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=text_box.yview)
        text_box.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text_box.pack(side="left", fill="both", expand=True)
        text_box.insert("1.0", detail)
        text_box.configure(state="disabled")
        ttk.Button(win, text="닫기", command=win.destroy).pack(pady=(0, 10))

    # 1) 메인 스레드: Tkinter 콜백(버튼 클릭 등) 중 발생한 예외
    def report_callback_exception(exc_type, exc_value, exc_tb):
        show_error_popup(exc_type, exc_value, exc_tb)

    root.report_callback_exception = report_callback_exception

    # 2) 백그라운드 스레드(threading.Thread)에서 발생한 예외 - 메인 스레드가
    # 아니므로 Tkinter 위젯을 직접 못 건드려서 root.after로 안전하게 넘긴다
    def thread_excepthook(args):
        exc_type, exc_value, exc_tb = args.exc_type, args.exc_value, args.exc_traceback
        root.after(0, lambda: show_error_popup(exc_type, exc_value, exc_tb))

    threading.excepthook = thread_excepthook


if __name__ == "__main__":
    # Windows 고해상도(DPI 스케일링 125%/150%/200% 등) 디스플레이에서 창이
    # 흐릿하게 보이거나 크기가 이상하게 나오는 문제 방지 (Win10/11 공통)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    _install_global_error_handlers(root)
    app = CathPlotGUI(root)
    _check_gnuplot_installed(root)  # 백그라운드에서 확인 - 화면은 바로 뜸
    root.mainloop()
