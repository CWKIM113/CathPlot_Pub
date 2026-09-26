"""
======================================================================
CathPlot

Module:
    data_parser.py

Purpose:
    Parse CATHENA DAT file metadata.

Features:
    - Read OUTPUT definitions
    - Read signal names
    - Read signal multipliers
    - Read FORTRAN format line
    - Detect DATA section
    - Export metadata to JSON

Notes:
    OUTPUT #N corresponds to DATA column N+1.
    DATA column 1 is always Time.

    Multiple signal definitions under one OUTPUT are metadata only.
    DATA already contains the final calculated value.

Author:
    CWKim / ChatGPT

Version:
    1.0

======================================================================
"""

from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from pathlib import Path
import copy
import json
import os
import re
import threading


# ==========================================================
# COMMENT HANDLING (.dat 파일 공용)
# ==========================================================
# [추가 - 요청] "dat parsing에서 #, !, **, = 등으로 시작하면 comment이고
# 중간에도 ! 이후는 comment로 처리되고 있나요? 안 되어 있으면 반영해줘요" -
# 기존엔 "#"/"---"/"==="/"**"만(그것도 헤더 경계 탐색에서만) 일부 인식됐고,
# 실제 데이터 행 파싱(resort_dat_file 등)에서는 숫자 변환 실패 시 그 줄을
# 통째로 버리는 것으로 우연히 비슷하게 동작했을 뿐 의도된 주석 규칙은
# 아니었음(중간(inline) 주석은 전혀 없었음). 아래 두 함수로 dat 파싱
# 전체(헤더 경계 탐색 + 실제 데이터 행 읽기, Cathena/Generic 공통)와
# cathplot_gui.py의 데이터 행 읽기 루프(resort_dat_file 등)에서 공유해서
# 쓴다.
COMMENT_LINE_PREFIXES = ("#", "!", "**", "=")


def is_comment_or_blank(line):
    """줄 전체가 주석이거나 빈 줄이면 True (앞뒤 공백 제거 후 판정)."""
    text = line.strip()
    return (not text) or text.startswith(COMMENT_LINE_PREFIXES)


def strip_inline_comment(line):
    """"!" 이후(그 줄 안에서 처음 나오는 지점부터 끝까지)를 주석으로 보고
    잘라낸다 - 데이터 값 자체에 "!"가 올 일이 없어 안전(다른 마커(#/**/=)는
    줄 맨 앞에서만 주석으로 취급 - 요청대로 inline은 "!"만 적용)."""
    idx = line.find("!")
    return line if idx < 0 else line[:idx]


# ==========================================================
# 데이터 행 분리/숫자 변환 공용 헬퍼
# ==========================================================
# [추가 - 요청] "실행속도/중복성 검토" - 데이터 행을 컬럼으로 나누는
# re.split(r'[,\s]+', ...)와 "D 지수 표기/천단위 콤마"를 처리하는
# float(tok.replace("D","E").replace("d","e").replace(",",""))가 gnu_generator.py/
# cathplot_gui.py 곳곳(8군데 이상)에 똑같이 복사돼 있었고, 매 행마다 정규식
# 캐시 조회 + replace 3번을 거쳐 큰 파일에서 가장 비싼 구간이었음. 결과가
# 완전히 같은 더 빠른 공용 함수로 모은다.
_FIELD_SPLIT_RE = re.compile(r"[,\s]+")


def split_fields(text):
    """re.split(r'[,\\s]+', text)와 항상 같은 결과를 돌려준다. 앞/뒤가 콤마나
    공백이 아닌(=호출부가 strip()한 보통의 데이터 행) 경우에는 결과가 같다는
    것이 보장되는 str.split() 경로로 빠르게 처리하고, 그 밖의 드문 경우
    (빈 문자열, 앞/뒤 콤마 등 - 정규식은 이때 빈 문자열 필드를 만듦)는 원래
    정규식을 그대로 쓴다."""
    if not text or text[0] == "," or text[-1] == "," or text[0].isspace() or text[-1].isspace():
        return _FIELD_SPLIT_RE.split(text)
    return text.replace(",", " ").split()


def parse_number(tok):
    """FORTRAN "D" 지수 표기(1.0D+03)와 천단위 콤마를 허용하는 float 변환.
    float(tok.replace("D","E").replace("d","e").replace(",",""))와 같은 결과
    (실패 시 ValueError) - "D"/"d"/","가 들어간 문자열은 float()가 절대
    받아들이지 않으므로, 먼저 그대로 변환해보고 실패할 때만 치환한다."""
    try:
        return float(tok)
    except ValueError:
        return float(tok.replace("D", "E").replace("d", "e").replace(",", ""))


