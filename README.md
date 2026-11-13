# CathPlot

CathPlot is a Windows desktop application for **X-Y plotting**. It allows users to create, customize, compare, and export plots from tabular data files. CATHENA DAT files are among the supported input formats; the application is not limited to CATHENA data.

## Main Features

- **X-Y data plotting**: Select data columns for X and Y axes and create one or multiple curves.
- **Data file handling**: Read tabular data, including CATHENA DAT output. The parser handles signal metadata, numeric values, comment lines, and inline comments.
- **Curve customization**: Configure curve colors, line styles, markers, and other plot properties.
- **Plot generation**: Generate plots using the external gnuplot engine.
- **Batch processing**: Manage multiple plot tasks using Batch Set/Queue, with bounded parallel execution.
- **Animation and preview**: Provide plot animation and preview workflows in the desktop GUI.
- **Export and printing**: Support plot output and conversion workflows involving PDF, PNG/JPG, SVG, and EMF, subject to the installed gnuplot and application environment.
- **Windows packaging**: Build a distributable application with PyInstaller.

## Source Files

| File | Description |
|---|---|
| `cathplot_gui.py` | Main Tkinter GUI and plotting workflow |
| `data_parser.py` | Input data parsing and shared data utilities |
| `gnu_generator.py` | gnuplot script generation, rendering, and output conversion |
| `requirements.txt` | Required external Python packages |
| `CathPlot.spec` | PyInstaller build configuration |

## Environment and Dependencies

- OS: Windows
- Language: Python 3
- GUI: Tkinter
- Plot engine: gnuplot (installed separately)
- Python packages:
  - `pywin32`: Windows printing and GUI integration
  - `Pillow`: Image processing and high-resolution PNG support
  - `PyMuPDF`: PDF rendering and conversion workflows

## Installation and Run

1. Install Python 3 and gnuplot.
2. Clone or download this repository.
3. Install the Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Ensure that gnuplot is available through PATH or the application's configuration.
5. Run the application:

   ```bash
   python cathplot_gui.py
   ```

Refer to the user manual included in the repository for detailed setup and operation instructions.

## Documentation

- [User Manual (V1.0)](CathPlot_사용설명서(V1.0).docx)
- [Change History (V1.0)](CathPlot_변경이력(V1.0).docx)
- [Presentation](CathPlot_발표.pptx)

## Notes

- CathPlot is a general-purpose X-Y plotting application. CATHENA DAT is one supported data source, not the application's sole purpose.
- gnuplot is a separate external program and must be installed independently.
- Available export, printing, and conversion options may depend on the Windows environment and installed components.
- For detailed usage and version-specific behavior, consult the included user manual and change history.
