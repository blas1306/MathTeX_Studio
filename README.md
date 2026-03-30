# MathTeX

MathTeX is a computational environment for writing technical documents with executable math.

It combines numerical and symbolic computation with LaTeX so you can calculate values, generate plots and tables, and inject the results directly into the final PDF.

In short:

> LaTeX + computation that updates itself

## Overview

In a traditional workflow, computations, plots, tables, and writing often live in separate tools. MathTeX brings those steps together in one place.

With MathTeX, you can:

- write calculation scripts in `.mtx` files
- create executable LaTeX documents in `.mtex`
- insert computed values with `\var{...}`
- insert generated plots with `\plot{...}`
- insert generated tables with `\table{...}`
- compile the final document to PDF

## Core Concepts

### `.mtx` scripts

Use `.mtx` files for calculation, experimentation, reusable functions, and plotting.

Typical use cases:

- quick numeric experiments
- function definitions
- linear algebra
- symbolic differentiation and solving
- reusable helper scripts

### `.mtex` documents

Use `.mtex` files when you want a LaTeX document that executes code blocks and embeds the results into the document output.

This is the format intended for:

- reports
- assignments
- technical notes
- documents with computed values, plots, and tables

## Example

```latex
\documentclass{article}
\begin{document}

\begin{code}
A = [1, 2; 3, 4];
b = [5; 6];
x = A | b;
\end{code}

The solution is:

\[
x = \var{x}
\]

\end{document}
```

MathTeX will:

1. execute the code block
2. replace `\var{x}` with the computed result
3. generate an intermediate `.tex` file
4. compile the final PDF

## Plot Example

```text
f(x) = x.^2 - 2;
\plot(f, -1, 3, name = "graph");
```

```latex
\plot{graph}
```

## Features

- interactive scripting with `.mtx` files
- executable LaTeX documents with `.mtex`
- automatic PDF generation through `pdflatex`
- inline value injection with `\var{...}`
- named plot generation and insertion with `\plot{...}`
- named table generation and insertion with `\table{...}`
- matrix and element-wise operations
- linear algebra tools such as LU, SVD, and linear system solving
- calculus and symbolic utilities such as derivatives and solving
- numerical methods including Newton-Raphson style workflows
- PySide6 desktop interface with CLI fallback

## Requirements

- Python 3
- dependencies from `requirements.txt`
- `pdflatex` available in `PATH`
- PySide6 with QtPdf support for the GUI preview

Recommended LaTeX distributions:

- Windows: MiKTeX
- Linux/macOS: TeX Live

## Installation

```bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
```

## Running

Start the desktop application:

```bash
python src/main.py
```

Force CLI mode:

```bash
python src/main.py --cli
```

Current behavior:

- `python src/main.py` tries to launch the PySide6 GUI
- if the GUI cannot start, MathTeX falls back to CLI mode
- `python src/main.py --cli` always starts the text interface

## Build Output

When compiling a `.mtex` document, MathTeX writes build artifacts to `build/`.

Typical outputs:

- `build/<name>.tex`
- `build/<name>.pdf`
- `build/compile.log`

If compilation fails, `build/compile.log` is the first place to check.

## Project Structure

```text
src/        Core application code
tests/      Automated tests
docs/       User documentation
ejemplos/   Example scripts and documents
```

Notable files:

- `src/main.py`: application entry point
- `src/latex_lang.py`: language runtime
- `src/mtex_executor.py`: `.mtex` execution and build pipeline
- `src/qt_app.py`: PySide6 GUI

## Documentation

User documentation:

- `docs/guia_de_uso.md`
- `docs/operadores_elemento_a_elemento.md`

## Example Demos

- **Physics Lab Report**: experimental data, computed values, and an automatically generated plot
- **Linear Algebra Report**: solving a linear system and embedding matrix factorizations into a document
- **Newton Method Demo**: numerical root-finding with generated output and plot

## Notes

- If PDF compilation fails, verify that `pdflatex` is installed and available in `PATH`.
- If preview does not work, verify that PySide6 includes QtPdf support.
- Placeholders such as `\var{A[2,1]}` use 1-based indexing.

## Philosophy

MathTeX is not trying to replace MATLAB, Wolfram, or Jupyter.

Its focus is narrower and more document-oriented:

> simplify the workflow of writing technical documents with embedded computation

## Project Status

MathTeX is under active development.

The `.mtex` document pipeline is already usable and continues to improve, while the application and user experience are still evolving.

## AI Assistance Disclaimer

This project has been developed with significant assistance from AI tools.

As the author, I do not yet have the full level of expertise required to build a system of this complexity entirely on my own. However, this project is also part of my learning process.

My goal is to progressively deepen my understanding of the underlying concepts and reduce reliance on AI over time, eventually being able to continue developing and maintaining MathTeX more independently.

## Contributing

Contributions are welcome. Contribution guidelines are not yet formalized.

## License

This project is licensed under the GNU General Public License v3.0 (GPL-3.0).

This means:
- You are free to use, modify, and distribute the software
- Any distributed modifications must also be open source under the same license