def _file_cache_key(path):
    """파일 내용이 바뀌면 달라지는 캐시 키(정규화 절대경로, 수정시각, 크기)."""
    st = os.stat(path)
    return (os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size)


class _LRUCache:
    """스레드 안전한 작은 LRU 캐시(Batch가 여러 스레드에서 동시에 plot을 만듦)."""

    def __init__(self, maxsize):
        self.maxsize = maxsize
        self._data = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            val = self._data.get(key)
            if val is not None:
                self._data.move_to_end(key)
            return val

    def put(self, key, val):
        with self._lock:
            self._data[key] = val
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)


class DatTable:
    """dat 파일의 실제 데이터 행(data_start_line 이후, 줄 전체 주석/빈 줄을
    뺀 뒤 inline "!" 주석을 잘라내고 strip한 텍스트)과, 요청된 컬럼의 숫자
    값을 한 번만 계산해 보관한다. column()이 돌려주는 리스트는 texts와 같은
    길이이며, 그 행에 해당 컬럼이 없거나 숫자로 못 읽으면 None이다 - 기존
    루프들의 "len(fields) <= max_col이면 건너뜀 / ValueError면 건너뜀"
    조건이 곧 "필요한 컬럼 중 하나라도 None이면 건너뜀"과 같다."""

    def __init__(self, texts):
        self.texts = texts
        self._cols = {}
        self._lock = threading.Lock()
        # 호출부가 이 파일 내용에서 파생된 계산 결과(예: 컬럼 min/max)를
        # 기억해둘 수 있는 자리 - 파일이 바뀌면 table 자체가 새로 만들어진다.
        self.memo = {}

    def column(self, idx):
        return self.columns(idx)[0]

    def columns(self, *idxs):
        missing = [i for i in dict.fromkeys(idxs) if i not in self._cols]
        if missing:
            with self._lock:
                missing = [i for i in missing if i not in self._cols]
                if missing:
                    self._build(missing)
        return tuple(self._cols[i] for i in idxs)

    def _build(self, idxs):
        outs = {i: [] for i in idxs}
        for text in self.texts:
            fields = split_fields(text)
            n = len(fields)
            for i, out in outs.items():
                if 0 <= i < n:
                    try:
                        out.append(parse_number(fields[i]))
                    except ValueError:
                        out.append(None)
                else:
                    out.append(None)
        self._cols.update(outs)


_PARSE_CACHE = _LRUCache(64)
_TABLE_CACHE = _LRUCache(6)


