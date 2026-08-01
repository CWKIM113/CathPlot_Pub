"""
======================================================================
CathPlot

Module:
    dat_reader.py

Purpose:
    Read numerical data section from CATHENA DAT file.

Author:
    CWKim / ChatGPT

Version:
    1.0
======================================================================
"""

from pathlib import Path


class DatReader:

    def __init__(self, metadata):

        self.metadata = metadata

        self.time = []

        self.outputs = {}

    def read(self, filename):

        path = Path(filename)

        with open(path, "r", errors="ignore") as f:

            lines = f.readlines()

        start = self.metadata.data_start_line

        #
        # output containers
        #

        for var in self.metadata.variables:

            self.outputs[var.output_no] = []

        #
        # read data rows
        #

        for line in lines[start:]:

            txt = line.strip()

            if txt == "":
                continue

            parts = txt.split()

            #
            # sanity check
            #

            if len(parts) < self.metadata.n_outputs + 1:
                continue

            try:

                values = [float(x) for x in parts]

            except:

                continue

            #
            # time
            #

            self.time.append(values[0])

            #
            # outputs
            #

            for var in self.metadata.variables:

                col = var.data_column - 1

                self.outputs[var.output_no].append(
                    values[col]
                )

    def get_series(self, output_no):

        return (
            self.time,
            self.outputs[output_no]
        )

# ==========================================================
# TEST
# ==========================================================

import sys

if len(sys.argv) < 2:

    print(
        "Usage: python dat_reader.py file.dat"
    )

    raise SystemExit

filename = sys.argv[1]

if __name__ == "__main__":

    from cathena_parser import CathenaDatParser

    parser = CathenaDatParser()

    meta = parser.parse(filename)

    reader = DatReader(meta)

    reader.read(filename)

    t, y = reader.get_series(4)

    print()

    print("POINTS =", len(t))

    print()

    for i in range(min(10, len(t))):

        print(
            f"{t[i]:10.3f}",
            f"{y[i]:12.6f}"
        )
