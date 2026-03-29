import re
import shutil
import subprocess
import sympy as sp
import numpy as np
import os
import platform
from dataclasses import dataclass
from pathlib import Path

from diagnostics import (
    diagnostic_line_offset,
    make_build_diagnostic,
    render_diagnostic,
    runtime_error_from_exception,
)

# ImportÃ¡ tu propio motor MathTeX
from latex_lang import (
    ejecutar_linea,
    get_document_output_dir,
    reset_plot_state,
    reset_environment,
    set_document_output_dir,
    set_plot_mode,
    get_plot_mode,
)  # <- ajustAÃ© esto al nombre de tu funciÃ³n real


# ============================================================
# === CONVERSIÃ“N DE RESULTADOS A LATEX =======================
# ============================================================

def matrix_to_latex(M):
    """Convierte listas, arrays o matrices SymPy a formato LaTeX."""
    try:
        # Si ya es una matriz de SymPy, usamos su latex interno
        if isinstance(M, sp.MatrixBase):
            return sp.latex(M)
        # Si es lista o array (como [[1,2],[3,4]])
        elif isinstance(M, (list, tuple, np.ndarray)):
            # Convertir a SymPy.Matrix para formateo
            mat = sp.Matrix(M)
            return sp.latex(mat)
        else:
            return str(M)
    except Exception as e:
        return f"\\textcolor{{red}}{{Matrix error: {e}}}"


def expr_to_latex(expr):
    """Convierte cualquier tipo de expresiÃ³n a cÃ³digo LaTeX."""
    # Si es simbÃ³lico (de SymPy)
    if isinstance(expr, sp.Basic):
        return sp.latex(expr)
    # Si es matriz
    if isinstance(expr, (sp.MatrixBase, np.ndarray, list, tuple)):
        return matrix_to_latex(expr)
    # Si es nÃºmero o cadena
    if isinstance(expr, (int, float, complex)):
        return str(expr)
    # Fallback
    try:
        return sp.latex(sp.sympify(expr))
    except Exception:
        return str(expr)


_VAR_NOT_FOUND = object()
_LATEX_TEXT_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _escape_latex_text(text):
    return "".join(_LATEX_TEXT_ESCAPES.get(ch, ch) for ch in str(text))


def _latex_message(text, *, color="red"):
    return f"\\textcolor{{{color}}}{{{_escape_latex_text(text)}}}"


def _parse_one_based_index(token):
    cleaned = token.strip()
    if not re.fullmatch(r"[+-]?\d+", cleaned):
        raise ValueError("indice no valido")
    idx = int(cleaned)
    if idx < 1:
        raise ValueError("los indices empiezan en 1")
    return idx - 1


def _raise_index_out_of_range(name, index, size):
    raise ValueError(f"indice {index} fuera de rango para {name} (maximo {size})")


def _resolve_sequence_index(value, base_name, index):
    if isinstance(value, sp.MatrixBase):
        if value.cols == 1:
            size = value.rows
            if index >= size:
                _raise_index_out_of_range(base_name, index + 1, size)
            return value[index, 0]
        if value.rows == 1:
            size = value.cols
            if index >= size:
                _raise_index_out_of_range(base_name, index + 1, size)
            return value[0, index]
        raise ValueError(f"{base_name} es una matriz; usa dos indices")

    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            raise ValueError(f"{base_name} es escalar y no admite indices")
        if value.ndim == 1:
            size = value.shape[0]
            if index >= size:
                _raise_index_out_of_range(base_name, index + 1, size)
            return value[index]
        if value.ndim == 2 and 1 in value.shape:
            size = max(value.shape)
            if index >= size:
                _raise_index_out_of_range(base_name, index + 1, size)
            return value.reshape(-1)[index]
        if value.ndim == 2:
            raise ValueError(f"{base_name} es una matriz; usa dos indices")

    if isinstance(value, (list, tuple)):
        size = len(value)
        if index >= size:
            _raise_index_out_of_range(base_name, index + 1, size)
        return value[index]

    raise ValueError(f"{base_name} es escalar y no admite indices")


