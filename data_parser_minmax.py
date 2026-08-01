"""
======================================================================
CathPlot

Module:
    data_parser.py

Purpose:
    Parse CATHENA and Generic DAT file metadata, compute min/max statistics,
    and manage JSON caching.

Author:
    CWKim / ChatGPT

Version:
    1.0a
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
    #Signal definition belonging to one OUTPUT.
    name: str
    multiplier: float = 1.0


@dataclass
class PlotVariable:

    #One OUTPUT #N definition.

    output_no: int
    data_column: int
    signals: list[SignalDefinition] = field(default_factory=list)
    alias: str = ""
    min_val: float = 0.0
    max_val: float = 1.0

    @property
    def display_name(self):
        if self.alias:
            return self.alias
        if len(self.signals) == 0:
            return f"OUTPUT #{self.output_no}"
        if len(self.signals) == 1:
            return self.signals[0].name
        return self.signals[0].name + f" (+{len(self.signals)-1})"


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
        json_path = path.with_suffix(".json")

        # 1. JSON 캐시 파일이 존재하면 파싱 생략 후 로드
        if json_path.exists():
            return self.load_from_json(json_path)

        # 2. 존재하지 않으면 원본 파일 읽기
        with open(path, "r", errors="ignore") as f:
            lines = [x.rstrip("\n") for x in f]

        if len(lines) < 2:
            raise RuntimeError("Invalid DAT file.")

        # CATHENA 파일인지 일반 파일인지 자동 감지(OUTPUT # 키워드 존재 여부)
        if any("OUTPUT #" in line.upper() for line in lines[:15]):
            dat_file = self._parse_cathena(lines, path)
        else:
            dat_file = self._parse_generic(lines, path)

        # 3. 파싱 결과 및 min/max를 즉시 JSON으로 캐싱 (CWD / DAT 경로 기준)
        self.save_to_json(dat_file, json_path)

        return dat_file

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

        return DatFile(

            filename=path.name,

            date_line=date_line,

            title_lines=title_lines,

            format_line=format_line,

            n_outputs=n_outputs,

            variables=variables,

            data_start_line=data_start_line
        )

        #pass

    def _parse_generic(self, lines, path):
        # 1. 데이터 시작 위치 및 헤더 탐색
        data_start_line = 0
        header_line = ""
        for i, line in enumerate(lines):
            if self._is_numeric_row(line):
                data_start_line = i
                # 데이터 바로 위 줄을 헤더로 (구분선은 건너뜀)
                if i > 0 and not self._is_numeric_row(lines[i-1]) and "---" not in lines[i-1]:
                    header_line = lines[i-1]
                break
        
        # 2. 숫자 데이터 행 추출 및 컬럼별 min/max 계산
        data_rows = []
        for line in lines[data_start_line:]:
            if self._is_numeric_row(line):
                vals = [float(x.replace(',', '')) for x in re.split(r'[,\s]+', line.strip()) if x]
                if vals:
                    data_rows.append(vals)

        num_cols = len(data_rows[0]) if data_rows else 0
        
        col_stats = {}
        for c in range(num_cols):
            col_vals = [row[c] for row in data_rows if len(row) > c]
            if col_vals:
                col_stats[c] = (min(col_vals), max(col_vals))
            else:
                col_stats[c] = (0.0, 1.0)

        # 3. 헤더 처리
        raw_headers = re.split(r'[,\s]+', header_line.strip()) if header_line else []
        
        # 4. PlotVariable 생성 (var_# 자동 지정 및 min/max 부여)
        variables = []
        for i in range(num_cols):
            if i == 0: continue # Time 컬럼 제외
            
            # 헤더 이름 할당 또는 var_# 자동 지정
            if i < len(raw_headers) and raw_headers[i].strip():
                name = raw_headers[i].strip()
            else:
                name = f"var_{i}" 
            
            c_min, c_max = col_stats.get(i, (0.0, 1.0))

            variables.append(PlotVariable(
                output_no=i, 
                data_column=i + 1,
                signals=[SignalDefinition(name=name)],
                min_val=c_min,
                max_val=c_max
            ))
            
        return DatFile(
            filename=path.name,
            date_line="Generic Format",
            title_lines=[lines[0].strip() if lines else "Title"],
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
            float(txt.split()[0].replace(',', ''))
            return True
        except:
            return False

# ==========================================================
# JSON EXPORT
# ==========================================================

    def save_to_json(self, datfile: DatFile, outfile: Path):
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(asdict(datfile), f, indent=4, ensure_ascii=False)

# ==========================================================
# TEST PROGRAM
# ==========================================================

    def load_from_json(self, json_path: Path) -> DatFile:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        variables = []
        for v in data["variables"]:
            signals = [SignalDefinition(**s) for s in v["signals"]]
            variables.append(PlotVariable(
                output_no=v["output_no"],
                data_column=v["data_column"],
                signals=signals,
                alias=v.get("alias", ""),
                min_val=v.get("min_val", 0.0),
                max_val=v.get("max_val", 1.0)
            ))
            
        return DatFile(
            filename=data["filename"],
            date_line=data["date_line"],
            title_lines=data["title_lines"],
            format_line=data["format_line"],
            n_outputs=data["n_outputs"],
            variables=variables,
            data_start_line=data["data_start_line"]
        )
        