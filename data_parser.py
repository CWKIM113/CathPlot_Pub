"""
======================================================================
CathPlot

Module:
    cathena_parser.py

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

from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import re


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


# ==========================================================
# PARSER
# ==========================================================

class CathenaDatParser:
    output_re = re.compile(r"OUTPUT\s*#\s*(\d+)", re.IGNORECASE)

    def parse(self, filename):
        path = Path(filename)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [x.rstrip("\n") for x in f]

        # CATHENA 파일 감지 (OUTPUT # 키워드 존재 여부)
        if any("OUTPUT #" in line.upper() for line in lines[:15]):
            return self._parse_cathena(lines, path)
        else:
            return self._parse_generic(lines, path)

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
                # blank
                #
                if txt.strip() == "":
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
                    except:
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
                    
                    if not prev_line or "---" in prev_line or "===" in prev_line:
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
            raw_headers = [t.strip() for t in tokens if t.strip() and t.strip() != "---"]

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
        txt = line.strip()
        if not txt or "---" in txt or "===" in txt: 
            return False
        try:
            parts = re.split(r'[,\s]+', txt)
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
        print("python cathena_parser.py sample.dat")
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