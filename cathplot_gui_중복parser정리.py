import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# 가정: GnuplotGenerator 클래스는 동일 프로젝트 내에 정의되어 있다고 가정합니다.
# from gnuplot_generator import GnuplotGenerator


class CathPlotGUI:

    def __init__(self, root):
        self.root = root
        self.root.title("CathPlot GUI Pipeline")
        self.root.geometry("600x500")

        self.plot_dir = os.path.join(os.getcwd(), "plots")
        self.title_counters = {}
        self.plot_processes = []
        self.active_entry = None

        # 레이아웃 및 파일명 설정 변수
        self.layout_var = tk.StringVar(value="1x1")
        self.filename_var = tk.StringVar(value="CathPlot")

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill="both", expand=True)

        # 상단 설정 프레임
        settings_frame = ttk.LabelFrame(main_frame, text="Plot Settings", padding=10)
        settings_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(settings_frame, text="Filename:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        filename_entry = ttk.Entry(settings_frame, textvariable=self.filename_var, width=25)
        filename_entry.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        filename_entry.bind("<FocusIn>", lambda e: self.set_active_entry(filename_entry))

        ttk.Label(settings_frame, text="Layout:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        layout_combo = ttk.Combobox(settings_frame, textvariable=self.layout_var, values=["1x1", "2x2", "3x3"], width=10)
        layout_combo.grid(row=1, column=1, sticky="w", padx=5, pady=5)

        # 하단 액션 버튼 프레임
        action_frame = ttk.Frame(main_frame, padding=10)
        action_frame.pack(fill="x", padx=5, pady=10)

        save_btn = ttk.Button(action_frame, text="Save Plot As...", command=self.execute_save_dialog)
        save_btn.pack(side="left", padx=5)

        print_btn = ttk.Button(action_frame, text="Print Plot", command=self.execute_print_dialog)
        print_btn.pack(side="left", padx=5)

        sym_btn = ttk.Button(action_frame, text="Special Symbols", command=self.open_permanent_symbol_window)
        sym_btn.pack(side="left", padx=5)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def execute_plot_pipeline(self, mode="Interactive", custom_filepath=None, custom_format=None):
        # 단일 플롯 파이프라인 실행 로직
        os.makedirs(self.plot_dir, exist_ok=True)
        target = "screen" if mode == "Interactive" else "file"
        fmt = (custom_format or "pdf").lower() if target == "file" else "interactive"

        if custom_filepath:
            outfile = custom_filepath
        else:
            raw_title = self.filename_var.get().strip() or "CathPlot"
            safe_title = "".join(c for c in raw_title if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"
            next_id = self.title_counters.get(safe_title, 0) + 1
            self.title_counters[safe_title] = next_id
            outfile = os.path.join(
                self.plot_dir,
                f"{safe_title}_{next_id}.plt" if target == "screen" else f"{safe_title}_{next_id}.{fmt}"
            )
        return outfile
        
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
            raw_title = "CathPlot_Multi"
            safe_title = "".join(c for c in raw_title if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"
            next_id = self.title_counters.get(safe_title, 0) + 1
            self.title_counters[safe_title] = next_id
            outfile = os.path.join(
                self.plot_dir,
                f"{safe_title}_{next_id}.plt" if target == "screen" else f"{safe_title}_{next_id}.{fmt}"
            )

        layout = self.layout_var.get()
        generator = GnuplotGenerator(self.plot_dir)
        generator.create_multi_plot_script(selected_plot_defs, outfile, layout=layout, fmt=fmt)
        return outfile

    def _print_and_cleanup(self, pdf_path):
        try:
            if os.path.exists(pdf_path):
                os.startfile(pdf_path, "print")
        except Exception as e:
            print(f"Print execution error: {e}")

    def execute_print_dialog(self):
        temp_pdf = os.path.join(self.plot_dir, "CathPlot_Print_Temp.pdf")
        outfile = self.execute_plot_pipeline(mode="Batch", custom_filepath=temp_pdf, custom_format="pdf")
        if outfile and os.path.exists(outfile):
            threading.Thread(
                target=self._print_and_cleanup, args=(outfile,), daemon=True
            ).start()

    def execute_save_dialog(self):
        file_types = [
            ("PDF Document (*.pdf)", "*.pdf"),
            ("PNG Image (*.png)", "*.png"),
            ("SVG Vector Graphic (*.svg)", "*.svg"),
            ("JPEG Image (*.jpg)", "*.jpg"),
            ("Encapsulated PostScript (*.eps)", "*.eps"),
        ]
        raw_title = self.filename_var.get().strip() or "CathPlot"
        safe_title = "".join(c for c in raw_title if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"

        filepath = filedialog.asksaveasfilename(
            initialdir=self.plot_dir,
            initialfile=safe_title,
            defaultextension=".pdf",
            filetypes=file_types,
            title="Save Plot As..."
        )
        if not filepath:
            return

        fmt = os.path.splitext(filepath)[1].replace(".", "").lower()
        self.execute_plot_pipeline(mode="Batch", custom_filepath=filepath, custom_format=fmt)
        messagebox.showinfo("Success", f"Successfully saved: {os.path.basename(filepath)}")
        self.update_plot_file_list()

    def update_plot_file_list(self):
        pass

    def open_permanent_symbol_window(self):
        sym_win = tk.Toplevel(self.root)
        sym_win.title("Symbol & Special Character Map")
        sym_win.geometry("350x250")
        
        symbols = ["Ω", "Δ", "Θ", "Lambda", "μ", "π", "σ", "°C", "≥", "≤", "≠", "approx"]
        
        frame = ttk.Frame(sym_win, padding=10)
        frame.pack(fill="both", expand=True)

        def insert_sym(s):
            if self.active_entry:
                try:
                    self.active_entry.insert(tk.INSERT, s)
                except Exception:
                    pass

        for idx, sym in enumerate(symbols):
            btn = ttk.Button(frame, text=sym, width=5, command=lambda s=sym: insert_sym(s))
            btn.grid(row=idx // 4, column=idx % 4, padx=5, pady=5)

    def set_active_entry(self, entry):
        self.active_entry = entry

    def on_closing(self):
        for proc in self.plot_processes:
            try:
                proc.terminate()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = CathPlotGUI(root)
    root.mainloop()        