# -*- coding: utf-8 -*-

import tkinter as tk
import os
import subprocess
import threading
import time
import glob
import re

from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox

#import win32con
#import win32gui
#import win32ui
import win32api
import pythoncom

from data_parser import CathenaDatParser
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
    "Dash-Dot": "dashdot",
    "Short Dash": "shortdash",
    "Dash-Dot-Dot": "dashdotdot",
}

COLOR_LIST = list(COLOR_MAP.keys())
STYLE_LIST = list(STYLE_MAP.keys())

class CathPlotGUI:

    def __init__(self, root):
        self.root = root
        self.root.title("CathPlot V1.0d ... By C. W. Kim @2026.07.23 ")
        self.root.geometry("1200x800")
        self.root.tk.call('tk', 'windowingsystem')

        self.parser = CathenaDatParser()
        self.file_rows = []
        self.comment_list = []
        self.arrow_list = []

        self.selected_x_key = tk.StringVar(value="")
        self.prev_x_key = ""

        self.selected_y1_vars = {}
        self.selected_y2_vars = {}
        self.legend_vars = {}
        self.xshift_vars = {}

        self.color_vars = {}
        self.linestyle_vars = {}
        self.linewidth_vars = {}

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
        os.makedirs(self.plot_dir, exist_ok=True)

        self.create_widgets()
        self.root.after(10, self.update_plot_file_list)

        # cathplot_gui.py의 __init__ 메서드 내부에 추가
        self.sorted_data_cache = {}  # 형식: {(dat_file_path, x_output_no): "임시파일경로.dat"}

        # __init__ 안쪽의 적절한 위치 (예: 맨 마지막)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        self.file_frame = ttk.LabelFrame(self.root, text="DAT Files")
        self.file_frame.pack(fill="x", padx=10, pady=0)

        self.file_canvas = tk.Canvas(self.file_frame, height=75, width=120)
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

        self.var_frame = ttk.LabelFrame(self.root, text="Available Variables Selection")
        self.var_frame.pack(fill="x", expand=False, padx=10, pady=0)

        self.canvas = tk.Canvas(self.var_frame, height=280)
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

        self.plot_canvas = tk.Canvas(self.plot_container, height=300, highlightthickness=0)
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

        self.linewidth_var = tk.StringVar(value="1.5")

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
        linewidth_list = ["0.8","1.0","1.2","1.5","2.0","2.5","3.0","4.0"]

        # Row 0
        ttk.Label(self.plot_frame, text="Plot Title").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.title_entry = ttk.Entry(self.plot_frame, textvariable=self.title_var, width=30)
        self.title_entry.grid(row=0, column=1, padx=5, pady=2, sticky="w")
        self.title_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.title_entry))

        t_font_frame = ttk.Frame(self.plot_frame)
        t_font_frame.grid(row=0, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(t_font_frame, textvariable=self.title_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(t_font_frame, textvariable=self.title_size_var, values=size_list, width=2, state="readonly").pack(side="left", padx=2)

        legend_frame = ttk.Frame(self.plot_frame)
        legend_frame.grid(row=0, column=3, columnspan=3, padx=15, pady=2, sticky="w")
        ttk.Checkbutton(legend_frame, text="Legend On", variable=self.legend_on_var).pack(side="left", padx=5)
        ttk.Checkbutton(legend_frame, text="Legend Box", variable=self.legend_box_var).pack(side="left", padx=5)
        ttk.Label(legend_frame, text="Pos:").pack(side="left", padx=2)
        pos_list = ["right top", "right bottom", "left top", "left bottom", "center top", "center bottom", "center center", "outside right"]
        ttk.Combobox(legend_frame, textvariable=self.legend_pos_var, values=pos_list, width=14, state="readonly").pack(side="left", padx=2)

        ttk.Label(legend_frame,text="Width:").pack(side="left", padx=(12,2))
        ttk.Combobox(legend_frame,textvariable=self.linewidth_var, values=linewidth_list, width=5, state="readonly").pack(side="left", padx=2)

        # Row 1
        ttk.Label(self.plot_frame, text="X Axis Title").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.xlabel_entry = ttk.Entry(self.plot_frame, textvariable=self.xlabel_var, width=30)
        self.xlabel_entry.grid(row=1, column=1, padx=5, pady=2, sticky="w")
        self.xlabel_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.xlabel_entry))

        x_font_frame = ttk.Frame(self.plot_frame)
        x_font_frame.grid(row=1, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(x_font_frame, textvariable=self.xlabel_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(x_font_frame, textvariable=self.xlabel_size_var, values=size_list, width=2, state="readonly").pack(side="left", padx=2)

        self.frame_auto_var = tk.BooleanVar(value=False)
        self.frame_width_var = tk.StringVar(value="5")
        self.frame_height_var = tk.StringVar(value="4")
        self.frame_unit_var = tk.StringVar(value="in")

        frame_size_f = ttk.Frame(self.plot_frame)
        frame_size_f.grid(row=1, column=3, columnspan=3, sticky="w", padx=15, pady=2)

        ttk.Checkbutton(
            frame_size_f, text="Frame Size Auto", variable=self.frame_auto_var,
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
            values=["in", "cm"], width=2, state="readonly"
        )
        self.frame_unit_combo.pack(side="left", padx=(6, 0))
        self.toggle_frame_size_state()

        # Row 2
        ttk.Label(self.plot_frame, text="Y Left Title (Y1)").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        self.ylabel_entry = ttk.Entry(self.plot_frame, textvariable=self.ylabel_var, width=30)
        self.ylabel_entry.grid(row=2, column=1, padx=5, pady=2, sticky="w")
        self.ylabel_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.ylabel_entry))

        y_font_frame = ttk.Frame(self.plot_frame)
        y_font_frame.grid(row=2, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(y_font_frame, textvariable=self.ylabel_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(y_font_frame, textvariable=self.ylabel_size_var, values=size_list, width=2, state="readonly").pack(side="left", padx=2)

        # Row 3
        ttk.Label(self.plot_frame, text="Y Right Title (Y2)").grid(row=3, column=0, padx=5, pady=2, sticky="w")
        self.y2label_entry = ttk.Entry(self.plot_frame, textvariable=self.y2label_var, width=30)
        self.y2label_entry.grid(row=3, column=1, padx=5, pady=2, sticky="w")
        self.y2label_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.y2label_entry))

        y2_font_frame = ttk.Frame(self.plot_frame)
        y2_font_frame.grid(row=3, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(y2_font_frame, textvariable=self.y2label_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(y2_font_frame, textvariable=self.y2label_size_var, values=size_list, width=2, state="readonly").pack(side="left", padx=2)

        self.filename_var = tk.StringVar(value="CathPlot")
        ttk.Label(self.plot_frame, text="Plot File Name").grid(row=2, column=3, padx=(20, 2), pady=2, sticky="w")
        self.filename_entry = ttk.Entry(self.plot_frame, textvariable=self.filename_var, width=20)
        self.filename_entry.grid(row=2, column=3, padx=(115, 5), pady=2, sticky="w")

        # Row 4
        ttk.Checkbutton(self.plot_frame, text="Auto X Range", variable=self.xauto_var).grid(row=4, column=0, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(self.plot_frame, text="Auto Y Left (Y1)", variable=self.yauto_var).grid(row=4, column=2, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(self.plot_frame, text="Auto Y Right (Y2)", variable=self.y2auto_var).grid(row=4, column=4, sticky="w", padx=5, pady=2)

        # Row 5
        ttk.Label(self.plot_frame, text="X Min/Max").grid(row=5, column=0, sticky="w", padx=5, pady=2)
        self.xmin_var = tk.StringVar()
        self.xmax_var = tk.StringVar()
        x_limit_f = ttk.Frame(self.plot_frame)
        x_limit_f.grid(row=5, column=1, sticky="w", padx=5)
        ttk.Entry(x_limit_f, textvariable=self.xmin_var, width=9).pack(side="left")
        ttk.Label(x_limit_f, text="~").pack(side="left", padx=2)
        ttk.Entry(x_limit_f, textvariable=self.xmax_var, width=9).pack(side="left")

        ttk.Label(self.plot_frame, text="Y Left (Y1) Min/Max").grid(row=5, column=2, sticky="w", padx=5, pady=0)
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

        grid_checks_f = ttk.Frame(self.plot_frame)
        grid_checks_f.grid(row=7, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        ttk.Checkbutton(
            grid_checks_f, text="Major Grid", variable=self.major_grid_var,
            command=self.on_major_grid_toggled
        ).pack(side="left")

        self.minor_grid_check = ttk.Checkbutton(
            grid_checks_f, text="Minor Grid", variable=self.minor_grid_var
        )
        self.minor_grid_check.pack(side="left", padx=(8, 0))

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

        self.button_frame = ttk.Frame(self.root)
        self.button_frame.pack(side="bottom", fill="x", padx=10, pady=10)

        ttk.Button(self.button_frame, text="PLOT", command=lambda: self.execute_plot_pipeline("Interactive")).pack(side="left")
        ttk.Button(self.button_frame, text="PRINT", command=self.execute_print_dialog).pack(side="left", padx=5)
        ttk.Button(self.button_frame, text="SAVE", command=self.execute_save_dialog).pack(side="left", padx=5)
        ttk.Button(self.button_frame, text="Close All Plots", command=self.close_all_plot_windows).pack(side="right", padx=5)
        ttk.Button(self.button_frame, text="Multi Print/Save...", command=self.open_multi_plot_dialog).pack(side="left", padx=15)
        ttk.Button(self.button_frame, text="Clean Past Plots", command=self.open_delete_dialog).pack(side="right", padx=5)

        self.add_file_row()

        self.ylabel_var.trace_add("write", lambda *args: self.on_y1_title_changed(*args))
        self.y2label_var.trace_add("write", lambda *args: self.on_y2_title_changed(*args))
        self.xlabel_var.trace_add("write", lambda *args: self.on_x_title_changed(*args))

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
    LAYOUT_FIXED_ORIENTATION = {
        "Auto": None,
        "1/p": None,
        "2/p": "portrait",    # 2/p만 세로 고정
        "4/p": None,
        "6/p": None,
    }
    LAYOUT_DEFAULT_ORIENTATION = {
        "Auto": "portrait",
        "1/p": "portrait",
        "2/p": "portrait",
        "4/p": "landscape",
        "6/p": "portrait",
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

        def on_layout_changed(*_):
            layout = self.layout_var.get()
            fixed = self.LAYOUT_FIXED_ORIENTATION.get(layout)
            if fixed:
                self.orientation_var.set(fixed)
                orient_combo.config(state="disabled")
            else:
                self.orientation_var.set(self.LAYOUT_DEFAULT_ORIENTATION.get(layout, "portrait"))
                orient_combo.config(state="readonly")

        layout_combo.bind("<<ComboboxSelected>>", on_layout_changed)
        on_layout_changed()

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
                file_types = [
                    ("Portable Document Format (*.pdf)", "*.pdf"),
                    ("PNG Image (*.png)", "*.png"),
                    ("SVG Vector Graphic (*.svg)", "*.svg"),
                    ("JPEG Image (*.jpg)", "*.jpg"),
                    ("Enhanced Metafile (*.emf)", "*.emf"),
                    ("Encapsulated PostScript (*.eps)", "*.eps"),
                ]
                filepath = filedialog.asksaveasfilename(
                    parent=dialog,
                    initialdir=self.plot_dir,
                    initialfile=base_name,
                    defaultextension=".pdf",
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
                    temp_pdf = os.path.join(self.plot_dir, f"MultiPlot_Print_{idx}.pdf")
                    if not os.path.exists(temp_pdf):
                        break
                    idx += 1

                dialog.destroy()

                try:
                    self.execute_multi_plot_pipeline(
                        selected_defs, "Batch", temp_pdf, "pdf"
                    )
                    if os.path.exists(temp_pdf):
                        threading.Thread(
                            target=self._print_and_cleanup, args=(temp_pdf,), daemon=True
                        ).start()
                except Exception as e:
                    messagebox.showerror("Print Error", str(e))

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", pady=15)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=15)
        ttk.Button(btn_frame, text="Save...", command=lambda: on_execute("Save")).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Print", command=lambda: on_execute("Print")).pack(side="right", padx=5)

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
                    capture_output=True, text=True
                )
                has_any = "gnuplot.exe" in check.stdout

                subprocess.run(["taskkill", "/F", "/IM", "gnuplot_qt.exe"], capture_output=True)
                subprocess.run(["taskkill", "/F", "/IM", "gnuplot.exe"], capture_output=True)
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
                        capture_output=True
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
            self.xshift_vars,
            self.color_vars,
            self.linestyle_vars,
            self.linewidth_vars,
        ):
            for key in list(d.keys()):
                if key.startswith(prefix):
                    del d[key]

        #if self.selected_x_key.get().startswith(prefix):
        #    self.selected_x_key.set("")

        # 파일별 X축 변수 초기화
        if r_info["x_var"].get().startswith(prefix):
            r_info["x_var"].set("")

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

        datfile = r_info["filename"]
        prefix = f"{datfile}||"

        for d in (
            self.legend_vars,
            self.selected_y1_vars,
            self.selected_y2_vars,
            self.xshift_vars,
        ):
            for key in list(d.keys()):
                if key.startswith(prefix):
                    del d[key]

        #if self.selected_x_key.get().startswith(prefix):
        #    self.selected_x_key.set("")
        #    self.prev_x_key = ""
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

    def add_comment_row(self):
        row = ttk.Frame(self.c_list_frame)
        row.pack(fill="x", pady=2)

        data = {'txt': tk.StringVar(), 'x': tk.StringVar(), 'y': tk.StringVar(), 'ang': tk.StringVar(value="0"), 'frame': row}
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

    def add_arrow_row(self):
        row = ttk.Frame(self.a_list_frame)
        row.pack(fill="x", pady=2)

        data = {'x1': tk.StringVar(), 'y1': tk.StringVar(), 'x2': tk.StringVar(), 'y2': tk.StringVar(),
                'type': tk.StringVar(value="head"), 'frame': row}
        self.arrow_list.append(data)

        ttk.Button(row, text="X", width=3, command=lambda: self.remove_row(self.arrow_list, row)).pack(side="right", padx=5)

        head_display_var = tk.StringVar(value="ForwHead")

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

            #f_base = os.path.splitext(os.path.basename(datfile))[0]
            file_x_var = info["x_var"]  # <-- 해당 파일 전용 X축 변수 가져오기
            frame = ttk.LabelFrame(container, text=os.path.basename(datfile))

            frame.grid(row=valid_file_count // 3, column=valid_file_count % 3, sticky="nw", padx=2, pady=2)
            valid_file_count += 1

            header_f = ttk.Frame(frame)
            header_f.pack(fill="x", padx=2)
            ttk.Label(header_f, text="No.  Variable", font=("Arial", 9, "bold"), width=24).pack(side="left")

            ttk.Label(header_f, text="X", width=2, font=("Consolas",10,"bold")).pack(side="left")
            ttk.Label(header_f, text="Y1", width=3, font=("Consolas",10,"bold")).pack(side="left")
            ttk.Label(header_f, text="Y2", width=3, font=("Consolas",10,"bold")).pack(side="left")
            ttk.Label(header_f, text="Shift", width=5, font=("Consolas",10,"bold")).pack(side="left")
            ttk.Label(header_f, text="Color", width=6, font=("Consolas",10,"bold")).pack(side="left")
            ttk.Label(header_f, text="Style", width=5, font=("Consolas",10,"bold")).pack(side="left")

            #time_key = f"{datfile}||TIME"
            #
            #if time_key not in self.color_vars:
            #    self.color_vars[time_key] = tk.StringVar(value="Auto")
            #if time_key not in self.linestyle_vars:
            #    self.linestyle_vars[time_key] = tk.StringVar(value="Auto")
            #if not self.selected_x_key.get():
            #    self.selected_x_key.set(time_key)
            #    self.prev_x_key = time_key
            #if time_key not in self.legend_vars:
            #    self.legend_vars[time_key] = tk.StringVar(value="Time")
            #if time_key not in self.xshift_vars:
            #    self.xshift_vars[time_key] = tk.StringVar(value="0.0")
            #if time_key not in self.linewidth_vars:
            #    self.linewidth_vars[time_key] = tk.DoubleVar(value=1.5)
            #
            #time_row = ttk.Frame(frame)
            #time_row.pack(anchor="w", fill="x", padx=2, pady=0)
            #
            #ttk.Label(time_row, text="0", width=3, anchor="e").pack(side="left")
            #ttk.Entry(time_row, textvariable=self.legend_vars[time_key], width=20).pack(side="left", padx=0)
            #
            #ttk.Radiobutton(
            #    time_row, variable=self.selected_x_key, value=time_key, command=self.sync_axis_labels
            #).pack(side="left", padx=0)
            #
            #ttk.Checkbutton(time_row, state="disabled").pack(side="left", padx=0)
            #ttk.Checkbutton(time_row, state="disabled").pack(side="left", padx=0)
            #
            #ttk.Entry(time_row, textvariable=self.xshift_vars[time_key], width=5).pack(side="left", padx=0)
            #ttk.Label(time_row, width=2).pack(side="left")
            #ttk.Label(time_row, width=2).pack(side="left")

            for pv in meta.variables:
                title = pv.signals[0].name if pv.signals else f"OUTPUT {pv.output_no}"
                key_str = f"{datfile}||{pv.output_no}"

                # 첫 번째 변수(No=0)가 비어있다면 이 파일의 기본 X축으로 자동 설정
                if pv.output_no == 0 and not file_x_var.get():
                    file_x_var.set(key_str)

                if key_str not in self.color_vars:
                    self.color_vars[key_str] = tk.StringVar(value="Auto")
                if key_str not in self.linestyle_vars:
                    self.linestyle_vars[key_str] = tk.StringVar(value="Auto")
                if key_str not in self.legend_vars:
                    self.legend_vars[key_str] = tk.StringVar(value=title)
                #if key_str not in self.selected_y1_vars:
                #    self.selected_y1_vars[key_str] = tk.BooleanVar(value=False)
                #if key_str not in self.selected_y2_vars:
                #    self.selected_y2_vars[key_str] = tk.BooleanVar(value=False)
                #if key_str not in self.xshift_vars:
                #    self.xshift_vars[key_str] = tk.StringVar(value="0.0")
                #if key_str not in self.linewidth_vars:
                #    self.linewidth_vars[key_str] = tk.DoubleVar(value=1.5)
                if pv.output_no == 0:
                    if key_str not in self.xshift_vars:
                        self.xshift_vars[key_str] = tk.StringVar(value="0.0")
                    if key_str not in self.linewidth_vars:
                        self.linewidth_vars[key_str] = tk.DoubleVar(value=1.5)
                else:
                    if key_str not in self.selected_y1_vars:
                        self.selected_y1_vars[key_str] = tk.BooleanVar(value=False)
                    if key_str not in self.selected_y2_vars:
                        self.selected_y2_vars[key_str] = tk.BooleanVar(value=False)
                    if key_str not in self.xshift_vars:
                        self.xshift_vars[key_str] = tk.StringVar(value="0.0")
                    if key_str not in self.linewidth_vars:
                        self.linewidth_vars[key_str] = tk.DoubleVar(value=1.5)

                row_frame = ttk.Frame(frame)
                row_frame.pack(anchor="w", fill="x", padx=0, pady=0)

                ttk.Label(row_frame, text=f"{pv.output_no:>2}", width=3, anchor="e").pack(side="left")
                entry = ttk.Entry(row_frame, textvariable=self.legend_vars[key_str], width=20)
                entry.pack(side="left", padx=(1,0))
                entry.bind("<FocusIn>", lambda e, ent=entry: self.set_active_entry(ent))

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

                #r_x = ttk.Radiobutton(row_frame, value=key_str, variable=self.selected_x_key, command=make_x_toggle_cmd(key_str))
                #
                #def make_y_excl_cmd(target_key=key_str, clicked_axis="Y1"):
                #    def y_excl_handler():
                #        if clicked_axis == "Y1":
                #            if self.selected_y1_vars[target_key].get():
                #                self.selected_y2_vars[target_key].set(False)
                #                if self.selected_x_key.get() == target_key:
                #                    self.selected_x_key.set("")
                #                    self.prev_x_key = ""
                #        elif clicked_axis == "Y2":
                #            if self.selected_y2_vars[target_key].get():
                #                self.selected_y1_vars[target_key].set(False)
                #                if self.selected_x_key.get() == target_key:
                #                    self.selected_x_key.set("")
                #                    self.prev_x_key = ""
                #        self.sync_axis_labels()
                #    return y_excl_handler
                #
                #c_y1 = ttk.Checkbutton(row_frame, variable=self.selected_y1_vars[key_str], command=make_y_excl_cmd(key_str, "Y1"))
                #c_y2 = ttk.Checkbutton(row_frame, variable=self.selected_y2_vars[key_str], command=make_y_excl_cmd(key_str, "Y2"))
                #
                #r_x.pack(side="left", padx=0)
                #c_y1.pack(side="left", padx=0)
                #c_y2.pack(side="left", padx=0)

                # 파일별 x_var를 라디오버튼에 바인딩
                r_x = ttk.Radiobutton(row_frame, value=key_str, variable=file_x_var)

                if pv.output_no == 0:
                    r_x.pack(side="left", padx=0)
                    ttk.Checkbutton(row_frame, state="disabled").pack(side="left", padx=0)
                    ttk.Checkbutton(row_frame, state="disabled").pack(side="left", padx=0)
                else:
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

                    c_y1 = ttk.Checkbutton(row_frame, variable=self.selected_y1_vars[key_str], command=make_y_excl_cmd(key_str, "Y1", file_x_var))
                    c_y2 = ttk.Checkbutton(row_frame, variable=self.selected_y2_vars[key_str], command=make_y_excl_cmd(key_str, "Y2", file_x_var))

                    r_x.pack(side="left", padx=0)
                    c_y1.pack(side="left", padx=0)
                    c_y2.pack(side="left", padx=0)

                ttk.Entry(row_frame, textvariable=self.xshift_vars[key_str], width=5).pack(side="left", padx=0)
                ttk.Combobox(row_frame, textvariable=self.color_vars[key_str], values=COLOR_LIST, width=3, state="readonly").pack(side="left", padx=(2,0))
                ttk.Combobox(row_frame, textvariable=self.linestyle_vars[key_str], values=STYLE_LIST, width=3, state="readonly").pack(side="left", padx=(2,0))

            clear_btn_f = ttk.Frame(frame)
            clear_btn_f.pack(fill="x", anchor="e", padx=5)
            ttk.Button(clear_btn_f, text="Clear All", command=lambda tf=datfile: self.clear_file_selections(tf)).pack(side="right", pady=2)

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
        x_key = self.selected_x_key.get()
        if self.x_title_auto and x_key in self.legend_vars:
            self._updating_x = True
            self.xlabel_var.set(self.legend_vars[x_key].get())
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
        self._sorted_dat_cache.clear()

        # 1. 처음 한 번만 삭제 확인 박스를 띄웁니다.
        if not messagebox.askyesno("Confirm", "Do you really want to clean all past temporary plot files?"):
            return

        try:
            import glob
            # 디렉토리 내의 임시 플롯용 파일 패턴들 (*.plt, *.gnu, *Temp*)을 모두 수집
            patterns = [
                os.path.join(self.plot_dir, "*.plt"),
                os.path.join(self.plot_dir, "*.gnu"),
            #    os.path.join(self.plot_dir, "*_Temp*.*")
            ]

            deleted_count = 0
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
            messagebox.showinfo("Success", f"Cleaned up {deleted_count} past temporary plot files.")
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

    def resorted_dat_file(self, dat_file, x_output_no):
        """X축 변수 오름차순 정렬이 적용된 임시 DAT 파일을 관리 및 생성합니다."""
        # 캐시가 이미 존재하고 원본보다 최신이면 그대로 사용
        if dat_file in self._sorted_dat_cache:
            cached_path = self._sorted_dat_cache[dat_file]
            if os.path.exists(cached_path) and os.path.getmtime(cached_path) >= os.path.getmtime(dat_file):
                return cached_path

        try:
            with open(dat_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            header = []
            data_rows = []
            is_data = False

            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    if not is_data:
                        header.append(line)
                    else:
                        data_rows.append((line, None))  # 주석 줄 보존
                    continue

                # 데이터 파싱 시도 (첫 번째 컬럼을 X축으로 가정하여 정렬)
                parts = stripped.replace(',', ' ').split()
                try:
                    x_val = float(parts[0])
                    data_rows.append((line, x_val))
                    is_data = True
                except ValueError:
                    if not is_data:
                        header.append(line)
                    else:
                        data_rows.append((line, None))

            # 숫자 X값을 기준으로 오름차순 정렬 (숫자가 아닌 행은 원래 순서 유지)
            numeric_rows = [r for r in data_rows if r[1] is not None]
            other_rows = [r for r in data_rows if r[1] is None]

            numeric_rows.sort(key=lambda x: x[1])

            # 정렬된 임시 파일 생성
            temp_dir = self.get_temp_dir()
            base_name = os.path.basename(dat_file)
            sorted_path = os.path.join(temp_dir, f"sorted_{base_name}")

            with open(sorted_path, 'w', encoding='utf-8') as f:
                for h in header:
                    f.write(h if h.endswith('\n') else h + '\n')
                for r, _ in numeric_rows + other_rows:
                    f.write(r if r.endswith('\n') else r + '\n')

            self._sorted_dat_cache[dat_file] = sorted_path
            return sorted_path

        except Exception as e:
            print(f"Error sorting DAT file {dat_file}: {e}")
            return dat_file  # 오류 발생 시 원본 반환

    def execute_plot_pipeline(self, mode="Interactive"):
        """플롯 생성 및 실행 파이프라인 (속성 누락 에러 원천 차단 버전)"""
        # eps_var가 없어 발생하는 에러를 막기 위한 임시 방어 코드
        if not hasattr(self, 'eps_var'):
            class DummyVar:
                def get(self): return False
            self.eps_var = DummyVar()
        try:
            # 1. 활성화된 Y1, Y2 키 목록 가져오기
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

            # 2. X축 파일 정렬 및 커브 정의 생성
            for d_file, out_no, title, axis, key in temp_curves_info:
                file_x_output_no = 0
                try:
                    for info in self.file_rows:
                        if info.get("filename") == d_file:
                            x_key_val = info.get("x_var").get()
                            if x_key_val and "||" in x_key_val:
                                _, x_out_no_str = x_key_val.split("||")
                                file_x_output_no = int(x_out_no_str)
                            break
                except Exception:
                    file_x_output_no = 0

                target_dat_file = d_file
                if file_x_output_no > 0 and hasattr(self, 'resort_dat_file'):
                    try:
                        target_dat_file = self.resort_dat_file(d_file, file_x_output_no)
                    except Exception:
                        target_dat_file = d_file

                def get_var_val(v_dict, k, default):
                    try:
                        val = v_dict.get(k).get()
                        return val if val != "" else default
                    except Exception:
                        return default

                curves.append(CurveDefinition(
                    dat_file=target_dat_file, 
                    output_no=out_no, 
                    title=title, 
                    axis=axis,
                    x_shift=float(get_var_val(self.xshift_vars, key, 0.0)), 
                    color=COLOR_MAP.get(get_var_val(self.color_vars, key, None), None) if 'COLOR_MAP' in globals() else None,
                    linestyle=STYLE_MAP.get(get_var_val(self.linestyle_vars, key, None), None) if 'STYLE_MAP' in globals() else None, 
                    linewidth=float(get_var_val(self.linewidth_vars, key, 1.5))
                ))

            # 3. 안전한 값 가져오기 헬퍼 함수
            def safe_get(attr_name, default):
                attr = getattr(self, attr_name, None)
                if attr is not None and hasattr(attr, 'get'):
                    try:
                        return attr.get()
                    except Exception:
                        return default
                return default

            # 4. PlotDefinition 생성 (속성 누락 안전 처리)
            plotdef = PlotDefinition(
                title=safe_get('title_var', ''),
                xlabel=safe_get('xlabel_var', ''),
                ylabel=safe_get('ylabel_var', ''),
                y2label=safe_get('y2label_var', ''),
                output_format=mode,  # eps_var 의존성 제거, 전달받은 mode 사용
                xauto=safe_get('xauto_var', False),
                yauto=safe_get('yauto_var', False),
                y2auto=safe_get('y2auto_var', False),
                xmin=safe_get('xmin_var', ''), xmax=safe_get('xmax_var', ''),
                ymin=safe_get('ymin_var', ''), ymax=safe_get('ymax_var', ''),
                y2min=safe_get('y2min_var', ''), y2max=safe_get('y2max_var', ''),
                xtics=safe_get('xtics_var', ''), ytics=safe_get('ytics_var', ''), y2tics=safe_get('y2tics_var', ''),
                curves=curves
            )

            # 5. Gnuplot 실행
            generator = GnuplotGenerator(plotdef)
            generator.run()

            outfile = generator.output_file
            curr_id = getattr(self, 'current_dataset_id', 'default')
            safe_title = "".join(c for c in safe_get('title_var', 'plot') if c.isalnum() or c in (' ', '_', '-')).rstrip()

            if mode == "Interactive" and getattr(generator, 'last_process', None) is not None:
                if hasattr(self, 'plot_processes'):
                    self.plot_processes.append(generator.last_process)
                if hasattr(self, 'active_plots_cache'):
                    self.active_plots_cache[f"{safe_title}_{curr_id}"] = plotdef

            if hasattr(self, 'history_plots') and plotdef not in self.history_plots:
                self.history_plots.append(plotdef)

            if hasattr(self, 'update_plot_file_list'):
                self.update_plot_file_list()

            return outfile

        except Exception as e:
            messagebox.showerror("Error", f"Failed to execute plot pipeline: {e}")

    def show_multiplot_dialog(self, mode="Batch", default_format="pdf"):
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
                file_types = [("PDF cairo", "*.pdf"), ("PNG image", "*.png"), ("SVG vector", "*.svg")]
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

            # 2. [핵심 수정] 인쇄(Print) 모드일 때만 프린터 선택 창을 강제로 호출합니다.
            if mode != "Save":
                #try:
                #    if os.path.exists(filepath):
                #        self._print_emf_and_cleanup(filepath, "CathPlot Multi Plot")
                #except Exception as e:
                #    messagebox.showerror("Print Error", f"인쇄 창을 띄우지 못했습니다: {e}", parent=dialog)
                if os.path.exists(filepath):
                    threading.Thread(
                        target=self._print_and_cleanup, args=(filepath,), daemon=True
                    ).start()

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
        fmt = (custom_format or "pdf").lower() if target == "file" else "interactive"

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

        import dataclasses
        # 캐시에 저장된 원본 plotdef를 직접 고치는 대신 복사본을 만들어 적용한다.
        run_plot_defs = [
            dataclasses.replace(pd, is_print_mode=(mode == "Batch"))
            for pd in selected_plot_defs
        ]

        generator = GnuplotGenerator(self.plot_dir)
        generator.create_multiplot_script(
            plots=run_plot_defs, outfile=outfile, fmt=fmt,
            layout_option=layout_opt, orientation=self.orientation_var.get(),
            keep_script=(mode == "Save"),
            frame_auto=final_frame_auto, frame_width=final_frame_width,
            frame_height=final_frame_height, frame_unit=final_frame_unit
        )

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
        idx = 1
        while True:
            temp_pdf = os.path.join(self.plot_dir, f"Print_Job_Temp_{idx}.pdf")
            if not os.path.exists(temp_pdf):
                break
            idx += 1

        try:
            success_path = self.execute_plot_pipeline("Batch", custom_filepath=temp_pdf, custom_format="PDF")

        except Exception as e:
            messagebox.showerror("Print Error", f"PDF 생성 중 오류가 발생했습니다:\n{e}")
            return

        if success_path and os.path.exists(success_path):
            threading.Thread(
                target=self._print_and_cleanup, args=(success_path,), daemon=True
            ).start()

#    def _print_emf_and_cleanup(self, filepath, document_name):
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
            self.root.after(0, lambda: messagebox.showerror("Print Error", str(e)))
        finally:
            pythoncom.CoUninitialize()

        # 인쇄 스풀/뷰어가 파일을 읽어갈 시간을 준 뒤 삭제 (메인 스레드 안 막음)
        def _delayed_delete():
            for _ in range(5):
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    break
                except Exception:
                    time.sleep(1.0)

        threading.Timer(10.0, _delayed_delete).start()

    def execute_save_dialog(self):
        raw_title = self.filename_var.get().strip() or "CathPlot"
        next_id = self.title_counters.get(raw_title, 0) or 1
        safe_title = "".join([c for c in raw_title if c.isalnum() or c in ("_", "-")]).strip() or "CathPlot"
        default_name = f"{safe_title}_{next_id}"

        file_types = [
            ("Portable Document Format (*.pdf)", "*.pdf"),
            ("PNG Image (*.png)", "*.png"),
            ("SVG Vector Graphic (*.svg)", "*.svg"),
            ("JPEG Image (*.jpg)", "*.jpg"),
            ("Enhanced Metafile (*.emf)", "*.emf"),
            ("Encapsulated PostScript (*.eps)", "*.eps"),
        ]
        selected_path = filedialog.asksaveasfilename(initialdir=self.plot_dir, initialfile=default_name, title="Save Plot As...", filetypes=file_types, defaultextension=".pdf")
        if not selected_path: return

        ext = os.path.splitext(selected_path)[1].lower().replace(".", "")
        fmt_map = {"pdf": "PDF", "png": "PNG", "svg": "SVG", "jpg": "JPG", "jpeg": "JPG", "emf": "EMF", "eps": "EPS"}
        self.execute_plot_pipeline("Batch", custom_filepath=os.path.abspath(selected_path), custom_format=fmt_map.get(ext, "PDF"))

    def set_active_entry(self, entry):
        self.active_entry = entry

    def cleanup_sorted_cache(self):
        for cached_path in self.sorted_data_cache.values():
            if os.path.exists(cached_path):
                try:
                    os.remove(cached_path)
                except Exception:
                    pass
        self.sorted_data_cache.clear()

    def on_closing(self):
        """GUI 창이 닫힐 때 캐시를 청소하고 프로그램을 종료합니다."""
        self.cleanup_sorted_cache()
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

if __name__ == "__main__":
    root = tk.Tk()
    app = CathPlotGUI(root)
    root.mainloop()
