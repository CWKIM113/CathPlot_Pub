# -*- coding: utf-8 -*-

import tkinter as tk
import os
import subprocess
import time
import glob

from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox

from cathena_parser import CathenaDatParser
from gnu_generator import PlotDefinition, CurveDefinition, GnuplotGenerator

class CathPlotGUI:

    def __init__(self, root):
        self.root = root
        self.root.title("CathPlot V1.0b")
        self.root.geometry("1150x850")  # UI 컴포넌트 확장을 고려하여 가로폭 최적화

        self.parser = CathenaDatParser()
        self.file_rows = []
        self.check_vars = []
        self.active_entry = None

        self.last_opened_dir = None
        self.title_counters = {}
        self.active_plots_cache = {}

        self.create_widgets()

        # 모듈 상단에서 정의한 경로를 클래스 전역변수로 사용
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = os.path.dirname(self.script_dir)
        self.src_dir = self.script_dir
        self.plot_dir = os.path.join(self.project_root, "plot")
        # 이제 어디서든 self.plot_dir로 접근 가능
        os.makedirs(self.plot_dir, exist_ok=True)

    def create_widgets(self):
        # 1. DAT Files 영역
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

        # 2. 중간 기호 버튼 컨테이너
        btn_container = ttk.Frame(self.root)
        btn_container.pack(fill="x", padx=10, pady=0)

        self.var_symbol_btn = ttk.Button(
            btn_container, text=chr(937), width=5,
            command=self.open_permanent_symbol_window
        )
        self.var_symbol_btn.pack(side="right", padx=5)

        # 3. Available Variables 영역
        self.var_frame = ttk.LabelFrame(self.root, text="Available Variables")
        #self.var_frame.pack(fill="both", expand=True, padx=10, pady=0)
        self.var_frame.pack(fill="x", expand=False, padx=10, pady=0)

        # self.canvas = tk.Canvas(self.var_frame) # 연동식
        self.canvas = tk.Canvas(self.var_frame, height=300)# 고정식

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

        # 4. Plot Setting 영역
        self.plot_frame = ttk.LabelFrame(self.root, text="Plot Setting")
        self.plot_frame.pack(fill="x", padx=10, pady=0)

        self.title_var = tk.StringVar(value="CathPlot")
        self.xlabel_var = tk.StringVar(value="Time (sec)")
        self.ylabel_var = tk.StringVar(value="")
        self.xauto_var = tk.BooleanVar(value=True)
        self.yauto_var = tk.BooleanVar(value=True)

        # UI 상호작용 변수 정의
        self.legend_box_var = tk.BooleanVar(value=True)
        self.legend_pos_var = tk.StringVar(value="right top")
        self.title_font_var = tk.StringVar(value="Malgun Gothic")
        self.title_size_var = tk.StringVar(value="14")
        self.xlabel_font_var = tk.StringVar(value="Malgun Gothic")
        self.xlabel_size_var = tk.StringVar(value="11")
        self.ylabel_font_var = tk.StringVar(value="Malgun Gothic")
        self.ylabel_size_var = tk.StringVar(value="11")

        font_list = ["Malgun Gothic", "Arial", "Times New Roman", "Courier New", "Consolas"]
        size_list = ["6", "8", "9", "10", "11", "12", "14", "16", "18", "20"]

        # Row 0: Plot Title + Font/Size 컴보 + Legend 제어 컴포넌트 우측 배치
        ttk.Label(self.plot_frame, text="Plot Title").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.title_entry = ttk.Entry(self.plot_frame, textvariable=self.title_var, width=30)
        self.title_entry.grid(row=0, column=1, padx=5, pady=2, sticky="w")
        self.title_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.title_entry))

        t_font_frame = ttk.Frame(self.plot_frame)
        t_font_frame.grid(row=0, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(t_font_frame, textvariable=self.title_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(t_font_frame, textvariable=self.title_size_var, values=size_list, width=4, state="readonly").pack(side="left", padx=2)

        legend_frame = ttk.Frame(self.plot_frame)
        legend_frame.grid(row=0, column=3, columnspan=2, padx=15, pady=2, sticky="w")
        ttk.Checkbutton(legend_frame, text="Legend Box On", variable=self.legend_box_var).pack(side="left", padx=5)
        ttk.Label(legend_frame, text="Pos:").pack(side="left", padx=2)
        pos_list = ["right top", "right bottom", "left top", "left bottom", "outside right"]
        ttk.Combobox(legend_frame, textvariable=self.legend_pos_var, values=pos_list, width=12, state="readonly").pack(side="left", padx=2)

        # Row 1: X Axis Title + Font/Size 컴보 우측 배치
        ttk.Label(self.plot_frame, text="X Axis").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.xlabel_entry = ttk.Entry(self.plot_frame, textvariable=self.xlabel_var, width=30)
        self.xlabel_entry.grid(row=1, column=1, padx=5, pady=2, sticky="w")
        self.xlabel_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.xlabel_entry))

        x_font_frame = ttk.Frame(self.plot_frame)
        x_font_frame.grid(row=1, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(x_font_frame, textvariable=self.xlabel_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(x_font_frame, textvariable=self.xlabel_size_var, values=size_list, width=4, state="readonly").pack(side="left", padx=2)

        # Row 2: Y Axis Title + Font/Size 컴보 우측 배치
        ttk.Label(self.plot_frame, text="Y Axis").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        self.ylabel_entry = ttk.Entry(self.plot_frame, textvariable=self.ylabel_var, width=30)
        self.ylabel_entry.grid(row=2, column=1, padx=5, pady=2, sticky="w")
        self.ylabel_entry.bind("<FocusIn>", lambda e: self.set_active_entry(self.ylabel_entry))

        y_font_frame = ttk.Frame(self.plot_frame)
        y_font_frame.grid(row=2, column=2, padx=5, pady=2, sticky="w")
        ttk.Combobox(y_font_frame, textvariable=self.ylabel_font_var, values=font_list, width=12, state="readonly").pack(side="left", padx=2)
        ttk.Combobox(y_font_frame, textvariable=self.ylabel_size_var, values=size_list, width=4, state="readonly").pack(side="left", padx=2)

        # 축 구성 수치 인풋 필드 레이아웃
        ttk.Checkbutton(self.plot_frame, text="Auto X Range", variable=self.xauto_var).grid(row=3, column=0, sticky="w", padx=5, pady=0)
        ttk.Checkbutton(self.plot_frame, text="Auto Y Range", variable=self.yauto_var).grid(row=3, column=1, sticky="w", padx=5, pady=0)

        ttk.Label(self.plot_frame, text="X Min").grid(row=4, column=0, sticky="w", padx=5, pady=0)
        self.xmin_var = tk.StringVar()
        ttk.Entry(self.plot_frame, textvariable=self.xmin_var, width=12).grid(row=4, column=1, sticky="w", padx=5, pady=0)

        ttk.Label(self.plot_frame, text="X Max").grid(row=4, column=2, sticky="w", padx=5, pady=0)
        self.xmax_var = tk.StringVar()
        ttk.Entry(self.plot_frame, textvariable=self.xmax_var, width=12).grid(row=4, column=3, sticky="w", padx=5, pady=0)

        ttk.Label(self.plot_frame, text="Y Min").grid(row=5, column=0, sticky="w", padx=5, pady=0)
        self.ymin_var = tk.StringVar()
        ttk.Entry(self.plot_frame, textvariable=self.ymin_var, width=12).grid(row=5, column=1, sticky="w", padx=5, pady=0)

        ttk.Label(self.plot_frame, text="Y Max").grid(row=5, column=2, sticky="w", padx=5, pady=0)
        self.ymax_var = tk.StringVar()
        ttk.Entry(self.plot_frame, textvariable=self.ymax_var, width=12).grid(row=5, column=3, sticky="w", padx=5, pady=0)

        ttk.Label(self.plot_frame, text="X Major Tick").grid(row=6, column=0, sticky="w", padx=5, pady=0)
        self.xtics_var = tk.StringVar()
        ttk.Entry(self.plot_frame, textvariable=self.xtics_var, width=12).grid(row=6, column=1, sticky="w", padx=5, pady=0)

        ttk.Label(self.plot_frame, text="X Minor Tick No").grid(row=6, column=2, sticky="w", padx=5, pady=0)
        self.mxtics_var = tk.StringVar()
        ttk.Entry(self.plot_frame, textvariable=self.mxtics_var, width=12).grid(row=6, column=3, sticky="w", padx=5, pady=0)

        ttk.Label(self.plot_frame, text="Y Major Tick").grid(row=7, column=0, sticky="w", padx=5, pady=0)
        self.ytics_var = tk.StringVar()
        ttk.Entry(self.plot_frame, textvariable=self.ytics_var, width=12).grid(row=7, column=1, sticky="w", padx=5, pady=0)

        ttk.Label(self.plot_frame, text="Y Minor Tick No").grid(row=7, column=2, sticky="w", padx=5, pady=0)
        self.mytics_var = tk.StringVar()
        ttk.Entry(self.plot_frame, textvariable=self.mytics_var, width=12).grid(row=7, column=3, sticky="w", padx=5, pady=0)

        self.minor_grid_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.plot_frame, text="Enable Minor Grid", variable=self.minor_grid_var).grid(row=8, column=0, columnspan=2, sticky="w", padx=5, pady=0)

        # 하단 액션 인터페이스
        button_frame = ttk.Frame(self.root)
        button_frame.pack(side="bottom", fill="x", padx=10, pady=10)

        ttk.Button(button_frame, text="PLOT", command=lambda: self.execute_plot_pipeline("Interactive")).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Print", command=self.execute_print_dialog).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Save", command=self.execute_save_dialog).pack(side="left", padx=5)

        self.add_file_row()

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

        ttk.Entry(row, textvariable=var, width=60).pack(side="left", padx=5)
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
        init_dir = self.last_opened_dir if self.last_opened_dir else os.getcwd()
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
        valid_files = [
            info for info in self.file_rows if info["filename"] and info["meta"]
        ]
        if valid_files:
            first_filename = valid_files[0]["filename"]
            base_name = os.path.splitext(os.path.basename(first_filename))[0]
            self.title_var.set(base_name)
        else:
            self.title_var.set("CathPlot")

    def show_variables(self):
        backup_data = {}
        if hasattr(self, 'check_vars') and self.check_vars:
            for datfile, pv, var, legend_var in self.check_vars:
                backup_data[(datfile, pv.output_no)] = {
                    "checked": var.get(), "legend": legend_var.get()
                }

        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        self.check_vars = []
        container = ttk.Frame(self.scrollable_frame)
        container.pack(fill="both", expand=True)

        for idx, info in enumerate(self.file_rows):
            if info["meta"] is None:
                continue
            datfile = info["filename"]
            meta = info["meta"]

            frame = ttk.LabelFrame(container, text=os.path.basename(datfile))
            btn_frame = ttk.Frame(frame)
            btn_frame.pack(anchor="w")

            ttk.Button(
                btn_frame, text="All", width=5,
                command=lambda f=datfile: self.select_all(f)
            ).pack(side="left")
            ttk.Button(
                btn_frame, text="None", width=5,
                command=lambda f=datfile: self.clear_all(f)
            ).pack(side="left")
            frame.grid(row=idx // 3, column=idx % 3, sticky="nw", padx=5, pady=5)

            for pv in meta.variables:
                title = (
                    pv.signals[0].name if pv.signals else f"OUTPUT {pv.output_no}"
                )
                default_checked = False
                f_base = os.path.splitext(os.path.basename(datfile))[0]
                default_legend = f"{f_base} : {title}"

                key = (datfile, pv.output_no)
                if key in backup_data:
                    default_checked = backup_data[key]["checked"]
                    default_legend = backup_data[key]["legend"]

                var = tk.BooleanVar(value=default_checked)
                legend_var = tk.StringVar(value=default_legend)

                row_frame = ttk.Frame(frame)
                row_frame.pack(anchor="w", fill="x", padx=5)

                ttk.Checkbutton(
                    row_frame, text=f"{pv.output_no:3d}", variable=var
                ).pack(side="left")
                entry = ttk.Entry(row_frame, textvariable=legend_var, width=30)
                entry.pack(side="left", padx=3)
                entry.bind(
                    "<FocusIn>", lambda e, ent=entry: self.set_active_entry(ent)
                )

                self.check_vars.append((datfile, pv, var, legend_var))

    def select_all(self, datfile):
        for f, pv, var, legend_var in self.check_vars:
            if f == datfile:
                var.set(True)

    def clear_all(self, datfile):
        for f, pv, var, legend_var in self.check_vars:
            if f == datfile:
                var.set(False)

    def execute_plot_pipeline(
        self, mode, custom_filepath=None, custom_format=None,
        target_plot_def=None, layout_option=None
    ):
        # [핵심 수정] 현재 디렉토리가 src가 아니더라도 이 스크립트(cathplot_gui.py) 위치를 기준으로 정밀 경로 조율
        #script_dir = os.path.dirname(os.path.abspath(__file__)) # 언제나 src 폴더의 절대 주소를 가리킴
        #project_root = os.path.abspath(os.path.join(script_dir, ".."))
        # script_dir: cathplot_gui.py가 위치한 폴더 (예: C:\MyProject\src)
        # script_dir = os.path.dirname(os.path.abspath(__file__)) - 전역변수로 지정
        # project_root: src의 상위 폴더 (예: C:\MyProject)
        # project_root = os.path.dirname(script_dir) - 전역변수로 지정

        # src_dir = script_dir  - 전역변수로 지정
        # plot_dir = os.path.join(project_root, "plot")  - 전역변수로 지정

        os.makedirs(self.src_dir, exist_ok=True)
        os.makedirs(self.plot_dir, exist_ok=True)

        if isinstance(target_plot_def, list):
            ts = int(time.time() * 1000) % 100000
            outfile = os.path.join(self.plot_dir, f"CathPlot_MultiTemp_{ts}.gnu")
            #gen = GnuplotGenerator()
            gen = GnuplotGenerator(plot_dir=self.plot_dir)
            if custom_filepath:
                gen.custom_export_path = custom_filepath.replace("\\", "/")
            gen.create_multiplot_script(target_plot_def, layout_option, outfile)
        else:
            if target_plot_def:
                plot = target_plot_def
                plot.output_format = custom_format
            else:
                if all(info["meta"] is None for info in self.file_rows):
                    messagebox.showwarning("Warning", "Please select a DAT file.")
                    return None

                raw_title = self.title_var.get().strip()
                if not raw_title:
                    raw_title = "CathPlot"

                if raw_title not in self.title_counters:
                    self.title_counters[raw_title] = 0
                self.title_counters[raw_title] += 1
                curr_id = self.title_counters[raw_title]

                plot = PlotDefinition(
                    title=raw_title, xauto=self.xauto_var.get(),
                    yauto=self.yauto_var.get(), xlabel=self.xlabel_var.get(),
                    ylabel=self.ylabel_var.get(), xmin=self.xmin_var.get(),
                    xmax=self.xmax_var.get(), ymin=self.ymin_var.get(),
                    ymax=self.ymax_var.get(), xtics=self.xtics_var.get().strip(),
                    ytics=self.ytics_var.get().strip(),
                    mxtics=self.mxtics_var.get().strip(),
                    mytics=self.mytics_var.get().strip(),
                    minor_grid=self.minor_grid_var.get(),
                    legend_box=self.legend_box_var.get(),
                    legend_pos=self.legend_pos_var.get(),
                    title_font=self.title_font_var.get(),
                    title_size=self.title_size_var.get(),
                    xlabel_font=self.xlabel_font_var.get(),
                    xlabel_size=self.xlabel_size_var.get(),
                    ylabel_font=self.ylabel_font_var.get(),
                    ylabel_size=self.ylabel_size_var.get()
                )
                plot.output_format = mode
                plot.plot_id = curr_id

                plot.curves = []
                for datfile, pv, var, legend_var in self.check_vars:
                    if not var.get():
                        continue

                    shift_val = 0.0
                    for info in self.file_rows:
                        if info["filename"] == datfile:
                            try:
                                shift_val = float(info["tshift_var"].get())
                            except ValueError:
                                shift_val = 0.0
                            break

                    plot.curves.append(
                        CurveDefinition(
                            dat_file=datfile, output_no=pv.output_no,
                            title=legend_var.get(), time_shift=shift_val,
                            linewidth=1.5
                        )
                    )

                if not plot.curves:
                    self.title_counters[raw_title] -= 1
                    messagebox.showwarning("Warning", "Please select at least one variable.")
                    return None

                cache_key = f"{raw_title}_{curr_id}"
                self.active_plots_cache[cache_key] = plot

            curr_id = plot.plot_id
            safe_title = "".join([c for c in plot.title if c.isalnum() or c in ("_", "-")]).strip()
            if not safe_title:
                safe_title = "CathPlot"

            if mode == "Interactive":
                outfile = os.path.join(self.plot_dir, f"{safe_title}_{curr_id}.gnu")
            else:
                outfile = os.path.join(self.plot_dir, f"{safe_title}_Temp_{curr_id}.gnu")

            gen = GnuplotGenerator()
            if custom_filepath:
                gen.custom_export_path = custom_filepath.replace("\\", "/")

            gen.create_script(plot, outfile)

        try:
            abs_outfile = os.path.abspath(outfile)
            if mode == "Interactive" and not isinstance(target_plot_def, list):
                # Gnuplot 실행 시 무조건 src_dir을 작업공간으로 지정하여 스크립트를 파싱시킴.
                # 수정 코드 (persist 옵션 추가)
                subprocess.Popen(
                    ["gnuplot", "-persist", abs_outfile], cwd=self.plot_dir)
 #                   creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
 #               )
                return abs_outfile
            else:
                res = subprocess.run(
                    ["gnuplot", abs_outfile],
                    cwd=self.plot_dir,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )
                if res.returncode != 0:
                    raise RuntimeError(res.stderr)
                time.sleep(0.05)
                if os.path.exists(abs_outfile):
                    try:
                        os.remove(abs_outfile)
                    except Exception:
                        pass
                return custom_filepath

        except Exception as e:
            messagebox.showerror("Gnuplot Error", str(e))
            return None

    def update_plot_file_list(self):
        # 1. 경로 내 모든 gnu 파일 탐색
        target_pattern = os.path.join(self.plot_dir, "*.gnu")
        files = glob.glob(target_pattern)
        # 2. 생성 시간(ctime) 기준으로 정렬 (작성 순서대로 정렬)
        files.sort(key=os.path.getctime, reverse=False)
        # 3. UI 컴포넌트(예: self.file_listbox) 초기화 후 순서대로 삽입
        # (실제 사용 중이신 Listbox 변수명으로 변경하셔야 합니다)
        if hasattr(self, 'file_listbox'):
            self.file_listbox.delete(0, 'end')
            for f in files:
                self.file_listbox.insert('end', os.path.basename(f))

    def execute_print_dialog(self):
        selection = self.prompt_select_plot_window("Select Windows to Print", allow_multiple=True)
        if not selection:
            return

        script_dir = os.path.dirname(os.path.abspath(__file__))
        temp_pdf = os.path.join(script_dir, "Print_Job_Temp.pdf")

        if len(selection["ids"]) == 1:
            target_def = self.active_plots_cache[selection["ids"][0]]
            target_def.is_print_mode = True
            success_path = self.execute_plot_pipeline("Batch", custom_filepath=temp_pdf, custom_format="PDF", target_plot_def=target_def)
        else:
            plot_defs = []
            for pid in selection["ids"]:
                p_def = self.active_plots_cache[pid]
                p_def.is_print_mode = True
                plot_defs.append(p_def)
            success_path = self.execute_plot_pipeline("Batch", custom_filepath=temp_pdf, custom_format="PDF", target_plot_def=plot_defs, layout_option=selection["layout"])

        if success_path and os.path.exists(success_path):
            try:
                abs_pdf = os.path.abspath(success_path)

                # Acrobat 뷰어 GUI가 강제로 열리지 않도록 유도하는 PowerShell 정적 드라이버 다이렉트 전송 방식 고도화
                ps_cmd = f"Start-Process -FilePath '{abs_pdf}' -ArgumentList '/h /p' -NoNewWindow -Wait"
                subprocess.run(["powershell", "-Command", ps_cmd], check=True, creationflags=subprocess.CREATE_NO_WINDOW)

                # 드라이버 버퍼에 완전히 올라가 락이 해제될 수 있도록 충분히 수초 간 대기 후 임시 인쇄용 파일 삭제 보장
                time.sleep(3.0)
                self.safe_delete_file(abs_pdf)
            except Exception as e:
                messagebox.showerror("Print Error", f"Cannot send job to spooler:\n{str(e)}")
                self.safe_delete_file(temp_pdf)

    def safe_delete_file(self, filepath):
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass

    def execute_save_dialog(self):
        selection = self.prompt_select_plot_window("Select Windows to Save", allow_multiple=True)
        if not selection:
            return

        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_save_dir = os.path.abspath(os.path.join(script_dir, "../plot"))
        os.makedirs(base_save_dir, exist_ok=True)

        if len(selection["ids"]) == 1:
            initial_file = self.active_plots_cache[selection["ids"][0]].title
        else:
            initial_file = "Combined_Plots"

        file_types = [
            ("Portable Document Format (*.pdf)", "*.pdf"),
            ("PNG Image (*.png)", "*.png"),
            ("SVG Vector Graphic (*.svg)", "*.svg"),
            ("JPEG Image (*.jpg)", "*.jpg"),
            ("Enhanced Metafile (*.emf)", "*.emf"),
            ("All Files (*.*)", "*.*")
        ]

        selected_path = filedialog.asksaveasfilename(
            initialdir=base_save_dir, initialfile=initial_file,
            title="Save Plot As...", filetypes=file_types,
            defaultextension=".pdf"
        )

        if not selected_path:
            return

        selected_path = os.path.abspath(selected_path)
        ext = os.path.splitext(selected_path)[1].lower().replace(".", "")

        fmt_map = {"pdf": "PDF", "png": "PNG", "svg": "SVG", "jpg": "JPG", "jpeg": "JPG", "emf": "EMF"}
        gnu_format = fmt_map.get(ext, "PDF")

        if len(selection["ids"]) == 1:
            target_def = self.active_plots_cache[selection["ids"][0]]
            target_def.is_print_mode = False
            self.execute_plot_pipeline("Batch", custom_filepath=selected_path, custom_format=gnu_format, target_plot_def=target_def)
        else:
            plot_defs = []
            for pid in selection["ids"]:
                p_def = self.active_plots_cache[pid]
                p_def.is_print_mode = False
                plot_defs.append(p_def)
            self.execute_plot_pipeline("Batch", custom_filepath=selected_path, custom_format=gnu_format, target_plot_def=plot_defs, layout_option=selection["layout"])

    def prompt_select_plot_window(self, dialog_title, allow_multiple=False):
        available_keys = sorted(list(self.active_plots_cache.keys()))
        if not available_keys:
            messagebox.showwarning("Warning", "No active plot windows found.")
            return None

        if len(available_keys) == 1 and not allow_multiple:
            return {"ids": [available_keys[0]], "layout": "Auto"}

        chooser = tk.Toplevel(self.root)
        chooser.title(dialog_title)
        chooser.geometry("420x340")
        chooser.resizable(False, False)
        chooser.attributes("-topmost", True)

        chooser.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width() // 2) - 210
        ry = self.root.winfo_y() + (self.root.winfo_height() // 2) - 170
        chooser.geometry(f"+{rx}+{ry}")

        ttk.Label(chooser, text="Select Window Targets to Process:", font=("Arial", 10, "bold")).pack(pady=5)

        list_frame = ttk.Frame(chooser)
        list_frame.pack(fill="both", expand=True, padx=15, pady=2)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        listbox = tk.Listbox(
            list_frame, selectmode=tk.MULTIPLE if allow_multiple else tk.SINGLE,
            yscrollcommand=scrollbar.set, exportselection=False
        )
        scrollbar.config(command=listbox.yview)
        scrollbar.pack(side="right", fill="y")
        listbox.pack(side="left", fill="both", expand=True)

        for k in available_keys:
            parts = k.split("_")
            idx_str = parts[-1]
            ori_title = "_".join(parts[:-1])
            listbox.insert(tk.END, f" {ori_title}_{idx_str}")
        listbox.select_set(0)

        layout_frame = ttk.Frame(chooser)
        layout_frame.pack(fill="x", padx=15, pady=5)

        ttk.Label(layout_frame, text="Multiplot Layout:").pack(side="left", padx=5)
        layout_combo = ttk.Combobox(
            layout_frame, values=["Auto", "2/p (Portrait)", "4/p (Landscape)", "6/p (Portrait)"],
            state="readonly", width=18
        )
        layout_combo.current(0)
        layout_combo.pack(side="left", padx=5)

        result_container = {"ids": [], "layout": "Auto"}

        def on_confirm():
            selections = listbox.curselection()
            if not selections:
                messagebox.showwarning("Warning", "Please select a window.")
                return

            result_container["ids"] = [available_keys[idx] for idx in selections]
            result_container["layout"] = layout_combo.get()
            chooser.destroy()

        ttk.Button(chooser, text="Confirm", command=on_confirm, width=12).pack(pady=10)

        self.root.wait_window(chooser)
        return result_container if result_container["ids"] else None

    def set_active_entry(self, entry):
        self.active_entry = entry

    def insert_symbol_to_active(self, symbol):
        if hasattr(self, 'active_entry') and self.active_entry is not None:
            try:
                if self.active_entry.winfo_exists():
                    self.active_entry.insert(tk.INSERT, symbol)
                    self.active_entry.focus_set()
            except Exception:
                pass

    def open_permanent_symbol_window(self):
        if hasattr(self, 'sym_win') and self.sym_win.winfo_exists():
            self.sym_win.lift()
            return

        self.sym_win = tk.Toplevel(self.root)
        self.sym_win.title("Symbols")
        self.sym_win.attributes("-topmost", False)

        self.root.update_idletasks()
        main_x, main_y = self.root.winfo_x(), self.root.winfo_y()
        main_w = self.root.winfo_width()
        self.sym_win.geometry(f"+{main_x + main_w + 10}+{main_y + 30}")

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