# CathPlot

CathPlot is a Windows desktop application originally developed to **automate plotting and image generation for CATHENA analysis results**. It helps users turn CATHENA output data into consistently formatted plots and image files with less repetitive manual work.

The application has since been extended to support **general-purpose data files**, so users can also create X-Y plots from other tabular data sources.

## Main Features

- **CATHENA result plotting**: Read CATHENA output files and use their signal definitions and data columns to prepare plots.
- **Automated plot and image generation**: Generate plot images and other output files through a repeatable workflow, reducing manual plotting effort.
- **General data-file support**: Apply the plotting workflow to ordinary tabular data files in addition to CATHENA results.
- **X-Y curve configuration**: Select X- and Y-axis data and configure multiple curves.
- **Curve and plot customization**: Configure colors, line styles, markers, labels, axes, and other plot properties.
- **Batch processing**: Manage multiple plotting tasks using Batch Set/Queue, with bounded parallel execution.
- **Animation and preview**: Provide plot animation and preview workflows in the desktop GUI.
- **Export and printing**: Support output and conversion workflows involving PDF, PNG/JPG, SVG, and EMF, subject to the installed gnuplot and application environment.
- **Windows application packaging**: Build a distributable application with PyInstaller.

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

- CathPlot was originally designed for plotting CATHENA analysis results and automating plot-image generation. Support for general data files was added as an extension.
- gnuplot is a separate external program and must be installed independently.
- Available export, printing, and conversion options may depend on the Windows environment and installed components.
- For detailed usage and version-specific behavior, consult the included user manual and change history.
