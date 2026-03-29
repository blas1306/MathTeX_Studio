# Suite de tests de MathTeX

## Proposito

La suite protege contratos reales del lenguaje y del workflow de MathTeX sin perseguir cobertura cosmetica. La idea es que sirva como red de seguridad y tambien como mapa rapido del proyecto.

## Como correrla

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Si quieres ver salida de comandos durante la corrida:

```powershell
.venv\Scripts\python.exe -m pytest tests -q -s
```

## Estructura general

La carpeta `tests/` sigue siendo plana a proposito: hoy el volumen no justifica subdirectorios. La convencion util es agrupar por area funcional y reservar el sufijo `*_contracts` para invariantes transversales.

Los tests cargan `src/` automaticamente desde `tests/conftest.py`, asi que la suite puede seguir corriendose desde la raiz del repo sin exportar `PYTHONPATH`.

- Parser y AST: `test_ast_core_contracts.py`, `test_ast_index_assign.py`, `test_parser_ast_contracts.py`, `test_parser_control_flow_contracts.py`, `test_parser_negative_contracts.py`, `test_statement_splitter.py`, `test_string_list_assignment.py`.
- Runtime y estado: `test_runtime_state_contracts.py`, `test_runtime_document_contracts.py`, `test_workspace_clear.py`, `test_semicolon_silencing.py`, `test_function_condition_near_real.py`.
- Comandos y algebra: `test_min_max_commands.py`, `test_solver_behaviors.py`, `test_nr_command.py`, `test_ode_command.py`, `test_nthroot_command.py`, `test_lu_command.py`, `test_svd_command.py`, `test_spectral_commands.py`, `test_linspace_parametric.py`, `test_elementwise_ops.py`, `test_multivariable_diff_matrix.py`.
- Documentos `.mtex`, tablas y outputs: `test_tables.py`, `test_var_placeholder_indexing.py`, `test_plot_placeholder_replacement.py`, `test_mtex_build_outputs.py`.
- Plots y backend: `test_plot_backend_document_mode.py`, `test_plot_backend_figures.py`, `test_plot_name_argument.py`.
- Proyecto y workflow: `test_project_system.py`, `test_project_workflow_contracts.py`, `test_import_silence.py`, `test_newton_multivariable_script.py`.
- Catalogo y ayudas de edicion: `test_command_catalog_contracts.py`, `test_autocomplete_engine.py`, `test_execution_results.py`.

## Contratos importantes protegidos

- El parser respeta precedencia, bloques de control y rechaza entradas rotas sin dejar estado parcial.
- `reset_environment()` limpia estado de usuario pero conserva builtins reutilizables.
- La ejecucion de `.mtex` no filtra variables, tablas ni plots entre corridas y restaura el modo de plot previo.
- Las tablas, `\var{...}` y `\plot{...}` reemplazan placeholders de forma estable en el `.tex` generado.
- Los comandos catalogados siguen teniendo una superficie real compatible con la implementacion.
- Proyectos y recientes manejan estructura, metadata invalida y deduplicacion de forma consistente.

## Mapa de cobertura cualitativo

- Parser: bien cubierto.
- AST: razonablemente cubierto.
- Runtime/state: bien cubierto.
- Comandos matematicos: razonablemente cubierto.
- Plots/backend: razonablemente cubierto.
- Documentos `.mtex` / build: razonablemente cubierto.
- Proyecto/workflow: medio cubierto.
- Catalogo/autocomplete: razonablemente cubierto.
- GUI logica no visual: poco cubierto.

Huecos abiertos:

- GUI visual Qt y flujos de interfaz completos.
- Casos negativos mas finos del parser fuera de los contratos ya agregados.
- Integraciones end-to-end largas de proyecto con multiples archivos y assets.
- AST fuera de nodos y rutas ya cubiertas por parser/index assignment.

## Principios para nuevos tests

- Priorizar contratos reales y regresiones de bugs por encima de cobertura cosmetica.
- Preferir tests pequenos, deterministas y con poco estado compartido.
- Agregar tests de integracion solo cuando validen limites entre modulos que ya fallaron o son delicados.
- Mantener separados los tests unitarios de backend puro y los tests de workflow `.mtex` o proyecto.
- Evitar GUI visual pesada salvo que un bug concreto lo justifique.