def load_dat_table(filename):
    """(DatFile 메타데이터, DatTable)을 돌려준다 - 파일 내용이 바뀌지 않는 한
    캐시를 재사용한다(한 번 plot할 때 같은 파일을 curve/축/마커 계산마다
    여러 번 다시 읽고 파싱하던 중복을 없앰). 읽기 실패 시 예외를 그대로 낸다."""
    key = _file_cache_key(filename)
    cached = _TABLE_CACHE.get(key)
    if cached is not None:
        return cached
    dat_info = CathenaDatParser().parse(filename)
    with open(filename, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    texts = []
    for row in lines[dat_info.data_start_line:]:
        text = strip_inline_comment(row).strip()
        if not is_comment_or_blank(text):
            texts.append(text)
    result = (dat_info, DatTable(texts))
    _TABLE_CACHE.put(key, result)
    return result


# ==========================================================
# DATA CLASSES
# ==========================================================

@dataclass
class SignalDefinition:
    """
    Signal definition belonging to one OUTPUT.
    """

    name: str
    multiplier: float = 1.0


@dataclass
class PlotVariable:
    """
    One OUTPUT #N definition.
    """

    output_no: int

    data_column: int

    signals: list[SignalDefinition] = field(default_factory=list)

    alias: str = ""

    @property
    def display_name(self):

        if self.alias:
            return self.alias

        if len(self.signals) == 0:
            return f"OUTPUT #{self.output_no}"

        if len(self.signals) == 1:
            return self.signals[0].name

        return (
            self.signals[0].name
            + f" (+{len(self.signals)-1})"
        )


@dataclass
class DatFile:

    filename: str

    date_line: str

    title_lines: list[str]

    format_line: str

    n_outputs: int

    variables: list[PlotVariable]

    data_start_line: int

    # [추가] gnuplot splot용 CATHENA 출력(모든 헤더 줄에 '#'가 붙고, 데이터가
    # "time output_no value" 3컬럼 x n_outputs줄 + 빈 줄 반복 블록 구조인
    # surface 포맷) 여부. 일반 CATHENA .dat와는 데이터 구조가 완전히 달라서
    # (여러 컬럼 한 줄이 아니라 3컬럼 여러 줄), 3D-Plot에서 별도 취급이 필요함.
    is_surface: bool = False

    # [추가] surface 포맷의 각 채널 이름이 "VOID:HTSECT(1)", "VOID:HTSECT(2)"처럼
    # "공통이름(위치번호)" 패턴이면, 그 공통이름만 뽑아서 Z축 라벨 기본값으로 쓴다.
    surface_base_name: str = ""


# ==========================================================
# PARSER
# ==========================================================

class CathenaDatParser:
    output_re = re.compile(r"OUTPUT\s*#\s*(\d+)", re.IGNORECASE)

    def parse(self, filename):
        # [추가 - 요청] "실행속도 검토" - 같은 dat 파일을 plot 한 번에도
        # 수십 번(curve/축/마커 계산마다) 처음부터 다시 읽고 파싱하고 있었음.
        # 파일 내용(수정시각/크기)이 그대로면 이전 결과를 재사용한다. 호출부가
        # 결과 객체를 고쳐도 캐시가 오염되지 않게 항상 복사본을 돌려준다.
        path = Path(filename)
        key = _file_cache_key(path)
        cached = _PARSE_CACHE.get(key)
        if cached is None:
            cached = self._parse_uncached(path)
            _PARSE_CACHE.put(key, cached)
        return copy.deepcopy(cached)

    def _parse_uncached(self, path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [x.rstrip("\n") for x in f]

        # [추가] gnuplot splot용 CATHENA surface 출력 감지 - 일반 CATHENA와
        # 헤더 내용은 같지만 모든 줄(날짜/타이틀/OUTPUT#/변수명 포함)에 '#'가
        # 붙어있는 게 특징(gnuplot이 '#'로 시작하는 줄을 자동으로 주석 처리해
        # 그냥 splot에 넣어도 되게 만든 포맷). 1번째 줄이 '#'로 시작하고
        # OUTPUT # 패턴도 있으면 이 포맷으로 판단한다.
        if lines and lines[0].strip().startswith("#") and any("OUTPUT #" in line.upper() for line in lines[:20]):
            return self._parse_cathena_splot(lines, path)
        # CATHENA 파일 감지 (OUTPUT # 키워드 존재 여부)
        if any("OUTPUT #" in line.upper() for line in lines[:15]):
            return self._parse_cathena(lines, path)
        else:
            return self._parse_generic(lines, path)

    @staticmethod
    def _strip_hash(line):
        """줄 맨 앞의 '#'(과 그 뒤 공백 1개)만 제거한다(내용 중간의 #는 그대로 둠)."""
        s = line.rstrip()
        if s.startswith("#"):
            s = s[1:]
            if s.startswith(" "):
                s = s[1:]
        return s

    @staticmethod
    def _surface_base_name(names):
        """"VOID:HTSECT(1)", "VOID:HTSECT(2)", ... 처럼 "공통이름(위치번호)"
        패턴이면 공통이름만 뽑아 반환한다(패턴이 안 맞으면 첫 채널 이름 그대로)."""
        m = re.match(r"^(.*)\(\s*\d+\s*\)\s*$", names[0]) if names else None
        base = m.group(1).strip() if m else (names[0] if names else "")
        # 모든 채널이 같은 base로 시작하는지 확인 - 아니면 그냥 첫 채널 이름 사용
        if base and all(n.startswith(base) for n in names):
            return base
        return names[0] if names else ""

    def _parse_cathena_splot(self, lines, path):
        """gnuplot splot용 CATHENA surface 출력 파싱. 헤더는 일반 CATHENA와
        같은 내용이되 전부 '#'가 붙어있고, OUTPUT # 마다 "# OUTPUT # N:" 줄
        다음에 "# 변수명" 줄이 하나(또는 그 사이 "#"만 있는 구분줄들)로 온다.
        데이터 본문은 재가공하지 않는다 - gnuplot이 '#' 줄/빈 줄을 그대로
        무시하고 using 1:2:3 with lines로 바로 splot 가능한 형식이라, 여기서는
        메타데이터(채널 이름, 개수)만 뽑아내면 충분하다."""
        stripped = [self._strip_hash(l) if l.strip().startswith("#") else l.rstrip() for l in lines]

        date_line = stripped[0]
        title_lines = [stripped[1], stripped[2]] if len(stripped) > 2 else []

        # "# 10" 처럼 정수만 있는 줄을 n_outputs로 사용(중복 헤더가 있어도
        # 첫 번째로 발견되는 순수 정수 줄을 채택)
        n_outputs = 0
        for s in stripped[:10]:
            if s.strip().isdigit():
                n_outputs = int(s.strip())
                break

        variables = [PlotVariable(output_no=0, data_column=1, signals=[SignalDefinition(name="Time")])]
        names = []
        i = 0
        while i < len(stripped):
            m = self.output_re.search(stripped[i])
            if m:
                output_no = int(m.group(1))
                # OUTPUT # 줄 다음, 다음 OUTPUT#/데이터 줄이 나오기 전까지의
                # 비어있지 않은 줄을 변수명으로 취급(보통 1줄).
                j = i + 1
                sig_name = f"OUTPUT #{output_no}"
                while j < len(stripped):
                    txt = stripped[j].strip()
                    if not txt or self.output_re.search(stripped[j]) or self._is_numeric_row(lines[j]):
                        break
                    sig_name = txt
                    j += 1
                variables.append(PlotVariable(output_no=output_no, data_column=output_no + 1,
                                               signals=[SignalDefinition(name=sig_name)]))
                names.append(sig_name)
            i += 1

        data_start_line = None
        for i, raw in enumerate(lines):
            if self._is_numeric_row(raw):
                data_start_line = i
                break
        if data_start_line is None:
            raise RuntimeError("DATA section not found.")

        return DatFile(
            filename=path.name,
            date_line=date_line,
            title_lines=title_lines,
            format_line="",
            n_outputs=n_outputs or len(names),
            variables=variables,
            data_start_line=data_start_line,
            is_surface=True,
            surface_base_name=self._surface_base_name(names),
        )

    def _parse_cathena(self, lines, path):
        if len(lines) < 6:
            raise RuntimeError("Invalid DAT file.")

        date_line = lines[0].rstrip()

        title_lines = [
            lines[1].rstrip(),
            lines[2].rstrip()
        ]
        
        n_outputs = int(lines[3].strip())
        format_line = lines[4].rstrip()
        variables = []
        data_start_line = None

        i = 5
        while i < len(lines):
            line = lines[i]

            #
            # DATA section?
            #
            if self._is_numeric_row(line):
                data_start_line = i
                break

            #
            # OUTPUT section?
            #
            m = self.output_re.search(line)

            if not m:
                i += 1
                continue
            output_no = int(m.group(1))
            signals = []
            i += 1

            while i < len(lines):
                txt = lines[i].rstrip()
                #
                # next OUTPUT
                #
                if self.output_re.search(txt):
                    break

                #
                # data begins
                #
                if self._is_numeric_row(txt):
                    data_start_line = i
                    break

                #
                # blank or comment (#, !, **, = 로 시작하는 줄 - 요청대로
                # OUTPUT 아래 signal 목록 사이에 낀 주석/빈 줄도 signal
                # 이름으로 잘못 읽히지 않게 여기서도 건너뛴다)
                #
                if is_comment_or_blank(txt):
                    i += 1
                    continue

                #
                # signal definition
                #
                name = txt.strip()
                multiplier = 1.0

                if "-MULTIPLIED BY:" in txt:
                    left, right = txt.split(
                        "-MULTIPLIED BY:",
                        1
                    )
                    name = left.strip()
                    try:
                        multiplier = float(
                            right.strip()
                        )
                    except ValueError:
                        multiplier = 1.0
                signals.append(
                    SignalDefinition(
                        name=name,
                        multiplier=multiplier
                    )
                )

                i += 1

            variables.append(
                PlotVariable(
                    output_no=output_no,
                    data_column=output_no + 1,
                    signals=signals
                )
            )

            if data_start_line is not None:
                break

        if data_start_line is None:
            raise RuntimeError(
                "DATA section not found."
            )

        # 0번 컬럼(Time)이 변수 목록에 누락되어 있는 경우 자동으로 맨 앞에 추가
        has_time_var = any(getattr(v, 'output_no', None) == 0 for v in variables)
        if not has_time_var:
            time_variable = PlotVariable(
                output_no=0,
                data_column=1,
                signals=[SignalDefinition(name="Time", multiplier=1.0)]
            )
            # 0번 컬럼을 가장 맨 앞에 삽입
            variables.insert(0, time_variable)

        return DatFile(
            filename=path.name,
            date_line=date_line,
            title_lines=title_lines,
            format_line=format_line,
            n_outputs=n_outputs,
            variables=variables,
            data_start_line=data_start_line
        )
        
    def _parse_generic(self, lines, path):
        # 1. 데이터 시작 위치(첫 번째 숫자 행) 탐색 및 헤더 추출
        data_start_line = 0
        header_line = ""
        
        for i, line in enumerate(lines):
            if self._is_numeric_row(line):
                data_start_line = i
                
                # 데이터 행 바로 위에서부터 위쪽으로 거슬러 올라가며 유효한 헤더 텍스트 탐색
                for j in range(i - 1, -1, -1):
                    prev_line = lines[j].strip()
                    
                    if is_comment_or_blank(prev_line) or "---" in prev_line or "===" in prev_line or "**" in prev_line:
                        continue
                    if self._is_numeric_row(prev_line):
                        continue
                    
                    header_line = prev_line
                    break
                break

        # 2. 컬럼 수 확인 (첫 데이터 줄 기준, 쉼표나 공백 분리)
        sample_data = re.split(r'[,\s]+', lines[data_start_line].strip())
        num_cols = len(sample_data)

        # 3. 헤더 줄의 단어들을 순서대로 모두 추출 (구분선이나 빈 항목 제외)
        raw_headers = []
        if header_line:
            # 쉼표나 공백 단위로 쪼개서 유효한 단어들만 수집
            tokens = re.split(r'[,\s]+', header_line.strip())
            raw_headers = [t.strip() for t in tokens if t.strip() and t.strip() not in ("---", "**")]

        # 4. PlotVariable 생성 (헤더 순서대로 앞에서부터 매칭, 부족하면 var_# 사용)
        variables = []
        for i in range(num_cols):
            # 헤더 목록에 해당 순서의 이름이 존재하면 그 이름을 그대로 사용
            if i < len(raw_headers) and raw_headers[i]:
                name = raw_headers[i]
            else:
                # 헤더 개수보다 컬럼이 더 많아서 부족한 경우에만 var_# 로 자동 채움
                name = f"var_{i}"

            variables.append(PlotVariable(
                output_no=i,
                data_column=i + 1,
                signals=[SignalDefinition(name=name)]
            ))

        return DatFile(
            filename=path.name,
            date_line="Generic Format",
            title_lines=[lines[0].strip()],
            format_line="Generic Table",
            n_outputs=num_cols - 1,
            variables=variables,
            data_start_line=data_start_line
        )

    @staticmethod
    def _is_numeric_row(line):
        # [수정 - 요청] "#, !, **, =로 시작하면 comment" 규칙 반영 - inline
        # "!" 주석도 먼저 잘라내고 판정한다(주석 뒤에 숫자가 남아 우연히
        # 숫자 행으로 오인되지 않게).
        txt = strip_inline_comment(line).strip()
        if is_comment_or_blank(txt) or "---" in txt or "===" in txt or "**" in txt:
            return False
        try:
            parts = split_fields(txt)
            if not parts:
                return False
            float(parts[0].replace(',', ''))
            return True
        except ValueError:
            return False

# ==========================================================
# JSON EXPORT
# ==========================================================

def save_json(datfile, outfile):

    with open(
        outfile,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            asdict(datfile),
            f,
            indent=4,
            ensure_ascii=False
        )


# ==========================================================
# TEST PROGRAM
# ==========================================================

if __name__ == "__main__":

    import sys

    if len(sys.argv) < 2:

        print()
        print("Usage:")
        print("python data_parser.py sample.dat")
        print()

        raise SystemExit

    parser = CathenaDatParser()

    dat = parser.parse(sys.argv[1])

    print()
    print("=" * 70)
    print("FILE :", dat.filename)
    print("=" * 70)

    print()

    print("DATE:")
    print(dat.date_line)

    print()

    print("TITLES:")
    for t in dat.title_lines:
        print(t)

    print()

    print("FORMAT:")
    print(dat.format_line)

    print()

    print("NUMBER OF OUTPUTS :", dat.n_outputs)

    print()

    for var in dat.variables:

        print(
            f"OUTPUT #{var.output_no:3d} "
            f"(DATA COLUMN {var.data_column})"
        )

        for sig in var.signals:

            print(
                f"    {sig.multiplier:g} * "
                f"{sig.name}"
            )

        print()

    print(
        "DATA START LINE :",
        dat.data_start_line
    )

    jsonfile = (
        Path(sys.argv[1]).with_suffix(".json")
    )

    save_json(
        dat,
        jsonfile
    )

    print()

    print("JSON SAVED :", jsonfile)

    print()

#    input("Press Enter to exit...")