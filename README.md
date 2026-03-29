# MathTeX

MathTeX es un entorno para calculo simbolico/numerico con una sintaxis inspirada en Octave/MATLAB y soporte para documentos LaTeX ejecutables. El proyecto permite trabajar de dos formas:

- Scripts `.mtx` para calculo interactivo, funciones, matrices y graficos.
- Documentos `.mtex` para mezclar LaTeX con bloques de codigo MathTeX y generar `.tex` + `.pdf`.

La aplicacion usa una unica interfaz grafica basada en PySide6. Si la GUI no puede abrirse, queda disponible una consola tipo REPL.

## Caracteristicas principales

- Editor interactivo para archivos `.mtx`.
- Espacio de trabajo `.mtex` con vista previa PDF.
- Compilacion de proyectos a una carpeta `build/`.
- Graficos 2D integrados y reutilizables dentro del documento con `\plot{...}`.
- Insercion de variables calculadas dentro de LaTeX con `\var{...}`.
- Generacion de tablas LaTeX con `table(...)` y uso posterior con `\table{...}`.
- Soporte para algebra lineal, derivadas, sistemas lineales, SVD, LU, Newton-Raphson, min/max, normas y operaciones elemento a elemento.

## Requisitos

- Python 3
- Dependencias de `requirements.txt`
- `pdflatex` instalado y disponible en `PATH` para generar PDF
- PySide6 con soporte para `QtPdf`/`QtPdfWidgets` en la instalacion activa

En Windows normalmente esto se resuelve instalando MiKTeX. En Linux/macOS puedes usar TeX Live o una distribucion equivalente.

## Instalacion

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si ya tienes un entorno virtual activo, basta con instalar las dependencias.

## Ejecucion

```powershell
python src/main.py
```

Opciones utiles:

- `python src/main.py --cli`: fuerza el modo consola.

## Flujo rapido

### 1. Scripts `.mtx`

Usa el editor interactivo para probar calculos, funciones y graficos.

```text
f(x) = x.^2 - 2;
x = \NR(f, 1, 1e-8);
\plot(f, -1, 3, name = "raiz");
```

### 2. Documentos `.mtex`

Un archivo `.mtex` es un documento LaTeX con bloques de codigo MathTeX.

```latex
\documentclass{article}
\begin{document}

\begin{code}
A = [1, 2; 3, 4];
b = [5; 6];
x = A | b;
\end{code}

La solucion es $\var{x}$.

\end{document}
```

Al compilar, MathTeX ejecuta el bloque, reemplaza placeholders y genera los artefactos de salida.

## Estructura del repositorio

- `src/`: codigo fuente Python del proyecto.
- `src/main.py`: punto de entrada principal para GUI PySide6 o modo CLI.
- `src/qt_app.py`: interfaz Qt principal.
- `src/latex_lang.py`: nucleo del lenguaje MathTeX.
- `src/mtex_executor.py`: ejecucion de `.mtex` y compilacion a LaTeX/PDF.
- `src/project_system.py`: proyectos, metadata `.mtexproj` y recientes.
- `src/project_outputs.py`: manejo de artefactos de compilacion.
- `src/parsers/`: extensiones del lenguaje.
- `ejemplos/`: scripts y documentos de ejemplo.
- `docs/`: documentacion complementaria.
- `tests/`: pruebas automatizadas.

## Archivos y carpetas generadas

- `.mtexproj`: metadata del proyecto.
- `build/`: salida de compilacion de documentos.
- `build/<nombre>.tex`: LaTeX final generado por MathTeX.
- `build/<nombre>.pdf`: PDF compilado.
- `build/compile.log`: log consolidado de compilacion.

## Documentacion adicional

- `docs/guia_de_uso.md`: flujo de trabajo recomendado y sintaxis mas usada.
- `docs/operadores_elemento_a_elemento.md`: uso de `.*`, `./`, `.^`, `.+` y `.-`.

## Ejemplos incluidos

En `ejemplos/` hay scripts y documentos para:

- Newton-Raphson
- minimos cuadrados
- graficos 2D
- funciones propias e imports desde `.mtx`
- tablas para documentos
- ejemplos documentales con sus `.tex` y `.pdf`

## Nota practica

Si la compilacion falla, revisa primero `build/compile.log`. Si la app abre pero no muestra la vista previa, verifica que `pdflatex` este disponible y que la instalacion de PySide6 incluya `QtPdf`.
