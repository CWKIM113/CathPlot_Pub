import os
import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLineEdit, QComboBox, QLabel, QFileDialog, QDialog, QCheckBox
)

class DatRowWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = ""
        self.color = "blue"
        self.style = "lines"
        self.legend_mode = "Integrated (Default)"
        self.title = ""
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.path_input = QLineEdit(self)
        self.path_input.setPlaceholderText("DAT file path...")
        
        self.x_col_input = QLineEdit("0", self)
        self.x_col_input.setFixedWidth(40)
        self.y_col_input = QLineEdit("1", self)
        self.y_col_input.setFixedWidth(40)

        self.axis_combo = QComboBox(self)
        self.axis_combo.addItems(["Y1", "Y2"])

        # 공간 절약을 위한 상세 스타일 팝업 호출 버튼
        self.btn_detail_style = QPushButton("⚙️ Style", self)
        self.btn_detail_style.setFixedWidth(70)
        self.btn_detail_style.clicked.connect(self.open_detail_style_dialog)

        # 행 삭제 버튼 [X]
        self.btn_delete = QPushButton("X", self)
        self.btn_delete.setFixedWidth(30)

        layout.addWidget(self.path_input, stretch=4)
        layout.addWidget(QLabel("X:"))
        layout.addWidget(self.x_col_input)
        layout.addWidget(QLabel("Y:"))
        layout.addWidget(self.y_col_input)
        layout.addWidget(self.axis_combo)
        layout.addWidget(self.btn_detail_style)
        layout.addWidget(self.btn_delete)

    def open_detail_style_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Curve Detail Settings")
        dialog.resize(320, 240)
        
        dlg_layout = QVBoxLayout(dialog)

        # 곡선 타이틀 입력
        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("Title:"))
        self.input_title = QLineEdit(self.title)
        title_layout.addWidget(self.input_title)
        dlg_layout.addLayout(title_layout)

        # 색상 선택
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self.combo_color = QComboBox()
        self.combo_color.addItems(["blue", "red", "green", "black", "orange", "purple"])
        self.combo_color.setCurrentText(self.color)
        color_layout.addWidget(self.combo_color)
        dlg_layout.addLayout(color_layout)

        # 선 스타일 선택
        style_layout = QHBoxLayout()
        style_layout.addWidget(QLabel("Line Style:"))
        self.combo_style = QComboBox()
        self.combo_style.addItems(["lines", "points", "linespoints", "impulses"])
        self.combo_style.setCurrentText(self.style)
        style_layout.addWidget(self.combo_style)
        dlg_layout.addLayout(style_layout)

        # Legend 모드 선택
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(QLabel("Legend Mode:"))
        self.combo_legend_mode = QComboBox()
        self.combo_legend_mode.addItems([
            "Integrated (Default)", 
            "Show Y1 Only", 
            "Show Y2 Only", 
            "Hide All"
        ])
        self.combo_legend_mode.setCurrentText(self.legend_mode)
        legend_layout.addWidget(self.combo_legend_mode)
        dlg_layout.addLayout(legend_layout)

        btn_apply = QPushButton("Apply & Close", dialog)
        btn_apply.clicked.connect(lambda: self.save_dialog_values(dialog))
        dlg_layout.addWidget(btn_apply)

        dialog.exec_()

    def save_dialog_values(self, dialog):
        self.title = self.input_title.text()
        self.color = self.combo_color.currentText()
        self.style = self.combo_style.currentText()
        self.legend_mode = self.combo_legend_mode.currentText()
        dialog.accept()


class CathPlotGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CathPlot Generator")
        self.resize(750, 450)
        
        # Template 디렉토리 준비
        self.template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template")
        os.makedirs(self.template_dir, exist_ok=True)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # -------------------------------------------------------------
        # DAT 파일 제어용 컨트롤 레이아웃 ([X], [+] 버튼 및 Template, Mode)
        # -------------------------------------------------------------
        control_layout = QHBoxLayout()

        self.btn_delete_row = QPushButton("X", self)
        self.btn_delete_row.setFixedWidth(30)
        
        # [+] 버튼을 [X] 버튼 우측으로 이동 배치
        self.btn_add_row = QPushButton("+", self)
        self.btn_add_row.setFixedWidth(30)

        control_layout.addWidget(self.btn_delete_row)
        control_layout.addWidget(self.btn_add_row)

        # Template Read / Save 버튼
        self.btn_template_read = QPushButton("Template Read", self)
        self.btn_template_read.clicked.connect(self.load_template)

        self.btn_template_save = QPushButton("Template Save", self)
        self.btn_template_save.clicked.connect(self.save_template)

        # Interactive / Batch 모드 선택 (Interactive 기본)
        self.combo_mode = QComboBox(self)
        self.combo_mode.addItems(["Interactive", "Batch"])
        self.combo_mode.setCurrentIndex(0)

        control_layout.addWidget(self.btn_template_read)
        control_layout.addWidget(self.btn_template_save)
        control_layout.addWidget(QLabel("Mode:"))
        control_layout.addWidget(self.combo_mode)
        
        control_layout.addStretch(1)
        main_layout.addLayout(control_layout)

    def save_template(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Template", self.template_dir, "Gnuplot Template (*.plt)"
        )
        if file_path:
            print(f"템플릿 저장 완료: {file_path}")

    def load_template(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Template", self.template_dir, "Gnuplot Template (*.plt)"
        )
        if file_path:
            print(f"템플릿 불러오기 완료: {file_path}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = CathPlotGUI()
    gui.show()
    sys.exit(app.exec_())