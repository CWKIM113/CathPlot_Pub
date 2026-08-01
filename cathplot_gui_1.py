# -*- coding: utf-8 -*-

import tkinter as tk
import os
import subprocess
import time
import glob

from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox

#import win32api
#import win32print

from cathena_parser import CathenaDatParser
from gnu_generator import PlotDefinition, CurveDefinition, GnuplotGenerator

class CathPlotGUI:

    def __init__(self, root):
        self.root = root
        self.root.title("CathPlot V1.0c - Multi Annotationb")
        self.root.geometry("1200x980")
        self.root.tk.call('tk', 'windowingsystem')

        self.parser = CathenaDatParser()
        self.file_rows = []
        self.comment_list = [] # 다중 주석 관리 리스트
        self.arrow_list = []   # 다중 화살표 관리 리스트

        self.selected_x_key = tk.StringVar(value="")
        self.prev_x_key = ""

        self.selected_y1_vars = {}
        self.selected_y2_vars = {}
        self.legend_vars = {}

        self.active_entry = None
        self.last_opened_dir = None
        self.title_counters = {}
        self.active_plots_cache = {}

        self.cwd = os.getcwd()
        self.plot_dir = os.path.join(self.cwd, "plot")
        os.makedirs(self.plot_dir, exist_ok=True)

        self.create_widgets()
        self.root.after(10, self.update_plot_file_list)

    def create_widgets(self):
        self.file_frame = ttk.LabelFrame(self.root, text="DAT Files")
        self.file_frame.pack(fill="x", padx=10, pady=0)

        self.file_canvas = tk.Canvas(self.file_frame, height=75)
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

        self.file_canvas.pack(side="left", fill="x", expand=True, padx=5, pady=0)
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

        self.var_frame = ttk.LabelFrame(self.root, text="Available Variables Selection")
        self.var_frame.pack(fill="x", expand=False, padx=10, pady=0)

        self.canvas = tk.Canvas(self.var_frame, height=220)
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

        # Plot Setting Area
        self.plot_frame = ttk.LabelFrame(self.root, text="Plot Setting")
        self.plot_frame.pack(fill="x", padx=10, pady=5)

        self.title_var = tk.StringVar(value="CathPlot")
        self.xlabel_var = tk.StringVar(value="")
        self.ylabel_var = tk.StringVar(value="")
        self.y2label_var = tk.StringVar(value="")

        self.xauto_var = tk.BooleanVar(value=True)
        self.yauto_var = tk.BooleanVar(value=True)
        self.y2auto_var = tk.BooleanVar(value=True)

        self.legend_on_var = tk.BooleanVar(value=True)
        self.legend_box_var = tk.BooleanVar(value=True)
        self.legend_pos_var = tk.StringVar(value="right top")

        self.title_font_var = tk.StringVar(value="Malgun Gothic")
        self.title_size_var = tk.StringVar(value="14")
        self.xlabel_font_var = tk.StringVar(value="Malgun Gothic")
        self.xlabel_size_var = tk.StringVar(value="11")
        self.ylabel_font_var = tk.StringVar(value="Malgun Gothic")
        self.ylabel_size_var = tk.StringVar(value="11")
        self.y2label_font_var = tk.StringVar(value="Malgun Gothic")
        self.y2label_size_var = tk.StringVar(value="11")

        font_list = ["Malgun Gothic", "Arial", "Times New Roman", "Courier New", "Consolas"]
        size_list = ["6", "8", "9", "10", "11", "12", "14", "16", "18", "20"]

        # Row 0: Title & Legend
        ttk.Label(self.plot_frame, text="Plot Title").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.title_entry = ttk.Entry(self.plot_frame, textvariable=self.title_var, width=22)
        self.title_entry.grid(row=0, column=1, padx=5, pady=2, sticky="w")
        self.title_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.title_entry))

        t_font_frame = ttk.Frame(self.plot_frame)
        t_font_frame.grid(row=0, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(t_font_frame, textvariable=self.title_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(t_font_frame, textvariable=self.title_size_var, values=size_list, width=4, state="readonly").pack(side="left", padx=2)

        legend_frame = ttk.Frame(self.plot_frame)
        legend_frame.grid(row=0, column=3, columnspan=3, padx=15, pady=2, sticky="w")
        ttk.Checkbutton(legend_frame, text="Legend On", variable=self.legend_on_var).pack(side="left", padx=5)
        ttk.Checkbutton(legend_frame, text="Legend Box", variable=self.legend_box_var).pack(side="left", padx=5)
        ttk.Label(legend_frame, text="Pos:").pack(side="left", padx=2)
        pos_list = ["right top", "right bottom", "left top", "left bottom", "center top", "center bottom", "center center", "outside right"]
        ttk.Combobox(legend_frame, textvariable=self.legend_pos_var, values=pos_list, width=14, state="readonly").pack(side="left", padx=2)

        # Row 1: X Axis
        ttk.Label(self.plot_frame, text="X Axis Title").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.xlabel_entry = ttk.Entry(self.plot_frame, textvariable=self.xlabel_var, width=22)
        self.xlabel_entry.grid(row=1, column=1, padx=5, pady=2, sticky="w")
        self.xlabel_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.xlabel_entry))

        x_font_frame = ttk.Frame(self.plot_frame)
        x_font_frame.grid(row=1, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(x_font_frame, textvariable=self.xlabel_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(x_font_frame, textvariable=self.xlabel_size_var, values=size_list, width=4, state="readonly").pack(side="left", padx=2)

        # Row 2: Y Left Axis (Y1)
        ttk.Label(self.plot_frame, text="Y Left Title (Y1)").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        self.ylabel_entry = ttk.Entry(self.plot_frame, textvariable=self.ylabel_var, width=22)
        self.ylabel_entry.grid(row=2, column=1, padx=5, pady=2, sticky="w")
        self.ylabel_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.ylabel_entry))

        y_font_frame = ttk.Frame(self.plot_frame)
        y_font_frame.grid(row=2, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(y_font_frame, textvariable=self.ylabel_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(y_font_frame, textvariable=self.ylabel_size_var, values=size_list, width=4, state="readonly").pack(side="left", padx=2)

        # Row 3: Y Right Axis (Y2)
        ttk.Label(self.plot_frame, text="Y Right Title (Y2)").grid(row=3, column=0, padx=5, pady=2, sticky="w")
        self.y2label_entry = ttk.Entry(self.plot_frame, textvariable=self.y2label_var, width=22)
        self.y2label_entry.grid(row=3, column=1, padx=5, pady=2, sticky="w")
        self.y2label_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.y2label_entry))

        y2_font_frame = ttk.Frame(self.plot_frame)
        y2_font_frame.grid(row=3, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(y2_font_frame, textvariable=self.y2label_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(y2_font_frame, textvariable=self.y2label_size_var, values=size_list, width=4, state="readonly").pack(side="left", padx=2)

        # Row 4: Auto Range Checkbuttons
        ttk.Checkbutton(self.plot_frame, text="Auto X Range", variable=self.xauto_var).grid(row=4, column=0, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(self.plot_frame, text="Auto Y Left (Y1)", variable=self.yauto_var).grid(row=4, column=1, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(self.plot_frame, text="Auto Y Right (Y2)", variable=self.y2auto_var).grid(row=4, column=2, sticky="w", padx=5, pady=2)

        # Row 5: Min / Max Limits
        ttk.Label(self.plot_frame, text="X Min/Max").grid(row=5, column=0, sticky="w", padx=5, pady=2)
        self.xmin_var = tk.StringVar()
        self.xmax_var = tk.StringVar()
        x_limit_f = ttk.Frame(self.plot_frame)
        x_limit_f.grid(row=5, column=1, sticky="w", padx=5)
        ttk.Entry(x_limit_f, textvariable=self.xmin_var, width=9).pack(side="left")
        ttk.Label(x_limit_f, text="~").pack(side="left", padx=2)
        ttk.Entry(x_limit_f, textvariable=self.xmax_var, width=9).pack(side="left")

        ttk.Label(self.plot_frame, text="Y Left (Y1) Min/Max").grid(row=5, column=2, sticky="w", padx=5, pady=2)
        self.ymin_var = tk.StringVar()
        self.ymax_var = tk.StringVar()
        y1_limit_f = ttk.Frame(self.plot_frame)
        y1_limit_f.grid(row=5, column=3, sticky="w", padx=5)
        ttk.Entry(y1_limit_f, textvariable=self.ymin_var, width=9).pack(side="left")
        ttk.Label(y1_limit_f, text="~").pack(side="left", padx=2)
        ttk.Entry(y1_limit_f, textvariable=self.ymax_var, width=9).pack(side="left")

        ttk.Label(self.plot_frame, text="Y Right (Y2) Min/Max").grid(row=5, column=4, sticky="w", padx=5, pady=2)
        self.y2min_var = tk.StringVar()
        self.y2max_var = tk.StringVar()
        y2_limit_f = ttk.Frame(self.plot_frame)
        y2_limit_f.grid(row=5, column=5, sticky="w", padx=5)
        ttk.Entry(y2_limit_f, textvariable=self.y2min_var, width=9).pack(side="left")
        ttk.Label(y2_limit_f, text="~").pack(side="left", padx=2)
        ttk.Entry(y2_limit_f, textvariable=self.y2max_var, width=9).pack(side="left")

        # Row 6: Major / Minor Ticks
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

        # Row 7: Minor Grid Option
        self.minor_grid_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.plot_frame, text="Enable Minor Grid", variable=self.minor_grid_var).grid(row=7, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # Annotations Area
        self.anno_frame = ttk.LabelFrame(self.root, text="Multi Annotations")
        self.anno_frame.pack(fill="x", padx=10, pady=5)

        # Comment & Arrow 컨테이너
        self.c_list_frame = ttk.Frame(self.anno_frame)
        self.c_list_frame.pack(fill="x", padx=5)
        self.a_list_frame = ttk.Frame(self.anno_frame)
        self.a_list_frame.pack(fill="x", padx=5)

        btn_f = ttk.Frame(self.anno_frame)
        btn_f.pack(fill="x", pady=5)
        ttk.Button(btn_f, text="+ Add Comment", command=self.add_comment_row).pack(side="left", padx=5)
        ttk.Button(btn_f, text="+ Add Line/Arrow", command=self.add_arrow_row).pack(side="left", padx=5)

        # Comment Controls
        self.comment_list = [] # 관리용 리스트
        self.comment_on_var = tk.BooleanVar(value=False)
        self.comment_text_var = tk.StringVar()
        self.comment_x_var = tk.StringVar()
        self.comment_y_var = tk.StringVar()

        c_frame = ttk.Frame(self.anno_frame)
        c_frame.pack(fill="x", padx=5, pady=2)
        ttk.Checkbutton(c_frame, text="Enable Comment", variable=self.comment_on_var).pack(side="left", padx=5)
        ttk.Label(c_frame, text="Text:").pack(side="left", padx=2)
        self.c_entry = ttk.Entry(c_frame, textvariable=self.comment_text_var, width=30)
        self.c_entry.pack(side="left", padx=5)
        self.c_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.c_entry))

        ttk.Label(c_frame, text="X:").pack(side="left", padx=2)
        ttk.Entry(c_frame, textvariable=self.comment_x_var, width=8).pack(side="left", padx=2)
        ttk.Label(c_frame, text="Y:").pack(side="left", padx=2)
        ttk.Entry(c_frame, textvariable=self.comment_y_var, width=8).pack(side="left", padx=2)

        # [요청 반영] 선 및 화살표, 각도 제어 세부 프레임 구현
        self.arrow_on_var = tk.BooleanVar(value=False)
        self.arrow_mode_var = tk.StringVar(value="coord") # coord: 좌표지정, angle: 각도지정
        self.arrow_x1_var = tk.StringVar()
        self.arrow_y1_var = tk.StringVar()
        self.arrow_x2_var = tk.StringVar()
        self.arrow_y2_var = tk.StringVar()
        self.arrow_len_var = tk.StringVar()   # 선 길이 변수
        self.arrow_ang_var = tk.StringVar()   # 선 각도 변수
        self.arrow_dir_var = tk.StringVar(value="nohead")

        a_frame = ttk.Frame(self.anno_frame)
        a_frame.pack(fill="x", padx=5, pady=2)
        ttk.Checkbutton(a_frame, text="Enable Line/Arrow", variable=self.arrow_on_var).grid(row=0, column=0, sticky="w", padx=5)

        # 입력 모드 선택 라디오 버튼
        ttk.Radiobutton(a_frame, text="좌표 기준 지정", value="coord", variable=self.arrow_mode_var, command=self.toggle_arrow_entry_state).grid(row=0, column=1, padx=5, sticky="w")
        ttk.Radiobutton(a_frame, text="각도/길이 기준 지정", value="angle", variable=self.arrow_mode_var, command=self.toggle_arrow_entry_state).grid(row=0, column=2, padx=5, sticky="w")

        # 공통 입력 및 모드별 가변 입력 셀 구성
        inputs_f = ttk.Frame(a_frame)
        inputs_f.grid(row=1, column=0, columnspan=4, sticky="ew", padx=5, pady=3)

        ttk.Label(inputs_f, text="Start X1:").pack(side="left", padx=2)
        ttk.Entry(inputs_f, textvariable=self.arrow_x1_var, width=7).pack(side="left", padx=2)
        ttk.Label(inputs_f, text="Y1:").pack(side="left", padx=2)
        ttk.Entry(inputs_f, textvariable=self.arrow_y1_var, width=7).pack(side="left", padx=2)

        # 좌표 모드용 Entry 컨테이너
        self.coord_container = ttk.Frame(inputs_f)
        self.coord_container.pack(side="left")
        ttk.Label(self.coord_container, text="  →  End X2:").pack(side="left", padx=2)
        ttk.Entry(self.coord_container, textvariable=self.arrow_x2_var, width=7).pack(side="left", padx=2)
        ttk.Label(self.coord_container, text="Y2:").pack(side="left", padx=2)
        ttk.Entry(self.coord_container, textvariable=self.arrow_y2_var, width=7).pack(side="left", padx=2)

        # 각도 모드용 Entry 컨테이너
        self.angle_container = ttk.Frame(inputs_f)
        ttk.Label(self.angle_container, text="  →  Length:").pack(side="left", padx=2)
        ttk.Entry(self.angle_container, textvariable=self.arrow_len_var, width=7).pack(side="left", padx=2)
        ttk.Label(self.angle_container, text="Angle(°):").pack(side="left", padx=2)
        ttk.Entry(self.angle_container, textvariable=self.arrow_ang_var, width=7).pack(side="left", padx=2)

        ttk.Label(inputs_f, text="   Type:").pack(side="left", padx=5)
        arrow_types = [("선 (No Arrow)", "nohead"), ("순방향 (→)", "head"), ("역방향 (←)", "backhead"), ("양방향 (↔)", "heads")]
        a_type_combo = ttk.Combobox(inputs_f, textvariable=self.arrow_dir_var, values=[t[1] for t in arrow_types], width=10, state="readonly")
        a_type_combo.pack(side="left", padx=2)

        # 세션 리스트 박스 영역 : Bottom List box & Action buttons
        list_label_frame = ttk.LabelFrame(self.root, text="Generated Plot Scripts (Current Session)")
        list_label_frame.pack(fill="both", expand=True, padx=10, pady=5)

        list_scroll = ttk.Scrollbar(list_label_frame, orient="vertical")
        self.file_listbox = tk.Listbox(list_label_frame, yscrollcommand=list_scroll.set, height=5)
        list_scroll.config(command=self.file_listbox.yview)
        list_scroll.pack(side="right", fill="y")
        self.file_listbox.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        self.button_frame = ttk.Frame(self.root)
        self.button_frame.pack(side="bottom", fill="x", padx=10, pady=10)

        ttk.Button(self.button_frame, text="PLOT", command=lambda: self.execute_plot_pipeline("Interactive")).pack(side="left")
        ttk.Button(self.button_frame, text="Print", command=self.execute_print_dialog).pack(side="left", padx=5)
        ttk.Button(self.button_frame, text="Save", command=self.execute_save_dialog).pack(side="left", padx=5)
        ttk.Button(self.button_frame, text="Clean Past Plots", command=self.clean_past_plots).pack(side="right", padx=5)

        self.add_file_row()
        self.toggle_arrow_entry_state()

    def toggle_arrow_entry_state(self):
        # 선택한 선 모드에 맞춰 불필요한 입력칸 숨김/숨김해제 스위칭
        if self.arrow_mode_var.get() == "coord":
            self.angle_container.pack_forget()
            self.coord_container.pack(side="left")
        else:
            self.coord_container.pack_forget()
            self.angle_container.pack(side="left")

    def add_file_row(self):
        var = tk.StringVar()
        tshift_var = tk.StringVar(value="0.0")

        row = ttk.Frame(self.file_scrollable_frame)
        info = {
            "frame": row, "var": var, "filename": "",
            "meta": None, "tshift_var": tshift_var
        }
        self.file_rows.append(info)
        row.pack(fill="x", padx=5, pady=0)

        ttk.Entry(row, textvariable=var, width=46).pack(side="left", padx=5)
        ttk.Button(
            row, text="Browse",
            command=lambda v=var, r_info=info: self.load_dat_file(v, r_info)
        ).pack(side="left")

        ttk.Label(row, text="Time Shift:").pack(side="left", padx=(10, 2))
        ttk.Entry(row, textvariable=tshift_var, width=8).pack(side="left")
        ttk.Label(row, text="(s)").pack(side="left", padx=(0, 5))

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

        var.set(filename)
        r_info["filename"] = filename
        r_info["meta"] = self.parser.parse(filename)

        self.update_title_from_first_file()
        self.show_variables()

    def delete_dat_file_row(self, r_info):
        if "frame" in r_info and r_info["frame"].winfo_exists():
            r_info["frame"].destroy()
        if r_info in self.file_rows:
            self.file_rows.remove(r_info)

        self.update_title_from_first_file()
        self.show_variables()

    def update_title_from_first_file(self):
        valid_files = [info for info in self.file_rows if info["filename"] and info["meta"]]
        if valid_files:
            first_filename = valid_files[0]["filename"]
            base_name = os.path.splitext(os.path.basename(first_filename))[0]
            self.title_var.set(base_name)
        else:
            self.title_var.set("CathPlot")

    #def add_comment_row(self):
    #    # 입력 필드를 동적으로 추가하는 함수
    #    row = ttk.Frame(self.anno_frame)
    #    row.pack(fill="x")
    #
    #    txt_var = tk.StringVar()
    #    x_var = tk.StringVar()
    #    y_var = tk.StringVar()
    #
    #    ttk.Entry(row, textvariable=txt_var, width=20).pack(side="left")
    #    ttk.Entry(row, textvariable=x_var, width=8).pack(side="left")
    #    ttk.Entry(row, textvariable=y_var, width=8).pack(side="left")
    #
    #    # 데이터를 리스트에 저장
    #    self.comment_list.append({'txt': txt_var, 'x': x_var, 'y': y_var})

    def add_comment_row(self):
        row = ttk.Frame(self.c_list_frame)
        row.pack(fill="x", pady=2)

        data = {'txt': tk.StringVar(), 'x': tk.StringVar(), 'y': tk.StringVar(), 'frame': row}
        self.comment_list.append(data)

        ttk.Label(row, text="Txt:").pack(side="left")
        ttk.Entry(row, textvariable=data['txt'], width=20).pack(side="left", padx=2)
        ttk.Label(row, text="X:").pack(side="left")
        ttk.Entry(row, textvariable=data['x'], width=8).pack(side="left", padx=2)
        ttk.Label(row, text="Y1:").pack(side="left")
        ttk.Entry(row, textvariable=data['y'], width=8).pack(side="left", padx=2)
        ttk.Button(row, text="X", width=3, command=lambda: self.remove_row(self.comment_list, row)).pack(side="left", padx=5)

    def add_arrow_row(self):
        row = ttk.Frame(self.a_list_frame)
        row.pack(fill="x", pady=2)

        data = {'x1': tk.StringVar(), 'y1': tk.StringVar(), 'x2': tk.StringVar(), 'y2': tk.StringVar(),
                'mode': tk.StringVar(value="coord"), 'len': tk.StringVar(), 'ang': tk.StringVar(), 'type': tk.StringVar(value="head"), 'frame': row}
        self.arrow_list.append(data)

        ttk.Entry(row, textvariable=data['x1'], width=6).pack(side="left", padx=1)
        ttk.Entry(row, textvariable=data['y1'], width=6).pack(side="left", padx=1)
        ttk.Label(row, text="→").pack(side="left")
        ttk.Entry(row, textvariable=data['x2'], width=6).pack(side="left", padx=1) # 좌표모드용
        ttk.Entry(row, textvariable=data['y2'], width=6).pack(side="left", padx=1)
        ttk.Button(row, text="X", width=3, command=lambda: self.remove_row(self.arrow_list, row)).pack(side="left", padx=5)

    def remove_row(self, target_list, frame):
        frame.destroy()
        for item in target_list:
            if item['frame'] == frame:
                target_list.remove(item)
                break

    def show_variables(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        container = ttk.Frame(self.scrollable_frame)
        container.pack(fill="both", expand=True)

        valid_file_count = 0

        for idx, info in enumerate(self.file_rows):
            if info["meta"] is None:
                continue
            datfile = info["filename"]
            meta = info["meta"]

            frame = ttk.LabelFrame(container, text=os.path.basename(datfile))
            frame.grid(row=valid_file_count // 3, column=valid_file_count % 3, sticky="nw", padx=6, pady=5)
            valid_file_count += 1

            header_f = ttk.Frame(frame)
            header_f.pack(fill="x", padx=2)
            ttk.Label(header_f, text="No.  Variable Name", font=("Arial", 9, "bold")).pack(side="left")
            ttk.Label(header_f, text="X   Y1  Y2", font=("Consolas", 10, "bold")).pack(side="right", padx=12)

            for pv in meta.variables:
                title = pv.signals[0].name if pv.signals else f"OUTPUT {pv.output_no}"
                f_base = os.path.splitext(os.path.basename(datfile))[0]

                key_str = f"{datfile}||{pv.output_no}"
                if key_str not in self.legend_vars:
                    self.legend_vars[key_str] = tk.StringVar(value=f"{f_base}:{title}")
                if key_str not in self.selected_y1_vars:
                    self.selected_y1_vars[key_str] = tk.BooleanVar(value=False)
                if key_str not in self.selected_y2_vars:
                    self.selected_y2_vars[key_str] = tk.BooleanVar(value=False)

                row_frame = ttk.Frame(frame)
                row_frame.pack(anchor="w", fill="x", padx=2, pady=1)

                ttk.Label(row_frame, text=f"{pv.output_no:2d}").pack(side="left")
                entry = ttk.Entry(row_frame, textvariable=self.legend_vars[key_str], width=20)
                entry.pack(side="left", padx=2)
                entry.bind("<FocusIn>", lambda e, ent=entry: self.set_active_entry(ent))

                control_f = ttk.Frame(row_frame)
                control_f.pack(side="right", padx=2)

                def make_x_toggle_cmd(target_key=key_str):
                    def x_toggle_handler():
                        if self.prev_x_key == target_key:
                            self.selected_x_key.set("")
                            self.prev_x_key = ""
                        else:
                            self.prev_x_key = target_key
                            self.selected_y1_vars[target_key].set(False)
                            self.selected_y2_vars[target_key].set(False)
                        self.sync_axis_labels()
                    return x_toggle_handler

                r_x = ttk.Radiobutton(control_f, value=key_str, variable=self.selected_x_key, command=make_x_toggle_cmd(key_str))
                r_x.pack(side="left", padx=3)

                def make_y_excl_cmd(target_key=key_str, clicked_axis="Y1"):
                    def y_excl_handler():
                        if clicked_axis == "Y1":
                            if self.selected_y1_vars[target_key].get():
                                self.selected_y2_vars[target_key].set(False)
                                if self.selected_x_key.get() == target_key:
                                    self.selected_x_key.set("")
                                    self.prev_x_key = ""
                        elif clicked_axis == "Y2":
                            if self.selected_y2_vars[target_key].get():
                                self.selected_y1_vars[target_key].set(False)
                                if self.selected_x_key.get() == target_key:
                                    self.selected_x_key.set("")
                                    self.prev_x_key = ""
                        self.sync_axis_labels()
                    return y_excl_handler

                c_y1 = ttk.Checkbutton(control_f, variable=self.selected_y1_vars[key_str], command=make_y_excl_cmd(key_str, "Y1"))
                c_y2 = ttk.Checkbutton(control_f, variable=self.selected_y2_vars[key_str], command=make_y_excl_cmd(key_str, "Y2"))

                c_y1.pack(side="left", padx=3)
                c_y2.pack(side="left", padx=3)

    def clear_file_selections(self, target_df):

        for k in list(self.selected_y1_vars.keys()):
            if k.startswith(target_df):
                self.selected_y1_vars[k].set(False)
                self.selected_y2_vars[k].set(False)
        if self.selected_x_key.get().startswith(target_df):
            self.selected_x_key.set("")
            self.prev_x_key = ""
        self.sync_axis_labels()

        clear_btn_f = ttk.Frame(frame)
        clear_btn_f.pack(fill="x", anchor="e", padx=5)
        ttk.Button(clear_btn_f, text="Clear All", command=clear_file_selections).pack(side="right", pady=2)

        self.scrollable_frame.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.sync_axis_labels()

    def sync_axis_labels(self):
        x_key = self.selected_x_key.get()
        if not x_key:
            self.xlabel_var.set("Time (s)")
        elif x_key in self.legend_vars:
            self.xlabel_var.set(self.legend_vars[x_key].get())

        y1_selected = [self.legend_vars[k].get() for k, v in self.selected_y1_vars.items() if v.get()]
        y2_selected = [self.legend_vars[k].get() for k, v in self.selected_y2_vars.items() if v.get()]

        if y1_selected:
            self.ylabel_var.set(", ".join(y1_selected))
        else:
            self.ylabel_var.set("")

        if y2_selected:
            self.y2label_var.set(", ".join(y2_selected))
        else:
            self.y2label_var.set("")

    def clean_past_plots(self):
        target_pattern = os.path.join(self.plot_dir, "*.gnu")
        files = glob.glob(target_pattern)
        if not files:
            messagebox.showinfo("Clean Info", "No past plot files found.")
            return
        if messagebox.askyesno("Clean Plots", f"Delete all {len(files)} script files?"):
            for f in files:
                try: os.remove(f)
                except Exception: pass
            self.active_plots_cache.clear()
            self.title_counters.clear()
            self.update_plot_file_list()

    def execute_plot_pipeline(self, mode, custom_filepath=None, custom_format=None, target_plot_def=None, layout_option=None):
        os.makedirs(self.plot_dir, exist_ok=True)

        raw_title = self.title_var.get().strip() or "CathPlot"
        if raw_title not in self.title_counters:
            self.title_counters[raw_title] = 0
        self.title_counters[raw_title] += 1
        curr_id = self.title_counters[raw_title]

        safe_title = "".join([c for c in raw_title if c.isalnum() or c in ("_", "-")]).strip() or "CathPlot"
        outfile = os.path.join(self.plot_dir, f"{safe_title}_{curr_id}.gnu" if mode == "Interactive" else f"{safe_title}_Temp_{curr_id}.gnu")

        x_key = self.selected_x_key.get()
        active_y1_keys = [k for k, v in self.selected_y1_vars.items() if v.get()]
        active_y2_keys = [k for k, v in self.selected_y2_vars.items() if v.get()]

        if not active_y1_keys and not active_y2_keys:
            messagebox.showwarning("Warning", "Please select at least one Y1 or Y2 variable.")
            return None

        script_lines = [
            "set encoding utf8\n",
            "set terminal windows size 960,540 enhanced\n" if mode == "Interactive" else f"set terminal {custom_format or 'pdf'} enhanced\n",
            f"set title '{raw_title}' font '{self.title_font_var.get()},{self.title_size_var.get()}'\n",
            f"set xlabel '{self.xlabel_var.get()}' font '{self.xlabel_font_var.get()},{self.xlabel_size_var.get()}'\n",
            f"set ylabel '{self.ylabel_var.get()}' font '{self.ylabel_font_var.get()},{self.ylabel_size_var.get()}'\n"
        ]

        if custom_filepath:
            script_lines.insert(2, f"set output '{custom_filepath.replace('\\', '/')}'\n")

        if active_y2_keys:
            script_lines.extend(["set lmargin at screen 0.11\n", "set rmargin at screen 0.88\n"])
        else:
            if "outside right" in self.legend_pos_var.get():
                script_lines.extend(["set lmargin at screen 0.10\n", "set rmargin at screen 0.75\n"])
            else:
                script_lines.extend(["set lmargin at screen 0.11\n", "set rmargin at screen 0.94\n"])

        script_lines.extend(["set tmargin at screen 0.92\n", "set bmargin at screen 0.12\n"])
        script_lines.append("set grid xtics ytics\n")
        if self.minor_grid_var.get():
            script_lines.append("set grid mxtics mytics\n")

        if not self.xauto_var.get() and self.xmin_var.get() and self.xmax_var.get():
            script_lines.append(f"set xrange [{self.xmin_var.get()}:{self.xmax_var.get()}]\n")

        if not self.yauto_var.get() and self.ymin_var.get() and self.ymax_var.get():
            script_lines.append(f"set yrange [{self.ymin_var.get()}:{self.ymax_var.get()}]\n")

        if active_y2_keys:
            script_lines.append(f"set y2label '{self.y2label_var.get()}' font '{self.y2label_font_var.get()},{self.y2label_size_var.get()}'\n")
            script_lines.append("set y2tics\n")
            if not self.y2auto_var.get() and self.y2min_var.get() and self.y2max_var.get():
                script_lines.append(f"set y2range [{self.y2min_var.get()}:{self.y2max_var.get()}]\n")
        else:
            script_lines.append("unset y2tics\n")

        if self.legend_on_var.get():
            l_pos = self.legend_pos_var.get()
            box_opt = "box" if self.legend_box_var.get() else "nobox"
            if l_pos == "center center":
                script_lines.append(
                    f"set key center center {box_opt} reverse left"
                    f"samplen 1.5 spacing 1.1\n"
                )
            elif l_pos == "outside right":
                script_lines.append(f"set key outside right center {box_opt} samplen 2 spacing 1.1\n")
            else:
                script_lines.append(f"set key {l_pos} {box_opt} samplen 2 spacing 1.1\n")
        else:
            script_lines.append("unset key\n")

        if self.comment_on_var.get() and self.comment_text_var.get().strip():
            cx = self.comment_x_var.get().strip() or "graph 0.5"
            cy = self.comment_y_var.get().strip() or "graph 0.5"
            script_lines.append(f"set label '{self.comment_text_var.get().strip()}' at {cx},{cy} center\n")
        else:
            script_lines.append("unset label\n")

        # 여러 주석을 Gnuplot 명령어로 변환
        for c in self.comment_list:
            text = c['txt'].get()
            x = c['x'].get()
            y = c['y'].get()
            if text:
                script_lines.append(f"set label '{text}' at {x},{y}\n")

        with open(outfile, 'a', encoding='utf-8') as f:
            for c in self.comment_list:
                if c['txt'].get():
                    f.write(f"set label '{c['txt'].get()}' at {c['x'].get()},{c['y'].get()} center\n")

            for a in self.arrow_list:
                # 각도 모드 계산 로직 포함
                if a['mode'].get() == "coord":
                    f.write(f"set arrow from {a['x1'].get()},{a['y1'].get()} to {a['x2'].get()},{a['y2'].get()} {a['type'].get()} lw 1.5\n")
                else:
                    f.write(f"set arrow from {a['x1'].get()},{a['y1'].get()} to ({a['x1'].get()})+({a['len'].get()})*cos(({a['ang'].get()})*pi/180.0), ({a['y1'].get()})+({a['len'].get()})*sin(({a['ang'].get()})*pi/180.0) {a['type'].get()} lw 1.5\n")

        # [요청 반영] Line / Arrow 스크립트 빌드 부분 (좌표 모드 vs 각도 모드 분기)
        if self.arrow_on_var.get():
            ax1 = self.arrow_x1_var.get().strip() or "graph 0.2"
            ay1 = self.arrow_y1_var.get().strip() or "graph 0.2"
            head_style = self.arrow_dir_var.get()

            if self.arrow_mode_var.get() == "coord":
                ax2 = self.arrow_x2_var.get().strip() or "graph 0.4"
                ay2 = self.arrow_y2_var.get().strip() or "graph 0.4"
                script_lines.append(f"set arrow from {ax1},{ay1} to {ax2},{ay2} {head_style} lw 1.5 lc rgb 'black'\n")
            else:
                # 각도 모드: gnuplot 스크립트 내부에서 삼각함수 연산 처리
                length = self.arrow_len_var.get().strip() or "10.0"
                angle = self.arrow_ang_var.get().strip() or "45.0"
                script_lines.append(f"set arrow from {ax1},{ay1} to ({ax1}) + ({length})*cos(({angle})*pi/180.0), ({ay1}) + ({length})*sin(({angle})*pi/180.0) {head_style} lw 1.5 lc rgb 'black'\n")
        else:
            script_lines.append("unset arrow\n")

        plot_commands = []

        def build_curve_string(target_key, axis_target):
            d_file, out_no = target_key.split("||")
            t_shift = "0.0"
            for info in self.file_rows:
                if info["filename"] == d_file:
                    t_shift = info["tshift_var"].get() or "0.0"
                    break

            if not x_key:
                x_val = f"(column(1)+{t_shift})"
            else:
                _, x_no = x_key.split("||")
                x_val = f"(column({x_no}))"

            y_val = f"(column({out_no}))"

            leg_text = self.legend_vars[target_key].get()

            return (
                f"'{d_file.replace('\\', '/')}' "
                f"using {x_val}:{y_val} "
                f"title '{leg_text}' "
                f"axes {axis_target} "
                f"with lines linewidth 2"
            )

        for y1k in active_y1_keys:
            plot_commands.append(build_curve_string(y1k, "x1y1"))
        for y2k in active_y2_keys:
            plot_commands.append(build_curve_string(y2k, "x1y2"))

        if plot_commands:
            script_lines.append("plot " + ", ".join(plot_commands) + "\n")

        with open(outfile, 'w', encoding='utf-8') as f:
            f.writelines(script_lines)

        try:
            abs_outfile = os.path.abspath(outfile)
            if mode == "Interactive":
                subprocess.Popen(["gnuplot", "-persist", abs_outfile], cwd=self.plot_dir)
                return abs_outfile
            else:
                res = subprocess.run(["gnuplot", abs_outfile], cwd=self.plot_dir, capture_output=True, text=True, encoding='utf-8', errors='replace')
                if res.returncode != 0: raise RuntimeError(res.stderr)
                if os.path.exists(abs_outfile):
                    try: os.remove(abs_outfile)
                    except Exception: pass
                self.update_plot_file_list()
                return custom_filepath
        except Exception as e:
            messagebox.showerror("Gnuplot Error", str(e))
            return None

    def update_plot_file_list(self):
        if not hasattr(self, 'plot_dir') or not self.plot_dir: return
        files = glob.glob(os.path.join(self.plot_dir, "*.gnu"))
        files.sort(key=os.path.getctime)
        if hasattr(self, 'file_listbox'):
            self.file_listbox.delete(0, 'end')
            for f in files: self.file_listbox.insert('end', os.path.basename(f))

    def execute_print_dialog(self):
        temp_pdf = os.path.join(self.plot_dir, "Print_Job_Temp.pdf")
        success_path = self.execute_plot_pipeline("Batch", custom_filepath=temp_pdf, custom_format="PDF")
        if success_path and os.path.exists(success_path):
            try:
                win32api.ShellExecute(0, "print", os.path.abspath(success_path), None, ".", 0)
                time.sleep(4.0)
                if os.path.exists(temp_pdf): os.remove(temp_pdf)
            except Exception as e:
                messagebox.showerror("Print Error", str(e))

    def execute_save_dialog(self):
        file_types = [("Portable Document Format (*.pdf)", "*.pdf"), ("PNG Image (*.png)", "*.png"), ("SVG Vector Graphic (*.svg)", "*.svg")]
        selected_path = filedialog.asksaveasfilename(initialdir=self.plot_dir, initialfile=self.title_var.get(), title="Save Plot As...", filetypes=file_types, defaultextension=".pdf")
        if not selected_path: return

        ext = os.path.splitext(selected_path)[1].lower().replace(".", "")
        fmt_map = {"pdf": "PDF", "png": "PNG", "svg": "SVG"}
        self.execute_plot_pipeline("Batch", custom_filepath=os.path.abspath(selected_path), custom_format=fmt_map.get(ext, "PDF"))

    def set_active_entry(self, entry):
        self.active_entry = entry

    def insert_symbol_to_active(self, symbol):
        if hasattr(self, 'active_entry') and self.active_entry is not None:
            try:
                if self.active_entry.winfo_exists():
                    self.active_entry.insert(tk.INSERT, symbol)
                    self.active_entry.focus_set()
            except Exception: pass

    def open_permanent_symbol_window(self):
        if hasattr(self, 'sym_win') and self.sym_win.winfo_exists():
            self.sym_win.lift()
            return
        self.sym_win = tk.Toplevel(self.root)
        self.sym_win.title("Symbols")

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
            btn.grid(row=i // 7, column=i % 7, padx=3, pady=3)

if __name__ == "__main__":
    root = tk.Tk()
    app = CathPlotGUI(root)
    root.mainloop()