def _resolve_matrix_index(value, base_name, row_index, col_index):
    if isinstance(value, sp.MatrixBase):
        rows, cols = value.shape
        if row_index >= rows or col_index >= cols:
            raise ValueError(
                f"indices ({row_index + 1}, {col_index + 1}) fuera de rango para {base_name} "
                f"({rows}x{cols})"
            )
        return value[row_index, col_index]

    if isinstance(value, np.ndarray):
        if value.ndim != 2:
            if value.ndim == 1:
                raise ValueError(f"{base_name} es un vector; usa un solo indice")
            raise ValueError(f"{base_name} no admite dos indices")
        rows, cols = value.shape
        if row_index >= rows or col_index >= cols:
            raise ValueError(
                f"indices ({row_index + 1}, {col_index + 1}) fuera de rango para {base_name} "
                f"({rows}x{cols})"
            )
        return value[row_index, col_index]

    if isinstance(value, (list, tuple)):
        rows = len(value)
        if row_index >= rows:
            raise ValueError(f"fila {row_index + 1} fuera de rango para {base_name} (maximo {rows})")
        row_value = value[row_index]
        if not isinstance(row_value, (list, tuple, np.ndarray)):
            raise ValueError(f"{base_name} no es una matriz indexable con dos indices")
        cols = len(row_value)
        if col_index >= cols:
            raise ValueError(
                f"columna {col_index + 1} fuera de rango para {base_name}[{row_index + 1}] (maximo {cols})"
            )
        return row_value[col_index]

    raise ValueError(f"{base_name} no es una matriz indexable con dos indices")


def _resolve_var_reference(ref, contexto):
    expr = ref.strip()
    if expr in contexto:
        return contexto[expr]

    m = re.fullmatch(r"([a-zA-Z_][a-zA-Z0-9_]*)(?:\((.+)\)|\[(.+)\])", expr)
    if not m:
        return _VAR_NOT_FOUND

    base_name = m.group(1)
    raw_indices = m.group(2) if m.group(2) is not None else m.group(3)
    if base_name not in contexto:
        return _VAR_NOT_FOUND

    value = contexto[base_name]
    tokens = [tok.strip() for tok in raw_indices.split(",") if tok.strip()]
    if not tokens:
        raise ValueError("indice vacio")
    if len(tokens) > 2:
        raise ValueError("maximo dos indices")

    if len(tokens) == 1:
        i = _parse_one_based_index(tokens[0])
        return _resolve_sequence_index(value, base_name, i)

    i = _parse_one_based_index(tokens[0])
    j = _parse_one_based_index(tokens[1])
    return _resolve_matrix_index(value, base_name, i, j)

# ============================================================
# === REEMPLAZO AUTOMÃTICO DE VARIABLES ======================
# ============================================================

def reemplazar_vars(texto, contexto):
    """Reemplaza \var{nombre} con su valor LaTeX en el texto."""
    contexto = contexto or {}

    def repl(m):
        var = m.group(1)
        try:
            resolved = _resolve_var_reference(var, contexto)
        except Exception as e:
            return _latex_message(f"Error var {var}: {e}")
        if resolved is _VAR_NOT_FOUND:
            return _latex_message(f"?{var}?", color="gray")
        try:
            return expr_to_latex(resolved)
        except Exception as e:
            return _latex_message(f"Error var {var}: {e}")

    return re.sub(r"\\var\{([^{}]+)\}", repl, texto)

