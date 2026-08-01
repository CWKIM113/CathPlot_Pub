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

    output_re = re.compile(
        r"OUTPUT\s*#\s*(\d+)",
        re.IGNORECASE
    )

    def parse(self, filename):

        path = Path(filename)

        with open(path, "r", errors="ignore") as f:
            lines = [x.rstrip("\n") for x in f]

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

    @staticmethod
    def _is_numeric_row(line):

        txt = line.strip()

        if txt == "":
            return False

        try:

            float(txt.split()[0])

            return True

        except:

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