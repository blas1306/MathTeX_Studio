# GUI Migration Notes

## Initial Audit Summary

MathTeX contained three GUI paths before this refactor:

- `qt_app.py` already held the most complete desktop UI and was the safest consolidation target.
- `main.py` still contained a large Tkinter application with overlapping editor, console, preview, and workspace behavior.
- `autocomplete_popup.py` was a Tkinter-only autocomplete popup used by the legacy Tk editor.

## Modules Already Well Aligned With PySide6

- `qt_app.py`
- `pdf_preview.py`
- `logs_output_widget.py`
- `project_widgets.py`
- `project_outputs.py`
- `project_system.py`
- `execution_results.py`

These modules already formed the modern GUI path for:

- interactive editor
- MTeX Studio
- project management
- PDF preview
- logs/output
- workspace visualization

## Modules That Still Depended On Tkinter

- `main.py`
- `autocomplete_popup.py`
- `plot_backend.py` had Tk-specific interactive backend detection

The Tk path duplicated responsibilities already present in `qt_app.py`, so it was removed instead of being kept in parallel.

## Modules That Used PyQt6 Compatibility

- `qt_app.py`
- `pdf_preview.py`
- `logs_output_widget.py`
- `project_widgets.py`
- `plot_backend.py`

The compatibility was mostly import fallbacks, signal aliases, and backend checks. Those were safe to migrate first because the main PySide6 implementation already existed.

## Safe-First Migration Order

1. Remove PyQt6/PySide6 ambiguity from the Qt modules.
2. Keep `qt_app.py` as the single GUI shell and make `main.py` a thin entrypoint.
3. Delete Tkinter-only UI modules once nothing imported them.
4. Update dependency and usage docs so the project clearly states PySide6 as the only GUI stack.

## Decisions Applied In This Pass

- PySide6 is now the only supported GUI binding.
- Tkinter UI code was removed instead of preserved as fallback compatibility.
- The PDF preview stays on `QtPdf`/`QtPdfWidgets`.
- Interactive plotting avoids Tk backend assumptions and prefers Qt-backed matplotlib usage.
- The CLI REPL remains available as a non-GUI fallback.