def reemplazar_plots(texto, contexto=None):
    def repl(m):
        raw_options = m.group(1)
        nombre = m.group(2)
        include_opts = raw_options.strip() if raw_options and raw_options.strip() else r"width=0.6\linewidth"
        plot_map = contexto.get("_plot_files", {}) if contexto else {}
        output_dir = contexto.get("_document_output_dir") if contexto else None
        output_dir_path = Path(output_dir) if output_dir else None
        candidatos = []
        if nombre in plot_map:
            candidatos.append(plot_map[nombre])
        candidatos.append(f"{nombre}.png")
        candidatos.append(f"plot_{nombre}.png")
        archivo = None
        include_target = None
        for ruta in candidatos:
            if not ruta:
                continue
            candidate_path = Path(ruta)
            if candidate_path.exists():
                archivo = str(candidate_path)
                include_target = candidate_path.as_posix()
                break
            if output_dir_path is not None and not candidate_path.is_absolute():
                built_candidate = output_dir_path / candidate_path
                if built_candidate.exists():
                    archivo = str(built_candidate)
                    include_target = candidate_path.name
                    break
        if archivo:
            return (
                "\\begin{figure}[H]\n"
                "\\centering\n"
                f"\\includegraphics[{include_opts}]{{{include_target or archivo}}}\n"
                "\\end{figure}\n"
            )
        return _latex_message(f"[No se encontro {nombre}]")

    return re.sub(r"\\plot(?:\[([^\]]*)\])?\{([a-zA-Z_][a-zA-Z0-9_]*)\}", repl, texto)


def reemplazar_tablas(texto, contexto=None):
    table_blocks = contexto.get("_table_blocks", {}) if contexto else {}
    missing_table = False

    def repl(m):
        nonlocal missing_table
        table_id = m.group(1).strip()
        table_tex = table_blocks.get(table_id)
        if table_tex is not None:
            return table_tex
        missing_table = True
        print(f"Warning: table '{table_id}' not found for \\table{{...}}.")
        return _latex_message(f"[Table {table_id} not found]")

    replaced = re.sub(r"\\table\{([^{}]+)\}", repl, texto)
    return replaced, missing_table


BASE_REQUIRED_LATEX_PACKAGES = (
    ("graphicx", r"\usepackage{graphicx}"),
    ("float", r"\usepackage{float}"),
    ("fontenc", r"\usepackage[T1]{fontenc}"),
    ("lmodern", r"\usepackage{lmodern}"),
)
OPTIONAL_LATEX_PACKAGES = {
    "booktabs": r"\usepackage{booktabs}",
    "xcolor": r"\usepackage{xcolor}",
}

CODEBLOCK_SPLIT_RE = re.compile(r"\\codeblock|\\endcodeblock|\\begin\{code\}|\\end\{code\}")
MULTIPASS_HINT_RE = re.compile(
    r"""(?ix)
    \\tableofcontents
    |\\listoffigures
    |\\listoftables
    |\\(?:ref|pageref|autoref|eqref)\{
    |\\(?:cite|nocite)\{
    |\\(?:bibliography|addbibresource)\{
    |\\printbibliography
    """
)
RERUN_LOG_HINTS = (
    "Rerun to get cross-references right.",
    "LaTeX Warning: Label(s) may have changed. Rerun",
    "There were undefined references.",
)


def _build_required_packages(contexto=None, include_xcolor: bool = False):
    package_list = list(BASE_REQUIRED_LATEX_PACKAGES)
    requested = set()

    if contexto:
        raw = contexto.get("_required_packages", set())
        if isinstance(raw, str):
            requested.add(raw)
        elif isinstance(raw, (list, tuple, set)):
            requested.update(str(pkg) for pkg in raw)

    if include_xcolor:
        requested.add("xcolor")

    for pkg_name in ("booktabs", "xcolor"):
        if pkg_name in requested:
            package_list.append((pkg_name, OPTIONAL_LATEX_PACKAGES[pkg_name]))

    return package_list


def ensure_required_packages(tex: str, required_packages=None) -> str:
    """Inserta los paquetes necesarios en el preambulo si faltan."""
    packages = required_packages if required_packages is not None else BASE_REQUIRED_LATEX_PACKAGES
    marker = r"\begin{document}"
    marker_idx = tex.find(marker)
    if marker_idx == -1:
        return tex

    preamble = tex[:marker_idx]
    rest = tex[marker_idx:]
    missing = []

    for pkg_name, directive in packages:
        pattern = rf"\\usepackage(?:\[[^\]]*\])?\{{{re.escape(pkg_name)}\}}"
        if re.search(pattern, preamble):
            continue
        missing.append(directive)

    if not missing:
        return tex

    insertion = ("\n" if preamble and not preamble.endswith("\n") else "") + "\n".join(missing) + "\n"
    return preamble + insertion + rest


