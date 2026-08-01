# -*- coding: utf-8 -*-

import os
import re
import glob
import time
import threading
import subprocess
import dataclasses
import pythoncom
import win32api
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# (시스템 환경에 맞게 선언되어 있다고 가정하는 매핑 및 리스트)
COLOR_LIST = ["Auto", "black", "red", "green", "blue", "magenta", "cyan", "orange"]
STYLE_LIST = ["Auto", "-", "--", ":", "-."]

COLOR_MAP = {
    "black": "black", "red": "red", "green": "green", "blue": "blue",
    "magenta": "magenta", "cyan": "cyan", "orange": "orange"
}
STYLE_MAP = {
    "-": "solid", "--": "dashed", ":": "dotted", "-.": "dashdot"
}

@dataclasses.dataclass
class CurveDefinition:
    dat_file: str
    output_no: int
    title: str = ""
    axis: str = "y1"
    x_shift: float = 0.0
    color: str = None
    linestyle: str = None
    linewidth: float = 1.5

@dataclasses.dataclass
class PlotDefinition:
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    y2label: str = ""
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
    xtics: str = ""
    ytics: str = ""
    y2tics: str = ""
    mxtics: str = ""
    mytics: str = ""
    my2tics: str = ""
    major_grid: bool = True
    minor_grid: bool = False
    legend_on: bool = True
    legend_box: bool = True
    legend_pos: str = "top right"
    title_font: str = ""
    title_size: str = ""
    xlabel_font: str = ""
    xlabel_size: str = ""
    ylabel_font: str = ""
    ylabel_size: str = ""
    y2label_font: str = ""
    y2label_size: str = ""
    is_print_mode: bool = False
    frame_auto: bool = True
    frame_width: str = ""
    frame_height: str = ""
    frame_unit: str = "inch"
    x_output_no: int = 0
    curves: list = dataclasses.field(default_factory=list)

class GnuplotGenerator:
    def __init__(self, plot_dir):
        self.plot_dir = plot_dir
        self.last_process = None

    def create_script(self, plotdef, outfile, fmt, annotations, arrows):
        # Gnuplot 스크립트 생성 로직 구현 위치
        pass

    def create_multiplot_script(self, plots, outfile, fmt, layout_option, orientation, keep_script, frame_auto, frame_width, frame_height, frame_unit):
        # 멀티플롯 스크립트 생성 로직 구현 위치
        pass


class CathPlotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("CathPlot")
        self.cwd = os.getcwd()
        self.plot_dir = self.cwd
        
        # 각종 상태 변수 초기화
        self.file_rows = []
        self.active_plots_cache = {}
        self.history_plots = []
        self.title_counters = {}
        self.multi_counters = {}
        self.plot_processes = []
        self.sorted_dat_cache = {}
        self.active_entry = None
        
        self.layout_var = tk.StringVar(value="Auto")
        self.orientation_var = tk.StringVar(value="portrait")
        self.title_var = tk.StringVar(value="CathPlot")
        self.filename_var = tk.StringVar(value="CathPlot")
        self.xlabel_var = tk.StringVar(value="")
        self.ylabel_var = tk.StringVar(value="")
        self.y2label_var = tk.StringVar(value="")
        
        self.xauto_var = tk.BooleanVar(value=True)
        self.yauto_var = tk.BooleanVar(value=True)
        self.y2auto_var = tk.BooleanVar(value=True)
        self.xmin_var = tk.StringVar(value="")
        self.xmax_var = tk.StringVar(value="")
        self.ymin_var = tk.StringVar(value="")
        self.ymax_var = tk.StringVar(value="")
        self.y2min_var = tk.StringVar(value="")
        self.y2max_var = tk.StringVar(value="")
        
        self.xtics_var = tk.StringVar(value="")
        self.ytics_var = tk.StringVar(value="")
        self.y2tics_var = tk.StringVar(value="")
        self.mxtics_var = tk.StringVar(value="")
        self.mytics_var = tk.StringVar(value="")
        self.my2tics_var = tk.StringVar(value="")
        
        self.major_grid_var = tk.BooleanVar(value=True)
        self.minor_grid_var = tk.BooleanVar(value=False)
        self.legend_on_var = tk.BooleanVar(value=True)
        self.legend_box_var = tk.BooleanVar(value=True)
        self.legend_pos_var = tk.StringVar(value="top right")
        
        self.title_font_var = tk.StringVar(value="")
        self.title_size_var = tk.StringVar(value="")
        self.xlabel_font_var = tk.StringVar(value="")
        self.xlabel_size_var = tk.StringVar(value="")
        self.ylabel_font_var = tk.StringVar(value="")
        self.ylabel_size_var = tk.StringVar(value="")
        self.y2label_font_var = tk.StringVar(value="")
        self.y2label_size_var = tk.StringVar(value="")
        
        self.frame_auto_var = tk.BooleanVar(value=True)
        self.frame_width_var = tk.StringVar(value="")
        self.frame_height_var = tk.StringVar(value="")
        self.frame_unit_var = tk.StringVar(value="inch")
        
        self.comment_on_var = tk.BooleanVar(value=False)
        self.arrow_on_var = tk.BooleanVar(value=False)

        self.x_title_auto = True
        self.y1_title_auto = True
        self.y2_title_auto = True
        self._updating_x = False
        self._updating_y1 = False
        self._updating_y2 = False

        self.legend_vars = {}
        self.selected_y1_vars = {}
        self.selected_y2_vars = {}
        self.xshift_vars = {}
        self.color_vars = {}
        self.linestyle_vars = {}
        self.linewidth_var = tk.DoubleVar(value=1.5)

        self.LAYOUT_FIXED_ORIENTATION = {}
        self.LAYOUT_DEFAULT_ORIENTATION = {}
        self.LAYOUT_GRID = {"Auto": (1, 1), "1/p": (1, 1), "2/p": (1, 2), "4/p": (2, 2), "6/p": (2, 3)}

        # UI 기본 프레임 및 컴포넌트 변수 매핑
        self.scrollable_frame = ttk.Frame(root)
        self.canvas = tk.Canvas(root)
        self.c_list_frame = ttk.Frame(root)
        self.a_list_frame = ttk.Frame(root)
        self.comment_list = []
        self.arrow_list = []
        self.file_listbox = None

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

            selected_defs = [available_plots[i] for i in selected_indices]
            layout = self.layout_var.get()
            rows, cols = self.LAYOUT_GRID.get(layout, (1, 1))

            if layout != "Auto" and len(selected_defs) > rows * cols:
                messagebox.showwarning(
                    "Warning",
                    f"'{layout}' 레이아웃은 최대 {rows*cols}개까지만 담을 수 있습니다.\n"
                    f"지금 {len(selected_defs)}개를 선택하셨습니다 - 개수를 줄이거나 "
                    f"더 큰 레이아웃(또는 Auto)을 선택해주세요.",
                    parent=dialog
                )
                return

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
                    parent=dialog, initialdir=self.plot_dir, initialfile=base_name,
                    defaultextension=".pdf", filetypes=file_types, title="Save Multiplot As..."
                )
                if not filepath:
                    return

                fmt = os.path.splitext(filepath)[1].replace(".", "").lower()
                self.execute_multi_plot_pipeline(selected_defs, mode, filepath, fmt)
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
                    self.execute_multi_plot_pipeline(selected_defs, "Batch", temp_pdf, "pdf")
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

        ttk.Label(dlg, text="어떻게 닫으시겠습니까?", padding=15).pack()

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
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
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

        ttk.Button(btn_f, text="최신 창은 남기고 나머지만 닫기", command=lambda: do_close("keep_latest")).pack(fill="x", pady=2)
        ttk.Button(btn_f, text="이 프로그램에서 연 창 전부 닫기", command=lambda: do_close("all_mine")).pack(fill="x", pady=2)
        ttk.Button(btn_f, text="시스템의 모든 gnuplot 창 닫기", command=lambda: do_close("system_all")).pack(fill="x", pady=2)
        ttk.Button(btn_f, text="취소", command=lambda: do_close("cancel")).pack(fill="x", pady=(8, 2))

    def add_file_row(self):
        var = tk.StringVar()
        file_x_var = tk.StringVar(value="")
        row = ttk.Frame(self.file_scrollable_frame) if hasattr(self, 'file_scrollable_frame') else ttk.Frame(self.root)
        info = {
            "frame": row, "var": var, "filename": "", "meta": None,
            "x_var": file_x_var
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
            self.legend_vars, self.selected_y1_vars, self.selected_y2_vars,
            self.xshift_vars, self.color_vars, self.linestyle_vars
        ):
            for key in list(d.keys()):
                if key.startswith(prefix):
                    del d[key]

        if r_info["x_var"].get().startswith(prefix):
            r_info["x_var"].set("")

        var.set(filename)
        r_info["filename"] = filename
        r_info["meta"] = self.parser.parse(filename) if hasattr(self, 'parser') else None

        self.update_title_from_first_file()
        self.show_variables()

    def delete_dat_file_row(self, r_info):
        if "frame" in r_info and r_info["frame"].winfo_exists():
            r_info["frame"].destroy()
        if r_info in self.file_rows:
            self.file_rows.remove(r_info)

        datfile = r_info["filename"]
        prefix = f"{datfile}||"

        for d in (self.legend_vars, self.selected_y1_vars, self.selected_y2_vars, self.xshift_vars):
            for key in list(d.keys()):
                if key.startswith(prefix):
                    del d[key]

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
        "No Head": "nohead", "ForwHead": "head",
        "BackHead": "backhead", "Both Heads": "heads",
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
            row, textvariable=head_display_var, values=list(self.ARROW_HEAD_DISPLAY_MAP.keys()),
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

    def clear_file_selections(self, target_df):
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
        for info in self.file_rows:
            if info["filename"] == target_df:
                info["x_var"].set("")
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
            file_x_var = info["x_var"]
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

            for pv in meta.variables:
                title = pv.signals[0].name if pv.signals else f"OUTPUT {pv.output_no}"
                key_str = f"{datfile}||{pv.output_no}"

                if pv.output_no == 0 and not file_x_var.get():
                    file_x_var.set(key_str)

                if key_str not in self.color_vars:
                    self.color_vars[key_str] = tk.StringVar(value="Auto")
                if key_str not in self.linestyle_vars:
                    self.linestyle_vars[key_str] = tk.StringVar(value="Auto")
                if key_str not in self.legend_vars:
                    self.legend_vars[key_str] = tk.StringVar(value=title)

                if pv.output_no == 0:
                    if key_str not in self.xshift_vars:
                        self.xshift_vars[key_str] = tk.StringVar(value="0.0")
                else:
                    if key_str not in self.selected_y1_vars:
                        self.selected_y1_vars[key_str] = tk.BooleanVar(value=False)
                    if key_str not in self.selected_y2_vars:
                        self.selected_y2_vars[key_str] = tk.BooleanVar(value=False)
                    if key_str not in self.xshift_vars:
                        self.xshift_vars[key_str] = tk.StringVar(value="0.0")

                row_frame = ttk.Frame(frame)
                row_frame.pack(anchor="w", fill="x", padx=0, pady=0)

                ttk.Label(row_frame, text=f"{pv.output_no:>2}", width=3, anchor="e").pack(side="left")
                entry = ttk.Entry(row_frame, textvariable=self.legend_vars[key_str], width=20)
                entry.pack(side="left", padx=(1,0))
                entry.bind("<FocusIn>", lambda e, ent=entry: self.set_active_entry(ent))

                r_x = ttk.Radiobutton(row_frame, value=key_str, variable=file_x_var, command=self.sync_axis_labels)

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
        if hasattr(self, 'canvas'):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.sync_axis_labels()

    def sync_axis_labels(self):
        x_key = ""
        for info in self.file_rows:
            if info.get("filename") and info.get("meta") is not None:
                x_key = info["x_var"].get()
                if x_key:
                    break

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
        self.cleanup_sorted_cache()
        if not messagebox.askyesno("Confirm", "Do you really want to clean all past temporary plot files?"):
            return

        try:
            patterns = [os.path.join(self.plot_dir, "*.plt"), os.path.join(self.plot_dir, "*.gnu")]
            deleted_count = 0
            for pattern in patterns:
                for filepath in glob.glob(pattern):
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                            deleted_count += 1
                        except:
                            pass
            self.update_plot_file_list()
            messagebox.showinfo("Success", f"Cleaned up {deleted_count} past temporary plot files.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to clean past plots: {e}")

    def clear_all_plots(self):
        self.clean_past_plots()
        if not messagebox.askyesno("Confirm", "Clear all plots from history and reset window naming?"):
            return

        try:
            patterns = [os.path.join(self.plot_dir, "*.plt"), os.path.join(self.plot_dir, "*.gnu")]
            for pattern in patterns:
                for filepath in glob.glob(pattern):
                    if os.path.exists(filepath):
                        try: os.remove(filepath)
                        except: pass

            if hasattr(self, 'title_counters'):
                self.title_counters.clear()
            if hasattr(self, 'history_plots'):
                self.history_plots.clear()
            if hasattr(self, 'active_plots_cache'):
                self.active_plots_cache.clear()
            if hasattr(self, 'plot_processes'):
                for p in self.plot_processes:
                    try: p.terminate()
                    except: pass
                self.plot_processes.clear()

            self.update_plot_file_list()
            messagebox.showinfo("Success", "All plots cleared and naming IDs have been reset.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to clear all plots: {e}")

    def reset_history(self):
        if not messagebox.askyesno("Confirm", "Clear all plots from history?"):
            return
        if hasattr(self, 'title_counters'):
            self.title_counters.clear()
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

    def resorted_dat_file(self, dat_file, x_output_no):
        cache_key = (dat_file, x_output_no)
        if cache_key in self.sorted_dat_cache:
            cached_path = self.sorted_dat_cache[cache_key]
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
                        data_rows.append((line, None))
                    continue

                parts = stripped.replace(',', ' ').split()
                try:
                    x_val = float(parts[x_output_no])
                    data_rows.append((line, x_val))
                    is_data = True
                except (ValueError, IndexError):
                    if not is_data:
                        header.append(line)
                    else:
                        data_rows.append((line, None))

            numeric_rows = [r for r in data_rows if r[1] is not None]
            other_rows = [r for r in data_rows if r[1] is None]
            numeric_rows.sort(key=lambda x: x[1])

            temp_dir = self.get_temp_dir()
            base_name = os.path.splitext(os.path.basename(dat_file))[0]
            ext = os.path.splitext(dat_file)[1] or ".dat"
            sorted_path = os.path.join(temp_dir, f"{base_name}_sortedX{x_output_no}{ext}")

            with open(sorted_path, 'w', encoding='utf-8') as f:
                for h in header:
                    f.write(h if h.endswith('\n') else h + '\n')
                for r, _ in numeric_rows + other_rows:
                    f.write(r if r.endswith('\n') else r + '\n')

            self.sorted_dat_cache[cache_key] = sorted_path
            return sorted_path
        except Exception as e:
            messagebox.showerror("Resort Error", f"'{os.path.basename(dat_file)}' 파일 정렬 중 오류:\n{e}")
            return dat_file

    def execute_plot_pipeline(self, mode, custom_filepath=None, custom_format=None):
        os.makedirs(self.plot_dir, exist_ok=True)
        raw_title = self.filename_var.get().strip() or "CathPlot"

        if mode == "Interactive":
            if raw_title not in self.title_counters:
                self.title_counters[raw_title] = 0
            self.title_counters[raw_title] += 1
            curr_id = self.title_counters[raw_title]
        else:
            curr_id = self.title_counters.get(raw_title, 0) or 1

        safe_title = "".join([c for c in raw_title if c.isalnum() or c in ("_", "-")]).strip() or "CathPlot"
        target = "screen" if mode == "Interactive" else "file"
        fmt = (custom_format or "pdf").lower() if target == "file" else "interactive"

        outfile = custom_filepath if custom_filepath else os.path.join(self.plot_dir, f"{safe_title}_{curr_id}.gnu")

        active_y1_keys = [k for k, v in self.selected_y1_vars.items() if v.get()]
        active_y2_keys = [k for k, v in self.selected_y2_vars.items() if v.get()]

        if not active_y1_keys and not active_y2_keys:
            messagebox.showwarning("Warning", "Please select at least one Y1 or Y2 variable.")
            return None

        curves = []
        for key in active_y1_keys:
            d_file, out_no = key.split("||")
            curves.append(CurveDefinition(
                dat_file=d_file, output_no=int(out_no), title=self.legend_vars[key].get(), axis="y1",
                x_shift=float(self.xshift_vars[key].get() or 0.0), color=COLOR_MAP.get(self.color_vars[key].get(), None),
                linestyle=STYLE_MAP.get(self.linestyle_vars[key].get(), None), linewidth=float(self.linewidth_var.get() or 1.5)
            ))

        for key in active_y2_keys:
            d_file, out_no = key.split("||")
            curves.append(CurveDefinition(
                dat_file=d_file, output_no=int(out_no), title=self.legend_vars[key].get(), axis="y2",
                x_shift=float(self.xshift_vars[key].get() or 0.0), color=COLOR_MAP.get(self.color_vars[key].get(), None),
                linestyle=STYLE_MAP.get(self.linestyle_vars[key].get(), None), linewidth=float(self.linewidth_var.get() or 1.5)
            ))

        x_output_no = 0
        if curves:
            first_dat_file = curves[0].dat_file
            for info in self.file_rows:
                if info.get("filename") == first_dat_file:
                    x_key_val = info["x_var"].get()
                    if x_key_val and "||" in x_key_val:
                        _, x_out_no_str = x_key_val.split("||")
                        try:
                            x_output_no = int(x_out_no_str)
                        except ValueError:
                            x_output_no = 0
                    break

        if x_output_no > 0:
            for curve in curves:
                sorted_path = self.resorted_dat_file(curve.dat_file, x_output_no)
                curve.dat_file = sorted_path

        if not self.xlabel_var.get().strip() and curves:
            try:
                first_file = curves[0].dat_file
                found_header = None
                with open(first_file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('#'):
                            if str(x_output_no) in line or "Time" in line or "X" in line:
                                found_header = line.lstrip('#').strip()
                        elif line:
                            break
                if found_header:
                    self.xlabel_var.set(found_header)
                else:
                    base_name = os.path.splitext(os.path.basename(first_file))[0]
                    self.xlabel_var.set(base_name if x_output_no == 0 else f"{base_name} [Col {x_output_no}]")
            except Exception:
                self.xlabel_var.set("Time" if x_output_no == 0 else f"Variable {x_output_no}")

        is_auto = self.frame_auto_var.get()
        w_str = self.frame_width_var.get().strip()
        h_str = self.frame_height_var.get().strip()
        unit = self.frame_unit_var.get()

        final_frame_width, final_frame_height, final_frame_unit, final_frame_auto = "", "", "", True
        if target == "file" and not is_auto and w_str and h_str:
            try:
                float(w_str)
                float(h_str)
                final_frame_width = w_str
                final_frame_height = h_str
                final_frame_unit = unit
                final_frame_auto = False
            except ValueError:
                final_frame_auto = True

        plotdef = PlotDefinition(
            title=self.title_var.get(), xlabel=self.xlabel_var.get(),
            ylabel=self.ylabel_var.get(), y2label=self.y2label_var.get(),
            output_format=mode, xauto=self.xauto_var.get(), yauto=self.yauto_var.get(), y2auto=self.y2auto_var.get(),
            xmin=self.xmin_var.get(), xmax=self.xmax_var.get(), ymin=self.ymin_var.get(), ymax=self.ymax_var.get(),
            y2min=self.y2min_var.get(), y2max=self.y2max_var.get(), xtics=self.xtics_var.get(),
            ytics=self.ytics_var.get(), y2tics=self.y2tics_var.get(), mxtics=self.mxtics_var.get(),
            mytics=self.mytics_var.get(), my2tics=self.my2tics_var.get(), major_grid=self.major_grid_var.get(),
            minor_grid=self.minor_grid_var.get(), legend_on=self.legend_on_var.get(), legend_box=self.legend_box_var.get(),
            legend_pos=self.legend_pos_var.get(), title_font=self.title_font_var.get(), title_size=self.title_size_var.get(),
            xlabel_font=self.xlabel_font_var.get(), xlabel_size=self.xlabel_size_var.get(), ylabel_font=self.ylabel_font_var.get(),
            ylabel_size=self.ylabel_size_var.get(), y2label_font=self.y2label_font_var.get(), y2label_size=self.y2label_size_var.get(),
            is_print_mode=(mode == "Batch"), frame_auto=final_frame_auto, frame_width=final_frame_width,
            frame_height=final_frame_height, frame_unit=final_frame_unit, x_output_no=x_output_no, curves=curves
        )

        generator = GnuplotGenerator(self.plot_dir)
        generator.create_script(
            plotdef=plotdef, outfile=outfile, fmt=fmt,
            annotations=self._collect_annotations(), arrows=self._collect_arrows()
        )

        if mode == "Interactive" and generator.last_process is not None:
            self.plot_processes.append(generator.last_process)
            self.active_plots_cache[f"{safe_title}_{curr_id}"] = plotdef

        if plotdef not in self.history_plots:
            self.history_plots.append(plotdef)

        self.update_plot_file_list()
        return outfile

    def show_multiplot_dialog(self, mode="Batch", default_format="pdf"):
        dialog = tk.Toplevel(self.root)
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
                filepath = os.path.join(self.plot_dir, "MultiPlot_Print_1.emf")
                fmt = "emf"

            self.layout_var.set(layout_cmb_var.get())
            self.execute_multi_plot_pipeline(selected_defs, mode, filepath, fmt)

            if mode != "Save":
                if os.path.exists(filepath):
                    threading.Thread(
                        target=self._print_and_cleanup, args=(filepath,), daemon=True
                    ).start()

            dialog.destroy()
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
        outfile = custom_filepath if custom_filepath else os.path.join(self.plot_dir, f"MultiPlot.gnu" if target == "screen" else f"MultiPlot_Output.{fmt}")

        layout_opt = self.layout_var.get()
        is_auto = self.frame_auto_var.get()
        w_str = self.frame_width_var.get().strip()
        h_str = self.frame_height_var.get().strip()
        unit = self.frame_unit_var.get()

        final_frame_width, final_frame_height, final_frame_unit, final_frame_auto = "", "", "", True
        if target == "file" and not is_auto and w_str and h_str:
            try:
                float(w_str)
                float(h_str)
                final_frame_width = w_str
                final_frame_height = h_str
                final_frame_unit = unit
                final_frame_auto = False
            except ValueError:
                final_frame_auto = True

        run_plot_defs = [
            dataclasses.replace(pd, is_print_mode=(mode == "Batch"))
            for pd in selected_plot_defs
        ]

        generator = GnuplotGenerator(self.plot_dir)
        generator.create_multiplot_script(
            plots=run_plot_defs, outfile=outfile, fmt=fmt,
            layout_option=layout_opt, orientation=self.orientation_var.get(),
            keep_script=(mode == "Save"), frame_auto=final_frame_auto,
            frame_width=final_frame_width, frame_height=final_frame_height, frame_unit=final_frame_unit
        )

        self.update_plot_file_list()
        return outfile

    def update_plot_file_list(self):
        if not hasattr(self, 'plot_dir') or not self.plot_dir: return
        files = glob.glob(os.path.join(self.plot_dir, "*.plt"))
        files.sort(key=os.path.getctime)
        if hasattr(self, 'file_listbox') and self.file_listbox:
            self.file_listbox.delete(0, 'end')
            for f in files: self.file_listbox.insert('end', os.path.basename(f))

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

    def _print_and_cleanup(self, filepath):
        pythoncom.CoInitialize()
        try:
            result = win32api.ShellExecute(0, "print", os.path.abspath(filepath), None, ".", 0)
            if result > 32:
                self.root.after(0, lambda: messagebox.showinfo("Print", "인쇄 작업을 프린터로 전송했습니다."))
            if result <= 32:
                win32api.ShellExecute(0, "open", os.path.abspath(filepath), None, ".", 0)
                self.root.after(0, lambda: messagebox.showinfo(
                    "Print", "이 PDF 뷰어는 자동 인쇄를 지원하지 않아 파일을 열기만 했습니다.\n열린 창에서 Ctrl+P로 직접 인쇄해주세요."
                ))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Print Error", str(e)))
        finally:
            pythoncom.CoUninitialize()

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
        for cached_path in self.sorted_dat_cache.values():
            if os.path.exists(cached_path):
                try: os.remove(cached_path)
                except Exception: pass
        self.sorted_dat_cache.clear()

    def on_closing(self):
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
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()