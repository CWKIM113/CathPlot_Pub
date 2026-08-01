import os
import sys
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QCheckBox,
    QPushButton, QLineEdit, QComboBox, QLabel, QFileDialog, QDialog, QScrollArea, QGroupBox, QSizePolicy
)

class DatRowWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = ""
        self.x_col = 0        
        self.y_col = 1        
        self.axis = "Y1"      
        self.color = "blue"
        self.style = "lines"
        self.legend_mode = "Integrated (Default)"
        self.title = ""
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.path_input = QLineEdit(self)
        self.path_input.setPlaceholderText("DAT file path...")
        
        self.btn_browse = QPushButton("Browse...", self)
        self.btn_browse.setFixedWidth(75)
        self.btn_browse.clicked.connect(self.browse_file)

        self.btn_x_select = QPushButton(f"X: Col {self.x_col}", self)
        self.btn_x_select.setFixedWidth(80)
        self.btn_x_select.clicked.connect(self.open_x_selection_dialog)

        self.y_col_input = QLineEdit(str(self.y_col), self)
        self.y_col_input.setFixedWidth(40)
        self.y_col_input.textChanged.connect(self.update_y_col)

        self.axis_combo = QComboBox(self)
        self.axis_combo.addItems(["Y1", "Y2"])
        self.axis_combo.setCurrentText(self.axis)
        self.axis_combo.currentTextChanged.connect(self.update_axis)

        self.btn_detail_style = QPushButton("⚙️ Style", self)
        self.btn_detail_style.setFixedWidth(75)
        self.btn_detail_style.clicked.connect(self.open_detail_style_dialog)

        self.btn_delete = QPushButton("X", self)
        self.btn_delete.setFixedWidth(30)

        layout.addWidget(self.path_input, stretch=4)
        layout.addWidget(self.btn_browse)
        layout.addWidget(self.btn_x_select)
        layout.addWidget(QLabel("Y:"))
        layout.addWidget(self.y_col_input)
        layout.addWidget(self.axis_combo)
        layout.addWidget(self.btn_detail_style)
        layout.addWidget(self.btn_delete)

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open DAT File", "", "DAT Files (*.dat);;All Files (*)")
        if file_path:
            self.path_input.setText(file_path)
            self.file_path = file_path

    def open_x_selection_dialog(self):
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
        self.resize(900, 700)
        
        self.template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template")
        os.makedirs(self.template_dir, exist_ok=True)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # -------------------------------------------------------------
        # 1. 최상단 글로벌 컨트롤 영역 (Template, Mode)
        # -------------------------------------------------------------
        top_control_layout = QHBoxLayout()

        self.btn_template_read = QPushButton("Template Read", self)
        self.btn_template_read.clicked.connect(self.load_template)

        self.btn_template_save = QPushButton("Template Save", self)
        self.btn_template_save.clicked.connect(self.save_template)

        self.combo_mode = QComboBox(self)
        self.combo_mode.addItems(["Interactive", "Batch"])
        self.combo_mode.setCurrentIndex(0)

        top_control_layout.addWidget(self.btn_template_read)
        top_control_layout.addWidget(self.btn_template_save)
        top_control_layout.addWidget(QLabel("Mode:"))
        top_control_layout.addWidget(self.combo_mode)
        top_control_layout.addStretch(1)
        
        main_layout.addLayout(top_control_layout)

        # -------------------------------------------------------------
        # 2. 축 및 범례 설정 그룹 박스 (Axis & Legend Settings)
        # -------------------------------------------------------------
        settings_group = QGroupBox("Plot Settings (Labels, Ranges & Legend)", self)
        settings_layout = QVBoxLayout(settings_group)

        # 라벨 설정 레이아웃
        label_layout = QHBoxLayout()
        label_layout.addWidget(QLabel("X Label:"))
        self.input_xlabel = QLineEdit("X", self)
        label_layout.addWidget(self.input_xlabel)

        label_layout.addWidget(QLabel("Y1 Label:"))
        self.input_ylabel = QLineEdit("Y1", self)
        label_layout.addWidget(self.input_ylabel)

        label_layout.addWidget(QLabel("Y2 Label:"))
        self.input_y2label = QLineEdit("Y2", self)
        label_layout.addWidget(self.input_y2label)
        settings_layout.addLayout(label_layout)

        # 범위(Range) 설정 레이아웃
        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("X Range:"))
        self.input_xmin = QLineEdit(self)
        self.input_xmin.setPlaceholderText("min")
        self.input_xmax = QLineEdit(self)
        self.input_xmax.setPlaceholderText("max")
        range_layout.addWidget(self.input_xmin)
        range_layout.addWidget(self.input_xmax)

        range_layout.addWidget(QLabel("Y1 Range:"))
        self.input_ymin = QLineEdit(self)
        self.input_ymin.setPlaceholderText("min")
        self.input_ymax = QLineEdit(self)
        self.input_ymax.setPlaceholderText("max")
        range_layout.addWidget(self.input_ymin)
        range_layout.addWidget(self.input_ymax)
        settings_layout.addLayout(range_layout)

        # 범례(Legend) 및 커스텀 위치(X, Y) 설정 레이아웃
        legend_layout = QHBoxLayout()
        self.chk_legend_on = QCheckBox("Show Legend", self)
        self.chk_legend_on.setChecked(True)

        self.combo_legend_pos = QComboBox(self)
        self.combo_legend_pos.addItems(["right top", "right bottom", "left top", "left bottom", "outside right"])

        self.chk_legend_custom = QCheckBox("Custom Pos (X,Y):", self)
        self.input_legend_x = QLineEdit(self)
        self.input_legend_x.setPlaceholderText("0.8")
        self.input_legend_x.setFixedWidth(50)
        self.input_legend_y = QLineEdit(self)
        self.input_legend_y.setPlaceholderText("0.8")
        self.input_legend_y.setFixedWidth(50)

        self.chk_legend_box = QCheckBox("Box", self)
        self.chk_legend_box.setChecked(True)

        legend_layout.addWidget(self.chk_legend_on)
        legend_layout.addWidget(self.combo_legend_pos)
        legend_layout.addWidget(self.chk_legend_custom)
        legend_layout.addWidget(self.input_legend_x)
        legend_layout.addWidget(self.input_legend_y)
        legend_layout.addWidget(self.chk_legend_box)
        legend_layout.addStretch(1)

        settings_layout.addLayout(legend_layout)
        main_layout.addWidget(settings_group)

        # -------------------------------------------------------------
        # 3. DAT 파일 목록 그룹 박스 (DAT Files)
        # -------------------------------------------------------------
        dat_group_box = QGroupBox("DAT Files", self)
        dat_group_layout = QVBoxLayout(dat_group_box)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        
        self.scroll_content = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_content)
        self.rows_layout.setAlignment(Qt.AlignTop)
        self.rows_layout.setContentsMargins(2, 2, 2, 2)
        
        self.scroll_area.setWidget(self.scroll_content)
        dat_group_layout.addWidget(self.scroll_area)

        # 행 추가/삭제 버튼 ([X], [+] 중앙 정렬 혹은 좌측 정렬)
        btn_layout = QHBoxLayout()
        self.btn_delete_row = QPushButton("X", self)
        self.btn_delete_row.setFixedWidth(35)
        self.btn_delete_row.clicked.connect(self.remove_dat_row)

        self.btn_add_row = QPushButton("+", self)
        self.btn_add_row.setFixedWidth(35)
        self.btn_add_row.clicked.connect(self.add_dat_row)

        btn_layout.addWidget(self.btn_delete_row)
        btn_layout.addWidget(self.btn_add_row)
        btn_layout.addStretch(1)

        dat_group_layout.addLayout(btn_layout)
        main_layout.addWidget(dat_group_box)

        # 초기 실행 시 기본 행 1개 생성
        self.add_dat_row()

    def add_dat_row(self):
        row_widget = DatRowWidget(self)
        row_widget.btn_delete.clicked.connect(lambda: self.remove_specific_row(row_widget))
        self.rows_layout.addWidget(row_widget)

    def remove_dat_row(self):
        count = self.rows_layout.count()
        if count > 1:
            item = self.rows_layout.itemAt(count - 1)
            if item and item.widget():
                widget = item.widget()
                self.rows_layout.removeWidget(widget)
                widget.deleteLater()

    def remove_specific_row(self, row_widget):
        if self.rows_layout.count() > 1:
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