def _tex_likely_needs_multipass(tex: str) -> bool:
    return bool(MULTIPASS_HINT_RE.search(tex))


def _log_requests_rerun(log_path: str) -> bool:
    if not os.path.exists(log_path):
        return False
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            log_text = f.read()
    except Exception:
        return False
    return any(hint in log_text for hint in RERUN_LOG_HINTS)


def _extract_latex_error_summary(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None

    for idx, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("!"):
            follow_up = ""
            if idx + 1 < len(lines):
                follow_up = lines[idx + 1].strip()
            if follow_up and not follow_up.startswith("l."):
                return f"{stripped} {follow_up}".strip()
            return stripped
    return None


def summarize_latex_build_failure(log_path: str | Path) -> str | None:
    return _extract_latex_error_summary(Path(log_path))


def explain_latex_build_failure(log_path: str | Path, tex_path: str | Path | None = None) -> str | None:
    summary = summarize_latex_build_failure(log_path)
    if not summary:
        return None

    lowered = summary.lower()
    tex_text = ""
    if tex_path is not None:
        try:
            tex_text = Path(tex_path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            tex_text = ""

    if "misplaced alignment tab character &" in lowered:
        if r"\begin{matrix}" in tex_text:
            return (
                r"LaTeX found a matrix environment in the generated document, but the preamble does not include "
                r"\usepackage{amsmath}. Add that package explicitly to the .mtex document."
            )
        if any(token in tex_text for token in (r"\begin{tabular}", r"\begin{array}", r"\begin{align}", r"\begin{aligned}")):
            return (
                "LaTeX found an alignment marker '&' outside a valid alignment context. "
                "Check the surrounding tabular/array/align markup near the reported line."
            )
        return (
            "LaTeX found an '&' alignment marker where plain text or normal math was expected. "
            "Check the reported line for matrix, table, array, or align syntax."
        )

    if "undefined control sequence" in lowered:
        return (
            "LaTeX tried to use a command that is not defined in the current preamble. "
            "Check for a misspelled command or a missing package."
        )

    if "missing $ inserted" in lowered:
        return (
            "LaTeX detected content that should probably be inside math mode. "
            "Check underscores, carets, and formulas near the reported line."
        )

    return None


def _write_compile_log(log_path: Path, compile_log_path: Path, fallback_text: str | None = None) -> None:
    if log_path.exists():
        try:
            shutil.copyfile(log_path, compile_log_path)
            return
        except Exception:
            pass
    if fallback_text is None:
        return
    try:
        compile_log_path.write_text(fallback_text, encoding="utf-8")
    except Exception:
        pass


def _run_pdflatex(
    tex_filename: str,
    cwd: str,
    draftmode: bool = False,
    output_dir: str | None = None,
    synctex: bool = False,
):
    cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error"]
    if output_dir:
        cmd.append(f"-output-directory={output_dir}")
    if synctex:
        cmd.append("-synctex=1")
    if draftmode:
        cmd.append("-draftmode")
    cmd.append(tex_filename)
    return subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _delimiter_balance_delta(text: str) -> int:
    """Calcula el cambio neto de delimitadores ignorando strings y comentarios."""
    delta = 0
    in_str = False
    quote = ""
    escaped = False

    for ch in text:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if in_str:
            if ch == quote:
                in_str = False
                quote = ""
            continue
        if ch in {"'", '"'}:
            in_str = True
            quote = ch
            continue
        if ch in {"#", "%"}:
            break
        if ch in "([{":
            delta += 1
        elif ch in ")]}":
            delta -= 1
    return delta


def _statement_is_comment_only(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("#") or stripped.startswith("%")


def _statement_requests_plot(text: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z0-9_])(plot|plot3)\s*\(", text))


@dataclass(frozen=True)
class CodeStatement:
    text: str
    start_line: int
    end_line: int


def split_code_statements_with_lines(block: str, *, preserve_newlines: bool = True) -> list[CodeStatement]:
    statements: list[CodeStatement] = []
    current_lines: list[str] = []
    current_flat: list[str] = []
    current_start_line: int | None = None
    current_end_line: int | None = None
    depth = 0

    def flush() -> None:
        nonlocal current_lines, current_flat, current_start_line, current_end_line, depth
        if current_start_line is None or current_end_line is None:
            current_lines = []
            current_flat = []
            depth = 0
            return
        text = "\n".join(current_lines).strip() if preserve_newlines else " ".join(current_flat).strip()
        if text:
            statements.append(CodeStatement(text=text, start_line=current_start_line, end_line=current_end_line))
        current_lines = []
        current_flat = []
        current_start_line = None
        current_end_line = None
        depth = 0

    for line_number, raw_line in enumerate(block.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            if current_start_line is not None and depth > 0:
                current_lines.append("")
                current_end_line = line_number
            elif current_start_line is not None and depth <= 0:
                flush()
            continue

        if current_start_line is None:
            current_start_line = line_number
        current_end_line = line_number
        current_lines.append(raw_line.rstrip())
        current_flat.append(stripped)
        depth += _delimiter_balance_delta(stripped)

        if depth <= 0:
            flush()

    flush()
    return statements


def split_code_statements(block: str) -> list[str]:
    """
    Split a code block into executable statements, allowing
    multiline expressions while delimiters remain open.
    """
    return [statement.text for statement in split_code_statements_with_lines(block, preserve_newlines=False)]


# Backward-compatible alias for internal callers that still import the old name.
_split_code_statements = split_code_statements


# ============================================================
# === EJECUTOR PRINCIPAL DE ARCHIVOS .MTEX ===================
# ============================================================

def ejecutar_mtex(path, contexto, abrir_pdf=True, build_dir: str | Path | None = None):
    """
    Read an .mtex file, execute MathTeX blocks,
    replace variables, and generate a .tex file and PDF.
    """
    if not str(path).lower().endswith(".mtex"):
        print("Warning: ejecutar_mtex is intended for .mtex documents (LaTeX+MathTeX).")
    reset_environment(contexto)
    previous_plot_mode = get_plot_mode()
    previous_plot_output_dir = get_document_output_dir()
    set_plot_mode("document")

    source_path = Path(path).expanduser().resolve()
    source_dir = source_path.parent
    output_dir_path = Path(build_dir).expanduser().resolve() if build_dir is not None else source_dir
    output_dir_path.mkdir(parents=True, exist_ok=True)
    tex_path = output_dir_path / f"{source_path.stem}.tex"
    pdf_path = output_dir_path / f"{source_path.stem}.pdf"
    log_path = output_dir_path / f"{source_path.stem}.log"
    compile_log_path = output_dir_path / "compile.log"
    try:
        tex_target = os.path.relpath(tex_path, start=source_dir)
    except ValueError:
        tex_target = str(tex_path)
    set_document_output_dir(output_dir_path)
    if contexto is not None:
        contexto["_document_output_dir"] = str(output_dir_path)

    with open(source_path, "r", encoding="utf-8") as f:
        contenido = f.read()
    likely_multipass = _tex_likely_needs_multipass(contenido)

    bloques = CODEBLOCK_SPLIT_RE.split(contenido)
    salida_parts: list[str] = []
    dentro = False
    compile_log_fallback = None

    for bloque in bloques:
        if dentro:
            lineas = split_code_statements_with_lines(bloque)
            resultado_final = None
            plot_generado = False

            for statement in lineas:
                linea = statement.text.strip()
                if not linea or _statement_is_comment_only(linea):
                    continue
                try:
                    with diagnostic_line_offset(statement.start_line - 1):
                        resultado = ejecutar_linea(statement.text)
                    resultado_final = resultado
                    if _statement_requests_plot(statement.text):
                        plot_generado = True
                except Exception as e:
                    diag = runtime_error_from_exception(e, source=statement.text, line=statement.start_line)
                    salida_parts.append(_latex_message(render_diagnostic(diag)))

            if resultado_final is not None and not plot_generado:
                salida_parts.append(expr_to_latex(resultado_final))
        else:
            salida_parts.append(bloque)

        dentro = not dentro

    salida_tex = "".join(salida_parts)
    salida_tex = reemplazar_vars(salida_tex, contexto)
    salida_tex = reemplazar_plots(salida_tex, contexto)
    salida_tex, missing_table = reemplazar_tablas(salida_tex, contexto)
    needs_xcolor = missing_table or (r"\textcolor{" in salida_tex)
    required_packages = _build_required_packages(contexto, include_xcolor=needs_xcolor)
    salida_tex = ensure_required_packages(salida_tex, required_packages=required_packages)

    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(salida_tex)

    print(f"LaTeX file generated: {tex_path}")

    pdf_generado = None
    previous_pdf_bytes = None
    if pdf_path.exists():
        try:
            previous_pdf_bytes = pdf_path.read_bytes()
        except Exception:
            previous_pdf_bytes = None
    try:
        final_run = None
        if likely_multipass:
            draft_pass = _run_pdflatex(
                tex_target,
                str(source_dir),
                draftmode=True,
                output_dir=str(output_dir_path),
            )
            if draft_pass.returncode != 0:
                final_run = draft_pass
            else:
                normal_pass = _run_pdflatex(
                    tex_target,
                    str(source_dir),
                    draftmode=False,
                    output_dir=str(output_dir_path),
                )
                final_run = normal_pass
                if normal_pass.returncode == 0 and _log_requests_rerun(str(log_path)):
                    final_run = _run_pdflatex(
                        tex_target,
                        str(source_dir),
                        draftmode=False,
                        output_dir=str(output_dir_path),
                    )
        else:
            normal_pass = _run_pdflatex(
                tex_target,
                str(source_dir),
                draftmode=False,
                output_dir=str(output_dir_path),
            )
            final_run = normal_pass
            if normal_pass.returncode == 0 and _log_requests_rerun(str(log_path)):
                final_run = _run_pdflatex(
                    tex_target,
                    str(source_dir),
                    draftmode=False,
                    output_dir=str(output_dir_path),
                )

        if final_run is not None and final_run.returncode == 0 and pdf_path.exists():
            print("PDF compiled successfully.")
            pdf_generado = str(pdf_path)

            if abrir_pdf:
                system_name = platform.system()
                if system_name == "Windows":
                    os.startfile(str(pdf_path))
                elif system_name == "Darwin":
                    subprocess.run(["open", str(pdf_path)])
                else:
                    subprocess.run(["xdg-open", str(pdf_path)])
        else:
            compile_log_fallback = "LaTeX compilation failed.\n"
            if final_run is None:
                compile_log_fallback += "The compiler did not produce a result.\n"
            elif not pdf_path.exists():
                compile_log_fallback += "The compiler finished without producing a PDF.\n"
            build_diag = make_build_diagnostic(
                "latex-compilation-failed",
                "LaTeX compilation failed.",
                source=_extract_latex_error_summary(log_path),
                hint=f"Check {compile_log_path.name} for the full compiler output.",
            )
            print(render_diagnostic(build_diag))
            if previous_pdf_bytes is not None:
                try:
                    pdf_path.write_bytes(previous_pdf_bytes)
                except Exception:
                    pass

    except Exception as e:
        compile_log_fallback = f"Error while compiling PDF: {e}\n"
        build_diag = make_build_diagnostic(
            "latex-compilation-exception",
            f"Error while compiling PDF: {e}",
            hint="Check the compiler installation and project paths.",
        )
        print(render_diagnostic(build_diag))
        if previous_pdf_bytes is not None:
            try:
                pdf_path.write_bytes(previous_pdf_bytes)
            except Exception:
                pass

    finally:
        set_plot_mode(previous_plot_mode or "interactive")
        set_document_output_dir(previous_plot_output_dir)
        _write_compile_log(log_path, compile_log_path, fallback_text=compile_log_fallback)

        plot_files = []
        if contexto:
            plot_files.extend(contexto.get("plots", []))
            extra = contexto.get("_plot_files", {})
            plot_files.extend(extra.values())
            contexto["plots"] = []
            if "_plot_files" in contexto:
                contexto["_plot_files"].clear()
            contexto.pop("_document_output_dir", None)

    return pdf_generado

