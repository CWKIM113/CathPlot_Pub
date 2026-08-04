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
import traceback
import time
import glob
import re
import uuid

from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import font as tkfont
from pathlib import Path

import win32con
import win32gui
import win32ui
import win32api
import win32print
import pywintypes
import pythoncom
        
from data_parser import CathenaDatParser, save_json
from gnu_generator import PlotDefinition, CurveDefinition, GnuplotGenerator

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

class CathPlotGUI:

    def __init__(self, root):
        self.root = root
        self.root.title("CathPlot V1.0(Test) by C.W.Kim @2026.08.05")
        # [수정] 노트북처럼 시스템 DPI가 다른 환경에서 초기 창이 작게 보인다는
        # 피드백으로 창 크기(아래 geometry)만 20% 키움 - 처음엔 글꼴/위젯
        # 크기까지 같이 키우는 tk scaling도 적용해봤지만, 그러면 글자가 커져서
        # 목록(DAT 파일/변수 선택 등)에 한 번에 보이는 줄 수가 줄어드는 부작용이
        # 있어 되돌림. 창만 넓어지고 글꼴/여백은 그대로 유지된다.
        # [수정] 가로는 대문자 8자 정도(-110px), 세로는 대문자 3~4자 정도(+70px)
        # 조정해달라는 피드백 반영
        self.root.geometry("1150x1030")
        self.root.tk.call('tk', 'windowingsystem')

        self.parser = CathenaDatParser()
        self.file_rows = []
        self.comment_list = []
        self.arrow_list = []

        self.selected_x_key = tk.StringVar(value="")
        self.prev_x_key = ""

        # X축 변수 재정렬용 임시파일 캐시: {(dat_file, x_output_no): 임시파일경로}
        self.sorted_dat_cache = {}

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

        self.create_widgets()
        self.root.after(10, self.update_plot_file_list)
        self.root.after(50, self._warmup_gnuplot)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        self.file_frame = ttk.LabelFrame(self.root, text="DAT Files")
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

        self.var_symbol_btn = ttk.Button(
            btn_container, text=chr(937), width=5,
            command=self.open_permanent_symbol_window
        )
        self.var_symbol_btn.pack(side="right", padx=5)

        ttk.Button(
            btn_container, text="Batch Queue", command=self.open_batch_queue_dialog
        ).pack(side="left", padx=5)
        ttk.Button(
            btn_container, text="Batch Set", command=self.open_batch_set_dialog
        ).pack(side="left", padx=5)
        ttk.Button(
            btn_container, text="Template Save", command=self.save_template
        ).pack(side="left", padx=5)
        ttk.Button(
            btn_container, text="Template Load", command=self.load_template
        ).pack(side="left", padx=5)

        self.var_frame = ttk.LabelFrame(self.root, text="Available Variables Selection")
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

        self.plot_container = ttk.LabelFrame(self.root, text="Plot Setting")
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
        self.legend_thick_var = tk.StringVar(value="1.5")  # legend box 테두리 두께
        self.legend_font_var = tk.StringVar(value="Malgun Gothic")  # Legend 전용 폰트(Comment도 같이 씀)
        self.legend_size_var = tk.StringVar(value="9")  # Legend 전용 크기(Comment도 같이 씀)

        # Legend2 (보조 legend box) - 기본은 꺼져 있음
        self.legend2_on_var = tk.BooleanVar(value=False)
        self.legend2_box_var = tk.BooleanVar(value=True)
        self.legend2_pos_var = tk.StringVar(value="right bottom")

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
        ttk.Label(self.plot_frame, text="Plot Title").grid(row=0, column=0, padx=5, pady=0, sticky="w")
        self.title_entry = ttk.Entry(self.plot_frame, textvariable=self.title_var, width=30)
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

        # --- Legend1 줄 (Plot Title 줄 우측) ---
        legend1_row = ttk.Frame(self.plot_frame)
        legend1_row.grid(row=0, column=3, columnspan=3, padx=3, pady=0, sticky="w")
        ttk.Checkbutton(legend1_row, text="Legend1 On", variable=self.legend_on_var).pack(side="left", padx=3)
        ttk.Checkbutton(legend1_row, text="Legend1 Box", variable=self.legend_box_var).pack(side="left", padx=3)
        ttk.Label(legend1_row, text="Pos1:").pack(side="left", padx=2)
        legend_pos_combo = ttk.Combobox(legend1_row, textvariable=self.legend_pos_var, values=pos_list, width=10)
        legend_pos_combo.pack(side="left", padx=2)
        _add_legend_pos_hint(legend_pos_combo)

        def _legend1_get(key):
            if key not in self.in_legend1_vars:
                self.in_legend1_vars[key] = tk.BooleanVar(value=True)
            return self.in_legend1_vars[key].get()

        def _legend1_set(key, val):
            if key not in self.in_legend1_vars:
                self.in_legend1_vars[key] = tk.BooleanVar(value=True)
            self.in_legend1_vars[key].set(val)

        legend1_curves_btn = ttk.Button(legend1_row, text="Curves", width=7)
        legend1_curves_btn.pack(side="left", padx=(3, 1))
        legend1_curves_btn.configure(
            command=lambda: self._open_curve_select_popup(
                legend1_curves_btn, "Legend1 Curves", _legend1_get, _legend1_set
            )
        )

        ttk.Label(legend1_row, text="Box Thick:").pack(side="left", padx=(3, 1))
        ttk.Combobox(legend1_row, textvariable=self.legend_thick_var, values=thick_list, width=3, state="readonly").pack(side="left", padx=2)

        marker_settings_btn = ttk.Button(legend1_row, text="Marker")
        marker_settings_btn.pack(side="left", padx=(6, 1))
        marker_settings_btn.configure(command=self._open_marker_settings_popup)

        # --- Legend2 줄 (X Axis Title 줄 우측, 보조 legend box, 기본 꺼짐) ---
        # Box Thick는 Legend1/2가 같은 값을 공유함 (따로 둘 필요 없어서 Box Thick2는 없앰)
        # 어느 curve가 Legend1/2 중 어디에 나타날지는 아래 "Available Variables Selection"
        # 표의 Leg 열(1 또는 2)에서 변수별로 고른다
        legend2_row = ttk.Frame(self.plot_frame)
        legend2_row.grid(row=1, column=3, columnspan=3, padx=3, pady=0, sticky="w")
        ttk.Checkbutton(legend2_row, text="Legend2 On", variable=self.legend2_on_var).pack(side="left", padx=3)
        ttk.Checkbutton(legend2_row, text="Legend2 Box", variable=self.legend2_box_var).pack(side="left", padx=3)
        ttk.Label(legend2_row, text="Pos2:").pack(side="left", padx=2)
        legend2_pos_combo = ttk.Combobox(legend2_row, textvariable=self.legend2_pos_var, values=pos_list, width=10)
        legend2_pos_combo.pack(side="left", padx=2)
        _add_legend_pos_hint(legend2_pos_combo)
        def _legend2_get(key):
            if key not in self.legend_group_vars:
                self.legend_group_vars[key] = tk.StringVar(value="2")
            return self.legend_group_vars[key].get() == "2"

        def _legend2_set(key, val):
            if key not in self.legend_group_vars:
                self.legend_group_vars[key] = tk.StringVar(value="2")
            self.legend_group_vars[key].set("2" if val else "1")

        legend2_curves_btn = ttk.Button(legend2_row, text="Curves", width=7)
        legend2_curves_btn.pack(side="left", padx=(3, 1))
        legend2_curves_btn.configure(
            command=lambda: self._open_curve_select_popup(
                legend2_curves_btn, "Legend2 Curves", _legend2_get, _legend2_set
            )
        )

        ttk.Label(legend2_row, text="Font:").pack(side="left", padx=(6, 1))
        legend_font_combo = ttk.Combobox(legend2_row, textvariable=self.legend_font_var, values=font_list, width=12, state="readonly")
        legend_font_combo.pack(side="left", padx=1)
        self._disable_combobox_wheel(legend_font_combo)
        legend_size_combo = ttk.Combobox(legend2_row, textvariable=self.legend_size_var, values=size_list, width=2, state="readonly")
        legend_size_combo.pack(side="left", padx=1)
        self._disable_combobox_wheel(legend_size_combo)

        # Row 1
        ttk.Label(self.plot_frame, text="X Axis Title").grid(row=1, column=0, padx=5, pady=0, sticky="w")
        self.xlabel_entry = ttk.Entry(self.plot_frame, textvariable=self.xlabel_var, width=30)
        self.xlabel_entry.grid(row=1, column=1, padx=5, pady=0, sticky="w")
        self.xlabel_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.xlabel_entry))

        x_font_frame = ttk.Frame(self.plot_frame)
        x_font_frame.grid(row=1, column=2, padx=5, pady=0, sticky="w")
        ttk.Combobox(x_font_frame, textvariable=self.xlabel_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(x_font_frame, textvariable=self.xlabel_size_var, values=size_list, width=2, state="readonly").pack(side="left", padx=2)

        # [수정] 기본값을 Auto로 변경 - 화면에서는 항상 검증된 scale=1.0 기준으로
        # 뜨게 하고, 인쇄/저장 시 특정 물리 크기가 필요할 때만 꺼서 W/H를 쓰도록 함
        self.frame_auto_var = tk.BooleanVar(value=True)
        self.frame_width_var = tk.StringVar(value="10")
        self.frame_height_var = tk.StringVar(value="8")
        self.frame_unit_var = tk.StringVar(value="cm")

        frame_size_f = ttk.Frame(self.plot_frame)
        frame_size_f.grid(row=2, column=3, columnspan=3, sticky="w", padx=3, pady=0)

        ttk.Checkbutton(
            frame_size_f, text="Axis Frame Auto", variable=self.frame_auto_var,
            command=self.toggle_frame_size_state
        ).pack(side="left", padx=5)

        ttk.Label(frame_size_f, text="W:").pack(side="left", padx=(8, 2))
        self.frame_width_entry = ttk.Entry(frame_size_f, textvariable=self.frame_width_var, width=6)
        self.frame_width_entry.pack(side="left")

        ttk.Label(frame_size_f, text="H:").pack(side="left", padx=(6, 2))
        self.frame_height_entry = ttk.Entry(frame_size_f, textvariable=self.frame_height_var, width=6)
        self.frame_height_entry.pack(side="left")

        self.frame_unit_combo = ttk.Combobox(
            frame_size_f, textvariable=self.frame_unit_var,
            values=["in", "cm"], width=4, state="readonly"
        )
        self.frame_unit_combo.pack(side="left", padx=(6, 0))
        self.toggle_frame_size_state()

        # Row 2
        ttk.Label(self.plot_frame, text="Y Left Title (Y1)").grid(row=2, column=0, padx=5, pady=0, sticky="w")
        self.ylabel_entry = ttk.Entry(self.plot_frame, textvariable=self.ylabel_var, width=30)
        self.ylabel_entry.grid(row=2, column=1, padx=5, pady=0, sticky="w")
        self.ylabel_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.ylabel_entry))

        # Row 3
        ttk.Label(self.plot_frame, text="Y Right Title (Y2)").grid(row=3, column=0, padx=5, pady=0, sticky="w")
        self.y2label_entry = ttk.Entry(self.plot_frame, textvariable=self.y2label_var, width=30)
        self.y2label_entry.grid(row=3, column=1, padx=5, pady=0, sticky="w")
        self.y2label_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.y2label_entry))

        self.filename_var = tk.StringVar(value="CathPlot")
        ttk.Label(self.plot_frame, text="Plot File Name").grid(row=3, column=3, padx=(3, 2), pady=0, sticky="w")
        self.filename_entry = ttk.Entry(self.plot_frame, textvariable=self.filename_var, width=20)
        self.filename_entry.grid(row=3, column=3, padx=(115, 5), pady=0, sticky="w")

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
        ttk.Checkbutton(x_auto_f, text="Auto X Range", variable=self.xauto_var).pack(side="left")

        x_log_f = ttk.Frame(self.plot_frame)
        x_log_f.grid(row=4, column=1, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(x_log_f, text="Log", variable=self.xlog_var).pack(side="left")
        xfmt_combo = ttk.Combobox(x_log_f, textvariable=self.xfmt_var, values=FMT_LIST, width=7, state="readonly")
        xfmt_combo.pack(side="left", padx=(2, 0))
        self._disable_combobox_wheel(xfmt_combo)

        y1_auto_f = ttk.Frame(self.plot_frame)
        y1_auto_f.grid(row=4, column=2, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(y1_auto_f, text="Auto Y1 (Left) Range", variable=self.yauto_var).pack(side="left")

        y1_log_f = ttk.Frame(self.plot_frame)
        y1_log_f.grid(row=4, column=3, sticky="w", padx=2, pady=2)
        ttk.Checkbutton(y1_log_f, text="Log", variable=self.y1log_var).pack(side="left")
        y1fmt_combo = ttk.Combobox(y1_log_f, textvariable=self.y1fmt_var, values=FMT_LIST, width=7, state="readonly")
        y1fmt_combo.pack(side="left", padx=(2, 0))
        self._disable_combobox_wheel(y1fmt_combo)

        y2_auto_f = ttk.Frame(self.plot_frame)
        y2_auto_f.grid(row=4, column=4, sticky="w", padx=2, pady=2)
        ttk.Checkbutton(y2_auto_f, text="Auto Y2 (Right) Range", variable=self.y2auto_var).pack(side="left")

        y2_log_f = ttk.Frame(self.plot_frame)
        y2_log_f.grid(row=4, column=5, sticky="w", padx=2, pady=2)
        ttk.Checkbutton(y2_log_f, text="Log", variable=self.y2log_var).pack(side="left")
        y2fmt_combo = ttk.Combobox(y2_log_f, textvariable=self.y2fmt_var, values=FMT_LIST, width=7, state="readonly")
        y2fmt_combo.pack(side="left", padx=(2, 0))
        self._disable_combobox_wheel(y2fmt_combo)

        # Row 5
        ttk.Label(self.plot_frame, text="X Min/Max").grid(row=5, column=0, sticky="w", padx=5, pady=2)
        self.xmin_var = tk.StringVar()
        self.xmax_var = tk.StringVar()
        x_limit_f = ttk.Frame(self.plot_frame)
        x_limit_f.grid(row=5, column=1, sticky="w", padx=5)
        ttk.Entry(x_limit_f, textvariable=self.xmin_var, width=9).pack(side="left")
        ttk.Label(x_limit_f, text="~").pack(side="left", padx=2)
        ttk.Entry(x_limit_f, textvariable=self.xmax_var, width=9).pack(side="left")

        ttk.Label(self.plot_frame, text="Y1 Min/Max").grid(row=5, column=2, sticky="w", padx=(5, 0), pady=0)
        self.ymin_var = tk.StringVar()
        self.ymax_var = tk.StringVar()
        y1_limit_f = ttk.Frame(self.plot_frame)
        y1_limit_f.grid(row=5, column=3, sticky="w", padx=2)
        ttk.Entry(y1_limit_f, textvariable=self.ymin_var, width=9).pack(side="left")
        ttk.Label(y1_limit_f, text="~").pack(side="left", padx=2)
        ttk.Entry(y1_limit_f, textvariable=self.ymax_var, width=9).pack(side="left")

        ttk.Label(self.plot_frame, text="Y2 Min/Max").grid(row=5, column=4, sticky="w", padx=(2, 0), pady=2)
        self.y2min_var = tk.StringVar()
        self.y2max_var = tk.StringVar()
        y2_limit_f = ttk.Frame(self.plot_frame)
        y2_limit_f.grid(row=5, column=5, sticky="w", padx=1)
        ttk.Entry(y2_limit_f, textvariable=self.y2min_var, width=9).pack(side="left")
        ttk.Label(y2_limit_f, text="~").pack(side="left", padx=2)
        ttk.Entry(y2_limit_f, textvariable=self.y2max_var, width=9).pack(side="left")

        # Row 6
        ttk.Label(self.plot_frame, text="X Tics/Minor").grid(row=6, column=0, sticky="w", padx=5, pady=2)
        self.xtics_var = tk.StringVar()
        self.mxtics_var = tk.StringVar()
        x_tick_f = ttk.Frame(self.plot_frame)
        x_tick_f.grid(row=6, column=1, sticky="w", padx=5)
        ttk.Entry(x_tick_f, textvariable=self.xtics_var, width=9).pack(side="left")
        ttk.Entry(x_tick_f, textvariable=self.mxtics_var, width=5).pack(side="left", padx=(5, 0))

        ttk.Label(self.plot_frame, text="Y Left (Y1) Tics").grid(row=6, column=2, sticky="w", padx=5, pady=2)
        self.ytics_var = tk.StringVar()
        self.mytics_var = tk.StringVar()
        y1_tick_f = ttk.Frame(self.plot_frame)
        y1_tick_f.grid(row=6, column=3, sticky="w", padx=5)
        ttk.Entry(y1_tick_f, textvariable=self.ytics_var, width=9).pack(side="left")
        ttk.Entry(y1_tick_f, textvariable=self.mytics_var, width=5).pack(side="left", padx=(5, 0))

        ttk.Label(self.plot_frame, text="Y Right (Y2) Tics").grid(row=6, column=4, sticky="w", padx=5, pady=2)
        self.y2tics_var = tk.StringVar()
        self.my2tics_var = tk.StringVar()
        y2_tick_f = ttk.Frame(self.plot_frame)
        y2_tick_f.grid(row=6, column=5, sticky="w", padx=5)
        ttk.Entry(y2_tick_f, textvariable=self.y2tics_var, width=9).pack(side="left")
        ttk.Entry(y2_tick_f, textvariable=self.my2tics_var, width=5).pack(side="left", padx=(5, 0))

        # Row 7
        self.major_grid_var = tk.BooleanVar(value=True)
        self.minor_grid_var = tk.BooleanVar(value=False)

        major_grid_f = ttk.Frame(self.plot_frame)
        major_grid_f.grid(row=7, column=0, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(
            major_grid_f, text="Major Grid", variable=self.major_grid_var,
            command=self.on_major_grid_toggled
        ).pack(side="left")

        minor_grid_f = ttk.Frame(self.plot_frame)
        minor_grid_f.grid(row=7, column=1, sticky="w", padx=5, pady=2)
        self.minor_grid_check = ttk.Checkbutton(
            minor_grid_f, text="Minor Grid", variable=self.minor_grid_var
        )
        self.minor_grid_check.pack(side="left")

        # Annotations Area
        self.anno_frame = ttk.LabelFrame(self.plot_frame, text="Multi Annotations")
        self.anno_frame.grid(row=8, column=0, columnspan=6, sticky="ew", padx=5, pady=2)

        self.c_list_frame = ttk.Frame(self.anno_frame)
        self.c_list_frame.pack(fill="x", padx=5)
        self.a_list_frame = ttk.Frame(self.anno_frame)
        self.a_list_frame.pack(fill="x", padx=5)

        self.comment_on_var = tk.BooleanVar(value=True)
        self.arrow_on_var = tk.BooleanVar(value=True)

        btn_f = ttk.Frame(self.anno_frame)
        #self.anno_btn_f = ttk.Frame(self.anno_frame)
        #btn_f = self.anno_btn_f

        btn_f.pack(fill="x", pady=0)

        comment_btn_col = ttk.Frame(btn_f)
        comment_btn_col.pack(side="left", padx=5)
        ttk.Button(comment_btn_col, text="+ Add Comment", command=self.add_comment_row).pack(side="top", anchor="w")
        ttk.Checkbutton(comment_btn_col, text="Enable Comments", variable=self.comment_on_var).pack(side="top", anchor="w")

        arrow_btn_col = ttk.Frame(btn_f)
        arrow_btn_col.pack(side="left", padx=15)
        ttk.Button(arrow_btn_col, text="+ Add Line/Arrow", command=self.add_arrow_row).pack(side="top", anchor="w")
        ttk.Checkbutton(arrow_btn_col, text="Enable Arrows", variable=self.arrow_on_var).pack(side="top", anchor="w")

        # [수정] "Comment/Arrow 입력창이 안 보임 - 항상 빈 칸이 하나씩 나오게
        # 해야 함(어차피 안 지워지는 빈 칸이니 기본으로 둠)" - 시작할 때 매번
        # "+"를 눌러 추가하지 않아도 바로 입력할 수 있게, 빈 행을 하나씩
        # 미리 만들어둔다(모두 지웠을 때도 remove_row에서 다시 하나 채워줌).
        self.add_comment_row()
        self.add_arrow_row()

        # 고급: raw gnuplot 명령어 직접 입력 (여기 적은 내용은 생성되는 .plt 파일에 그대로 삽입됨)
        self.raw_gnuplot_frame = ttk.LabelFrame(self.plot_frame, text="Advanced: Raw gnuplot commands")
        self.raw_gnuplot_frame.grid(row=9, column=0, columnspan=6, sticky="ew", padx=5, pady=2)
        self.raw_gnuplot_text = tk.Text(self.raw_gnuplot_frame, height=3, wrap="none")
        self.raw_gnuplot_text.pack(fill="x", padx=5, pady=3)

        self.button_frame = ttk.Frame(self.root)
        self.button_frame.pack(side="bottom", fill="x", padx=10, pady=4)

        ttk.Button(self.button_frame, text="PLOT", command=lambda: self.execute_plot_pipeline("Interactive")).pack(side="left")
        ttk.Button(self.button_frame, text="PRINT", command=self.execute_print_dialog).pack(side="left", padx=5)
        ttk.Button(self.button_frame, text="SAVE", command=self.execute_save_dialog).pack(side="left", padx=5)
        ttk.Button(self.button_frame, text="Close All Plots", command=self.close_all_plot_windows).pack(side="right", padx=5)
        ttk.Button(self.button_frame, text="Multi Print/Save", command=self.open_multi_plot_dialog).pack(side="left", padx=15)
        ttk.Button(self.button_frame, text="Clean Past Plots", command=self.open_delete_dialog).pack(side="right", padx=5)

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
        # 검증된 고정값을 쓰되, "가로 길이를 줄여달라"는 요청으로 1330 ->
        # 1150으로 낮춤(초기 self.root.geometry 호출과 동일한 값으로 유지).
        self.root.geometry(f"1150x{required_height}")

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
        """region_widget 위에 마우스가 있는 동안만 마우스 휠을 target_canvas 스크롤에 연결한다
        (다른 스크롤 영역끼리 휠 스크롤이 서로 간섭하지 않도록 진입/이탈 시에만 bind_all/unbind_all)"""
        def _on_mousewheel(event):
            target_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_enter(_event):
            region_widget.bind_all("<MouseWheel>", _on_mousewheel)

        def _on_leave(_event):
            region_widget.unbind_all("<MouseWheel>")

        region_widget.bind("<Enter>", _on_enter)
        region_widget.bind("<Leave>", _on_leave)

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
        dialog.title("Multi Print / Save")
        dialog.geometry("420x520")
        dialog.transient(self.root)

        ttk.Label(dialog, text="Select plots (plot 창 이름순):").pack(anchor="w", padx=10, pady=(10, 0))

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

        ttk.Label(dialog, text="Layout:").pack(anchor="w", padx=10, pady=(10, 0))
        layout_combo = ttk.Combobox(
            dialog, textvariable=self.layout_var,
            values=["Auto", "1/p", "2/p", "4/p", "6/p"], state="readonly"
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

            selected_names = [available_names[i] for i in selected_indices]
            selected_defs = [available_plots[i] for i in selected_indices]

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

                self.execute_multi_plot_pipeline(
                    selected_defs, mode, filepath, fmt
                )

                dialog.destroy()
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
        ttk.Button(btn_frame, text="Save", command=lambda: on_execute("Save")).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Print", command=lambda: on_execute("Print")).pack(side="right", padx=5)

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
            "legend_thick": self.legend_thick_var.get(),
            "legend_font": self.legend_font_var.get(), "legend_size": self.legend_size_var.get(),
            "legend2_on": self.legend2_on_var.get(),
            "legend2_box": self.legend2_box_var.get(),
            "legend2_pos": self.legend2_pos_var.get(),
            "legend2_thick": self.legend_thick_var.get(),
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

            # --- annotation(코멘트) / arrow(화살표) ---
            "comment_on": self.comment_on_var.get(),
            "arrow_on": self.arrow_on_var.get(),
            "annotations": [
                {"txt": c['txt'].get(), "x": c['x'].get(), "y": c['y'].get(), "ang": c['ang'].get()}
                for c in self.comment_list
            ],
            "arrows": [
                {"x1": a['x1'].get(), "y1": a['y1'].get(), "x2": a['x2'].get(), "y2": a['y2'].get(), "type": a['type'].get()}
                for a in self.arrow_list
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
            self.legend_thick_var.set(data.get("legend_thick", self.legend_thick_var.get()))
            self.legend_font_var.set(data.get("legend_font", self.legend_font_var.get()))
            self.legend_size_var.set(data.get("legend_size", self.legend_size_var.get()))
            self.legend2_on_var.set(data.get("legend2_on", self.legend2_on_var.get()))
            self.legend2_box_var.set(data.get("legend2_box", self.legend2_box_var.get()))
            self.legend2_pos_var.set(data.get("legend2_pos", self.legend2_pos_var.get()))
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

            # annotation/arrow: 템플릿 파일에 해당 항목이 있을 때만 기존 행을 전부 지우고
            # 저장된 내용으로 다시 생성 (없는 구버전 템플릿을 불러올 땐 기존 목록 유지)
            if "annotations" in data or "arrows" in data:
                for item in list(self.comment_list):
                    item['frame'].destroy()
                self.comment_list.clear()
                for item in list(self.arrow_list):
                    item['frame'].destroy()
                self.arrow_list.clear()

                for c in data.get("annotations", []):
                    self.add_comment_row(initial=c)
                for a in data.get("arrows", []):
                    self.add_arrow_row(initial=a)

                # 템플릿에 저장된 annotation/arrow가 하나도 없으면(빈 리스트),
                # 목록이 완전히 비지 않도록 기본 빈 줄을 하나씩 채워 넣는다.
                if not self.comment_list:
                    self.add_comment_row()
                if not self.arrow_list:
                    self.add_arrow_row()

                self.comment_on_var.set(data.get("comment_on", self.comment_on_var.get()))
                self.arrow_on_var.set(data.get("arrow_on", self.arrow_on_var.get()))

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
                target_dat_file = self.resort_dat_file(abs_path, x_output_no)
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
            legend_thick=data.get("legend_thick", "1.5"),
            legend_font=data.get("legend_font", "Malgun Gothic"), legend_size=data.get("legend_size", "9"),
            legend2_on=data.get("legend2_on", False), legend2_box=data.get("legend2_box", True),
            legend2_pos=data.get("legend2_pos", "right bottom"), legend2_thick=data.get("legend2_thick", "1.5"),
            title_font=data.get("title_font", "Malgun Gothic"), title_size=data.get("title_size", "14"),
            xlabel_font=data.get("xlabel_font", "Malgun Gothic"), xlabel_size=data.get("xlabel_size", "11"),
            ylabel_font=data.get("ylabel_font", "Malgun Gothic"), ylabel_size=data.get("ylabel_size", "11"),
            y2label_font=data.get("y2label_font", "Malgun Gothic"), y2label_size=data.get("y2label_size", "11"),
            frame_auto=data.get("frame_auto", True), frame_width=data.get("frame_width", ""),
            frame_height=data.get("frame_height", ""), frame_unit=data.get("frame_unit", "in"),
            curves=curves,
            annotations=(
                [{"text": c["txt"], "x": c["x"], "y": c["y"], "angle": c["ang"]} for c in data.get("annotations", [])]
                if data.get("comment_on", True) else []
            ),
            arrows=(
                [{"x1": a["x1"], "y1": a["y1"], "x2": a["x2"], "y2": a["y2"],
                  "head": head_label_map.get(a["type"], "Forward")} for a in data.get("arrows", [])]
                if data.get("arrow_on", True) else []
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
        dlg.geometry("640x440")

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

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=10, pady=5)
        ttk.Button(btn_row, text="+ Add Templates...", command=add_files).pack(side="left", padx=5)
        ttk.Button(btn_row, text="Remove Selected", command=remove_selected).pack(side="left", padx=5)
        ttk.Button(btn_row, text="▲", width=3, command=lambda: move(-1)).pack(side="left", padx=2)
        ttk.Button(btn_row, text="▼", width=3, command=lambda: move(1)).pack(side="left", padx=2)

        ttk.Label(btn_row, text="Format:").pack(side="left", padx=(20, 2))
        # [수정] "Word 등에 이미지로 넣으려면 pdf는 안 되고, 가볍고 품질 좋은
        # png가 default여야 함" - 기본 포맷을 png로 변경, jpg 추가, 순서를
        # png/pdf/jpg/svg/emf/eps로 통일.
        fmt_var = tk.StringVar(value="png")
        ttk.Combobox(
            btn_row, textvariable=fmt_var, values=["png", "pdf", "jpg", "svg", "emf", "eps"],
            width=6, state="readonly"
        ).pack(side="left")

        def run_batch_set():
            if not queue_list:
                messagebox.showwarning("Batch Set", "먼저 Template 파일을 추가하세요.")
                return
            dlg.destroy()
            self._run_batch_set_async(list(queue_list), fmt_var.get())

        run_row = ttk.Frame(dlg)
        run_row.pack(fill="x", padx=10, pady=10)
        ttk.Button(run_row, text="취소", command=dlg.destroy).pack(side="right", padx=5)
        ttk.Button(run_row, text="Run Batch Set", command=run_batch_set).pack(side="right", padx=5)

    def _run_batch_set(self, template_paths, fmt, progress_callback=None):
        """template_paths(각각 완전한 plot 사양이 담긴 *.json)를 순서대로 읽어서
        이미지로 저장한다. self.xxx_var.get() 같은 Tkinter 접근을 안 하므로
        백그라운드 스레드에서 호출해도 안전함."""
        import json

        saved_count = 0
        errors = []
        warnings = []
        total = len(template_paths)

        for done_idx, tpath in enumerate(template_paths, start=1):
            tname = os.path.basename(tpath)
            if progress_callback:
                progress_callback(done_idx - 1, total, tname)

            try:
                with open(tpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                errors.append(f"{tname}: 템플릿 읽기 실패 ({e})")
                continue

            try:
                plotdef = self._build_plotdef_from_template_data(data)
            except Exception as e:
                errors.append(f"{tname}: {e}")
                continue

            raw_name = (data.get("filename") or "").strip() or os.path.splitext(tname)[0]
            safe_name = "".join(c for c in raw_name if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"
            outfile = os.path.join(self.plot_dir, f"{safe_name}_batchset.{fmt}")

            try:
                plotdef, font_warn = self._check_and_fix_fonts(plotdef)
                generator = GnuplotGenerator(self.plot_dir)
                generator.create_script(plotdef, outfile, fmt=fmt,
                                         annotations=plotdef.annotations, arrows=plotdef.arrows)
                saved_count += 1
                for w in font_warn + generator.warnings:
                    warnings.append(f"{tname}: {w}")
            except Exception as e:
                errors.append(f"{tname}: 저장 실패 ({e})")

        if progress_callback:
            progress_callback(total, total, "완료")

        msg = f"{saved_count}개 Template 처리 완료. (plot_dir: {self.plot_dir})"
        if errors:
            msg += "\n\n오류:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n... 외 {len(errors) - 10}개"
        log_path = self._log_batch_warnings(warnings)
        if log_path:
            msg += f"\n\n경고 {len(warnings)}건이 로그에 기록되었습니다: {log_path}"
        self.root.after(0, lambda m=msg: messagebox.showinfo("Batch Set", m))

    def _run_batch_set_async(self, template_paths, fmt):
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

        def worker():
            self._run_batch_set(template_paths, fmt, progress_callback=progress_callback)
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
            ttk.Checkbutton(fill_cell, variable=self.marker_fill_vars[key]).pack(side="left")

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

                ttk.Checkbutton(list_frame, text=label, variable=check_var, command=_toggle).pack(anchor="w", pady=1)

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
            "legend_thick": self.legend_thick_var.get(),
            "legend_font": self.legend_font_var.get(), "legend_size": self.legend_size_var.get(),
            "legend2_on": self.legend2_on_var.get(), "legend2_box": self.legend2_box_var.get(),
            "legend2_pos": self.legend2_pos_var.get(), "legend2_thick": self.legend_thick_var.get(),
            "title_font": self.title_font_var.get(), "title_size": self.title_size_var.get(),
            "xlabel_font": self.xlabel_font_var.get(), "xlabel_size": self.xlabel_size_var.get(),
            "ylabel_font": self.ylabel_font_var.get(), "ylabel_size": self.ylabel_size_var.get(),
            "y2label_font": self.y2label_font_var.get(), "y2label_size": self.y2label_size_var.get(),
            "frame_auto": self.frame_auto_var.get(), "frame_width": self.frame_width_var.get(),
            "frame_height": self.frame_height_var.get(), "frame_unit": self.frame_unit_var.get(),
            "extra_gnuplot": self.raw_gnuplot_text.get("1.0", "end-1c"),
        }

    def _run_batch_queue(self, relative_paths, fmt, settings, progress_callback=None):
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

        for done_idx, rel_path in enumerate(relative_paths, start=1):
            if progress_callback:
                progress_callback(done_idx - 1, total, rel_path)

            abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(self.cwd, rel_path)
            if not os.path.exists(abs_path):
                errors.append(f"{rel_path}: 파일 없음")
                continue

            try:
                dat_info = self.parser.parse(abs_path)
            except Exception as e:
                errors.append(f"{rel_path}: 파싱 실패 ({e})")
                continue

            target_dat_file = abs_path
            try:
                target_dat_file = self.resort_dat_file(abs_path, x_output_no)
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
                errors.append(f"{rel_path}: 매칭되는 var_no가 이 파일에 없음")
                continue

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
                legend_thick=settings.get("legend_thick", "1.5"),
                legend_font=settings.get("legend_font", "Malgun Gothic"), legend_size=settings.get("legend_size", "9"),
                legend2_on=settings.get("legend2_on", False), legend2_box=settings.get("legend2_box", True),
                legend2_pos=settings.get("legend2_pos", "right bottom"),
                legend2_thick=settings.get("legend2_thick", "1.5"),
                title_font=settings["title_font"], title_size=settings["title_size"],
                xlabel_font=settings["xlabel_font"], xlabel_size=settings["xlabel_size"],
                ylabel_font=settings["ylabel_font"], ylabel_size=settings["ylabel_size"],
                y2label_font=settings["y2label_font"], y2label_size=settings["y2label_size"],
                frame_auto=settings["frame_auto"], frame_width=settings["frame_width"],
                frame_height=settings["frame_height"], frame_unit=settings["frame_unit"],
                curves=curves,
                annotations=[],  # Batch Queue에서는 annotation/arrow 리셋
                arrows=[],
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
                saved_count += 1
                for w in font_warn + generator.warnings:
                    warnings.append(f"{rel_path}: {w}")
            except Exception as e:
                errors.append(f"{rel_path}: 저장 실패 ({e})")

        if progress_callback:
            progress_callback(total, total, "완료")

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
        ttk.Button(
            row, text="Browse",
            command=lambda v=var, r_info=info: self.load_dat_file(v, r_info)
        ).pack(side="left")

        ttk.Button(
            row, text="X", width=2,
            command=lambda r_info=info: self.delete_dat_file_row(r_info)
        ).pack(side="left", padx=3)

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

        for d in (
            self.legend_vars,
            self.selected_y1_vars,
            self.selected_y2_vars,
        ):
            for key in list(d.keys()):
                if key.startswith(prefix):
                    del d[key]
        self.file_xshift_vars.pop(datfile, None)

        if r_info["x_var"].get().startswith(prefix):
            r_info["x_var"].set("")

        self.update_title_from_first_file()
        self.show_variables()

    def update_title_from_first_file(self):
        valid_files = [info for info in self.file_rows if info["filename"] and info["meta"]]
        if valid_files:
            first_filename = valid_files[0]["filename"]
            base_name = os.path.splitext(os.path.basename(first_filename))[0]
            self.title_var.set(base_name)
            self.filename_var.set(base_name)
        else:
            self.title_var.set("CathPlot")
            self.filename_var.set("CathPlot")

    def add_comment_row(self, initial=None):
        init = initial or {}
        row = ttk.Frame(self.c_list_frame)
        row.pack(fill="x", pady=2)

        data = {
            'txt': tk.StringVar(value=init.get('txt', "")),
            'x': tk.StringVar(value=init.get('x', "")),
            'y': tk.StringVar(value=init.get('y', "")),
            'ang': tk.StringVar(value=init.get('ang', "0")),
            'frame': row,
        }
        self.comment_list.append(data)

        ttk.Button(row, text="X", width=3, command=lambda: self.remove_row(self.comment_list, row)).pack(side="right", padx=5)

        ttk.Label(row, text="[Comment]", foreground="blue").pack(side="left", padx=(0, 5))
        ttk.Label(row, text="Txt:").pack(side="left")
        ttk.Entry(row, textvariable=data['txt'], width=20).pack(side="left", padx=2)
        ttk.Label(row, text="X(0~100%):").pack(side="left")
        ttk.Entry(row, textvariable=data['x'], width=6).pack(side="left", padx=2)
        ttk.Label(row, text="Y(0~100%):").pack(side="left")
        ttk.Entry(row, textvariable=data['y'], width=6).pack(side="left", padx=2)
        ttk.Label(row, text="Angle(0~360°):").pack(side="left")
        ttk.Entry(row, textvariable=data['ang'], width=6).pack(side="left", padx=2)

    ARROW_HEAD_DISPLAY_MAP = {
        "No Head": "nohead",
        "ForwHead": "head",
        "BackHead": "backhead",
        "Both Heads": "heads",
    }

    def add_arrow_row(self, initial=None):
        init = initial or {}
        row = ttk.Frame(self.a_list_frame)
        row.pack(fill="x", pady=2)

        saved_type = init.get('type', "head")
        data = {'x1': tk.StringVar(value=init.get('x1', "")), 'y1': tk.StringVar(value=init.get('y1', "")),
                'x2': tk.StringVar(value=init.get('x2', "")), 'y2': tk.StringVar(value=init.get('y2', "")),
                'type': tk.StringVar(value=saved_type), 'frame': row}
        self.arrow_list.append(data)

        ttk.Button(row, text="X", width=3, command=lambda: self.remove_row(self.arrow_list, row)).pack(side="right", padx=5)

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

        ttk.Label(row, text="X1(0~100%):").pack(side="left")
        ttk.Entry(row, textvariable=data['x1'], width=5).pack(side="left", padx=1)
        ttk.Label(row, text="Y1(0~100%):").pack(side="left")
        ttk.Entry(row, textvariable=data['y1'], width=5).pack(side="left", padx=1)
        ttk.Label(row, text="→ X2(0~100%):").pack(side="left")
        ttk.Entry(row, textvariable=data['x2'], width=5).pack(side="left", padx=1)
        ttk.Label(row, text="Y2(0~100%):").pack(side="left")
        ttk.Entry(row, textvariable=data['y2'], width=5).pack(side="left", padx=1)

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

        # [추가] Comment/Arrow를 전부 지워서 목록이 완전히 비면, 빈 공간 대신
        # 처음 화면처럼 빈 줄 하나를 다시 채워 넣는다.
        if not target_list:
            if target_list is self.comment_list:
                self.add_comment_row()
            elif target_list is self.arrow_list:
                self.add_arrow_row()

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
            frame = ttk.LabelFrame(container, text=os.path.basename(datfile))

            frame.grid(row=valid_file_count // 3, column=valid_file_count % 3, sticky="nw", padx=2, pady=2)
            valid_file_count += 1

            header_f = ttk.Frame(frame)
            header_f.pack(fill="x", padx=2)
            ttk.Label(header_f, text="No.  Variable", font=("Arial", 9, "bold"), width=24).pack(side="left")

            ttk.Label(header_f, text="X", width=2, font=("Consolas",10,"bold")).pack(side="left")
            ttk.Label(header_f, text="Y1", width=3, font=("Consolas",10,"bold")).pack(side="left")
            ttk.Label(header_f, text="Y2", width=3, font=("Consolas",10,"bold")).pack(side="left")
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

                r_x = ttk.Radiobutton(row_frame, value=key_str, variable=file_x_var, command=make_x_cmd(key_str, file_x_var))
                # 이미 선택된 라디오버튼을 다시 클릭했을 때 해제되도록 마우스 이벤트 가로채기
                r_x.bind("<Button-1>", on_x_radio_click)

                c_y1 = ttk.Checkbutton(row_frame, variable=self.selected_y1_vars[key_str], command=make_y_excl_cmd(key_str, "Y1", file_x_var))
                c_y2 = ttk.Checkbutton(row_frame, variable=self.selected_y2_vars[key_str], command=make_y_excl_cmd(key_str, "Y2", file_x_var))

                r_x.pack(side="left", padx=0)
                c_y1.pack(side="left", padx=0)
                c_y2.pack(side="left", padx=0)

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

    def clear_all_plots(self):
        """전체 초기화 루틴"""
        self.clean_past_plots()

        # 전체 삭제 확인 후 완전 초기화 진행
        if not messagebox.askyesno("Confirm", "Clear all plots from history and reset window naming?"):
            return

        try:
            import glob
            # 1. 실제 하드디스크의 이전 생성 플롯 파일 일괄 제거 (*.plt, *.gnu 등)
            patterns = [
                os.path.join(self.plot_dir, "*.plt"),
                os.path.join(self.plot_dir, "*.gnu"),
            #    os.path.join(self.plot_dir, "*_Temp*.*")
            ]
            for pattern in patterns:
                for filepath in glob.glob(pattern):
                    if os.path.exists(filepath):
                        try: os.remove(filepath)
                        except: pass

            # 2. [핵심] 동일 이름 중복 현상을 방지하기 위해 네이밍 일련번호 카운터 완전 리셋
            if hasattr(self, 'title_counters'):
                self.title_counters.clear()

            # 3. 메모리 상의 세션 캐시 및 히스토리 리스트 완전 리셋
            if hasattr(self, 'history_plots'):
                self.history_plots.clear()
            if hasattr(self, 'active_plots_cache'):
                self.active_plots_cache.clear()
            if hasattr(self, 'plot_processes'):
                # 혹시 백그라운드에 살아있는 프로세스가 있다면 종료 유도
                for p in self.plot_processes:
                    try: p.terminate()
                    except: pass
                self.plot_processes.clear()

            # 4. GUI 화면 갱신
            self.update_plot_file_list()
            messagebox.showinfo("Success", "All plots cleared and naming IDs have been reset.")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to clear all plots: {e}")

    def reset_history(self):  # 혹은 파일 내 clear_history_list 등 매핑된 이름 유지
        if not messagebox.askyesno("Confirm", "Clear all plots from history?"):
            return

        # [핵심 보정] 기존 창 이름 번호(일련번호)가 꼬이지 않도록 완전히 비움
        if hasattr(self, 'title_counters'):
            self.title_counters.clear()

        # 기존 메모리 리스트 초기화 유지
        if hasattr(self, 'history_plots'):
            self.history_plots.clear()

        self.update_plot_file_list()
        messagebox.showinfo("Success", "History and plot naming counters have been reset.")

    def _collect_annotations(self):
        if not self.comment_on_var.get():
            return []
        annotations = []
        for item in self.comment_list:
            text = item['txt'].get().strip()
            x = item['x'].get().strip()
            y = item['y'].get().strip()
            angle = item['ang'].get().strip() or "0"
            if text and x and y:
                annotations.append({"text": text, "x": x, "y": y, "angle": angle})
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
            arrows.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "head": head})
        return arrows

    def get_temp_dir(self):
        temp_dir = os.path.join(self.cwd, "temp_sorted")
        os.makedirs(temp_dir, exist_ok=True)
        return temp_dir

    def resort_dat_file(self, dat_file, x_col):
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
        """
        if not os.path.exists(dat_file):
            return dat_file

        try:
            if not hasattr(self, 'plot_dir') or not self.plot_dir:
                self.plot_dir = os.path.join(os.path.dirname(os.path.abspath(dat_file)), "plot")

            temp_dir = os.path.join(self.plot_dir, "temp_sorted")
            os.makedirs(temp_dir, exist_ok=True)

            base_name = os.path.basename(dat_file)
            name_root, ext = os.path.splitext(base_name)
            sorted_filename = f"{name_root}_sortedX{x_col}{ext}"
            sorted_filepath = os.path.join(temp_dir, sorted_filename)

            if os.path.exists(sorted_filepath):
                return sorted_filepath

            # 파서로 Cathena/Generic 여부와 무관하게 데이터 시작 줄과 변수명을 동일한 방식으로 판단
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
            if name and name.lower() not in installed:
                fallback = self._pick_fallback_font(installed, sample_text)
                changes[field] = fallback
                key = (name, field)
                if key not in reported:
                    warnings.append(f"'{name}' 폰트를 찾을 수 없어 '{fallback}'(으)로 대체했습니다. ({label})")
                    reported.add(key)

        if changes:
            plotdef = dataclasses.replace(plotdef, **changes)
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
            # Axis Frame Auto가 켜진 채로 파일 출력(Batch/PRINT)하는 경우, 포맷마다
            # 서로 다른 임의의 기본값을 쓰는 대신 Multi-Print의 1/p Auto와 동일한
            # 방식(A4 용지 - 절대 여백)으로 계산해서 일관되게 적용한다. 화면에 그냥
            # 띄우는 Interactive는 해당 없음(용지 개념이 없으므로 그대로 둠).
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
                legend_thick=self.legend_thick_var.get(),
                legend_font=self.legend_font_var.get(), legend_size=self.legend_size_var.get(),
                legend2_on=self.legend2_on_var.get(),
                legend2_box=self.legend2_box_var.get(),
                legend2_pos=self.legend2_pos_var.get(),
                legend2_thick=self.legend_thick_var.get(),
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
            generator.create_script(
                plotdef, outfile, fmt=fmt,
                annotations=plotdef.annotations, arrows=plotdef.arrows
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
            self.execute_multi_plot_pipeline(selected_defs, mode, filepath, fmt)

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
            if mode == "Save":
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
        if layout_opt == "Auto":
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
            for_print=(mode != "Save"),
        )

        if generator.last_size_warning:
            messagebox.showwarning("Plot 크기 자동 조정", generator.last_size_warning)

        _all_warn = _font_warn + generator.warnings
        if _all_warn:
            messagebox.showwarning("Multi Print/Save 경고", "\n\n".join(_all_warn))

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
                    is_landscape_shape = w >= h
                    wants_landscape = (orientation == "landscape")
                    if is_landscape_shape != wants_landscape:
                        w, h = h, w
                return dataclasses.replace(pd, frame_auto=False, frame_width=str(w), frame_height=str(h), frame_unit=unit)

            if chosen_plotdef is not None:
                print_plotdef = dataclasses.replace(chosen_plotdef, is_print_mode=True)
                print_plotdef = _apply_orientation_to_plotdef(print_plotdef, orientation)
                print_plotdef, _font_warn = self._check_and_fix_fonts(print_plotdef)
                generator = GnuplotGenerator(self.plot_dir)
                generator.create_script(print_plotdef, temp_emf, fmt="emf",
                                         annotations=print_plotdef.annotations, arrows=print_plotdef.arrows)
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
                if (w >= h) != (orientation == "landscape"):
                    w, h = h, w
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

    def _pick_printer_dialog(self):
        """설치된 프린터 목록을 직접 열거해서 자체 선택창으로 고르게 한다
        (네이티브 win32 프린트 대화상자를 대체 - 반드시 메인 스레드에서 호출해야 함).
        용지 방향은 여기서 다시 묻지 않음 - 단일 PRINT는 _pick_plot_to_print_dialog에서,
        Multi Print/Save는 자체 orientation_var에서 이미 정해져서 넘어옴 (중복 방지).
        반환값: printer_name, 취소 시 None"""
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
                        fit_aspect = fit_w / fit_h
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
        _pick_plot_to_print_dialog와 동일한 패턴)."""
        chosen_plotdef, orientation = self._pick_plot_to_save_dialog()
        if chosen_plotdef is False:
            return  # 사용자가 취소함
        # chosen_plotdef가 None이면 "현재 화면 설정"을 고른 것 - 아래 기존 방식 그대로 진행

        raw_title = self.filename_var.get().strip() or "CathPlot"
        next_id = self.title_counters.get(raw_title, 0) or 1
        safe_title = "".join([c for c in raw_title if c.isalnum() or c in ("_", "-")]).strip() or "CathPlot"
        default_name = f"{safe_title}_{next_id}"

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
                if (w >= h) != (orientation == "landscape"):
                    w, h = h, w
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
            if (w >= h) != (orientation == "landscape"):
                w, h = h, w
        save_plotdef = dataclasses.replace(
            chosen_plotdef, is_print_mode=True, frame_auto=False,
            frame_width=str(w), frame_height=str(h), frame_unit=unit_out,
        )
        try:
            save_plotdef, _font_warn = self._check_and_fix_fonts(save_plotdef)
            generator = GnuplotGenerator(self.plot_dir)
            generator.create_script(save_plotdef, os.path.abspath(selected_path), fmt=fmt.lower(),
                                     annotations=save_plotdef.annotations, arrows=save_plotdef.arrows)
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
        그대로 쓰고, 선택한 용지 방향에 맞춰 가로/세로만 맞바꿔서 비율을
        유지한다. (cm, cm) 튜플의 문자열을 반환한다."""
        w, h = 10.0, 8.0
        if (w >= h) != (orientation == "landscape"):
            w, h = h, w
        return f"{w:.2f}", f"{h:.2f}"

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
                subprocess.run(
                    [gnuplot_exe], input=script, text=True, capture_output=True,
                    encoding="utf-8", errors="replace",
                    timeout=20, **_no_console_kwargs()
                )
                if os.path.exists(warmup_out):
                    os.remove(warmup_out)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def on_closing(self):
        """GUI 창이 닫힐 때 temp_sorted 임시 폴더와 gnuplot 프로세스를 정리하고 프로그램을 종료합니다."""
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
        #    시스템에 남은 gnuplot_qt.exe(공유 드라이버)/gnuplot.exe도 함께 정리
        try:
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
