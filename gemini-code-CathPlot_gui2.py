import os
import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLineEdit, QComboBox, QLabel, QFileDialog, QDialog, QScrollArea
)

class DatRowWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = ""
        self.x_col = 0        # DAT 파일별 독립적인 X열 지정 (단일 변수)
        self.y_col = 1        # DAT 파일별 Y열 지정
        self.axis = "Y1"      # "Y1" 또는 "Y2"
        self.color = "blue"
        self.style = "lines"
        self.legend_mode = "Integrated (Default)"
        self.title = ""
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 1. 파일 경로 입력 필드
        self.path_input = QLineEdit(self)
        self.path_input.setPlaceholderText("DAT file path...")
        
        # 2. X축 선택 버튼 (클릭 시 독립적인 X열 지정 다이얼로그 호출)
        self.btn_x_select = QPushButton(f"X: Col {self.x_col}", self)
        self.btn_x_select.setFixedWidth(80)
        self.btn_x_select.clicked.connect(self.open_x_selection_dialog)

        # 3. Y축 지정 입력 필드
        self.y_col_input = QLineEdit(str(self.y_col), self)
        self.y_col_input.setFixedWidth(40)
        self.y_col_input.textChanged.connect(self.update_y_col)

        # 4. Y1 / Y2 축 독립 선택 콤보박스
        self.axis_combo = QComboBox(self)
        self.axis_combo.addItems(["Y1", "Y2"])
        self.axis_combo.setCurrentText(self.axis)
        self.axis_combo.currentTextChanged.connect(self.update_axis)

        # 5. 상세 스타일 팝업 호출 버튼 (⚙️ Style)
        self.btn_detail_style = QPushButton("⚙️ Style", self)
        self.btn_detail_style.setFixedWidth(70)
        self.btn_detail_style.clicked.connect(self.open_detail_style_dialog)

        # 6. 행 삭제 버튼 [X]
        self.btn_delete = QPushButton("X", self)
        self.btn_delete.setFixedWidth(30)

        layout.addWidget(self.path_input, stretch=4)
        layout.addWidget(self.btn_x_select)
        layout.addWidget(QLabel("Y:"))
        layout.addWidget(self.y_col_input)
        layout.addWidget(self.axis_combo)
        layout.addWidget(self.btn_detail_style)
        layout.addWidget(self.btn_delete)

    def open_x_selection_dialog(self):
        """각 DAT 파일마다 단 1개의 X 변수(열)를 독립적으로 선택하는 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Select X Column (1 Variable)")
        dialog.resize(250, 150)
        
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.addWidget(QLabel("Enter X Column Index (0-based):"))
        
        input_x = QLineEdit(str(self.x_col), dialog)
        dlg_layout.addWidget(input_x)

        btn_ok = QPushButton("OK", dialog)
        def apply_x():
            try:
                val = int(input_x.text())
                if val >= 0:
                    self.x_col = val
                    self.btn_x_select.setText(f"X: Col {self.x_col}")
                    dialog.accept()
            except ValueError:
                pass
        btn_ok.clicked.connect(apply_x)
        dlg_layout.addWidget(btn_ok)
        dialog.exec_()

    def update_y_col(self, text):
        try:
            self.y_col = int(text)
        except ValueError:
            pass

    def update_axis(self, text):
        self.axis = text

    def open_detail_style_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Curve Detail Settings")
        dialog.resize(320, 240)
        
        dlg_layout = QVBoxLayout(dialog)

        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("Title:"))
        self.input_title = QLineEdit(self.title)
        title_layout.addWidget(self.input_title)
        dlg_layout.addLayout(title_layout)

        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self.combo_color = QComboBox()
        self.combo_color.addItems(["blue", "red", "green", "black", "orange", "purple"])
        self.combo_color.setCurrentText(self.color)
        color_layout.addWidget(self.combo_color)
        dlg_layout.addLayout(color_layout)

        style_layout = QHBoxLayout()
        style_layout.addWidget(QLabel("Line Style:"))
        self.combo_style = QComboBox()
        self.combo_style.addItems(["lines", "points", "linespoints", "impulses"])
        self.combo_style.setCurrentText(self.style)
        style_layout.addWidget(self.combo_style)
        dlg_layout.addLayout(style_layout)

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
        self.resize(800, 500)
        
        self.template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template")
        os.makedirs(self.template_dir, exist_ok=True)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # -------------------------------------------------------------
        # 상단 제어 패널 ([X], [+] 버튼 및 Template, Mode)
        # -------------------------------------------------------------
        control_layout = QHBoxLayout()

        self.btn_delete_row = QPushButton("X", self)
        self.btn_delete_row.setFixedWidth(30)
        self.btn_delete_row.clicked.connect(self.remove_dat_row)
        
        # [+] 버튼을 [X] 버튼 우측으로 이동 배치
        self.btn_add_row = QPushButton("+", self)
        self.btn_add_row.setFixedWidth(30)
        self.btn_add_row.clicked.connect(self.add_dat_row)

        control_layout.addWidget(self.btn_delete_row)
        control_layout.addWidget(self.btn_add_row)

        self.btn_template_read = QPushButton("Template Read", self)
        self.btn_template_read.clicked.connect(self.load_template)

        self.btn_template_save = QPushButton("Template Save", self)
        self.btn_template_save.clicked.connect(self.save_template)

        self.combo_mode = QComboBox(self)
        self.combo_mode.addItems(["Interactive", "Batch"])
        self.combo_mode.setCurrentIndex(0)

        control_layout.addWidget(self.btn_template_read)
        control_layout.addWidget(self.btn_template_save)
        control_layout.addWidget(QLabel("Mode:"))
        control_layout.addWidget(self.combo_mode)
        
        control_layout.addStretch(1)
        main_layout.addLayout(control_layout)

        # -------------------------------------------------------------
        # DAT 파일 행들이 쌓이는 스크롤 영역 (누락되었던 영역 복원)
        # -------------------------------------------------------------
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        
        self.scroll_content = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_content)
        self.rows_layout.addStretch(1) # 위젯들이 위로 밀착되도록 스트레치 추가
        
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)

        # 초기 실행 시 기본 행 1개 생성
        self.add_dat_row()

    def add_dat_row(self):
        """[+] 버튼 클릭 시 새로운 DAT 행 추가"""
        row_widget = DatRowWidget(self)
        # 삭제 버튼 연결
        row_widget.btn_delete.clicked.connect(lambda: self.remove_specific_row(row_widget))
        # 스트레치(마지막 빈 공간) 바로 위에 삽입
        count = self.rows_layout.count()
        self.rows_layout.insertWidget(count - 1, row_widget)

    def remove_dat_row(self):
        """마지막 행 삭제 [X]"""
        count = self.rows_layout.count()
        if count > 2: # 스트레치 제외하고 최소 1개는 유지
            item = self.rows_layout.itemAt(count - 2)
            if item and item.widget():
                widget = item.widget()
                self.rows_layout.removeWidget(widget)
                widget.deleteLater()

    def remove_specific_row(self, row_widget):
        """특정 행 개별 삭제"""
        if self.rows_layout.count() > 2:
            self.rows_layout.removeWidget(row_widget)
            row_widget.deleteLater()

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