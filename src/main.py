from __future__ import annotations

import sys

STARTUP_IMPORT_ERROR: ModuleNotFoundError | None = None
ejecutar_linea = None
split_code_statements = None

try:
    from latex_lang import ejecutar_linea
    from mtex_executor import split_code_statements
except ModuleNotFoundError as exc:
    STARTUP_IMPORT_ERROR = exc

QT_IMPORT_ERROR: Exception | None = None

try:  # pragma: no cover - depende de la instalacion del usuario
    from qt_app import QT_AVAILABLE, launch_qt_gui
except Exception as exc:  # pragma: no cover - fallback CLI
    QT_AVAILABLE = False
    launch_qt_gui = None
    QT_IMPORT_ERROR = exc


def repl() -> None:
    """Traditional REPL kept for compatibility with the previous workflow."""
    if STARTUP_IMPORT_ERROR is not None or ejecutar_linea is None or split_code_statements is None:
        _print_missing_dependency_help()
        return

    print("Welcome to MathTeX")
    print("Type 'exit', or 'quit' to leave.\n")

    while True:
        try:
            raw_input = input("MathTeX> ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if raw_input.strip().lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        for statement in split_code_statements(raw_input):
            ejecutar_linea(statement)


def launch_gui() -> bool:
    """Launch the PySide6 GUI when it is available."""
    if not QT_AVAILABLE or launch_qt_gui is None:
        return False
    return bool(launch_qt_gui())


def _qt_error_message() -> str:
    if QT_IMPORT_ERROR is None:
        return ""
    name = QT_IMPORT_ERROR.__class__.__name__
    detail = str(QT_IMPORT_ERROR).strip()
    return f"{name}: {detail}" if detail else name


def _print_missing_dependency_help() -> None:
    print("Could not start MathTeX because a required Python dependency is missing.")
    print(f"Python executable: {sys.executable}")
    if STARTUP_IMPORT_ERROR is not None:
        missing = getattr(STARTUP_IMPORT_ERROR, "name", None)
        if missing:
            print(f"Missing module: {missing}")
    print("Install the project dependencies with:")
    print(f"  \"{sys.executable}\" -m pip install -r requirements.txt")


def main() -> None:
    if STARTUP_IMPORT_ERROR is not None:
        _print_missing_dependency_help()
        return

    args = {arg.lower() for arg in sys.argv[1:]}

    if {"--cli", "--no-gui"} & args:
        repl()
        return

    if "--tk" in args:
        print("The Tkinter interface was removed. Starting the PySide6 interface instead.\n")

    if launch_gui():
        return

    print("Could not start the PySide6 interface.")
    qt_error = _qt_error_message()
    if qt_error:
        print(f"Qt import error: {qt_error}")
    print("Use '--cli' to force text mode.\n")
    repl()


if __name__ == "__main__":
    main()
