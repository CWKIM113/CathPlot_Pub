# -*- coding: utf-8 -*-

import tkinter as tk
import os
import shlex  # Batch Set List(txt)에서 ""로 감싼 공백 포함 파일명을 안전하게 나누는 데 사용(_apply_list_file)
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
import copy

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

from data_parser import CathenaDatParser, save_json, is_comment_or_blank, strip_inline_comment
from gnu_generator import (PlotDefinition, CurveDefinition, FunctionCurveDefinition, GnuplotGenerator,
                            PIP_OVERLAY_CHROMA_KEY, DASH_PATTERNS)

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
    # [수정 - 요청] "Style box 폭을 줄이기 위해 Short-Dash -> Short-D로 축약" -
    # 최장 옵션이 10자(Short-Dash)에서 7자(Short-D/Dash-2D 동률)로 줄어서
    # STYLE_COL_PX도 같이 줄일 수 있게 됨(아래 STYLE_COL_PX 참고).
    "Short-D": "shortdash",
    "Dash-2D": "dashdotdot",  # Dash-Dot-Dot (이점쇄선)
}

# Marker(점 마커) 모양 - 표시 라벨 -> (속 빈 pointtype, 채운 pointtype)
# Cross/Star는 gnuplot에 채운/빈 구분이 따로 없어 동일값 사용
# [추가 - 요청] "마커에 좌,우 방향 세모 추가" - gnuplot 내장 숫자
# pointtype에는 좌/우 삼각형이 없어서(위/아래만 8·9/10·11로 있음),
# gnuplot 5+ pngcairo/qt/wxt가 지원하는 "유니코드 문자를 pointtype으로
# 직접 쓰는" 기능으로 구현함(실제 렌더링으로 좌우 방향과 속 빈/채움
# 둘 다 정상 표시되는 것 확인). 숫자가 아니라 문자열이므로, 이 값을
# 쓰는 쪽(gnu_generator의 pointtype 출력부)이 정수/문자열 둘 다
# 처리하도록 맞춰야 함.
MARKER_SHAPE_MAP = {
    "None": (None, None),
    "Circle": (6, 7),
    "Square": (4, 5),
    # [수정 - 사용자 요청] "marker 순서를 다이아몬드를 세모 앞으로" - 표시
    # 순서(=이 dict의 키 순서를 그대로 쓰는 MARKER_SHAPE_LIST, 콤보박스
    # 목록 순서)만 바꾼다. 각 gnuplot pointtype 번호 자체는 그대로.
    "Diamond": (12, 13),
    "Triangle": (8, 9),
    "Tri-Down": (10, 11),
    "Tri-Left": ("◁", "◀"),
    "Tri-Right": ("▷", "▶"),
    "Cross": (1, 1),
    # [추가 - 사용자 요청] "gnuplot에 오각형도 있는지 -> Pentagon을 별
    # 앞에 추가" - 실제 gnuplot(pngcairo)으로 pointtype 14/15가 속
    # 빈/채운 오각형임을 렌더링으로 확인 후 추가.
    "Pentagon": (14, 15),
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
        self.root.title("CathPlot V1.0      Developed by Cheolwoo Kim at 09/23/2026.")
        # [수정] 노트북처럼 시스템 DPI가 다른 환경에서 초기 창이 작게 보인다는
        # 피드백으로 창 크기(아래 geometry)만 20% 키움
        # [수정 - 사용자 요청] "가로 길이도 flexible하게(노트북에선 가로를
        # 매번 늘려야 해서 불편함), 상한선은 둬야죠" - 세로(위 required_height)
        # 와 같은 방식으로 화면 실제 가로 해상도(winfo_screenwidth) 기준으로
        # 계산한다. [주의] 아래 required_height 옆 "되돌림" 주석 참고 -
        # winfo_reqwidth()(위젯이 "필요하다"고 보고하는 폭)로 자동 계산했다가
        # file/var 목록의 가로 스크롤 캔버스가 실제보다 훨씬 작은 값을
        # 보고해서 우측이 잘리는 심각한 문제가 있었던 전례가 있음 - 이번엔
        # 그것과 다르게 위젯이 아니라 "실제 모니터 해상도"를 기준으로 삼아서
        # 그 문제를 그대로 재현하지 않는다. self.root/self.win_w를 아래
        # 필요한 곳(재계산되는 두 번째 geometry 호출)에서도 재사용해야 하므로
        # 인스턴스 속성으로 저장해둔다.
        # [되돌림 - 사용자 재보고] "PC에서는 다 보였는데 1500으로 올렸더니
        # 노트북에서도 너무 넓어져서 남는 여백이 생김(Box에서 curves 끝까지
        # 정도 폭) - 줄일 필요 있음. flexible이 좋고 아래에 좌우 scroll
        # 있으면 좋겠음" - 1200이 PC에서는 원래 "다 보임"(=충분했음) 이었던
        # 걸로 봐서, 위 1500행 상향이 과했음 - 1200으로 되돌린다. 가로
        # 스크롤이 안 보였던 원인은 폭 부족이 아니라 다른 문제(각 섹션
        # 자체의 가로 스크롤바 - file_hscrollbar/hscrollbar/plot_hscrollbar
        # - 가 세로 공간 부족으로 화면 밖에 밀려났을 가능성)로 보이므로,
        # 폭을 다시 올리는 대신 세로 required_height 클램프(아래)가 그
        # 스크롤바들 자리까지 확실히 포함하도록 두고 지켜본다.
        # [수정 - 사용자 요청] "Curves가 다 보이도록 가로크기를 조금만 더
        # 키울까요?" - Curves/Function/Marker 버튼을 각 줄 왼쪽으로 옮겨서
        # (위 참고) 이제 창이 좁아도 이 버튼들 자체는 항상 보이지만, 그
        # 뒤에 이어지는 Pos/Align/Box W/H 같은 필드까지 여유 있게 보이도록
        # 최소/최대 폭을 60px씩 살짝 올림(900->960, 1200->1260).
        # [수정 - 사용자 요청] "DAT file 3개가 들어갈 정도로(=조금 줄여줘)" -
        # 이후 Function/Marker를 별도 줄로 완전히 옮기면서 Legend 줄의 폭
        # 압박이 더 줄어들어, 위에서 올렸던 폭을 다시 조금 낮춰도 됨
        # (960->920, 1260->1220).
        # [수정 - 사용자 요청] "Dat list의 Color/Style을 팝업으로 옮겼으니
        # 창 폭도 더 줄여보자, 대신 다른 줄이 넘치면 알려달라" - 실제
        # 병목은 Dat list가 아니라 legend1_row/legend2_row였음(각 699px,
        # 최대폭 1220px보다 이미 넘치는 상태였음 - Xvfb 헤드리스 실측으로
        # 확인). Box W/H, Legend Font/Size, Box Thick를 전부 "Legend
        # Detail" 팝업(_open_legend_detail_popup)으로 옮겨 그 두 줄을
        # 562px까지 줄이고 나서 다시 실측(plot_frame 필요 폭 1164~1176px)
        # 해 최대폭을 그만큼만 남기고 낮춘다(1220->1190, 여유 ~15~25px).
        # 최소폭(920)은 원래도 이 요청과 무관한 별개 이슈(아주 작은 화면
        # 에서는 이 최소폭보다도 legend 줄이 넓어 스크롤 없이 잘렸었는데,
        # 이번 축소로 그 문제도 완화는 됐지만 완전히 해결된 건 아님)라
        # 그대로 둔다.
        self._win_w = max(920, min(1190, self.root.winfo_screenwidth() - 80))
        self.root.geometry(f"{self._win_w}x1030")
        self.root.tk.call('tk', 'windowingsystem')

        # [수정 - 사용자 보고 버그] "맨 마지막 PLOT 버튼 줄이 노트북에선
        # 잘려서 나옴(PC 큰 화면은 문제없음)" - 이 버튼 줄(self.button_frame)
        # 은 원래 아래쪽(__init__ 끝부분, PLOT/SAVE/PRINT 버튼을 채워 넣는
        # 자리)에서야 비로소 만들고 pack(side="bottom")했는데, Tk의 pack은
        # "먼저 pack된 쪽이 공간을 먼저 차지"하는 방식이라 - file/var 목록,
        # Plot Setting 등 그 앞에 먼저 pack되는 훨씬 큰 섹션들이 이미 공간을
        # 다 차지해버리면, 정작 이 버튼 줄이 창 높이 밖으로 밀려날 수 있음
        # (화면이 작아 전체 내용이 다 안 들어가는 노트북에서 특히 그럼 -
        # PIP 팝업의 "닫기 버튼 항상 보이게" 수정과 완전히 같은 원인/해법).
        # Frame 객체 자체와 pack(side="bottom")만 여기서 미리 해두고(공간을
        # 먼저 예약), 실제 버튼들을 채워 넣는 코드는 원래 위치에 그대로
        # 둔다(이미 pack된 Frame에 나중에 자식 위젯을 추가하는 것은 아무
        # 문제 없음).
        self.button_frame = ttk.Frame(self.root)
        self.button_frame.pack(side="bottom", fill="x", padx=10, pady=4)

        self.parser = CathenaDatParser()
        self.file_rows = []
        self.comment_list = []
        self.arrow_list = []
        self.circle_list = []
        # [추가 - 요청] Function Curve(2D) - sin(x) 같은 삼각함수/다항식/사용자
        # 정의 함수를 데이터 없이 gnuplot 수식만으로 그리는 커브 목록. 팝업
        # 안에서만 행을 추가/삭제하므로(화면 본문에 자리를 새로 만들지 않음),
        # 팝업이 닫혀 있어도 값을 유지하기 위해 여기서 별도 리스트로 보관한다.
        self.function_curves_list = []

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

        # [추가 - 요청] "X 버튼으로 닫을 때 Batch Set/Queue가 백그라운드로 실행
        # 중이면 이름을 보여주고 정말 종료할지 확인" - 실행 중인 배치 작업을
        # {job_id: 표시용 이름} 형태로 추적한다. _register_batch_job/
        # _unregister_batch_job이 시작/종료 시 채우고 비우며, on_closing에서
        # 이 dict가 비어있지 않으면 경고 후 선택하게 한다.
        self._active_batch_jobs = {}
        self._batch_job_seq = 0
        self._batch_job_lock = threading.Lock()

        # [추가 - 요청] "sorted dat 삭제를 CathPlot이 마음대로 정하지 말고
        # 사용자 옵션으로 둬라" - 기본값은 꺼짐(=안 지움, 재현성 우선).
        # "Clean Past Plots" 버튼 옆 체크박스로 켜면 종료(X 버튼) 시
        # plot_dir/temp_sorted를 지운다. on_closing에서 이 값을 확인한다.
        self.delete_temp_on_close_var = tk.BooleanVar(value=False)

        self.selected_y1_vars = {}
        self.selected_y2_vars = {}
        # [추가 - 요청] "선택한 순서대로 curve를 그려주기(Legend/default title
        # 순서에도 연동)" - Y1/Y2 체크박스를 클릭한 순서를 그대로 기억한다
        # (make_y_excl_cmd 참고). 체크 해제하면 그 키만 빠지고, 다시 체크하면
        # 원래 있던 자리가 아니라 맨 뒤에 새로 추가됨(재정렬 아니라 이어붙이기 -
        # Multi-Plot "선택 순서대로 배치"와 동일한 규칙). _ordered_selected_keys()
        # 가 이 리스트를 실제 그리기/legend/Batch Queue 순서로 변환한다.
        self._curve_order = []
        # [추가 - 사용자 보고 버그] "Legend1 Curves로 순서를 바꾸면 Legend2도
        # 같이 바뀜 - 각각 독립적으로" - 지금까지는 두 Legend의 "Curves"
        # 팝업이 이 하나의 self._curve_order만 같이 건드려서 서로 분리될 수
        # 없었음. 각 Legend 박스 "안에서의" 표시 순서만 따로 추적하는 두 개의
        # 독립적인 리스트("1"=Legend1, "2"=Legend2) - 아직 한 번도 그 Legend의
        # 팝업에서 순서를 안 바꾼 curve는 이 리스트에 없어도 되고, 그때는
        # self._curve_order(원래 클릭 순서)를 그대로 기본값으로 쓴다
        # (_legend_ordered_keys 참고).
        self._legend_order = {"1": [], "2": []}
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
        # [추가 - 요청] "Cubic Spline" - 팝업에 새 칸을 넣을 자리가 없어서
        # (요청: "선택된 커버에 대해 check box로 지정") Var list 행 자체에
        # 체크박스 하나만 추가 - 켜면 이 curve에 gnuplot의 자연 3차 스플라인
        # 보간(smooth csplines)을 적용한다(gnu_generator.CurveDefinition.
        # smooth_csplines 참고).
        self.smooth_csplines_vars = {}

        self.active_entry = None
        self.last_opened_dir = None
        self.title_counters = {}
        self.multi_counters = {}
        self.active_plots_cache = {}
        self.plot_processes = []
        # [추가 - 사용자 보고 버그] "덮어쓰기 plot 이후 replot 하면 plt
        # 파일은 update 되지만 화면의 창은 같은 이름으로 추가만 됨(이전
        # 창은 안 닫힘)" - "덮어쓰기(번호 증가 안 함)" 옵션은 항상 같은
        # base_name(예: "out111_1")으로 .plt를 다시 쓰는데, Interactive는
        # 매번 새 gnuplot 프로세스/창을 띄우므로 같은 제목의 창이 그대로
        # 겹쳐 쌓였다 - 이 dict로 "그 base_name으로 마지막에 연 창"을
        # 기억해두고, 덮어쓰기로 같은 이름을 다시 그릴 때 그 이전 창을
        # 먼저 닫는다.
        self.plot_process_by_title = {}
        self.history_plots = []  # 멀티플롯 이력 바인딩용 배열 생성

        self.y1_title_auto = True
        self.y2_title_auto = True
        self.x_title_auto = True
        # [추가 - 사용자 보고 버그] "Axis Title처럼, 사용자가 입력한 경우
        # Plot Title도 계속 사용하게" - X/Y1/Y2 축 제목과 같은 "칸이
        # 비어있으면 자동(파일에서 따라옴), 사용자가 뭔가 입력하면 그
        # 값을 유지" 규칙을 Plot Title에도 그대로 적용한다.
        self.plot_title_auto = True

        self._updating_y1 = False
        self._updating_y2 = False
        self._updating_x = False
        self._updating_title = False

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

    def _mk_btn(self, parent, text, command, color="secondary", fg="white", btn_pady=0, btn_width=None, btn_padx=8, grid_kw=None, **pack_kw):
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
        # [추가 - 요청] "Batch Queue 버튼을 Batch Set 버튼 정도 높이로" - 위
        # pady=0 기본값은 옆에 Entry/Combobox가 있는 촘촘한 줄(Browse 등)에나
        # 맞는 값이라, Batch Queue/Batch Set처럼 버튼만 단독으로 한 줄에 있는
        # 다이얼로그는 좀 더 여유 있는 높이가 자연스러움 - 필요할 때만
        # btn_pady로 내부 상하 여백을(기본은 0, 기존 호출부 영향 없음),
        # ▲/▼처럼 좁은 고정폭이 필요하면 btn_width로 지정할 수 있게 한다.
        kwargs = dict(
            text=text, command=command,
            font=("Malgun Gothic", 9, "bold"), bg=bg, fg=fg,
            activebackground=dark, activeforeground=fg,
            relief="raised", bd=1, padx=btn_padx, pady=btn_pady,
        )
        if btn_width is not None:
            kwargs["width"] = btn_width
        b = tk.Button(parent, **kwargs)
        # [추가 - 사용자 요청] "Format을 이름 기준과 정확히 정렬" - 서로 다른
        # 줄(버튼 개수가 다름)에 있는 두 요소를 픽셀 단위로 정확히 맞추려면
        # grid의 "같은 컬럼은 모든 행에서 항상 같은 x에서 시작" 특성이
        # 필요함(pack은 그런 보장이 없고, 렌더링 후 winfo_x()로 재는 방식은
        # 다이얼로그가 아직 화면에 map되기 전이라 실측 실패 확인됨) -
        # grid_kw가 주어지면 pack 대신 grid를 쓴다(기존 호출부는 전부
        # pack_kw만 쓰므로 동작 그대로 유지).
        if grid_kw is not None:
            b.grid(**grid_kw)
        else:
            b.pack(**pack_kw)
        return b

    def _bind_hscroll_wheel(self, canvas):
        # [추가 - 요청] "모든 block에서 가로 스크롤 가능하게" - 가로
        # 스크롤바 자체는 마우스로 드래그해야 해서 불편할 수 있으니, 세로
        # 휠 스크롤(Tkinter/Windows 기본)과 대칭으로 Shift+휠도 가로
        # 스크롤에 쓸 수 있게 한다(엑셀 등 다른 프로그램에서도 흔한 관례).
        def _on_shift_wheel(event):
            canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"
        canvas.bind("<Shift-MouseWheel>", _on_shift_wheel)

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

        # [추가 - 사용자 요청] "Browse 칸에 절대경로 대신 상대경로만 보이게" -
        # 각 dat 파일 행의 표시 텍스트를 cwd 기준 상대경로로 바꾸면(아래
        # _display_relpath 참고), 서로 다른 case 폴더의 같은 이름 파일이
        # 화면에서 항상 똑같이(예: "data/out111.dat") 보여 "지금 어느 case를
        # 보고 있는지" 구분이 오히려 더 어려워질 수 있음(사용자 지적) - 그래서
        # "기준이 되는 cwd 자체"를 이 라벨로 항상 보이게 해서, 상대경로(어떤
        # 파일)와 이 라벨(어느 폴더 기준)을 같이 보면 헷갈리지 않게 한다.
        # [수정 - 사용자 요청] "진한 보라색 등으로 눈에 띄게" -> "구분이 잘
        # 안됨 - 진한 바다색으로" -> "여전히 안 보임(내 눈이 이상한 건가?)" -
        # 색상 자체 문제가 아니라 ttk.Label이 원인이었음: Windows 기본
        # (vista) 테마가 ttk 위젯의 foreground 옵션을 실제 렌더링에서 조용히
        # 무시하는 경우가 있음(이 코드베이스의 tk.Entry/tk.Button/
        # tk.Checkbutton 전환 사례들과 동일한 문제 - cget()으로 읽으면 값은
        # 맞게 나오지만 화면에는 반영이 안 됨). 테마 영향을 안 받는
        # tk.Label로 바꿔 확실히 그 색으로 그려지게 한다.
        # [수정 - 버그] fill="x"로 라벨 위젯 자체가 전체 폭으로 늘어나면서,
        # pack()의 anchor="w"는 위젯의 "배치" 위치만 정할 뿐 그 늘어난
        # 위젯 안에서 글자 자체가 어디에 쓰이는지(위젯 자신의 anchor 옵션,
        # 기본값 center)는 별개라 텍스트가 가운데로 쏠려 보였음 - 위젯
        # 옵션에도 anchor="w"를 줘야 글자가 왼쪽에 붙는다.
        # [수정 - 사용자 요청] "진한 바다색으로도 구분 안되면 X버튼과 같은
        # 진한 붉은색으로" - tk.Label 전환 후에도 화면에서 계속 안 보인다는
        # 보고가 반복돼, 처음에 사용자가 미리 정해둔 대체 색(각 행 삭제
        # "X" 버튼과 동일한 PALETTE["danger"] 진한 붉은색)으로 바꾼다.
        tk.Label(
            self.file_frame, text=f"현재 작업 폴더(cwd): {self.cwd}",
            fg=self.PALETTE["danger"], bg=self.PALETTE["bg"], font=("Malgun Gothic", 9, "bold"),
            anchor="w"
        ).pack(fill="x", padx=5, pady=(2, 0), anchor="w")

        # [수정 - 요청] "모든 block에서 가로 스크롤 가능하게 - 일부 입력이
        # 잘림" - 세로 스크롤바만 있던 이 canvas를 자기 전용 sub-frame으로
        # 감싸서, 그 안에 가로 스크롤바도 같이 넣는다(오른쪽의 세로
        # 스크롤바/+ 버튼은 그대로 file_frame에 직접 배치 - 얘네까지 가로로
        # 같이 밀려나면 안 되므로).
        self.file_canvas_frame = ttk.Frame(self.file_frame)
        self.file_canvas = tk.Canvas(self.file_canvas_frame, height=85, width=120)
        self.file_scrollbar = ttk.Scrollbar(
            self.file_frame, orient="vertical", command=self.file_canvas.yview
        )
        self.file_hscrollbar = ttk.Scrollbar(
            self.file_canvas_frame, orient="horizontal", command=self.file_canvas.xview
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
        self.file_canvas.configure(yscrollcommand=self.file_scrollbar.set, xscrollcommand=self.file_hscrollbar.set)

        self.file_canvas_frame.pack(side="left", fill="both", expand=True, padx=5, pady=0)
        # [수정 - 사용자 재보고] "본래는 가로 scroll이 있었는데.... 아마도
        # PLOT 버튼 고정하면서부터인지?" - 세로 공간이 부족해질 때, pack은
        # "먼저 pack된 쪽이 자기 몫을 먼저 차지"하는 방식이라 - 여기서는
        # expand=True인 canvas가 먼저 pack돼 있어서 남는 공간을 전부 먼저
        # 가져가고, 그 뒤에 pack되는(=우선순위가 낮은) 가로 스크롤바가
        # 세로 공간이 부족해지면 화면 밖으로 밀려날 수 있었음(PLOT 버튼을
        # 고정한 방식과 같은 원인 - 이번엔 그 반대쪽, "가로 스크롤바"가
        # 희생되고 있었던 것으로 보임). PIP 팝업 닫기 버튼/메인 창 PLOT
        # 버튼과 같은 방식으로, 가로 스크롤바를 canvas보다 먼저 pack해서
        # 그 몫을 먼저 확보해둔다(canvas가 나머지를 그만큼 덜 차지하게 됨 -
        # 시각적으로는 스크롤바가 항상 보이는 대신 canvas 높이가 아주 약간
        # 줄어들 수 있음, 무시할 수준).
        self.file_hscrollbar.pack(side="bottom", fill="x")
        self.file_canvas.pack(side="top", fill="both", expand=True)
        self.file_scrollbar.pack(side="right", fill="y")
        self._bind_hscroll_wheel(self.file_canvas)

        # [수정 - 요청] "Dat file 추가 + 버튼에 배경색을" - ttk.Button은
        # Windows 기본 테마에서 배경색이 잘 안 먹는 문제가 이미 여러 번
        # 확인된 상태라(_mk_btn 주석 참고), Browse/X와 같은 tk.Button 기반
        # 헬퍼로 통일해 확실히 색이 반영되게 한다.
        # [수정 - 사용자 요청/시행착오] "+ 버튼이 너무 넓음" -> "박스는 그대로
        # 두고 안의 + 글자만 키워달라" -> "글자를 키웠더니 네모박스 안에서
        # + 위치가 아래로 치우침" -> "네모크기는 줄이고, 오메가 버튼을
        # 참조할 것" - 고정 크기 컨테이너에 억지로 채워 넣는 방식(작은
        # 박스에 큰 글자가 눌리며 중앙에서 벗어나 보임) 대신, 이미 잘
        # 보이는 우측 상단 "Ω" 버튼(var_symbol_btn)과 같은 방식(고정폭
        # tk.Button, width=3, Tk가 폰트+너비로 자연 계산한 박스 크기)으로
        # 단순화 - 폰트는 사용자가 테스트에서 지목한 Consolas(굵게)로,
        # 크기는 Ω(13pt)보다 조금 더 키워 "+"가 잘 보이게 한다.
        self.add_file_btn = self._mk_btn(
            self.file_frame, "+", self.add_file_row,
            color="secondary", btn_width=2, btn_pady=2, btn_padx=4, side="right", padx=1, pady=0,
        )
        self.add_file_btn.configure(font=("Consolas", 16, "bold"))

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
        # [수정 - 사용자 요청] "load 할 때 바로 그리는 방법 가능하나요?" -
        # Template을 저장해두고 나중에 불러와 "제대로 저장됐는지 확인"하는
        # 용도로 자주 쓰시는데, 그때마다 Load 따로 + Plot 버튼 따로 눌러야
        # 했음. 체크박스(기본 꺼짐 - 기존 동작 그대로 유지, Load만 하고
        # 바로 그리고 싶지 않은 경우도 있으므로)를 켜두면 Load 성공 직후
        # Interactive Plot까지 자동으로 이어서 실행한다. Batch Set 창 안의
        # "Template Load"(그 항목을 배치 목록에 채우기만 하는 용도, 5392행
        # 부근)는 이 체크박스와 무관하게 그대로 둔다(self.load_template을
        # 직접 호출 - 자동 실행 대상 아님).
        # [수정 - 사용자 요청] "Template Load시 바로 그리기를 기본으로" -
        # 기본값 꺼짐 -> 켜짐으로 변경.
        self.template_load_autoplot_var = tk.BooleanVar(value=True)
        def _load_template_then_maybe_plot():
            self.load_template()
            if self.template_load_autoplot_var.get():
                self.execute_plot_pipeline(mode="Interactive")
        self._mk_btn(btn_container, "Template Load", _load_template_then_maybe_plot,
                     color="grey", fg="white", side="left", padx=5)
        self._mk_check(btn_container, "Load 후 바로 그리기", self.template_load_autoplot_var,
                        size=15, anchor="w", side="left", padx=(2, 5))

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

        # [수정 - 요청] "모든 block에서 가로 스크롤 가능하게 - 일부 입력이
        # 잘림" - Var list는 No/Variable/X/Y1/Y2/Color/Style/Spl 칸이 옆으로
        # 길어서 창을 좁히면 오른쪽 칸(Style/Spl 등)이 잘리는데도 가로
        # 스크롤 수단이 없었음 - 세로 스크롤바와 같은 방식으로 가로도 추가.
        self.canvas_hframe = ttk.Frame(self.var_frame)
        self.canvas = tk.Canvas(self.canvas_hframe, height=290)
        self.scrollbar = ttk.Scrollbar(
            self.var_frame, orient="vertical", command=self.canvas.yview
        )
        self.hscrollbar = ttk.Scrollbar(
            self.canvas_hframe, orient="horizontal", command=self.canvas.xview
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
        self.canvas.configure(yscrollcommand=self.scrollbar.set, xscrollcommand=self.hscrollbar.set)
        self.canvas_hframe.pack(side="left", fill="both", expand=True)
        # [수정 - 사용자 재보고] 위 file_hscrollbar와 같은 이유 - 가로
        # 스크롤바를 canvas보다 먼저 pack해서 세로 공간이 부족해도 항상
        # 자기 몫을 먼저 확보하게 한다(자세한 설명은 file_hscrollbar 쪽
        # 주석 참고).
        self.hscrollbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="top", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self._bind_hscroll_wheel(self.canvas)

        self.plot_container = ttk.LabelFrame(self.root, text="Plot Setting", style=self.SECTION_STYLE["plot_setting"])
        self.plot_container.pack(fill="x", padx=10, pady=0)

        # [수정 - 요청] "모든 block에서 가로 스크롤 가능하게 - 일부 입력이
        # 잘림" - 이 canvas는 자기 폭을 항상 화면 폭에 맞추는 바인딩이 있어서
        # (아래 itemconfig(width=e.width)), 창을 좁히면 안의 내용(Title/
        # Legend/Frame/Axis 등 여러 입력줄)이 그만큼 그대로 잘려 보이고 가로
        # 스크롤로 나머지를 볼 방법이 없었음 - 내용 자체가 요구하는 최소
        # 폭(plot_frame.winfo_reqwidth()) 밑으로는 안 줄이게 바꾸고, 가로
        # 스크롤바를 추가해서 그 이하로 창이 좁아져도 스크롤로 나머지를 볼
        # 수 있게 한다.
        self.plot_canvas_hframe = ttk.Frame(self.plot_container)
        self.plot_canvas = tk.Canvas(self.plot_canvas_hframe, height=330, highlightthickness=0)

        self.plot_scrollbar = ttk.Scrollbar(self.plot_container, orient="vertical", command=self.plot_canvas.yview)
        self.plot_hscrollbar = ttk.Scrollbar(self.plot_canvas_hframe, orient="horizontal", command=self.plot_canvas.xview)
        self.plot_canvas.configure(yscrollcommand=self.plot_scrollbar.set, xscrollcommand=self.plot_hscrollbar.set)

        self.plot_canvas_hframe.pack(side="left", fill="both", expand=True)
        # [수정 - 사용자 재보고] "본래는 가로 scroll이 있었는데.... 아마도
        # PLOT 버튼 고정하면서부터인지?" - 위 file_hscrollbar와 같은 이유 -
        # 가로 스크롤바를 canvas보다 먼저 pack해서 세로 공간이 부족해도
        # 항상 자기 몫을 먼저 확보하게 한다(자세한 설명은 file_hscrollbar
        # 쪽 주석 참고 - "Plot Setting" 섹션 자체는 raw gnuplot/Comment/
        # Arrow/Circle 입력까지 전부 포함해 다른 두 목록보다 세로로 훨씬
        # 길어서, 창 높이가 부족해질 때 이 스크롤바가 가장 먼저 밀려날
        # 위험이 컸던 곳).
        self.plot_hscrollbar.pack(side="bottom", fill="x")
        self.plot_canvas.pack(side="top", fill="both", expand=True)
        self.plot_scrollbar.pack(side="right", fill="y")
        self._bind_hscroll_wheel(self.plot_canvas)

        self.plot_frame = ttk.Frame(self.plot_canvas)
        self.canvas_window = self.plot_canvas.create_window((0, 0), window=self.plot_frame, anchor="nw")

        self.plot_frame.bind(
            "<Configure>",
            lambda e: self.plot_canvas.configure(scrollregion=self.plot_canvas.bbox("all"))
        )
        self.plot_canvas.bind(
            "<Configure>",
            lambda e: self.plot_canvas.itemconfig(
                self.canvas_window, width=max(e.width, self.plot_frame.winfo_reqwidth())
            )
        )

        self.title_var = tk.StringVar(value="Plot Title")
        self.xlabel_var = tk.StringVar(value="")
        self.ylabel_var = tk.StringVar(value="")
        self.y2label_var = tk.StringVar(value="")

        self.xauto_var = tk.BooleanVar(value=True)
        self.yauto_var = tk.BooleanVar(value=True)
        self.y2auto_var = tk.BooleanVar(value=True)
        # [추가 - 사용자 요청] "y2 data 선택 있어도 tic 및 num을 안 그리게
        # 하는 방안은 없는지?" - Y2를 실제로 쓰더라도(legend로만 구분)
        # 오른쪽 축 tic 눈금/숫자를 완전히 끌 수 있는 옵션.
        self.y2tics_on_var = tk.BooleanVar(value=True)
        # [추가 - 사용자 요청] "Tic num 체크박스는 y1에도 있나요?" - Y2와
        # 같은 옵션을 Y1(왼쪽 축)에도 적용.
        self.ytics_on_var = tk.BooleanVar(value=True)

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

        # [추가 - 요청] PIP(부분 확대 inset) - 이 plot 안에 작은 확대 plot을
        # 하나 더 겹쳐 그리는 기능. 메인 창엔 버튼 하나만 두고(3D Plot과 같은
        # 방식) 나머지는 open_pip_dialog 팝업에서 설정한다. gnu_generator의
        # PlotDefinition.pip(dict)와 1:1로 대응 - _resolve_pip_config()가
        # 이 tk 변수들을 그 dict로 변환한다.
        self.pip_enabled_var = tk.BooleanVar(value=False)
        # [수정 - 요청] "위치입력이 좌상단인데 legend/annotation은 좌하단
        # 기준을 씀 - 통일" - 앵커를 좌측 하단으로 바꾸고, 기준도 캔버스
        # 전체가 아니라 큰 plot의 실제 축 프레임(axis frame)으로 통일
        # (gnu_generator._render_pip_inset 참고). 기본값 pos_y도 기존
        # 95(위 모서리 기준)와 시각적으로 같은 자리가 되도록 60(=95-기존
        # size_h 기본값 35)으로 같이 조정.
        self.pip_pos_x_var = tk.StringVar(value="10")     # 좌측 하단 모서리 X(%, 축 프레임 기준, 왼쪽=0)
        self.pip_pos_y_var = tk.StringVar(value="60")     # 좌측 하단 모서리 Y(%, 축 프레임 기준, 아래=0/위=100)
        self.pip_size_w_var = tk.StringVar(value="35")
        self.pip_size_h_var = tk.StringVar(value="35")
        # [추가 - 요청] 크기 단위: "%"(기본, 축 프레임 대비 비율) 또는
        # "in"/"cm"(실제 물리적 길이 - gnu_generator._render_pip_inset이
        # 터미널 명령의 실제 캔버스 크기로 환산함)
        self.pip_size_unit_var = tk.StringVar(value="%")
        # [추가 - 요청] "원/타원으로 클리핑" - "rect"(기본, 기존과 동일)면
        # 지금까지처럼 사각 박스, "circle"/"ellipse"면 create_script가 PDF를
        # 다 그린 뒤 실제로 그 모양대로 잘라낸다(gnu_generator._apply_pip_clip
        # 참고 - PDF/PNG/JPG/SVG는 자동 반영, EMF/Multi-Plot은 1차 구현
        # 범위 밖이라 항상 사각형). clip_rx/ry는 annotation의 Circle과 같은
        # 관례(%, 이 작은 plot 자신의 박스 기준 반지름, Ry 비우면 원).
        # [수정 - 사용자 지적] "반지름 50%가 최대(꽉참)라는 게 안 와닿는다 -
        # 반지름끼리 비교하면 100%가 꽉참이어야 하지 않나?" - 정확한 지적.
        # 내부 저장값(pip["clip_rx"], gnu_generator.py의 모든 타원 수식)은
        # "박스 전체 크기 대비 %"라는 기존 관례를 그대로 유지하되(기존
        # Template과의 하위호환 - 저장된 숫자의 의미가 안 바뀜), 화면에 보여
        # 주고 입력받는 이 tk 변수만 "박스 자신의 절반(반지름) 대비 %"(=100이
        # 꽉참) 기준으로 두 배 스케일을 쓴다 - 아래 저장/불러오기 지점에서
        # 서로 변환한다(÷2로 저장, ×2로 복원).
        self.pip_clip_shape_var = tk.StringVar(value="rect")
        self.pip_clip_rx_var = tk.StringVar(value="100")
        self.pip_clip_ry_var = tk.StringVar(value="")
        self.pip_xmin_var = tk.StringVar(value="")
        self.pip_xmax_var = tk.StringVar(value="")
        self.pip_ymin_var = tk.StringVar(value="")
        self.pip_ymax_var = tk.StringVar(value="")
        # [추가 - 요청] "Ymin/Ymax 입력이 Y1에만 적용되고 Y2는 그대로(plot 전체
        # 구간) 나타남 - Y1max/Y1min, Y2max/Y2min처럼 Y2도 따로 입력받게" -
        # 기본값은 빈 문자열(=지정 안 함 = plot 자체 구간을 그대로 따름).
        self.pip_y2min_var = tk.StringVar(value="")
        self.pip_y2max_var = tk.StringVar(value="")
        # [추가 - 요청] "돋보기(magnifier)" - 확대 구간(X/Y min/max)을 직접
        # 입력하는 대신, 중심(X,Y1)+반지름(X)+배율만 주면 gnu_generator.
        # compute_magnifier_pip가 자동으로 xmin/xmax/y1min/y1max/y2min/y2max
        # (실제 데이터에 맞게)와 size_w/size_h(배율로)를 계산한다. 여러 curve
        # 가 겹친 지점을 구별하는 용도 - main plot에는 점선 원으로 위치 표시.
        # 켜져 있으면 위 xmin/xmax/ymin/ymax는 무시되고 이 값들로 덮어씀.
        self.pip_mag_on_var = tk.BooleanVar(value=False)
        self.pip_mag_center_x_var = tk.StringVar(value="")
        self.pip_mag_center_x_mode_var = tk.StringVar(value="data")
        self.pip_mag_center_y1_var = tk.StringVar(value="")
        self.pip_mag_center_y1_mode_var = tk.StringVar(value="data")
        self.pip_mag_radius_x_var = tk.StringVar(value="")
        self.pip_mag_radius_x_mode_var = tk.StringVar(value="data")
        self.pip_mag_ratio_var = tk.StringVar(value="4")
        # [추가 - 요청] "PIP 위치 입력을 비활성화하고 돋보기 큰원 중심/
        # 반지름을 입력으로 - 중심(작은원과 큰원)은 서로 매칭되니까" - 둘 다
        # 비워두면 큰 원(인셋 박스)의 중심은 위 중심X/Y1(데이터 좌표를 축
        # 프레임 %로 환산)과 자동으로 일치하고, 크기는 배율로 자동 계산됨
        # (compute_magnifier_pip 참고) - 값을 넣으면 그 자리/크기를 직접
        # 지정할 수 있음(축 프레임 % 기준, 반지름은 "%").
        self.pip_mag_box_center_x_var = tk.StringVar(value="")
        self.pip_mag_box_center_x_mode_var = tk.StringVar(value="data")
        self.pip_mag_box_center_y_var = tk.StringVar(value="")
        self.pip_mag_box_center_y_mode_var = tk.StringVar(value="data")
        self.pip_mag_box_radius_var = tk.StringVar(value="")
        self.pip_title_on_var = tk.BooleanVar(value=False)
        # [추가 - 요청] "PIP PopUp에서 Plot Title과 Axis Title check box 분리"
        # - 기존엔 Plot Title(plotdef.title)만 껐다 켤 수 있었고, X/Y1/Y2축
        # 제목(axis label)은 항상 강제로 안 보이게 고정돼 있었음(_render_pip_
        # inset이 무조건 unset xlabel/ylabel/y2label). 별도 체크박스를 둬서
        # 원하면 축 제목도 켤 수 있게 함 - 기존 Template(이 키가 없는 json)은
        # get() 기본값으로 꺼짐(기존 동작과 동일)이라 안전함.
        self.pip_axis_title_on_var = tk.BooleanVar(value=False)
        self.pip_legend_on_var = tk.BooleanVar(value=False)
        # [추가 - 사용자 요청] "Plot Title/Axis Title/Legend 표시도 original
        # (메인)을 보고 기본 체크 여부를 정해야" - Plot Title/Axis Title은
        # PIP 전용 텍스트를 직접 입력해 쓸 수도 있어 비활성화(회색)는
        # 부적절하고, 메인에 그 내용이 있으면 기본으로 체크만 해준다(사용자가
        # 한 번이라도 직접 건드리면 그 뒤로 자동 동기화 중단 - grid_on과 같은
        # 패턴). Legend는 메인 자체 Legend On이 꺼져 있으면 보여줄 내용이
        # 없으므로 Marker처럼 아예 비활성화(회색)한다.
        self._pip_title_user_set = False
        self._pip_axis_title_user_set = False
        self._pip_legend_user_set = False
        # [추가 - 요청] "돋보기 형태로 위치/반지름만 주고, 그 안엔 curve만" -
        # 켜면 title/axis frame(테두리)/격자/tic 숫자를 전부 무시.
        self.pip_minimal_var = tk.BooleanVar(value=False)
        # [추가 - 사용자 요청] "PIP 인셋 grid도 on/off 옵션" - 지금까지는
        # 메인 화면의 Major/Minor Grid 설정을 인셋도 그대로 따라가기만
        # 했는데, 인셋만 독립적으로 켜고 끌 수 있게 별도 체크박스를 둔다
        # (기본값은 기존 동작과 같은 켜짐). 간단히 표시가 켜지면 이 값과
        # 무관하게 항상 꺼짐(gnu_generator._render_pip_inset 참고).
        # [수정 - 사용자 지적] "무조건 check 되어 있으면 곤란 - 메인의 grid
        # 설정을 보고 프로그램이 자동으로 on/off를 표기해야" - 고정값
        # True로 시작하는 대신, PIP 팝업을 열 때마다(사용자가 이 체크박스를
        # 아직 직접 건드리지 않았거나 Template이 명시적으로 값을 지정하지
        # 않은 한) 메인 화면의 Major Grid 설정을 그대로 반영해 보여준다
        # (open_pip_dialog의 checkbox 생성부/load_template 참고).
        self.pip_grid_on_var = tk.BooleanVar(value=True)
        self._pip_grid_user_set = False
        # [추가 - 요청] "Inset 크기에 따라 다르니까, PIP 입력에 마커 on/off
        # (원래 plot에 마커 있는 경우만) 넣어 두지" - 지금까지 inset 안
        # curve는 항상 선(line)만 그리고 마커는 생략했는데(좁은 인셋에서
        # 지저분해 보일 수 있어 1차 구현 때부터 의도적으로 제외), 사용자가
        # 필요할 때 켤 수 있게 체크박스를 추가한다. 실제 효과는 원본 curve에
        # marker_shape가 설정된 경우에만 나타난다(없는 curve는 켜도 선만
        # 그대로 - _build_pip_folded_overlay가 각 curve의 marker_shape
        # 유무로 자연스럽게 걸러줌).
        self.pip_marker_on_var = tk.BooleanVar(value=False)
        # [수정 - 사용자 보고 버그] "in-plot title/tic font가 너무 작아짐" -
        # 0.35로 낮췄던 기본값을 0.6으로 되돌림(gnu_generator.py의 동일
        # 기본값과 함께 - legend 전용 축소는 별도 메커니즘이 담당).
        self.pip_font_scale_var = tk.StringVar(value="0.6")
        # [수정 - 요청] "불투명 켬/끔" 체크박스 -> "배경 불투명도(%) 슬라이더"
        # (0~100, 기본 100=완전 불투명 - 기존 opaque=True 체크와 동일한 기본
        # 모습). Template Save/Load는 구 "opaque"(bool) 키도 그대로 읽어
        # opacity로 변환한다(_load_batch_item/Template Load 참고).
        self.pip_opacity_var = tk.IntVar(value=100)
        # 데이터 소스: "current"(기본, 이 plot 자신의 곡선) / "cached"(이미
        # 그려진 다른 plot) / "pltfile"(.plt 파일에서 곡선 추출)
        self.pip_source_var = tk.StringVar(value="current")
        self.pip_cached_name_var = tk.StringVar(value="")
        self.pip_pltfile_path_var = tk.StringVar(value="")
        # [추가 - 요청] "PIP 표시옵션에서 Plot Title/X/Y1/Y2 title을 default를
        # 제시하고 수정 가능하게" - 지금까지 in-plot의 Plot/axis title은
        # 항상 메인 plot 자신의 title_var/xlabel_var/ylabel_var/y2label_var를
        # 그대로 썼는데(gnu_generator._render_pip_inset), PIP의 데이터 소스가
        # "다른(이미 그려진) plot"이나 ".plt 파일"일 때는 그 원본이 title이
        # 없거나 다른 title을 쓸 수도 있어 항상 메인 것만 강제로 보여주는 게
        # 부적절할 수 있음 - 인셋 전용으로 독립적으로 지정 가능한 텍스트
        # 필드를 추가한다. 빈 문자열(기본)이면 기존과 동일하게 메인 plot의
        # 값을 그대로 물려받고(구버전 Template과도 호환), 팝업을 열 때
        # 비어있으면 편의상 메인의 현재 값을 기본으로 미리 채워 보여준다
        # (open_pip_dialog 참고) - 그대로 두면 메인과 동일하게 나오고, 필요시
        # 자유롭게 고쳐서 인셋만 다른(또는 빈) title을 쓸 수 있다.
        self.pip_title_text_var = tk.StringVar(value="")
        self.pip_xlabel_text_var = tk.StringVar(value="")
        self.pip_ylabel_text_var = tk.StringVar(value="")
        self.pip_y2label_text_var = tk.StringVar(value="")

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
        # [수정 - 사용자 요청] thick_list(Box Thick 콤보값)는 "상세 내용은
        # popup으로" 요청에 따라 _open_legend_detail_popup으로 옮겨져
        # 이제 이 메서드(create_widgets)에서는 안 쓰인다(팝업 쪽에 동일
        # 값으로 다시 정의돼 있음).
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
                    tw, text="프리셋 선택 또는 좌표 직접 입력 가능\n예: 70,90 (X,Y 0~100%, annotation과 동일)\n고급: graph 0.7,0.9 (axis frame 기준 0~1 비율)",
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
        # [수정 - 사용자 요청] "Curves가 다 보이도록 가로크기를 조금만 더
        # 키울까요? Curves/Function/Marker 버튼들을 좌측으로 이동해서
        # 정렬하면 조금만 키워도 될 듯" - 이 버튼들이 전부 줄 맨 끝(오른쪽
        # 맞춤)에 있어서, 창 폭이 조금만 좁아도(작은 화면 등) 아예 화면
        # 밖으로 밀려나 안 보이고 이 구역엔 가로 스크롤바도 없어 접근 자체가
        # 안 됐음(DAT Files/Available Variables 표와 달리) - Box 체크박스
        # 바로 뒤(줄 앞쪽)로 옮겨서, 창이 조금 좁아도 항상 보이게 한다.
        legend1_curves_btn = tk.Button(
            legend1_row, text="Curves", width=7, font=("Malgun Gothic", 9, "bold"),
            bg=self.PALETTE["secondary"], fg="white",
            activebackground=self.PALETTE["secondary_dark"], activeforeground="white",
            relief="raised", bd=1, pady=1,
        )
        legend1_curves_btn.pack(side="left", padx=(3, 8))
        ttk.Label(legend1_row, text="Pos1:").pack(side="left", padx=(21, 2))
        legend_pos_combo = ttk.Combobox(legend1_row, textvariable=self.legend_pos_var, values=pos_list, width=10)
        legend_pos_combo.pack(side="left", padx=2)
        _add_legend_pos_hint(legend_pos_combo)
        ttk.Label(legend1_row, text="Align:").pack(side="left", padx=(4, 1))
        ttk.Combobox(legend1_row, textvariable=self.legend_align_var, values=["Auto", "Left", "Right"],
                     width=5, state="readonly").pack(side="left", padx=1)
        # [수정 - 사용자 요청] "창 폭을 줄이려면 Legend1/2 줄이 먼저 줄어야
        # 하고, 상세 내용은 popup으로, 전체적으로 깔끔한 입력 모양이
        # 중요함" - Font/Size/Box Thick/Box W/H처럼 "자동 추정이 안 맞을
        # 때만 쓰는" 고급/저빈도 입력들을 이 줄과 아래 row2_f에서 전부
        # 빼서 별도 "Detail" 팝업(_open_legend_detail_popup, Legend1/2
        # 공용)으로 옮긴다 - 이 줄엔 자주 쓰는 On/Box/Curves/Pos/Align만
        # 남는다. 그 팝업을 여는 버튼 자체도 이 줄에 넣으면(84px) 다시
        # 이 줄이 병목이 되므로, row=2(옛 row2_f 자리, 이제 비어 있음)에
        # 따로 둔다 - 아래 참고.

        def _legend1_get(key):
            if key not in self.in_legend1_vars:
                self.in_legend1_vars[key] = tk.BooleanVar(value=True)
            return self.in_legend1_vars[key].get()

        def _legend1_set(key, val):
            if key not in self.in_legend1_vars:
                self.in_legend1_vars[key] = tk.BooleanVar(value=True)
            self.in_legend1_vars[key].set(val)

        # [수정 - 사용자 요청] "Curves를 좌측으로 이동" - 버튼 자체는 위(Box
        # 체크박스 바로 뒤)로 옮겼으니 여기서는 명령만 연결한다(_legend1_get/
        # _legend1_set이 여기서만 정의돼 있어 configure는 이 위치에서 함).
        legend1_curves_btn.configure(
            command=lambda: self._open_curve_select_popup(
                legend1_curves_btn, "Legend1 Curves", _legend1_get, _legend1_set, "1"
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
        # [수정 - 사용자 요청] "Curves를 좌측으로 이동" - legend1_row와 동일한
        # 이유로 Box 체크박스 바로 뒤로 옮김.
        legend2_curves_btn = tk.Button(
            legend2_row, text="Curves", width=7, font=("Malgun Gothic", 9, "bold"),
            bg=self.PALETTE["secondary"], fg="white",
            activebackground=self.PALETTE["secondary_dark"], activeforeground="white",
            relief="raised", bd=1, pady=1,
        )
        legend2_curves_btn.pack(side="left", padx=(3, 8))
        ttk.Label(legend2_row, text="Pos2:").pack(side="left", padx=(21, 2))
        legend2_pos_combo = ttk.Combobox(legend2_row, textvariable=self.legend2_pos_var, values=pos_list, width=10)
        legend2_pos_combo.pack(side="left", padx=2)
        _add_legend_pos_hint(legend2_pos_combo)
        ttk.Label(legend2_row, text="Align:").pack(side="left", padx=(4, 1))
        ttk.Combobox(legend2_row, textvariable=self.legend2_align_var, values=["Auto", "Left", "Right"],
                     width=5, state="readonly").pack(side="left", padx=1)
        # [수정 - 사용자 요청] Legend1과 동일하게 Box W/H는 Detail 팝업으로
        # 이동(이 줄 폭을 줄이기 위해).
        def _legend2_get(key):
            if key not in self.legend_group_vars:
                self.legend_group_vars[key] = tk.StringVar(value="2")
            return self.legend_group_vars[key].get() == "2"

        def _legend2_set(key, val):
            if key not in self.legend_group_vars:
                self.legend_group_vars[key] = tk.StringVar(value="2")
            self.legend_group_vars[key].set("2" if val else "1")

        legend2_curves_btn.configure(
            command=lambda: self._open_curve_select_popup(
                legend2_curves_btn, "Legend2 Curves", _legend2_get, _legend2_set, "2"
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

        # [수정 - 사용자 요청] "상세 내용은 popup으로" - 원래 이 자리(row=2,
        # col=3~5)에 있던 Legend Font/Size/Box Thick 줄(row2_f)을 완전히
        # 제거하고 _open_legend_detail_popup 팝업으로 옮겼다. 그 팝업을
        # 여는 버튼만 이 (이제 비어있던) 자리에 혼자 두면 legend1_row/
        # legend2_row 폭에 얹히지 않아 그 두 줄이 더 짧아진다.
        legend_detail_row = ttk.Frame(self.plot_frame)
        legend_detail_row.grid(row=2, column=3, columnspan=3, sticky="w", padx=3, pady=0)
        legend_detail_btn = tk.Button(
            legend_detail_row, text="Legend Detail", width=13, font=("Malgun Gothic", 9, "bold"),
            bg=self.PALETTE["secondary"], fg="white",
            activebackground=self.PALETTE["secondary_dark"], activeforeground="white",
            relief="raised", bd=1, pady=1,
            command=self._open_legend_detail_popup,
        )
        legend_detail_btn.pack(side="left", padx=(3, 3))
        # 버튼 라벨만으론 안에 뭐가 있는지 안 보이니 마우스오버 힌트로 보충.
        _add_hint(legend_detail_btn, "Legend Font/Size, Box Thick(공용), Legend1/2 Box W/H")

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

        # [수정 - 사용자 지적] "Function/Marker는 Legend box와 무관한데
        # legend 입력처럼 보임 - 한 줄 내려서 Axis Frame Auto 자리로" - 이
        # 줄(row=3 우측)을 Function/Marker 전용으로 쓰고, 원래 여기 있던
        # Axis Frame Auto 내용은 바로 아래(새 row=4)로 옮긴다(그 아래
        # 코드 참고 - Auto X Range 이하 행들도 전부 한 칸씩 밀림).
        func_marker_row = ttk.Frame(self.plot_frame)
        func_marker_row.grid(row=3, column=3, columnspan=3, sticky="we", padx=3, pady=0)
        function_curves_btn = tk.Button(
            func_marker_row, text="Function", width=8, font=("Malgun Gothic", 9, "bold"),
            bg=self.PALETTE["secondary"], fg="white",
            activebackground=self.PALETTE["secondary_dark"], activeforeground="white",
            relief="raised", bd=1, pady=1,
        )
        function_curves_btn.pack(side="left", padx=(3, 30))
        function_curves_btn.configure(command=self._open_function_curves_popup)

        # [수정 - 사용자 요청] "Function과 Marker 버튼은 더 띄워줘요, 충분히" -
        # 서로 딱 붙어 보이지 않도록 둘 사이 간격을 넉넉히 줌.
        # [수정 - 사용자 요청] "Marker 팝업에 Color/Style도 통합" - 버튼
        # 라벨도 넓어진 역할에 맞게 "Curve"로 변경.
        marker_settings_btn = tk.Button(
            func_marker_row, text="Curve", width=8, font=("Malgun Gothic", 9, "bold"),
            bg=self.PALETTE["secondary"], fg="white",
            activebackground=self.PALETTE["secondary_dark"], activeforeground="white",
            relief="raised", bd=1, pady=1,
        )
        marker_settings_btn.pack(side="left", padx=(44, 3))
        marker_settings_btn.configure(command=self._open_curve_settings_popup)

        # [수정] 기본값을 Auto로 변경 - 화면에서는 항상 검증된 scale=1.0 기준으로
        # 뜨게 하고, 인쇄/저장 시 특정 물리 크기가 필요할 때만 꺼서 W/H를 쓰도록 함
        self.frame_auto_var = tk.BooleanVar(value=True)
        self.frame_width_var = tk.StringVar(value="10")
        self.frame_height_var = tk.StringVar(value="8")
        self.frame_unit_var = tk.StringVar(value="cm")

        # [수정 - 사용자 요청] "Axis Frame Auto 줄의 이후 내용은 Auto X
        # Range 입력 줄 위에 추가" - row=3에 있던 이 내용을 row=4로 내려서
        # (Function/Marker가 비운 자리 대신) Auto X Range 행(원래 row=4,
        # 이제 row=5로 한 칸씩 밀림) 바로 위에 오게 한다.
        row3_f = ttk.Frame(self.plot_frame)
        row3_f.grid(row=4, column=0, columnspan=2, sticky="w", padx=0, pady=0)

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

        # [수정 - 사용자 요청] "Plot File Name도 충분히 앞쪽으로(Plot Title의
        # Font 칸 정도 위치로) 이동" - 우측 끝(right align) 대신, row3_f
        # 밖으로 빼서 Plot Title Font 콤보(t_font_frame)와 같은 grid
        # column=2에 직접 배치해 그 열과 자연스럽게 좌측 정렬되게 한다.
        filename_f = ttk.Frame(self.plot_frame)
        filename_f.grid(row=4, column=2, columnspan=4, sticky="w", padx=(5, 0), pady=0)
        self.filename_var = tk.StringVar(value="CathPlot")
        ttk.Label(filename_f, text="Plot File Name", font=("Malgun Gothic", 9, "bold")).pack(side="left", padx=(0, 3))
        self.filename_entry = self._mk_entry(filename_f, self.filename_var, width=20, color="accent3")
        self.filename_entry.pack(side="left")
        # [추가 - 사용자 요청] "같은 이름으로 계속 덮어쓰기 옵션" - PLOT을
        # 누를 때마다 title_counters가 증가해 "{이름}_1, _2, _3..."으로 새
        # .plt/이미지 파일이 계속 쌓이는데(여러 창을 나란히 비교하려는
        # 의도된 기능), Template을 불러와 "제대로 저장됐는지"만 확인하는
        # 반복 작업에서는 그 누적이 불필요하다는 지적 - 기본 꺼짐(기존 동작
        # 그대로)이고, 켜면 항상 "{이름}_1"로 고정해 매번 덮어쓴다(execute_
        # plot_pipeline 참고). [주의] 같은 제목의 이전 Interactive 창이 아직
        # 떠 있으면 그 창은 옛 내용 그대로 남고 새 창이 같은 제목으로 하나
        # 더 열림(창을 자동으로 닫지는 않음 - "여러 창 비교" 기존 동작과
        # 충돌하지 않도록 강제 종료는 하지 않기로 함) - 켜서 쓰실 땐 이전
        # 창을 직접 닫아가며 쓰시는 걸 권장.
        self.plot_overwrite_var = tk.BooleanVar(value=False)
        self._mk_check(filename_f, "덮어쓰기(번호 증가 안 함)", self.plot_overwrite_var,
                        size=15, anchor="w", side="left", padx=(6, 0))

        # Row 4
        self.xlog_var = tk.BooleanVar(value=False)
        self.y1log_var = tk.BooleanVar(value=False)
        self.y2log_var = tk.BooleanVar(value=False)
        self.xfmt_var = tk.StringVar(value="Normal")
        self.y1fmt_var = tk.StringVar(value="Normal")
        self.y2fmt_var = tk.StringVar(value="Normal")
        FMT_LIST = ["Normal", "Scientific", "Power10"]

        x_auto_f = ttk.Frame(self.plot_frame)
        x_auto_f.grid(row=5, column=0, sticky="w", padx=5, pady=2)
        self._mk_check(x_auto_f, "Auto X Range", self.xauto_var, color="accent", side="left")

        x_log_f = ttk.Frame(self.plot_frame)
        x_log_f.grid(row=5, column=1, sticky="w", padx=5, pady=2)
        self._mk_check(x_log_f, "Log", self.xlog_var, side="left")
        xfmt_combo = ttk.Combobox(x_log_f, textvariable=self.xfmt_var, values=FMT_LIST, width=7, state="readonly")
        xfmt_combo.pack(side="left", padx=(2, 0))
        self._disable_combobox_wheel(xfmt_combo)

        y1_auto_f = ttk.Frame(self.plot_frame)
        y1_auto_f.grid(row=5, column=2, sticky="w", padx=5, pady=2)
        self._mk_check(y1_auto_f, "Auto Y1 (Left) Range", self.yauto_var, color="accent", side="left")

        y1_log_f = ttk.Frame(self.plot_frame)
        y1_log_f.grid(row=5, column=3, sticky="w", padx=2, pady=2)
        self._mk_check(y1_log_f, "Log", self.y1log_var, side="left")
        y1fmt_combo = ttk.Combobox(y1_log_f, textvariable=self.y1fmt_var, values=FMT_LIST, width=7, state="readonly")
        y1fmt_combo.pack(side="left", padx=(2, 0))
        self._disable_combobox_wheel(y1fmt_combo)
        # [추가 - 사용자 요청] Y2와 동일한 "Tics" 표시/숨김 옵션을 Y1에도.
        self._mk_check(y1_log_f, "Tics", self.ytics_on_var, side="left")

        y2_auto_f = ttk.Frame(self.plot_frame)
        y2_auto_f.grid(row=5, column=4, sticky="w", padx=2, pady=2)
        self._mk_check(y2_auto_f, "Auto Y2 (Right) Range", self.y2auto_var, color="accent", side="left")

        y2_log_f = ttk.Frame(self.plot_frame)
        y2_log_f.grid(row=5, column=5, sticky="w", padx=2, pady=2)
        self._mk_check(y2_log_f, "Log", self.y2log_var, side="left")
        y2fmt_combo = ttk.Combobox(y2_log_f, textvariable=self.y2fmt_var, values=FMT_LIST, width=7, state="readonly")
        y2fmt_combo.pack(side="left", padx=(2, 0))
        self._disable_combobox_wheel(y2fmt_combo)
        # [추가 - 사용자 요청] "y2 tic/숫자를 아예 안 그리게" - Y2를 실제로
        # 쓰더라도 오른쪽 축 눈금 자체를 완전히 숨기는 옵션.
        self._mk_check(y2_log_f, "Tics", self.y2tics_on_var, side="left")

        # Row 5
        ttk.Label(self.plot_frame, text="X Min/Max", style="RowHead.TLabel").grid(row=6, column=0, sticky="w", padx=5, pady=2)
        self.xmin_var = tk.StringVar()
        self.xmax_var = tk.StringVar()
        x_limit_f = ttk.Frame(self.plot_frame)
        x_limit_f.grid(row=6, column=1, sticky="w", padx=5)
        self._mk_entry(x_limit_f, self.xmin_var, width=9, color="accent3").pack(side="left")
        ttk.Label(x_limit_f, text="~").pack(side="left", padx=2)
        self._mk_entry(x_limit_f, self.xmax_var, width=9, color="accent3").pack(side="left")

        ttk.Label(self.plot_frame, text="Y1 Min/Max", style="RowHead.TLabel").grid(row=6, column=2, sticky="w", padx=5, pady=2)
        self.ymin_var = tk.StringVar()
        self.ymax_var = tk.StringVar()
        y1_limit_f = ttk.Frame(self.plot_frame)
        y1_limit_f.grid(row=6, column=3, sticky="w", padx=5)
        self._mk_entry(y1_limit_f, self.ymin_var, width=9, color="accent3").pack(side="left")
        ttk.Label(y1_limit_f, text="~").pack(side="left", padx=2)
        self._mk_entry(y1_limit_f, self.ymax_var, width=9, color="accent3").pack(side="left")

        ttk.Label(self.plot_frame, text="Y2 Min/Max", style="RowHead.TLabel").grid(row=6, column=4, sticky="w", padx=5, pady=2)
        self.y2min_var = tk.StringVar()
        self.y2max_var = tk.StringVar()
        y2_limit_f = ttk.Frame(self.plot_frame)
        y2_limit_f.grid(row=6, column=5, sticky="w", padx=5)
        self._mk_entry(y2_limit_f, self.y2min_var, width=9, color="accent3").pack(side="left")
        ttk.Label(y2_limit_f, text="~").pack(side="left", padx=2)
        self._mk_entry(y2_limit_f, self.y2max_var, width=9, color="accent3").pack(side="left")

        # Row 6
        ttk.Label(self.plot_frame, text="X Tics/Minor", style="RowHead.TLabel").grid(row=7, column=0, sticky="w", padx=5, pady=2)
        self.xtics_var = tk.StringVar()
        self.mxtics_var = tk.StringVar()
        x_tick_f = ttk.Frame(self.plot_frame)
        x_tick_f.grid(row=7, column=1, sticky="w", padx=5)
        self._mk_entry(x_tick_f, self.xtics_var, width=9, color="accent3").pack(side="left")
        self._mk_entry(x_tick_f, self.mxtics_var, width=5, color="accent3").pack(side="left", padx=(5, 0))

        ttk.Label(self.plot_frame, text="Y Left (Y1) Tics", style="RowHead.TLabel").grid(row=7, column=2, sticky="w", padx=5, pady=2)
        self.ytics_var = tk.StringVar()
        self.mytics_var = tk.StringVar()
        y1_tick_f = ttk.Frame(self.plot_frame)
        y1_tick_f.grid(row=7, column=3, sticky="w", padx=5)
        self._mk_entry(y1_tick_f, self.ytics_var, width=9, color="accent3").pack(side="left")
        self._mk_entry(y1_tick_f, self.mytics_var, width=5, color="accent3").pack(side="left", padx=(5, 0))

        ttk.Label(self.plot_frame, text="Y Right (Y2) Tics", style="RowHead.TLabel").grid(row=7, column=4, sticky="w", padx=5, pady=2)
        self.y2tics_var = tk.StringVar()
        self.my2tics_var = tk.StringVar()
        y2_tick_f = ttk.Frame(self.plot_frame)
        y2_tick_f.grid(row=7, column=5, sticky="w", padx=5)
        self._mk_entry(y2_tick_f, self.y2tics_var, width=9, color="accent3").pack(side="left")
        self._mk_entry(y2_tick_f, self.my2tics_var, width=5, color="accent3").pack(side="left", padx=(5, 0))

        # Row 7
        self.major_grid_var = tk.BooleanVar(value=True)
        self.minor_grid_var = tk.BooleanVar(value=False)

        major_grid_f = ttk.Frame(self.plot_frame)
        major_grid_f.grid(row=8, column=0, sticky="w", padx=5, pady=2)
        self._mk_check(
            major_grid_f, "Major Grid", self.major_grid_var,
            command=self.on_major_grid_toggled, side="left"
        )

        minor_grid_f = ttk.Frame(self.plot_frame)
        minor_grid_f.grid(row=8, column=1, sticky="w", padx=5, pady=2)
        self.minor_grid_check = self._mk_check(
            minor_grid_f, "Minor Grid", self.minor_grid_var, side="left"
        )

        # Annotations Area
        self.anno_frame = ttk.LabelFrame(self.plot_frame, text="Multi Annotations", style=self.SECTION_STYLE["annotations"])
        self.anno_frame.grid(row=9, column=0, columnspan=6, sticky="ew", padx=5, pady=2)

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

        # [수정 - 요청] "Enable Comments/Arrows/Circles 체크박스가 꼭 필요한지 -
        # 3D처럼 입력 있으면 자동으로 켜지고 없으면 자동으로 꺼지는 게 낫지
        # 않은지" - _collect_annotations/_collect_arrows/_collect_circles가
        # 이미 빈 줄을 항상 걸러내고 있어서(내용을 채우면 자동으로 그려짐),
        # 이 체크박스들은 "채워놓고 체크를 깜빡하면 안 보이는" 혼란만 주는
        # 중복 게이트였음 - 제거(3D 주석 목록과 동일하게 통일).
        comment_btn_col = ttk.Frame(btn_f)
        comment_btn_col.pack(side="left", padx=5)
        ttk.Button(comment_btn_col, text="+ Add Comment", command=self.add_comment_row).pack(side="top", anchor="w")

        arrow_btn_col = ttk.Frame(btn_f)
        arrow_btn_col.pack(side="left", padx=15)
        ttk.Button(arrow_btn_col, text="+ Add Line/Arrow", command=self.add_arrow_row).pack(side="top", anchor="w")

        # [추가] "Arrow 옆에 Circle(중심축 2개 타원 - 반지름 1개만 입력하면 원)"
        circle_btn_col = ttk.Frame(btn_f)
        circle_btn_col.pack(side="left", padx=15)
        # [수정 - 사용자 요청] "+Add Circle 버튼 상하 위치를 옆 +Add Line/Arrow와
        # 맞추고 아래 comment를 우측에 정리" - 버튼 아래에 안내 Label을 별도
        # 줄로(side="top") 쌓으면 이 칸만 세로로 더 길어져 버튼이 다른 두
        # 칸(Comment/Arrow - 버튼 하나뿐)보다 위쪽으로 붕 떠 보였음. 버튼과
        # Label을 같은 행(side="left")에 나란히 두어 이 칸도 다른 칸과 같은
        # 높이(버튼 한 줄)가 되게 하고, 안내문은 버튼 우측에 붙인다.
        ttk.Button(circle_btn_col, text="+ Add Circle", command=self.add_circle_row).pack(side="left", anchor="w")
        # [추가 - 사용자 요청] "반지름 입력에 100%면 가득 찬다는 노트를" -
        # PIP Radius(Rx,Ry)%와 같은 기준(100=꽉참)으로 통일했으므로(gnu_
        # generator._build_plot_commands 참고), 그 사실을 여기서도 짧게
        # 안내한다.
        ttk.Label(circle_btn_col, text="%모드: 반지름 100=중심에서 축 가장자리까지",
                  foreground="#888888", font=("", 8)).pack(side="left", anchor="w", padx=(6, 0))

        # [수정] "Comment/Arrow 입력창이 안 보임 - 항상 빈 칸이 하나씩 나오게
        # 해야 함(어차피 안 지워지는 빈 칸이니 기본으로 둠)" - 시작할 때 매번
        # "+"를 눌러 추가하지 않아도 바로 입력할 수 있게, 빈 행을 하나씩
        # 미리 만들어둔다(모두 지웠을 때도 remove_row에서 다시 하나 채워줌).
        self.add_comment_row()
        self.add_arrow_row()
        self.add_circle_row()

        # 고급: raw gnuplot 명령어 직접 입력 (여기 적은 내용은 생성되는 .plt 파일에 그대로 삽입됨)
        self.raw_gnuplot_frame = ttk.LabelFrame(self.plot_frame, text="Advanced: Raw gnuplot commands", style=self.SECTION_STYLE["advanced"])
        self.raw_gnuplot_frame.grid(row=10, column=0, columnspan=6, sticky="ew", padx=5, pady=2)
        # [수정 - 요청] "Advanced block 입력에도 색 구분 테두리" - tk.Text는
        # 원래도 ttk가 아니라 highlightbackground/highlightcolor가 항상
        # 동작함(테마 영향 없음) - Advanced 섹션색(danger)으로 맞춤.
        self.raw_gnuplot_text = tk.Text(
            self.raw_gnuplot_frame, height=3, wrap="none",
            highlightthickness=1, highlightbackground=self.PALETTE["danger"], highlightcolor=self.PALETTE["danger"],
        )
        self.raw_gnuplot_text.pack(fill="x", padx=5, pady=3)

        # [이동됨] self.button_frame 생성+pack(side="bottom")은 이제 __init__
        # 맨 위로 옮겨서 다른 섹션보다 먼저 공간을 예약해둠(위 "PLOT 버튼 줄이
        # 노트북에서 잘림" 수정 참고) - 여기서는 이미 존재하는 그 Frame에
        # 버튼들만 채워 넣는다.

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

        # [수정 - 요청] "PIP 버튼은 PLOT 근방에 배치" - 기존엔 Batch Set/Queue/
        # Template Save-Load 줄(btn_container)에 있었는데, PIP는 PLOT/SAVE/
        # PRINT 실행 시 항상 같이 반영되는 설정이라 PLOT 바로 옆이 더 자연스러움.
        # [수정 - 요청] "PIP 버튼 앞에 체크박스(기본 꺼짐)를 두고, PIP 버튼을
        # 누르면 자동으로 체크되게, 팝업 안의 'PIP 사용' 체크박스는 없애고
        # (중복이라) 이 체크박스 하나로 통일 - 팝업을 닫아도 그대로 유지"
        # - self.pip_enabled_var를 여기서 직접 노출하고, 버튼은 그 값을
        # True로 만든 뒤 팝업을 연다(끄고 싶으면 이 체크박스만 그냥 끄면
        # 되고, 팝업을 다시 열 필요 없음).
        self._mk_check(self.button_frame, "", self.pip_enabled_var, side="left", padx=(5, 0), pady=2)

        def _open_pip_dialog_and_enable():
            self.pip_enabled_var.set(True)
            self.open_pip_dialog()

        self._mk_btn(self.button_frame, "PIP", _open_pip_dialog_and_enable,
                     color="grey", fg="white", side="left", padx=(2, 5), pady=2)

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
        # [수정 - 요청] "SAVE 버튼과 Animate Time box 간격을 좀 더 크게 -
        # SAVE/PRINT 그룹과 구별되게" - 오른쪽 여백을 0 -> 16px로.
        animate_f.pack(side="left", padx=(8, 16))
        self._mk_check(animate_f, "Animate", self.animate_var, color="accent", side="left")
        ttk.Label(animate_f, text="Time(s):").pack(side="left", padx=(4, 1))
        self._mk_entry(animate_f, self.animate_duration_var, width=4, color="accent").pack(side="left")

        _accent_btn(self.button_frame, "SAVE", pal["accent2"], pal["accent2_dark"],
                    self.execute_save_dialog, side="left", padx=5, pady=2)
        _accent_btn(self.button_frame, "PRINT", pal["accent3"], pal["accent3_dark"],
                    self.execute_print_dialog, side="left", padx=5, pady=2)
        _accent_btn(self.button_frame, "Close All Plots", pal["danger"], pal["danger_dark"],
                    self.close_all_plot_windows, side="right", padx=5, pady=2)
        # [수정 - 요청] "PLOT/SAVE/PRINT는 전부 대문자인데 Multi-Plot만 혼합
        # 표기라 어색하다" - 나머지와 통일해 전부 대문자로.
        _accent_btn(self.button_frame, "MULTI-PLOT", pal["amber"], pal["amber_dark"],
                    self.open_multi_plot_dialog, side="left", padx=15, pady=2)
        self._mk_btn(self.button_frame, "Clean Past Plots", self.open_delete_dialog,
                     color="secondary", side="right", padx=5, pady=2)
        # [추가 - 요청] "sorted dat 삭제 여부를 사용자가 고를 수 있게" -
        # 체크하면 CathPlot을 X 버튼으로 닫을 때 plot_dir/temp_sorted를
        # 지운다(기본은 안 지움 - .plt 재현성 우선). on_closing 참고.
        ttk.Checkbutton(
            self.button_frame, text="종료 시 sorted 캐시 삭제",
            variable=self.delete_temp_on_close_var
        ).pack(side="right", padx=(5, 10), pady=2)

        self.add_file_row()

        self.ylabel_var.trace_add("write", lambda *args: self.on_y1_title_changed(*args))
        self.y2label_var.trace_add("write", lambda *args: self.on_y2_title_changed(*args))
        self.xlabel_var.trace_add("write", lambda *args: self.on_x_title_changed(*args))
        self.title_var.trace_add("write", lambda *args: self.on_plot_title_changed(*args))

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
        # winfo_reqheight가 문제없이 동작했던 것과 대조적). 자동 계산(위젯
        # 기준) 대신 검증된 고정값을 쓰되, "노트북 화면에 맞게 넓혀달라"는
        # 요청으로 1150 -> 1200으로 조정.
        # [수정 - 사용자 보고 버그] "맨 마지막 PLOT 버튼 줄이 노트북에선
        # 잘려서 나옴(PC 큰 화면은 문제없음)" - required_height는 이 창의
        # "필요한" 높이일 뿐 화면에 실제로 들어가는지는 전혀 고려하지 않아서,
        # 노트북처럼 화면이 작으면 이 높이가 화면 세로 해상도보다 커져 창
        # 아래쪽(PLOT 버튼 줄)이 화면 밖으로 밀려났음(위 button_frame을
        # 다른 섹션보다 먼저 pack해 공간을 예약해둔 것과 별개로, "창 자체"가
        # 화면보다 크면 그 예약도 소용없음 - 창이 화면 밖으로 넘쳐버리므로).
        # PIP 팝업 높이를 화면 해상도에 비례하게 고친 것과 같은 방식으로,
        # 실제 화면 높이(winfo_screenheight, 작업표시줄/제목줄 여유로 100px
        # 뺌)를 넘지 않게 상한을 둔다 - 필요한 높이가 이미 화면보다 작으면
        # (PC의 큰 화면) 그대로 그 값을 쓰므로 기존 동작에 영향 없음.
        # [수정 - 사용자 요청] "가로 길이도 flexible하게, 상한선은 둬야죠"
        # - 가로는 위 winfo_reqwidth() 대신(그 방식이 실패했던 이유는 이미
        # 위에서 설명한 대로) __init__ 맨 위에서 실제 화면 가로 해상도 기준
        # 으로 미리 계산해 저장해 둔 self._win_w(900~1200 사이, PC 큰 화면은
        # 1200 상한 그대로)를 여기서도 그대로 재사용한다 - 위젯 reqwidth를
        # 다시 재는 게 아니므로 그 실패를 반복하지 않는다.
        _screen_h = self.root.winfo_screenheight()
        required_height = min(required_height, max(500, _screen_h - 100))
        self.root.geometry(f"{self._win_w}x{required_height}")

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

    def _unbind_mousewheel(self, region_widget):
        """[추가 - 코드 재검토로 발견된 버그] PIP 팝업처럼 열고 닫기를 반복하는
        창이 _bind_mousewheel로 등록만 하고 닫을 때 등록을 안 지워서,
        팝업을 열 때마다 이미 destroy된(죽은) 위젯 참조가 self._wheel_regions에
        계속 쌓이던 문제(메인 창처럼 앱 생애주기 동안 한 번만 만드는 위젯은
        문제없음 - 반복해서 열고 닫는 팝업만 해당). 팝업이 실제로 닫힐 때
        (dlg의 <Destroy> 이벤트) 그 팝업이 등록해둔 항목만 골라서 지운다."""
        if hasattr(self, "_wheel_regions"):
            self._wheel_regions = [
                (rw, tc) for rw, tc in self._wheel_regions if rw is not region_widget
            ]

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
        _plt_files = glob.glob(os.path.join(self.plot_dir, "*.plt"))
        # [수정 - 요청] "_ctrl_*.plt, _status_*.txt도 Animation용인데 일괄삭제에
        # 같이 섞여 나오고, .txt는 아예 검색이 안 됨(패턴이 *.plt뿐이었음)" -
        # status(.txt)도 같이 찾고, 파일명 패턴(_ctrl_/_status_)으로 Animation
        # 내부 파일을 일반 결과물과 분리해서 보여준다. 그리고 그중에서도 지금
        # 실행 중인 Animation이 쓰고 있는 파일(_active_anim_files, Animation
        # Control 패널이 열려있는 동안 등록됨)은 실수로 지워서 재생이 깨지는
        # 일이 없도록 아예 목록에서 뺀다(경고보다 안전한 방식).
        _active = getattr(self, "_active_anim_files", set())
        _regular_files, _anim_files, _excluded_active_count = [], [], 0
        for f in _plt_files:
            _base = os.path.basename(f)
            if "_ctrl_" in _base:
                if os.path.abspath(f) in _active:
                    _excluded_active_count += 1
                    continue
                _anim_files.append(f)
            else:
                _regular_files.append(f)
        for f in glob.glob(os.path.join(self.plot_dir, "*_status_*.txt")):
            if os.path.abspath(f) in _active:
                _excluded_active_count += 1
                continue
            _anim_files.append(f)

        # [수정 - 요청] "Clean Past Plots가 sorted 캐시도 지우는지?" - 확인해보니
        # 이 창(.plt 목록)과 temp_sorted 삭제(clean_past_plots 함수)가 서로
        # 완전히 분리돼 있었고, 심지어 clean_past_plots는 어느 버튼에도 연결
        # 안 된 죽은 코드였음. 여기 한 곳에서 같이 처리하도록 통합한다 -
        # .plt가 하나도 없어도 temp_sorted만 남아있을 수 있으니, 그 경우도
        # 창을 열어준다.
        _temp_dir = os.path.join(self.plot_dir, "temp_sorted")
        _temp_file_count = 0
        if os.path.isdir(_temp_dir):
            try:
                _temp_file_count = sum(len(fs) for _, _, fs in os.walk(_temp_dir))
            except Exception:
                _temp_file_count = 0
        if not _regular_files and not _anim_files and _temp_file_count == 0:
            messagebox.showinfo("정리 안내", "이전에 저장된 plot 파일이 없습니다.")
            return

        del_win = tk.Toplevel(self.root)
        del_win.title("Delete Plot Files")
        del_win.geometry("440x520")

        ttk.Label(del_win, text="결과 파일 (.plt)").pack(anchor="w", padx=10, pady=(10, 0))
        listbox = tk.Listbox(del_win, selectmode=tk.EXTENDED, height=8)
        listbox.pack(fill="both", expand=True, padx=10, pady=(2, 5))
        for f in _regular_files:
            listbox.insert(tk.END, os.path.basename(f))

        _anim_label = "Animation 내부 파일 (ctrl/status - 지워도 안전, 다음 Animation 실행 시 새로 만들어짐)"
        if _excluded_active_count:
            _anim_label += f"\n(지금 실행 중인 {_excluded_active_count}개는 목록에서 자동 제외됨)"
        ttk.Label(del_win, text=_anim_label, wraplength=420, justify="left").pack(anchor="w", padx=10, pady=(5, 0))
        anim_listbox = tk.Listbox(del_win, selectmode=tk.EXTENDED, height=5)
        anim_listbox.pack(fill="both", expand=True, padx=10, pady=(2, 5))
        for f in _anim_files:
            anim_listbox.insert(tk.END, os.path.basename(f))

        _clean_temp_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            del_win,
            text="temp_sorted 캐시도 함께 비우기",
            variable=_clean_temp_var,
        ).pack(anchor="w", padx=10, pady=(0, 0))
        ttk.Label(
            del_win,
            text=f"({_temp_file_count}개 파일 - 원본 dat 다시 불러오면 자동 재생성됨)",
            wraplength=400, justify="left", foreground="#666666",
        ).pack(anchor="w", padx=28, pady=(0, 5))

        def confirm_delete():
            selected_indices = listbox.curselection()
            anim_selected_indices = anim_listbox.curselection()
            _total_selected = len(selected_indices) + len(anim_selected_indices)
            _want_temp_clean = _clean_temp_var.get()
            if _total_selected == 0 and not _want_temp_clean:
                return
            if _total_selected:
                if not messagebox.askyesno("확인", f"선택한 {_total_selected}개 파일이 삭제됩니다. 계속할까요?"):
                    return
            if _want_temp_clean:
                # [수정 - 요청] "sorted 폴더를 지울 때 확인이 필요해서" - .plt
                # 파일 선택 삭제와는 별개로, temp_sorted는 영향 범위가 더 크고
                # (Batch 재사용성·재현성과 직결) 되돌릴 수 없으므로 독립된
                # 확인창을 하나 더 띄운다(파일 개수까지 알려줌).
                if not messagebox.askyesno(
                    "확인 - temp_sorted 삭제",
                    f"temp_sorted 폴더({_temp_file_count}개 파일)를 완전히 비웁니다.\n\n"
                    "이 폴더를 참조하는 저장된 .plt 파일은 이후 다시 열어도 "
                    "데이터를 찾지 못합니다(원본 dat를 다시 불러오면 자동 재생성은 됨).\n\n"
                    "계속할까요?"
                ):
                    _want_temp_clean = False
                    if not _total_selected:
                        return
            failed = []
            for i in selected_indices:
                filename = listbox.get(i)
                try:
                    os.remove(os.path.join(self.plot_dir, filename))
                except Exception as e:
                    failed.append(f"{filename}: {e}")
            for i in anim_selected_indices:
                filename = anim_listbox.get(i)
                try:
                    os.remove(os.path.join(self.plot_dir, filename))
                except Exception as e:
                    failed.append(f"{filename}: {e}")
            if _want_temp_clean:
                try:
                    import shutil
                    if os.path.isdir(_temp_dir):
                        shutil.rmtree(_temp_dir)
                except Exception as e:
                    failed.append(f"temp_sorted: {e}")
            del_win.destroy()
            self.update_plot_file_list()
            if failed:
                messagebox.showerror(
                    "삭제 오류",
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

        def _on_order_mode_toggled():
            # [수정 - 버그] "선택 순서대로 배치" 체크박스를 켜기 *전에* 이미
            # 마우스로 골라둔 항목이 있으면, 그 항목들은 _on_listbox_select가
            # 한 번도 안 불려서 _selection_order에 없음 - 그 상태로 켜면
            # 번호가 하나도 안 붙어 보이고(체크박스는 켜졌는데 순서 표시가
            # 없어 헷갈림), OK를 눌러도 _selection_order가 비어 있어 조용히
            # 알파벳순으로 폴백해버림. 켤 때 이미 선택된 항목을 인덱스
            # 순서로 시드(seed)해서 최소한 뭔가 반영되게 한다.
            if order_mode_var.get():
                for idx in sorted(plot_listbox.curselection()):
                    if idx not in _selection_order:
                        _selection_order.append(idx)
            _refresh_listbox_display()

        plot_listbox.bind("<<ListboxSelect>>", _on_listbox_select)
        # [수정 - 버그] side="left"로 dialog에 바로 넣었더니, 이 체크박스가
        # 왼쪽 세로 칸을 차지해버려서 그 뒤에 side="top"(기본값)으로 packing된
        # Layout/Orientation/Axis Frame/Cancel-Print-Save 버튼들이 전부 그
        # 나머지 좁은 오른쪽 칸에 눌려 들어가 글자가 잘려 보이던 버그였음
        # (Batch Queue와는 별개의, 이번에 새로 발견한 순수 레이아웃 버그 -
        # 위젯 geometry 직접 조회로 확인). 다른 위젯들과 같은 side="top" +
        # anchor="w"로 통일.
        self._mk_check(
            dialog, "선택 순서대로 배치 (Ctrl+클릭으로 하나씩 선택)", order_mode_var,
            command=_on_order_mode_toggled, anchor="w", padx=10, pady=(5, 0)
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
                messagebox.showwarning("경고", "목록에서 plot을 하나 이상 선택해주세요.", parent=dialog)
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
                    "경고",
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
                    messagebox.showinfo("완료", f"저장했습니다: {os.path.basename(filepath)}")

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
                    messagebox.showerror("인쇄 오류", str(e))

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", pady=15)
        # [수정 - 요청] "Batch Queue 선택창(이 Multi Save/Print 창)의 버튼 높이가
        # 너무 낮음 - Batch Set 버튼들과 비슷하게" - 기존 ttk.Button은 옆의
        # Batch Set/Batch Queue 대화상자 버튼(_mk_btn, btn_pady=10)보다 눈에
        # 띄게 낮아 보였음. 같은 헬퍼·같은 btn_pady로 통일하고, color는 이미
        # PALETTE에 정의된 용도별 강조색(accent2=SAVE, accent3=PRINT)을 그대로
        # 따른다.
        self._mk_btn(btn_frame, "Cancel", dialog.destroy, color="danger", btn_pady=0, side="right", padx=15)
        self._mk_btn(btn_frame, "Print", lambda: on_execute("Print"), color="accent3", btn_pady=0, side="right", padx=5)
        self._mk_btn(btn_frame, "Save", lambda: on_execute("Save"), color="accent2", btn_pady=0, side="right", padx=5)

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
            "y2tics_on": self.y2tics_on_var.get(),
            "ytics_on": self.ytics_on_var.get(),
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
            # [수정 - 사용자 보고 버그] "Batch Set 결과에 왜 화면 중심쯤에
            # 화살표/원이 나타나지?" - 화면엔 항상 빈 Comment/Arrow/Circle
            # 입력줄이 기본으로 하나씩 떠 있는데(add_comment_row 등을
            # create_widgets에서 초기 호출), 실제 plot(Interactive 등)에
            # 쓰는 _collect_annotations/_collect_arrows/_collect_circles는
            # 이 빈 줄을 걸러내지만 여기(Template Save가 쓰는 원본
            # 직렬화)는 그 필터 없이 self.comment_list/arrow_list/
            # circle_list를 통째로 그대로 저장했다 - 그래서 아무 내용도
            # 안 채운 빈 줄이 "좌표 빈 문자열"인 채로 Template에 실제
            # annotation처럼 저장되고, Batch Set이 이를 읽어 그리면서
            # 좌표가 빈 값이라 임의의(대략 화면 중앙) 위치에 화살표/원이
            # 그려졌다. 같은 기준(내용이 실제로 채워졌는지)으로 여기도
            # 걸러서 저장한다.
            "annotations": [
                {"txt": c['txt'].get(), "x": c['x'].get(), "y": c['y'].get(), "ang": c['ang'].get(),
                 "coord_mode": c['coord_mode'].get(), "color": c['color'].get()}
                for c in self.comment_list
                if c['txt'].get().strip() and c['x'].get().strip() and c['y'].get().strip()
            ],
            "arrows": [
                {"x1": a['x1'].get(), "y1": a['y1'].get(), "x2": a['x2'].get(), "y2": a['y2'].get(), "type": a['type'].get(),
                 "coord_mode": a['coord_mode'].get(), "color": a['color'].get(), "size": a['size'].get()}
                for a in self.arrow_list
                if a['x1'].get().strip() and a['y1'].get().strip() and a['x2'].get().strip() and a['y2'].get().strip()
            ],
            "circles": [
                {"x": e['x'].get(), "y": e['y'].get(), "rx": e['rx'].get(), "ry": e['ry'].get(),
                 "coord_mode": e['coord_mode'].get(), "color": e['color'].get()}
                for e in self.circle_list
                if e['x'].get().strip() and e['y'].get().strip() and e['rx'].get().strip()
            ],

            # --- var_no(output_no) 기준 curve 스타일: Color/Linestyle/Linewidth/Shift ---
            # (어떤 dat 파일인지와 무관하게, output_no 기준으로 저장 - Batch Queue의
            #  레시피 개념과 동일. 지금 화면에서 Y1/Y2로 선택된 변수들만 저장됨)
            "curve_styles": self._capture_curve_recipe()[0],

            # --- Function Curve(2D) - 데이터 파일 없이 수식만으로 그리는 curve들 ---
            "function_curves": self._function_curves_to_json(),

            # --- Plot File Name (Batch Set에서 출력 파일명 기본값으로 사용) ---
            "filename": self.filename_var.get(),

            # --- 실제 파일별 X/Y1/Y2 변수 지정 (Batch Set에서 이 Template 하나만으로
            #     완전히 같은 plot을 재현할 수 있도록, dat 파일명 자체도 포함) ---
            "file_assignments": self._capture_file_assignments(),

            # [추가] "3D도 Batch에 연동" - surface(splot) 파일은 Y1/Y2 선택이 없어
            # file_assignments에는 안 잡히므로(변수 선택 UI 자체가 없음), 3D Batch가
            # 이 Template만으로 surface도 재현할 수 있게 경로를 별도로 저장한다.
            "surface_files": self._capture_surface_files(),

            # [추가 - 요청] "선택한 순서대로 curve 그리기"가 Template Save/
            # Batch Set에도 반영되도록 - 클릭 순서를 "상대경로||output_no"
            # 리스트로 저장(_capture_curve_order 참고). Batch Set은 파일명까지
            # 그대로 매칭하고, Template Load는 output_no만 뽑아 recipe 방식으로
            # 재해석한다(둘 다 아래 소비하는 쪽 주석 참고).
            "curve_order": self._capture_curve_order(),
            # [추가 - 사용자 보고 버그] "Legend1/Legend2 순서 독립적으로" -
            # 위 curve_order(전체 그리기 순서)와는 별개로, 각 Legend 박스
            # "안"의 표시 순서를 따로 저장한다(_capture_legend_order 참고).
            "legend1_curve_order": self._capture_legend_order("1"),
            "legend2_curve_order": self._capture_legend_order("2"),

            # --- Advanced: Raw gnuplot 입력창 내용 ---
            "extra_gnuplot": self.raw_gnuplot_text.get("1.0", "end-1c"),

            # --- PIP(부분 확대 inset) ---
            # [주의] curves(실제 CurveDefinition 객체)는 JSON으로 저장하지
            # 않음 - source가 "cached"/"pltfile"이면 불러올 때(_resolve_pip_
            # dict_for_batch/_resolve_pip_config) cached_name/pltfile_path로
            # 다시 찾아서 채운다.
            "pip": {
                "enabled": self.pip_enabled_var.get(),
                "pos_x": self.pip_pos_x_var.get(), "pos_y": self.pip_pos_y_var.get(),
                "size_w": self.pip_size_w_var.get(), "size_h": self.pip_size_h_var.get(),
                "size_unit": self.pip_size_unit_var.get(),
                "clip_shape": self.pip_clip_shape_var.get(),
                "clip_rx": self._clip_pct_to_stored(self.pip_clip_rx_var.get()),
                "clip_ry": self._clip_pct_to_stored(self.pip_clip_ry_var.get()),
                "xmin": self.pip_xmin_var.get(), "xmax": self.pip_xmax_var.get(),
                "ymin": self.pip_ymin_var.get(), "ymax": self.pip_ymax_var.get(),
                "y2min": self.pip_y2min_var.get(), "y2max": self.pip_y2max_var.get(),
                "title_on": self.pip_title_on_var.get(), "axis_title_on": self.pip_axis_title_on_var.get(),
                "legend_on": self.pip_legend_on_var.get(), "minimal": self.pip_minimal_var.get(),
                "grid_on": self.pip_grid_on_var.get(),
                "marker_on": self.pip_marker_on_var.get(),
                "title_text": self.pip_title_text_var.get(), "xlabel_text": self.pip_xlabel_text_var.get(),
                "ylabel_text": self.pip_ylabel_text_var.get(), "y2label_text": self.pip_y2label_text_var.get(),
                "font_scale": self.pip_font_scale_var.get(), "opacity": self.pip_opacity_var.get(),
                "source": self.pip_source_var.get(),
                "cached_name": self.pip_cached_name_var.get(),
                "pltfile_path": self.pip_pltfile_path_var.get(),
                "magnifier": self._collect_magnifier_dict(),
            },
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

    def _build_3d_curves_from_template_data(self, data, td3_data=None):
        """[추가] "3D도 Batch에 연동" - 2D Template JSON의 file_assignments만으로
        (화면 상태를 전혀 안 건드리고) 3D curve 목록을 만든다.
        [수정 - 사용자 요청] "한 파일에서 y,z값을 따로 줄 수는 없나(여러 set)... "
        - 화면에서 쓰는 _collect_3d_curves와 마찬가지로, 파일당 Y1/Y2가 여러 개면
        (개수가 같으면) 그 개수만큼 여러 3D curve를 만든다.
        [수정 - 사용자 요청] "(3D template을 이미 쓰는데) 이미 잘 정리된 set
        아닌지" - 3D Template(td3_data)이 있고 그 안에 "curve_pairs"(화면에서
        _resolve_3d_pair_dialog로 확정했던 실제 (Y1,Y2) 짝, 파일의 cwd 기준
        상대경로가 키)가 있으면 그 짝을 그대로 쓴다(화면에서 기본 순서쌍이 아닌
        다른 짝을 골랐어도 Batch가 똑같이 재현). 다만 그 짝이 지금 이 2D
        Template의 y1_output_nos/y2_output_nos에 실제로 다 들어있는지 검증한
        뒤에만 신뢰하고(템플릿을 손으로 고쳤거나 선택이 그 사이 바뀌었으면
        안전하게 무시), 없거나 안 맞으면 예전처럼 output_no 오름차순 자동
        짝짓기로 대체한다(클릭 순서 정보가 없는 헤드리스 환경의 차선책 - 개수가
        다르면 그마저도 못 하므로 스킵)."""
        eligible = []
        skipped = []
        _saved_pairs_by_file = (td3_data or {}).get("curve_pairs", {}) or {}
        for fa in data.get("file_assignments", []):
            rel_path = fa["filename"]
            abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(self.cwd, rel_path)
            bn = os.path.basename(abs_path)

            def _nos(items):
                return sorted((v["output_no"] if isinstance(v, dict) else v) for v in (items or []))
            y1s = _nos(fa.get("y1_output_nos"))
            y2s = _nos(fa.get("y2_output_nos"))

            if not y1s and not y2s:
                continue  # 아예 선택 안 한 파일은 조용히 무시

            # [추가] 3D Template에 저장된 실제 짝을 먼저 시도(있고 유효할 때만).
            pairs_for_file = None
            _saved_pairs = _saved_pairs_by_file.get(rel_path)
            if _saved_pairs:
                _y1_set, _y2_set = set(y1s), set(y2s)
                try:
                    _candidate = [(int(p[0]), int(p[1])) for p in _saved_pairs]
                except (TypeError, ValueError, IndexError):
                    _candidate = []
                if _candidate and all(p[0] in _y1_set and p[1] in _y2_set for p in _candidate):
                    pairs_for_file = _candidate

            if pairs_for_file is None:
                if len(y1s) == 0 or len(y2s) == 0:
                    reason = []
                    if len(y1s) == 0: reason.append("Y1 없음")
                    if len(y2s) == 0: reason.append("Y2 없음")
                    skipped.append(f"{bn}: {', '.join(reason)}")
                    continue
                if len(y1s) != len(y2s):
                    skipped.append(
                        f"{bn}: Y1 {len(y1s)}개, Y2 {len(y2s)}개(개수가 달라 자동으로 못 정함 - "
                        "화면 3D Plot에서 짝을 맞춰 Template으로 저장해두면 Batch도 그 짝을 그대로 씀)"
                    )
                    continue
                pairs_for_file = list(zip(y1s, y2s))

            if not os.path.exists(abs_path):
                skipped.append(f"{bn}: 파일 없음")
                continue
            x_output_no = fa.get("x_output_no") or 0
            try:
                target_dat_file = self.resort_dat_file(abs_path, x_output_no)
            except Exception:
                target_dat_file = abs_path
            x_shift = float(fa.get("x_shift") or 0.0)

            # [추가 - 사용자 요청] 한 파일에서 여러 짝이 나오면 화면판과 동일하게
            # label에 번호를 붙여 구분(#1, #2, ...) - 1개뿐이면 기존처럼 번호 없음
            # (marker_shapes 등 label 기준 매칭 템플릿과의 호환 유지).
            multi = len(pairs_for_file) > 1
            for idx, (y1_no, y2_no) in enumerate(pairs_for_file):
                eligible.append({
                    "dat_file": target_dat_file,
                    "x_col": x_output_no + 1,
                    "y_col": y1_no + 1,
                    "z_col": y2_no + 1,
                    "x_shift": x_shift,
                    "label": f"{bn}#{idx + 1}" if multi else bn,
                })
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

            # [추가 - 요청] PIP(부분 확대 inset) - 구버전 템플릿(pip 키 없음)과도
            # 호환되도록 data.get("pip", {})가 비어있으면 전부 기존 값 유지.
            _pip_data = data.get("pip", {})
            self.pip_enabled_var.set(_pip_data.get("enabled", self.pip_enabled_var.get()))
            self.pip_pos_x_var.set(_pip_data.get("pos_x", self.pip_pos_x_var.get()))
            self.pip_pos_y_var.set(_pip_data.get("pos_y", self.pip_pos_y_var.get()))
            self.pip_size_w_var.set(_pip_data.get("size_w", self.pip_size_w_var.get()))
            self.pip_size_h_var.set(_pip_data.get("size_h", self.pip_size_h_var.get()))
            self.pip_size_unit_var.set(_pip_data.get("size_unit", self.pip_size_unit_var.get()))
            self.pip_clip_shape_var.set(_pip_data.get("clip_shape", self.pip_clip_shape_var.get()))
            # [수정 - 사용자 지적] 저장값은 여전히 "박스 전체 기준"(하위호환) -
            # 화면 표시용 "반지름(박스 절반) 기준"으로 되돌려서 채운다. 키
            # 자체가 없으면(구버전 Template 등) 변환하지 않고 현재 화면값
            # 그대로 유지(폴백을 잘못 다시 변환하는 것 방지).
            if "clip_rx" in _pip_data:
                self.pip_clip_rx_var.set(self._clip_pct_from_stored(_pip_data.get("clip_rx")))
            if "clip_ry" in _pip_data:
                self.pip_clip_ry_var.set(self._clip_pct_from_stored(_pip_data.get("clip_ry")))
            self.pip_xmin_var.set(_pip_data.get("xmin", self.pip_xmin_var.get()))
            self.pip_xmax_var.set(_pip_data.get("xmax", self.pip_xmax_var.get()))
            self.pip_ymin_var.set(_pip_data.get("ymin", self.pip_ymin_var.get()))
            self.pip_ymax_var.set(_pip_data.get("ymax", self.pip_ymax_var.get()))
            self.pip_y2min_var.set(_pip_data.get("y2min", self.pip_y2min_var.get()))
            self.pip_y2max_var.set(_pip_data.get("y2max", self.pip_y2max_var.get()))
            self.pip_title_on_var.set(_pip_data.get("title_on", self.pip_title_on_var.get()))
            self.pip_axis_title_on_var.set(_pip_data.get("axis_title_on", self.pip_axis_title_on_var.get()))
            self.pip_legend_on_var.set(_pip_data.get("legend_on", self.pip_legend_on_var.get()))
            # Template이 명시적으로 저장해둔 값이면 그 뒤로 팝업을 열어도
            # 메인 설정으로 자동 동기화하지 않고 이 값을 유지한다(위
            # open_pip_dialog 참고, grid_on과 같은 패턴).
            if "title_on" in _pip_data:
                self._pip_title_user_set = True
            if "axis_title_on" in _pip_data:
                self._pip_axis_title_user_set = True
            if "legend_on" in _pip_data:
                self._pip_legend_user_set = True
            self.pip_minimal_var.set(_pip_data.get("minimal", self.pip_minimal_var.get()))
            self.pip_grid_on_var.set(_pip_data.get("grid_on", self.pip_grid_on_var.get()))
            if "grid_on" in _pip_data:
                # Template이 이 값을 명시적으로 저장해뒀던 경우 - 그 뒤로는
                # 팝업을 열어도 메인 Grid 설정으로 자동 동기화하지 않고
                # 이 값을 그대로 유지한다(위 open_pip_dialog 참고).
                self._pip_grid_user_set = True
            self.pip_marker_on_var.set(_pip_data.get("marker_on", self.pip_marker_on_var.get()))
            self.pip_title_text_var.set(_pip_data.get("title_text", self.pip_title_text_var.get()))
            self.pip_xlabel_text_var.set(_pip_data.get("xlabel_text", self.pip_xlabel_text_var.get()))
            self.pip_ylabel_text_var.set(_pip_data.get("ylabel_text", self.pip_ylabel_text_var.get()))
            self.pip_y2label_text_var.set(_pip_data.get("y2label_text", self.pip_y2label_text_var.get()))
            self.pip_font_scale_var.set(_pip_data.get("font_scale", self.pip_font_scale_var.get()))
            # [수정 - 요청] "불투명 켬/끔" 체크박스 -> 0~100% 슬라이더로 교체 -
            # 예전 Template(구 "opaque" bool 키만 있음)도 그대로 불러와지도록
            # opacity가 없으면 opaque(True->100/False->0)로 변환해서 채운다.
            if "opacity" in _pip_data:
                try:
                    self.pip_opacity_var.set(int(round(float(_pip_data.get("opacity")))))
                except (TypeError, ValueError):
                    pass
            elif "opaque" in _pip_data:
                self.pip_opacity_var.set(100 if _pip_data.get("opaque") else 0)
            self.pip_source_var.set(_pip_data.get("source", self.pip_source_var.get()))
            self.pip_cached_name_var.set(_pip_data.get("cached_name", self.pip_cached_name_var.get()))
            self.pip_pltfile_path_var.set(_pip_data.get("pltfile_path", self.pip_pltfile_path_var.get()))
            # [추가 - 요청] "돋보기" 설정도 Template Load 때 같이 복원.
            _mag_data = _pip_data.get("magnifier") or {}
            self.pip_mag_on_var.set(bool(_mag_data.get("enabled", self.pip_mag_on_var.get())))
            self.pip_mag_center_x_var.set(_mag_data.get("center_x", self.pip_mag_center_x_var.get()))
            self.pip_mag_center_x_mode_var.set(_mag_data.get("center_x_mode", self.pip_mag_center_x_mode_var.get()))
            self.pip_mag_center_y1_var.set(_mag_data.get("center_y1", self.pip_mag_center_y1_var.get()))
            self.pip_mag_center_y1_mode_var.set(_mag_data.get("center_y1_mode", self.pip_mag_center_y1_mode_var.get()))
            self.pip_mag_radius_x_var.set(_mag_data.get("radius_x", self.pip_mag_radius_x_var.get()))
            self.pip_mag_radius_x_mode_var.set(_mag_data.get("radius_x_mode", self.pip_mag_radius_x_mode_var.get()))
            self.pip_mag_ratio_var.set(_mag_data.get("magnification", self.pip_mag_ratio_var.get()))
            self.pip_mag_box_center_x_var.set(_mag_data.get("box_center_x", self.pip_mag_box_center_x_var.get()))
            self.pip_mag_box_center_x_mode_var.set(_mag_data.get("box_center_x_mode", self.pip_mag_box_center_x_mode_var.get()))
            self.pip_mag_box_center_y_var.set(_mag_data.get("box_center_y", self.pip_mag_box_center_y_var.get()))
            self.pip_mag_box_center_y_mode_var.set(_mag_data.get("box_center_y_mode", self.pip_mag_box_center_y_mode_var.get()))
            self.pip_mag_box_radius_var.set(_mag_data.get("box_radius", self.pip_mag_box_radius_var.get()))

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
            # [추가 - 사용자 보고 버그 재검토로 발견] "Plot Title은 저장 안
            # 되나요?"를 고치면서 확인해보니, Plot File Name(filename_var -
            # Batch Set 출력 파일명 기본값)도 Save에는 포함되면서(_template_
            # dict) Load에서는 아예 복원한 적이 없었음(Batch Set 전용 함수인
            # _build_plotdef_from_template_data만 이 값을 읽음 - Template
            # Load 버튼과는 무관). title과 같은 이유로 여기서 같이 복원한다.
            if "filename" in data:
                self.filename_var.set(data["filename"])

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
            self.y2tics_on_var.set(data.get("y2tics_on", self.y2tics_on_var.get()))
            self.ytics_on_var.set(data.get("ytics_on", self.ytics_on_var.get()))
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

            # Function Curve(2D) - 구버전 템플릿(키가 아예 없음)에서는 기존 목록 유지
            if "function_curves" in data:
                for item in list(self.function_curves_list):
                    if item['frame'] is not None:
                        item['frame'].destroy()
                self.function_curves_list.clear()
                for fc in data.get("function_curves", []):
                    self.add_function_curve_row(initial=fc)

            # [추가 - 사용자 보고 크리티컬 버그] "template 저장 후 불러오면
            # 현재 창의 선택된 커브에 겹침 - 선택 안 한 파일의 변수도 선택되고
            # X(time) 변수에 check 없이 뜸" - load_template이 지금까지
            # file_assignments(파일별 X/Y1/Y2 지정)를 아예 안 읽고 있었음
            # (curve_styles는 "이미 선택된" 변수의 색상/굵기 등 스타일만
            # 바꿀 뿐, 무엇을 선택할지는 전혀 건드리지 않음 - _build_plotdef_
            # from_template_data가 이 파일을 읽긴 하지만 그건 Batch Set 전용
            # 무-화면 경로라 Template Load 버튼과는 무관) - 그 결과 템플릿을
            # 불러와도 "현재 화면에 이미 체크돼 있던 것"이 그대로 남아 템플릿의
            # 선택과 뒤섞여 겹쳐 보였음. 요청대로 "모든 선택을 먼저 초기화한
            # 뒤 저장된 내용대로만 다시 선택"하도록 고친다 - 파일은 이미
            # 열려있으면 그대로 재사용(색상 등 스타일 dict가 파일 경로 문자열로
            # 키가 잡혀 있어 재사용해야 기존 상태와 안 어긋남), 안 열려있으면
            # 빈 행을 찾아 쓰거나 새 행을 만들어 추가로 연다.
            _file_assignments = data.get("file_assignments", [])
            _fa_scope_keys = set()  # 아래 curve_styles 블록에서 "템플릿이 실제로 지정한 (파일,번호)"만 스타일을 적용하도록 범위를 좁히는 데 재사용
            if _file_assignments:
                for _v in self.selected_y1_vars.values():
                    _v.set(False)
                for _v in self.selected_y2_vars.values():
                    _v.set(False)
                for _info in self.file_rows:
                    _info["x_var"].set("")

                for _fa in _file_assignments:
                    _rel_path = _fa.get("filename", "")
                    if not _rel_path:
                        continue
                    # [수정 - 되돌림, 사용자 설명] "cwd 이후 구조는 같지만
                    # dat 파일은 물리적으로 다른 경우가 대부분" - 같은 상대
                    # 구조의 서로 다른 case 폴더에 CathPlot을 각각 실행해
                    # 같은 Template을 적용하는 게 주된 사용 방식이라, 경로
                    # 복원은 반드시 "지금(로드 시점)의" cwd 기준 상대경로여야
                    # 함(저장 시점의 절대경로를 우선하면, case를 바꿔 다시
                    # 열었을 때 새 case가 아니라 예전 case의 파일을 그대로
                    # 참조하는 더 심각한 오류가 됨) - 한때 저장 시점 절대경로를
                    # 우선하도록 바꿨던 시도를 원래의 cwd-상대경로 방식으로
                    # 되돌린다(해시 불안정 문제는 resort_dat_file 쪽에서
                    # 경로를 정규화하는 것으로 별도 해결 - 아래 참고).
                    _abs_path = _rel_path if os.path.isabs(_rel_path) else os.path.join(self.cwd, _rel_path)
                    if not os.path.exists(_abs_path):
                        continue  # 템플릿 저장 이후 파일이 옮겨지거나 지워졌으면 조용히 건너뜀

                    _target_info = next((i for i in self.file_rows if i.get("filename") == _abs_path), None)
                    if _target_info is None:
                        _target_info = next((i for i in self.file_rows if not i.get("filename")), None)
                        if _target_info is None:
                            self.add_file_row()
                            _target_info = self.file_rows[-1]
                        try:
                            _meta = self.parser.parse(_abs_path)
                        except Exception:
                            continue
                        _target_info["var"].set(self._display_relpath(_abs_path))
                        _target_info["filename"] = _abs_path
                        _target_info["meta"] = _meta
                        try:
                            save_json(_meta, Path(_abs_path).with_suffix(".json"))
                        except Exception:
                            pass

                    _datfile = _target_info["filename"]
                    _x_no = _fa.get("x_output_no")
                    if _x_no is not None:
                        _target_info["x_var"].set(f"{_datfile}||{_x_no}")
                    for _no in _fa.get("y1_output_nos") or []:
                        _key_str = f"{_datfile}||{_no}"
                        if _key_str not in self.selected_y1_vars:
                            self.selected_y1_vars[_key_str] = tk.BooleanVar(value=False)
                        self.selected_y1_vars[_key_str].set(True)
                        _fa_scope_keys.add(_key_str)
                    for _no in _fa.get("y2_output_nos") or []:
                        _key_str = f"{_datfile}||{_no}"
                        if _key_str not in self.selected_y2_vars:
                            self.selected_y2_vars[_key_str] = tk.BooleanVar(value=False)
                        self.selected_y2_vars[_key_str].set(True)
                        _fa_scope_keys.add(_key_str)
                    if "x_shift" in _fa:
                        if _datfile not in self.file_xshift_vars:
                            self.file_xshift_vars[_datfile] = tk.StringVar(value="0")
                        self.file_xshift_vars[_datfile].set(str(_fa.get("x_shift") or "0"))

                # [수정 - 사용자 보고 버그] "Plot Title은 Template 저장 시 기록
                # 안 되나요? 불러오니 file명으로 바뀜" - 여기서 update_title_
                # from_first_file()을 불렀던 것(load_dat_file이 새 파일 여는
                # 경우를 그대로 따라한 것)이 원인이었음: 이 함수 위쪽에서 이미
                # data["title"]/data["filename"]으로 Plot Title을 정확히
                # 복원해뒀는데, 그 뒤에 이 호출이 파일 이름 기준으로 다시
                # 덮어써버렸음(파일을 새로 열든 재사용하든 상관없이 무조건
                # 실행됐음). Template Load는 "파일을 새로 연 것"이 아니라
                # "저장된 파일/변수 지정을 반영한 것"이므로, 제목은 템플릿이
                # 저장해둔 값을 그대로 유지해야 함 - 이 호출을 제거한다.
                self.show_variables()
                self.sync_axis_labels()

            # var_no(output_no) 기준 curve 스타일(Color/Linestyle/Linewidth/Shift + 축)을
            # 현재 로드된 파일들 중 output_no가 일치하는 변수에 적용 (Batch Queue의
            # 레시피와 동일한 개념 - 어떤 dat 파일인지와 무관하게 output_no로 매칭)
            curve_styles = data.get("curve_styles", [])
            if curve_styles:
                # [수정 - 사용자 보고 크리티컬 버그] "Template load 해서 그리면
                # 모두 나중 curve 이름/marker 모양 등이 같은 이름으로 나타남" -
                # output_no만 키로 쓰면 서로 다른 파일이 같은 output_no를 쓸 때
                # (흔함) dict 생성 과정에서 먼저 것들이 전부 덮어써져 마지막
                # 항목 하나만 남았음(모든 curve가 그 하나의 스타일/이름을
                # 공유하게 됨). 이제 각 항목이 원본 파일(rel path, "file"
                # 필드 - 없으면 구버전 템플릿이므로 예전처럼 output_no만으로
                # 폴백)을 같이 들고 있으므로, (file, output_no) 조합으로 먼저
                # 정확히 매칭하고, 못 찾을 때만 output_no 전용 dict로 대체한다.
                style_by_file_no = {}
                style_by_no = {}
                for item in curve_styles:
                    style_by_no[item["output_no"]] = item  # 구버전 호환 폴백(마지막 항목 우선 - 기존 동작 유지)
                    _item_file = item.get("file")
                    if _item_file:
                        style_by_file_no[(_item_file, item["output_no"])] = item
                for info in self.file_rows:
                    if not info.get("filename") or info.get("meta") is None:
                        continue
                    datfile = info["filename"]
                    try:
                        _datfile_rel = os.path.relpath(datfile, self.cwd)
                    except ValueError:
                        _datfile_rel = datfile
                    for pv in info["meta"].variables:
                        style = style_by_file_no.get((_datfile_rel, pv.output_no)) or style_by_no.get(pv.output_no)
                        if not style:
                            continue
                        key_str = f"{datfile}||{pv.output_no}"
                        # [수정 - 사용자 재보고 크리티컬 버그] "같은 변수명(=보통
                        # 같은 output_no)의 다른 파일도 선택되는 문제가 있네요" -
                        # 위 axis 선택뿐 아니라 색상/스타일 자체도 output_no만
                        # 보고 "현재 열려있는 모든 파일"에 다 적용되고 있었음
                        # (이 파일이 템플릿에 없어도 마찬가지) - file_assignments가
                        # 있으면(=위에서 정확히 어떤 파일의 어떤 번호인지 이미
                        # 알고 있으면) 그 범위(_fa_scope_keys) 밖의 (파일,번호)는
                        # 스타일 적용도 건너뛴다(범위 밖 파일은 색상/마커 등도
                        # 템플릿과 무관하게 원래 값 그대로 유지돼야 함).
                        if _file_assignments and key_str not in _fa_scope_keys:
                            continue
                        # [수정 - 사용자 보고 버그] "변수명(legend)을 수정해서
                        # 저장했는데 load하니 원래 이름으로 되돌아감" - 위
                        # _capture_curve_recipe에 새로 추가한 "legend" 필드를
                        # 여기서 복원한다. 구버전 템플릿(이 필드 자체가 없음)은
                        # style.get("legend")가 빈 문자열이라 조건에서 걸러져
                        # 기존 값(파일 자체의 변수명)이 그대로 유지된다.
                        _saved_legend = style.get("legend")
                        if _saved_legend and key_str in self.legend_vars:
                            self.legend_vars[key_str].set(_saved_legend)
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
                        if key_str not in self.smooth_csplines_vars:
                            self.smooth_csplines_vars[key_str] = tk.BooleanVar(value=False)
                        self.smooth_csplines_vars[key_str].set(style.get("smooth_csplines", False))
                        # [수정 - 사용자 보고 크리티컬 버그] "선택 안 한 파일의
                        # 변수도 선택됨" - 이 axis 선택 코드는 output_no만
                        # 보고 "현재 열려있는 모든 파일" 중 일치하는 변수를
                        # 죄다 선택 처리해버림(Batch Set이 다른 dat 파일에
                        # 이 레시피를 재현할 때 필요해서 원래 이렇게 설계됨 -
                        # _capture_curve_recipe 참고, "특정 파일명과 무관").
                        # 그런데 Template Load는 위에서 이미 file_assignments
                        # (어떤 파일의 어떤 변수인지 정확히 지정)로 선택을
                        # 정확하게 복원해뒀으므로, 여기서 또 output_no만 보고
                        # 다른(템플릿에 없는) 파일까지 같이 선택해버리면 그
                        # 선택이 다시 겹쳐 버림 - file_assignments가 있으면(=
                        # 위에서 이미 정확히 복원했으면) 이 재선택은 생략하고
                        # 스타일만 적용한다(file_assignments가 없는 구버전
                        # 템플릿은 지금까지처럼 레시피 방식 그대로 유지).
                        if not _file_assignments:
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

            # [추가 - 요청] "선택한 순서대로 curve 그리기"를 Template Load에도
            # 반영. 위 curve_styles 복원은 output_no로만 매칭하는 "레시피"
            # 방식(어떤 dat 파일인지 무관 - 위 주석 참고)이라, 저장된
            # curve_order("상대경로||output_no")에서도 output_no만 뽑아 같은
            # 방식으로 재해석한다(파일명은 무시 - curve_styles와 매칭 방식을
            # 맞춤). "curve_order" 키가 아예 없는 구버전 템플릿은 지금 순서
            # 트래킹을 그대로 둔다(건드리지 않음).
            if "curve_order" in data:
                _output_no_order = []
                _seen_no = set()
                for _entry in data.get("curve_order") or []:
                    try:
                        _no = int(str(_entry).rsplit("||", 1)[1])
                    except (ValueError, IndexError):
                        continue
                    if _no not in _seen_no:
                        _seen_no.add(_no)
                        _output_no_order.append(_no)
                _no_priority = {no: i for i, no in enumerate(_output_no_order)}
                _selected_keys = [k for k, v in self.selected_y1_vars.items() if v.get()]
                _selected_keys += [k for k, v in self.selected_y2_vars.items() if v.get()]
                _selected_keys = list(dict.fromkeys(_selected_keys))  # 중복 제거(순서 유지)

                def _key_priority(k):
                    try:
                        no = int(k.split("||")[1])
                    except (ValueError, IndexError):
                        return len(_output_no_order)
                    return _no_priority.get(no, len(_output_no_order))

                self._curve_order = sorted(_selected_keys, key=_key_priority)

            # [추가 - 사용자 보고 버그] "Legend1/Legend2 순서 독립적으로" -
            # 위 curve_order와 별개로, 각 Legend 박스 안의 표시 순서도 저장돼
            # 있으면 복원한다("legend1_curve_order" 키가 없는 구버전
            # Template은 지금 상태(보통 curve_order 기본값)를 그대로 둠).
            if "legend1_curve_order" in data:
                self._restore_legend_order_from_data("1", data.get("legend1_curve_order"))
            if "legend2_curve_order" in data:
                self._restore_legend_order_from_data("2", data.get("legend2_curve_order"))

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

        # [수정 - 사용자 보고 버그] "Batch Set 결과 Legend Title이 원본
        # 변수명으로 나타남(개별 화면에서는 사용자가 고친 이름이 제대로
        # 나옴)" - curve_styles 각 항목엔 사용자가 고친 legend 텍스트가
        # "legend" 필드로, 그리고 어느 파일의 것인지 구분하는 "file"
        # 필드도 같이 저장돼 있는데(레시피 필드의 file은 "여러 파일에
        # 재사용" 용도인 Batch Queue에서는 의도적으로 무시하지만, Batch
        # Set은 template 하나하나가 이미 특정 파일 조합 전용이라 이 값을
        # 그대로 써야 함), 여기서는 output_no만으로 매칭해서 그 두 필드를
        # 전혀 안 썼다 - 같은 output_no를 쓰는 파일이 이 template 안에
        # 여러 개면(흔함) 스타일이 서로 뒤섞이는 문제도 같이 있었음.
        # "파일||output_no"로 먼저 찾고(정확한 매칭), 없으면(file 필드가
        # 없는 예전 template 호환용) output_no만으로 한 번 더 시도한다.
        style_by_file_no = {}
        style_by_no = {}
        for item in data.get("curve_styles", []):
            style_by_no[item["output_no"]] = item
            if item.get("file"):
                style_by_file_no[f'{item["file"]}||{item["output_no"]}'] = item

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
                    style = style_by_file_no.get(f"{rel_path}||{output_no}") or style_by_no.get(output_no, {})
                    var_obj = var_by_no.get(output_no)
                    _saved_legend = str(style.get("legend", "")).strip()
                    legend_text = _saved_legend or (var_obj.display_name if var_obj else f"var_{output_no}")
                    try:
                        # [수정 - 요청] "선택한 순서대로 curve 그리기"가 Batch
                        # Set에도 반영되도록, 여기서는 (order_key, curve)
                        # 튜플로 잠시 담아둔다 - order_key는 Template Save가
                        # 쓰는 것과 동일한 "상대경로||output_no" 표현이라
                        # curve_order와 정확히(파일명까지) 매칭된다.
                        curves.append((f"{rel_path}||{output_no}", CurveDefinition(
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
                            smooth_csplines=style.get("smooth_csplines", False),
                            orig_dat_file=rel_path,
                        )))
                    except ValueError:
                        continue  # X/Y 번호가 같은 경우 등은 건너뜀

        if not curves:
            raise ValueError("이 템플릿에는 그릴 변수(Y1/Y2)가 없습니다.")

        # [추가 - 요청] curve_order(저장된 클릭 순서)가 있으면 그 순서대로
        # 재배열 - 없는(구버전 템플릿) curve는 원래 순서 그대로 뒤에 남음
        # (안정 정렬 - Python sorted()는 stable이라 동일 우선순위끼리는
        # 원래 상대 순서를 유지함).
        _order = data.get("curve_order") or []
        _order_index = {k: i for i, k in enumerate(_order)}
        curves.sort(key=lambda item: _order_index.get(item[0], len(_order)))
        curves = [c for _key, c in curves]

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
            y2tics_on=data.get("y2tics_on", True), ytics_on=data.get("ytics_on", True),
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
            # [수정 - 사용자 보고 버그] 아래 세 목록 모두 "내용이 실제로
            # 채워진 항목만" 남기도록 방어적으로 다시 거른다 - 이전에는
            # Template Save(_template_dict)가 화면에 항상 떠 있는 빈
            # 기본 입력줄까지 좌표 빈 문자열인 채로 그대로 저장해서, 이미
            # 저장된 예전 Template들에 이런 "내용 없는" annotation이
            # 섞여 있을 수 있다(원인은 저장 쪽에서 고쳤지만, 이미 저장된
            # 파일들은 그대로 남아있으므로 읽는 쪽에서도 한 번 더 막아야
            # 안전함).
            annotations=(
                [{"text": c["txt"], "x": c["x"], "y": c["y"], "angle": c["ang"],
                  "coord_mode": c.get("coord_mode", "pct"), "color": COLOR_MAP.get(c.get("color", "Auto"), "")}
                 for c in data.get("annotations", [])
                 if str(c.get("txt", "")).strip() and str(c.get("x", "")).strip() and str(c.get("y", "")).strip()]
                if data.get("comment_on", True) else []
            ),
            arrows=(
                [{"x1": a["x1"], "y1": a["y1"], "x2": a["x2"], "y2": a["y2"],
                  "head": head_label_map.get(a["type"], "Forward"),
                  "coord_mode": a.get("coord_mode", "pct"), "color": COLOR_MAP.get(a.get("color", "Auto"), ""),
                  "head_size": self.ARROW_SIZE_MAP.get(a.get("size", "M"), self.ARROW_SIZE_MAP["M"])}
                 for a in data.get("arrows", [])
                 if str(a.get("x1", "")).strip() and str(a.get("y1", "")).strip()
                 and str(a.get("x2", "")).strip() and str(a.get("y2", "")).strip()]
                if data.get("arrow_on", True) else []
            ),
            circles=(
                [{"x": e["x"], "y": e["y"], "rx": e["rx"], "ry": e.get("ry", ""),
                  "coord_mode": e.get("coord_mode", "pct"), "color": COLOR_MAP.get(e.get("color", "Auto"), "")}
                 for e in data.get("circles", [])
                 if str(e.get("x", "")).strip() and str(e.get("y", "")).strip() and str(e.get("rx", "")).strip()]
                if data.get("circle_on", True) else []
            ),
            is_print_mode=True,
            x_output_no=default_x_output_no,
            extra_gnuplot=data.get("extra_gnuplot", ""),
            # [추가 - 요청] PIP(부분 확대 inset) - Template에 저장된 pip 설정을
            # 그대로 복원. source가 "cached"/"pltfile"였던 템플릿은 이 시점에
            # curves를 다시 채워 넣어야 하므로 _resolve_pip_curves_for_data로
            # 한 번 더 해석한다(캐시에 없는 이름이면 조용히 "현재 plot 없음"
            # 취급 - 아래 참고).
            pip=self._resolve_pip_dict_for_batch(data.get("pip", {})),
            function_curves=self._function_curves_from_json(data.get("function_curves", [])),
        )

    def _resolve_pip_dict_for_batch(self, pip_data):
        """[추가 - 요청] Batch Set처럼 화면(screen) tk 변수를 건드리지 않고
        Template 데이터만으로 PlotDefinition을 만드는 경로에서, pip.source가
        "cached"(이미 그려진 plot)나 "pltfile"(.plt 파일)이면 저장된 이름/경로로
        curves를 다시 채워 넣는다. "current"(기본, 이 Template 자신의 곡선을
        그대로 축소해서 보여줌)는 curves를 안 채워도 _render_pip_inset이
        main_cmd_list를 그대로 쓰므로 손댈 게 없음."""
        if not pip_data or not pip_data.get("enabled"):
            return pip_data or {}
        pip_data = dict(pip_data)  # 원본(Template dict) 변형 방지
        source = pip_data.get("source", "current")
        if source == "cached":
            name = pip_data.get("cached_name", "")
            cached_plotdef = self.active_plots_cache.get(name)
            if cached_plotdef is not None:
                pip_data["curves"] = cached_plotdef.curves
            # 캐시에 없으면(다른 세션에서 저장된 Template 등) 조용히
            # "현재 plot"으로 폴백 - curves를 안 채우면 _render_pip_inset이
            # main_cmd_list(이 Template 자신의 곡선)를 그대로 씀.
        elif source == "pltfile":
            path = pip_data.get("pltfile_path", "")
            # [수정 - 사용자 질문/요청] "template를 다른 폴더에서 가져오면
            # PIP그림은 없으니까 오류내지 경고를 줘야" - 예전엔 여기서 미리
            # os.path.exists(path)로 걸러서, .plt 파일 자체가 없으면(템플릿을
            # 통째로 다른 폴더에서 불러온 경우 등) _parse_plt_curves를 아예
            # 안 부르고 조용히 "현재 plot"으로 폴백했음. 이제 그 사전 검사를
            # 없애 _parse_plt_curves가 직접 열어보게 하고(OSError면 그 자체를
            # 이유로 담은 warnings를 돌려줌 - 위 docstring/OSError 분기 참고),
            # 아래에서 _resolve_pip_config(대화형)과 동일하게 warnings를
            # 항상 남긴다.
            if path:
                curves, warnings = self._parse_plt_curves(path)
                if curves:
                    pip_data["curves"] = curves
                if warnings:
                    # [추가 - 사용자 질문/요청] 여기는 백그라운드 스레드에서도
                    # 호출될 수 있어(Batch Set) messagebox를 바로 띄울 수 없음.
                    # _process_one_batch_set_item이 res["warnings"]로 모아
                    # 사용자에게 보여주는 기존 관례를 따라, pip_data 자체에
                    # 담아 호출부가 꺼내 쓰게 한다(조용히 사라지지 않게).
                    pip_data["_source_warnings"] = warnings
        self._pip_autofill_range(pip_data)
        return pip_data

    def _parse_plt_curves(self, plt_path):
        """[추가 - 요청] PIP inset의 데이터 소스로 ".plt 파일 불러오기"를 지원
        하기 위해, CathPlot 자신이 생성한 .plt 스크립트에서 curve의 plot 표현식
        ("파일" using (...):col notitle axes x1y1 with lines lw N [lc rgb "..."]
        [dashtype (...)])을 정규식으로 되짚어 대략적인 CurveDefinition 목록을
        복원한다. 어디까지나 "이미 그려진 plot을 그대로 다시 쓰는" 캐시 방식의
        보조 수단이라, 이 함수는 우리 자신의 생성 포맷에만 맞춰져 있고(범용
        gnuplot 스크립트 파서가 아님) marker/legend_group 등 부가 정보는
        복원하지 않는다(inset은 어차피 선(line)만 그리므로 문제 없음).
        [수정 - 사용자 질문/요청] "다른 기기/세션에서 이 .plt를 불러오면, plot
        절에 박힌 경로(대부분 resort_dat_file의 임시 정렬 캐시 - .gitignore
        대상이라 사라질 수 있음)가 없을 텐데?" - (curves, warnings) 튜플을
        돌려주도록 바꾼다. 캐시 경로가 없으면 _build_plot_commands가 같이
        남겨둔 "# CathPlot-src N orig="..." xout=N" 복구용 주석(원본 dat 파일의
        cwd 기준 상대경로)을 보고 그 자리에서 resort_dat_file을 다시 실행해
        이 기기에 캐시를 새로 만든다 - 원본조차 없으면(또는 이 주석 자체가
        없는 예전 .plt면) 그 curve만 건너뛰고 이유를 warnings에 담아 호출부가
        사용자에게 알릴 수 있게 한다(예전처럼 조용히 사라지지 않음)."""
        try:
            with open(plt_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            return [], [f".plt 파일을 열 수 없습니다: {plt_path} ({e})"]

        # [수정 - 사용자 보고 버그] "PIP 인셋 안에 두 가지 그림이 겹쳐 보임" -
        # 소스로 지정한 .plt 파일 자신이 (CathPlot이 만든 파일이니 흔히 그럴
        # 수 있듯) 자기 자신의 PIP 인셋 구간을 포함하고 있으면, 그 인셋 자신의
        # curve plot 명령도(Rect 클리핑이면 NaN 감싸기 없이 메인과 똑같은
        # "using (...):N notitle axes ... with lines" 형식이라) 이 정규식에
        # 그대로 다시 매치돼, 메인 curve + 인셋 curve가 중복으로 섞여
        # 들어갔음(실제로 서로 다른 확대/축소 구간의 같은 데이터라 "두 그림이
        # 겹쳐" 보이는 원인). _parse_plt_titles가 이미 같은 이유로 하던 것과
        # 동일하게, "# --- PIP (부분 확대) inset ---" 주석 이후는 아예
        # 보지 않는다(있으면 그 앞부분만, 없으면 전체를 그대로 검색).
        marker_pip = "# --- PIP (부분 확대) inset ---"
        idx = text.find(marker_pip)
        if idx >= 0:
            text = text[:idx]

        # [수정 - 사용자 보고 버그] "in-plot으로 .plt를 지정하면 그 파일이 아니라
        # 현재 main-plot을 불러옴" - 실제 렌더링으로 재현·확인한 근본 원인:
        # Cubic Spline이 켜진 curve는 _build_plot_commands가 y 컬럼 번호와
        # "notitle" 사이에 " smooth csplines"를 끼워 넣는데(gnuplot 문법상
        # smooth 절은 using 바로 뒤에 와야 함), 이 정규식은 y 컬럼 번호
        # 바로 뒤에 공백만 있고 곧장 "notitle"이 온다고 가정해서 그 사이에
        # 낀 "smooth csplines" 때문에 매치가 통째로 실패했음(실측: 두 curve
        # 모두 Spline이 켜진 .plt로 직접 검증 - 매치 0건). 곡선을 하나도
        # 못 찾으면(curves=[]) 조용히 "현재 화면"으로 대체돼(_resolve_pip_
        # config), 사용자에게는 원인도 알려주지 않고 완전히 다른 plot의
        # 곡선이 나오는 것처럼 보였음 - smooth 절을 선택적으로 허용한다.
        pattern = re.compile(
            r'"([^"]+)"\s+using\s+\(\$(\d+)\+([^)]*)\):(\d+)(?:\s+smooth\s+csplines)?\s+notitle\s+axes\s+(x1y1|x1y2)'
            r'\s+with\s+lines\s+lw\s+([\d.]+)(?:\s+lc\s+rgb\s+"([^"]+)")?'
        )
        # [수정 - 사용자 재지적] "curve title이 전부 파일명으로 나오는 게
        # 말이 안 됨 - *.plt를 직접 그리면 제대로 나오는데" - 맞는 지적이었음:
        # "plot \" 명령 자체는 항상 notitle이라 거기엔 원래 title이 없는 게
        # 맞지만, 그 원래 title은 이 파일 안에 이미 따로(_render_legend_box가
        # main legend를 그리려고 남겨둔) "set label 800N/900N "실제 제목""
        # 으로 그대로 남아있음(같은 curve의 "set arrow 800N/900N ... lc rgb
        # "색"... dashtype (...)"에는 원래 색/점선 스타일까지 같이 남아있음) -
        # .plt를 직접 실행하면 이 label들이 그대로 화면에 그려지니 제대로
        # 보였던 것. 이 legend arrow/label 쌍을 curve와 같은 순서로 추가
        # 파싱해서, 파일명 대신 이 실제 title(+dashtype)을 쓴다.
        # [수정 - 재검토로 발견된 버그] "PIP .plt 소스 curve에 marker가
        # 설정돼 있으면 legend title이 marker 기호(예: "○"/"△") 한 글자로
        # 나옴" - _render_legend_box는 marker가 있는 curve일 때 "set arrow"
        # 와 진짜 title "set label" 사이에 marker 기호용 "set label
        # (ID+5000) "○" ..."을 하나 더 끼워 넣는데(legend에 기호도 같이
        # 보여주려는 것), 위 정규식은 "set arrow 바로 다음 줄의 set label"을
        # 무조건 title로 가정해서 marker가 있으면 그 끼워진 기호 label을
        # 잘못 집었음. 실제로는 title의 "set label ID"가 "set arrow ID"와
        # 항상 같은 번호(마커 기호는 ID+5000)이므로, arrow의 번호를
        # 캡처해뒀다가 그 "같은 번호"를 가진 label만 title로 매치한다
        # (중간에 끼는 marker 기호 label은 번호가 다르므로 있어도 없어도
        # 건너뛰도록 선택 그룹으로 허용).
        _legend_pair_re = re.compile(
            r'set arrow (\d+) from graph [^\n]*?'
            r'lc rgb "([^"]+)" lw [\d.]+(?:\s+dashtype \(([^)]+)\))?\s*\n'
            r'(?:set label \d+ "(?:[^"\\]|\\.)*" at graph[^\n]*\n)?'
            r'set label \1 "((?:[^"\\]|\\.)*)" at graph'
        )
        _legend_entries = [
            (m.group(2), m.group(4), m.group(3))  # (color, title, dashtype_raw)
            for m in _legend_pair_re.finditer(text)
        ]
        _dash_to_style = {v.replace(" ", ""): k for k, v in DASH_PATTERNS.items()}

        def _style_for_dashtype(raw):
            if not raw:
                return None
            return _dash_to_style.get(raw.replace(" ", ""))

        base_dir = os.path.dirname(os.path.abspath(plt_path))
        curves = []
        warnings = []
        # [추가 - 사용자 질문/요청] _build_plot_commands가 같이 남겨둔 원본 dat
        # 파일 경로 복구용 주석("# CathPlot-src N orig="..." xout=N")을 curve
        # 순번(N) 기준으로 파싱해둔다 - N은 아래 "for i, m in enumerate(_matches)"
        # 의 i와 항상 같은 기준(둘 다 plotdef.curves를 순서대로 훑어 만들어짐)
        # 이라 그대로 조회할 수 있다. 이 주석이 없는(예전 버전에서 만든) .plt는
        # 그냥 빈 dict라 아래 폴백이 자동으로 생략되고 기존 동작 그대로다.
        _origin_re = re.compile(r'#\s*CathPlot-src\s+(\d+)\s+orig="((?:[^"\\]|\\.)*)"\s+xout=(\d+)')
        _origin_map = {}
        for _om in _origin_re.finditer(text):
            try:
                _origin_map[int(_om.group(1))] = (_om.group(2).replace('\\"', '"'), int(_om.group(3)))
            except ValueError:
                pass
        _matches = list(pattern.finditer(text))
        # 개수가 정확히 같으면(가장 흔한 경우 - legend에서 빠진 curve가 없음)
        # 순서 그대로 1:1 대응시킨다 - plot \ 절과 legend 블록 둘 다
        # _build_plot_commands가 같은 curves 리스트를 같은 순서로 훑어
        # 만들므로 순서가 항상 일치함(색이 우연히 같은 curve가 있어도
        # 순서 매칭은 영향받지 않음).
        _use_positional = len(_legend_entries) == len(_matches)
        # 개수가 다르면(예: 일부 curve가 Legend에서 제외됨) 색상 기준으로
        # 대응시킨다 - 이 경우 같은 색을 쓰는 curve가 여럿이면 그 중 하나만
        # 골라지는 한계가 있지만, 파일명보다는 항상 낫다.
        _color_lookup = {}
        if not _use_positional:
            for color, title, dash_raw in _legend_entries:
                _color_lookup.setdefault(color, (title, dash_raw))

        for i, m in enumerate(_matches):
            path, x_col, x_shift, y_col, axis, lw, color = m.groups()
            dat_file = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
            # [추가 - 사용자 질문/요청] "다른 기기/세션이면 이 경로(대부분
            # resort_dat_file의 임시 정렬 캐시)가 없을 텐데?" - 없으면 원본
            # 경로(위 _origin_map, cwd 기준 상대경로)로 이 기기에서 정렬
            # 캐시를 그 자리에서 다시 만들어본다. 원본조차 없으면(또는 이
            # 주석 자체가 없는 예전 .plt면) 이 curve만 건너뛰고 이유를
            # warnings에 남겨 호출부가 사용자에게 알릴 수 있게 한다(예전처럼
            # 조용히 사라지지 않음).
            if not os.path.exists(dat_file):
                _orig_info = _origin_map.get(i)
                _recovered = None
                if _orig_info:
                    _orig_rel, _orig_xout = _orig_info
                    _orig_abs = _orig_rel if os.path.isabs(_orig_rel) else os.path.join(self.cwd, _orig_rel)
                    if os.path.exists(_orig_abs):
                        try:
                            _recovered = self.resort_dat_file(_orig_abs, _orig_xout)
                        except Exception:
                            _recovered = _orig_abs  # 정렬은 실패해도 원본 자체는 있으니 그거라도 사용
                if _recovered and os.path.exists(_recovered):
                    dat_file = _recovered
                elif _orig_info:
                    warnings.append(
                        f"curve {i + 1}: dat 파일을 찾을 수 없습니다 "
                        f"(정렬 캐시: {os.path.basename(path)} 없음, 원본도 없음: {_orig_info[0]})"
                    )
                    continue
                else:
                    warnings.append(
                        f"curve {i + 1}: dat 파일을 찾을 수 없습니다 ({path}) - "
                        "이 .plt에는 원본 경로 복구 정보가 없습니다(예전 버전에서 생성됐을 수 있음)"
                    )
                    continue
            _title = None
            _dash_raw = None
            if _use_positional:
                _entry_color, _title, _dash_raw = _legend_entries[i]
            elif color and color in _color_lookup:
                _title, _dash_raw = _color_lookup[color]
            if not _title:
                _title = os.path.splitext(os.path.basename(dat_file))[0]
            try:
                curves.append(CurveDefinition(
                    dat_file=dat_file,
                    output_no=int(y_col) - 1,
                    title=_title,
                    axis="y2" if axis == "x1y2" else "y1",
                    x_shift=float(x_shift or 0.0),
                    color=color or None,
                    linestyle=_style_for_dashtype(_dash_raw),
                    linewidth=float(lw or 1.5),
                    x_output_no=int(x_col) - 1,
                ))
            except ValueError:
                continue  # X/Y 컬럼이 같은 경우 등은 건너뜀(CurveDefinition.__post_init__ 참고)
        return curves, warnings

    def _parse_plt_titles(self, plt_path):
        """[추가 - 요청] "in-plot x/y1/y2의 default를 main-plot(또는 읽어온
        plot)의 축 title을 넣어줘요" - PIP source가 ".plt 파일"일 때는 그
        파일 자신의 title/xlabel/ylabel/y2label을 기본값 후보로 쓰기 위해,
        _parse_plt_curves와 같은 방식(우리 자신의 생성 포맷 전용, 범용
        파서 아님)으로 "set title/xlabel/ylabel/y2label "..."" 줄을 찾는다.
        그 .plt 파일 자체에 PIP 인셋이 포함돼 있으면 인셋 구간(주석
        "# --- PIP (부분 확대) inset ---" 이후)은 그 인셋 자신의 title 재선언
        이라 메인 것과 섞이면 안 되므로, 그 앞부분만 본다. 같은 줄이 여러 번
        나오면(예: 조건별 재설정) 마지막 것을 실제 적용된 값으로 본다.
        읽기 실패 시 None."""
        try:
            with open(plt_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return None
        marker = "# --- PIP (부분 확대) inset ---"
        idx = text.find(marker)
        main_text = text[:idx] if idx >= 0 else text

        def _last(pattern):
            matches = re.findall(pattern, main_text)
            return matches[-1] if matches else ""

        _q = r'((?:[^"\\]|\\.)*)'
        return (
            _last(r'set title "' + _q + '"'),
            _last(r'set xlabel "' + _q + '"'),
            _last(r'set ylabel "' + _q + '"'),
            _last(r'set y2label "' + _q + '"'),
        )

    def _parse_plt_ranges(self, plt_path):
        """[추가 - 요청] "당연히 .plt 파일 자체에서 Y 범위도 같이 읽어와서
        자동으로 채우기 해야지요" - PIP 소스가 ".plt 파일"이면 원/타원
        클리핑에 X뿐 아니라 Y1(및 Y2 곡선이 있으면 Y2)까지 "구체적인 숫자"
        범위가 필요한데(_ellipse_native_ok), 그동안 사용자가 PIP 팝업에
        Y1/Y2 min/max를 직접 입력해야만 했음 - 이미 그 .plt 파일 자신이
        메인 plot을 그릴 때 쓴 set yrange/y2range를 그대로 갖고 있으므로
        (_parse_plt_titles와 같은 방식 - PIP 인셋 구간 이전만, CathPlot
        자신의 생성 포맷 전용) 그 값을 그대로 읽어와서 기본값으로 쓸 수
        있다.
        [수정 - 사용자 재보고] "PIP에 있던 *.plt에 X-range도 있는데 기본값
        으로 안 읽어 오네?" - Y1/Y2만 읽고 X는 빠져 있었음(같은 파일에
        "set xrange [...]"도 항상 같이 있으므로 안 읽을 이유가 없음) -
        Y1/Y2와 완전히 같은 방식으로 xrange도 같이 읽어온다.
        반환: (xmin, xmax, ymin, ymax, y2min, y2max) - 각각 못 찾으면 None."""
        try:
            with open(plt_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return (None, None, None, None, None, None)
        marker = "# --- PIP (부분 확대) inset ---"
        idx = text.find(marker)
        main_text = text[:idx] if idx >= 0 else text

        def _last_range(prefix):
            matches = re.findall(
                prefix + r'\s*\[\s*([^:\]]+)\s*:\s*([^:\]]+)\s*\]', main_text
            )
            return matches[-1] if matches else None

        xr = _last_range(r'set\s+xrange')
        yr = _last_range(r'set\s+yrange')
        y2r = _last_range(r'set\s+y2range')
        return (
            xr[0].strip() if xr else None, xr[1].strip() if xr else None,
            yr[0].strip() if yr else None, yr[1].strip() if yr else None,
            y2r[0].strip() if y2r else None, y2r[1].strip() if y2r else None,
        )

    def _parse_plt_display_flags(self, plt_path):
        """[추가 - 사용자 요청] "PIP 소스가 cached/pltfile이면 original을 몰라
        자동 인식이 안 된다"는 한계를 없애기 위해, ".plt 파일" 소스일 때도
        그 원본이 실제로 grid/legend/marker를 썼는지 감지한다(_parse_plt_
        titles/_parse_plt_ranges와 같은 방식 - 우리 자신의 생성 포맷 전용,
        PIP 인셋 구간 이전 "메인" 부분만 봄). 반환: (grid_on, legend_on,
        marker_on) 각각 bool 또는(판단 불가 시) None - 호출부는 None이면
        그 항목의 자동 동기화를 건너뛴다."""
        try:
            with open(plt_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return (None, None, None)
        marker_sep = "# --- PIP (부분 확대) inset ---"
        idx = text.find(marker_sep)
        main_text = text[:idx] if idx >= 0 else text

        _grid_matches = re.findall(r'^\s*(set grid\b[^\n]*|unset grid)\s*$', main_text, re.MULTILINE)
        grid_on = _grid_matches[-1].startswith("set grid") if _grid_matches else None

        # legend는 _parse_plt_curves가 쓰는 것과 같은 "set arrow ID ... \n set label ID" 짝
        # (legend 항목 하나당 하나씩 남음)이 하나라도 있으면 legend가 있던 것으로 본다.
        _legend_pair_re = re.compile(
            r'set arrow (\d+) from graph [^\n]*?'
            r'lc rgb "([^"]+)" lw [\d.]+(?:\s+dashtype \(([^)]+)\))?\s*\n'
            r'(?:set label \d+ "(?:[^"\\]|\\.)*" at graph[^\n]*\n)?'
            r'set label \1 "((?:[^"\\]|\\.)*)" at graph'
        )
        legend_on = bool(_legend_pair_re.search(main_text))

        marker_on = "with points pt " in main_text

        return (grid_on, legend_on, marker_on)

    def _resolve_pip_original_flags(self):
        """[추가 - 사용자 요청] "cached/pltfile도 original을 보고 자동 인식해야"
        - PIP 표시 옵션(Plot Title/Axis Title/Legend/Grid/Marker) 체크박스의
        기본값/비활성화 판단에 쓸, "PIP가 실제로 보여줄 원본"의 title/axis
        title/legend/grid/marker 유무를 소스별로 알아낸다. 판단 불가한
        항목은 None(호출부가 자동 동기화를 건너뛰는 신호)으로 둔다.
        - source="current": 메인 화면 tk 변수를 그대로 읽음(가장 흔한 경우).
        - source="cached": self.active_plots_cache에 이미 들어있는 완성된
          PlotDefinition 객체(title/legend_on/major_grid/curves 등을 이미
          속성으로 갖고 있음)에서 직접 읽음 - 추가 파싱 불필요.
        - source="pltfile": 그 .plt 파일을 _parse_plt_titles/_parse_plt_
          display_flags로 파싱해서 읽음(우리 자신의 생성 포맷 전용 파서).
        """
        source = self.pip_source_var.get()
        flags = {"title": None, "axis_title": None, "legend": None, "grid": None, "marker": None}

        if source == "current":
            flags["title"] = bool(self.title_var.get().strip())
            flags["axis_title"] = bool(
                self.xlabel_var.get().strip() or self.ylabel_var.get().strip() or self.y2label_var.get().strip()
            )
            flags["legend"] = self.legend_on_var.get()
            flags["grid"] = self.major_grid_var.get()
            try:
                _sel_keys = self._ordered_selected_keys()[0]
            except Exception:
                _sel_keys = []
            flags["marker"] = any(
                self.marker_shape_vars[k].get() != "None" for k in _sel_keys if k in self.marker_shape_vars
            )
        elif source == "cached":
            name = self.pip_cached_name_var.get()
            pd = self.active_plots_cache.get(name)
            if pd is not None:
                flags["title"] = bool((pd.title or "").strip())
                flags["axis_title"] = bool(
                    (pd.xlabel or "").strip() or (pd.ylabel or "").strip() or (pd.y2label or "").strip()
                )
                flags["legend"] = bool(getattr(pd, "legend_on", False))
                flags["grid"] = bool(getattr(pd, "major_grid", False))
                flags["marker"] = any(
                    getattr(c, "marker_shape", None) is not None for c in getattr(pd, "curves", []) or []
                )
        elif source == "pltfile":
            path = self.pip_pltfile_path_var.get()
            if path and os.path.exists(path):
                titles = self._parse_plt_titles(path)
                if titles is not None:
                    t, xl, yl, y2l = titles
                    flags["title"] = bool((t or "").strip())
                    flags["axis_title"] = bool((xl or "").strip() or (yl or "").strip() or (y2l or "").strip())
                grid_on, legend_on, marker_on = self._parse_plt_display_flags(path)
                flags["grid"] = grid_on
                flags["legend"] = legend_on
                flags["marker"] = marker_on
        return flags

    @staticmethod
    def _clip_pct_to_stored(raw):
        """[추가 - 사용자 지적] 화면에 보이는 "반지름 %"(박스 자신의 절반
        기준, 100=꽉참)를 gnu_generator.py가 기대하는 저장 관례("박스 전체
        크기" 기준, 50=꽉참)로 변환 - 단순히 절반. 빈 값/숫자 아님은 그대로
        돌려줘 기존 빈칸(Ry 비우면 원) 관례를 그대로 보존한다."""
        raw = (raw or "").strip()
        if not raw:
            return raw
        try:
            return str(float(raw) / 2.0)
        except (TypeError, ValueError):
            return raw

    @staticmethod
    def _clip_pct_from_stored(raw):
        """[추가 - 사용자 지적] 저장된 값(박스 전체 기준, 50=꽉참)을 화면
        표시용(박스 절반=반지름 기준, 100=꽉참)으로 되돌린다 - 위 함수의
        역변환(2배)."""
        raw = (raw or "").strip()
        if not raw:
            return raw
        try:
            return str(float(raw) * 2.0)
        except (TypeError, ValueError):
            return raw

    def _display_relpath(self, abs_path):
        """[추가 - 사용자 요청] "Browse 칸에 절대경로 대신 상대경로만" - DAT
        Files 각 행의 입력칸(화면 표시 전용 - info["filename"]이 실제 파일
        접근에 쓰이는 절대경로를 따로 그대로 유지하므로 이건 순수하게
        보여주기만 바꾸는 안전한 변경)에 cwd 기준 상대경로를 보여준다.
        Template에 저장되는 상대경로(_capture_file_assignments의 rel_path)
        와 완전히 같은 계산이라 "Template에 저장될 값 그대로"를 미리 보는
        셈이기도 하다. cwd 밖(다른 드라이브 등 - relpath 계산 자체가 불가능한
        경우)이면 절대경로를 그대로 보여준다."""
        try:
            return os.path.relpath(abs_path, self.cwd)
        except ValueError:
            return abs_path

    def _pip_default_titles(self):
        """[추가 - 요청] PIP 팝업을 열 때 Plot Title/X/Y1/Y2 Title 입력칸에
        미리 채워줄 기본값을, source에 맞는 원본에서 가져온다 - "현재
        화면"(current)이면 지금까지처럼 이 탭 자신의 title_var 등을 그대로
        쓰지만, "저장된 plot"(cached)이나 ".plt 파일"(pltfile)이면 그
        원본(다른 plot)이 있을 수 있는데도 항상 이 탭 자신의 값만 보여주는
        건 부적절함 - 실제로 인셋에 그려질 그 원본 자신의 title을 기본값
        으로 삼는다. cached plotdef를 못 찾거나(다른 세션 Template 등) .plt
        파일에서 못 읽으면 안전하게 이 탭 자신의 값으로 폴백한다."""
        source = self.pip_source_var.get()
        if source == "cached":
            cached = self.active_plots_cache.get(self.pip_cached_name_var.get())
            if cached is not None:
                return (cached.title or "", cached.xlabel or "", cached.ylabel or "", cached.y2label or "")
        elif source == "pltfile":
            path = self.pip_pltfile_path_var.get()
            if path and os.path.exists(path):
                parsed = self._parse_plt_titles(path)
                if parsed is not None:
                    return parsed
        return (self.title_var.get(), self.xlabel_var.get(), self.ylabel_var.get(), self.y2label_var.get())

    def open_pip_dialog(self):
        """[추가 - 요청] PIP(Picture-in-Picture, 부분 확대) 설정 팝업 - 3D
        Plot과 같은 방식으로 메인 창엔 버튼 하나만 두고 나머지 설정은 여기서.
        확인(OK)을 누르면 tk 변수에 반영되고, PLOT/SAVE/PRINT 때 그 값을 읽어
        pip 활성화 여부와 무관하게 항상 반영한다(꺼져 있으면 _render_pip_inset이
        아무것도 안 그림)."""
        # [수정 - 버그] "PIP 버튼을 누를 때마다 똑같은 창이 중복으로 계속 생김" -
        # open_permanent_symbol_window(Ω 팔레트)와 같은 패턴: 이미 열려있는
        # 창이 있으면 새로 만들지 않고 그 창을 맨 위로 올리기만 한다.
        if hasattr(self, "_pip_dialog") and self._pip_dialog.winfo_exists():
            self._pip_dialog.lift()
            self._pip_dialog.focus_force()
            return

        dlg = tk.Toplevel(self.root)
        self._pip_dialog = dlg
        dlg.title("PIP - 작은 plot을 부분 확대해서 겹쳐 그리기")
        dlg.transient(self.root)
        # [수정 - 사용자 보고] "PIP 입력창의 세로 길이를 늘려줘요 - 3줄 정도
        # 잘림(4줄 정도 키울 것)" - Plot Title/X/Y1/Y2 Title 텍스트 입력칸
        # (2줄) + 안내 문구(1줄)를 표시 옵션에 새로 추가하면서 늘어난 내용
        # 만큼 창 높이는 그대로였던 것이 원인 - 540 -> 650(약 4줄 분량,
        # 110px)로 키움.
        # [수정 - 사용자 요청] "PIP 입력창 세로길이를 2줄 정도 줄여줘요" -
        # 위에서 키운 뒤로 아래쪽에 여백이 남아 보인다는 피드백 - 한 줄을
        # 위와 같은 기준(약 27px)으로 잡아 2줄분(약 55px) 줄임(650 -> 595).
        # [수정 - 사용자 재요청] "PIP 입력화면을 3줄 더 키워줘요. 닫기 버튼은
        # 맨 아래에 항상 보이게" - 세로 길이를 계속 조금씩 늘렸다 줄였다 해온
        # 이력(540->650->595) 자체가, 화면(특히 사용자의 노트북처럼 작은
        # 화면)마다 실제로 필요한 높이가 달라 고정 숫자로는 근본적으로 못
        # 맞춘다는 뜻 - 이번엔 숫자만 또 조정하는 대신 구조를 바꾼다: 닫기
        # 버튼(btn_row)을 본문보다 먼저, dlg에 직접 side="bottom"으로 pack해
        # 공간을 먼저 확보하고(그래야 본문이 넘쳐도 밀려나지 않고 항상 보임),
        # 나머지 본문 전체를 Canvas+Scrollbar로 감싸 화면이 작아 다 안
        # 들어가도 마우스 휠로 스크롤해서 볼 수 있게 한다.
        # [수정 - 사용자 재요청] "스크롤바가 생겼으니 3줄 대신 2줄만 늘려줘요
        # (PC에서는 너무 남을 수도 있어서). 화면 해상도에 따라 flexible하게
        # 안 되나요?" - 스크롤이 이미 안전망이므로 굳이 3줄(680)까지 키울
        # 필요는 없다는 지적이 맞음 - 기준을 2줄(595+~55px=650)로 낮추고,
        # 그 값을 고정 숫자로 박아두는 대신 실제 화면 높이(winfo_screenheight)
        # 에 비례해서 계산한다: 화면이 작으면(노트북 등) 그만큼 비례해서
        # 더 작게 열어(모자란 부분은 스크롤로 보완), 화면이 크면(데스크톱)
        # 650을 넘지 않게 상한을 둬서(요청하신 "너무 남는" 여백 방지) 그 두
        # 극단 사이를 화면 크기에 맞게 자동으로 채운다. 작업표시줄/제목줄
        # 등에 뺏기는 여백을 고려해 화면 높이에서 100px을 먼저 빼고 계산.
        # [수정 - 사용자 요청] "PIP 입력창 세로를 조금 더 길게" - 상한을
        # 650 -> 700으로 올린다(화면이 작으면 여전히 비례해서 줄어들고,
        # 그래도 모자라면 스크롤이 안전망 - 구조는 그대로 유지).
        # [수정 - 사용자 요청] "화면의 가로폭을 글자 안 잘리게 조금 더 키우고,
        # 세로폭도 1줄 정도 더 키울 것" - 가로 760 -> 820(라벨/입력칸이 긴
        # 줄, 예: "반지름(%, 보통 20~40 · 100=축 전체를 채움):"이 잘리던 것
        # 방지), 세로는 위 이력과 같은 기준(한 줄 ≈ 27~30px)으로 상하한을
        # 모두 30px씩 올림(420->450, 700->730) - 화면 크기 비례 계산 구조는
        # 그대로 유지.
        _screen_h = dlg.winfo_screenheight()
        _dlg_h = max(450, min(730, int((_screen_h - 100) * 0.85)))
        dlg.geometry(f"820x{_dlg_h}")

        # [수정 - 요청] "팝업 안의 PIP 사용 체크박스는 없애고, 메인 창 PIP
        # 버튼 앞 체크박스 하나로 통일" - 여기 있던 중복 체크박스 제거
        # (self.pip_enabled_var는 메인 창에서 이미 켜져 있는 상태로 이 팝업이
        # 열림 - _open_pip_dialog_and_enable 참고).

        # [추가 - 사용자 요청] "닫기 버튼은 맨 아래에 항상 보이게" - 본문
        # (스크롤 영역)보다 먼저 dlg에 직접 pack(side="bottom")해서 세로
        # 공간을 먼저 확보한다(Tk pack은 나중에 pack되는 쪽이 남은 공간을
        # 쓰므로, 순서를 바꿔 이 버튼이 항상 우선권을 갖게 함 - 본문이
        # 넘치면 밀려나는 쪽은 이제 스크롤 영역이지 이 버튼이 아니다).
        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=10, pady=15, side="bottom")
        self._mk_btn(btn_row, "닫기", dlg.destroy, color="accent", side="right", padx=5)

        # [추가 - 사용자 요청] 본문을 스크롤 가능하게 감싸는 Canvas -
        # 화면이 작아 위 680px 높이로도 다 안 들어가면 마우스 휠로 스크롤.
        _body_canvas = tk.Canvas(dlg, highlightthickness=0)
        _body_vsb = ttk.Scrollbar(dlg, orient="vertical", command=_body_canvas.yview)
        _body_canvas.configure(yscrollcommand=_body_vsb.set)
        _body_vsb.pack(side="right", fill="y")
        _body_canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(_body_canvas)
        _body_window_id = _body_canvas.create_window((0, 0), window=body, anchor="nw")

        def _on_body_configure(event=None):
            _body_canvas.configure(scrollregion=_body_canvas.bbox("all"))
        body.bind("<Configure>", _on_body_configure)

        def _on_canvas_configure(event):
            # 본문 안의 LabelFrame들이 fill="x"로 캔버스 폭을 그대로 따라가게
            _body_canvas.itemconfigure(_body_window_id, width=event.width)
        _body_canvas.bind("<Configure>", _on_canvas_configure)

        # [수정 - 코드 재검토로 발견된 버그, 더 심각한 재수정] 처음엔 여기서
        # 직접 bind_all로 마우스 휠을 잡았는데, "이 팝업 위가 아니어도(메인
        # 창 file/var 목록 위에서도) 이 본문이 같이 스크롤됨"뿐 아니라 -
        # bind_all은 위젯이 아니라 애플리케이션 전체의 "all" 태그 하나를
        # 공유해서, add="+" 없이 다시 bind_all을 걸면 이미 걸려있던 메인
        # 창의 전역 휠 핸들러(_on_global_mousewheel, 아래 참고)를 통째로
        # "덮어써서" 이 팝업이 열려있는 동안 메인 창 file/var/Plot Setting
        # 목록의 휠 스크롤이 전혀 안 먹게 되고, 팝업을 닫을 때 하던
        # unbind_all은 그 자리를 원래 핸들러로 복구하는 게 아니라 아예
        # 아무 것도 없는 상태로 지워버려서 그 뒤로는 메인 창 스크롤 자체가
        # 영구히 먹통이 되는 훨씬 심각한 문제였음. 새로 만드는 대신, 메인
        # 창 file/var/Plot Setting 목록이 이미 쓰고 있는 공용 메커니즘
        # (_bind_mousewheel/_on_global_mousewheel - bind_all을 앱 전체에
        # 딱 한 번만 걸어두고, event.widget에서 조상 방향으로 올라가며 어느
        # 영역에 속하는지 찾아 그 영역의 캔버스만 스크롤) 그대로 재사용한다
        # - 새로 bind_all을 걸지 않으므로 위 덮어쓰기 문제 자체가 없다.
        self._bind_mousewheel(body, _body_canvas)
        # [추가 - 코드 재검토로 발견된 버그] 위 등록을 팝업이 닫힐 때(다시
        # 열 때마다 body가 매번 새 위젯이라 등록도 매번 새로 쌓임) 지우지
        # 않으면 self._wheel_regions가 죽은 위젯 참조로 계속 늘어남 - 팝업을
        # 열고 닫기를 반복하는 세션에서 누적됨(_unbind_mousewheel 참고).
        dlg.bind("<Destroy>", lambda e: self._unbind_mousewheel(body))

        # --- 데이터 소스 ---
        src_frame = ttk.LabelFrame(body, text="작은 plot에 표시할 데이터")
        src_frame.pack(fill="x", padx=10, pady=5)

        cached_combo_ref = {}

        def _refresh_cached_names():
            self._cleanup_stale_plot_cache()
            names = sorted(self.active_plots_cache.keys())
            combo = cached_combo_ref.get("combo")
            if combo is not None:
                combo["values"] = names
                if self.pip_cached_name_var.get() not in names and names:
                    self.pip_cached_name_var.set(names[0])

        ttk.Radiobutton(
            src_frame, text="현재 plot (이 화면 설정 그대로, 확대만)",
            variable=self.pip_source_var, value="current"
        ).pack(anchor="w", padx=5, pady=(5, 2))

        cached_row = ttk.Frame(src_frame)
        cached_row.pack(fill="x", padx=5, pady=2)
        ttk.Radiobutton(
            cached_row, text="이미 그려진 plot:", variable=self.pip_source_var, value="cached"
        ).pack(side="left")
        cached_combo = ttk.Combobox(
            cached_row, textvariable=self.pip_cached_name_var, state="readonly", width=22
        )
        cached_combo.pack(side="left", padx=(5, 0))
        cached_combo_ref["combo"] = cached_combo
        self._mk_btn(cached_row, "새로고침", _refresh_cached_names, color="grey", side="left", padx=(5, 0))
        _refresh_cached_names()

        pltfile_row = ttk.Frame(src_frame)
        pltfile_row.pack(fill="x", padx=5, pady=(2, 5))
        ttk.Radiobutton(
            pltfile_row, text="plt 파일:", variable=self.pip_source_var, value="pltfile"
        ).pack(side="left")
        pltfile_label = ttk.Label(pltfile_row, text="(선택 안 됨)", foreground="#555555", width=22, anchor="w")
        pltfile_label.pack(side="left", padx=(5, 0))

        def _pick_pltfile():
            path = filedialog.askopenfilename(
                parent=dlg, initialdir=self.plot_dir,
                filetypes=[("gnuplot script", "*.plt"), ("All files", "*.*")],
                title="PIP에 쓸 .plt 파일 선택"
            )
            if not path:
                return
            self.pip_pltfile_path_var.set(path)
            pltfile_label.config(text=os.path.basename(path), foreground="black")
            self.pip_source_var.set("pltfile")

        self._mk_btn(pltfile_row, "찾아보기...", _pick_pltfile, color="grey", side="left", padx=(5, 0))
        if self.pip_pltfile_path_var.get():
            _cur_pltfile = self.pip_pltfile_path_var.get()
            # [추가 - 사용자 질문/요청] "template를 다른 폴더에서 가져오면
            # PIP그림은 없으니까... 위치를 다시 입력하게" - 다이얼로그를 열
            # 때마다(다른 기기/폴더에서 불러온 Template일 수 있으므로) 현재
            # 경로가 실제로 존재하는지 확인해서, 없으면 빨간 글씨로 표시해
            # "찾아보기..."로 다시 지정하라는 신호를 바로 눈에 띄게 준다
            # (렌더링 시점의 messagebox 경고와 별개로, 설정을 여는 즉시 보임).
            if os.path.exists(_cur_pltfile):
                pltfile_label.config(text=os.path.basename(_cur_pltfile), foreground="black")
            else:
                pltfile_label.config(text=f"(없음) {os.path.basename(_cur_pltfile)}", foreground="red")

        # --- 위치/크기 ---
        # [수정 - 요청] "기준이 좌상단/캔버스 전체인데 legend/annotation은
        # 좌하단/축 프레임 기준" - 라벨도 실제 동작(축 프레임 기준, 좌측
        # 하단 모서리)에 맞게 수정.
        geo_frame = ttk.LabelFrame(body, text="위치(축 프레임 대비 %) / 크기")
        geo_frame.pack(fill="x", padx=10, pady=5)
        # [수정 - 사용자 요청] "PIP popup 화면에서 입력 box들이 아래위가
        # 예쁘게 정렬되게" - 각 줄의 첫 라벨("좌측 하단 X(%):"/"가로
        # 크기(W):"/"프레임 모양:")이 길이가 서로 달라 그 뒤 입력칸이
        # 줄마다 다른 x 위치에서 시작했음 - 제일 긴 라벨 기준으로 폭을
        # 통일(anchor="w"로 왼쪽 정렬)해서 입력칸들이 세로로 한 줄에 맞게
        # 정렬되도록 한다.
        _GEO_LABEL_W = 13
        pos_row = ttk.Frame(geo_frame)
        pos_row.pack(fill="x", padx=5, pady=3)
        ttk.Label(pos_row, text="좌측 하단 X(%):", width=_GEO_LABEL_W, anchor="w").pack(side="left")
        ttk.Entry(pos_row, textvariable=self.pip_pos_x_var, width=6).pack(side="left", padx=(4, 12))
        ttk.Label(pos_row, text="Y(%):").pack(side="left")
        ttk.Entry(pos_row, textvariable=self.pip_pos_y_var, width=6).pack(side="left", padx=(4, 0))
        size_row = ttk.Frame(geo_frame)
        size_row.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Label(size_row, text="가로 크기(W):", width=_GEO_LABEL_W, anchor="w").pack(side="left")
        ttk.Entry(size_row, textvariable=self.pip_size_w_var, width=6).pack(side="left", padx=(4, 8))
        ttk.Label(size_row, text="세로 크기(H):").pack(side="left")
        ttk.Entry(size_row, textvariable=self.pip_size_h_var, width=6).pack(side="left", padx=(4, 8))
        # [추가 - 요청] "작은 plot 크기를 실제 길이 or %로" - %(캔버스 대비
        # 비율, 기본)이거나 in/cm(실제 물리적 길이)를 고를 수 있게.
        ttk.Combobox(
            size_row, textvariable=self.pip_size_unit_var, values=["%", "in", "cm"],
            width=4, state="readonly"
        ).pack(side="left", padx=(4, 0))

        # [추가 - 요청] "원/타원으로 클리핑" - 위 위치/크기(박스) 자체와는
        # 별개로, 그 박스 안에서 실제로 보이는 모양을 사각형 대신 원/타원으로
        # 잘라낼 수 있게 함(annotation의 Circle과 같은 관례: Radius(Rx,Ry),
        # Ry 비우면 원). "원/타원"을 고르면 Rx/Ry 입력이 활성화된다.
        clip_row = ttk.Frame(geo_frame)
        clip_row.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Label(clip_row, text="프레임 모양:", width=_GEO_LABEL_W, anchor="w").pack(side="left")
        clip_shape_combo = ttk.Combobox(
            clip_row, textvariable=self.pip_clip_shape_var,
            values=["rect", "circle", "ellipse"], width=8, state="readonly"
        )
        clip_shape_combo.pack(side="left", padx=(4, 12))
        # [수정 - 요청] "반지름 50%가 지름 100%라 마치 메인 plot 전체를
        # 말하는 것처럼 보여서 헷갈림" - 이 %의 기준은 메인 plot 전체가
        # 아니라 바로 위에서 W/H%로 정한 "in-plot(PIP) 박스 자신"의 폭/
        # 높이임을 라벨에 명시.
        # [수정 - 사용자 지적] "반지름끼리 비교하면 100%가 꽉참이어야
        # 하지 않나?" - 맞는 지적: 예전엔 "박스 전체 크기 대비 %"라
        # 50%가 꽉참이었음(반지름을 지름과 비교하는 셈이라 안 와닿음) -
        # 이제 화면 입력은 "박스 자신의 절반(=박스의 반지름) 대비 %"로
        # 바꿔 100%가 꽉참이 되도록 함(저장값은 하위호환을 위해 그대로
        # 유지 - _clip_pct_to_stored/_clip_pct_from_stored가 화면↔저장
        # 사이에서 변환).
        ttk.Label(clip_row, text="Radius(Rx,Ry) %(in-plot 박스 대비,100=꽉참):").pack(side="left")
        clip_rx_entry = ttk.Entry(clip_row, textvariable=self.pip_clip_rx_var, width=6)
        clip_rx_entry.pack(side="left", padx=(4, 2))
        clip_ry_entry = ttk.Entry(clip_row, textvariable=self.pip_clip_ry_var, width=6)
        clip_ry_entry.pack(side="left", padx=(2, 4))
        # [수정 - 사용자 요청] "PIP 창의 tip 등은 진한 이탤릭체 등으로 -
        # 잘 안보임" - 옅은 회색(gray)이라 눈에 잘 안 띄었음. 이 아래 PIP
        # 팝업의 보조 설명 라벨들을 전부 짙은 회색(#3a3a3a)+기울임으로 바꿔
        # 잘 읽히게 한다.
        # [수정 - 사용자 지적] "팁 글자는 보통 진하기로(입력 설명과 구별
        # 되게)" - 굵게(bold)까지 주면 오히려 실제 입력 라벨(각 필드 이름)
        # 만큼 진해 보여 구분이 안 됐음 - 굵기는 보통으로 낮추고 기울임+
        # 짙은 회색만 유지해 "부차적 설명"임이 한눈에 구별되게 한다.
        ttk.Label(clip_row, text="(Ry 비우면 원)", foreground="#3a3a3a", font=("Malgun Gothic", 9, "italic")).pack(side="left")

        def _toggle_clip_entries(*_):
            _shape = self.pip_clip_shape_var.get()
            clip_rx_entry.config(state="normal" if _shape in ("circle", "ellipse") else "disabled")
            clip_ry_entry.config(state=("normal" if _shape == "ellipse" else "disabled"))
        _clip_trace_id = self.pip_clip_shape_var.trace_add("write", _toggle_clip_entries)
        _toggle_clip_entries()

        # --- 확대 구간 ---
        # [수정 - 버그] 이 라벨이 실제 동작과 어긋나 있었음 - "Y는 자동"은
        # 데이터 소스가 "이미 그려진 plot/plt 파일"일 때만 맞고, 기본값인
        # "현재 plot" 소스에서는 X와 마찬가지로 메인 plot의 실제 범위를 그대로
        # 물려받음(gnu_generator._render_pip_inset의 xrange_cmd/yrange_cmd
        # 참고) - 실제 조건 그대로 문구를 고침.
        zoom_frame = ttk.LabelFrame(
            body,
            text="확대 구간 (비우면: X는 항상 메인과 동일 / Y는 '현재 plot' 소스면 메인과 동일, 다른 소스면 자동)"
        )
        zoom_frame.pack(fill="x", padx=10, pady=5)
        # [수정 - 사용자 요청] "확대구간 Xmin,Xmax를 아래 Y1min,Y1max에
        # 정렬" - 두 줄의 첫 라벨("X min:"/"Y1 min:") 길이가 달라 입력칸
        # 시작 위치가 어긋났음 - 폭을 통일.
        _ZOOM_LABEL_W = 8
        xz_row = ttk.Frame(zoom_frame)
        xz_row.pack(fill="x", padx=5, pady=3)
        ttk.Label(xz_row, text="X min:", width=_ZOOM_LABEL_W, anchor="w").pack(side="left")
        ttk.Entry(xz_row, textvariable=self.pip_xmin_var, width=8).pack(side="left", padx=(4, 12))
        ttk.Label(xz_row, text="X max:", width=_ZOOM_LABEL_W, anchor="w").pack(side="left")
        ttk.Entry(xz_row, textvariable=self.pip_xmax_var, width=8).pack(side="left", padx=(4, 0))
        yz_row = ttk.Frame(zoom_frame)
        yz_row.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Label(yz_row, text="Y1 min:", width=_ZOOM_LABEL_W, anchor="w").pack(side="left")
        ttk.Entry(yz_row, textvariable=self.pip_ymin_var, width=8).pack(side="left", padx=(4, 12))
        ttk.Label(yz_row, text="Y1 max:", width=_ZOOM_LABEL_W, anchor="w").pack(side="left")
        ttk.Entry(yz_row, textvariable=self.pip_ymax_var, width=8).pack(side="left", padx=(4, 20))
        # [수정 - 요청] "Y1/Y2를 같은 줄에" - 별도 행 대신 같은 yz_row에
        # 이어서 배치(간격만 좀 더 줌).
        ttk.Label(yz_row, text="Y2 min:").pack(side="left")
        ttk.Entry(yz_row, textvariable=self.pip_y2min_var, width=8).pack(side="left", padx=(4, 12))
        ttk.Label(yz_row, text="Y2 max:").pack(side="left")
        ttk.Entry(yz_row, textvariable=self.pip_y2max_var, width=8).pack(side="left", padx=(4, 0))
        # [추가 - 요청] "Ymin/Ymax가 Y1에만 적용되고 Y2는 그대로 나타남 - Y2도
        # 따로 입력받게" (비우면 plot 자체 Y2 구간을 그대로 따름 -
        # gnu_generator._render_pip_inset의 y2range_cmd 참고).

        # --- 돋보기(magnifier) ---
        # [추가 - 요청] "돋보기 기능 - 여러 curve(/마커포함)가 겹치면 구별
        # 용도, 중심(x,y1)+반지름(x)+배율만 주면 확대해서 그려줌, 중심/
        # 반지름 둘 다 좌표값 또는 %로" - 켜면 위 X/Y min/max 입력은 무시
        # 되고 여기 값들로 자동 계산된다(gnu_generator.compute_magnifier_pip,
        # execute_plot_pipeline에서 plotdef 생성 직후 호출). main plot에는
        # 중심 위치에 점선 원(circles 주석 재사용)으로 표시됨.
        mag_frame = ttk.LabelFrame(body, text="돋보기 (중심+반지름+배율로 확대구간 자동계산 - 겹친 curve 구별용)")
        mag_frame.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(
            mag_frame, text="돋보기 모드 사용 (켜면 위 확대구간 입력 대신 이 값 사용)",
            variable=self.pip_mag_on_var
        ).pack(anchor="w", padx=5, pady=(5, 2))
        ttk.Label(
            mag_frame,
            text="팁: gnuplot 창에서 좌클릭으로 좌표 확인, 'r'로 눈금자(ruler) 고정 후 이동하면 dx가 표시됨(반지름 값으로 활용)",
            foreground="#3a3a3a", font=("Malgun Gothic", 8, "italic")
        ).pack(anchor="w", padx=5, pady=(0, 4))

        # [수정 - 사용자 요청] "data 대신 좌표값, pct 대신 %로" - 다른 곳
        # (Comment/Arrow/Circle 좌표 모드, self.COORD_MODE_DISPLAY 참고)과
        # 동일하게, 내부 저장 값("data"/"pct" - gnu_generator.py의
        # compute_magnifier_pip이 이 문자열로 분기)은 그대로 두고 화면
        # 표시용 별도 StringVar만 만들어 "%"/"좌표값"으로 보여준다.
        def _mk_mode_combo(parent, mode_var):
            _disp = tk.StringVar(value=self.COORD_MODE_DISPLAY.get(mode_var.get(), "좌표값"))
            def _sync(*_a):
                mode_var.set(self.COORD_MODE_FROM_DISPLAY.get(_disp.get(), "data"))
            _disp.trace_add("write", _sync)
            return ttk.Combobox(parent, textvariable=_disp, state="readonly", width=5, values=["좌표값", "%"])

        # [수정 - 사용자 요청] "두 줄로 나뉘어 있는데 한 줄로 합쳐줘요" -
        # 중심X/Y1 + 반지름X + 배율(대상 curve 쪽 4개 입력)을 한 줄로 합침.
        # [수정 - 사용자 요청] "PIP popup 입력 box들이 아래위가 예쁘게
        # 정렬되게" - 이 줄의 첫 라벨과 바로 아래 인셋 박스 줄의 첫 라벨의
        # 길이가 서로 달라 그 뒤 입력칸 시작 위치가 어긋났음 - 더 긴 라벨
        # 기준으로 폭을 통일한다.
        # [수정 - 사용자 지적] "'중심'의 의미가 불분명함 - 좀 더 정확히" -
        # 이 줄의 "중심"은 확대(zoom)할 대상 지점(메인 plot 데이터 좌표
        # 기준)이고, 아래 줄의 "중심"은 그 결과물인 인셋 박스 자체가 화면
        # 어디에 놓일지(위치)라 서로 다른 개념인데 둘 다 그냥 "중심"이라
        # 헷갈렸음 - 이 줄은 "확대 중심"/"확대 반지름"으로, 아래 줄은
        # "박스 중심"/"박스 반지름"으로 접두어를 서로 다르게 붙여 구분한다.
        _MAG_LABEL_W = 15
        mag_center_row = ttk.Frame(mag_frame)
        mag_center_row.pack(fill="x", padx=5, pady=2)
        ttk.Label(mag_center_row, text="확대 중심 X:", width=_MAG_LABEL_W, anchor="w").pack(side="left")
        ttk.Entry(mag_center_row, textvariable=self.pip_mag_center_x_var, width=8).pack(side="left", padx=(4, 2))
        _mk_mode_combo(mag_center_row, self.pip_mag_center_x_mode_var).pack(side="left", padx=(0, 12))
        # [수정 - 사용자 요청] "확대 중심 X: .... 뒤에 확대 중심 Y1 -> Y1로,
        # 아래 박스 중심과 같은 방식으로" - 아래 "박스 중심" 줄이 두 번째
        # 필드를 "박스 중심 Y:"로 안 쓰고 그냥 "Y:"로 줄인 것과 같은 방식으로
        # 통일(반복되는 "확대 중심" 접두어를 생략).
        ttk.Label(mag_center_row, text="Y1:").pack(side="left")
        ttk.Entry(mag_center_row, textvariable=self.pip_mag_center_y1_var, width=8).pack(side="left", padx=(4, 2))
        _mk_mode_combo(mag_center_row, self.pip_mag_center_y1_mode_var).pack(side="left", padx=(0, 12))
        # [수정 - 사용자 요청] "반지름 box도 정렬" - 아래 줄 "박스 반지름* (%):"
        # 라벨과 텍스트 길이가 달라 입력칸 시작 위치가 어긋났음 - 폭 통일.
        _MAG_RADIUS_LABEL_W = 16
        ttk.Label(mag_center_row, text="확대 반지름 X:", width=_MAG_RADIUS_LABEL_W, anchor="w").pack(side="left")
        ttk.Entry(mag_center_row, textvariable=self.pip_mag_radius_x_var, width=8).pack(side="left", padx=(4, 2))
        _mk_mode_combo(mag_center_row, self.pip_mag_radius_x_mode_var).pack(side="left", padx=(0, 12))
        ttk.Label(mag_center_row, text="배율:").pack(side="left")
        # [수정 - 사용자 요청] "배율 입력 박스 크기를 줄여줘요" - 보통 한두
        # 자리 숫자(예: 4)만 들어가는데 width=6은 과했음 - 3으로 축소.
        ttk.Entry(mag_center_row, textvariable=self.pip_mag_ratio_var, width=3).pack(side="left", padx=(4, 2))
        ttk.Label(mag_center_row, text="배").pack(side="left")

        # [추가 - 사용자 지적] "배율을 활용한 크기를 직관적으로 알기 어렵다" -
        # 반지름/배율을 입력할 때마다 실제로 계산될 인셋 박스 크기(%)를
        # 미리 보여준다(실행 버튼을 눌러보지 않고도 감을 잡을 수 있게).
        # 계산식은 compute_magnifier_pip과 완전히 동일(중복 방지를 위해 그
        # 함수를 그대로 호출) - 다만 X축 범위는 매번 실제로 다시 그려서
        # 구하면 무거우므로, 이미 화면에 있는 xmin_var/xmax_var(Auto면
        # 마지막 실행 때 계산돼 채워진 값, Manual이면 사용자가 직접 넣은 값)
        # 를 그대로 재사용한다 - 아직 한 번도 실행 안 해 비어있으면 "?"로
        # 표시(추정 불가).
        # [추가 - 사용자 요청] "PIP 위치 입력을 비활성화하고 돋보기 큰원
        # 중심/반지름을 입력으로 - 중심(작은원과 큰원)은 서로 매칭되니까" -
        # 위 PIP "위치(%)"/"가로·세로 크기" 필드 대신, 돋보기 전용으로 큰
        # 원(인셋 박스) 자체의 중심(축 프레임 %)과 반지름(%)을 직접 넣을 수
        # 있는 둘째 줄. 비워두면(기본) 중심은 위 중심X/Y1과 자동 일치, 반지름은
        # 배율로 자동 계산 - 값을 넣으면 그 값이 우선한다(compute_magnifier_pip
        # 참고).
        # [수정 - 사용자 질문] "네모일 때는 입력을 어떻게?" - 라벨을 "큰원"
        # (원 전용처럼 보임)에서 "인셋 박스"로 바꿈: 이 반지름은 프레임
        # 모양(원/사각형, 위 "프레임 모양" 드롭다운)과 무관하게 항상 "박스
        # 폭의 절반"을 뜻해서(원이면 그대로 눈에 보이는 반지름, 사각형이면
        # 박스 가로폭의 절반) 두 모양 다 같은 필드 하나로 처리되고 따로
        # 입력칸을 나눌 필요가 없다.
        # [수정 - 사용자 보고 버그, 요청] "x=200은 200%인데 위치가?" - 이
        # 중심 입력이 항상 축 프레임 %(0~100)만 받아서, 중심X/Y1과 같은
        # 감각으로 데이터 좌표값(예: X=200)을 넣으면 200%로 잘못 해석돼
        # 유효범위(0~100)를 훌쩍 넘어 엉뚱한 자리로 튕겨나갔다 - 위 중심X/Y1
        # 과 완전히 같은 방식(좌표값/% 선택, 기본 좌표값)으로 바꾼다.
        mag_box_row = ttk.Frame(mag_frame)
        mag_box_row.pack(fill="x", padx=5, pady=(0, 2))
        # [수정 - 사용자 지적] "'중심'의 의미가 불분명함" - 위 줄("확대
        # 중심")과 짝이 되도록 이 줄은 "박스 중심"/"박스 반지름"으로 통일
        # (인셋 박스 자체가 화면에 놓일 위치/크기라는 뜻).
        ttk.Label(mag_box_row, text="박스 중심 X:", width=_MAG_LABEL_W, anchor="w").pack(side="left")
        # [수정 - 사용자 요청] "인셋박스 중심과 위 중심 입력의 box크기와
        # 정렬" - 입력칸 폭도 위 확대 중심 줄(width=8)과 통일(예전엔 6).
        ttk.Entry(mag_box_row, textvariable=self.pip_mag_box_center_x_var, width=8).pack(side="left", padx=(4, 2))
        _mk_mode_combo(mag_box_row, self.pip_mag_box_center_x_mode_var).pack(side="left", padx=(0, 12))
        # [수정 - 사용자 지적] "박스쪽도 Y1이 맞지 않는지?" - 이 값도(위
        # "확대 중심 Y1"과 마찬가지로) Y1 축 기준 위치라 그냥 "Y:"보다
        # "Y1:"이 더 정확함.
        ttk.Label(mag_box_row, text="Y1:").pack(side="left")
        ttk.Entry(mag_box_row, textvariable=self.pip_mag_box_center_y_var, width=8).pack(side="left", padx=(4, 2))
        _mk_mode_combo(mag_box_row, self.pip_mag_box_center_y_mode_var).pack(side="left", padx=(0, 12))
        # [수정 - 사용자 지적] "라벨에 다 넣지 말고 반지름*(%) 처럼 짧게
        # 쓰고 *로 아래에 설명" - 가운데점(·)이 뭘 구분하는지 불확실하고
        # 라벨 자체도 길어 옆 입력칸과 함께 잘리기 쉬웠음 - 라벨은 "박스
        # 반지름* (%):"로 짧게 줄이고, "보통 20~40 권장"/"100=축 전체를
        # 채움" 같은 자세한 뜻은 아래 각주(* ...) 한 줄로 옮긴다.
        ttk.Label(mag_box_row, text="박스 반지름* (%):", width=_MAG_RADIUS_LABEL_W, anchor="w").pack(side="left")
        ttk.Entry(mag_box_row, textvariable=self.pip_mag_box_radius_var, width=8).pack(side="left", padx=(4, 2))
        # [수정 - 사용자 지적] "PIP Radius(Rx,Ry)%처럼 반지름끼리 비교해
        # 100%가 꽉참이어야 헷갈리지 않는다" - 예전엔 이 반지름(%)이 "축
        # 프레임 폭 대비"라 지름(그 2배)이 곧 박스 크기가 되는 관례였고,
        # 그래서 반지름 50%가 이미 "축 전체를 채우는" 상한이었음(적당한
        # 값이 아니라 최댓값이라 헷갈렸던 원인) - PIP Radius(Rx,Ry)%를
        # "100=꽉참"으로 통일한 것과 똑같은 기준으로 여기도 맞춘다(더 이상
        # 2배 안 함 - compute_magnifier_pip 참고). 실측 기준(반지름 15→지름
        # 30%가 적당한 크기였음)을 새 기준(2배)으로 환산해 "보통 20~40"으로
        # 힌트도 같이 바로잡는다.
        # [수정 - 사용자 지적] "'(비우면 중심...)'이 너무 길어서 잘림 - 아래
        # 줄에 *로 표기함이 좋을 듯" - 위에서 라벨 밖으로 뺀 반지름 설명과
        # "비우면 자동" 설명을 한 각주 줄로 합쳐 별도 줄에 둔다(잘림 방지 +
        # "*"가 위 "반지름*"을 가리키는 각주임을 명확히 함).
        mag_box_note_row = ttk.Frame(mag_frame)
        mag_box_note_row.pack(fill="x", padx=5, pady=(0, 2))
        ttk.Label(
            mag_box_note_row,
            text="* 박스 반지름(%): 보통 20~40 권장, 100=축 전체를 채움. 비우면(박스 중심도 마찬가지) 위 확대 중심X/Y1·배율에서 자동 계산됨",
            foreground="#3a3a3a", font=("Malgun Gothic", 8, "italic")
        ).pack(side="left")

        mag_preview_var = tk.StringVar(value="")
        mag_preview_row = ttk.Frame(mag_frame)
        mag_preview_row.pack(fill="x", padx=5, pady=(0, 5))
        # [수정 - 사용자 질문] "이 줄의 역할이 뭔지 불확실함(버튼도 아니고)" -
        # 이 줄은 입력 위젯이 아니라, 위에서 지금까지 입력한 중심/반지름/배율
        # (또는 인셋 박스 직접 지정값)으로 Plot을 실제로 실행하면 인셋이 얼마
        # 크기(축 프레임 대비 %)로 나올지, 실행 전에 미리 계산해서 보여주는
        # "읽기 전용 미리보기"임 - [수정 - 사용자 지적] "(자동 계산, 참고용)"
        # 보다 "(자체계산)"이 더 확실한 표현이라는 지적을 반영해 교체.
        ttk.Label(mag_preview_row, text="→ 예상 인셋 크기 (자체계산 값, 참고용):",
                  foreground="#3a3a3a", font=("Malgun Gothic", 9, "italic")).pack(side="left")
        ttk.Label(mag_preview_row, textvariable=mag_preview_var, foreground="#0056b3").pack(side="left", padx=(4, 0))

        def _update_mag_preview(*_a):
            if not self.pip_mag_on_var.get():
                mag_preview_var.set("")
                return
            try:
                _xlo = float(self.xmin_var.get())
                _xhi = float(self.xmax_var.get())
                if not (_xhi > _xlo):
                    raise ValueError
            except (TypeError, ValueError):
                mag_preview_var.set("? (먼저 한 번 실행해서 X축 범위를 확정해 주세요)")
                return
            _gen = GnuplotGenerator(self.plot_dir)
            _mag_cfg = self._collect_magnifier_dict()
            _box_r_raw = (_mag_cfg.get("box_radius") or "").strip()
            if _box_r_raw:
                try:
                    # [수정 - 사용자 지적] "기준이 같아야 헷갈리지 않는다" -
                    # PIP Radius(Rx,Ry)%(100=꽉참)와 동일하게 통일 - 반지름
                    # %가 그대로 지름(=박스 가로 크기) %가 됨(더 이상 2배
                    # 안 함, gnu_generator.compute_magnifier_pip과 동일).
                    _size_w = min(max(float(_box_r_raw) / 100.0, 0.05), 1.0)
                except (TypeError, ValueError):
                    mag_preview_var.set("? (인셋 박스 반지름 값을 확인해 주세요)")
                    return
                _size_h = min(max(_size_w * (5.95 / 4.17), 0.05), 1.0)
                # [수정 - 사용자 보고 버그 예방, 기준 변경에 맞춤] 반지름이
                # 100%를 넘으면(=지름이 축 프레임 전체를 넘음) 박스가 축
                # 프레임을 꽉 채워 중심X/Y가 사실상 무시된 것처럼 보이므로
                # 미리보기에서부터 경고한다.
                _clip_note = "" if float(_box_r_raw) <= 100.0 else " ⚠ 반지름 100%를 넘으면 박스가 축 프레임 전체를 채워 중심 지정이 무시됩니다"
                mag_preview_var.set(f"가로 {_size_w * 100:.1f}% / 세로 {_size_h * 100:.1f}%  (인셋 박스 반지름 직접 입력값 기준){_clip_note}")
                return
            _r = _gen._resolve_magnifier_value(_mag_cfg.get("radius_x"), _mag_cfg.get("radius_x_mode", "data"), _xlo, _xhi, is_length=True)
            try:
                _mag = float(_mag_cfg.get("magnification") or 1.0)
            except (TypeError, ValueError):
                _mag = 1.0
            _mag = max(_mag, 0.1)
            if _r is None or _r <= 0:
                mag_preview_var.set("? (반지름을 먼저 입력해 주세요)")
                return
            _size_w = min(max((2.0 * _r) / max(_xhi - _xlo, 1e-9) * _mag, 0.05), 1.0)
            _size_h = min(max(_size_w * (5.95 / 4.17), 0.05), 1.0)
            mag_preview_var.set(f"가로 {_size_w * 100:.1f}% / 세로 {_size_h * 100:.1f}%  (X축 전체 {_xhi - _xlo:.4g} 중 {2 * _r:.4g} 구간 기준)")

        for _v in (self.pip_mag_on_var, self.pip_mag_radius_x_var, self.pip_mag_radius_x_mode_var,
                   self.pip_mag_ratio_var, self.pip_mag_box_radius_var):
            _v.trace_add("write", _update_mag_preview)
        _update_mag_preview()

        def _toggle_mag_entries(*_a):
            _on = self.pip_mag_on_var.get()
            _zstate = "disabled" if _on else "normal"
            for _w in (xz_row, yz_row):
                for _c in _w.winfo_children():
                    if isinstance(_c, ttk.Entry):
                        _c.config(state=_zstate)
            # [추가 - 사용자 지적] "PIP W/H 단위가 %,in,cm인데 돋보기랑
            # 헷갈릴 듯" - 돋보기가 켜지면 compute_magnifier_pip이 가로/세로
            # 크기와 단위(%로 고정)를 배율로부터 자동 계산해 덮어쓰므로, 위
            # 확대구간 입력(xz_row/yz_row)과 마찬가지로 "가로/세로 크기(W/H)"
            # 입력칸과 단위 선택도 동시에 비활성화해 "이건 돋보기가 대신
            # 계산한다"는 걸 화면에서 바로 알 수 있게 한다.
            for _c in size_row.winfo_children():
                if isinstance(_c, (ttk.Entry, ttk.Combobox)):
                    _c.config(state=_zstate if isinstance(_c, ttk.Entry) else ("disabled" if _on else "readonly"))
            # [추가 - 사용자 요청] "PIP 위치 입력을 비활성화하고" - 돋보기가
            # 켜지면 박스 위치(pos_x/pos_y)는 항상 compute_magnifier_pip이
            # 중심X/Y1(또는 아래 "큰원 중심" 직접 입력)에서 계산해 강제로
            # 덮어쓰므로, 기존 "위치(%)" 입력칸은 더 이상 읽히지 않는다는
            # 걸 명확히 보여주기 위해 같이 비활성화한다.
            for _c in pos_row.winfo_children():
                if isinstance(_c, ttk.Entry):
                    _c.config(state=_zstate)
        self.pip_mag_on_var.trace_add("write", _toggle_mag_entries)
        _toggle_mag_entries()

        # --- 표시 옵션 ---
        opt_frame = ttk.LabelFrame(body, text="표시 옵션")
        opt_frame.pack(fill="x", padx=10, pady=5)
        # [수정 - 요청] "Plot Title과 Axis Title check box 분리" - 기존엔
        # Plot Title(plotdef.title)만 켜고 끌 수 있었고 X/Y1/Y2 축 제목은
        # 항상 강제로 안 보였음(_render_pip_inset 참고) - 별도 체크박스로 분리.
        # [수정 - 요청] "입력 box는 그냥 두고, 대신 팝업의 체크박스를 키워요" -
        # 기본 15px 대신 Var list의 Y1/Y2 체크박스와 같은 19px로.
        # [수정 - 사용자 요청] "손대는 김에 Plot Title 표시, Axis Title 표시,
        # Legend 표시 등은 한줄에" -> "너무 줄이 많음" -> "마커표시도 같은
        # 줄로" -> "간단히 표시는 다음 줄로 이동" - Plot Title/Axis Title/
        # Legend/Marker 표시는 한 줄에, "간단히 표시"만 따로 다음 줄에 둔다.
        title_opt_row = ttk.Frame(opt_frame)
        title_opt_row.pack(fill="x")
        # [추가 - 사용자 요청] "Plot Title/Axis Title/Legend/Grid/Marker 표시도
        # original 보고 기본 체크/비활성화" - Plot Title/Axis Title은 PIP
        # 전용 텍스트를 직접 입력할 수도 있어 비활성화(회색)는 부적절하고,
        # original에 내용이 있으면 기본값만 체크. Legend/Marker/Grid는
        # original에 없으면 비활성화(Grid는 회색 대신 기본 체크만 - Title과
        # 같은 취급, 사용자 지적 반영)까지 한다. 어느 항목이든 사용자가 한
        # 번이라도 직접 건드리거나 Template이 명시한 값이 있으면 그 뒤로는
        # 자동 동기화하지 않는다.
        # [수정 - 사용자 지적] "original plot은 main plot이 아닐 수도 있음" -
        # PIP 소스가 "현재 plot"뿐 아니라 "cached"(이미 그려진 plot)/
        # "pltfile"(.plt 파일)일 수도 있어, 그 실제 원본의 title/axis title/
        # legend/grid/marker 유무를 소스별로 알아내는 _resolve_pip_original_
        # flags()를 통해 판단한다(판단 불가 항목은 None - 그 항목은 자동
        # 동기화/비활성화를 건너뛰고 마지막 값·항상 활성 상태를 유지).
        _orig_flags = self._resolve_pip_original_flags()
        if _orig_flags["title"] is not None and not self._pip_title_user_set:
            self.pip_title_on_var.set(_orig_flags["title"])
        if _orig_flags["axis_title"] is not None and not self._pip_axis_title_user_set:
            self.pip_axis_title_on_var.set(_orig_flags["axis_title"])
        self._mk_check(
            title_opt_row, "Plot Title 표시", self.pip_title_on_var, size=19, anchor="w", side="left", padx=5, pady=2,
            command=lambda: setattr(self, "_pip_title_user_set", True)
        )
        self._mk_check(
            title_opt_row, "Axis Title 표시", self.pip_axis_title_on_var, size=19, anchor="w", side="left", padx=5, pady=2,
            command=lambda: setattr(self, "_pip_axis_title_user_set", True)
        )
        # [추가 - 사용자 요청] "Legend box도 original에 없으면 회색으로" -
        # original이 Legend On이 아니면 보여줄 legend 내용이 없으므로
        # Marker와 같은 방식으로 비활성화한다.
        if _orig_flags["legend"] is not None and not self._pip_legend_user_set:
            self.pip_legend_on_var.set(_orig_flags["legend"])
        pip_legend_chk = self._mk_check(
            title_opt_row, "Legend 표시", self.pip_legend_on_var, size=19, anchor="w", side="left", padx=5, pady=2,
            command=lambda: setattr(self, "_pip_legend_user_set", True)
        )
        pip_legend_chk.configure(state=("normal" if (_orig_flags["legend"] is None or _orig_flags["legend"]) else "disabled"))
        # [수정 - 사용자 지적] "Marker 표시 체크박스 설명이 애매함" - "원본에
        # marker 있는 curve만"이 무엇을 뜻하는지 불명확했음 - "인셋에도
        # 표시"로 동작을 명시한다. [추가 - 사용자 지적] "원본에 marker가
        # 없으면 체크박스를 회색으로(즉 사용 못하게)" - 켜도 효과가 없는
        # 상황을 라벨 설명 대신 비활성화(disabled)로 직접 보여주는 게 더
        # 명확함 - 회색이면 조건 설명 자체가 불필요해지므로 괄호 설명은 뺀다.
        pip_marker_chk = self._mk_check(title_opt_row, "Marker 인셋에도 표시", self.pip_marker_on_var, size=19, anchor="w", side="left", padx=5, pady=2)
        pip_marker_chk.configure(state=("normal" if (_orig_flags["marker"] is None or _orig_flags["marker"]) else "disabled"))
        # [추가 - 사용자 요청] "PIP 인셋 grid도 on/off 옵션" - 메인 화면의
        # Major/Minor Grid 설정과 무관하게 인셋만 따로 켜고 끌 수 있게 함.
        # [수정 - 사용자 지적] "무조건 check 되어 있으면 곤란 - original을
        # 보고 프로그램이 자동으로 on/off를 표기해야(Title과 같은 방식 -
        # 비활성화는 하지 않고 기본값만)" - 사용자가 이 체크박스를 이번
        # 세션에서 아직 직접 건드리지 않았고 Template도 명시적으로 값을
        # 지정한 적 없으면(_pip_grid_user_set=False), 팝업을 열 때마다
        # original의 grid 유무를 그대로 반영해서 보여준다 - 한 번이라도
        # 직접 클릭하거나 Template이 값을 지정하면 그 뒤로는 사용자가 고른
        # 값을 그대로 유지(자동 동기화 중단).
        if _orig_flags["grid"] is not None and not self._pip_grid_user_set:
            self.pip_grid_on_var.set(_orig_flags["grid"])
        pip_grid_chk = self._mk_check(
            title_opt_row, "Grid 표시", self.pip_grid_on_var, size=19, anchor="w", side="left", padx=5, pady=2,
            command=lambda: setattr(self, "_pip_grid_user_set", True)
        )

        def _sync_pip_grid_state(*_a):
            pip_grid_chk.configure(state=("disabled" if self.pip_minimal_var.get() else "normal"))
        _grid_minimal_trace_id = self.pip_minimal_var.trace_add("write", _sync_pip_grid_state)
        _sync_pip_grid_state()

        # [추가 - 요청] "원 안에 아무것도 없이 curve만 넣는 경우도 옵션으로" -
        # 켜면 title/axis frame(테두리)/격자/tic 숫자를 전부 무시하고 배경+
        # curve만 보이게 한다(원으로 확대할 때는 축 좌표 등이 오히려 방해가
        # 될 수 있다는 요청 - _build_pip_folded_overlay가 이 값을 읽어
        # 테두리/격자/tic 생성을 건너뜀). 위 요청대로 다음 줄에 별도로 둠.
        # [수정 - 사용자 지적] "라벨이 Legend/Title도 같이 꺼지는 걸 설명 안
        # 함" - 실제로는 위 "Legend 표시"/"Plot Title 표시" 등을 따로 켜둬도
        # 이 옵션이 켜지면 다 무시되고 Curve만 남음(gnu_generator.py의
        # "if not minimal:" 분기에 title/axis title/legend가 모두 같이
        # 묶여 있음) - 라벨에 이 점을 명시해 오해를 없앤다.
        minimal_opt_row = ttk.Frame(opt_frame)
        minimal_opt_row.pack(fill="x")
        self._mk_check(
            minimal_opt_row,
            "간단히 표시 (Curve만 - 테두리/tic/Title/Legend 등 나머지는 위 설정과 무관하게 모두 생략)",
            self.pip_minimal_var, size=19, anchor="w", side="left", padx=5, pady=2
        )

        # [추가 - 요청] "PIP 표시옵션에서 Plot Title/X/Y1/Y2 title을 default를
        # 제시하고 수정 가능하게 - 불러오는 in-plot의 원본 파일에 title 등이
        # 없을 경우나 수정할 경우를 생각해서" - 지금까지 in-plot의 Plot/axis
        # title은 항상 메인 plot 자신의 title_var/xlabel_var/ylabel_var/
        # y2label_var를 그대로 썼는데(_render_pip_inset), PIP 데이터 소스가
        # "다른(이미 그려진) plot"이나 ".plt 파일"이면 그 원본은 title이
        # 아예 없거나 메인과 다른 title을 쓸 수 있어 항상 메인 것만 강제로
        # 보여주는 게 부적절할 수 있음 - 인셋 전용으로 독립 지정 가능한
        # 텍스트 필드를 추가한다. 아직 한 번도 손대지 않아 비어있으면(신규
        # PIP거나 구버전 Template) 팝업을 열 때마다 편의상 메인의 현재 값을
        # 기본으로 미리 채워 보여준다 - 그대로 두면 지금까지와 동일하게
        # 메인과 같은 title이 나오고, 필요하면 자유롭게 고쳐서 인셋만 다른
        # (또는 빈) title을 쓸 수 있다. 한 번이라도 값이 들어간 뒤에는(빈
        # 문자열로 일부러 지운 경우 포함) 그 값을 그대로 유지하고 더 이상
        # 메인 값으로 덮어쓰지 않는다.
        # [수정 - 사용자 요청] "default를 main-plot(또는 읽어온 plot)의 축
        # title을 넣어줘요" - source가 "저장된 plot"/".plt 파일"이면 그
        # 원본 자신의 title을 기본값으로 삼는다(_pip_default_titles 참고).
        _def_title, _def_xlabel, _def_ylabel, _def_y2label = self._pip_default_titles()
        if not self.pip_title_text_var.get().strip():
            self.pip_title_text_var.set(_def_title)
        if not self.pip_xlabel_text_var.get().strip():
            self.pip_xlabel_text_var.set(_def_xlabel)
        if not self.pip_ylabel_text_var.get().strip():
            self.pip_ylabel_text_var.set(_def_ylabel)
        if not self.pip_y2label_text_var.get().strip():
            self.pip_y2label_text_var.set(_def_y2label)

        # [수정 - 사용자 요청] "Plot Title box와 Y1 title box, X title box와
        # Y2 title box를 정렬" - "Plot Title:"(11자)와 "Y1 Title:"(9자),
        # "X Title:"(8자)와 "Y2 Title:"(9자)의 길이가 서로 달라 입력칸 시작
        # 위치가 어긋났음 - 첫 라벨/셋째 라벨 각각 폭을 통일.
        _TITLE_LABEL_W1 = 11
        _TITLE_LABEL_W2 = 9
        title_txt_row1 = ttk.Frame(opt_frame)
        title_txt_row1.pack(fill="x", padx=5, pady=(4, 2))
        ttk.Label(title_txt_row1, text="Plot Title:", width=_TITLE_LABEL_W1, anchor="w").pack(side="left")
        ttk.Entry(title_txt_row1, textvariable=self.pip_title_text_var, width=16).pack(side="left", padx=(4, 12))
        ttk.Label(title_txt_row1, text="X Title:", width=_TITLE_LABEL_W2, anchor="w").pack(side="left")
        ttk.Entry(title_txt_row1, textvariable=self.pip_xlabel_text_var, width=12).pack(side="left", padx=(4, 0))
        title_txt_row2 = ttk.Frame(opt_frame)
        title_txt_row2.pack(fill="x", padx=5, pady=(0, 2))
        ttk.Label(title_txt_row2, text="Y1 Title:", width=_TITLE_LABEL_W1, anchor="w").pack(side="left")
        ttk.Entry(title_txt_row2, textvariable=self.pip_ylabel_text_var, width=16).pack(side="left", padx=(4, 12))
        ttk.Label(title_txt_row2, text="Y2 Title:", width=_TITLE_LABEL_W2, anchor="w").pack(side="left")
        ttk.Entry(title_txt_row2, textvariable=self.pip_y2label_text_var, width=12).pack(side="left", padx=(4, 0))
        ttk.Label(
            opt_frame,
            text="(기본은 메인 plot의 title과 동일 - 원본 파일에 title이 없거나 다르게 쓰려면 직접 수정)",
            foreground="#3a3a3a", font=("Malgun Gothic", 9, "italic")
        ).pack(fill="x", padx=5, pady=(0, 4))

        # [수정 - 요청] "반투명에서 문제 있으면 슬라이더 대신 투명/불투명
        # 라디오버튼만 쓰는 게 낫지 않은지?" - 반투명(1~99%)은 화면
        # 오버레이에서 gnuplot을 한 번 더 돌려 배경을 만들어야 하는 유일한
        # 경우라, 이 둘(0%/100%)로만 제한하면 그 재실행 자체를
        # skip_beneath_if_opaque로 생략할 수 있어(_apply_pip_clip 참고)
        # dat가 큰 경우 특히 체감 속도가 빨라진다. self.pip_opacity_var는
        # 그대로 0/100 정수를 담는 IntVar로 유지해서, 이 값을 읽는 나머지
        # 코드(저장/불러오기, gnu_generator 등)는 손댈 필요 없음.
        opac_row = ttk.Frame(opt_frame)
        opac_row.pack(fill="x", padx=5, pady=2)
        ttk.Label(opac_row, text="배경:").pack(side="left")
        ttk.Radiobutton(opac_row, text="불투명 (기본)", variable=self.pip_opacity_var, value=100).pack(side="left", padx=(6, 12))
        ttk.Radiobutton(opac_row, text="투명", variable=self.pip_opacity_var, value=0).pack(side="left")

        def _on_opacity_change(*_):
            pass
        _opac_trace_id = self.pip_opacity_var.trace_add("write", _on_opacity_change)
        _on_opacity_change()

        # [수정 - 사용자 보고 버그] "PIP 옵션(데이터 소스)을 바꿔도 Plot/X/Y1/
        # Y2 Title 입력칸이 안 바뀌고 맨 처음 고른 소스의 값 그대로 남음 -
        # 심지어 '현재 plot'으로 되돌려도 그대로임" - 위 title 기본값 채우기
        # (_pip_default_titles)는 이 팝업을 "여는 시점"에 한 번만 실행되고,
        # 그마저도 "비어있을 때만" 채워서, 이미 한 번 채워진 뒤에는 팝업을
        # 닫지 않고 소스(라디오버튼/이미 그려진 plot 콤보/plt 파일)만 바꾸면
        # 전혀 갱신이 안 됐음 - source/cached_name/pltfile_path 중 하나라도
        # 바뀔 때마다 title을 그 새 소스 기준으로 다시(무조건) 채운다.
        # [수정 - 사용자 보고 버그, 근본 원인] "PIP를 원/사각형 어느 쪽으로
        # 그려도 창에 안 나타남(좌표는 나타남 - 그림이 하나뿐이라는 뜻)" -
        # Y1/Y2 확대 구간(pip_ymin_var 등)도 같은 문제를 갖고 있었음: 한 번
        # 다른 소스(.plt 파일/이미 그려진 plot)에서 자동으로 채워지면
        # (_pip_autofill_range) 그 뒤 소스를 바꿔도 "이미 값이 있으니"
        # 그대로 안 지워졌음 - 예를 들어 .plt 파일 소스에서 Y2가 -252~128로
        # 자동 채워진 뒤 소스를 "현재 plot"(실제 Y2 범위가 0~30대)으로
        # 바꾸면, 그 낡은(-252~128) 범위가 그대로 남아있어 원/타원 클리핑이
        # 그 범위를 기준으로 계산되면서 실제 곡선이 전부 그 범위 밖으로
        # 밀려나 인셋 안이 사실상 텅 비어 보였던 것(그림이 없으니 클리핑
        # 경계도 못 그려 완전히 안 보임) - source가 바뀔 때마다 Y1/Y2
        # min/max를 일단 비운 뒤 새 소스 기준으로 다시 자동 채움.
        def _pip_source_changed(*_args):
            _t, _xl, _yl, _y2l = self._pip_default_titles()
            self.pip_title_text_var.set(_t)
            self.pip_xlabel_text_var.set(_xl)
            self.pip_ylabel_text_var.set(_yl)
            self.pip_y2label_text_var.set(_y2l)
            _tmp_pip = {
                "source": self.pip_source_var.get(),
                "cached_name": self.pip_cached_name_var.get(),
                "pltfile_path": self.pip_pltfile_path_var.get(),
                "xmin": "", "xmax": "", "ymin": "", "ymax": "", "y2min": "", "y2max": "",
            }
            self._pip_autofill_range(_tmp_pip)
            self.pip_xmin_var.set(_tmp_pip.get("xmin") or "")
            self.pip_xmax_var.set(_tmp_pip.get("xmax") or "")
            self.pip_ymin_var.set(_tmp_pip.get("ymin") or "")
            self.pip_ymax_var.set(_tmp_pip.get("ymax") or "")
            self.pip_y2min_var.set(_tmp_pip.get("y2min") or "")
            self.pip_y2max_var.set(_tmp_pip.get("y2max") or "")

        _src_trace_id = self.pip_source_var.trace_add("write", _pip_source_changed)
        _cached_trace_id = self.pip_cached_name_var.trace_add("write", _pip_source_changed)
        _pltfile_trace_id = self.pip_pltfile_path_var.trace_add("write", _pip_source_changed)

        # [수정 - 버그] "PIP 팝업을 열었다 닫았다 반복하면 trace 콜백이 계속
        # 쌓임" - 위 trace_add들은 dlg가 닫혀도 tk 변수 쪽에 그대로 남아있어서,
        # 팝업을 닫은 뒤 이 tk 변수가 다시 바뀌면(Template Load, 팝업 재실행
        # 등) 이미 파괴된 위젯(clip_rx_entry/opac_value_lbl)을 건드리려다
        # TclError가 나고, 팝업을 열 때마다 죽은 콜백이 계속 누적됨(실측으로
        # 재현·확인) - 팝업이 닫힐 때 이 세션의 trace만 제거한다.
        def _cleanup_pip_dialog_traces(event):
            if event.widget is not dlg:
                return
            for _var, _tid in (
                (self.pip_clip_shape_var, _clip_trace_id),
                (self.pip_opacity_var, _opac_trace_id),
                (self.pip_source_var, _src_trace_id),
                (self.pip_cached_name_var, _cached_trace_id),
                (self.pip_pltfile_path_var, _pltfile_trace_id),
                (self.pip_minimal_var, _grid_minimal_trace_id),
            ):
                try:
                    _var.trace_remove("write", _tid)
                except tk.TclError:
                    pass
        dlg.bind("<Destroy>", _cleanup_pip_dialog_traces, add="+")

        font_row = ttk.Frame(opt_frame)
        font_row.pack(fill="x", padx=5, pady=(2, 5))
        ttk.Label(font_row, text="폰트 축소 배율:").pack(side="left")
        font_scale_entry = ttk.Entry(font_row, textvariable=self.pip_font_scale_var, width=6)
        font_scale_entry.pack(side="left", padx=(4, 0))
        # [추가 - 요청] "기본값이 이미 찍혀있는데 사용자가 직접 입력한
        # 건지 기본값이 그냥 채워진 건지 구분이 안 됨 - 입력 안 하면
        # 회색으로, 입력하면 진하게" - 아직 기본값 그대로면 회색으로
        # 표시해 "이건 그냥 기본값입니다"를 알려주고, 실제로 타이핑하는
        # 순간(첫 키 입력) 검정으로 바꿔서 "이제부터는 직접 정한 값"임을
        # 표시한다. 단, Template/Batch Set에서 이미 기본값이 아닌 값을
        # 불러온 경우는 처음부터 검정(그 값 자체가 의미 있는 사용자
        # 값이므로).
        # [수정 - 사용자 보고 버그, 재조정] "PIP in-plot legend font/box가
        # 상대적으로 너무 큼"이라는 보고로 한때 기본값을 0.35로 낮췄었으나,
        # 그 뒤 legend 전용 축소 메커니즘(compact 배율, text_corr 보정,
        # marker 동기화 등)이 따로 추가된 상태에서 다시 확인해보니 이번엔
        # "title/tic font가 너무 작아짐(2배 정도 키워야)"는 반대 방향
        # 보고를 받음 - title/tic까지 함께 줄이는 이 공용 배율은 0.6으로
        # 되돌리고, legend만 더 작게 하고 싶으면 legend 전용 메커니즘 쪽을
        # 조정하는 방향으로 정리.
        if self.pip_font_scale_var.get().strip() == "0.6":
            font_scale_entry.configure(foreground="grey")

        def _font_scale_first_edit(event=None):
            font_scale_entry.configure(foreground="black")
            font_scale_entry.unbind("<KeyPress>")

        font_scale_entry.bind("<KeyPress>", _font_scale_first_edit)

    def _pip_autofill_range(self, pip):
        """[추가 - 요청] "당연히 .plt 파일 자체에서 Y 범위도 같이 읽어와서
        자동으로 채우기 해야지요" - PIP 소스가 "저장된 plot"/".plt 파일"
        이면 원/타원 클리핑에 Y1(Y2 곡선이 있으면 Y2도) "구체적인 숫자"
        범위가 필요한데(_ellipse_native_ok), 지금까지는 사용자가 PIP
        팝업에 Y1/Y2 min/max를 직접 입력해야만 했음 - 사용자가 이미 채운
        값이 있으면 그대로 두고(우선), 비어있을 때만 원본에서 자동으로
        채운다("user 입력 없으면 전체 구간에서 읽어와야지" - 그 원본이
        원래 그렸던 전체 Y 범위 그대로).
        - ".plt 파일": 그 파일 자신의 main plot이 쓴 set yrange/y2range를
          그대로 읽어옴(_parse_plt_ranges - auto/수동 여부와 무관하게 항상
          그 파일에 구체적 숫자로 이미 박혀 있음).
        - "저장된 plot": 그 plotdef가 Y를 수동으로 지정해뒀으면(yauto=False)
          그 값을 그대로 씀. auto(yauto=True)면 그 객체 자체엔 확정된 숫자가
          없지만("실제 렌더링 시점에야 데이터에서 계산되는 값") - "일단
          dummy 숫자를 넣고 나중에 대체"할 필요 없이, 그 plotdef가 이미
          들고 있는 실제 curve/dat 참조를 그대로 써서 지금 이 자리에서
          바로 진짜 값을 계산한다(_nice_axis_range - CathPlot이 화면에
          실제로 auto Y범위를 표시할 때 쓰는 것과 완전히 같은 계산, 결과도
          그때와 동일함 - "임시 추정치"가 아니라 "그 데이터의 실제 nice
          범위").
        pip dict를 그 자리에서 수정한다(GUI 경로 _resolve_pip_config와
        Batch 경로 _resolve_pip_dict_for_batch가 공통으로 재사용)."""
        source = pip.get("source")
        xmin = xmax = ymin = ymax = y2min = y2max = None
        if source == "cached":
            cached_plotdef = self.active_plots_cache.get(pip.get("cached_name", ""))
            if cached_plotdef is not None:
                # [추가 - 사용자 재보고] "PIP에 있던 *.plt에 X-range도 있는데
                # 기본값으로 안 읽어 오네?" - Y1/Y2와 완전히 같은 방식으로
                # "저장된 plot" 소스도 X 범위를 같이 채운다(수동 지정이면
                # 그 값, auto면 실제 데이터로 지금 계산).
                if not getattr(cached_plotdef, "xauto", True) and cached_plotdef.xmin and cached_plotdef.xmax:
                    xmin, xmax = cached_plotdef.xmin, cached_plotdef.xmax
                if not getattr(cached_plotdef, "yauto", True) and cached_plotdef.ymin and cached_plotdef.ymax:
                    ymin, ymax = cached_plotdef.ymin, cached_plotdef.ymax
                if not getattr(cached_plotdef, "y2auto", True) and cached_plotdef.y2min and cached_plotdef.y2max:
                    y2min, y2max = cached_plotdef.y2min, cached_plotdef.y2max
                # [추가 - 요청] "auto로 뒀던 경우는... dummy 숫자를 가정하고
                # 나서 알게 되면 대체하는 방안은?" - dummy가 아니라 그
                # plotdef의 실제 curve 데이터로 지금 바로 진짜 값을 계산해서
                # 채운다(수동 지정이 없을 때만 - 위에서 이미 못 채웠으면).
                _uses_y2_cached = any(getattr(c, "axis", "y1") == "y2" for c in cached_plotdef.curves)
                if xmin is None or xmax is None:
                    try:
                        _nicex = GnuplotGenerator(plot_dir=self.plot_dir)._nice_axis_range(
                            cached_plotdef, "x", is_log=getattr(cached_plotdef, "xlog", False))
                        if _nicex:
                            xmin, xmax = f"{_nicex[0]:g}", f"{_nicex[1]:g}"
                    except Exception:
                        pass
                if ymin is None or ymax is None:
                    try:
                        _nice = GnuplotGenerator(plot_dir=self.plot_dir)._nice_axis_range(
                            cached_plotdef, "y1", is_log=getattr(cached_plotdef, "y1log", False))
                        if _nice:
                            ymin, ymax = f"{_nice[0]:g}", f"{_nice[1]:g}"
                    except Exception:
                        pass
                if _uses_y2_cached and (y2min is None or y2max is None):
                    try:
                        _nice2 = GnuplotGenerator(plot_dir=self.plot_dir)._nice_axis_range(
                            cached_plotdef, "y2", is_log=getattr(cached_plotdef, "y2log", False))
                        if _nice2:
                            y2min, y2max = f"{_nice2[0]:g}", f"{_nice2[1]:g}"
                    except Exception:
                        pass
        elif source == "pltfile":
            path = pip.get("pltfile_path", "")
            if path and os.path.exists(path):
                xmin, xmax, ymin, ymax, y2min, y2max = self._parse_plt_ranges(path)
        if xmin is not None and xmax is not None and not (
                str(pip.get("xmin", "")).strip() and str(pip.get("xmax", "")).strip()):
            pip["xmin"], pip["xmax"] = xmin, xmax
        if ymin is not None and ymax is not None and not (
                str(pip.get("ymin", "")).strip() and str(pip.get("ymax", "")).strip()):
            pip["ymin"], pip["ymax"] = ymin, ymax
        if y2min is not None and y2max is not None and not (
                str(pip.get("y2min", "")).strip() and str(pip.get("y2max", "")).strip()):
            pip["y2min"], pip["y2max"] = y2min, y2max

    def _collect_magnifier_dict(self):
        """[추가 - 요청] "돋보기" tk 변수들을 pip["magnifier"] sub-dict로
        모은다 - Template 저장용 dict와 _resolve_pip_config 양쪽에서 같이
        재사용(중복 방지)."""
        return {
            "enabled": self.pip_mag_on_var.get(),
            "center_x": self.pip_mag_center_x_var.get(),
            "center_x_mode": self.pip_mag_center_x_mode_var.get(),
            "center_y1": self.pip_mag_center_y1_var.get(),
            "center_y1_mode": self.pip_mag_center_y1_mode_var.get(),
            "radius_x": self.pip_mag_radius_x_var.get(),
            "radius_x_mode": self.pip_mag_radius_x_mode_var.get(),
            "magnification": self.pip_mag_ratio_var.get(),
            "box_center_x": self.pip_mag_box_center_x_var.get(),
            "box_center_x_mode": self.pip_mag_box_center_x_mode_var.get(),
            "box_center_y": self.pip_mag_box_center_y_var.get(),
            "box_center_y_mode": self.pip_mag_box_center_y_mode_var.get(),
            "box_radius": self.pip_mag_box_radius_var.get(),
        }

    def _resolve_pip_config(self):
        """[추가 - 요청] PIP 팝업(open_pip_dialog)에서 고른 tk 변수들을,
        gnu_generator.PlotDefinition.pip이 기대하는 dict로 변환한다. source가
        "cached"/"pltfile"이면 여기서 실제 curves 리스트까지 채워 넣는다
        (execute_plot_pipeline은 화면 tk 변수에 바로 접근할 수 있는 메인
        스레드에서만 호출되므로, Batch Set 경로(_resolve_pip_dict_for_batch -
        Template에 저장된 이름/경로로 다시 찾음)와 로직이 갈라져 있다)."""
        pip = {
            "enabled": self.pip_enabled_var.get(),
            "pos_x": self.pip_pos_x_var.get(),
            "pos_y": self.pip_pos_y_var.get(),
            "size_w": self.pip_size_w_var.get(),
            "size_h": self.pip_size_h_var.get(),
            "size_unit": self.pip_size_unit_var.get(),
            "clip_shape": self.pip_clip_shape_var.get(),
            "clip_rx": self._clip_pct_to_stored(self.pip_clip_rx_var.get()),
            "clip_ry": self._clip_pct_to_stored(self.pip_clip_ry_var.get()),
            "xmin": self.pip_xmin_var.get(),
            "xmax": self.pip_xmax_var.get(),
            "ymin": self.pip_ymin_var.get(),
            "ymax": self.pip_ymax_var.get(),
            "y2min": self.pip_y2min_var.get(),
            "y2max": self.pip_y2max_var.get(),
            "title_on": self.pip_title_on_var.get(),
            "axis_title_on": self.pip_axis_title_on_var.get(),
            "legend_on": self.pip_legend_on_var.get(),
            "minimal": self.pip_minimal_var.get(),
            "grid_on": self.pip_grid_on_var.get(),
            "marker_on": self.pip_marker_on_var.get(),
            "title_text": self.pip_title_text_var.get(),
            "xlabel_text": self.pip_xlabel_text_var.get(),
            "ylabel_text": self.pip_ylabel_text_var.get(),
            "y2label_text": self.pip_y2label_text_var.get(),
            "font_scale": self.pip_font_scale_var.get(),
            "opacity": self.pip_opacity_var.get(),
            "source": self.pip_source_var.get(),
            "cached_name": self.pip_cached_name_var.get(),
            "pltfile_path": self.pip_pltfile_path_var.get(),
            "magnifier": self._collect_magnifier_dict(),
        }
        if not pip["enabled"]:
            return pip
        if pip["source"] == "cached":
            cached_plotdef = self.active_plots_cache.get(pip["cached_name"])
            if cached_plotdef is not None:
                pip["curves"] = cached_plotdef.curves
        elif pip["source"] == "pltfile" and pip["pltfile_path"]:
            curves, warnings = self._parse_plt_curves(pip["pltfile_path"])
            if curves:
                pip["curves"] = curves
            if warnings:
                # [추가 - 사용자 질문/요청] 여기는 메인(대화형) 스레드에서만
                # 호출되므로(execute_plot_pipeline) messagebox를 바로 띄워도
                # 안전함 - "조용히 사라지는 것보다는" 요청대로 즉시 알린다.
                messagebox.showwarning(
                    "PIP 소스 dat 파일 문제",
                    "PIP inset의 일부 곡선을 복구하지 못했습니다:\n\n" + "\n".join(warnings),
                )
        self._pip_autofill_range(pip)
        return pip

    def _normalize_pip_for_animation(self, plotdef):
        """[추가 - 요청] "PIP+Animation" - PIP의 배경 반투명(1~99%)은 gnuplot
        자체 기능이 아니라 PDF를 다 그린 뒤 PyMuPDF/PIL로 후처리해서 만드는데
        (gnu_generator._apply_pip_clip 참고), Animation은 gnuplot이 자기
        혼자(do-for 루프) 프레임을 계속 다시 그리는 구조라 프레임마다 이
        무거운 후처리를 다시 돌릴 방법이 없다(실측: 그러려면 지금처럼
        "gnuplot 하나가 계속 도는" 구조를 버리고 프레임마다 별도 렌더링을
        150번 반복해야 함 - 비현실적).

        [수정 - 발견] "원/타원 클리핑은 항상 사각형으로 강제" - 처음엔 원/
        타원도 항상 후처리가 필요하다고 생각해서 무조건 사각형으로 바꿨는데,
        opacity가 0(완전 투명) 또는 100(완전 불투명)이면 원/타원도 gnuplot
        네이티브(set object ellipse + 데이터 레벨 NaN 마스킹)로 처리 가능함을
        확인함(_render_pip_inset의 _ellipse_native_ok 참고) - 이제 원/타원
        클리핑 자체는 강제로 바꾸지 않는다. 배경 불투명도만 여전히 0/100
        둘 중 하나로 정리한다(그 사이 반투명이면 사용자에게 메시지로 물어봐서
        - 요청: "반투명인 경우, 메시지를 주고" - 완전 불투명/완전 투명 중
        하나로 결정). 이렇게 정리해도 드물게(X/Y 범위가 아직 구체적 숫자로
        확정 안 된 경우) 네이티브 경로를 못 타면, create_animation_script가
        그 시점에 한 번 더 사각형으로 안전하게 대체하고 경고를 남긴다
        (Multi-Plot과 동일한 방어적 폴백 - 여기서는 미리 예측하지 않음).

        pip이 꺼져 있거나 이미 0/100이면 plotdef를 그대로 반환한다(불필요한
        복제/질문 없음). 사용자가 메시지에서 취소를 고르면 None을 반환해
        호출부가 애니메이션 시작 자체를 중단하게 한다."""
        pip = getattr(plotdef, "pip", None)
        if not pip or not pip.get("enabled"):
            return plotdef

        _opacity_raw = str(pip.get("opacity", "")).strip()
        try:
            _opacity = float(_opacity_raw) if _opacity_raw else (100.0 if pip.get("opaque", True) else 0.0)
        except (TypeError, ValueError):
            _opacity = 100.0
        _opacity = max(0.0, min(100.0, _opacity))

        _overrides = {}
        if 0.0 + 1e-6 < _opacity < 100.0 - 1e-6:
            _choice = messagebox.askyesnocancel(
                "PIP + Animation",
                f"PIP 배경이 반투명({_opacity:.0f}%)으로 설정되어 있습니다.\n"
                "Animation은 매 프레임을 gnuplot이 직접 반복해서 그리는 구조라 "
                "반투명(부분 합성)은 지원하지 않습니다(완전 불투명/완전 투명 "
                "둘 중 하나만 저비용으로 가능).\n\n"
                "완전 불투명으로 표시할까요?\n"
                "(예: 완전 불투명 / 아니오: 완전 투명 / 취소: 애니메이션 시작 안 함)"
            )
            if _choice is None:
                return None
            _overrides["opacity"] = 100.0 if _choice else 0.0
        if not _overrides:
            return plotdef
        _new_plotdef = copy.copy(plotdef)
        _new_plotdef.pip = dict(pip, **_overrides)
        return _new_plotdef

    def open_batch_set_dialog(self):
        """여러 개의 '완전한' Template(*.json - dat 파일명+변수 지정까지 포함)을
        모아서, 순서대로 각각 이미지로 저장하는 배치. Batch Queue(하나의 레시피를
        여러 파일에 적용)와 달리, 여기서는 각 Template 자체가 이미 파일까지
        지정된 완전한 plot 하나씩을 의미한다."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Batch Set - 여러 Template을 순서대로 이미지로")
        # [수정 - 버그] "3D Template 선택... 버튼을 누르면 이 Batch Set 창이
        # CathPlot 메인 창 뒤로 숨음" - 이 다이얼로그가 지금까지 transient로
        # 등록돼 있지 않았음(다른 대부분의 다이얼로그는 dialog.transient(self.
        # root)를 호출함). transient가 없으면 안에서 뜨는 파일 선택창이 닫힐 때
        # 창 관리자가 소유 관계를 몰라 root를 이 창 위로 올려버릴 수 있음 -
        # root의 임시 자식으로 등록해 항상 그 위에 유지되게 한다.
        dlg.transient(self.root)
        # [수정 - 요청] 버튼 높이를 1.4배로 키우면서(btn_pady=10) 창에 필요한
        # 최소 높이가 480px보다 커져 listbox가 그만큼 눌리던 것을 보정.
        # [수정 - 사용자 보고 버그] "입력화면에서 글자가 안 잘리게" - 이름
        # 기준/접미사 줄, 공통 Axis Frame 크기 줄+안내 문구 줄이 추가되면서
        # 필요한 최소 높이가 늘어났는데 창 크기는 그대로라 아래쪽(listbox나
        # 안내 문구)이 잘려 보였음 - 폭도 넓혀 한 줄에 든 요소들이 넉넉하게
        # 보이도록, 높이도 늘어난 줄 수만큼 키운다.
        # [수정 - 사용자 요청] "가로크기를 줄여서 접미사 박스가 안 잘릴
        # 정도로" - 실측 winfo_reqwidth()(모든 위젯이 실제로 필요로 하는
        # 최소 폭)가 719px이었음 - 여유를 조금만 둔 730px로 맞춘다(800은
        # 필요 이상으로 넓었음).
        dlg.geometry("730x620")

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
        # [수정 - 사용자 요청] "여러 파일을 한번에 선택되게(ctrl+click,
        # shift+click), Add Template의 입력 선택창처럼" - 기본
        # selectmode("browse")는 한 번에 하나만 선택되는데, "extended"로
        # 바꾸면 탐색기/파일 선택 대화상자와 같은 방식으로 Shift(범위)/
        # Ctrl(개별 추가)로 여러 줄을 한 번에 선택할 수 있다.
        listbox = tk.Listbox(dlg, width=90, height=14, selectmode="extended")
        listbox.pack(fill="both", expand=True, padx=10, pady=5)

        # [추가 - 요청] "Run Batch Set 실행 시 지금 구성한 순서를 저장할지
        # 물어보면 어떨지" - queue_list를 바꾸는 동작(추가/삭제/순서변경/
        # List Load) 이후엔 dirty를 True로 두고, List Save가 실제로
        # 성공하면 False로 되돌린다. Run Batch Set을 누른 시점에 dirty면
        # (=지금 화면 순서가 어떤 파일에도 그대로 저장돼 있지 않으면) 저장
        # 여부를 한 번 물어봄 - 방금 불러온 목록을 그대로 실행할 때처럼
        # 안 바뀐 경우는 매번 묻지 않는다.
        list_dirty = [False]
        # [추가 - 요청] "저장 시 기본 확장자는 txt로 두되, 이미 열어서 쓰던
        # 파일이 있으면(Load/Edit로 연 파일) 그 파일명·확장자를 그대로
        # 이어서 쓰도록" - Load/Edit/Save로 마지막에 손댄 파일 경로를
        # 기억해뒀다가, 다음 List Save 때 그 파일명(및 확장자)을 기본값으로
        # 띄운다. 아직 아무 파일도 안 거쳤으면(None) 기존처럼 빈 파일명 +
        # .txt 기본값을 그대로 씀.
        last_list_path = [None]

        def add_files():
            paths = filedialog.askopenfilenames(
                parent=dlg, initialdir=template_dir,
                filetypes=[("CathPlot Template", "*.json"), ("All files", "*.*")],
                title="Batch Set에 추가할 Template 파일 선택 (여러 개 선택 가능)"
            )
            for p in paths:
                queue_list.append(p)
                listbox.insert("end", os.path.basename(p))
            if paths:
                list_dirty[0] = True

        def remove_selected():
            sel = listbox.curselection()
            if not sel:
                return
            first_idx = sel[0]
            for idx in reversed(sel):
                listbox.delete(idx)
                del queue_list[idx]
            list_dirty[0] = True
            # [추가 - 사용자 요청] "Remove Selected도 하나 지우면 list의
            # 다음 json이 자동 선택되게" - 삭제된 자리로 올라온(원래
            # 다음 순번) 항목을 이어서 선택해, 여러 개를 연달아 지울 때
            # 매번 다시 클릭할 필요가 없게 한다.
            if queue_list:
                next_idx = min(first_idx, len(queue_list) - 1)
                listbox.selection_set(next_idx)
                listbox.activate(next_idx)
                listbox.see(next_idx)

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
            list_dirty[0] = True

        # [추가 - 요청] "Batch Set 순서를 txt 파일로 저장/불러오기, 필요하면
        # 직접 수정해서 재사용" - 지금까지는 Batch Set을 열 때마다 매번
        # Template을 수동으로 다시 추가/재정렬해야 했음. 한 줄에 Template
        # 파일 하나씩(template 폴더 기준 상대경로 - 메모장 등으로 직접 열어
        # 고치기 쉽도록) 적은 평범한 txt로 저장해서, 다음에 그 파일을
        # 불러오면 같은 순서로 순식간에 복원된다.
        def _write_list_to(path):
            """[추가] queue_list를 path에 한 줄씩(template_dir 기준 상대경로,
            벗어나면 절대경로) 저장한다 - save_list()(직접 이름 골라 저장)와
            Run Batch Set 실행 시 자동 저장 확인(아래) 둘 다 이 헬퍼로
            통일해서 파일 형식이 어긋나지 않게 한다."""
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
                return False
            list_dirty[0] = False
            last_list_path[0] = path
            return True

        def save_list():
            if not queue_list:
                messagebox.showwarning("Batch Set", "저장할 Template이 없습니다.", parent=dlg)
                return
            if last_list_path[0]:
                init_dir = os.path.dirname(last_list_path[0]) or template_dir
                init_file = os.path.basename(last_list_path[0])
                ext = os.path.splitext(init_file)[1] or ".txt"
            else:
                init_dir, init_file, ext = template_dir, "", ".txt"
            path = filedialog.asksaveasfilename(
                parent=dlg, initialdir=init_dir, initialfile=init_file, defaultextension=ext,
                filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
                title="Batch Set 순서를 파일로 저장"
            )
            if not path:
                return
            _write_list_to(path)

        def _default_list_path():
            """[추가 - 요청] "Run Batch Set 실행 시, 저장된 적 없는 목록이면
            빈 파일명 대신 default 파일명을 제시하고, 같은 이름이 이미
            있으면 _#를 붙여라" - template_dir에 BatchSetList.txt가 없으면
            그대로, 있으면 BatchSetList_1.txt, _2.txt.. 순으로 비어있는
            이름을 찾는다."""
            base, ext = "BatchSetList", ".txt"
            candidate = os.path.join(template_dir, base + ext)
            n = 1
            while os.path.exists(candidate):
                candidate = os.path.join(template_dir, f"{base}_{n}{ext}")
                n += 1
            return candidate

        def _apply_list_file(path, replace=False):
            """[추가] load_list()와 edit_list_notepad() 둘 다 "txt 한 줄당
            Template 하나"를 큐에 반영하는 동일한 로직을 쓰므로 공통 헬퍼로
            뺌 - Edit in Notepad...에서 메모장을 닫자마자 같은 파일을 바로
            불러오는 데도 그대로 재사용.
            [수정 - 버그] replace=False(기존 동작, List Load용)는 항상
            append라서, "이미 이 파일을 불러와 둔 상태에서 Edit in
            Notepad...로 그 파일을 고치고 닫으면" 기존 항목 위에 고친
            내용이 또 append되어 전부 중복되는 문제가 있었음(예: A,B,C가
            이미 목록에 있는데 그 파일을 열어 순서만 B,A,C로 바꾸고 닫으면
            A,B,C,B,A,C가 됨). Edit in Notepad...는 "그 파일 내용 그대로
            반영"이 목적이므로, replace=True를 받으면 적용 전에 기존 목록을
            비운다."""
            try:
                with open(path, "r", encoding="utf-8") as f:
                    # [추가 - 요청] "메모장으로 직접 손볼 때 주석을 남길 수
                    # 있는지, 첫 칸에 #?" - #으로 시작하는 줄(공백 제거 후
                    # 기준)은 주석으로 보고 건너뛴다. 저장(List Save)은
                    # queue_list(파일 경로)만 기록하므로 주석은 손으로 편집한
                    # 파일에서만 유지됨 - Edit in Notepad...로 열어 직접
                    # 적어두면 다음에 그 파일을 불러올 때도 그대로 무시된다.
                    # [수정 - 요청] "dat 파싱과 같은 규칙(#,!,**,= 줄 시작 +
                    # inline !)을 여기도 적용" - data_parser의 공용 주석
                    # 규칙을 그대로 재사용해 통일함.
                    lines = [
                        stripped for ln in f
                        if not is_comment_or_blank(stripped := strip_inline_comment(ln).strip())
                    ]
            except OSError as e:
                messagebox.showerror("Batch Set", f"불러오기 실패:\n{e}", parent=dlg)
                return
            if replace:
                queue_list.clear()
                listbox.delete(0, "end")
            last_list_path[0] = path

            def _resolve(entry):
                p = entry if os.path.isabs(entry) else os.path.join(template_dir, entry)
                p = os.path.normpath(p)
                # [추가 - 요청] "확장자 없이 적어도 되는지(자동인식)" - Batch
                # Set List는 어차피 Template(.json)만 다루므로, 그대로는 없는데
                # 확장자가 아예 없으면 .json을 붙여 한 번 더 찾아본다.
                if not os.path.exists(p) and not os.path.splitext(p)[1]:
                    p_json = p + ".json"
                    if os.path.exists(p_json):
                        return p_json
                return p

            missing = []
            added = False
            for line in lines:
                # [추가 - 요청] "한 줄에 여러 Template을 콤마/공백/탭으로 구분해
                # 적을 수 있는지, 공백 포함 파일명은 ""로 감싸면" - Windows
                # 경로/파일명엔 공백이 흔해서(예: "케이스 1.json") 무조건
                # 나누면 멀쩡한 파일명이 두 개로 쪼개질 위험이 있음. 그래서:
                # 1) 그 줄 전체가 그대로 존재하는 파일이면(공백 포함 파일명을
                #    따옴표 없이 한 줄에 하나만 적은 경우 등) 나누지 않고 그대로 씀.
                # 2) 아니면 shlex로 나눈다 - 공백/탭 구분은 기본 지원하고,
                #    ""로 감싼 구간은 안에 공백이 있어도 하나로 유지됨.
                # 3) shlex가 처리 못 하는 콤마 구분은 각 조각을 다시 콤마로
                #    쪼개서 지원(따옴표 안의 콤마까지 보호하진 못하는 게
                #    한계 - 파일명에 콤마가 실제로 들어가는 경우는 드물어서 감수).
                if os.path.exists(_resolve(line)):
                    entries = [line]
                else:
                    try:
                        tokens = shlex.split(line)
                    except ValueError:
                        # 따옴표 짝이 안 맞는 등 shlex가 실패하면 공백 기준으로 폴백
                        tokens = line.split()
                    entries = [part for tok in tokens for part in tok.split(",") if part]
                for entry in entries:
                    p = _resolve(entry)
                    if os.path.exists(p):
                        queue_list.append(p)
                        listbox.insert("end", os.path.basename(p))
                        added = True
                    else:
                        missing.append(entry)
            if replace and not missing:
                # replace 모드는 이 파일 내용을 그대로 화면에 반영한 것이라(빠진
                # 항목 없이) 지금 화면 상태 == 파일 내용이므로 dirty가 아님.
                list_dirty[0] = False
            elif added:
                # [추가] Load는 기존 목록 뒤에 이어붙이는 방식이라, 지금
                # 화면 상태가 방금 불러온 그 파일과 완전히 같다는 보장이
                # 없음(이미 다른 항목이 있었을 수도 있음) - 안전하게 dirty로
                # 표시해 Run Batch Set 때 저장 여부를 물어보게 함.
                list_dirty[0] = True
            if missing:
                messagebox.showwarning(
                    "Batch Set",
                    "다음 항목은 파일을 찾을 수 없어 건너뛰었습니다:\n" + "\n".join(missing),
                    parent=dlg
                )

        def load_list():
            path = filedialog.askopenfilename(
                parent=dlg, initialdir=template_dir,
                filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
                title="Batch Set 순서 파일 불러오기 (기존 목록 뒤에 추가됨)"
            )
            if not path:
                return
            _apply_list_file(path)

        # [수정 - 사용자 보고 버그] "이름기준을 위 Format에 정렬하라니까 왜
        # 못 알아듣지?" - pack()은 서로 다른(별개) Frame 두 줄의 시작 x를
        # 픽셀 단위로 맞춰준다는 보장이 없고(버튼 개수/폭이 줄마다 달라
        # "대충 비슷한 위치"에 그침), 렌더링 후 위젯의 winfo_x()를 읽어
        # 맞추는 방식도 다이얼로그가 아직 화면에 map되기 전이라 항상 0을
        # 반환해 실패했음(실측 확인) - 두 줄을 하나의 grid_frame 안에서
        # grid(row=0/1, column=...)로 배치한다. grid는 "같은 컬럼은 모든
        # 행에서 항상 같은 x에서 시작"이 보장되므로, Format과 이름 기준을
        # 같은 컬럼(옆의 버튼 개수가 서로 달라도)에 두면 폰트/DPI와 무관하게
        # 항상 정확히 일치한다.
        grid_frame = ttk.Frame(dlg)
        grid_frame.pack(fill="x", padx=10, pady=5)
        # [수정 - 요청] "Batch Set 버튼들도 색상을 넣는 게 어떨지" - Batch
        # Queue와 같은 방식(_mk_btn, tk.Button 기반 - ttk.Button 렌더링 버그
        # 우회책이기도 함)으로 통일, 높이도 Batch Queue와 맞춤.
        # [수정 - 요청] "Batch Set/Batch Queue/M-P 선택창 버튼들이 메인 창의
        # PLOT~Multi-Plot 버튼보다 크고 높다" - 여러 차례 조정 끝에(42px ->
        # 36px) 결국 메인 창 버튼들과 맞추기로 하고, _mk_btn의 기본값(btn_pady=0,
        # 다른 대부분의 색상 버튼-Curves/Marker/Browse/Template 등-이 이미
        # 쓰는 값)으로 되돌림. Batch Set/Batch Queue/M-P(Multi Save-Print)
        # 세 창 모두 동일 적용해 서로 높이가 계속 일치하도록 함.
        self._mk_btn(grid_frame, "+ Add Templates...", add_files, color="grey", btn_pady=0,
                     grid_kw=dict(row=0, column=0, padx=5, sticky="w"))
        self._mk_btn(grid_frame, "Remove Selected", remove_selected, color="grey", btn_pady=0,
                     grid_kw=dict(row=0, column=1, padx=5, sticky="w"))
        self._mk_btn(grid_frame, "▲", lambda: move(-1), color="grey", btn_pady=0, btn_width=3,
                     grid_kw=dict(row=0, column=2, padx=2, sticky="w"))
        self._mk_btn(grid_frame, "▼", lambda: move(1), color="grey", btn_pady=0, btn_width=3,
                     grid_kw=dict(row=0, column=3, padx=2, sticky="w"))

        # [수정 - 요청] "메모장으로 열어 고친 뒤 List Load를 또 눌러야 하는
        # 게 아니라, 저장하고 닫으면 그대로 불러오기(load)까지 되도록" -
        # 메모장이 닫힐 때까지 기다린 뒤, 같은 파일을 _apply_list_file로 바로
        # 불러온다. 메모장을 그냥 닫기만 하고 저장을 안 했으면 파일 내용이
        # 그대로라 다시 읽어도 문제 없음.
        # [수정 - 성능] subprocess.run을 메인 스레드에서 그대로 부르면 Tkinter는
        # 싱글스레드라 메모장을 닫을 때까지 이벤트 루프 전체가 멈춰(Batch Set
        # 창뿐 아니라 CathPlot 메인 창까지 응답 없음 상태로 보임) - 메모장
        # 실행은 백그라운드 스레드로 넘기고, 끝난 뒤 결과 반영(_apply_list_file)
        # 과 위젯 조작만 self.root.after로 메인 스레드에 되돌린다(_run_batch_
        # queue_async 등 기존 코드와 같은 패턴). 메모장이 열려 있는 동안 같은
        # 버튼을 또 눌러 두 번째 메모장이 뜨는 것도 막아둔다.
        def edit_list_notepad():
            path = filedialog.askopenfilename(
                parent=dlg, initialdir=template_dir,
                filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
                title="Batch Set 순서 파일을 메모장으로 열어 편집 (닫으면 자동으로 다시 불러옴)"
            )
            if not path:
                return

            edit_btn.config(state="disabled")

            def worker():
                error = None
                try:
                    subprocess.run(["notepad.exe", path])
                except OSError as e:
                    error = e

                def _finish():
                    # [수정 - 버그] 메모장이 열려 있는 동안 Batch Set 창 자체가
                    # 닫혔을 수 있음(취소 등) - 이미 파괴된 위젯(listbox 등)을
                    # 건드리면 TclError가 나므로, 창이 남아있을 때만 반영한다.
                    if not dlg.winfo_exists():
                        return
                    edit_btn.config(state="normal")
                    if error is not None:
                        messagebox.showerror("Batch Set", f"메모장 실행 실패:\n{error}", parent=dlg)
                        return
                    # replace=True: 편집한 파일 내용을 그대로 반영(기존 목록에
                    # 이어붙이지 않음) - 아래 _apply_list_file 주석 참고.
                    _apply_list_file(path, replace=True)

                self.root.after(0, _finish)

            threading.Thread(target=worker, daemon=True).start()

        # [수정 - 사용자 요청] "Format도 약간 더 왼쪽으로" - 버튼들 바로
        # 옆(컬럼4)에 최소 여백만 두고 배치.
        ttk.Label(grid_frame, text="Format:").grid(row=0, column=4, padx=(12, 2), sticky="w")
        # [수정] "Word 등에 이미지로 넣으려면 pdf는 안 되고, 가볍고 품질 좋은
        # png가 default여야 함" - 기본 포맷을 png로 변경, jpg 추가, 순서를
        # png/pdf/jpg/svg/emf/eps로 통일.
        fmt_var = tk.StringVar(value="png")
        ttk.Combobox(
            grid_frame, textvariable=fmt_var, values=["png", "pdf", "jpg", "svg", "emf", "eps"],
            width=6, state="readonly"
        ).grid(row=0, column=5, sticky="w")

        # [수정 - 사용자 보고 버그] "Format box는 그 위치 그대로 두고 이름
        # 기준 등을 Format에 맞춰 바로 아래에" - List Save/List Load/Edit in
        # Notepad를 grid_frame의 1행(row=1)에 놓고, 이름 기준/접미사는 Format과
        # 같은 컬럼(4,5)에 이어서 놓아 항상 픽셀 단위로 정확히 아래에 오게 한다.
        self._mk_btn(grid_frame, "List Save...", save_list, color="grey", btn_pady=0,
                     grid_kw=dict(row=1, column=0, padx=5, pady=(5, 0), sticky="w"))
        self._mk_btn(grid_frame, "List Load...", load_list, color="grey", btn_pady=0,
                     grid_kw=dict(row=1, column=1, padx=5, pady=(5, 0), sticky="w"))
        edit_btn = self._mk_btn(grid_frame, "Edit in Notepad...", edit_list_notepad, color="grey", btn_pady=0,
                                 grid_kw=dict(row=1, column=2, columnspan=2, padx=5, pady=(5, 0), sticky="w"))
        name_suffix_row = grid_frame

        # [추가 - 사용자 요청] "batch set에서 만들어지는 이미지파일명에 대한
        # 사용자 선택 옵션 - template와 같은 파일명+batch, Plot_File_Name+
        # batch... 같은 파일이 존재하면 _#로 추가" - 출력 파일명을 무엇
        # 기준으로 만들지 고를 수 있게 한다. "Template 파일명"(기본, 서로
        # 다른 template은 항상 서로 다른 json 파일명이라 고유함이 보장됨)과
        # "Plot File Name"(메인 화면의 Plot File Name 입력칸 값 - plot 창
        # 이름과 저장 파일명 기본값으로 쓰이는 바로 그 필드. 원본 dat
        # 파일명 기반이라 같은 dat로 만든 여러 template이 흔히 겹침 -
        # 그래서 겹치면 자동으로 "_2","_3"...을 붙여 절대 서로 덮어쓰지
        # 않게 한다). [수정 - 사용자 지적] 처음엔 이 옵션을 "Plot Title"로
        # 잘못 표시했었는데, 실제로 쓰는 값은 title_var(그래프 위에 표시되는
        # 제목)가 아니라 filename_var(Plot File Name - plot 창 이름과
        # 동일한 값)라서 혼동을 막기 위해 이름을 바로잡음.
        ttk.Label(name_suffix_row, text="이름 기준:").grid(row=1, column=4, padx=(12, 2), pady=(5, 0), sticky="w")
        NAME_MODE_DISPLAY = {"template": "Template 파일명", "title": "Plot File Name"}
        NAME_MODE_FROM_DISPLAY = {v: k for k, v in NAME_MODE_DISPLAY.items()}
        name_mode_display_var = tk.StringVar(value=NAME_MODE_DISPLAY["template"])
        ttk.Combobox(
            name_suffix_row, textvariable=name_mode_display_var,
            values=list(NAME_MODE_DISPLAY.values()), width=14, state="readonly"
        ).grid(row=1, column=5, pady=(5, 0), sticky="w")

        # [추가 - 사용자 요청] "굳이 batchset을 안 붙여도 될 듯한데... 아니면
        # 간단히 bat만 붙이든지" - 접미사 자체를 직접 입력할 수 있게 한다
        # (기본 "_bat"로 짧게, 완전히 비우면 접미사 없이 이름 그대로 저장 -
        # 그래도 같은 이름이 이미 있으면 자동으로 "_2","_3"...는 그대로 붙음).
        ttk.Label(name_suffix_row, text="  접미사:").grid(row=1, column=6, pady=(5, 0), sticky="w")
        suffix_var = tk.StringVar(value="_bat")
        # [수정 - 사용자 요청] "접미사 박스도 줄이고 딱 맞게" - "_bat"(4글자)
        # 기준으로 딱 맞는 폭으로 축소(기존 7 -> 5).
        ttk.Entry(name_suffix_row, textvariable=suffix_var, width=5).grid(row=1, column=7, padx=(2, 0), pady=(5, 0), sticky="w")

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
        # [수정 - 요청] "(3D Template 없음)" -> "(없음)"으로 줄였다가, 그마저도
        # 없는 상태를 굳이 문구로 표시할 필요 없다는 피드백 - 선택 전엔 아예
        # 빈 칸으로 두고, 실제 선택됐을 때만 파일명이 나타나게 한다.
        td3_label = ttk.Label(td3_row, text="", foreground="#555555")
        td3_label.pack(side="left", padx=5)

        def pick_3d_template():
            p = filedialog.askopenfilename(
                parent=dlg, initialdir=template_dir,
                filetypes=[("CathPlot 3D Template", "*.json"), ("All files", "*.*")],
                title="3D Template 선택 (Batch Set 전체 항목에 공통 적용)"
            )
            if p:
                td3_path_var.set(p)
                td3_label.config(text=os.path.basename(p), foreground="black")

        # [수정 - 사용자 보고] "3D 관련 box 선택/미선택을 줄여줘요. 너무 큼
        # (특히 세로 폭이, 가로도 줄이고)" - 순수 ttk.Button은 세로 padding이
        # 기본값이라 옆의 다른 버튼들(_mk_btn 기반, btn_pady=0으로 이미
        # 압축됨)보다 훨씬 두꺼워 보였음 - 이 다이얼로그의 다른 버튼들과
        # 동일한 _mk_btn(compact)으로 통일하고 폭도 좁게 지정.
        self._mk_btn(td3_row, "선택...", pick_3d_template, color="grey", btn_pady=0, btn_width=6, side="left", padx=5)
        # [수정 - 요청] "해제" 버튼이 마치 뭔가를 고정/잠금 해제하는 것처럼
        # 읽혀 헷갈린다는 피드백 - 실제 동작(고른 3D Template을 다시 없음
        # 상태로 되돌림)에 맞게 "미선택"으로 라벨만 변경.
        self._mk_btn(td3_row, "미선택", lambda: (td3_path_var.set(""), td3_label.config(text="", foreground="#555555")),
                     color="grey", btn_pady=0, btn_width=6, side="left")

        # [추가 - 사용자 요청] "batch set에서 axis frame 크기를 이미지 선택처럼
        # 입력으로 주는 건 어떨까요? (template에 없으니까...)" - CathPlot을 막
        # 띄우고(메인 화면 값을 따로 맞출 겨를 없이) 바로 Batch Set부터 여는
        # 경우가 흔해서(자동화 워크플로), 메인 화면의 공용 Axis Frame 위젯 값을
        # 그냥 읽어오는 방식(Multi-Plot과 동일한 방식) 대신, Batch Set 다이얼로그
        # 안에 별도 입력칸을 둔다. 체크 해제(기본값) 시엔 지금까지와 동일하게
        # 각 template 자신의 frame 설정(Auto면 10x8cm, Manual이면 그 값)을 그대로
        # 쓰고, 체크하면 여기 입력한 크기를 모든 template에 공통으로 덮어쓴다.
        # [수정 - 사용자 보고 버그] "글자가 안 잘리게, axis frame 관련 설명은
        # 다음 줄에 명시" - 체크박스+입력칸 줄과 안내 문구를 한 줄에 같이
        # 욱여넣어서 다이얼로그 폭에 안 들어가고 잘려 보였음 - 안내 문구를
        # 별도 줄(common_frame_note_row)로 분리하고, 체크박스도 다른 화면의
        # 체크박스들과 같은 _mk_check(직접 그린 비트맵 기반, 네이티브보다
        # 크고 또렷함)로 통일해서 크기를 키운다.
        common_frame_row = ttk.Frame(dlg)
        common_frame_row.pack(fill="x", padx=10, pady=(0, 2))
        common_frame_var = tk.BooleanVar(value=False)
        common_frame_w_var = tk.StringVar(value="10.00")
        common_frame_h_var = tk.StringVar(value="8.00")
        common_frame_unit_var = tk.StringVar(value="cm")

        self._mk_check(common_frame_row, "공통 Axis Frame 크기 사용", common_frame_var,
                        color="accent", size=19, bold=True, side="left")
        cf_w_entry = ttk.Entry(common_frame_row, textvariable=common_frame_w_var, width=6)
        cf_w_entry.pack(side="left", padx=(10, 2))
        ttk.Label(common_frame_row, text="x").pack(side="left")
        cf_h_entry = ttk.Entry(common_frame_row, textvariable=common_frame_h_var, width=6)
        cf_h_entry.pack(side="left", padx=(2, 4))
        cf_unit_combo = ttk.Combobox(common_frame_row, textvariable=common_frame_unit_var, values=["cm", "in"], width=4, state="readonly")
        cf_unit_combo.pack(side="left")

        def _update_common_frame_state(*_a):
            state = "normal" if common_frame_var.get() else "disabled"
            cf_w_entry.config(state=state)
            cf_h_entry.config(state=state)
            cf_unit_combo.config(state=("readonly" if common_frame_var.get() else "disabled"))
        common_frame_var.trace_add("write", _update_common_frame_state)
        _update_common_frame_state()

        common_frame_note_row = ttk.Frame(dlg)
        common_frame_note_row.pack(fill="x", padx=10, pady=(0, 5))
        # [수정 - 사용자 요청] "아래 comment도 비례하지 않으니 는 위로 붙이고,
        # 필요하면 각.... 등은 다음 줄로" - 줄바꿈 지점을 "자동으로" 뒤가
        # 아니라 "비례하지 않으니," 뒤로 옮긴다(1행은 위 체크박스 줄과 더
        # 붙어 보이게, 2행은 "필요하면"부터 시작).
        ttk.Label(
            common_frame_note_row,
            text="(체크 해제 시 개별 template 설정 사용. 프레임 크기를 바꿔도 폰트 크기는 자동으로 비례하지 않으니,\n"
                 "필요하면 각 template의 Font 크기도 같이 조정하세요)",
            foreground="#555555", justify="left"
        ).pack(side="left")

        def _confirm_save_before_run(target_path):
            """[수정 - 요청] "제안된 이름을 거절(아니오)하면 그냥 저장 없이
            넘어가는 게 아니라, 다른 파일명을 직접 넣을 수 있어야" - 기존엔
            askyesno(예/아니오) 2개뿐이라 "아니오"가 곧 "저장 안 함"이었음.
            버튼 3개짜리 작은 확인창으로 바꿔서 "다른 이름으로 저장..."을
            고르면 List Save...와 같은 파일 대화상자가 뜨도록 분리함.
            반환값: "quick"(제안된 이름 그대로) / "saveas"(다른 이름 직접
            입력) / "skip"(저장 안 하고 바로 실행)."""
            choice = {"v": "skip"}
            fname = os.path.basename(target_path)
            verb = "덮어쓸까요" if last_list_path[0] else "저장할까요"

            confirm = tk.Toplevel(dlg)
            confirm.title("Batch Set")
            confirm.transient(dlg)
            confirm.resizable(False, False)
            ttk.Label(
                confirm,
                text="지금 구성한 Batch Set 순서가 저장되어 있지 않습니다.\n"
                     f"'{fname}' 파일로 {verb}?",
                justify="left"
            ).pack(padx=15, pady=(15, 10))

            def pick(v):
                choice["v"] = v
                confirm.destroy()

            btns = ttk.Frame(confirm)
            btns.pack(pady=(0, 15), padx=15)
            # [수정 - 버그] 이 작은 확인창처럼 새로 뜨는 Toplevel 안 ttk.Button은
            # 이 PC의 Windows 테마에서 글자가 안 보이거나 깨지는 렌더링 버그가
            # 있었음(Batch Queue 쪽에서 실제 화면 캡처+픽셀 분석으로 확인,
            # 아래 참고) - 검증된 tk.Button 기반 _mk_btn으로 통일.
            self._mk_btn(btns, "예 (이 이름으로 저장)", lambda: pick("quick"), color="accent2", side="left", padx=5)
            self._mk_btn(btns, "다른 이름으로 저장...", lambda: pick("saveas"), color="grey", side="left", padx=5)
            self._mk_btn(btns, "아니오 (저장 안 함)", lambda: pick("skip"), color="danger", side="left", padx=5)
            confirm.protocol("WM_DELETE_WINDOW", lambda: pick("skip"))
            confirm.grab_set()
            dlg.wait_window(confirm)
            return choice["v"]

        def run_batch_set():
            if not queue_list:
                messagebox.showwarning("Batch Set", "먼저 Template 파일을 추가하세요.")
                return
            # [수정 - 요청] "저장 여부를 묻되, 기존 파일 있으면 그 이름으로
            # 덮어쓸지 물어보고, 없으면 default 파일명을 제시(중복이면 _#
            # 추가)해라" - 이 확인 팝업 자체에 저장될 파일명을 미리 보여주고
            # "예"만 누르면 바로 그 이름으로 저장한다. "다른 이름으로
            # 저장..."을 고르면 List Save...와 같은 파일 대화상자가 뜬다.
            if list_dirty[0]:
                _target_path = last_list_path[0] or _default_list_path()
                _choice = _confirm_save_before_run(_target_path)
                if _choice == "quick":
                    _write_list_to(_target_path)
                elif _choice == "saveas":
                    save_list()
            dlg.destroy()
            _name_mode = NAME_MODE_FROM_DISPLAY.get(name_mode_display_var.get(), "template")
            _common_frame = None
            if common_frame_var.get():
                _cf_w = (common_frame_w_var.get() or "").strip()
                _cf_h = (common_frame_h_var.get() or "").strip()
                try:
                    float(_cf_w); float(_cf_h)
                    _common_frame = (_cf_w, _cf_h, common_frame_unit_var.get())
                except ValueError:
                    messagebox.showwarning("Batch Set", "공통 Axis Frame 크기가 숫자가 아닙니다. 개별 template 설정으로 진행합니다.")
            self._run_batch_set_async(list(queue_list), fmt_var.get(), td3_path_var.get() or None,
                                       name_mode=_name_mode, out_suffix=suffix_var.get(), common_frame=_common_frame)

        # [수정 - 사용자 요청] "Run Batch Set/취소 버튼은 좀 더 키우고" ->
        # 이후 "너무 크네" - btn_pady=10/큰 btn_width는 과했음, 다른 보조
        # 버튼(btn_pady=0)보다는 살짝 크되 과하지 않은 중간값으로 조정.
        run_row = ttk.Frame(dlg)
        run_row.pack(fill="x", padx=10, pady=10)
        self._mk_btn(run_row, "취소", dlg.destroy, color="danger", btn_pady=3, btn_width=8, side="right", padx=5)
        self._mk_btn(run_row, "Run Batch Set", run_batch_set, color="accent", btn_pady=3, btn_width=13, side="right", padx=5)

    def _render_3d_from_template_data(self, data, td3_data, outfile, fmt):
        """[추가] "3D도 Batch에 연동" - 2D Template의 data(file_assignments/
        surface_files)로 3D curve/surface를 derive하고, 3D Template(td3_data)의
        설정(회전각/Style/Palette/Marker/Comment 등)을 그대로 적용해서 3D 이미지를
        만든다. Tkinter 위젯 접근이 없어 백그라운드 스레드에서 호출해도 안전함.
        curve/surface가 하나도 없으면(적격 조건 안 맞음) 조용히 스킵(None 반환)."""
        eligible, _skipped = self._build_3d_curves_from_template_data(data, td3_data)
        surfaces = self._build_3d_surfaces_from_template_data(data)
        if not eligible and not surfaces:
            return None

        # [수정] "Marker Size, Style을 세트별로" - 3D Template의 marker_shapes와
        # 같은 방식(label 기준 dict)으로 저장된 marker_sizes/styles를 그대로 씀
        # (예전 템플릿에 있던 전역 marker_size/style 키는 없으면 기본값으로 대체).
        shapes = td3_data.get("marker_shapes", {})
        sizes = td3_data.get("marker_sizes", {})
        styles = td3_data.get("styles", {})
        # [수정 - 버그] "3D Curve 이름을 template에 저장" 기능(titles dict)이
        # 화면(대화형) 렌더링 경로에만 반영되고, Batch Set의 이 헤드리스 경로는
        # 계속 label을 그대로 title로 써서 사용자가 지정한 legend 이름이 무시되고
        # 있었음 - marker_shapes/sizes/styles와 동일한 label 기준 dict이므로
        # 같은 방식으로 반영한다(없으면 기존처럼 label 그대로 사용).
        titles = td3_data.get("titles", {})
        # [추가 - 사용자 요청] "3D Marker 개수도 template에 기록되게" - 화면
        # 렌더링 경로와 동일하게 Batch도 3D Template에 저장된 MaxNo.를 그대로
        # 적용한다(없으면 None = Auto~25개, create_3d_script 기본값).
        maxcounts = td3_data.get("marker_max_counts", {})
        _legacy_size = MARKER_SIZE_MAP.get(td3_data.get("marker_size", "M"), 1.0)
        _legacy_style = STYLE_3D_INTERNAL_MAP.get(td3_data.get("style", "Lines"), "lines")

        def _with_marker(item):
            item = dict(item)
            hollow_pt, _ = MARKER_SHAPE_MAP.get(shapes.get(item["label"], "Circle"), (None, None))
            item["marker_shape"] = hollow_pt
            item["marker_size"] = MARKER_SIZE_MAP.get(sizes.get(item["label"], ""), _legacy_size)
            item["style"] = STYLE_3D_INTERNAL_MAP.get(styles.get(item["label"], ""), _legacy_style)
            item["title"] = titles.get(item["label"], "").strip() or item["label"]
            _mc_str = str(maxcounts.get(item["label"], "") or "").strip()
            item["marker_max_count"] = int(_mc_str) if _mc_str else None
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

    def _process_one_batch_set_item(self, tpath, fmt, td3_data, name_mode="template", reserved_names=None, reserved_lock=None, out_suffix="_batchset", common_frame=None):
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

        # [수정 - 사용자 보고 버그] "Batch Set으로 1plot을 그리면 title/tic/
        # legend 폰트가 그림 대비 너무 작음" - execute_plot_pipeline(화면의
        # PLOT/SAVE/PRINT 버튼이 쓰는 경로)은 "Axis Frame Auto가 켜진 채로
        # 파일 출력하면 항상 기준 10x8cm로 계산"하는 로직이 있는데(그렇게
        # 안 하면 create_script가 Auto를 "11.7x8.3in 인쇄 페이지" 크기로
        # 가정해버려 캔버스가 훨씬 커지고, 절대 pt 크기인 폰트는 그대로라
        # 상대적으로 작아 보임), Batch Set/Queue는 이 함수에서 바로
        # create_script를 불러 그 로직을 거치지 않는다 - template에 저장된
        # frame_auto가 True(흔한 기본값)면 그대로 Auto로 렌더링돼 이 문제가
        # 재현된다. 같은 해석(Auto -> 10x8cm Manual)을 여기서도 적용한다.
        # [추가 - 사용자 요청] "batch set에서 axis frame 크기를 공통 입력으로
        # 주는 방안" - common_frame이 주어지면(Batch Set 다이얼로그에서 체크한
        # 경우) 각 template 자신의 frame_auto/width/height와 무관하게 이 크기를
        # 전부 동일하게 덮어쓴다(Multi-Plot이 메인 화면의 공용 Axis Frame 값을
        # 모든 선택 plot에 일괄 적용하는 것과 같은 원칙). 지정 안 하면(기본,
        # 체크 해제) 기존처럼 template 개별 설정을 따르되 Auto는 10x8cm로 resolve.
        if common_frame is not None:
            plotdef.frame_auto = False
            plotdef.frame_width, plotdef.frame_height, plotdef.frame_unit = common_frame
        elif plotdef.frame_auto:
            plotdef.frame_auto = False
            plotdef.frame_width, plotdef.frame_height = self._compute_auto_frame_size_cm(for_print=True)
            plotdef.frame_unit = "cm"

        # [추가 - 사용자 질문/요청] PIP가 ".plt 파일" 소스를 쓰는데 그 파일이
        # 참조하던 dat(정렬 캐시나 원본)를 이 기기/폴더에서 못 찾은 경우
        # (_resolve_pip_dict_for_batch가 채워둠) - 조용히 빠지지 않고 다른
        # 경고들과 같은 방식으로 res["warnings"]에 모아 사용자에게 보인다.
        _pip_src_warn = (plotdef.pip or {}).pop("_source_warnings", None) if getattr(plotdef, "pip", None) else None
        if _pip_src_warn:
            for w in _pip_src_warn:
                res["warnings"].append(f"{tname}: PIP {w}")

        # [수정 - 사용자 보고 버그, 이후 요청으로 선택 옵션화] "Batch Set
        # 결과가 원본dat파일명(Plot_File_Name)+batchset으로 나와서, 같은
        # dat 파일에서 만든 여러 template(예: 16개)이 실제로는 6개 파일로만
        # 저장되며 서로 덮어씀" - Plot_File_Name은 같은 dat 파일로 만든
        # 여러 template이 흔히 공유하는 값이라 고유 식별자가 못 된다.
        # 기본은 template 자신의 json 파일명(항상 서로 다름) 기준으로
        # 만들되, 사용자가 "Plot File Name" 기준을 직접 고르면 그 값을 쓴다
        # (요청). 접미사("_batchset")도 "굳이 안 붙여도 될 듯... 아니면
        # 간단히 bat만"이라는 요청에 따라 직접 입력(기본 "_bat", 비우면
        # 접미사 없음)할 수 있게 함. 이름이 겹치면(디스크에 이미 있던
        # 파일 포함, 또는 접미사를 비워 같은 template 이름끼리 겹치는
        # 경우) "_2","_3"...를 붙여 절대 서로 덮어쓰지 않는다 - 후보
        # 파일명 자체가 실제로 존재하는지(디스크 + 이번 배치에서 이미
        # 예약된 이름) 직접 확인하는 방식이라 접미사 유무와 무관하게
        # 항상 안전하다.
        if name_mode == "title":
            raw_name = (data.get("filename") or "").strip() or os.path.splitext(tname)[0]
        else:
            raw_name = os.path.splitext(tname)[0]
        base_safe_name = "".join(c for c in raw_name if c.isalnum() or c in ("_", "-")).strip() or "CathPlot"
        _suffix = "".join(c for c in (out_suffix or "") if c.isalnum() or c in ("_", "-"))

        def _candidate_stem(n):
            base = base_safe_name if n <= 1 else f"{base_safe_name}_{n}"
            return f"{base}{_suffix}"

        safe_stem = _candidate_stem(1)
        if reserved_names is not None and reserved_lock is not None:
            with reserved_lock:
                n = 1
                safe_stem = _candidate_stem(n)
                while safe_stem in reserved_names or os.path.exists(os.path.join(self.plot_dir, f"{safe_stem}.{fmt}")):
                    n += 1
                    safe_stem = _candidate_stem(n)
                reserved_names.add(safe_stem)
        outfile = os.path.join(self.plot_dir, f"{safe_stem}.{fmt}")

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
            outfile_3d = os.path.join(self.plot_dir, f"{safe_stem}_3D.{fmt}")
            try:
                result = self._render_3d_from_template_data(data, td3_data, outfile_3d, fmt)
                if result:
                    res["saved_3d"] = True
                else:
                    res["warnings"].append(f"{tname}: 3D 적격 조건(Y1 1개+Y2 1개, 또는 surface)에 맞는 파일이 없어 3D는 스킵")
            except Exception as e:
                res["errors"].append(f"{tname}: 3D 저장 실패 ({e})")

        return res

    def _run_batch_set(self, template_paths, fmt, progress_callback=None, td3_path=None, name_mode="template", out_suffix="_batchset", common_frame=None):
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

        # [추가 - 사용자 요청] "이름 기준(Plot File Name)을 고르면 같은 dat
        # 파일에서 만든 여러 template이 흔히 같은 이름으로 겹침 - 그 경우
        # 서로 덮어쓰지 않고 자동으로 _2, _3...을 붙여야 함" - 여러
        # template이 ThreadPoolExecutor로 동시에 처리되므로, "이번
        # 배치에서 이미 이 파일명을 예약했다"를 스레드 안전하게 기록/
        # 조회할 lock 하나를 만들어 각 작업자에게 넘긴다(실제 충돌 검사는
        # _process_one_batch_set_item 안에서 디스크의 실제 파일 존재 여부
        # 까지 함께 확인).
        _reserved_lock = threading.Lock()
        _reserved_names = set()

        done = 0
        with ThreadPoolExecutor(max_workers=_BATCH_MAX_WORKERS) as executor:
            futures = {
                executor.submit(self._process_one_batch_set_item, tpath, fmt, td3_data,
                                 name_mode, _reserved_names, _reserved_lock, out_suffix, common_frame): tpath
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

    def _run_batch_set_async(self, template_paths, fmt, td3_path=None, name_mode="template", out_suffix="_batchset", common_frame=None):
        """Batch Set을 백그라운드 스레드에서 실행하며 진행창을 보여준다."""
        job_id = self._register_batch_job("Batch Set", len(template_paths))

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
            try:
                self._run_batch_set(template_paths, fmt, progress_callback=progress_callback, td3_path=td3_path,
                                     name_mode=name_mode, out_suffix=out_suffix, common_frame=common_frame)
            finally:
                # [추가 - 요청] 작업이 끝났으니(성공/오류 무관) 실행 중 목록에서
                # 뺀다. dict 조작은 메인 스레드에서만 하도록 after(0, ...)로 넘김.
                self.root.after(0, lambda: self._unregister_batch_job(job_id))
            self.root.after(0, lambda: progress_win.destroy() if progress_win.winfo_exists() else None)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # [추가 - 요청] "DAT file 중 선택한 순서대로 curve를 그려주기(Legend box
    # 순서에도 연동)" - Y1/Y2 체크박스를 클릭한 순서(self._curve_order)를
    # 실제 그리기 순서로 변환하는 공용 헬퍼. PLOT/SAVE/PRINT(execute_plot_
    # pipeline)와 Batch Queue 레시피(_capture_curve_recipe) 둘 다 이걸 씀.
    # ------------------------------------------------------------------
    def _touch_curve_order(self, key):
        """Y1/Y2 체크박스가 눌릴 때마다 호출됨(make_y_excl_cmd). 지금 그
        key가 선택 상태(Y1 또는 Y2)면 순서 목록 맨 뒤에 추가(이미 있으면
        그대로 - 재정렬 아님), 선택 해제 상태면 목록에서 뺀다."""
        is_selected = (
            self.selected_y1_vars.get(key, tk.BooleanVar(value=False)).get()
            or self.selected_y2_vars.get(key, tk.BooleanVar(value=False)).get()
        )
        if is_selected:
            if key not in self._curve_order:
                self._curve_order.append(key)
        elif key in self._curve_order:
            self._curve_order.remove(key)

    def _ordered_selected_keys(self):
        """지금 Y1 또는 Y2로 선택된 모든 key(파일||output_no)를, 사용자가
        클릭(선택)한 순서 그대로 반환한다 - (ordered_keys, y1_key_set,
        y2_key_set) 튜플. self._curve_order에 없는 키(Template Load 등으로
        클릭을 거치지 않고 프로그램적으로 선택된 경우 - 안전망)는 원래
        순서 그대로 뒤에 덧붙인다."""
        y1_keys = [k for k, v in self.selected_y1_vars.items() if v.get()]
        y2_keys = [k for k, v in self.selected_y2_vars.items() if v.get()]
        y1_set, y2_set = set(y1_keys), set(y2_keys)
        selected = y1_set | y2_set
        ordered = [k for k in self._curve_order if k in selected]
        ordered += [k for k in y1_keys + y2_keys if k not in ordered]
        return ordered, y1_set, y2_set

    def _capture_curve_order(self):
        """[추가 - 요청] Template Save/Batch Set에도 클릭 순서를 반영하기 위해,
        _curve_order(화면의 절대경로 기준 key)를 file_assignments와 같은
        표현("cwd 기준 상대경로||output_no")으로 바꿔서 반환한다. Batch Set은
        이 문자열을 파일명까지 그대로 매칭하고(파일별로 정확), Template Load는
        같은 문자열에서 output_no만 뽑아 "레시피"(파일과 무관, curve_styles와
        동일한 매칭 방식) 순서로 재해석한다 - load_template 쪽 주석 참고."""
        ordered_keys, _y1, _y2 = self._ordered_selected_keys()
        result = []
        for key in ordered_keys:
            d_file, out_no = key.split("||")
            try:
                rel_path = os.path.relpath(d_file, self.cwd)
            except ValueError:
                rel_path = d_file
            result.append(f"{rel_path}||{out_no}")
        return result

    def _capture_legend_order(self, legend_key):
        """[추가 - 사용자 보고 버그] "Legend1 Curves로 순서를 바꾸면 Legend2도
        같이 바뀜 - 각각 독립적으로" 요청에 따라 추가된 legend별 독립 순서
        (self._legend_order[legend_key])를, _capture_curve_order와 동일한
        표현("cwd 기준 상대경로||output_no")으로 저장한다. 그 Legend에서
        아직 한 번도 순서를 안 바꿨으면(리스트가 비어있으면) 전체 클릭 순서
        (_curve_order)를 그대로 저장해, 다시 불러왔을 때도 "아직 커스텀
        안 한 상태"가 자연스럽게 유지되게 한다."""
        base_keys, _y1, _y2 = self._ordered_selected_keys()
        ordered_keys = self._legend_ordered_keys(legend_key, base_keys)
        result = []
        for key in ordered_keys:
            d_file, out_no = key.split("||")
            try:
                rel_path = os.path.relpath(d_file, self.cwd)
            except ValueError:
                rel_path = d_file
            result.append(f"{rel_path}||{out_no}")
        return result

    def _restore_legend_order_from_data(self, legend_key, entries):
        """[추가 - 사용자 보고 버그] Legend별 독립 순서를 Template에서 복원한다.
        curve_order 복원(load_template 안, 아래 참고)과 완전히 동일한 방식
        (파일명 무관 - output_no만으로 매칭하는 "레시피" 방식)을 그대로
        재사용해서, 서로 다른 dat 파일에 이 Template을 적용해도 legend 순서가
        의미 있게 이어진다."""
        _output_no_order = []
        _seen_no = set()
        for _entry in entries or []:
            try:
                _no = int(str(_entry).rsplit("||", 1)[1])
            except (ValueError, IndexError):
                continue
            if _no not in _seen_no:
                _seen_no.add(_no)
                _output_no_order.append(_no)
        _no_priority = {no: i for i, no in enumerate(_output_no_order)}
        _selected_keys = [k for k, v in self.selected_y1_vars.items() if v.get()]
        _selected_keys += [k for k, v in self.selected_y2_vars.items() if v.get()]
        _selected_keys = list(dict.fromkeys(_selected_keys))

        def _key_priority(k):
            try:
                no = int(k.split("||")[1])
            except (ValueError, IndexError):
                return len(_output_no_order)
            return _no_priority.get(no, len(_output_no_order))

        self._legend_order[legend_key] = sorted(_selected_keys, key=_key_priority)

    # ------------------------------------------------------------------
    # Batch Queue: 화면에서 지금 선택된 Y1/Y2/X (output_no=var_no 기준) 구성을
    # "레시피"로 캡처해서, 여러 dat 파일(상대경로)에 동일하게 적용하며
    # 각각 별도의 plot을 자동으로 만들어 저장한다.
    # ------------------------------------------------------------------
    def _capture_curve_recipe(self):
        """현재 화면에서 선택된 Y1/Y2 output_no(var_no) + 스타일과, X로 선택된 output_no를
        특정 파일명과 무관하게 레시피 형태로 추출한다."""
        # [수정 - 요청] "선택한 순서대로" - 예전엔 selected_y1_vars/selected_y2_vars
        # 딕셔너리 순서(=표에 나열된 순서)를 그대로 썼는데, 이제 클릭 순서
        # (_ordered_selected_keys)를 그대로 따른다.
        recipe = []
        ordered_keys, y1_set, _y2_set = self._ordered_selected_keys()
        for key in ordered_keys:
            _datfile_for_key, out_no = key.split("||")
            # [추가 - 사용자 보고 크리티컬 버그] "Template load 해서 그리면
            # 모두 나중 curve 이름/marker 모양 등이 같은 이름으로 나타남" -
            # load_template의 curve_styles 복원이 output_no만으로 매칭해서,
            # 서로 다른 파일이 같은 output_no를 쓰면(흔함) 전부 "레시피
            # 목록에서 그 output_no로 마지막에 나온 항목"으로 덮어써지고
            # 있었음. 여기서 각 항목에 원본 파일(cwd 기준 상대경로)을 같이
            # 저장해두면, Template Load가 file_assignments(정확히 어떤
            # 파일인지 이미 앎)와 함께 file+output_no로 정확히 매칭할 수
            # 있다. Batch Queue(_build_plotdef_from_template_data)는 이
            # 필드를 아예 안 읽으므로(의도적으로 파일 무관 재사용) 영향 없음.
            try:
                _rel_file_for_key = os.path.relpath(_datfile_for_key, self.cwd)
            except ValueError:
                _rel_file_for_key = _datfile_for_key
            recipe.append({
                "output_no": int(out_no),
                "file": _rel_file_for_key,
                "axis": "y1" if key in y1_set else "y2",
                # [추가 - 사용자 보고 버그] "변수명(legend)을 수정해서 저장했는데
                # load하니 원래 이름으로 되돌아감" - 지금까지 이 레시피가
                # legend 텍스트(사용자가 직접 고친 curve 이름) 자체를 아예
                # 저장하지 않아서, Load 시 파일을 새로 열거나 재사용할 때
                # show_variables()가 항상 파일 자체의 원래 변수명으로만
                # legend_vars를 채웠음(사용자가 고친 값이 있으면 안 덮어쓰지만,
                # 애초에 저장된 값 자체가 없으니 복원할 게 없었음). Batch
                # Set(_build_plotdef_from_template_data)은 원래도 이 값을 안
                # 쓰고 대상 파일 자신의 변수명을 그대로 쓰므로(여러 dat 파일에
                # 같은 레시피를 적용하는 용도라 의도적) 그쪽 동작에는 영향 없음.
                "legend": self.legend_vars[key].get() if key in self.legend_vars else "",
                "color": self.color_vars[key].get() if key in self.color_vars else "",
                "linestyle": self.linestyle_vars[key].get() if key in self.linestyle_vars else "",
                "linewidth": self.linewidth_vars[key].get() if key in self.linewidth_vars else "1.5",
                "legend_group": int(self.legend_group_vars[key].get()) if key in self.legend_group_vars else 1,
                "in_legend1": self.in_legend1_vars[key].get() if key in self.in_legend1_vars else True,
                "marker_shape_label": self.marker_shape_vars[key].get() if key in self.marker_shape_vars else "None",
                "marker_size_label": self.marker_size_vars[key].get() if key in self.marker_size_vars else "M",
                "marker_max_count": (self.marker_maxcount_vars[key].get() if key in self.marker_maxcount_vars else ""),
                "marker_fill": (self.marker_fill_vars[key].get() if key in self.marker_fill_vars else False),
                "smooth_csplines": (self.smooth_csplines_vars[key].get() if key in self.smooth_csplines_vars else False),
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

    def _open_legend_detail_popup(self):
        """Legend 상세 설정 팝업 - [수정 - 사용자 요청] "창 폭을 줄이려면
        Legend1/2 줄이 먼저 줄어야 하고, 상세 내용은 popup으로, 전체적으로
        깔끔한 입력 모양이 중요함" - Legend1/2 줄(legend1_row/legend2_row)과
        옛 row2_f에 있던 "자동 추정이 안 맞을 때만 쓰는" 저빈도 입력
        (Legend Font/Size, Box Thick, Box W/H)을 모두 여기로 모았다.
        Box Thick는 Legend1/2가 공유(기존과 동일), Box W/H는 Legend별로
        따로 입력한다."""
        popup = tk.Toplevel(self.root)
        popup.title("Legend Detail")
        popup.transient(self.root)

        # create_widgets()의 font_list/size_list와 동일 - 팝업이 별도
        # 메서드라 그 지역변수를 그대로 쓸 수 없어 다시 정의한다.
        font_list = ["Malgun Gothic", "Arial", "Times New Roman", "Courier New", "Consolas"]
        size_list = ["6", "8", "9", "10", "11", "12", "14", "16", "18", "20"]
        thick_list = ["0.8", "1.0", "1.2", "1.5", "2.0", "2.5", "3.0", "4.0"]

        body = ttk.Frame(popup)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        font_row = ttk.Frame(body)
        font_row.pack(fill="x", pady=(0, 6))
        ttk.Label(font_row, text="Legend Font:").pack(side="left", padx=(0, 2))
        font_combo = ttk.Combobox(font_row, textvariable=self.legend_font_var, values=font_list, width=14, state="readonly")
        font_combo.pack(side="left", padx=2)
        self._disable_combobox_wheel(font_combo)
        size_combo = ttk.Combobox(font_row, textvariable=self.legend_size_var, values=size_list, width=3, state="readonly")
        size_combo.pack(side="left", padx=2)
        self._disable_combobox_wheel(size_combo)

        thick_row = ttk.Frame(body)
        thick_row.pack(fill="x", pady=(0, 6))
        ttk.Label(thick_row, text="Box Thick (Legend1/2 공용):").pack(side="left", padx=(0, 2))
        thick_combo = ttk.Combobox(thick_row, textvariable=self.legend_thick_var, values=thick_list, width=4, state="readonly")
        thick_combo.pack(side="left", padx=2)
        self._disable_combobox_wheel(thick_combo)

        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=6)

        boxwh_l1_row = ttk.Frame(body)
        boxwh_l1_row.pack(fill="x", pady=2)
        ttk.Label(boxwh_l1_row, text="Legend1 Box W/H:", width=18, anchor="w").pack(side="left")
        self._mk_entry(boxwh_l1_row, self.legend_box_width_pct_var, width=5, color="accent3").pack(side="left", padx=1)
        self._mk_entry(boxwh_l1_row, self.legend_box_height_pct_var, width=5, color="accent3").pack(side="left", padx=1)

        boxwh_l2_row = ttk.Frame(body)
        boxwh_l2_row.pack(fill="x", pady=2)
        ttk.Label(boxwh_l2_row, text="Legend2 Box W/H:", width=18, anchor="w").pack(side="left")
        self._mk_entry(boxwh_l2_row, self.legend2_box_width_pct_var, width=5, color="accent3").pack(side="left", padx=1)
        self._mk_entry(boxwh_l2_row, self.legend2_box_height_pct_var, width=5, color="accent3").pack(side="left", padx=1)

        ttk.Label(
            body,
            text=("Print/Save 전용(화면 미리보기엔 적용 안 됨). 비우면 폰트 기준 자동 추정(기본) -\n"
                  "자동 추정이 안 맞을 때만 직접 지정.\n"
                  "숫자만: X/Y 데이터 좌표값 차이(인터랙티브 창에서 커서로 읽은 값 참고 - 예: 200)\n"
                  "%로 끝나면: axis 대비 비율 - 예: 30% (axis 범위가 나중에 바뀌면 비율도 같이 바뀜)"),
            foreground="#555555", justify="left"
        ).pack(anchor="w", pady=(8, 0))

        ttk.Button(popup, text="완료", command=popup.destroy).pack(anchor="e", padx=10, pady=8)

    def _open_curve_settings_popup(self):
        """Curve 설정 팝업(옛 Marker 설정 팝업) - Y1/Y2로 선택된 각 curve마다
        한 행씩, Color/Style(원래 Dat list에 인라인으로 있던 것 - "선택된
        curve에만 의미 있는 속성이니 Marker처럼 팝업으로 옮기는 게 더
        깔끔하고 Dat list 가로 공간도 확보된다"는 사용자 요청으로 이관)과
        기존 Shape(모양)/Size(크기)/Fill/Max Count(최대 마커 개수, 비우면
        Auto)를 한 곳에서 보여준다. 헤더와 입력칸 정렬은 고정 픽셀 폭
        프레임으로 맞춘다."""
        popup = tk.Toplevel(self.root)
        popup.title("Curve Settings")
        popup.transient(self.root)

        CURVE_PX, COLOR_PX, STYLE_PX, SHAPE_PX, SIZE_PX, FILL_PX, MAX_PX = 160, 65, 65, 100, 55, 50, 65

        def _cell(parent, px, height=20):
            f = tk.Frame(parent, width=px, height=height)
            f.pack_propagate(False)
            f.pack(side="left")
            return f

        header_f = ttk.Frame(popup)
        header_f.pack(fill="x", padx=10, pady=(10, 2))
        ttk.Label(_cell(header_f, CURVE_PX), text="Curve", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, COLOR_PX), text="Color", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, STYLE_PX), text="Style", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, SHAPE_PX), text="Shape", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, SIZE_PX), text="Size", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, FILL_PX), text="Fill", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, MAX_PX), text="Max#", font=("Consolas", 9, "bold")).pack(side="left")

        list_frame = ttk.Frame(popup)
        list_frame.pack(fill="both", expand=True, padx=10)

        # Max# 칸에는 정수만 입력되도록 (빈 값은 허용 - Auto 의미)
        vcmd = (popup.register(lambda s: s == "" or s.isdigit()), "%P")

        # [수정 - 사용자 보고 버그] "Marker 순서가 Curves(선택 순서)와 안
        # 맞고 dat list 순서로 나옴" - selected_y1_vars/selected_y2_vars
        # dict를 그대로 돌면 그 dict의 삽입 순서(=화면에 나열된 dat 변수
        # 목록 순서)를 따르게 되는데, 이는 Legend/curve_order 등 다른
        # 곳에서 이미 쓰는 "사용자가 클릭(선택)한 순서"(_ordered_selected_
        # keys)와 다르다 - 같은 기준으로 통일한다.
        # [수정 - 사용자 재보고 버그] "Curves에서 순서를 바꾸면 Marker도 같은
        # 순서로" - 위 수정은 클릭(선택)한 원래 순서만 따랐을 뿐, Curves
        # 팝업(Legend1)에서 ▲▼로 명시적으로 재배치한 순서(self._legend_order
        # ["1"] - _legend_ordered_keys 참고)는 반영하지 않았음. Legend1은
        # 기본으로 항상 전체 curve가 포함돼 있는 "주" legend이므로, 그 순서를
        # 기준으로 삼는다(아직 한 번도 안 바꿨으면 기존과 동일하게 클릭 순서
        # 그대로 - _legend_ordered_keys가 빈 리스트일 때 그렇게 처리함).
        _base_ordered_keys, _y1_set, _y2_set = self._ordered_selected_keys()
        _ordered_keys = self._legend_ordered_keys("1", _base_ordered_keys)
        any_added = False
        for key in _ordered_keys:
            any_added = True

            if key not in self.marker_shape_vars:
                self.marker_shape_vars[key] = tk.StringVar(value="None")
            if key not in self.marker_size_vars:
                self.marker_size_vars[key] = tk.StringVar(value="M")
            if key not in self.marker_maxcount_vars:
                self.marker_maxcount_vars[key] = tk.StringVar(value="")
            if key not in self.marker_fill_vars:
                self.marker_fill_vars[key] = tk.BooleanVar(value=False)
            # [추가 - 사용자 요청] Dat list에서 옮겨온 Color/Style - 보통
            # show_variables()가 먼저 이 key를 lazy-init해두지만, 방어적으로
            # 여기서도 동일하게 없으면 만든다(Marker 쪽 변수들과 같은 패턴).
            if key not in self.color_vars:
                self.color_vars[key] = tk.StringVar(value="Auto")
            if key not in self.linestyle_vars:
                self.linestyle_vars[key] = tk.StringVar(value="Auto")

            label = self.legend_vars[key].get() if key in self.legend_vars else key
            row_f = ttk.Frame(list_frame)
            row_f.pack(fill="x", pady=1)

            curve_cell = _cell(row_f, CURVE_PX)
            ttk.Label(curve_cell, text=label).pack(side="left")

            color_cell = _cell(row_f, COLOR_PX)
            color_combo = ttk.Combobox(color_cell, textvariable=self.color_vars[key],
                                        values=COLOR_LIST, state="readonly")
            color_combo.pack(side="left", fill="both", expand=True)
            self._disable_combobox_wheel(color_combo)

            style_cell = _cell(row_f, STYLE_PX)
            style_combo = ttk.Combobox(style_cell, textvariable=self.linestyle_vars[key],
                                        values=STYLE_LIST, state="readonly")
            style_combo.pack(side="left", fill="both", expand=True)
            self._disable_combobox_wheel(style_combo)

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

        # [추가 - 사용자 요청] "마커를 선택하면 auto로 순서대로 속빈 마커/
        # 다음 set은 속이찬 마커로 순서대로" - 여러 curve를 매번 손으로
        # 하나씩 고르지 않아도, 한 번 눌러서 Curve 순서(위 목록과 동일한
        # _ordered_keys)대로 서로 다른 모양을 자동 배정한다. 도형
        # 목록(None 제외)을 한 바퀴 돌 때는 속 빈(hollow) 버전을, 그
        # 다음(curve 수가 도형 수보다 많을 때) 바퀴는 같은 도형의 속 찬
        # (filled) 버전을 이어서 배정해 - 도형 수(None 제외 10개) x 2(빈/
        # 참) = 20개 조합을 다 쓸 때까지 최대한 서로 다르게 보이도록 한다.
        # 이미 골라둔 값이 있어도 항상 이 순서로 다시 채운다(예측 가능한
        # 한 번의 초기화 버튼).
        def _auto_assign_markers():
            shapes = [s for s in MARKER_SHAPE_LIST if s != "None"]
            n_shapes = len(shapes)
            if n_shapes == 0:
                return
            for i, key in enumerate(_ordered_keys):
                lap, shape_idx = divmod(i, n_shapes)
                self.marker_shape_vars[key].set(shapes[shape_idx])
                self.marker_fill_vars[key].set(bool(lap % 2 == 1))

        btn_row = ttk.Frame(popup)
        btn_row.pack(fill="x", padx=10, pady=8)
        ttk.Button(btn_row, text="완료", command=popup.destroy).pack(side="right")
        ttk.Button(btn_row, text="Auto(순서대로 배정)", command=_auto_assign_markers).pack(side="right", padx=(0, 6))

    # ------------------------------------------------------------------
    # Function Curve(2D) - 데이터 파일 없이 gnuplot 수식(삼각함수/다항식/
    # 사용자 정의 함수 등)을 그대로 하나의 curve로 추가한다. self.function_
    # curves_list에 tk.Var 기반 dict로 값을 보관해서, 팝업을 닫았다 다시
    # 열어도 입력한 내용이 유지된다(Comment/Arrow/Circle 목록과 동일한
    # 방식). Cubic Spline은 이 기능과 별개로 Var-list의 "SP" 체크박스로
    # 기존 데이터 curve에 적용한다(사용자 요청 - 입력칸을 새로 늘리지 않고
    # 기존 데이터 curve에 체크박스로 지정).
    # ------------------------------------------------------------------
    def _open_function_curves_popup(self):
        popup = tk.Toplevel(self.root)
        popup.title("Function Curves")
        popup.transient(self.root)

        EXPR_PX, TITLE_PX, AXIS_PX, COLOR_PX, STYLE_PX, LW_PX = 220, 110, 55, 75, 90, 55

        def _cell(parent, px, height=22):
            f = tk.Frame(parent, width=px, height=height)
            f.pack_propagate(False)
            f.pack(side="left")
            return f

        header_f = ttk.Frame(popup)
        header_f.pack(fill="x", padx=10, pady=(10, 2))
        ttk.Label(_cell(header_f, EXPR_PX), text="Expression (f(x))", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, TITLE_PX), text="Legend Title", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, AXIS_PX), text="Axis", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, COLOR_PX), text="Color", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, STYLE_PX), text="Style", font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Label(_cell(header_f, LW_PX), text="Width", font=("Consolas", 9, "bold")).pack(side="left")

        list_frame = ttk.Frame(popup)
        list_frame.pack(fill="both", expand=True, padx=10)
        self._func_curve_col_px = (EXPR_PX, TITLE_PX, AXIS_PX, COLOR_PX, STYLE_PX, LW_PX)

        if not self.function_curves_list:
            self.add_function_curve_row()
        for data in self.function_curves_list:
            self._build_function_curve_row_widgets(list_frame, data)

        add_row = ttk.Frame(popup)
        add_row.pack(fill="x", padx=10, pady=(4, 0))
        ttk.Button(add_row, text="+ 추가",
                   command=lambda: self._build_function_curve_row_widgets(
                       list_frame, self.add_function_curve_row())).pack(side="left")

        ttk.Label(
            popup,
            text="예: sin(x), 2*x**2+3*x+1, exp(-x)*cos(2*x) - gnuplot 내장 함수/식을 그대로 입력 (x의 함수).",
            foreground="#555555"
        ).pack(padx=10, pady=(6, 0), anchor="w")

        btn_row = ttk.Frame(popup)
        btn_row.pack(fill="x", padx=10, pady=8)
        ttk.Button(btn_row, text="완료", command=popup.destroy).pack(side="right")

    def add_function_curve_row(self, initial=None):
        """function_curves_list에 tk.Var 기반 행 데이터를 하나 추가하고 반환한다
        (위젯은 별도로 _build_function_curve_row_widgets가 만든다 - Template
        Load처럼 화면이 아직 없는 시점에도 데이터만 먼저 채울 수 있도록 분리)."""
        init = initial or {}
        data = {
            'expression': tk.StringVar(value=init.get('expression', "")),
            'title': tk.StringVar(value=init.get('title', "")),
            'axis': tk.StringVar(value=init.get('axis', "y1")),
            'color': tk.StringVar(value=init.get('color', "Auto")),
            'linestyle': tk.StringVar(value=init.get('linestyle', "Auto")),
            'linewidth': tk.StringVar(value=init.get('linewidth', "1.5")),
            'frame': None,
        }
        self.function_curves_list.append(data)
        return data

    def _build_function_curve_row_widgets(self, list_frame, data):
        EXPR_PX, TITLE_PX, AXIS_PX, COLOR_PX, STYLE_PX, LW_PX = self._func_curve_col_px

        def _cell(parent, px, height=22):
            f = tk.Frame(parent, width=px, height=height)
            f.pack_propagate(False)
            f.pack(side="left")
            return f

        row_f = ttk.Frame(list_frame)
        row_f.pack(fill="x", pady=1)
        data['frame'] = row_f

        ttk.Entry(_cell(row_f, EXPR_PX), textvariable=data['expression']).pack(side="left", fill="both", expand=True)
        ttk.Entry(_cell(row_f, TITLE_PX), textvariable=data['title']).pack(side="left", fill="both", expand=True)
        axis_combo = ttk.Combobox(_cell(row_f, AXIS_PX), textvariable=data['axis'],
                                   values=["y1", "y2"], state="readonly")
        axis_combo.pack(side="left", fill="both", expand=True)
        self._disable_combobox_wheel(axis_combo)
        color_combo = ttk.Combobox(_cell(row_f, COLOR_PX), textvariable=data['color'],
                                    values=COLOR_LIST, state="readonly")
        color_combo.pack(side="left", fill="both", expand=True)
        self._disable_combobox_wheel(color_combo)
        style_combo = ttk.Combobox(_cell(row_f, STYLE_PX), textvariable=data['linestyle'],
                                    values=STYLE_LIST, state="readonly")
        style_combo.pack(side="left", fill="both", expand=True)
        self._disable_combobox_wheel(style_combo)
        ttk.Entry(_cell(row_f, LW_PX), textvariable=data['linewidth']).pack(side="left", fill="both", expand=True)
        ttk.Button(row_f, text="X", width=3, style="Compact.TButton",
                   command=lambda: self._remove_function_curve_row(row_f)).pack(side="left", padx=(5, 0))

    def _remove_function_curve_row(self, row_f):
        row_f.destroy()
        for item in self.function_curves_list:
            if item['frame'] == row_f:
                self.function_curves_list.remove(item)
                break
        if not self.function_curves_list:
            self._build_function_curve_row_widgets(row_f.master, self.add_function_curve_row())

    def _build_function_curve_defs(self):
        """self.function_curves_list(tk.Var 기반) -> FunctionCurveDefinition 목록.
        Expression이 비어있는 행은 건너뛴다(빈 채로 팝업만 열어본 경우 대비)."""
        result = []
        for data in self.function_curves_list:
            expr = data['expression'].get().strip()
            if not expr:
                continue
            result.append(FunctionCurveDefinition(
                expression=expr,
                title=data['title'].get().strip() or expr,
                axis=data['axis'].get() or "y1",
                color=COLOR_MAP.get(data['color'].get(), None) or None,
                linestyle=STYLE_MAP.get(data['linestyle'].get(), None) or None,
                linewidth=float(data['linewidth'].get() or 1.5),
            ))
        return result

    def _function_curves_to_json(self):
        """Template Save용 - tk.Var 기반 목록을 순수 dict 목록으로 변환."""
        result = []
        for data in self.function_curves_list:
            expr = data['expression'].get().strip()
            if not expr:
                continue
            result.append({
                "expression": expr,
                "title": data['title'].get(),
                "axis": data['axis'].get(),
                "color": data['color'].get(),
                "linestyle": data['linestyle'].get(),
                "linewidth": data['linewidth'].get(),
            })
        return result

    @staticmethod
    def _function_curves_from_json(items):
        """Template Load용 - 순수 dict 목록 -> FunctionCurveDefinition 목록
        (화면 tk 변수를 전혀 건드리지 않으므로 백그라운드 스레드에서도 안전 -
        Batch Set이 _build_plotdef_from_template_data에서 사용)."""
        result = []
        for item in items or []:
            expr = str(item.get("expression", "")).strip()
            if not expr:
                continue
            result.append(FunctionCurveDefinition(
                expression=expr,
                title=item.get("title") or expr,
                axis=item.get("axis", "y1") or "y1",
                color=COLOR_MAP.get(item.get("color", "Auto"), None) or None,
                linestyle=STYLE_MAP.get(item.get("linestyle", "Auto"), None) or None,
                linewidth=float(item.get("linewidth") or 1.5),
            ))
        return result

    def _legend_ordered_keys(self, legend_key, base_keys):
        """[추가 - 사용자 보고 버그] "Legend1/Legend2 순서 독립적으로" -
        base_keys(보통 _ordered_selected_keys()가 반환하는 전체 클릭 순서)를
        legend_key("1"/"2")별 독립 순서(self._legend_order[legend_key])로
        다시 정렬한다. 그 Legend에서 아직 한 번도 순서를 안 바꿨으면(리스트가
        비어있으면) base_keys 순서를 그대로 기본값으로 써서(기존 동작과
        동일한 첫인상), 리스트에 아직 없는 키(새로 선택된 curve 등)는 원래
        자리 그대로 뒤에 이어붙인다."""
        order = self._legend_order.get(legend_key) or []
        if not order:
            return list(base_keys)
        base_set = set(base_keys)
        ordered = [k for k in order if k in base_set]
        ordered += [k for k in base_keys if k not in ordered]
        return ordered

    def _open_curve_select_popup(self, anchor_widget, title, get_checked, set_checked, legend_key):
        """Legend1/Legend2 공용 curve 선택 팝업. get_checked(key)/set_checked(key, bool)로
        체크 상태를 읽고 쓴다 - Legend1은 in_legend1_vars(bool), Legend2는
        legend_group_vars(문자열 "1"/"2")를 각각 다르게 저장하지만 이 함수는
        그 차이를 신경 안 쓰고 동일하게 다룬다. tk.Menu와 달리 항목을 체크해도
        창이 안 닫혀서 여러 개를 한 번에 고를 수 있다.

        [추가 - 요청] "선택한 순서대로 curve를 그려주기 - curves 선택 창에서도
        바꿀 수 있게" - 이 팝업이 지금 Y1/Y2로 선택된 모든 curve를 한 곳에
        모아 보여주는 건 Legend1/Legend2 어느 쪽에서 열어도 동일하지만, [수정
        - 사용자 보고 버그] "Legend1에서 순서를 바꾸면 Legend2도 같이 바뀜 -
        각각 독립적으로" - 순서 자체(각 줄의 ▲▼로 옮기는 것)는 legend_key
        ("1"=Legend1, "2"=Legend2)로 구분된 self._legend_order[legend_key]를
        따로 건드리도록 바꿔, 한쪽에서 순서를 바꿔도 다른 쪽은 그대로다."""
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.transient(self.root)
        x = anchor_widget.winfo_rootx()
        y = anchor_widget.winfo_rooty() + anchor_widget.winfo_height()
        popup.geometry(f"+{x}+{y}")

        list_frame = ttk.Frame(popup)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        _base_keys, _y1_set, _y2_set = self._ordered_selected_keys()
        keys = self._legend_ordered_keys(legend_key, _base_keys)

        def _reopen():
            popup.destroy()
            self._open_curve_select_popup(anchor_widget, title, get_checked, set_checked, legend_key)

        def _move(key, delta):
            lst = self._legend_order.get(legend_key) or []
            if key not in lst:
                # 트래킹 안 된 키(프로그램적 선택 등 - 안전망): 지금 표시
                # 순서를 그대로 기준선으로 등록한 뒤 옮긴다.
                lst = list(keys)
            self._legend_order[legend_key] = lst
            i = lst.index(key)
            j = i + delta
            if 0 <= j < len(lst):
                lst[i], lst[j] = lst[j], lst[i]
            _reopen()

        if not keys:
            ttk.Label(list_frame, text="(선택된 Y1/Y2 변수 없음)").pack(padx=5, pady=10)
        else:
            for idx, key in enumerate(keys):
                label = self.legend_vars[key].get() if key in self.legend_vars else key
                check_var = tk.BooleanVar(value=get_checked(key))

                def _toggle(cv=check_var, k=key):
                    set_checked(k, cv.get())

                row = ttk.Frame(list_frame)
                row.pack(fill="x", anchor="w")
                ttk.Label(row, text=f"{idx + 1}.", width=3, anchor="e").pack(side="left")
                self._mk_check(row, label, check_var, command=_toggle, anchor="w", pady=1, side="left")
                self._mk_btn(row, "▲", lambda k=key: _move(k, -1), color="grey", btn_width=2, side="left", padx=(6, 1))
                self._mk_btn(row, "▼", lambda k=key: _move(k, 1), color="grey", btn_width=2, side="left", padx=1)

        def select_all():
            for key in keys:
                set_checked(key, True)
            _reopen()

        def select_none():
            for key in keys:
                set_checked(key, False)
            _reopen()

        btn_row = ttk.Frame(popup)
        btn_row.pack(fill="x", padx=10, pady=8)
        ttk.Button(btn_row, text="전체 선택", command=select_all).pack(side="left", padx=(0, 5))
        ttk.Button(btn_row, text="전체 해제", command=select_none).pack(side="left")
        ttk.Button(btn_row, text="닫기", command=popup.destroy).pack(side="right")

    def open_batch_queue_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Batch Queue - 여러 파일 자동 처리")
        # [수정 - 버그] Batch Set과 같은 원인(transient 누락 + 내부 파일
        # 선택창에 parent 누락)으로 "Add Files... 누르면 이 창이 메인 창
        # 뒤로 숨음"이 여기서도 재현될 수 있어 미리 같이 고침.
        dlg.transient(self.root)
        dlg.geometry("640x420")

        ttk.Label(
            dlg,
            text="지금 화면에서 선택된 Y1/Y2/X (var_no 기준)와 스타일이 아래 파일들에 그대로 적용됩니다.\n"
                 "경로는 CathPlot 실행 폴더 기준 상대경로로 표시됩니다.\n"
                 "팁: 먼저 'Template Load...'로 스타일을 불러온 뒤 Run Batch 하면 그 스타일 그대로 적용됩니다.",
            justify="left"
        ).pack(fill="x", padx=10, pady=(10, 5))

        queue_list = []
        # [수정 - 사용자 요청] "여러 파일을 한번에 선택되게(ctrl+click,
        # shift+click), Add Template의 입력 선택창처럼" - 기본
        # selectmode("browse")는 한 번에 하나만 선택되는데, "extended"로
        # 바꾸면 탐색기/파일 선택 대화상자와 같은 방식으로 Shift(범위)/
        # Ctrl(개별 추가)로 여러 줄을 한 번에 선택할 수 있다.
        listbox = tk.Listbox(dlg, width=90, height=14, selectmode="extended")
        listbox.pack(fill="both", expand=True, padx=10, pady=5)

        def add_files():
            paths = filedialog.askopenfilenames(
                parent=dlg, initialdir=self.cwd,
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
        # [수정 - 버그] 이 창의 ttk.Button 3개는 이 PC의 Windows 테마에서
        # 안의 글자가 아예 안 보이거나 깨지는 렌더링 버그가 있었음(실제 화면
        # 캡처+픽셀 분석으로 확인 - style padding, pack ipady 둘 다 시도했지만
        # 원인이 아니었고, ttk.Button 자체가 문제였음. 같은 텍스트/같은 앱
        # 안에서도 Batch Set 창은 멀쩡해서 재현 조건은 못 찾음). 이미 이
        # 코드베이스에 있는 검증된 우회책(_mk_btn, tk.Button 기반 - "ttk.Button은
        # 배경색이 잘 안 먹는 환경이 확인돼서"와 같은 계열의 문제)으로 교체 -
        # 실제 화면 캡처로 글자가 정상적으로 보이는 것까지 확인함.
        self._mk_btn(btn_row, "+ Add Files...", add_files, color="grey", btn_pady=0, side="left", padx=5)
        self._mk_btn(btn_row, "Remove Selected", remove_selected, color="grey", btn_pady=0, side="left", padx=5)
        self._mk_btn(btn_row, "Template Load", self.load_template, color="grey", btn_pady=0, side="left", padx=5)

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
        self._mk_btn(run_row, "취소", dlg.destroy, color="danger", btn_pady=0, side="right", padx=5)
        self._mk_btn(run_row, "Run Batch", run_batch, color="accent", btn_pady=0, side="right", padx=5)

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
            "y2tics_on": self.y2tics_on_var.get(), "ytics_on": self.ytics_on_var.get(),
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

        try:
            _orig_rel = os.path.relpath(abs_path, self.cwd)
        except ValueError:
            _orig_rel = abs_path

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
                    smooth_csplines=item.get("smooth_csplines", False),
                    orig_dat_file=_orig_rel,
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
            y2tics_on=settings.get("y2tics_on", True), ytics_on=settings.get("ytics_on", True),
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

        # [수정 - 사용자 보고 버그] Batch Set과 동일한 이유 - Axis Frame
        # Auto면 execute_plot_pipeline과 같은 기준(10x8cm)으로 확정해서
        # Auto의 "11.7x8.3in 인쇄 페이지" 가정 때문에 폰트가 상대적으로
        # 작아 보이는 문제를 막는다.
        if plotdef.frame_auto:
            plotdef.frame_auto = False
            plotdef.frame_width, plotdef.frame_height = self._compute_auto_frame_size_cm(for_print=True)
            plotdef.frame_unit = "cm"

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
        job_id = self._register_batch_job("Batch Queue", len(relative_paths))

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
            try:
                self._run_batch_queue(relative_paths, fmt, settings, progress_callback=progress_callback)
            finally:
                # [추가 - 요청] Batch Set과 동일하게, 완료(성공/오류 무관) 시
                # 실행 중 목록에서 제거 - 반드시 메인 스레드에서.
                self.root.after(0, lambda: self._unregister_batch_job(job_id))
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

        # [수정 - 사용자 요청] "Dat files 항목의 Browse 입력칸을 지금의
        # 2배로 길게" - 60 -> 120으로 늘렸던 건 그때 절대경로 전체가 표시돼
        # 너무 길어서(알아보기 어려움)였는데, 이제 화면 표시를 cwd 기준
        # 상대경로로 바꿔(_display_relpath 참고) 훨씬 짧아짐 - 120은 과하고
        # (자리만 차지) 원래 값(60)은 다소 좁을 수 있어, 그 중간인 80으로.
        dat_path_entry = ttk.Entry(row, textvariable=var, width=80)
        dat_path_entry.pack(side="left", padx=5)
        # [추가 - 사용자 요청] "Browse 칸에 직접 타이핑해서 다른 폴더의
        # 파일로 바꿀 수 있나?" - Enter를 누르거나 이 칸에서 포커스가
        # 벗어나는 시점에 한해 적용(매 키 입력마다 파일을 다시 읽으려 하면
        # 타이핑 중간에 계속 "파일 없음" 경고가 뜨므로 곤란함).
        dat_path_entry.bind("<Return>", lambda e, v=var, r_info=info: self._on_dat_entry_typed(e, v, r_info, silent=False))
        dat_path_entry.bind("<FocusOut>", lambda e, v=var, r_info=info: self._on_dat_entry_typed(e, v, r_info, silent=True))
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
        # [추가 - 요청] "선택한 순서대로 curve 그리기" 목록에도 이 파일의
        # key가 남아있으면(파일 교체/삭제 후에도 순서 목록엔 낡은 키가 계속
        # 남아있던 문제) 같이 정리한다.
        self._curve_order = [k for k in self._curve_order if not k.startswith(prefix)]

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
        self._apply_selected_dat_file(var, r_info, filename)

    def _apply_selected_dat_file(self, var, r_info, filename):
        """[추가 - 요청 리팩터] load_dat_file(Browse 대화상자)과 아래
        _on_dat_entry_typed(직접 타이핑) 둘 다 "파일이 하나 정해졌을 때
        그 뒤에 할 일"(파서 실행/JSON 저장/변수 UI 갱신 등)은 완전히
        같아서, 그 공통 부분만 뽑아낸 것 - filename은 항상 절대경로여야
        한다(호출부 책임)."""
        datfile = r_info["filename"]
        prefix = f"{datfile}||"

        self._purge_file_vars(datfile)

        # 파일별 X축 변수 초기화
        if r_info["x_var"].get().startswith(prefix):
            r_info["x_var"].set("")

        var.set(self._display_relpath(filename))
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

    def _on_dat_entry_typed(self, event, var, r_info, silent=False):
        """[추가 - 사용자 요청] "Browse 칸에 직접 타이핑해서 다른 폴더의
        파일로 바꿀 수 있나?" - 원래 설명서에는 "직접 타이핑 가능"이라
        적혀 있었지만 실제로는 표시 전용이었던 것을 이번에 발견(정정)했는데,
        Browse/Template Load가 기본이고 이건 필요할 때만 쓰는 보조 수단이라는
        전제로, 아예 안 되는 것보다는 실제로 되게 해달라는 요청 - Enter(또는
        포커스가 벗어날 때)에 한해 지금 칸에 적힌 텍스트를 실제 경로로
        적용한다. 상대경로(현재 화면에 보이는 형식 그대로 - cwd 기준)와
        절대경로 둘 다 입력 가능. [주의] Enter(silent=False)는 실패 시 경고
        팝업을 띄우지만, 포커스 이탈(silent=True)은 조용히 원래 표시로만
        되돌린다 - 그래야 Browse 버튼을 누를 때(버튼 클릭 자체가 먼저
        FocusOut을 일으킴) 입력 중이던 텍스트 때문에 불필요한 경고가 먼저
        뜨는 걸 피할 수 있다."""
        raw = var.get().strip()
        if not raw:
            # 빈 칸으로 지운 것은 "취소"로 보고 원래 표시로 되돌린다.
            var.set(self._display_relpath(r_info["filename"]) if r_info.get("filename") else "")
            return
        candidate = raw if os.path.isabs(raw) else os.path.join(self.cwd, raw)
        candidate = os.path.abspath(candidate)
        if not os.path.isfile(candidate):
            if not silent:
                messagebox.showwarning("파일 없음", f"경로를 찾을 수 없습니다:\n{candidate}\n\n(cwd 기준 상대경로 또는 절대경로를 입력해 주세요)")
            var.set(self._display_relpath(r_info["filename"]) if r_info.get("filename") else "")
            return
        if os.path.abspath(candidate) == os.path.abspath(r_info.get("filename") or ""):
            # 실제로 안 바뀌었으면(표시만 다시 정리) 그대로 재적용할 필요 없음.
            var.set(self._display_relpath(candidate))
            return
        try:
            self._apply_selected_dat_file(var, r_info, candidate)
        except Exception as e:
            if not silent:
                messagebox.showerror("파일 읽기 실패", f"'{candidate}' 파일을 읽는 중 오류가 발생했습니다:\n{e}")
            var.set(self._display_relpath(r_info["filename"]) if r_info.get("filename") else "")

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
        else:
            base_name = "CathPlot"
        # [수정 - 사용자 보고 버그] "Axis Title처럼, 사용자가 입력한 경우
        # Plot Title도 계속 사용하게 해 줘요. 지금은 Dat File명으로 바뀜" -
        # 지금까지는 파일이 바뀔 때마다 Plot Title을 무조건 새 파일명으로
        # 덮어써서, 사용자가 직접 고친 제목도 파일을 추가/삭제/재선택할
        # 때마다 사라졌음. X/Y1/Y2 축 제목과 같은 규칙(칸이 비어있을 때만
        # 자동으로 파일명을 따라가고, 사용자가 뭔가 입력해두면 그 값을
        # 유지)을 Plot Title에도 적용한다. filename_var(저장 파일명
        # 기본값)는 기존처럼 항상 최신 파일명을 따라간다(제목과 별개로,
        # 저장할 때 파일명 제안 용도라 계속 최신이 유용함).
        self.filename_var.set(base_name)
        if self.plot_title_auto:
            self._updating_title = True
            self.title_var.set(base_name)
            self._updating_title = False

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
        # [수정 - 사용자 보고 버그] "행을 추가했다가 지우면 첫 줄 다음에 빈
        # 줄이 남는다(2줄 이상 추가한 뒤 지우면 한 줄 빼고 다 지워진 것처럼
        # 보임)" - pack 기반 destroy() 자체는 위젯 트리/목록에서 정확히
        # 제거되지만(Xvfb 헤드리스로 첫/중간/마지막 줄 삭제, 5~7줄에서
        # 연속 삭제까지 재현해봐도 목록 개수·위치는 항상 정상이었음 -
        # 이 로직 자체의 버그는 아님), Windows Tk가 중첩된 canvas/frame
        # 구조에서 destroy() 직후 화면을 즉시 다시 그리지 않고 남겨두는
        # (다음 이벤트가 올 때까지 미뤄지는) 경우가 있어 그 사이 예전
        # 픽셀이 남아있는 것으로 보인다. destroy 직후 명시적으로
        # update_idletasks()를 불러 갱신을 강제한다(값싸고 안전한 조치 -
        # 이 자체가 원인이 아니었더라도 부작용 없음).
        parent = frame.master
        frame.destroy()
        parent.update_idletasks()
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
        # anno_frame(Multi Annotations)이 plot_canvas 안에 있어, 내용이
        # 줄어들면 그 canvas의 scrollregion도 즉시 다시 계산되게 한다
        # (plot_frame의 <Configure> 바인딩에 맡기면 Windows에서 타이밍이
        # 밀릴 수 있어 여기서도 한 번 더 직접 강제).
        if hasattr(self, "plot_canvas"):
            self.plot_canvas.configure(scrollregion=self.plot_canvas.bbox("all"))

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
                    # [추가 - 요청] Clear All은 y_excl_handler(클릭 핸들러)를
                    # 거치지 않고 직접 .set(False)를 호출하므로, 선택 순서
                    # 목록에서도 여기서 같이 빼줘야 함(안 빼면 이미 지워진
                    # curve의 낡은 키가 순서 목록에 계속 남아있게 됨).
                    if k in self._curve_order:
                        self._curve_order.remove(k)
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
            # [수정 - 요청] "X radio, Y1, Y2 체크박스 사이의 간격을 0으로" -
            # 칸 폭 자체가 체크박스/라디오 실제 크기(19px)보다 넉넉해서 그
            # 여백만큼 옆 칸과 떨어져 보였음 - 체크박스 크기에 거의 딱
            # 맞는 폭으로 줄여 간격을 최소화(라디오 indicator가 체크박스
            # 이미지보다 살짝 작아 X_COL_PX는 조금 더 좁혀도 안전).
            X_COL_PX = 20
            Y1_COL_PX = 22
            Y2_COL_PX = 22
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
            # [수정 - 사용자 요청] "Color/Style은 선택된 curve에만 의미가
            # 있으니 Dat list가 아니라 Marker처럼 팝업에서 고르는 게 더
            # 깔끔함, 가로 공간도 확보" - 이 Dat list의 인라인 Color/Style
            # Combobox(및 헤더)를 제거하고, "Curve" 팝업(옛 Marker 팝업,
            # _open_curve_settings_popup)에 Color/Style 컬럼을 새로 추가해
            # 그쪽으로 통합했다. self.color_vars/self.linestyle_vars 상태
            # 자체(아래 key_str 루프의 lazy-init)는 그대로 유지 - plot 생성/
            # 템플릿 저장 코드가 이 dict를 그대로 읽으므로 값 저장 방식은
            # 변경 없음.
            # [추가 - 요청] "Cubic Spline" 체크박스 열 - Y1/Y2와 같은 좁은
            # 폭으로 맨 뒤에 붙인다(새 필드를 위한 넓은 칸을 새로 만들 자리가
            #없다는 요청 그대로 - 짧은 헤더 "SP"만, 원래 "Spl"에서 변경).
            # [수정 - 요청] "SP box 뒤 여분을 0으로" - Y1/Y2와 동일 폭으로
            # 맞춰 여백 없이 통일.
            # [수정 - 사용자 요청] "SP는 뜻이 애매하니 SPL 등으로" - "SP"만
            # 으론 무슨 뜻인지 안 보여서 "SPL"로 되돌림(그 전엔 "Spl"이었다가
            # 폭 절감 때문에 "SP"로 줄였던 이력 - 이번엔 폭 절감보다 의미
            # 전달이 우선이라는 요청). 글자 수가 늘어(2자->3자) Y1/Y2와
            # 같은 22px 폭으로는 잘려서, 이 칸만 살짝 넓힌다(22->30, 실측
            # 확인 - "SPL" 자체 폭 24px + 아래 체크박스 정렬용 nudge(-4px)
            # 감안하면 26px는 왼쪽이 살짝 잘림).
            SMOOTH_COL_PX = 30
            smooth_hdr_f = tk.Frame(header_f, width=SMOOTH_COL_PX, height=22)
            smooth_hdr_f.pack_propagate(False)
            smooth_hdr_f.pack(side="left")
            # [수정] _HDR_NUDGE_PX(-4)는 X/Y1/Y2/SP처럼 1~2글자 라벨을 그
            # 아래 체크박스 indicator와 맞추기 위한 보정값인데, "SPL"(3글자)
            # 에 그대로 쓰면 폭이 넓어져(실측 26px) 30px 칸 왼쪽으로 살짝
            # (2px) 잘려 나감 - 체크박스와의 완벽한 정렬보다 글자가 안
            # 잘리는 게 우선이라 이 라벨만 nudge 없이(x=0) 중앙 정렬한다.
            ttk.Label(smooth_hdr_f, text="SPL", font=("Consolas", 10, "bold")).place(relx=0.5, rely=0.5, anchor="center")

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
                if key_str not in self.smooth_csplines_vars:
                    self.smooth_csplines_vars[key_str] = tk.BooleanVar(value=False)

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
                        # [수정 - 버그] "Axis title이 클릭 순서를 따르게" 했더니,
                        # sync_axis_labels가 _touch_curve_order보다 먼저 호출돼
                        # 방금 클릭한 키가 아직 _curve_order에 안 들어간 상태로
                        # (안전망으로 맨 뒤 취급) axis title을 계산해서, 한 번
                        # 늦게(다음 클릭에서야) 반영되는 문제가 있었음 - 순서를
                        # 바꿔 _curve_order부터 갱신한 뒤 axis title을 계산한다.
                        self._touch_curve_order(target_key)
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

                smooth_cell_f = tk.Frame(row_frame, width=SMOOTH_COL_PX, height=22)
                smooth_cell_f.pack_propagate(False)
                smooth_cell_f.pack(side="left")
                c_smooth = self._mk_check(smooth_cell_f, "", self.smooth_csplines_vars[key_str], size=19, no_pack=True)
                c_smooth.place(relx=0.5, rely=0.5, anchor="center")

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

    def on_plot_title_changed(self, *args):
        if self._updating_title: return
        self.plot_title_auto = (self.title_var.get().strip() == "")

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

        # [수정 - 요청] "Axis title도 curve 순서에 연동?" - 예전엔 selected_y1_
        # vars/selected_y2_vars 딕셔너리 순서(=표에 나열된 순서)의 "첫 번째"를
        # 그대로 썼는데, 이제 클릭(선택)한 순서(_ordered_selected_keys)의
        # "첫 번째"를 따르도록 통일 - curve 그리기/legend 순서와 항상 같은
        # 기준을 쓰게 됨.
        _ordered_keys, _y1_set, _y2_set = self._ordered_selected_keys()
        y1_selected = [self.legend_vars[k].get() for k in _ordered_keys if k in _y1_set]
        y2_selected = [self.legend_vars[k].get() for k in _ordered_keys if k in _y2_set]

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
        if not messagebox.askyesno("확인", "이전 임시 plot 파일과 캐시를 모두 정리하시겠습니까?"):
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
            messagebox.showinfo("완료", "이전 임시 파일과 캐시를 정리했습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"이전 plot 정리 실패: {e}")

    # [삭제 - 죽은 코드] clear_all_plots/reset_history - grep 결과 이 파일 안에
    # 호출부(버튼/메뉴)가 전혀 없어(0 call sites) 화면 어디서도 실행될 수
    # 없었음. 실제로 쓰이는 "전체 초기화"는 clean_past_plots 하나뿐이라,
    # 이 둘은 clean_past_plots와 거의 같은 내용을 중복 구현한 채 방치돼
    # 있었을 뿐(git 히스토리에 남아있으니 필요하면 복원 가능).

    def _collect_annotations(self):
        # [수정 - 요청] "Enable Comments 체크박스가 꼭 필요한지 - 3D처럼 입력
        # 있으면 자동으로 켜지고 없으면 자동으로 꺼지는 게 낫지 않은지" -
        # 확인해보니 아래 루프가 이미 빈 줄(text/x/y 중 하나라도 없음)을
        # 항상 걸러내고 있어서, 이 체크박스는 "내용을 채워놓고도 체크를 깜빡
        # 잊으면 아무것도 안 보이는" 혼란만 주는 중복 게이트였음(3D의 주석
        # 목록은 애초에 이런 별도 체크박스가 없음) - 게이트를 없애고 내용
        # 유무로만 판단하게 통일.
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
        # [수정 - 요청] _collect_annotations와 동일한 이유로 게이트 제거 -
        # 아래 루프가 이미 빈 줄을 걸러냄.
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
        # [수정 - 요청] _collect_annotations와 동일한 이유로 게이트 제거 -
        # 아래 루프가 이미 빈 줄을 걸러냄.
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
    def _ordered_outs_for_file(self, d_file, out_nos):
        """[추가 - 사용자 요청] "한 파일에서 y,z값을 따로 줄 수는 없나(여러
        set)" - out_nos(해당 파일에서 선택된 output_no 목록)를 사용자가 클릭한
        순서(self._curve_order) 기준으로 정렬해 돌려준다("기본은 순서쌍으로"
        짝짓기의 기준). _curve_order에 없는 항목(예: Template Load로 클릭 없이
        복원된 경우)은 뒤에 번호 순으로 덧붙인다(그래도 뭔가는 나오게 하는
        방어적 처리)."""
        key_set = {f"{d_file}||{n}" for n in out_nos}
        ordered = [int(k.split("||")[1]) for k in self._curve_order if k in key_set]
        remaining = sorted(n for n in out_nos if n not in ordered)
        return ordered + remaining

    def _var_display_name(self, d_file, out_no):
        """[추가] 짝 맞추기 팝업 등에서 output_no만 보여주면 어떤 변수인지 알기
        어려우니, legend_vars에 저장된 실제 변수명을 같이 보여주기 위한 헬퍼."""
        key = f"{d_file}||{out_no}"
        if key in self.legend_vars:
            v = self.legend_vars[key].get()
            if v:
                return v
        return f"var_{out_no}"

    def _resolve_3d_pair_dialog(self, item):
        """[추가 - 사용자 요청] "3D에서 한 파일에서 y,z값을 따로 줄 수는
        없나(여러 set)... 기본은 순서쌍으로 하고 선택변수 쌍이 안맞으면 경고내고
        선택하게(아님 취소 가능하게)... 기본 쌍도 사용자가 바꿀 수 있게" - 한
        dat 파일에 Y1/Y2가 여러 개 선택돼(1:1이 아니어서) 자동으로 전부 짝지을
        수 없거나, 짝지을 수는 있어도(개수가 같아) 사용자가 확인/변경할 기회가
        필요한 경우에 뜨는 보조 팝업. 왼쪽에서 Y1 후보, 오른쪽에서 Y2 후보를
        하나씩 골라 "짝 추가"하는 선택 방식(숫자를 직접 타이핑하지 않음)이고,
        기본값으로 클릭 순서 기준 짝(item["default_pairs"])을 미리 채워둔다.
        "이 파일 제외"를 누르면 그 파일 전체를 3D에서 뺀다(빈 리스트 반환)."""
        d_file = item["d_file"]
        y1_candidates = item["y1_candidates"]
        y2_candidates = item["y2_candidates"]
        result = {"pairs": list(item["default_pairs"])}

        dlg = tk.Toplevel(self.root)
        dlg.configure(bg=self.PALETTE["bg"])
        dlg.title(f"3D Plot - Y1/Y2 짝 맞추기: {item['label']}")
        dlg.transient(self.root)
        dlg.grab_set()

        msg = f"'{item['label']}' 파일에 Y1 {len(y1_candidates)}개, Y2 {len(y2_candidates)}개가 선택돼 있습니다."
        if item.get("mismatched"):
            msg += "\n개수가 서로 달라 자동으로 전부 짝지을 수 없습니다 - 아래에서 직접 짝을 맞춰주세요."
        else:
            msg += "\n기본값(선택한 순서대로 짝지음)이 아래에 채워져 있습니다 - 필요하면 바꾸세요."
        ttk.Label(dlg, text=msg, wraplength=440, justify="left").pack(padx=10, pady=(10, 6), anchor="w")

        body = ttk.Frame(dlg)
        body.pack(fill="both", expand=True, padx=10)

        y1_frame = ttk.LabelFrame(body, text="Y1 후보")
        y1_frame.pack(side="left", fill="y", padx=(0, 5))
        y1_list = tk.Listbox(y1_frame, height=8, exportselection=False, width=20)
        for no in y1_candidates:
            y1_list.insert("end", f"{no}: {self._var_display_name(d_file, no)}")
        y1_list.pack(padx=4, pady=4)

        y2_frame = ttk.LabelFrame(body, text="Y2 후보")
        y2_frame.pack(side="left", fill="y", padx=5)
        y2_list = tk.Listbox(y2_frame, height=8, exportselection=False, width=20)
        for no in y2_candidates:
            y2_list.insert("end", f"{no}: {self._var_display_name(d_file, no)}")
        y2_list.pack(padx=4, pady=4)

        pair_frame = ttk.LabelFrame(body, text="확정된 짝 (3D curve 목록)")
        pair_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))
        pair_list = tk.Listbox(pair_frame, height=8, exportselection=False, width=32)
        pair_list.pack(padx=4, pady=4, fill="both", expand=True)

        def _refresh_pairs():
            pair_list.delete(0, "end")
            for y1_no, y2_no in result["pairs"]:
                pair_list.insert(
                    "end",
                    f"Y={y1_no}({self._var_display_name(d_file, y1_no)})  <->  "
                    f"Z={y2_no}({self._var_display_name(d_file, y2_no)})"
                )
        _refresh_pairs()

        btn_row = ttk.Frame(pair_frame)
        btn_row.pack(fill="x", padx=4, pady=(0, 4))

        def add_pair():
            s1 = y1_list.curselection()
            s2 = y2_list.curselection()
            if not s1 or not s2:
                messagebox.showwarning("3D Plot", "Y1, Y2 후보를 각각 하나씩 선택하세요.")
                return
            result["pairs"].append((y1_candidates[s1[0]], y2_candidates[s2[0]]))
            _refresh_pairs()

        def remove_pair():
            s = pair_list.curselection()
            if not s:
                return
            del result["pairs"][s[0]]
            _refresh_pairs()

        ttk.Button(btn_row, text="짝 추가 →", command=add_pair).pack(side="left", padx=2)
        ttk.Button(btn_row, text="선택 삭제", command=remove_pair).pack(side="left", padx=2)

        bottom = ttk.Frame(dlg)
        bottom.pack(fill="x", padx=10, pady=10)

        def _ok():
            dlg.destroy()

        def _exclude():
            result["pairs"] = []
            dlg.destroy()

        ttk.Button(bottom, text="이 파일 제외", command=_exclude).pack(side="left")
        ttk.Button(bottom, text="확인", command=_ok).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", _exclude)
        self.root.wait_window(dlg)
        return result["pairs"]

    def _collect_3d_curves(self, manual_pairs=None):
        """[추가] 3D Plot - "X,Y1,Y2 -> X,Y,Z로 매핑, 여러 세트(파일)를 같은
        화면에". 파일당 Y1/Y2가 정확히 1개씩이면 그대로 3D curve 하나가 되고,
        [수정 - 사용자 요청] "한 파일에서 y,z값을 따로 줄 수는 없나(set로 여러
        개)" - 한 파일에 Y1/Y2가 여러 개 선택돼 있어도(개수가 같든 다르든) 그
        조합만큼 여러 3D curve를 만들 수 있다. 어떤 Y1과 어떤 Y2를 짝지을지는
        이 함수가 직접 정하지 않고(모호함), 해당 파일들을 ambiguous로 돌려줘서
        호출부(open_3d_plot_dialog)가 _resolve_3d_pair_dialog로 사용자에게
        확인/지정하게 한 뒤, 그 결과(manual_pairs: {d_file: [(y1_out, y2_out),
        ...]})를 가지고 다시 호출하면 그 지정대로 eligible을 만든다(빈 리스트면
        그 파일 전체 제외 - "이 파일 제외" 버튼)."""
        manual_pairs = manual_pairs or {}
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
        ambiguous = []
        for d_file in sorted(all_files):
            y1s = y1_by_file.get(d_file, [])
            y2s = y2_by_file.get(d_file, [])
            # [수정] "3D legend에서도 동일 filename들을 filename-#로 구분 표기" -
            # Dat list 섹션 제목과 항상 같은 번호를 쓰도록 공용 dedup 함수 재사용.
            bn = self._dedup_display_name(d_file)

            if not y1s and not y2s:
                continue  # 아예 선택 안 한 파일은 조용히 무시

            if d_file in manual_pairs:
                pairs = manual_pairs[d_file]
            elif len(y1s) == 0 or len(y2s) == 0:
                reason = []
                if len(y1s) == 0: reason.append("Y1 없음")
                if len(y2s) == 0: reason.append("Y2 없음")
                skipped.append(f"{bn}: {', '.join(reason)}")
                continue
            elif len(y1s) == 1 and len(y2s) == 1:
                pairs = [(y1s[0], y2s[0])]
            else:
                # [추가] 여러 쌍이 나올 수 있는 경우 - 기본(클릭 순서) 짝을
                # 만들어 제안하되, 실제 확정은 항상 사용자 확인을 거친다.
                y1_ordered = self._ordered_outs_for_file(d_file, y1s)
                y2_ordered = self._ordered_outs_for_file(d_file, y2s)
                default_pairs = list(zip(y1_ordered, y2_ordered))
                ambiguous.append({
                    "d_file": d_file,
                    "label": bn,
                    "y1_candidates": y1_ordered,
                    "y2_candidates": y2_ordered,
                    "default_pairs": default_pairs,
                    "mismatched": len(y1s) != len(y2s),
                })
                continue

            if not pairs:
                continue  # manual_pairs에서 사용자가 이 파일 전체를 제외한 경우

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
            x_title = self.legend_vars.get(x_key_val).get() if x_key_val in self.legend_vars else ""

            # [추가 - 사용자 요청] 한 파일에서 여러 쌍이 나오면 label에 번호를
            # 붙여 구분한다(#1, #2, ...) - 기존 템플릿(marker_shapes 등은 label
            # 기준 dict)과의 호환을 위해 파일당 쌍이 1개뿐이면 기존처럼 번호를
            # 붙이지 않는다.
            multi = len(pairs) > 1
            for idx, (y1_out, y2_out) in enumerate(pairs):
                y1_key = f"{d_file}||{y1_out}"
                y2_key = f"{d_file}||{y2_out}"
                y_title = self.legend_vars.get(y1_key).get() if y1_key in self.legend_vars else ""
                y2_title = self.legend_vars.get(y2_key).get() if y2_key in self.legend_vars else ""
                eligible.append({
                    "dat_file": target_dat_file,
                    "x_col": file_x_output_no + 1,
                    "y_col": y1_out + 1,
                    "z_col": y2_out + 1,
                    "x_shift": x_shift,
                    "label": f"{bn}#{idx + 1}" if multi else bn,
                    "x_title": x_title,
                    "y_title": y_title,
                    "y2_title": y2_title,
                    # [추가 - 사용자 요청] "(x,y,z)의 순서쌍 col 표기" - 3D Plot
                    # 팝업의 Set 목록에서 실제 어떤 output_no끼리 짝지어졌는지
                    # 바로 보이게(0-based, Dat list의 변수 번호와 동일 기준).
                    "x_out": file_x_output_no,
                    "y1_out": y1_out,
                    "y2_out": y2_out,
                    # [추가 - 사용자 요청] "3D template이 실제 Y1/Y2 짝 정보를
                    # 기억하게" - target_dat_file(resort_dat_file이 돌려주는
                    # 정렬 캐시 파일)이 아니라 원본 d_file을 같이 들고 있어야
                    # _3d_template_dict가 이 짝을 원본 파일 기준(rel path)으로
                    # 저장할 수 있다(target_dat_file은 매번 새로 만들어지는
                    # 임시 캐시 경로라 저장용 키로 못 씀).
                    "orig_file": d_file,
                })
        return eligible, skipped, ambiguous

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
        eligible, skipped, ambiguous = self._collect_3d_curves()

        # [수정 - 사용자 요청] "한 파일에서 y,z값을 따로 줄 수는 없나(여러
        # set)... 기본은 순서쌍으로, 안 맞으면 경고 내고 선택하게(취소 가능)" -
        # 예전엔 Y1/Y2가 2개 이상이면(어느 것끼리 짝지을지 모호하다며) 팝업
        # 자체를 안 열고 바로 에러를 냈는데, 이제 그런 파일마다 _collect_3d_curves가
        # ambiguous로 돌려주므로 각각에 대해 _resolve_3d_pair_dialog(선택 방식
        # 짝짓기 팝업)를 띄워 사용자가 직접(또는 기본 순서쌍 그대로) 확정하게
        # 한 뒤, 그 결과(manual_pairs)로 eligible을 다시 계산한다. "이 파일
        # 제외"를 고르면 그 파일만 3D에서 빠지고(전체 취소가 아님) 나머지는
        # 정상 진행된다.
        if ambiguous:
            manual_pairs = {}
            for item in ambiguous:
                manual_pairs[item["d_file"]] = self._resolve_3d_pair_dialog(item)
            eligible, skipped, _ = self._collect_3d_curves(manual_pairs=manual_pairs)

        surfaces = self._collect_3d_surfaces()
        # [수정 - 요청] "2D+3D 한번에" - 파일 기반 curve/surface가 하나도 없어도
        # Function Surface(데이터 없이 Z=f(X,Y) 수식만으로 그리는 splot)를 이
        # 팝업 안에서 새로 추가할 수 있으므로, 더 이상 여기서 막지 않고 항상
        # 다이얼로그를 연다(파일이 아예 없을 때만 참고용으로 안내).
        if not eligible and not surfaces:
            msg = "지금 로드된 파일 중 3D로 바로 그릴 수 있는 것이 없습니다.\n(파일마다 Y1/Y2가 각각 1개 이상 선택되어 있어야 하고, Surface(splot) 파일은 로드만 하면 바로 사용 가능합니다.)\n아래 팝업에서 Function Surface(수식)만으로도 그릴 수 있습니다."
            if skipped:
                msg += "\n\n제외된 파일:\n" + "\n".join(skipped)
            messagebox.showinfo("3D Plot", msg)
        elif skipped:
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
        # [추가 - 요청] "3D popup 창에 옵션 체크박스를 넣으면" - 2D의 메인 화면
        # Animate 체크박스는 3D 파이프라인(create_3d_script)을 전혀 안 건드려서
        # 지금까지 3D에서는 켜져 있어도 완전히 무시됐음(연동 자체가 없었음) -
        # 3D는 자기 전용 팝업(여기)에 별도로 넣는다(2D 체크박스와 독립적).
        # X(Time) 값이 늘어남에 따라 curve/surface가 점점 그려지는(progress)
        # 애니메이션 - gnu_generator.create_3d_animation_script 참고(회전각은
        # 재생 내내 고정, annotation/arrow는 1차 구현 범위 밖).
        animate3d_var = tk.BooleanVar(value=False)
        animate3d_duration_var = tk.StringVar(value="20")
        self._mk_check(row2, "Animate", animate3d_var, color="accent", side="left", padx=(14, 0))
        ttk.Label(row2, text="Time(s):").pack(side="left", padx=(4, 1))
        ttk.Entry(row2, textvariable=animate3d_duration_var, width=4).pack(side="left")

        # [수정] "Marker Size를 세트 선택 줄로 이동(모양 앞에), Style도 세트별로
        # (curve마다 다르게 줄 수 있으므로) 이동 - Color Palette(입체채색)는
        # s-plot(surface)에만 의미가 있으니 curve 행에는 그 옵션 자체를 빼서
        # s-plot에서만 선택 가능하게 함" - curve/surface 체크박스, Style,
        # Marker Size, Marker 모양을 한 줄에서 같이 고른다.
        # [수정 - 사용자 요청] "3D에서도 커버특성을 묶어서 정리" - 2D Dat
        # list -> Curve Settings 팝업 통합과 같은 이유로, Style/Size/Shape/
        # MaxNo(저빈도 "세부 설정")를 이 줄에서 빼서 "Detail" 팝업
        # (_open_3d_curve_detail_popup, set_frame 헤더 참고)으로 옮긴다.
        # 이 줄엔 자주 쓰는 체크박스/이름/▲▼만 남는다.
        set_frame = ttk.LabelFrame(dialog, text="포함할 Set (체크 해제로 제외)")
        set_frame.pack(fill="x", padx=10, pady=5)
        _shape_choices = [s for s in MARKER_SHAPE_LIST if s != "None"]
        _style_choices_curve = [v for k, v in STYLE_3D_DISPLAY_MAP.items() if k != "pm3d"]
        _style_choices_surface = list(STYLE_3D_DISPLAY_MAP.values())
        _set_idx = 0
        curve_check_vars = []    # [(BooleanVar, curve_dict, shape_StringVar, size_StringVar, style_StringVar, title_StringVar, maxno_StringVar), ...]
        surface_check_vars = []  # [(BooleanVar, surface_dict, shape_StringVar, size_StringVar, style_StringVar, title_StringVar, maxno_StringVar), ...]
        # [추가 - 요청] "선택한 순서대로 curve를 그려주기 - 3D도 해당함" - 각
        # 행의 실제 Frame 위젯을 curve_check_vars/surface_check_vars와 나란히
        # 별도 리스트로 들고 있다가, ▲▼로 리스트 순서를 바꾸면 그 순서 그대로
        # 다시 pack해서 화면 표시 순서도 같이 바뀌게 한다(대화상자를 통째로
        # 다시 열지 않고 그 자리에서 즉시 반영 - Rotate X/Z 등 다른 입력값이
        # 안 날아가게).
        curve_check_frames = []
        surface_check_frames = []

        def _repack_3d_rows():
            for fr in curve_check_frames + surface_check_frames:
                fr.pack_forget()
            for fr in curve_check_frames:
                fr.pack(fill="x", pady=1)
            for fr in surface_check_frames:
                fr.pack(fill="x", pady=1)

        def _move_3d_row(vars_list, frames_list, frame, delta):
            # [수정 - 버그] 버튼이 생성 시점의 고정 인덱스를 그대로 들고
            # 있으면, 몇 번 옮긴 뒤에는 그 버튼이 원래 자기 줄이 아니라
            # "지금 그 인덱스에 있는 다른 줄"을 옮기게 됨 - 매번 클릭 시점에
            # frame(각 버튼이 속한 실제 위젯) 자신의 현재 위치를 새로 찾아서
            # 옮긴다.
            idx = frames_list.index(frame)
            j = idx + delta
            if not (0 <= j < len(vars_list)):
                return
            vars_list[idx], vars_list[j] = vars_list[j], vars_list[idx]
            frames_list[idx], frames_list[j] = frames_list[j], frames_list[idx]
            _repack_3d_rows()

        # [추가 - 사용자 요청] "각 3D 그림 이름은 file명으로 고정돼 있는데,
        # Plot/X/Y/Z Title처럼 사용자가 직접 수정 입력하게 해서 legend에도
        # 구별되게 해주고 template에도 기록하게 해줘요" - curve/surface별로
        # legend에 실제로 찍히는 이름(title_var_row, 비어있으면 기존처럼
        # 파일명 기반 label을 그대로 씀)을 담을 입력칸을 새로 추가한다.
        # c["label"]/s["label"] 자체는 손대지 않고 그대로 유지(marker 모양/
        # 크기/style을 template에 저장·복원할 때 쓰는 매칭 키라, 여기를
        # 사용자가 자유롭게 바꿀 수 있게 하면 그 매칭이 깨짐 - 그래서 이름
        # 표시용 별도 필드를 새로 둔다).
        # [추가 - 사용자 요청] "3D Marker 개수도 2D처럼 한 화면상 최대개수를
        # 정해요(기본 및 최대수 사용자 입력)" - MaxNo.(2D의 Max#와 동일한
        # 의미 - 비우면 Auto~25개) 입력값 검증(정수만 - 2D Max#와 동일).
        # [수정 - 사용자 요청] "3D에서도 커버특성을 묶어서 정리" 이후로는
        # curve/surface/manual 각 줄이 아니라 Set Detail 팝업 한 곳에서만
        # MaxNo를 입력받으므로, 이 변수는 그 팝업(아래 _open_3d_curve_
        # detail_popup)에서만 쓰인다.
        _maxno_vcmd = (dialog.register(lambda s: s == "" or s.isdigit()), "%P")

        for c in eligible:
            srow = ttk.Frame(set_frame)
            srow.pack(fill="x", pady=1)
            v = tk.BooleanVar(value=True)
            # [추가 - 사용자 요청] "(x,y,z)의 순서쌍 col 표기가 필요할 듯함,
            # 예로 (0,1,2)" - 어떤 output_no끼리 짝지어 이 curve가 됐는지
            # Set 목록에서 바로 보이게(0-based, Dat list 변수 번호와 동일 기준).
            _col_tag = f" (X{c.get('x_out', '?')},Y{c.get('y1_out', '?')},Z{c.get('y2_out', '?')})"
            self._mk_check(srow, f"[Curve] {c['label']}{_col_tag}", v, color="accent", side="left")
            # [수정 - 사용자 요청] Style/Size/Shape/MaxNo는 더 이상 이 줄에
            # inline으로 넣지 않고 Detail 팝업에서만 편집한다(아래 변수는
            # 그대로 유지 - curve_check_vars가 다운스트림 3D 렌더링에서
            # 그대로 참조함).
            shape_var = tk.StringVar(value=_shape_choices[_set_idx % len(_shape_choices)])
            size_var = tk.StringVar(value="M")
            style_var_row = tk.StringVar(value=STYLE_3D_DISPLAY_MAP["lines"])
            title_var_row = tk.StringVar(value="")
            maxno_var = tk.StringVar(value="")
            self._mk_btn(srow, "▼", lambda fr=srow: _move_3d_row(curve_check_vars, curve_check_frames, fr, 1),
                         color="grey", btn_width=2, side="right", padx=1)
            self._mk_btn(srow, "▲", lambda fr=srow: _move_3d_row(curve_check_vars, curve_check_frames, fr, -1),
                         color="grey", btn_width=2, side="right", padx=(4, 1))
            ttk.Label(srow, text="이름:").pack(side="left", padx=(6, 0))
            name_entry = ttk.Entry(srow, textvariable=title_var_row, width=14)
            name_entry.pack(side="left", padx=(2, 0))
            name_entry.bind("<FocusIn>", lambda e, ent=name_entry: self.set_active_entry(ent))
            curve_check_vars.append((v, c, shape_var, size_var, style_var_row, title_var_row, maxno_var))
            curve_check_frames.append(srow)
            _set_idx += 1
        for s in surfaces:
            srow = ttk.Frame(set_frame)
            srow.pack(fill="x", pady=1)
            v = tk.BooleanVar(value=True)
            self._mk_check(srow, f"[Surface] {s['label']} (채널 {s['n_outputs']}개, Z={s['z_label']})", v,
                            color="amber", side="left")
            # [수정 - 사용자 요청] Curve와 동일하게 Style/Size/Shape/MaxNo는
            # Detail 팝업으로 이동.
            shape_var = tk.StringVar(value=_shape_choices[_set_idx % len(_shape_choices)])
            size_var = tk.StringVar(value="M")
            style_var_row = tk.StringVar(value=STYLE_3D_DISPLAY_MAP["lines"])
            title_var_row = tk.StringVar(value="")
            maxno_var = tk.StringVar(value="")
            self._mk_btn(srow, "▼", lambda fr=srow: _move_3d_row(surface_check_vars, surface_check_frames, fr, 1),
                         color="grey", btn_width=2, side="right", padx=1)
            self._mk_btn(srow, "▲", lambda fr=srow: _move_3d_row(surface_check_vars, surface_check_frames, fr, -1),
                         color="grey", btn_width=2, side="right", padx=(4, 1))
            ttk.Label(srow, text="이름:").pack(side="left", padx=(6, 0))
            name_entry = ttk.Entry(srow, textvariable=title_var_row, width=14)
            name_entry.pack(side="left", padx=(2, 0))
            name_entry.bind("<FocusIn>", lambda e, ent=name_entry: self.set_active_entry(ent))
            surface_check_vars.append((v, s, shape_var, size_var, style_var_row, title_var_row, maxno_var))
            surface_check_frames.append(srow)
            _set_idx += 1

        # [추가 - 사용자 요청] "3D에서도 커버특성을 묶어서 정리" - 위에서
        # 각 줄(curve/surface)에서 뺀 Style/Size/Shape/MaxNo를 한 팝업에
        # 전부 모아서 보여준다(2D Curve Settings 팝업과 같은 표 형태).
        # curve_check_vars/surface_check_vars가 이미 다 채워진 뒤에
        # 여닫히므로(버튼 클릭 시점에 평가) 이 함수 정의 위치는 상관없지만,
        # 읽기 쉽게 두 루프 바로 뒤에 둔다.
        def _open_3d_curve_detail_popup():
            popup = tk.Toplevel(dialog)
            popup.title("3D Set Detail (Style/Size/Shape/MaxNo)")
            popup.transient(dialog)

            NAME_PX, STYLE_PX, SIZE_PX, SHAPE_PX, MAXNO_PX = 200, 100, 55, 90, 65

            def _cell(parent, px, height=22):
                f = tk.Frame(parent, width=px, height=height)
                f.pack_propagate(False)
                f.pack(side="left")
                return f

            header_f = ttk.Frame(popup)
            header_f.pack(fill="x", padx=10, pady=(10, 2))
            ttk.Label(_cell(header_f, NAME_PX), text="Curve/Surface", font=("Consolas", 9, "bold")).pack(side="left")
            ttk.Label(_cell(header_f, STYLE_PX), text="Style", font=("Consolas", 9, "bold")).pack(side="left")
            ttk.Label(_cell(header_f, SIZE_PX), text="Size", font=("Consolas", 9, "bold")).pack(side="left")
            ttk.Label(_cell(header_f, SHAPE_PX), text="Shape", font=("Consolas", 9, "bold")).pack(side="left")
            ttk.Label(_cell(header_f, MAXNO_PX), text="MaxNo.", font=("Consolas", 9, "bold")).pack(side="left")

            list_frame = ttk.Frame(popup)
            list_frame.pack(fill="both", expand=True, padx=10)

            def _add_detail_row(label_text, style_var_row, size_var, shape_var, maxno_var, style_choices):
                row_f = ttk.Frame(list_frame)
                row_f.pack(fill="x", pady=1)
                ttk.Label(_cell(row_f, NAME_PX), text=label_text).pack(side="left")
                style_combo = ttk.Combobox(_cell(row_f, STYLE_PX), textvariable=style_var_row,
                                            values=style_choices, state="readonly")
                style_combo.pack(side="left", fill="both", expand=True)
                self._disable_combobox_wheel(style_combo)
                size_combo = ttk.Combobox(_cell(row_f, SIZE_PX), textvariable=size_var,
                                           values=MARKER_SIZE_LIST, state="readonly")
                size_combo.pack(side="left", fill="both", expand=True)
                self._disable_combobox_wheel(size_combo)
                shape_combo = ttk.Combobox(_cell(row_f, SHAPE_PX), textvariable=shape_var,
                                            values=MARKER_SHAPE_LIST, state="readonly")
                shape_combo.pack(side="left", fill="both", expand=True)
                self._disable_combobox_wheel(shape_combo)
                maxno_cell = _cell(row_f, MAXNO_PX)
                ttk.Entry(maxno_cell, textvariable=maxno_var, validate="key",
                          validatecommand=_maxno_vcmd).pack(side="left", fill="both", expand=True)

            for v, c, shape_var, size_var, style_var_row, title_var_row, maxno_var in curve_check_vars:
                _add_detail_row(f"[Curve] {c['label']}", style_var_row, size_var, shape_var, maxno_var, _style_choices_curve)
            for v, s, shape_var, size_var, style_var_row, title_var_row, maxno_var in surface_check_vars:
                _add_detail_row(f"[Surface] {s['label']}", style_var_row, size_var, shape_var, maxno_var, _style_choices_surface)
            # [추가 - 사용자 요청] "3D Curve 직접 추가" 섹션도 같은 이유로
            # Style/Size/Shape/MaxNo를 여기로 옮긴다(Dat/X/Y/Z/이름은 "이
            # 줄이 어떤 데이터인지" 정하는 핵심이라 그 섹션에 인라인으로
            # 남겨둠 - Function Surface는 애초에 Shape/Size/MaxNo 자체가
            # 없는 순수 수식 곡면이라 Style 하나만 있고 이미 간결해서 제외).
            # manual_curve_rows는 이 함수보다 아래에서 정의되지만(late
            # binding), 팝업은 항상 버튼 클릭 시점(다이얼로그가 다 그려진
            # 뒤)에만 열리므로 그때는 이미 채워져 있어 문제없다.
            for d in manual_curve_rows:
                _mc_title = d['title'].get().strip()
                _mc_label = _mc_title if _mc_title else f"{d['file_label'].get()} (X={d['x'].get()},Y={d['y'].get()},Z={d['z'].get()})"
                _add_detail_row(f"[Manual] {_mc_label}", d['style'], d['size'], d['shape'], d['maxcount'], _style_choices_curve)

            if not curve_check_vars and not surface_check_vars and not manual_curve_rows:
                ttk.Label(list_frame, text="(curve/surface 없음)").pack(padx=5, pady=10)

            ttk.Label(
                popup, text="Style=파선/색상 등 3D 선 표시 방식(Surface는 pm3d 포함). MaxNo를 비우면 자동(Marker 개수 제한).",
                foreground="#555555"
            ).pack(padx=10, pady=(4, 0), anchor="w")

            ttk.Button(popup, text="완료", command=popup.destroy).pack(anchor="e", padx=10, pady=8)

        set_detail_row = ttk.Frame(dialog)
        set_detail_row.pack(fill="x", padx=10, pady=(0, 5))
        set_detail_btn = tk.Button(
            set_detail_row, text="Set Detail", width=11, font=("Malgun Gothic", 9, "bold"),
            bg=self.PALETTE["secondary"], fg="white",
            activebackground=self.PALETTE["secondary_dark"], activeforeground="white",
            relief="raised", bd=1, pady=1,
            command=_open_3d_curve_detail_popup,
        )
        set_detail_btn.pack(side="left")

        # [추가 - 요청] "2D+3D 한번에" - Function Surface: 데이터 파일 없이
        # Z=f(X,Y) gnuplot 수식(예: sin(x)*cos(y), x**2-y**2)을 그대로 splot에
        # 추가한다. curve/surface처럼 로드된 파일에서 자동으로 뜨는 목록이
        # 아니라(수식은 파일과 무관 - X 값이 연동될 file/컬럼이 필요 없음),
        # Comment/Arrow처럼 이 팝업 안에서 직접 행을 추가/삭제하는 목록으로 둔다.
        func_surface_rows = []
        func_surface_frame = ttk.LabelFrame(dialog, text="Function Surface (Z=f(X,Y), 데이터 없이 수식)")
        func_surface_frame.pack(fill="x", padx=10, pady=5)
        fs_list_frame = ttk.Frame(func_surface_frame)
        fs_list_frame.pack(fill="x")

        def add_func_surface_row(initial=None):
            init = initial or {}
            row = ttk.Frame(fs_list_frame)
            row.pack(fill="x", pady=1)
            data = {
                'expression': tk.StringVar(value=init.get('expression', "")),
                'title': tk.StringVar(value=init.get('title', "")),
                'style': tk.StringVar(value=STYLE_3D_DISPLAY_MAP.get(init.get('style', 'lines'), STYLE_3D_DISPLAY_MAP["lines"])),
                'frame': row,
            }
            func_surface_rows.append(data)

            # [수정 - 사용자 보고 버그] "3D Function Surface 추가시 curve명이
            # Z-title에 찍히지 않음" - 아래 _sync_default_titles는 체크된 첫
            # curve/surface만 보고 Z title 기본값을 채우는데, Function
            # Surface는 애초에 "포함할 Set" 체크박스 목록에 없는(파일과 무관한)
            # 별도 목록이라 이 함수가 Function Surface의 존재 자체를 몰랐음 -
            # curve/surface가 하나도 안 체크된 경우(Function Surface만으로
            # 그리는 경우 포함) Function Surface의 Title(비어있으면 수식
            # 자체)을 Z title 기본값으로 대신 쓰도록 trace를 추가한다. 행을
            # 추가/삭제/Title·수식 수정할 때마다 다시 계산되게 함(_sync_
            # default_titles는 이 함수보다 아래에서 정의되지만, 실제 호출은
            # 항상 다이얼로그가 다 그려진 뒤(버튼 클릭/타이핑 시점)라 늦은
            # 바인딩으로 문제없이 참조 가능).
            data['title'].trace_add("write", lambda *_: _sync_default_titles())
            data['expression'].trace_add("write", lambda *_: _sync_default_titles())

            def _remove_row():
                # [수정 - 사용자 보고 버그] 2D remove_row와 동일 이유 -
                # destroy 직후 update_idletasks()로 Windows Tk 리페인트
                # 지연을 강제 해소.
                parent = row.master
                row.destroy()
                parent.update_idletasks()
                func_surface_rows.remove(data)
                _sync_default_titles()
            ttk.Button(row, text="X", width=2, style="Compact.TButton",
                       command=_remove_row).pack(side="right", padx=3)
            ttk.Combobox(row, textvariable=data['style'], values=_style_choices_surface,
                         width=13, state="readonly").pack(side="right", padx=4)
            ttk.Label(row, text="Title:").pack(side="left", padx=(0, 2))
            fs_title_entry = ttk.Entry(row, textvariable=data['title'], width=14)
            fs_title_entry.pack(side="left", padx=2)
            fs_title_entry.bind("<FocusIn>", lambda e: self.set_active_entry(fs_title_entry))
            ttk.Label(row, text="Z=f(X,Y):").pack(side="left", padx=(6, 2))
            fs_expr_entry = ttk.Entry(row, textvariable=data['expression'], width=22)
            fs_expr_entry.pack(side="left", padx=2, fill="x", expand=True)
            fs_expr_entry.bind("<FocusIn>", lambda e: self.set_active_entry(fs_expr_entry))
            _sync_default_titles()

        ttk.Button(func_surface_frame, text="+ Add Function Surface", command=add_func_surface_row).pack(anchor="w", padx=5, pady=(0, 2))
        ttk.Label(
            func_surface_frame, text="예: sin(x)*cos(y), x**2+y**2 - gnuplot 내장 함수/식을 그대로 입력 (X,Y의 함수).",
            foreground="#555555"
        ).pack(anchor="w", padx=5, pady=(0, 4))

        # [추가 - 사용자 요청] "추가시 Dat file-list 중 선택, curve title명 및
        # (x,y,z) 입력 등" - 위 "포함할 Set"은 Dat list에서 Y1/Y2로 체크해둔
        # 변수만 자동으로 모아 만드는데, 그와 별개로 이 팝업 안에서 곧바로
        # (지금 로드된 Dat file 중 하나를 골라) X/Y/Z 변수를 직접 지정해 3D
        # curve를 추가할 수 있게 한다(Function Surface와 동일하게 이 팝업
        # 안에서 직접 행을 추가/삭제하는 목록 - 삭제는 각 행의 "X" 버튼).
        manual_curve_rows = []
        manual_curve_frame = ttk.LabelFrame(dialog, text="3D Curve 직접 추가 (Dat file에서 X/Y/Z 변수 직접 선택)")
        manual_curve_frame.pack(fill="x", padx=10, pady=5)
        mc_list_frame = ttk.Frame(manual_curve_frame)
        mc_list_frame.pack(fill="x")

        # 파일별 변수 선택지: {표시용 label: 실제 파일 경로}, {파일 경로: [(output_no, display_name), ...]}
        _mc_file_var_choices = {}
        for _info in self.file_rows:
            _meta = _info.get("meta")
            _fn = _info.get("filename")
            if _meta is None or not _fn or not hasattr(_meta, "variables"):
                continue
            _mc_file_var_choices[_fn] = [(vv.output_no, vv.display_name) for vv in _meta.variables]
        _mc_file_labels = [self._dedup_display_name(_fn) for _fn in _mc_file_var_choices.keys()]
        _mc_label_to_file = dict(zip(_mc_file_labels, _mc_file_var_choices.keys()))

        def add_manual_curve_row(initial=None):
            init = initial or {}
            row = ttk.Frame(mc_list_frame)
            row.pack(fill="x", pady=1)
            file_label_var = tk.StringVar(value=init.get('file_label') or (_mc_file_labels[0] if _mc_file_labels else ""))
            x_var = tk.StringVar(value=init.get('x', ""))
            y_var = tk.StringVar(value=init.get('y', ""))
            z_var = tk.StringVar(value=init.get('z', ""))
            title_var = tk.StringVar(value=init.get('title', ""))
            style_var = tk.StringVar(value=STYLE_3D_DISPLAY_MAP.get(init.get('style', 'lines'), STYLE_3D_DISPLAY_MAP["lines"]))
            shape_var = tk.StringVar(value=init.get('shape') or (_shape_choices[0] if _shape_choices else "None"))
            size_var = tk.StringVar(value=init.get('size', "M"))
            maxcount_var = tk.StringVar(value=init.get('maxcount', ""))
            data = {
                'file_label': file_label_var, 'x': x_var, 'y': y_var, 'z': z_var,
                'title': title_var, 'style': style_var, 'shape': shape_var, 'size': size_var,
                'maxcount': maxcount_var, 'frame': row,
            }
            manual_curve_rows.append(data)

            def _var_choice_values():
                _fn = _mc_label_to_file.get(file_label_var.get())
                return [f"{no}:{name}" for no, name in _mc_file_var_choices.get(_fn, [])]

            # [수정 - 사용자 보고 버그] 2D remove_row와 동일 이유 - destroy
            # 직후 update_idletasks()로 Windows Tk 리페인트 지연 해소.
            ttk.Button(row, text="X", width=2, style="Compact.TButton",
                       command=lambda: (row.destroy(), row.master.update_idletasks(), manual_curve_rows.remove(data))).pack(side="right", padx=3)
            # [수정 - 사용자 요청] "3D에서도 커버특성을 묶어서 정리" - Style/
            # Size/Shape(Marker 모양)/MaxNo는 더 이상 이 줄에 inline으로
            # 넣지 않고 "Set Detail" 팝업(_open_3d_curve_detail_popup)의
            # [Manual] 섹션에서 편집한다. 이 줄엔 "어떤 데이터인지"를 정하는
            # Dat/X/Y/Z/이름만 남긴다(위 style_var/shape_var/size_var/
            # maxcount_var 자체는 그대로 유지 - data dict에 담겨 다운스트림
            # 3D 렌더링에서 그대로 참조됨).
            ttk.Label(row, text="이름:").pack(side="left", padx=(6, 0))
            t_entry = ttk.Entry(row, textvariable=title_var, width=12)
            t_entry.pack(side="left", padx=2)
            t_entry.bind("<FocusIn>", lambda e: self.set_active_entry(t_entry))

            ttk.Label(row, text="Dat:").pack(side="left", padx=(6, 0))
            file_cb = ttk.Combobox(row, textvariable=file_label_var, values=_mc_file_labels,
                                    width=14, state="readonly")
            file_cb.pack(side="left", padx=2)
            ttk.Label(row, text="X:").pack(side="left", padx=(4, 0))
            x_cb = ttk.Combobox(row, textvariable=x_var, width=12, state="readonly")
            x_cb.pack(side="left", padx=2)
            ttk.Label(row, text="Y:").pack(side="left", padx=(4, 0))
            y_cb = ttk.Combobox(row, textvariable=y_var, width=12, state="readonly")
            y_cb.pack(side="left", padx=2)
            ttk.Label(row, text="Z:").pack(side="left", padx=(4, 0))
            z_cb = ttk.Combobox(row, textvariable=z_var, width=12, state="readonly")
            z_cb.pack(side="left", padx=2)

            def _on_file_change(*_a):
                vals = _var_choice_values()
                for cb in (x_cb, y_cb, z_cb):
                    cb['values'] = vals
                if not vals:
                    return
                if x_var.get() not in vals:
                    x_var.set(vals[0])
                if y_var.get() not in vals:
                    y_var.set(vals[min(1, len(vals) - 1)])
                if z_var.get() not in vals:
                    z_var.set(vals[min(2, len(vals) - 1)])
            file_label_var.trace_add("write", _on_file_change)
            _on_file_change()  # 처음 만들 때도 한 번 채움(Template 복원 시 저장된 값이 있으면 유지)

        ttk.Button(manual_curve_frame, text="+ Add 3D Curve", command=add_manual_curve_row).pack(anchor="w", padx=5, pady=(0, 2))
        ttk.Label(
            manual_curve_frame,
            text="Dat list의 Y1/Y2 체크와 무관하게, 로드된 파일 하나에서 원하는 X/Y/Z 변수를 직접 골라 3D curve로 추가합니다.",
            foreground="#555555"
        ).pack(anchor="w", padx=5, pady=(0, 4))

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
                # [수정 - 사용자 보고 버그] "3D Function Surface 추가시 curve명이
                # Z-title에 찍히지 않음" - 체크된 curve/surface가 하나도 없으면
                # (Function Surface만으로 그리는 경우 포함) 지금까지 여기서
                # 무조건 빈 문자열로 떨어졌음 - Function Surface는 "포함할 Set"
                # 체크박스 목록에 없는 별도 목록이라 이 함수가 그 존재 자체를
                # 몰랐던 게 원인. 첫 번째 Function Surface 행의 Title(비어
                # 있으면 수식 자체)을 대신 폴백으로 쓴다.
                _fs = next((d for d in func_surface_rows if d['expression'].get().strip()), None)
                new_zlabel = (_fs['title'].get().strip() or _fs['expression'].get().strip()) if _fs else ""
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
            # [수정 - 사용자 보고 버그] 2D remove_row와 동일 이유.
            ttk.Button(row, text="X", width=2, style="Compact.TButton", command=lambda: (row.destroy(), row.master.update_idletasks(), anno3d_list.remove(data))).pack(side="right", padx=3)
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
            # [수정 - 사용자 보고 버그] 2D remove_row와 동일 이유.
            ttk.Button(row, text="X", width=2, style="Compact.TButton", command=lambda: (row.destroy(), row.master.update_idletasks(), arrow3d_list.remove(data))).pack(side="right", padx=3)
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
            for v, c, shape_var, size_var, style_var_row, title_var_row, maxno_var in curve_check_vars:
                if not v.get():
                    continue
                c2 = dict(c)
                hollow_pt, _filled_pt = MARKER_SHAPE_MAP.get(shape_var.get(), (None, None))
                c2["marker_shape"] = hollow_pt
                c2["marker_size"] = MARKER_SIZE_MAP.get(size_var.get(), 1.0)
                c2["style"] = STYLE_3D_INTERNAL_MAP.get(style_var_row.get(), "lines")
                # [수정 - 사용자 요청] "3D 그림 이름이 file명 고정인데 legend에
                # 구별되게 사용자가 수정하게 해줘요" - 새로 추가한 이름 입력칸
                # (title_var_row)이 비어있지 않으면 그 값을, 비어있으면(기본)
                # 기존처럼 파일명 기반 label을 그대로 legend title로 쓴다.
                c2["title"] = title_var_row.get().strip() or c["label"]
                # [추가 - 사용자 요청] "3D Marker 개수도 2D처럼 최대개수를 정해요" -
                # 비우면 None(Auto~25개, create_3d_script 참고), 숫자면 그 값으로 고정.
                _maxno_str = maxno_var.get().strip()
                c2["marker_max_count"] = int(_maxno_str) if _maxno_str else None
                curves_final.append(c2)

            surfaces_final = []
            for v, s, shape_var, size_var, style_var_row, title_var_row, maxno_var in surface_check_vars:
                if not v.get():
                    continue
                s2 = dict(s)
                hollow_pt, _filled_pt = MARKER_SHAPE_MAP.get(shape_var.get(), (None, None))
                s2["marker_shape"] = hollow_pt
                s2["marker_size"] = MARKER_SIZE_MAP.get(size_var.get(), 1.0)
                s2["style"] = STYLE_3D_INTERNAL_MAP.get(style_var_row.get(), "lines")
                # [추가 - 사용자 요청] curve와 동일하게 surface도 legend 이름을
                # 사용자가 지정할 수 있게 함(비어있으면 기존처럼 label 유지).
                s2["title"] = title_var_row.get().strip() or s["label"]
                _s_maxno_str = maxno_var.get().strip()
                s2["marker_max_count"] = int(_s_maxno_str) if _s_maxno_str else None
                surfaces_final.append(s2)

            # [추가 - 요청] "2D+3D 한번에" - Function Surface(수식, 파일 없음).
            # Expression이 비어있는 행은 건너뛴다(빈 채로 팝업만 열어본 경우 대비).
            function_surfaces_final = []
            for d in func_surface_rows:
                expr = d['expression'].get().strip()
                if not expr:
                    continue
                function_surfaces_final.append({
                    "expression": expr,
                    "title": d['title'].get().strip() or expr,
                    "style": STYLE_3D_INTERNAL_MAP.get(d['style'].get(), "lines"),
                })

            # [추가 - 사용자 요청] "추가시 Dat file-list 중 선택, curve title명 및
            # (x,y,z) 입력 등" - 위 "3D Curve 직접 추가" 목록(Dat list의 Y1/Y2
            # 체크와 무관하게 직접 고른 X/Y/Z)을 curves_final에 그대로 합친다.
            # 대상 Dat file을 못 고른 경우(로드된 파일이 하나도 없어 콤보박스가
            # 비어있던 경우 등)는 조용히 건너뛴다.
            # [추가 - 사용자 요청] "y1=y2로 중복 선택은 안되게" - Dat list의
            # Y1/Y2 체크박스는 같은 변수를 Y1과 Y2 양쪽에 동시에 선택할 수 없게
            # 서로 배타적으로 막혀 있는데(체크박스 자체가 한쪽을 켜면 다른 쪽은
            # 꺼짐), "3D Curve 직접 추가"는 X/Y/Z를 각각 독립된 콤보박스로 자유
            # 선택하는 구조라 같은 변수를 Y와 Z에 동시에 고르는 것 자체는 막혀
            # 있지 않음 - Z=Y(같은 컬럼)이면 항상 z=y인 의미 없는 선(대각선)만
            # 나오므로, 여기서 걸러내고 한꺼번에 경고한다(다른 정상 행은 계속
            # 포함시킴 - 전체를 막지 않음).
            _mc_yz_dup_labels = []
            for d in manual_curve_rows:
                _fn = _mc_label_to_file.get(d['file_label'].get())
                if not _fn:
                    continue

                def _parse_out_no(_s):
                    try:
                        return int(_s.split(":")[0])
                    except (ValueError, AttributeError, IndexError):
                        return None
                x_no = _parse_out_no(d['x'].get())
                y_no = _parse_out_no(d['y'].get())
                z_no = _parse_out_no(d['z'].get())
                if x_no is None or y_no is None or z_no is None:
                    continue
                if y_no == z_no:
                    _mc_yz_dup_labels.append(
                        f"{self._dedup_display_name(_fn)} (Y=Z={y_no}: {self._var_display_name(_fn, y_no)})"
                    )
                    continue
                try:
                    _target_dat_file = self.resort_dat_file(_fn, x_no)
                except Exception:
                    _target_dat_file = _fn
                _x_shift = float(self.file_xshift_vars[_fn].get() or 0.0) if _fn in self.file_xshift_vars else 0.0
                _hollow_pt, _ = MARKER_SHAPE_MAP.get(d['shape'].get(), (None, None))
                _default_label = f"{self._dedup_display_name(_fn)} (X{x_no},Y{y_no},Z{z_no})"
                _mc_maxno_str = d['maxcount'].get().strip()
                curves_final.append({
                    "dat_file": _target_dat_file,
                    "x_col": x_no + 1, "y_col": y_no + 1, "z_col": z_no + 1,
                    "x_shift": _x_shift,
                    "label": _default_label,
                    "title": d['title'].get().strip() or _default_label,
                    "marker_shape": _hollow_pt,
                    "marker_size": MARKER_SIZE_MAP.get(d['size'].get(), 1.0),
                    "style": STYLE_3D_INTERNAL_MAP.get(d['style'].get(), "lines"),
                    "marker_max_count": int(_mc_maxno_str) if _mc_maxno_str else None,
                })

            if _mc_yz_dup_labels:
                messagebox.showwarning(
                    "3D Plot",
                    "다음 '3D Curve 직접 추가' 행은 Y와 Z가 같은 변수로 지정돼 있어"
                    "(z=y인 의미 없는 선) 제외했습니다 - Z를 다른 변수로 바꿔주세요:\n\n"
                    + "\n".join(_mc_yz_dup_labels)
                )

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
            # [추가 - 요청] "2D+3D 한번에" - Function Surface만으로도 그릴 수
            # 있게 다이얼로그를 항상 열도록 위 open_3d_plot_dialog의 진입 가드는
            # 없앴으므로, 셋 다(curve/surface/function_surface) 비어있는 채로
            # Plot/Save/Print를 누르면 여기서 대신 막는다(gnuplot이 빈 splot
            # 문법 오류를 내는 것보다 사용자에게 바로 알려주는 게 낫다).
            if not curves_final and not surfaces_final and not function_surfaces_final:
                messagebox.showwarning("3D Plot", "그릴 curve/surface/Function Surface가 없습니다.\n(Set 체크박스를 켜거나, 3D Curve를 직접 추가하거나, Function Surface를 하나 이상 추가하세요.)")
                return None

            return (curves_final, rot_x, rot_z, "lines", palette_var.get(),
                    colorbox_var.get(), annotations_3d, arrows_3d, equal_xyz_var.get(), surfaces_final,
                    xlabel3d_var.get(), ylabel3d_var.get(), zlabel3d_var.get(),
                    plot_title_var.get(), time_min, time_max, y_min, y_max, z_min, z_max,
                    animate3d_var.get(), animate3d_duration_var.get(), function_surfaces_final)

        def do_plot():
            # [수정] "3D Plot 추가 창은 plot 후에도 닫지 말 것" - rot_x/rot_z를
            # 조금씩 바꿔가며 여러 번 그려보는 용도가 많아서, 매번 다이얼로그를
            # 다시 열고 curve/comment/arrow 설정을 새로 고르는 게 번거로웠음.
            args = _collect_3d_state()
            if args is None:
                return
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
            if args is None:
                return
            _close_3d_dialog()
            self._save_3d_plot(*args)

        def do_print():
            args = _collect_3d_state()
            if args is None:
                return
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
            # [추가 - 사용자 요청] "3D 그림 이름도 template에 기록되게" - 위
            # marker 모양/크기/style과 동일한 방식(label 기준 dict)으로 사용자가
            # 입력한 legend 이름(title_var_row)도 같이 저장한다.
            # [추가 - 사용자 요청] "3D Marker 개수도 template에 기록되게" - 위
            # marker 모양/크기/style/이름과 동일한 방식(label 기준 dict)으로
            # MaxNo.(marker_max_count, 비면 Auto)도 같이 저장한다.
            # [추가 - 사용자 요청] "3D Template이 curve/surface 체크(선택) 여부
            # 자체를 저장 안 함"(821541c에서 발견해 기록해둔 별개 이슈) - marker
            # 모양/크기/style/이름/MaxNo.와 같은 label 기준 dict로 체크 상태도
            # 같이 저장한다.
            _shapes, _sizes, _styles, _titles, _maxcounts, _checked = {}, {}, {}, {}, {}, {}
            for v, c, shape_var, size_var, style_var_row, title_var_row, maxno_var in curve_check_vars:
                _shapes[c["label"]] = shape_var.get()
                _sizes[c["label"]] = size_var.get()
                _styles[c["label"]] = style_var_row.get()
                _titles[c["label"]] = title_var_row.get()
                _maxcounts[c["label"]] = maxno_var.get()
                _checked[c["label"]] = bool(v.get())
            for v, s, shape_var, size_var, style_var_row, title_var_row, maxno_var in surface_check_vars:
                _shapes[s["label"]] = shape_var.get()
                _sizes[s["label"]] = size_var.get()
                _styles[s["label"]] = style_var_row.get()
                _titles[s["label"]] = title_var_row.get()
                _maxcounts[s["label"]] = maxno_var.get()
                _checked[s["label"]] = bool(v.get())

            # [추가 - 사용자 요청] "3D template이 실제 Y1/Y2 짝 정보를 기억하게" -
            # Batch Set(헤드리스)이 화면에서 확정한 것과 똑같은 (Y1,Y2) 짝을 다시
            # 쓸 수 있도록, 파일별(원본 dat 파일의 cwd 기준 상대경로) 실제 사용된
            # (y1_out, y2_out) 짝 목록을 그대로 저장한다. label(#1,#2...)이 아니라
            # 원본 파일 경로를 키로 써야, Batch가 다시 계산한 순서가 화면과
            # 달라져도(파일당 여러 짝이면 순서가 달라질 수 있음) 안전하게 매칭
            #된다 - Batch 쪽은 이 짝을 실제 지금 선택된 Y1/Y2 목록과 대조해서
            # 유효할 때만 쓰고, 안 맞으면(템플릿을 손으로 고쳤거나 선택이
            # 바뀌었으면) 예전처럼 자동(오름차순) 추정으로 대체한다.
            _curve_pairs = {}
            for v, c, shape_var, size_var, style_var_row, title_var_row, maxno_var in curve_check_vars:
                _of = c.get("orig_file")
                if not _of or "y1_out" not in c or "y2_out" not in c:
                    continue  # "3D Curve 직접 추가"로 만든 curve는 이 짝짓기 대상이 아님
                try:
                    _rel = os.path.relpath(_of, self.cwd)
                except ValueError:
                    _rel = _of
                _curve_pairs.setdefault(_rel, []).append([c["y1_out"], c["y2_out"]])

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
                "animate3d": animate3d_var.get(), "animate3d_duration": animate3d_duration_var.get(),
                "marker_shapes": _shapes, "marker_sizes": _sizes, "styles": _styles, "titles": _titles,
                "marker_max_counts": _maxcounts, "checked": _checked,
                "curve_pairs": _curve_pairs,
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
                # [추가 - 요청] "2D+3D 한번에" - Function Surface(수식, 파일과
                # 무관하므로 curve/surface와 달리 label 매칭이 아니라 그대로 저장/복원).
                "function_surfaces": [
                    {"expression": d['expression'].get(), "title": d['title'].get(),
                     "style": STYLE_3D_INTERNAL_MAP.get(d['style'].get(), "lines")}
                    for d in func_surface_rows if d['expression'].get().strip()
                ],
                # [추가 - 사용자 요청] "추가시 Dat file-list 중 선택, curve title명
                # 및 (x,y,z) 입력 등" - 3D Curve 직접 추가 목록도 저장한다.
                # file_label(그 당시 표시명)뿐 아니라 file_rel(cwd 기준 상대경로)도
                # 같이 저장해서, 다음에 불러올 때 파일이 다시 로드돼 있으면(표시
                # 번호가 바뀌었더라도) 실제 경로 기준으로 다시 찾을 수 있게 한다.
                "manual_curves": [
                    {
                        "file_label": d['file_label'].get(),
                        "file_rel": (
                            os.path.relpath(_mc_label_to_file[d['file_label'].get()], self.cwd)
                            if d['file_label'].get() in _mc_label_to_file else ""
                        ),
                        "x": d['x'].get(), "y": d['y'].get(), "z": d['z'].get(),
                        "title": d['title'].get(),
                        "style": STYLE_3D_INTERNAL_MAP.get(d['style'].get(), "lines"),
                        "shape": d['shape'].get(), "size": d['size'].get(),
                        "maxcount": d['maxcount'].get(),
                    }
                    for d in manual_curve_rows
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
            animate3d_var.set(data.get("animate3d", False))
            animate3d_duration_var.set(data.get("animate3d_duration", animate3d_duration_var.get()))

            # [수정] "Marker Size, Style을 세트별로" - label 기준으로 각 행에
            # 복원(예전 템플릿의 "marker_size"/"style" 전역 키는 없으면 무시됨).
            _shapes = data.get("marker_shapes", {})
            _sizes = data.get("marker_sizes", {})
            _styles = data.get("styles", {})
            # [추가 - 사용자 요청] "3D 그림 이름도 template에 기록되게" - 위와
            # 같은 label 기준 매칭으로 legend 이름(titles)도 복원한다(구버전
            # 템플릿은 이 키가 없어 기존처럼 입력칸이 빈 채로 유지 = label 사용).
            _titles = data.get("titles", {})
            # [추가 - 사용자 요청] "3D Marker 개수도 template에 기록되게" - 위와
            # 동일한 label 기준 매칭으로 MaxNo.(marker_max_count)도 복원(구버전
            # 템플릿은 이 키가 없어 기존처럼 빈 칸 = Auto 유지).
            _maxcounts = data.get("marker_max_counts", {})
            # [추가 - 사용자 요청] "3D Template이 curve/surface 체크 여부를
            # 저장 안 함" 발견분 처리 - 같은 label 기준으로 체크 상태도
            # 복원한다(구버전 템플릿은 이 키가 없어 기존처럼 현재 체크
            # 상태 그대로 유지).
            _checked = data.get("checked", {})
            for v, c, shape_var, size_var, style_var_row, title_var_row, maxno_var in curve_check_vars:
                if c["label"] in _shapes:
                    shape_var.set(_shapes[c["label"]])
                if c["label"] in _sizes:
                    size_var.set(_sizes[c["label"]])
                if c["label"] in _styles:
                    style_var_row.set(_styles[c["label"]])
                if c["label"] in _titles:
                    title_var_row.set(_titles[c["label"]])
                if c["label"] in _maxcounts:
                    maxno_var.set(_maxcounts[c["label"]])
                if c["label"] in _checked:
                    v.set(_checked[c["label"]])
            for v, s, shape_var, size_var, style_var_row, title_var_row, maxno_var in surface_check_vars:
                if s["label"] in _shapes:
                    shape_var.set(_shapes[s["label"]])
                if s["label"] in _sizes:
                    size_var.set(_sizes[s["label"]])
                if s["label"] in _styles:
                    style_var_row.set(_styles[s["label"]])
                if s["label"] in _titles:
                    title_var_row.set(_titles[s["label"]])
                if s["label"] in _maxcounts:
                    maxno_var.set(_maxcounts[s["label"]])
                if s["label"] in _checked:
                    v.set(_checked[s["label"]])

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

            # [추가 - 요청] "2D+3D 한번에" - Function Surface(수식, 파일과 무관하므로
            # curve/surface처럼 label 매칭이 아니라 목록을 그대로 지우고 다시 만든다).
            if "function_surfaces" in data:
                for d in list(func_surface_rows):
                    d['frame'].destroy()
                func_surface_rows.clear()
                for fs in data.get("function_surfaces", []):
                    add_func_surface_row(initial=fs)

            # [추가 - 사용자 요청] "추가시 Dat file-list 중 선택, curve title명
            # 및 (x,y,z) 입력 등" - 3D Curve 직접 추가 목록 복원. file_rel(cwd
            # 기준 상대경로)로 지금 로드된 파일 중 실제 경로가 같은 것을 다시
            # 찾아 그 표시 label을 쓰고(표시 번호가 그때와 달라졌어도 안전),
            # 못 찾으면 옛 file_label이 지금도 그대로 있는지만 확인한다. 둘 다
            # 안 되면(그 파일이 지금 로드 안 돼 있음) 잘못된 파일을 가리키는 것
            # 보다 안전하게 그 행은 건너뛴다.
            if "manual_curves" in data:
                for d in list(manual_curve_rows):
                    d['frame'].destroy()
                manual_curve_rows.clear()
                for mc in data.get("manual_curves", []):
                    _restored_label = mc.get("file_label", "")
                    _rel = mc.get("file_rel", "")
                    if _rel:
                        _abs = _rel if os.path.isabs(_rel) else os.path.join(self.cwd, _rel)
                        for _lbl, _fn2 in _mc_label_to_file.items():
                            try:
                                if os.path.normcase(os.path.abspath(_fn2)) == os.path.normcase(os.path.abspath(_abs)):
                                    _restored_label = _lbl
                                    break
                            except Exception:
                                pass
                    if _restored_label not in _mc_file_labels:
                        continue
                    add_manual_curve_row(initial={
                        "file_label": _restored_label,
                        "x": mc.get("x", ""), "y": mc.get("y", ""), "z": mc.get("z", ""),
                        "title": mc.get("title", ""),
                        "style": mc.get("style", "lines"),
                        "shape": mc.get("shape", ""),
                        "size": mc.get("size", "M"),
                    })

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
                          y_min=None, y_max=None, z_min=None, z_max=None,
                          animate3d=False, animate3d_duration="20", function_surfaces=None):
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
            if animate3d:
                # [추가 - 요청] "3D popup의 Animate 체크박스" - 2D PLOT과 동일한
                # 방식(gnu_generator.create_3d_animation_script)으로 X(Time)
                # 값이 늘어남에 따라 curve/surface가 점점 그려지는 애니메이션을
                # 화면에 띄운다. annotations_3d/arrows_3d는 애니메이션에서는
                # 아직 지원 안 함(create_3d_animation_script 참고).
                try:
                    _duration_sec = float((animate3d_duration or "20").strip())
                except ValueError:
                    _duration_sec = 20.0
                generator.create_3d_animation_script(
                    curves, outfile,
                    xlabel=xlabel3d, ylabel=ylabel3d, zlabel=zlabel3d,
                    title=title_for_plot,
                    xlog=self.xlog_var.get(), ylog=self.y1log_var.get(), zlog=self.y2log_var.get(),
                    rot_x=rot_x, rot_z=rot_z, style=style, palette=palette, colorbox=colorbox,
                    equal_xyz=equal_xyz, surfaces=surfaces, function_surfaces=function_surfaces,
                    time_min=time_min, time_max=time_max,
                    y_min=y_min, y_max=y_max, z_min=z_min, z_max=z_max, duration_sec=_duration_sec,
                )
            else:
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
                    surfaces=surfaces, function_surfaces=function_surfaces, time_min=time_min, time_max=time_max,
                    y_min=y_min, y_max=y_max, z_min=z_min, z_max=z_max,
                )
        except Exception as e:
            messagebox.showerror("3D Plot Error", str(e))
            return

        # [추가 - 요청] "저장도 animation으로 되게" 이전에 "화면 재생도 2D와
        # 동일한 Pause/Speed/Exit 컨트롤이 뜨게" - 2D execute_plot_pipeline과
        # 같은 크래시 확인 + Animation Control 패널 오픈 패턴(_open_animation_
        # control_panel은 2D/3D 구분 없이 ctrl_path/status_path 프로토콜에만
        # 의존하므로 그대로 재사용됨).
        if animate3d and generator.last_process is not None:
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
                # [수정 - 사용자 보고, 2D PLOT 메시지와 동일하게 개선] 실제
                # 오류 내용을 잡았으면 그 사실 그대로만 보여주고(축 설정/
                # 데이터 범위와 무관한 원인일 때 오해를 줄 수 있음), 못
                # 잡았을 때만 기존 추정 문구를 대신 보여준다.
                if _err_detail:
                    _msg = f"gnuplot이 3D 애니메이션을 그리지 못하고 바로 종료됐습니다.\n\ngnuplot 오류 내용:\n{_err_detail[:500]}"
                else:
                    _msg = "gnuplot이 3D 애니메이션을 그리지 못하고 바로 종료됐습니다.\n축 설정이나 데이터 범위를 확인해주세요."
                messagebox.showwarning("3D Plot", _msg)
                generator.last_process = None
            elif getattr(generator, "last_anim_ctrl_path", None):
                self._open_animation_control_panel(
                    generator.last_anim_ctrl_path, generator.last_anim_frame_pause,
                    status_path=getattr(generator, "last_anim_status_path", None),
                    proc=generator.last_process,
                    plot_window_title=os.path.splitext(os.path.basename(outfile))[0],
                )

    def _generate_3d_file(self, outfile, fmt, curves, rot_x, rot_z, style, palette, colorbox,
                           annotations_3d, arrows_3d, equal_xyz, surfaces, xlabel3d="", ylabel3d="", zlabel3d="",
                           plot_title="", time_min=None, time_max=None,
                           y_min=None, y_max=None, z_min=None, z_max=None,
                           animate3d_duration="20", function_surfaces=None):
        """Save/Print가 공통으로 쓰는, 파일로 직접 렌더링하는 부분만 뽑은 버전
        (_execute_3d_plot의 화면(interactive) 전용 코드와 outfile/fmt만 다름).

        [추가 - 요청] "저장도 animation으로 되게 하면 됨" - fmt이 "gif"면(Save
        다이얼로그에서 Animated GIF를 골랐다는 뜻 - Animate 체크박스와 무관하게
        GIF 확장자 선택 자체가 신호) 2D의 "Save GIF"와 동일하게 create_3d_
        animation_script로 애니메이션 GIF를 만든다."""
        # [수정 - 버그] blank Plot Title/axis title이 폴백값으로 되돌아가던
        # 문제 - _execute_3d_plot과 동일하게 수정(위 주석 참고).
        title_for_plot = (plot_title or "").strip()
        generator = GnuplotGenerator(self.plot_dir)
        if fmt.lower() == "gif":
            try:
                _duration_sec = float((animate3d_duration or "20").strip())
            except ValueError:
                _duration_sec = 20.0
            generator.create_3d_animation_script(
                curves, outfile,
                xlabel=xlabel3d, ylabel=ylabel3d, zlabel=zlabel3d,
                title=title_for_plot,
                xlog=self.xlog_var.get(), ylog=self.y1log_var.get(), zlog=self.y2log_var.get(),
                rot_x=rot_x, rot_z=rot_z, style=style, palette=palette, colorbox=colorbox,
                equal_xyz=equal_xyz, surfaces=surfaces, function_surfaces=function_surfaces,
                time_min=time_min, time_max=time_max,
                y_min=y_min, y_max=y_max, z_min=z_min, z_max=z_max,
                duration_sec=_duration_sec, gif_path=outfile,
            )
            return
        generator.create_3d_script(
            curves, outfile, fmt=fmt,
            xlabel=xlabel3d, ylabel=ylabel3d, zlabel=zlabel3d,
            title=title_for_plot,
            xlog=self.xlog_var.get(), ylog=self.y1log_var.get(), zlog=self.y2log_var.get(),
            rot_x=rot_x, rot_z=rot_z, style=style, palette=palette, colorbox=colorbox,
            annotations_3d=annotations_3d, arrows_3d=arrows_3d, equal_xyz=equal_xyz,
            surfaces=surfaces, function_surfaces=function_surfaces, time_min=time_min, time_max=time_max,
            y_min=y_min, y_max=y_max, z_min=z_min, z_max=z_max,
        )

    def _save_3d_plot(self, curves, rot_x, rot_z, style, palette, colorbox, annotations_3d, arrows_3d,
                       equal_xyz=False, surfaces=None, xlabel3d="", ylabel3d="", zlabel3d="",
                       plot_title="", time_min=None, time_max=None,
                       y_min=None, y_max=None, z_min=None, z_max=None,
                       animate3d=False, animate3d_duration="20", function_surfaces=None):
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
            # [추가 - 요청] "저장도 animation으로 되게" - GIF 확장자를 고르면
            # (Animate 체크박스와 무관하게) _generate_3d_file이 애니메이션
            # GIF로 만든다(2D의 별도 "Save GIF" 버튼과 달리, 3D는 이 Save
            # 다이얼로그 하나에서 확장자 선택만으로 통일).
            ("Animated GIF (*.gif)", "*.gif"),
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
                                    y_min, y_max, z_min, z_max, animate3d_duration=animate3d_duration,
                                    function_surfaces=function_surfaces)
        except Exception as e:
            messagebox.showerror("저장 오류", f"3D Plot 저장 중 오류가 발생했습니다:\n{e}")
            return
        self.update_plot_file_list()
        messagebox.showinfo("완료", f"저장했습니다: {os.path.basename(selected_path)}")

    def _print_3d_plot(self, curves, rot_x, rot_z, style, palette, colorbox, annotations_3d, arrows_3d,
                        equal_xyz=False, surfaces=None, xlabel3d="", ylabel3d="", zlabel3d="",
                        plot_title="", time_min=None, time_max=None,
                        y_min=None, y_max=None, z_min=None, z_max=None,
                        animate3d=False, animate3d_duration="20", function_surfaces=None):
        """[추가] "3D Plot도 인쇄 지원" - 2D PRINT와 동일하게 EMF를 만들어
        프린터로 직접 그린다(_print_emf_and_cleanup/_pick_printer_dialog 재사용).
        2D처럼 어떤 plot을 고를지/용지 방향을 다시 묻는 절차는 3D 다이얼로그가
        이미 그 자리에서 설정을 받은 뒤라 생략하고 프린터만 고른다.

        [주의] animate3d/animate3d_duration은 여기서는 무시한다 - 인쇄는
        항상 정적인 한 페이지(EMF)라 애니메이션 개념이 없음(_collect_3d_state가
        Plot/Save/Print 세 버튼에 공통으로 쓰이는 튜플이라 시그니처만
        맞춰준다)."""
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
                                    y_min, y_max, z_min, z_max, function_surfaces=function_surfaces)
        except Exception as e:
            messagebox.showerror("인쇄 오류", f"인쇄용 파일 생성 중 오류가 발생했습니다:\n{e}")
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

            abs_dat_path = os.path.abspath(dat_file)
            # [수정 - 사용자 보고 버그] "같은 물리 파일인데 실행할 때마다
            # temp_sorted 해시가 달라짐" - 근본 원인은 self.cwd(=os.getcwd())
            # 가 CathPlot을 "어떻게 실행했는지"(exe 더블클릭 위치, 바로가기
            # 시작 위치 등)에 따라 실행마다 달라질 수 있다는 것 자체가 아니라
            # (그건 의도된 동작 - 아래 참고), os.path.abspath()가 만드는
            # 경로 "문자열"이 대소문자/짧은 8.3 경로 표기/심볼릭 링크·정션
            # 등으로 같은 실제 파일을 가리켜도 다르게 나올 수 있다는 점.
            # [주의 - 사용자 설명] 여기서 dat_file을 "어떤 파일로 볼지"
            # 자체(cwd 기준 상대경로 해석)는 의도적으로 그대로 둬야 함 -
            # "cwd 이후 폴더 구조는 같지만 dat 파일은 case마다 실제로 다른
            # 물리 파일"이 주된 사용 방식이라, 다른 case 폴더에서 실행하면
            # 그 case 자신의 dat를 가리켜야 정상이다(예전 case의 파일을
            # 계속 참조하면 오히려 더 심각한 오류가 됨 - 한 번 시도했다가
            # 되돌림). 대신 해시를 만들 때만 os.path.realpath(symlink/정션
            # 실제 경로로 해석)+os.path.normcase(Windows에서 대소문자 통일)
            # 로 정규화해서, 같은 실제 파일이면 문자열 표기가 달라도 항상
            # 같은 해시가 나오게 한다 - "어떤 파일을 쓸지"는 안 바뀌고
            # "그 파일을 무엇으로 해시할지"만 안정화됨.
            _hash_path = os.path.normcase(os.path.realpath(abs_dat_path))

            # [수정 - 요청 철회] "원본 dat 폴더에 두자"는 처음 방향을 다시
            # plot_dir/temp_sorted로 되돌림 - 실제로는 원본 dat 파일들이
            # 서로 다른 여러 폴더(공유 시뮬레이션 결과 폴더 등)에 흩어져
            # 있는 경우가 많아서, 그 폴더마다 매번 temp_sorted가 새로
            # 생기고 흔적이 여기저기 남는 게 더 문제라고 판단함. 대신
            # "CathPlot을 닫을 때 이 폴더를 지울지 말지"는 사용자가 직접
            # 고를 수 있는 옵션(delete_temp_on_close_var, 기본값 꺼짐)으로
            # 뺐다 - on_closing 쪽 수정 참고.
            temp_dir = os.path.join(self.plot_dir, "temp_sorted")
            os.makedirs(temp_dir, exist_ok=True)

            # [수정 - 버그] 파일명(base_name)만으로 임시 정렬 파일 이름을 정해서,
            # 서로 다른 폴더에 있는 "같은 이름"의 dat 파일(예: A/out111.dat와
            # B/out111.dat)을 같은 세션에서 같이 쓰면 temp_sorted 캐시가 서로
            # 덮어써서 경고 없이 잘못된 데이터를 plot에 쓰는 심각한 문제가
            # 있었음("파일명이 같을 때 sorted 파일이 덮어써진다" 실측 확인).
            #
            # [수정 - 버그, 근본적] "이전 plot과 현재 plot이 같은 폴더에
            # 유사 이름으로 있으면 같은 이름의 sorted.dat가 잘못 연계되지
            # 않는지? Batch Set은 self.file_rows(화면에 지금 열려있는 파일
            # 목록)를 안 쓰는데?" - 정확한 지적이었음. 아래 "겹칠 때만
            # 해시를 붙인다"는 판단 자체가 self.file_rows 기준이라, Batch
            # Set/Queue(각 Template의 dat 경로는 self.file_rows와 전혀
            # 무관하게 JSON에서 바로 읽음 - _build_plotdef_from_template_data
            # 참고)에서는 서로 다른 두 Template이 같은 파일명(다른 폴더)의
            # dat를 쓰면 이 충돌 감지가 전혀 작동하지 않아, 캐시가 조용히
            # 뒤섞일 위험이 실제로 있었다. 이제 세션/화면 상태와 무관하게
            # 해시(경로 기준, 항상 결정적)를 예외 없이 항상 붙인다 -
            # 그래야 같은 세션에 없던 "예전 plot"의 캐시나, self.file_rows를
            # 안 거치는 Batch/Template 경로에서도 절대 안 겹친다. 화면
            # LabelFrame 제목의 "-N"은 사람이 보기 편하라고 남겨두되(같은
            # 세션에서 동시에 열린 동일 파일명일 때만), 안전장치인 해시는
            # 이제 그 "-N" 계산과 무관하게 항상 계산한다.
            base_name = os.path.basename(dat_file)
            name_root, ext = os.path.splitext(base_name)
            path_hash = hashlib.md5(_hash_path.encode("utf-8")).hexdigest()[:6]

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
                sorted_filename = f"{name_root}-{_n if _n else 1}_{path_hash}_sortedX{x_col}{ext}"
            else:
                sorted_filename = f"{name_root}_{path_hash}_sortedX{x_col}{ext}"
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

                # [수정 - 요청] "#, !, **, =로 시작하면 comment, 중간의 !도
                # comment" - data_parser의 공용 규칙을 그대로 적용(inline
                # "!" 먼저 잘라낸 뒤 줄 전체 주석/빈 줄 여부 판정).
                data_rows = []
                for line in lines[dat_info.data_start_line:]:
                    stripped = strip_inline_comment(line).strip()
                    if is_comment_or_blank(stripped):
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
            text = strip_inline_comment(line).strip()
            if is_comment_or_blank(text):
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
            text = strip_inline_comment(line).strip()
            if is_comment_or_blank(text):
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

    def _get_window_client_screen_rect(self, hwnd):
        """[추가 - 요청] "PIP+Animation, 반투명(1~99%) + 화면 실시간 재생" -
        오버레이 창(_open_pip_overlay_window)을 gnuplot 창의 PIP 자리에
        픽셀 단위로 정확히 겹쳐야 하는데, _find_window_rect가 쓰는
        GetWindowRect는 제목표시줄/테두리까지 포함한 "창 전체" 좌표라 실제
        그림이 그려지는 영역(클라이언트 영역)과 다르다(제목표시줄만 30px
        안팎이라 그대로 쓰면 오버레이가 계속 위로 밀려 보임) - GetClientRect
        (클라이언트 영역 크기, 항상 좌상단이 0,0)와 ClientToScreen(그
        좌상단의 화면 절대좌표)을 조합해서 정확한 화면 좌표 사각형을
        구한다. 실패하면 None(호출자가 오버레이를 포기하도록)."""
        if not hwnd:
            return None
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            rect = wintypes.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return None
            pt = wintypes.POINT(0, 0)
            if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
                return None
            return (pt.x, pt.y, pt.x + rect.right, pt.y + rect.bottom)
        except Exception:
            return None

    def _read_anim_ctrl(self, ctrl_path):
        """[추가 - 요청] _write_anim_ctrl이 쓰는 제어 파일(gnuplot이 매
        프레임 load하는 것과 같은 파일)을 오버레이 창도 직접 읽어서, gnuplot
        본체와 완전히 같은 신호(Pause/Speed/Exit/재시작)를 따라가게 한다 -
        Animation Control 패널의 버튼은 이 파일만 갱신할 뿐 오버레이의
        존재를 몰라도 되므로 패널 쪽 코드는 전혀 안 건드려도 됨. 파일이
        아직 없거나(막 시작해서 gnuplot이 아직 안 만든 순간) 쓰는 도중이라
        일부만 읽히면 안전한 기본값으로 채운다."""
        result = {"paused_anim": False, "exit_anim": False, "frame_pause_anim": 0.02, "click_seq": 0}
        try:
            with open(ctrl_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return result
        for line in content.splitlines():
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            try:
                if key == "paused_anim":
                    result["paused_anim"] = val == "1"
                elif key == "exit_anim":
                    result["exit_anim"] = val == "1"
                elif key == "frame_pause_anim":
                    result["frame_pause_anim"] = float(val)
                elif key == "click_seq":
                    result["click_seq"] = int(val)
            except ValueError:
                pass
        return result

    def _open_pip_overlay_window(self, patches, geometry, ctrl_path, proc, plot_window_title):
        # [수정 - 버그, 재수정] "여러 창 Plot을 계속 눌러도 이전 창이 자동으로
        # 안 닫힘(여러 케이스를 나란히 비교하기 위함)"이 CathPlot의 기존
        # 원칙인데, 지난 수정에서 오버레이를 "전역에 하나만" 추적해서 새
        # PLOT을 그릴 때마다 무조건 지워버렸음 - 그 결과 여러 창을 나란히
        # 띄워 비교하면 "가장 최근 창에만 원이 남고, 이전 창들은 원이
        # 사라짐"이라는 실제로는 더 나쁜 회귀가 생겼다(사용자 재보고로 확인).
        # 원래 고치려던 문제(같은 창을 다시 그렸을 때 이전 오버레이가 안
        # 지워지고 남는 것)는 "같은 plot_window_title"일 때만 해당하므로,
        # 전역이 아니라 창 제목별로 추적해서 "같은 이름의 창"일 때만 이전
        # 걸 지우고, 다른 이름의 창(=다른 비교 케이스)은 서로 안 건드린다.
        if not hasattr(self, "_pip_overlay_windows"):
            self._pip_overlay_windows = {}
        _prev = self._pip_overlay_windows.get(plot_window_title)
        if _prev is not None:
            try:
                if _prev.winfo_exists():
                    _prev.destroy()
            except Exception:
                pass
            self._pip_overlay_windows.pop(plot_window_title, None)
        """[추가 - 요청] "PIP+Animation, 반투명(1~99%) + 화면 실시간 재생" -
        gnuplot 메인 창(터미널·기존 튜닝 전부 그대로, PIP 없이 메인 곡선만
        그림)은 전혀 안 건드리고, 미리 다 만들어둔(각 프레임에 이미 배경
        반투명까지 PIL로 합성된 - gnu_generator._build_pip_blended_frames
        참고) 작은 이미지 조각들을, 그 창의 PIP 자리 위에 정확히 겹치는
        테두리 없는 별도 창(overrideredirect)에 순서대로 갈아 끼운다.
        gnuplot 창 자체는 원래 그대로라 지금까지의 포커스/저장/인쇄 등
        튜닝이 전혀 위험해지지 않는다.

        동기화: gnuplot이 읽는 것과 동일한 제어 파일(ctrl_path)을 이
        오버레이도 직접 읽어서(파일 기반 IPC, gnuplot과 같은 프로토콜)
        Pause/Speed/Exit이 메인 창과 항상 같이 움직이게 한다. "다 끝난 뒤
        Resume으로 재시작"도 gnuplot 스크립트 자신의 규칙(그 시점의
        click_seq를 기억해두고, 그보다 큰 seq가 관측되면 처음부터 다시)을
        그대로 재현한다.

        [알려진 제한] 창을 못 찾거나(제목 매칭 실패) 이동/리사이즈하면
        오버레이가 어긋날 수 있음 - 지금 애니메이션 창은 항상 고정 위치로
        뜨고 크기 조정을 권장하지 않으므로 실사용에서는 크게 문제되지 않을
        것으로 봄."""
        try:
            from PIL import ImageTk, Image
        except ImportError:
            return None
        if not patches:
            return None

        # [수정 - 버그 발견] "오버레이 창이 1x1로 뜸" - gnuplot이 처음엔
        # "unknown" 터미널(범위 계산용, 화면에 안 보임)로 실행되다가 실제
        # "windows" 터미널로 전환되는 찰나(create_animation_script 참고)에
        # 창이 잠깐 작거나 불완전한 크기로 존재하는 순간이 있는 것으로
        # 실측 확인됨(재현: 몇 번 중 한 번 win_w/win_h가 1로 나옴, 재시도
        # 시 항상 정상값) - 클라이언트 영역이 너무 작으면(비정상) 잠깐
        # 대기 후 다시 조회한다.
        _hwnd, _client_rect = None, None
        if plot_window_title:
            for _attempt in range(6):
                _hwnd, _ = self._find_window_rect(plot_window_title, timeout_sec=3.0)
                _client_rect = self._get_window_client_screen_rect(_hwnd) if _hwnd else None
                if _client_rect and (_client_rect[2] - _client_rect[0]) > 50 and (_client_rect[3] - _client_rect[1]) > 50:
                    break
                self.root.update()
                time.sleep(0.25)
        if not _client_rect:
            return None
        cleft, ctop, cright, cbottom = _client_rect
        cw, ch = cright - cleft, cbottom - ctop
        if cw <= 0 or ch <= 0:
            return None

        page_w, page_h = geometry["page_w"], geometry["page_h"]
        sx, sy = cw / page_w, ch / page_h
        ox_px = geometry["origin_x"] * page_w
        oy_px_top = (1.0 - (geometry["origin_y"] + geometry["size_h"])) * page_h
        ow_px = geometry["size_w"] * page_w
        oh_px = geometry["size_h"] * page_h

        win_x = int(round(cleft + ox_px * sx))
        win_y = int(round(ctop + oy_px_top * sy))
        win_w = max(int(round(ow_px * sx)), 1)
        win_h = max(int(round(oh_px * sy)), 1)

        overlay = tk.Toplevel(self.root)
        self._pip_overlay_windows[plot_window_title] = overlay
        overlay.overrideredirect(True)
        try:
            overlay.attributes("-topmost", True)
        except Exception:
            pass
        # [추가 - 요청] "반투명일 때 in-plot이 화면에 고정되고, 고정된 내용이
        # 사각형 모양으로 보임" - 원/타원이면 gnu_generator가 그 바깥을
        # PIP_OVERLAY_CHROMA_KEY로 채워서 넘겨주므로(_chroma_mask_patch),
        # 여기서 그 색만 진짜 투명(-transparentcolor, Windows Tk 전용)으로
        # 뚫는다. 그러면 이제 정지된 스냅샷이 아니라 실시간으로 그 자리의
        # 실제 화면이 그대로 비쳐 보인다(rect는 애초에 전체가 내용이라
        # 손댈 필요 없음).
        _clip_shape = str(geometry.get("clip_shape", "rect")).strip().lower()
        if _clip_shape in ("circle", "ellipse"):
            try:
                _hexkey = "#%02x%02x%02x" % PIP_OVERLAY_CHROMA_KEY
                overlay.attributes("-transparentcolor", _hexkey)
            except Exception as _tc_err:
                # [수정 - 진단] "여전히 원/타원 바깥이 보라색으로 그대로
                # 보임" 재현 보고를 받아서, 원인 후보 중 하나(-transparentcolor
                # 자체가 이 Tk/Windows 조합에서 지원 안 되거나 예외 발생)를
                # 조용히 넘기지 않고 경고로 남긴다 - 이게 뜬다면 근본 원인이
                # 확인되는 것이고, 안 뜨는데도 여전히 보라색이면 다른 원인
                # (색상 정밀도 등)을 봐야 한다는 뜻이 됨.
                self.warnings.append(
                    f"PIP 화면 오버레이의 투명 처리(-transparentcolor)가 이 환경에서 지원되지 않아 "
                    f"원/타원 바깥이 배경색 그대로 보일 수 있습니다 ({type(_tc_err).__name__}: {_tc_err})."
                )
        # [수정 - 버그 발견] "오버레이 창이 1x1로 뜸" - geometry()로 크기를
        # 먼저 지정해도, 그 뒤에 자식 위젯(label)을 pack()하면 Tk가 "내용에
        # 맞춰 창 크기를 다시 계산"해버려서(이미지가 아직 안 채워진 빈
        # Label의 자연 크기 = 사실상 0에 가까움) 방금 지정한 크기가 조용히
        # 덮어써지는 것을 실측으로 확인함 - pack_propagate(False)로 "자식
        # 크기에 맞춰 창을 다시 줄이지 말라"고 명시하고, 이미지까지 다 채운
        # 뒤 geometry()를 한 번 더 호출 + update_idletasks()로 확정한다
        # (update_idletasks 없이는 override-redirect 창의 재적용된 geometry가
        # 실제로 반영되지 않는 것을 실측으로 확인함 - 일반 창과 다른 부분).
        overlay.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")
        overlay.pack_propagate(False)

        _photo_frames = []
        for p in patches:
            # [수정 - 버그] "원 가장자리에 보라색 테두리가 보이고, 시간이
            # 지날수록 원과 사각형 사이가 전부 보라색으로 참" - resize()의
            # 기본 보간 필터(부드럽게 섞는 방식)가 크로마키 순수색과 주변
            # 실제 내용 색을 섞어버려서, 그 경계 픽셀들이 더 이상
            # PIP_OVERLAY_CHROMA_KEY와 정확히 일치하지 않게 됨 ->
            # -transparentcolor는 "정확히 그 색"만 투명 처리하므로, 섞인
            # 경계 픽셀은 투명 처리가 안 되고 그대로 불투명하게 보임(보라색
            # 테두리, 그리고 크기가 자주 안 맞아 매 프레임 resize가 걸리는
            # Animation에서는 이게 반복 누적돼 점점 두드러져 보였던 것).
            # NEAREST(보간 없이 가장 가까운 픽셀 그대로 복사)로 바꾸면 색이
            # 섞이지 않아 경계가 항상 순수한 크로마키색 아니면 순수한 내용색
            # 둘 중 하나로만 유지됨(약간 계단 형태로 보일 수 있으나 투명
            # 처리가 정확해지는 게 우선).
            _resized = p.resize((win_w, win_h), Image.NEAREST) if p.size != (win_w, win_h) else p
            _photo_frames.append(ImageTk.PhotoImage(_resized))

        label = tk.Label(overlay, bd=0, highlightthickness=0)
        label.pack(fill="both", expand=True)
        label.config(image=_photo_frames[0])
        overlay._pip_overlay_photo_frames = _photo_frames  # GC 방지(참조 유지)
        overlay.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")
        overlay.update_idletasks()

        state = {"idx": 0, "awaiting_restart": False, "finished_seq": 0, "stopped": False}

        def _on_overlay_destroy(event):
            if event.widget is overlay:
                state["stopped"] = True
                if self._pip_overlay_windows.get(plot_window_title) is overlay:
                    self._pip_overlay_windows.pop(plot_window_title, None)
        overlay.bind("<Destroy>", _on_overlay_destroy)

        _last_resync_t = {"t": 0.0}

        def _resync_overlay_position():
            """[추가 - 요청] "반투명일 때 in-plot이 화면에 고정되고, 전체
            창을 움직여도 화면에 고정됨(큰 문제)" - 예전엔 오버레이 창
            위치를 맨 처음 한 번만 계산하고 이후로는 다시 안 봤음(docstring의
            "[알려진 제한]" 참고, 실사용에서 창을 안 움직인다는 잘못된
            가정이었음이 확인됨) - 이제 _advance가 돌 때마다(단, 너무 잦은
            win32 호출을 피하려 150ms 이하 간격이면 건너뜀) 메인 gnuplot
            창의 현재 위치를 다시 조회해서 오버레이를 따라가게 한다. 크기
            (win_w/win_h, 즉 이미 리샘플해둔 _photo_frames)는 안 건드림 -
            크기 조정까지 실시간 대응하려면 프레임을 매번 다시 리샘플해야
            해서 비용이 크고, docstring에 이미 "크기 조정은 권장하지 않음"
            으로 문서화돼 있어 범위 밖으로 둔다(이동만 고침)."""
            nonlocal win_x, win_y
            if _hwnd is None:
                return
            _now = time.time()
            if _now - _last_resync_t["t"] < 0.1:
                return
            _last_resync_t["t"] = _now
            try:
                _cr = self._get_window_client_screen_rect(_hwnd)
                if not _cr:
                    return
                _cl, _ct, _cr2, _cb = _cr
                _cw2, _ch2 = _cr2 - _cl, _cb - _ct
                if _cw2 <= 50 or _ch2 <= 50:
                    return
                _sx2, _sy2 = _cw2 / page_w, _ch2 / page_h
                _nx = int(round(_cl + ox_px * _sx2))
                _ny = int(round(_ct + oy_px_top * _sy2))
                if (_nx, _ny) != (win_x, win_y):
                    win_x, win_y = _nx, _ny
                    overlay.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")
            except Exception:
                pass

        def _advance():
            if state["stopped"] or not overlay.winfo_exists():
                return
            _resync_overlay_position()
            if proc is not None and proc.poll() is not None:
                try:
                    overlay.destroy()
                except Exception:
                    pass
                return
            # [추가 - 요청] "정적(비-Animation) 화면 PLOT에도 PIP 반투명
            # 오버레이" - ctrl_path가 없으면(애니메이션이 아니라 프레임이
            # 하나뿐인 정적 조각) 진행/재시작 로직 자체가 의미 없으므로
            # 건너뛰고, 메인 창(proc)이 살아있는 동안만 조용히 유지한다
            # (이미지는 이미 처음에 한 번 채워져 있음 - 아래 label.config 참고).
            if ctrl_path is None:
                # [수정 - 요청] "떠 있는 듯한 in-Plot 창이 조금 늦게 main
                # plot 따라 다님" - 정적(비-Animation) 케이스는 이 500ms
                # 주기가 곧 위치 재동기화(_resync_overlay_position) 주기
                # 이기도 해서, 창을 계속 움직이면 최대 0.5초까지 밀려
                # 보였다. 100ms로 줄여서 체감 지연을 크게 줄인다(내부
                # _resync_overlay_position의 150ms 스로틀도 100ms로 같이
                # 낮춰서 실제로 매 tick마다 갱신되게 함 - 아래 참고).
                overlay.after(100, _advance)
                return
            ctrl = self._read_anim_ctrl(ctrl_path)
            if ctrl["exit_anim"]:
                try:
                    overlay.destroy()
                except Exception:
                    pass
                return
            _seq = ctrl["click_seq"]

            if state["awaiting_restart"]:
                if _seq > state["finished_seq"]:
                    state["idx"] = 0
                    state["awaiting_restart"] = False
                else:
                    overlay.after(300, _advance)  # gnuplot 쪽 재시작 대기 폴링(0.3초)과 같은 주기
                    return

            if not ctrl["paused_anim"]:
                label.config(image=_photo_frames[state["idx"]])
                if state["idx"] >= len(_photo_frames) - 1:
                    state["finished_seq"] = _seq
                    state["awaiting_restart"] = True
                else:
                    state["idx"] += 1
            _fp = ctrl["frame_pause_anim"]
            overlay.after(max(int(_fp * 1000), 1), _advance)

        _advance()
        return overlay

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

        # [추가 - 요청] "실행 중인 Animation의 ctrl/status 파일을 Clean Past
        # Plots에서 실수로 지우면 재생이 깨짐" - 지금 이 패널이 살아있는 동안
        # 두 파일 경로를 "사용 중" 목록에 등록해서, open_delete_dialog가 이
        # 목록에 있는 건 아예 선택 대상에서 뺄 수 있게 한다(경고보다 안전한
        # "애초에 목록에 안 보이게"). 패널이 어떤 방식으로 닫히든(Exit 버튼,
        # 창 X, gnuplot 강제종료 후 수동으로 닫음) <Destroy> 이벤트는 항상
        # 한 번 발생하므로 거기서 등록 해제한다.
        if not hasattr(self, "_active_anim_files"):
            self._active_anim_files = set()
        self._active_anim_files.add(os.path.abspath(ctrl_path))
        if status_path:
            self._active_anim_files.add(os.path.abspath(status_path))

        def _unregister_anim_files(event=None):
            self._active_anim_files.discard(os.path.abspath(ctrl_path))
            if status_path:
                self._active_anim_files.discard(os.path.abspath(status_path))

        def _bump():
            # [추가 - 요청] 버튼을 누를 때마다 1씩 증가 - gnuplot이 "끝난
            # 시점 이후로 버튼이 한 번 더 눌렸는지"를 이 값으로 감지해서
            # Progress 100% 뒤에 Resume을 누르면 처음부터 재생하게 한다.
            state["seq"] += 1
            return state["seq"]

        panel = tk.Toplevel(self.root)
        panel.title("Animation Control")
        panel.resizable(False, False)
        panel.bind("<Destroy>", _unregister_anim_files, add="+")
        # [수정 - 요청] "Anim Control 창이 맨 위가 아님" - 새로 만든 Toplevel은
        # CathPlot(우리 앱) 안에서는 위로 오지만, 별도 프로세스인 gnuplot.exe
        # 창 등 "다른 애플리케이션" 위로는 보장이 안 됨(Windows 포커스
        # 스틸링 방지 정책과 같은 이유) - 명시적으로 topmost를 걸어준다.
        try:
            panel.attributes("-topmost", True)
        except Exception:
            pass
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
            # [수정 - 사용자 보고 버그] "Exit Animation을 누르면 plot 창
            # 자체가 사라짐(심각한 문제)" - 이전 수정(코드 리뷰로 발견)이
            # "즉시 종료함(창이 닫힘)"이라는 설명서 문구를 그대로 구현하려고
            # proc.terminate()로 gnuplot 프로세스 자체를 죽였는데, 그 창이
            # 곧 메인 plot 창이라 애니메이션만 멈추려 한 것인데 plot 결과
            # 전체가 같이 사라져버림 - 사용자가 원하는 동작은 "애니메이션만
            # 멈추고 plot 창은 그대로 유지"이므로 원래 방식(exit_flag만
            # 써서 gnuplot이 스스로 루프를 빠져나가 "pause mouse close"로
            # 넘어가게 함 - 창은 그대로 떠 있고 사용자가 직접 닫을 수 있음)
            # 으로 되돌린다.
            self._write_anim_ctrl(ctrl_path, False, state["frame_pause"], _bump(), exit_flag=1)
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
            # [수정 - 요청] "선택한 순서대로 curve를 그려주기(Legend box 순서에도
            # 연동)" - 예전엔 selected_y1_vars/selected_y2_vars 딕셔너리 순서
            # (=표에 나열된 순서, 파일 로드순+변수번호순)를 그대로 썼는데,
            # 이제 클릭(선택)한 순서(_ordered_selected_keys)를 그대로 따른다.
            # curves 리스트 순서가 곧 legend에 그려지는 순서이기도 해서(legend는
            # plotdef.curves를 그대로 순회함), 이 한 곳만 바꾸면 legend도 자동으로
            # 같이 따라옴.
            ordered_keys, active_y1_set, active_y2_set = self._ordered_selected_keys()

            if not ordered_keys:
                messagebox.showwarning("경고", "그릴 Y 변수를 하나 이상 선택해주세요.")
                return

            # [추가 - 사용자 보고 버그] "Legend1/Legend2 순서 독립적으로" -
            # 전체 그리기 순서(ordered_keys)와는 별개로, 각 Legend 박스 "안"의
            # 표시 순서는 legend별 독립 순서(_legend_order)를 따로 반영한다 -
            # CurveDefinition.legend1_order/legend2_order(정수 정렬키)로 넘겨
            # gnu_generator가 각 박스를 그 값 기준으로 따로 정렬하게 함.
            _legend1_index = {k: i for i, k in enumerate(self._legend_ordered_keys("1", ordered_keys))}
            _legend2_index = {k: i for i, k in enumerate(self._legend_ordered_keys("2", ordered_keys))}

            curves = []
            temp_curves_info = []

            for key in ordered_keys:
                d_file, out_no = key.split("||")
                axis = "y1" if key in active_y1_set else "y2"
                temp_curves_info.append((d_file, int(out_no), self.legend_vars[key].get(), axis, key))

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

                # [추가 - 사용자 질문/요청] "PIP inset을 다른 plot/.plt 파일에서
                # 불러올 때, 원본 dat 파일 경로가 기록돼야" - dat_file(위
                # target_dat_file)은 resort_dat_file이 만든 임시 정렬 캐시라
                # 다른 기기/세션엔 없을 수 있음 - 원본(d_file)을 cwd 기준
                # 상대경로로 같이 넘겨서, gnu_generator가 .plt에 복구용 주석을
                # 남기게 한다(사용자 확인: 절대경로는 기기마다 다르지만
                # 상대경로는 프로젝트 폴더 구조를 유지하면 보통 남아있음).
                try:
                    _orig_rel = os.path.relpath(d_file, self.cwd)
                except ValueError:
                    _orig_rel = d_file

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
                    legend1_order=_legend1_index.get(key, 0), legend2_order=_legend2_index.get(key, 0),
                    marker_shape=_marker_shape, marker_size=_marker_size, marker_max_count=_marker_max_count,
                    smooth_csplines=self.smooth_csplines_vars[key].get() if key in self.smooth_csplines_vars else False,
                    orig_dat_file=_orig_rel,
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
            elif self.plot_overwrite_var.get():
                # [추가 - 사용자 요청] "같은 이름으로 계속 덮어쓰기 옵션" -
                # 항상 "_1"로 고정해 번호를 증가시키지 않고, 파일 존재 여부와
                # 무관하게(=덮어쓰기 의도가 명확하므로) 충돌 확인 팝업 없이
                # 곧바로 그 자리에 다시 쓴다.
                next_id = 1
                base_name = f"{safe_title}_{next_id}"
                outfile = os.path.join(
                    self.plot_dir,
                    f"{base_name}.plt" if target == "screen" else f"{base_name}.{fmt}"
                )
                self.title_counters[safe_title] = next_id
                # [수정 - 사용자 보고 버그] "덮어쓰기 후 replot하면 이전
                # 창이 안 닫히고 같은 이름 창이 또 생김" - 덮어쓰기는 항상
                # 같은 base_name을 쓰므로, 그 이름으로 이전에 열어둔 창이
                # 아직 살아있으면(프로세스가 아직 안 끝났으면) 새로 열기
                # 전에 먼저 닫는다(다른 이름의 창들은 비교용으로 그대로
                # 둔다는 기존 방침은 그대로 유지 - 이 이름 하나만 정리).
                if target == "screen":
                    _prev_proc = self.plot_process_by_title.get(base_name)
                    if _prev_proc is not None and _prev_proc.poll() is None:
                        try:
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(_prev_proc.pid)], capture_output=True, **_no_console_kwargs())
                        except Exception:
                            pass
                        if _prev_proc in self.plot_processes:
                            self.plot_processes.remove(_prev_proc)
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
                y2tics_on=self.y2tics_on_var.get(),
                ytics_on=self.ytics_on_var.get(),
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
                function_curves=self._build_function_curve_defs(),
                annotations=self._collect_annotations(),
                arrows=self._collect_arrows(),
                circles=self._collect_circles(),
                is_print_mode=(mode == "Batch"),
                extra_gnuplot=self.raw_gnuplot_text.get("1.0", "end-1c"),
                pip=self._resolve_pip_config(),
            )

            # [추가 - 요청] "돋보기(magnifier)" - pip["magnifier"]가 켜져
            # 있으면, 중심/반지름/배율만으로 실제 xmin/xmax/y1min/y1max/
            # y2min/y2max/size_w/size_h를 자동 계산해 pip dict를 덮어쓰고,
            # main plot 위에 표시할 점선 원을 circles 주석 목록에 추가한다.
            # plotdef가 막 만들어진 직후(curves/x_output_no/xlog 등 계산에
            # 필요한 값이 전부 갖춰진 시점)에 해야 정확하다 - 아래 create_
            # script/create_animation_script 호출들은 전부 circles=getattr(
            # plotdef, "circles", [])로 매번 새로 읽으므로, 여기서 plotdef.
            # circles를 갱신해두면 그 호출들에 자동으로 반영된다.
            _mag_cfg = (plotdef.pip or {}).get("magnifier") or {}
            if _mag_cfg.get("enabled"):
                try:
                    _mag_gen = GnuplotGenerator(self.plot_dir)
                    _mag_pip, _mag_circle = _mag_gen.compute_magnifier_pip(plotdef, _mag_cfg, existing_pip=plotdef.pip)
                    if _mag_pip is not None:
                        plotdef.pip = _mag_pip
                        plotdef.circles = list(plotdef.circles or []) + [_mag_circle]
                except Exception as _mag_err:
                    # [주의] execute_plot_pipeline에는 누적 warnings 리스트가
                    # 없어(이 함수 범위엔 그런 속성/변수가 없음), 곧바로
                    # 메시지박스로 알린다(다른 즉석 입력 오류 처리와 동일한
                    # 방식) - 돋보기만 조용히 꺼진 채(수동 xmin/xmax 등은
                    # 그대로 살아있는 원래 pip dict) 나머지 plot은 계속 진행.
                    messagebox.showwarning(
                        "돋보기 계산 실패",
                        f"중심/반지름 값을 확인해주세요(숫자여야 함, 반지름>0).\n{_mag_err}"
                    )

            # 5. Gnuplot 스크립트 생성 및 실행 (GnuplotGenerator의 실제 API인 create_script 사용)
            if mode == "Interactive":
                # [수정] 예전엔 새 창을 열기 전에 추적 중이던 이전 interactive 창들을
                # 무조건 강제로 닫았는데, 여러 케이스를 화면에 나란히 띄워 비교하고
                # 싶을 때도 있어서 이제는 그냥 두고 개수만 추적한다. 다만 너무 많이
                # 쌓이면(gnuplot_qt.exe 공유 드라이버 폰트 캐시가 느려지는 문제가
                # 있었으므로) 20개 이상이면 가장 먼저 연 창을 닫을지 물어본다.
                # [수정 - 사용자 요청] "그림 표준화하다보면 plot이 여럿 그려지는데
                # 10개는 너무 자주 물어봄 - 너무 많으면 Close All Plot으로 처리
                # 하면 되니 20개로 늘려줘요."로 10 -> 20 상향.
                alive = [p for p in getattr(self, "plot_processes", []) if p.poll() is None]
                self.plot_processes = alive
                if len(alive) >= 20:
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
            _will_animate = (fmt == "gif") or (
                getattr(self, "animate_var", None) is not None and self.animate_var.get() and fmt == "interactive"
            )
            # [추가 - 요청] "반투명(1~99%) + GIF" - GIF 저장은 화면 실시간
            # 재생과 달리 "완성된 프레임들"을 다루므로, 프레임마다 무거운 PDF
            # 후처리 없이도 진짜 배경 반투명을 만들 수 있다(gnu_generator.
            # create_pip_animation_gif_blended 참고 - "완전불투명 버전"과
            # "PIP 없는 메인만" 버전을 각각 gnuplot이 저비용으로(전체 프레임
            # 한 번에) 만든 뒤, 두 GIF의 프레임끼리 짝지어 PIL로만 섞음). 그래서
            # GIF 저장일 때만 _normalize_pip_for_animation의 "반투명이면 완전
            # 불투명/투명 중 하나로 강제" 질문을 건너뛰고 이 경로로 보낸다 -
            # 화면 실시간 재생은 여전히 완성된 프레임이 없어서(진행 중인 gnuplot
            # 창) 기존처럼 강제한다.
            def _resolve_pip_partial_opacity(_plotdef):
                _pip = getattr(_plotdef, "pip", None)
                if not (_pip and _pip.get("enabled")):
                    return None
                _praw = str(_pip.get("opacity", "")).strip()
                try:
                    _pval = float(_praw) if _praw else (100.0 if _pip.get("opaque", True) else 0.0)
                except (TypeError, ValueError):
                    _pval = 100.0
                if 0.0 + 1e-6 < _pval < 100.0 - 1e-6:
                    return max(0.0, min(100.0, _pval))
                return None

            # [수정 - 요청, 재수정] "네이티브 클리핑 경로 제거"를 한때 원/타원
            # 전체로 넓혔었는데(오버레이 창을 항상 쓰게), 그게 오히려 "원
            # PIP가 항상 별도 창으로 맨 위에 따로 뜨고 화질도 못 미침"이라는
            # 더 큰 문제였음이 확인됨 - 되돌림. Opacity가 이제 0/100 라디오
            # 버튼만 남아 진짜 반투명(1~99%)은 UI에서 아예 선택 불가능하므로,
            # 오버레이는 원래 목적(진짜 반투명일 때만) 그대로 이
            # _resolve_pip_partial_opacity 하나로 rect/원/타원 구분 없이
            # 충분하다 - 원/타원도 대부분 gnu_generator의 네이티브 경로를
            # 타서 메인 gnuplot 창에 rect와 동일하게 그려진다.

            _pip_gif_blend_opacity = _resolve_pip_partial_opacity(plotdef) if fmt == "gif" else None
            # [추가 - 요청] "반투명(1~99%) + 화면 실시간 재생" - GIF와 달리
            # 실시간 재생은 "완성된 프레임 묶음"이 없는(gnuplot이 그때그때
            # 그리는 살아있는 창) 구조라 프레임을 후처리로 섞을 대상 자체가
            # 없어서 예전엔 항상 완전 불투명/투명 중 하나로 강제했는데,
            # 이제 "메인 창은 그대로 두고 그 위에 이미 배경 반투명까지 합성
            # 해둔 PIP 조각만 별도의 작은 창으로 겹쳐서 갈아 끼우는" 방식
            # (_open_pip_overlay_window)으로 실제 반투명을 보여준다 - 메인
            # gnuplot 창 자체는 전혀 안 바뀌므로 기존 튜닝에 영향 없음.
            #
            # [수정 - 요청, 재수정] "원 PIP가 항상 별도 창으로 맨 위에 따로
            # 뜨고, 진하기도 rect에 못 미침" - 한때 원/타원이면 opacity와
            # 무관하게 항상 이 오버레이를 쓰도록(_resolve_pip_needs_overlay)
            # 넓혔었는데, 그게 바로 이 문제(분리된 느낌·잘못된 z-order·
            # 화질 저하)의 원인이었다. Opacity가 이제 UI에서 0/100 라디오
            # 버튼만 남아 진짜 반투명(1~99%) 자체가 선택 불가능해졌으므로,
            # 원래 목적(진짜 반투명일 때만 오버레이 필요)에 맞게
            # _resolve_pip_partial_opacity로 되돌린다 - 그러면 원/타원도
            # rect처럼 gnu_generator의 네이티브 경로를 타고 메인 gnuplot
            # 창에 직접, 같은 굵기/진하기로 그려진다(gnu_generator.py의
            # force_postprocess 관련 수정과 짝을 이룸).
            _pip_interactive_blend_opacity = (
                _resolve_pip_partial_opacity(plotdef)
                if (fmt == "interactive" and getattr(self, "animate_var", None) is not None and self.animate_var.get())
                else None
            )
            if _will_animate and _pip_gif_blend_opacity is None and _pip_interactive_blend_opacity is None:
                # [추가 - 요청] "PIP+Animation" - PIP가 켜져 있으면 원/타원
                # 클리핑/배경 반투명을 Animation이 지원 가능한 형태(사각형+
                # 완전불투명 또는 완전투명)로 정리한다 - _normalize_pip_for_
                # animation 참고. 사용자가 반투명 선택 메시지에서 취소를
                # 고르면 애니메이션 자체를 시작하지 않는다.
                plotdef = self._normalize_pip_for_animation(plotdef)
                if plotdef is None:
                    return
            _pip_overlay_result = None  # 실시간 재생 + 반투명일 때만 채워짐(아래에서 오버레이 창을 여는 데 씀)
            _pip_static_overlay_result = None  # 정적(비-Animation) 화면 PLOT + 반투명일 때만 채워짐
            if fmt == "gif":
                try:
                    duration_sec = float((self.animate_duration_var.get() or "20").strip())
                except ValueError:
                    duration_sec = 20.0
                if _pip_gif_blend_opacity is not None:
                    generator.create_pip_animation_gif_blended(
                        plotdef, outfile,
                        annotations=plotdef.annotations, arrows=plotdef.arrows,
                        circles=getattr(plotdef, "circles", []), duration_sec=duration_sec,
                    )
                else:
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
                if _pip_interactive_blend_opacity is not None:
                    # 먼저(메인 창을 열기 전에) PIP 조각들을 다 만들어둔다 -
                    # 실패하면(PIL 없음, 위치 계산 실패 등) 조용히 안전한
                    # 기본값(완전 불투명)으로 대체한다.
                    _pip_overlay_result = generator._build_pip_blended_frames(
                        plotdef, annotations=plotdef.annotations, arrows=plotdef.arrows,
                        circles=getattr(plotdef, "circles", []), duration_sec=duration_sec,
                        plot_dir_hint=self.plot_dir, build_full_frames=False,
                    )
                    _main_only_plotdef = copy.copy(plotdef)
                    if _pip_overlay_result is not None:
                        _main_only_plotdef.pip = {}
                    else:
                        _main_only_plotdef.pip = dict(plotdef.pip, opacity=100.0)
                    generator.create_animation_script(
                        _main_only_plotdef, outfile,
                        annotations=plotdef.annotations, arrows=plotdef.arrows,
                        circles=getattr(plotdef, "circles", []), duration_sec=duration_sec,
                    )
                else:
                    generator.create_animation_script(
                        plotdef, outfile,
                        annotations=plotdef.annotations, arrows=plotdef.arrows,
                        circles=getattr(plotdef, "circles", []), duration_sec=duration_sec,
                    )
            else:
                # [추가 - 요청] "정적(비-Animation) 화면 PLOT에서도 PIP 원/
                # 타원+부분 반투명(1~99%)이 제대로 보이게" - Animation의
                # 실시간 오버레이(_pip_interactive_blend_opacity)와 완전히
                # 같은 개념을 프레임이 하나뿐인 정적 버전으로 적용한다.
                # Batch/Save/Print(fmt != "interactive")는 이 오버레이 창을
                # 띄울 화면 자체가 없으므로 대상에서 제외 - 그 경로는
                # create_script/gnu_generator가 자체적으로 처리(PDF 계열은
                # 이미 정상, EMF/EPS는 안전하게 사각형+가까운 극값으로 대체
                # + 경고).
                _static_partial_opacity = _resolve_pip_partial_opacity(plotdef) if fmt == "interactive" else None
                if _static_partial_opacity is not None:
                    _pip_static_overlay_result = generator.build_pip_static_overlay_patch(
                        plotdef, annotations=plotdef.annotations, arrows=plotdef.arrows,
                        circles=getattr(plotdef, "circles", []), plot_dir_hint=self.plot_dir,
                    )
                    _main_only_plotdef = copy.copy(plotdef)
                    if _pip_static_overlay_result is not None:
                        _main_only_plotdef.pip = {}
                    else:
                        _main_only_plotdef.pip = dict(plotdef.pip, opacity=100.0)
                    generator.create_script(
                        _main_only_plotdef, outfile, fmt=fmt,
                        annotations=plotdef.annotations, arrows=plotdef.arrows,
                        circles=getattr(plotdef, "circles", [])
                    )
                else:
                    generator.create_script(
                        plotdef, outfile, fmt=fmt,
                        annotations=plotdef.annotations, arrows=plotdef.arrows,
                        circles=getattr(plotdef, "circles", [])
                    )
            # [수정 - 버그] "PLOT 경고 창에 같은 문구가 여러 번 반복됨" -
            # _render_pip_inset이 Animation 처리 중 여러 차례(probe/실제
            # 스크립트 등) 불려서 generator.warnings에 같은 경고가 여러 번
            # append됨 - 순서는 유지한 채 중복만 제거해서 보여준다.
            _all_warn = list(dict.fromkeys(_font_warn + generator.warnings))

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
                    # [수정 - 사용자 보고] "메시지 중 축설정(log scale, data
                    # 범위) 등은 유효하지 않는 메시지로 보임" - PIP+Animation
                    # EOD 크래시처럼 실제 원인이 축 설정/데이터 범위와 전혀
                    # 무관한 경우에도 이 문구가 항상 붙어서 오해를 줬음 -
                    # gnuplot의 실제 오류 내용(_err_detail)을 잡았으면 그
                    # 사실 그대로만 보여주고, 못 잡았을 때만(추측할 단서가
                    # 그것뿐이므로) 기존의 일반적인 추정 문구를 대신 보여준다.
                    if _err_detail:
                        _msg = f"gnuplot이 그래프를 그리지 못하고 바로 종료됐습니다.\n\ngnuplot 오류 내용:\n{_err_detail[:500]}"
                    else:
                        _msg = "gnuplot이 그래프를 그리지 못하고 바로 종료됐습니다.\n축 설정(특히 Log Scale)이나 데이터 범위를 확인해주세요."
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
                    if _pip_overlay_result is not None:
                        # [추가 - 요청] "반투명 + 화면 실시간 재생" - 메인
                        # 창(방금 뜬, PIP 없이 메인 곡선만 있는 그 창) 위에
                        # 미리 합성해둔 PIP 조각을 겹치는 오버레이 창을 연다.
                        # 컨트롤 패널과 같은 ctrl_path/proc을 그대로 넘겨서
                        # Pause/Speed/Exit이 항상 같이 움직이게 한다.
                        self._open_pip_overlay_window(
                            _pip_overlay_result["patches"], _pip_overlay_result,
                            generator.last_anim_ctrl_path, generator.last_process,
                            os.path.splitext(os.path.basename(outfile))[0],
                        )
                elif _pip_static_overlay_result is not None:
                    # [추가 - 요청] "정적(비-Animation) 화면 PLOT에도 PIP
                    # 반투명 오버레이" - Animation Control 패널은 필요 없지만
                    # (애니메이션이 아니므로), 겹치는 조각 창 자체는 같은
                    # 방식으로 연다(ctrl_path=None으로 넘겨 "진행/재시작"
                    # 로직 없이 메인 창이 살아있는 동안만 정적으로 유지).
                    self._open_pip_overlay_window(
                        [_pip_static_overlay_result["patch"]], _pip_static_overlay_result,
                        None, generator.last_process,
                        os.path.splitext(os.path.basename(outfile))[0],
                    )

            # [수정 - 버그] "PIP+Animation(spline 등 경고 포함) 중 멈춘 것처럼
            # 보임" - 이 경고창(messagebox.showwarning, 모달)이 예전엔 위
            # create_animation_script 직후 곧바로 떴는데, 그러면 그 뒤에 오는
            # Animation Control 패널/PIP 오버레이 창 띄우기가 사용자가 이
            # 경고를 닫을 때까지 전부 미뤄져서(같은 메인 스레드) 애니메이션
            # 컨트롤이 안 뜨고 멈춘 것처럼 보였음 - 경고 자체는 정보성이라
            # 어디서 띄우든 상관없으므로, 크래시 확인/컨트롤 패널·오버레이
            # 띄우기가 전부 끝난 뒤로 옮겨서 실제 애니메이션 UI가 먼저 보이게 한다.
            if _all_warn:
                # [수정 - 요청, 재수정] "CathPlot 메인 화면이 맨 위에 고정됨 -
                # 지금 Anim 중인 plot창이 맨 위에 나와야 함" - root 전체를
                # topmost로 올렸다 내리던 이전 수정이 바로 그 원인이었다
                # (Animation처럼 경고가 반복되는 상황에서 CathPlot 메인
                # 창이 활성 plot/Animation 창 위로 계속 튀어 올라옴).
                # messagebox 자체가 모달이라 원래도 포커스는 알아서 받으므로
                # root를 통째로 topmost로 만들 필요가 없었다 - 제거.
                messagebox.showwarning("PLOT 경고", "\n\n".join(_all_warn))

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
                self.plot_process_by_title[base_name] = generator.last_process

            if plotdef not in self.history_plots:
                self.history_plots.append(plotdef)

            self.update_plot_file_list()
            return outfile

        except Exception as e:
            messagebox.showerror("오류", f"plot 생성 중 오류가 발생했습니다: {e}")


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
                messagebox.showwarning("경고", "목록에서 plot을 하나 이상 선택해주세요.", parent=dialog)
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
                messagebox.showinfo("완료", f"멀티플롯을 생성했습니다: {os.path.basename(filepath)}")

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", pady=15)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=15)
        ttk.Button(btn_frame, text="Run Plot", command=on_execute).pack(side="right", padx=5)

    def execute_multi_plot_pipeline(self, selected_plot_defs, mode, custom_filepath=None, custom_format=None):
        if not selected_plot_defs:
            messagebox.showwarning("경고", "멀티플롯 실행을 위해 선택된 plot이 없습니다.")
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
        _all_warn = list(dict.fromkeys(([generator.last_size_warning] if generator.last_size_warning else []) + _font_warn + generator.warnings))
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
                # [수정 - 버그] "PLOT 경고 창에 같은 문구가 여러 번 반복됨" -
                # _render_pip_inset이 Animation 처리 중 여러 차례(probe/실제
                # 스크립트 등) 불려서 generator.warnings에 같은 경고가 여러 번
                # append됨 - 순서는 유지한 채 중복만 제거해서 보여준다.
                _all_warn = list(dict.fromkeys(_font_warn + generator.warnings))
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
            messagebox.showerror("인쇄 오류", f"인쇄용 파일 생성 중 오류가 발생했습니다:\n{e}")
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
            messagebox.showerror("인쇄 오류", f"프린터 목록을 가져오지 못했습니다: {e}")
            return None

        if not names:
            messagebox.showerror("인쇄 오류", "설치된 프린터를 찾을 수 없습니다.")
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
            self.root.after(0, lambda msg=err_msg: messagebox.showerror("인쇄 오류", msg))
        except Exception as e:
            try:
                err_msg = f"[{step}] 중 오류: {e}"
            except Exception:
                err_msg = f"[{step}] 중 알 수 없는 오류 (메시지를 표시할 수 없음)"
            self.root.after(0, lambda msg=err_msg: messagebox.showerror("인쇄 오류", msg))
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
            self.root.after(0, lambda msg=err_msg: messagebox.showerror("인쇄 오류", msg))
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
            messagebox.showerror("저장 오류", f"파일 저장 중 오류가 발생했습니다:\n{e}")
            return
        _all_warn = list(dict.fromkeys(_font_warn + generator.warnings))
        if _all_warn:
            messagebox.showwarning("SAVE 경고", "\n\n".join(_all_warn))
        self.update_plot_file_list()
        messagebox.showinfo("완료", f"저장했습니다: {os.path.basename(selected_path)}")

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

    def _register_batch_job(self, kind, count):
        """[추가 - 요청] Batch Set/Queue가 시작될 때 호출 - 실행 중 목록에
        표시용 이름(예: 'Batch Set (12개 항목, 14:32 시작)')을 등록하고,
        나중에 _unregister_batch_job으로 지울 때 쓸 job_id를 반환한다.
        여러 배치가 동시에 실행될 수 있으므로(잠금 없음, 의도된 동작) id는
        매번 새로 발급하며, dict 자체의 동시 접근은 _batch_job_lock으로
        보호한다."""
        with self._batch_job_lock:
            self._batch_job_seq += 1
            job_id = self._batch_job_seq
            started_at = time.strftime("%H:%M:%S")
            self._active_batch_jobs[job_id] = f"{kind} ({count}개 항목, {started_at} 시작)"
        return job_id

    def _unregister_batch_job(self, job_id):
        """_register_batch_job으로 등록했던 항목을 지운다. 반드시 self.root.after(0, ...)
        를 통해 메인 스레드에서 호출할 것(백그라운드 워커 스레드가 직접 dict를
        건드리지 않도록)."""
        with self._batch_job_lock:
            self._active_batch_jobs.pop(job_id, None)

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
        # -1. [추가 - 요청] "X 버튼으로 닫기 전에, 백그라운드로 실행 중인 Batch
        # Set/Queue가 있으면 이름을 보여주고 정말 종료할지 물어봐라" - 이 작업들은
        # 전부 daemon 스레드라 그냥 닫으면 남은 항목이 아무 경고 없이 통째로
        # 사라지므로(진행률 창도, batch_warnings.log도 남지 않음), 여기서 먼저
        # 확인한다. "아니오"를 누르면 종료 자체를 취소(return)하고 창을 그대로
        # 둔다 - 이후 단계(gnuplot 정리 등)는 전혀 진행하지 않음.
        active_jobs = list(self._active_batch_jobs.values())
        if active_jobs:
            job_lines = "\n".join(f"  - {name}" for name in active_jobs)
            proceed = messagebox.askyesno(
                "실행 중인 Batch 작업 있음",
                f"다음 작업이 아직 백그라운드에서 실행 중입니다:\n\n{job_lines}\n\n"
                "지금 CathPlot을 닫으면 이 작업은 끝까지 완료되지 못하고 "
                "즉시 중단됩니다(완료 안내창·경고 로그도 남지 않습니다).\n\n"
                "그래도 종료하시겠습니까?"
            )
            if not proceed:
                return

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

        # [수정 - 요청] "CathPlot을 닫으면 temp_sorted가 통째로 지워져서 저장해둔
        # .plt가 상대경로로 가리키던 sorted 파일을 재현 못 함" - 무조건
        # 삭제하던 것을 없애고, "종료 시 sorted 캐시 삭제" 체크박스
        # (delete_temp_on_close_var, 기본값 꺼짐)로 사용자가 직접 고르게
        # 했다. 켜져 있을 때만 예전처럼 지운다 - 꺼져 있으면(기본) 남아있는
        # 채로 종료되어 나중에 .plt를 다시 열어도 재현 가능.
        if self.delete_temp_on_close_var.get():
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
