# Handoff — Dashboard W34 (Francisco Vilches)

Plan de referencia: [`PLAN_W34_DASHBOARD_CLAUDE.md`](PLAN_W34_DASHBOARD_CLAUDE.md). Plan técnico
detallado (diagnóstico, mapa de implementación, diseño): `C:\Users\panch\.claude\plans\trabaja-exclusivamente-en-este-synthetic-moonbeam.md`
(aprobado por la persona usuaria antes de iniciar la implementación).

**Declaración obligatoria (CLAUDE.md):** no se modificó la copia productiva local
(`C:\Users\panch\Desktop\Coddi\CDA\Dashboard\tds_alerts_dashboard`), no se tocaron otros worktrees,
`.env`, secretos, credenciales ni claves. No se ejecutó `git push`, merge, cherry-pick ni despliegue.
**Excepción documentada** (Fase 6, pedido explícito de la persona usuaria en el chat): se leyeron
—nunca se escribieron— archivos reales de datos desde esa ruta hacia el `data/` de este worktree;
`CLAUDE.md` prohíbe literalmente "usar" la copia productiva, no sólo modificarla — ver el detalle y
la distinción de redacción en "Fase 6" y en "Cumplimiento de las reglas de CLAUDE.md" más abajo.

## Decisiones tomadas por el usuario antes de implementar

1. **Entorno**: preparar `.venv` local e instalar dependencias desde PyPI, pidiendo aprobación explícita antes de instalar.
2. **Alcance de instalación** (tras encontrar que `requirements.txt` completo incluye paquetes de Campbell AI/ERP no usados por las 13 mejoras): instalar sólo el subconjunto que W34 toca.
3. **W34-06** (instante de alertas): normalizar a UTC en el borde de carga y convertir a `America/Santiago` sólo en presentación (consistente con Estado de Datos).
4. **W34-12** (nomenclatura de variables): unificar infraestructura y los casos de estilo; los conflictos semánticos se dejan sin tocar y se listan aquí para decisión de dominio (4 identificados al aprobar el plan — `TCOutTemp`, `oil_level_pct`, `rifle_oil_pressure_psi`, `oil_diff_pressure_psi` —, más un 5º encontrado durante el diagnóstico exhaustivo de implementación: `fuel_pump_intake_pressure_psi`).
5. **W34-04** (alertas mixtas): construir toda la infraestructura (fuente de verdad valor→etiqueta→color + leyenda) con `"Mixto"` como etiqueta provisional; el texto final lo define el usuario en la siguiente iteración.

## Entorno de validación

- Python base con pip: `C:\Users\panch\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe` (gestionado por `uv`, no requirió instalación nueva).
- Venv del proyecto: `.venv/` dentro de este worktree (ya cubierto por `.gitignore:45`, no se commitea).
- Paquetes instalados (subconjunto de `requirements.txt`, aprobado explícitamente): `pandas`, `numpy`, `pyarrow`, `openpyxl`, `pytz`, `PyYAML==6.0.3`, `pydantic`, `pydantic-settings`, `python-dotenv`, `dash`, `dash-bootstrap-components`, `plotly`, `itsdangerous`, `pytest`.
- **Omitidos deliberadamente** (ninguna de las 13 mejoras los importa; confirmado con `grep` antes de decidir): `fastapi`, `uvicorn`, `openai-agents`, `redis`, `boto3`, `botocore`, `s3fs`, `tqdm`, `nbformat`.
- **Nota de entorno no relacionada con código**: `%TEMP%\pytest-of-panch` quedó con permisos de otra sesión/usuario de Windows (mismo patrón que el `dubious ownership` de git) y bloqueaba la fixture `tmp_path` con `PermissionError: [WinError 5]`. Se resolvió apuntando pytest a un `--basetemp` propio (`%TEMP%\w34_pytest_tmp`), sin tocar ni borrar la carpeta ajena.

## Fase 0 — Baseline (antes de tocar código)

Comandos y resultado, en orden:

```bash
python -m compileall -q dashboard src config
# exit 0, sin salida
```

```bash
python -m pytest -q tests --continue-on-collection-errors --basetemp=<tmp>/w34_pytest_tmp
```

**Resultado baseline: `7 failed, 296 passed, 5 skipped, 26 warnings, 5 errors`**

| Categoría | Cantidad | Causa | ¿Relacionado con W34? |
|---|---:|---|---|
| ERROR de colección | 5 | `ModuleNotFoundError: fastapi` (4 archivos `test_campbell_ai_*`) / `boto3` (`test_auth_events_repository.py`) | No — excluido deliberadamente (ver Entorno) |
| FAILED | 4 | Mismo `ModuleNotFoundError: fastapi`, pero importado dentro del cuerpo del test (`test_campbell_ai_resources.py`), no a nivel de módulo → aparece como FAILED, no ERROR | No |
| FAILED | 3 | `CampbellDataError` real en `src/campbell_ai/chart_registry.py` (`_oil_essay_group_radar`, `test_group_radar_pins_each_threshold_to_a_fixed_radius`, `test_group_radar_splits_by_element_group`, `test_history_panels_pair_the_essays_that_are_read_together`) | **No** — pre-existente, fuera de las 13 mejoras (Campbell AI backend, no `ai_analysis_panel.py`). Verificado que la falla es de lógica del registro de charts, no de dependencias faltantes. **No se investiga ni se corrige aquí.** |
| SKIPPED | 5 | (no investigado — fuera de alcance, no relacionado con ningún archivo W34) | No |
| PASSED | 296 | — | Incluye `test_capstone_contract.py` completo (9/9, el más relevante para W34) y `test_data_freshness.py`, `test_telemetry_report.py`, `test_oil_limit_labels_and_consolidation.py` |

**Este es el baseline contra el que se compara cada fase.** Cualquier archivo `test_campbell_ai_*`
o `test_auth_events_repository.py` que aparezca con un resultado distinto tras un cambio de W34
sería una señal de alarma (ninguna mejora W34 debería tocar `src/campbell_ai/*` ni `src/data/auth_events_repository.py`).

## Matriz de trazabilidad

| W34-ID | Estado | Archivos | Prueba | Evidencia | Riesgo/bloqueo | Siguiente acción |
|---|---|---|---|---|---|---|
| F0 | Completada | — | `compileall` + `pytest` baseline | Ver tabla arriba | — | — |
| W34-11 | **Implementada** | `src/charts/signals.py`, `dashboard/components/alerts_charts.py`, `dashboard/callbacks/alerts_callbacks.py`, `tests/test_w34_signal_variables.py` | `pytest tests/test_w34_signal_variables.py` (15/15) + suite completa | 311 passed (296+15), mismos 7 failed/5 errors preexistentes — 0 regresión | Ninguno | `SIGNAL_LABELS` ahora `MappingProxyType` (inmutable); códigos Capstone movidos de `.update()` runtime a literal estático; nueva función pura `select_plottable_signals()` reemplaza la lista negra hardcodeada en `create_telemetry_evidence_section` |
| W34-06 | **Implementada** | `src/utils/date_utils.py` (nuevos `to_utc_naive`, `to_local_naive`, `format_local`), `src/data/loaders.py`, `dashboard/components/alerts_report.py`, `dashboard/components/alerts_tables.py`, `dashboard/callbacks/alerts_callbacks.py`, `dashboard/components/alerts_charts.py`, `tests/test_w34_timestamps.py` | `pytest tests/test_w34_timestamps.py` (26/26) + suite completa | 336 passed (311+25) en la implementación original; **bug real encontrado y corregido en la Fase 5 de validación visual** (ver abajo) | Ver "Riesgos" abajo (semántica del filtro de fecha se define en W34-05, no aquí) | Comparaciones/ventanas de evidencia siguen en UTC-naive (sin cambios); conversión a `America/Santiago` sólo en presentación (tabla, encabezado, dropdown, eje del gráfico de tendencias, hover del mapa GPS). El eje X del gráfico de tendencias se desplaza completo (no sólo el hover) para que ejes y tabla coincidan. **Fase 5**: `to_utc_naive`'s bulk `pd.to_datetime(series, utc=True)` silenciosamente convertía a `NaT` (y por tanto descartaba de la vista) las filas de un CSV con formatos genuinamente mixtos en una sola columna (naive + `Z` + offset, ej. una alerta Mixto real desapareció junto con su vecina) — corregido con un reintento por-elemento sólo para las filas afectadas; ver `test_a_genuinely_mixed_column_normalizes_every_row` |
| W34-01 | **Implementada** | `dashboard/components/labels.py`, `dashboard/callbacks/overview_general_callbacks.py`, `tests/test_w34_labels.py` | `pytest tests/test_w34_labels.py` (26/26) + suite completa | 362 passed (336+26), 0 regresión | Ninguno | General ahora usa `translate_component_label()` (vía nuevo helper puro `build_component_filter_options`) en vez de `.title()`; `value` del dropdown sigue crudo/mayúscula (no se tocó el join); fallback de componentes no catalogados mejorado (title-case legible en vez de eco de texto crudo) |
| W34-07 | **Validada/no duplicar** | `tests/test_w34_ai_panel_regression.py` (sólo pruebas, cero cambios en `ai_analysis_panel.py`/`alerts_tables.py`) | 17/17 | 379 passed (362+17), 0 regresión, ejecutada al cierre de Fase 1 (después de W34-01/06/11) | Ninguno para W34 | Sin cambios de implementación. Confirmado: sin imports de red/LLM; mensajes por defecto correctos para todas las combinaciones faltantes; decodificación de JSON estructurado Capstone sigue traduciendo señales correctamente tras W34-11. **Hallazgo no relacionado** (documentado, no corregido): `parse_ia_message_sections`'s guard `not x or pd.isna(x)` lanza excepción con `pd.NA`/listas — no se activa en el pipeline real (CSV vía `pd.read_csv` sólo produce `str`/`NaN` float en esta columna) |
| W34-03 | **Validada/no duplicar** | `dashboard/callbacks/alerts_callbacks.py` (import muerto retirado), `tests/test_w34_alerts_table.py` | 6/6 | 385 passed, 0 regresión | Ninguno | Ya estaba implementada; se retiró el import de `create_alerts_datatable` (variante legacy con `ID`/`Fuente` visibles) que era la única vía de regresión posible |
| W34-05 | **Implementada** | `dashboard/tabs/tab_alerts_detail.py`, `dashboard/callbacks/alerts_callbacks.py`, `tests/test_w34_alerts_filters.py` | 10/10 | 395 passed (385+10), 0 regresión | Ninguno | Filtro "Con Telemetría" retirado (layout + `Input`); nuevo `detail-filter-date-from` (`DatePickerSingle`). Semántica: inclusiva, vacío = sin límite, inválida = degrada a sin límite (no excepción). Resuelve la ambigüedad dejada pendiente en W34-06: la fecha se interpreta como día calendario de Chile y su límite de medianoche se convierte a UTC (`to_utc_naive(..., source_tz="America/Santiago")`) antes de comparar contra `Timestamp` |
| W34-04 | **Implementada** | `dashboard/components/labels.py` (nuevo `SOURCE_STYLE`/`source_style`/`source_color`), `dashboard/components/alerts_report.py`, `dashboard/components/alerts_tables.py`, `dashboard/tabs/tab_alerts_general.py`, `dashboard/callbacks/alerts_callbacks.py`, `tests/test_w34_alerts_source.py` | 17/17 | 412 passed (395+17), 0 regresión | Etiqueta final "Mixto" sigue provisional (decisión del usuario) | Fuente de verdad única en `labels.py` (evita import circular con `alerts_report.py`↔`alerts_tables.py`). 4 superficies ahora leen del mismo dict (verificado con monkeypatch): borde de tabla + `filter_query` derivado, leyenda nueva junto a la tabla, acento del KPI "Alertas mixtas" (antes `#7c6a9a`, independiente del borde `#6f42c1`), badge de color en el encabezado de detalle. `alert_summary()['mixed']` corregido para comparar `Trigger_type` crudo, no la etiqueta visible |
| W34-13 | **Implementada** | `dashboard/callbacks/overview_general_callbacks.py`, `dashboard/callbacks/data_freshness_callbacks.py` (`DASHBOARD_DATA_ROOT`), `tests/test_w34_source_availability.py` | 11/11 | 440 passed (429+11), 0 regresión | Ver "Riesgos" (3er estado "desconocido" no implementado por falta de datos reales) | Nuevo parámetro `client` en `create_critical_equipment_summary_table`, propagado desde `store-overview-data` (sin nuevo `Input`). Gate vía `is_service_enabled`: Telemetría lee `monitoring-alerts` **O** `overview-data-freshness` (no `monitoring-telemetry` — confirmado que CAPSTONE carece de ese servicio pero sí tiene alerts+freshness, así que su columna Telemetría debe mostrar datos reales, no "Sin Fuente"); Tribología lee `monitoring-oil`. 2 estados nuevos: "Sin Fuente" (servicio deshabilitado, nivel cliente) y "Sin Datos" (servicio habilitado, sin registro para esa unidad — reemplaza "N/A"). Columnas nunca se ocultan (evita el riesgo de desincronización cabecera/filas); el estado se comunica vía badge. `priority` verificado: un estado real nunca se suprime por el otro lado ausente |
| W34-10 | **Implementada** | `dashboard/tabs/tab_predictive_overview.py` (nuevo `classify_predictive_status`), `dashboard/callbacks/predictive_callbacks.py`, `tests/test_w34_predictive_table.py` | 19/19 | 429 passed (412+17) en la implementación original; **2do defecto encontrado y corregido en la Fase 5** (ver abajo) | Ninguno | 3 defectos corregidos: (1) unidad con `avg_ranking_30d` y `max_fm_30d` ambos `NaN` → antes "Saludable", ahora "Sin datos" (nuevo 4º estado, con KPI card y color propios); (2) `NaN` en ranking/promedios se renderizaba como texto literal `"nan"` en verde (bug más severo de lo diagnosticado originalmente: no era "0 verde" sino "nan" verde) — ahora "—" gris; (3) orden inestable ante empates → `Unit` como clave secundaria. **Duplicación encontrada y eliminada**: `predictive_callbacks.py::sort_failure_mode_table` reimplementaba la clasificación byte-a-byte; ambos sitios ahora comparten `classify_predictive_status()`. Cabecera "Status"→"Estado". Valores de ranking sin alterar (verificado bit-a-bit). **Fase 5**: la corrección original sólo cubrió `_failure_table`; la tarjeta de prioridad hermana (`_priority_card`, sección "Estado Flota — Prioridad") tenía el mismo defecto sin corregir — una unidad "Sin datos" mostraba literalmente "nan"/"+nan" en pantalla. Corregido con el mismo criterio (`pd.notna` antes de formatear); ver `test_priority_card_renders_dash_for_missing_score_not_the_text_nan`. **Fase 6**: al sincronizar con `origin/dev`, la clasificación por umbrales de esta fila (incluido el 4º estado "Sin datos") quedó **superada** por la nueva `attach_status()` de `dev` (lee `estado` de `analisis_inteligente.parquet`, sólo 3 estados posibles por diseño — REQ-PR-05); `classify_predictive_status` se eliminó por quedar sin uso. La corrección de "nulo≠0/nan" para los VALORES numéricos (no el estado) se conservó y re-aplicó sobre la arquitectura nueva de `dev`. Ver Fase 6 para el detalle completo de la reconciliación |
| W34-02 | **Implementada** | `dashboard/callbacks/data_freshness_callbacks.py` (nuevo `FRESHNESS_STATUS_STYLE`), `dashboard/tabs/tab_data_freshness.py`, `tests/test_w34_freshness_style.py` | 14/14 | 454 passed (440+14), 0 regresión | "Desconocido" (data_type no reconocido, código inalcanzable en la app real) no se migró al nuevo dict — irrelevante en la práctica | 1 mapa (`FRESHNESS_STATUS_STYLE`) reemplaza 3 paletas independientes (leyenda, `FRESHNESS_CRITERIA`, 8 reglas de tabla); `bg`/`text` reutilizan tokens `:root` existentes (`predictive_styles.css`, cargados globalmente vía `assets/`) en vez de hex nuevos; umbrales de frescura sin cambios (verificado); nuevo estado "Sin Datos" visualmente distinto de Ok/Atención/Preocupante |
| W34-08 | **Implementada** | `dashboard/components/telemetry_charts.py`, `tests/test_w34_telemetry_limits.py` | 5/5 | 459 passed (454+5), 0 regresión | Ninguno | Sólo cambian los 4 strings `name=` de las trazas de límite (P95→"Límite superior marginal", P98→"Límite superior condenatorio", P5→"Límite inferior marginal", P2→"Límite inferior condenatorio"); nombres de columna del parquet (`P2`/`P5`/`P95`/`P98`) y valores `y` intactos (verificado bit-a-bit); orden de leyenda (`legendrank`) sin cambios |
| W34-09 | **Implementada** | `dashboard/components/telemetry_charts.py`, `dashboard/callbacks/telemetry_callbacks.py`, `dashboard/tabs/tab_telemetry_unit_detail.py`, `tests/test_telemetry_report.py` (modificado), `tests/test_w34_telemetry_window.py` | 1 modificado + 1 nuevo en `test_telemetry_report.py` (12/12) + 11/11 en el nuevo archivo | 471 passed (460+11), 0 regresión | Ninguno | Nuevos parámetros `window_days=1`, `show_events=False` en `build_signal_timeseries_card` (único call site real: `update_signal_cards`, confirmado por grep). Botones reales (`dbc.RadioItems` estilo `btn-group`, no el `rangeselector` de Plotly) para que la ventana sea un `Input` testeable; conteos de eventos siguen en la tabla KPI de la señal (no afectados). `test_signal_chart_highlights_events_and_starts_at_longest_episode`/`test_signal_chart_falls_back_to_recent_window_without_episodes` modificados para pasar `show_events=True` explícito (ruta opt-in preservada, no eliminada) + 1 test nuevo confirmando el default simplificado |
| W34-12 | **Implementada** | `dashboard/components/predictive_config.py`, `tests/test_w34_labels.py` (sección añadida) | 5/5 nuevos (31/31 en el archivo) | 476 passed (471+5), 0 regresión | 5 conflictos semánticos escalados (ver "Riesgos") | Diagnóstico exhaustivo (no sólo los 4 originales) encontró un 5º conflicto: `fuel_pump_intake_pressure_psi` ("admisión" vs "entrega", extremos opuestos de la bomba). Diseño simplificado respecto al plan original: se verificó que `TELEMETRY_LABELS` sólo se usa en oraciones/títulos de gráfico (`tab_predictive_evidence.py`), nunca en columnas angostas — no hay restricción real de espacio, así que **no se implementó un parámetro `style="short"/"long"`**; en su lugar `TELEMETRY_LABELS` deriva directamente de `SIGNAL_LABELS` para los ~20 códigos de sólo-estilo, y los 5 escalados quedan como literales explícitos con comentario |
| **F4** | **Completada** | — | Suite completa + `test_w34_callback_registration.py` (nuevo, 8/8) | 484 passed, 5 skipped, 7 failed/5 errors preexistentes (sin cambio vs. baseline) | Ver "Riesgos" (sin `data/` no hay validación visual con datos reales) | `compileall` limpio; `git diff --check` sin errores; registro de callbacks de las 5 áreas (General, Estado de Datos, Alertas, Telemetría, Predictivo) verificado exhaustivamente — cada `Output`/`Input`/`State` literal de esas 5 áreas resuelve contra un `id` real en el layout combinado o contra un id dinámico documentado explícitamente (creado por el `children` de otro callback); regresión específica de W34-05 confirmada (`detail-filter-telemetry` ausente de layout y callbacks) |
| **F5** | **Completada** | `src/utils/date_utils.py`, `dashboard/tabs/tab_predictive_overview.py`, `tests/test_w34_timestamps.py` (+1), `tests/test_w34_predictive_table.py` (+2), `tests/test_w34_callback_registration.py` (fixture endurecida) | Revisión completa del diff + arnés Dash real con datos sintéticos + suite completa | 576 passed, 1 skipped, 4 failed (preexistentes, ver abajo) — **2 bugs reales encontrados y corregidos** | Ninguno nuevo | Ver sección "Fase 5 — Validación visual" abajo para el detalle completo |

## Fase 5 — Validación visual (post-implementación)

Pedido explícito de la persona usuaria: revisar el diff completo y corroborar los cambios con una
prueba visual exhaustiva. El bloqueo B2 original (sin `data/`, sin `boto3`/`fastapi`) se resolvió
así:

1. **Instalación completa de `requirements.txt`** (antes sólo el subconjunto W34) — todo desde PyPI,
   sin credenciales ni red hacia AWS/S3 (`boto3`/`s3fs` son SDKs que no contactan nada hasta que se
   invoca un método; nunca se invocó ninguno). `import dashboard.app` pasó a funcionar sin excepción.
2. **Arnés Dash propio** (`w34_visual_harness.py`, fuera del repo, en el scratchpad de la sesión) que
   monta las funciones reales de layout (`tab_alerts.create_layout()`, `tab_data_freshness.create_layout()`,
   `tab_overview_general.create_layout()`) y registra los callbacks reales (`alerts_callbacks`,
   `data_freshness_callbacks`, `register_overview_general_callbacks`, `register_predictive_callbacks`,
   `register_predictive_pages_callbacks`) — **sin pasar por `dashboard/app.py`**, deliberadamente:
   `dashboard/app.py` exige autenticación real (`dashboard/auth.py` + `config/users.py`), y CLAUDE.md
   prohíbe usar credenciales/claves y el instructivo general prohíbe modificar configuración de
   seguridad — no se creó ningún usuario ni se intentó eludir el login de ninguna forma. El arnés es
   un servidor Dash aparte, en un puerto local distinto, sin relación con el login de producción.
3. **Datos sintéticos reales** bajo `data/` en este worktree (ya cubierto por `.gitignore:75` y
   `:78-81` — nunca se commitea, no aparece en `git status`). Dos clientes reales de
   `config/client_services.json` (sin inventar uno nuevo): `CDA` (todos los servicios habilitados) y
   `ENEX` (sin `monitoring-alerts` ni `overview-data-freshness` — el caso real de "Sin Fuente" en
   W34-13; `CAPSTONE` NO sirve para esto, tiene ambos servicios habilitados a pesar de no tener
   `monitoring-telemetry`). Datos dejados en el worktree (no se borraron): útiles para una futura
   validación visual manual; seguros porque son 100 % sintéticos y están gitignored.

**Bugs reales encontrados y corregidos** (ninguno visible en las 484 pruebas de la Fase 4 — ambos
requerían datos encadenados de punta a punta, exactamente lo que una prueba unitaria aislada no
ejercita):

- **`to_utc_naive` (W34-06)**: con una columna de timestamps genuinamente mixta (naive + `Z` +
  offset en la misma columna, plausible en un CSV "consolidado" que acumula filas de distintas
  épocas del pipeline), `pd.to_datetime(serie, utc=True)` infiere un formato de la primera fila y
  convierte a `NaT` cualquier fila que no calce — silenciosamente. En la prueba visual, 2 de 5
  alertas sintéticas (incluida la única "Mixto") desaparecieron de la tabla, del KPI "Alertas
  mixtas" (quedó en 0) y de la selección de detalle, sin ningún error visible. **Corregido**:
  reintento por-elemento sólo para las filas que dieron `NaT` pese a tener un valor de origen no
  nulo — aísla cada valor del "camino rápido" de pandas que asume un formato uniforme. Nuevo test:
  `test_a_genuinely_mixed_column_normalizes_every_row` (`tests/test_w34_timestamps.py`).
- **`_priority_card` (W34-10)**: la corrección original de "nulo ≠ 0 verde" cubrió `_failure_table`
  pero no la tarjeta hermana de prioridad por unidad (`_priority_card`, sección "Estado Flota —
  Prioridad" del resumen de Predictivo) — una unidad con estado "Sin datos" mostraba literalmente el
  texto `"nan"` / `"+nan"` en pantalla (mismo patrón: `NaN >= umbral` es `False` en pandas, y
  `f"{nan:.0f}"` produce el string `"nan"`, no una excepción). **Corregido** con el mismo criterio
  `pd.notna()` ya usado en `_score_cell_style`. Nuevos tests:
  `test_priority_card_renders_dash_for_missing_score_not_the_text_nan` y
  `test_priority_card_keeps_real_values_and_delta_sign_intact` (`tests/test_w34_predictive_table.py`).

**Fragilidad de prueba encontrada y corregida** (no es un bug de producto): al correr por primera
vez la suite completa con todas las dependencias, `test_w34_callback_registration.py` empezó a
fallar de forma dependiente del orden — `dash.Dash.__init__` drena `dash._callback.GLOBAL_CALLBACK_LIST`
hacia la instancia que se construye y **limpia la lista global** (`dash/dash.py`:
`self._callback_list.extend(...)` seguido de `.clear()`), así que un `@callback` a nivel de módulo
queda permanentemente reclamado por la primera app Dash que se construya en el proceso — con 578
pruebas construyendo apps Dash, alguna otra prueba ganaba esa carrera antes de la mía. Corregido
recargando (`importlib.reload`) los 3 módulos de callback bare (`alerts_callbacks`,
`telemetry_callbacks`, `data_freshness_callbacks`) justo antes de construir la app del fixture, para
garantizar que sea ésta la que los reclame sin importar qué corrió antes.

**Confirmado visualmente en un navegador real** (no sólo inspección de árbol de componentes en
Python), sobre el arnés con datos sintéticos, incluyendo interacción real (clicks, selección de
dropdown, cambio de cliente):

| Mejora | Cómo se confirmó |
|---|---|
| W34-01 | Etiquetas idénticas ("Cárter", "Posterior al motor", "Conducto principal de aceite") en la tabla de Alertas para valores en minúscula, mayúscula y con guión bajo |
| W34-03 | Tabla de Alertas sin columnas `ID`/`Fuente`/`Evidencia` visibles (ya confirmado en Fase 1-4) |
| W34-04 | Badge "Fuente: Mixto" en el encabezado de detalle; KPI "Alertas mixtas" contando correctamente tras el fix de W34-06 |
| W34-05 | Filtro "Con Telemetría" ausente del tab Detalle; "Fecha desde" (`placeholder="Sin límite"`) presente en su lugar |
| W34-06 | El mismo instante ("17/08/2026 11:00") en la tabla, el dropdown de selección y el encabezado de detalle, para una alerta con offset `-04:00` de origen — y bug real encontrado (ver arriba) |
| W34-07 | Panel de Análisis Inteligente con Diagnóstico/Causa probable/Acciones renderizado correctamente desde JSON estilo Capstone, con 2 acciones como lista |
| W34-08 | Leyenda del gráfico de evidencia con "Límite superior/inferior marginal/condenatorio" — cero trazas `P<n>` — render standalone de `build_signal_timeseries_card` |
| W34-09 | Mismo render: eje X de exactamente 1 día por defecto, 0 formas de evento pese a pasar un evento real; `window_days=7` expande a exactamente 7 días |
| W34-10 | KPI "Sin Datos: 1"; unidad sin ranking mostrando "Sin datos" en vez de "Saludable" — y bug real encontrado en `_priority_card` (ver arriba) |
| W34-11 | Señal catalogada + no catalogada (`ZZZ_UNKNOWN_SIGNAL`) ambas visibles sin excepción; `Payload`/`EngSpd` correctamente excluidos de la lista de señales pero presentes como indicadores de contexto |
| W34-13 | CDA/CAM-03 (servicio habilitado, sin registros) → "Sin Datos"; ENEX (servicio deshabilitado) → "Sin Fuente" en *todas* sus unidades, mientras Tribología sigue mostrando estados reales — las 2 semánticas distintas, lado a lado |
| W34-02 | Tabla y leyenda de Estado de Datos con el mismo mapa de color/ícono (`FRESHNESS_STATUS_STYLE`) |
| W34-12 | No tiene superficie de UI propia — confirmado indirectamente: las etiquetas que aparecen en Alertas (compartidas con `SIGNAL_LABELS`) coinciden con las ya extensamente probadas en `tests/test_w34_labels.py` |

**No confirmado por navegador real** (limitación reconocida, no ocultada): la vista completa de
Telemetría > Detalle de unidad (selectores de unidad/sistema/señal poblados) requiere el data-lake
particionado de salud por unidad (`data/telemetry/golden/{client}/unit_health/year=/week=/*.parquet`
+ `latest.json` + registro de señales YAML) — no reconstruido por ser en su mayoría infraestructura
ajena al alcance de W34. En su lugar, W34-08/09 se confirmaron renderizando `build_signal_timeseries_card`
directamente (la misma función, la misma llamada real que usa `update_signal_cards`) a HTML standalone
y abriéndolo en el navegador — evidencia visual real, aunque sin la navegación de la pestaña completa.

**Estado final de la suite** (con `requirements.txt` completo instalado — primera vez que corre
realmente completa en este worktree, ya que antes 5 archivos fallaban en la colección misma por
`ModuleNotFoundError`): **576 passed, 1 skipped, 4 failed**. Los 4 `failed` son preexistentes y
confirmados sin relación con ningún archivo de W34:
- 3 en `test_campbell_ai_chart_types.py`: dependen de `data/oil/essays_elements.xlsx`, un archivo de
  referencia que no existe en este worktree (mismo patrón que el resto de bloqueos por falta de `data/`).
- 1 en `test_campbell_ai_persistence.py` (`test_the_listing_is_newest_first_and_scoped_to_the_active_company`):
  inestable incluso corriendo sólo los archivos de Campbell AI juntos, sin relación con ningún archivo
  tocado por W34 — parece un problema de temporización/orden preexistente en esa suite, no investigado
  por estar fuera de alcance.

No es comparable en línea recta contra el baseline de Fase 0 (296 passed) porque ese baseline corrió
con dependencias parciales — varios archivos que antes ni siquiera se podían importar ahora corren
sus pruebas completas. La comparación honesta es: **cada falla actual se verificó individualmente y
ninguna toca un archivo de W34**.

## Fase 6 — Sincronización con `origin/dev` y validación con datos reales

Pedido explícito de la persona usuaria: (1) usar la data real de la copia productiva local
(`C:\Users\panch\Desktop\Coddi\CDA\Dashboard\tds_alerts_dashboard\data`) para corroborar que las
mejoras funcionan; (2) revisar si `dev` tuvo actualizaciones e incorporarlas al worktree; (3)
revisar si los cambios de W34 seguían funcionando tras eso y ajustarlos si no.

### Sincronización con `dev`

`git fetch origin` mostró que `origin/dev` había avanzado de `506ad72` (la base registrada en la
Fase 0) a `6bf2307` — 10 commits nuevos, incluyendo trabajo de otra persona en Predictivo que
**tocó 2 de los mismos 3 archivos que W34-10 modificó**: `dashboard/callbacks/predictive_callbacks.py`
y `dashboard/tabs/tab_predictive_overview.py` (`src/data/loaders.py` también se tocó por ambos lados,
pero en regiones no solapadas — se fusionó sin conflicto).

Secuencia: `git stash push -u` (todo el trabajo de W34 sin commitear) → `git merge origin/dev` (limpio,
sin conflicto, ya que el `HEAD` de esta rama no tenía nada propio aún) → `git stash pop` (aquí
aparecieron los 2 conflictos reales). El stash se conservó como red de seguridad hasta confirmar que
la suite completa quedó verde, y se eliminó (`git stash drop`) recién al final — **no se tocó ningún
otro stash de la lista** (hay stashes preexistentes de otras ramas/worktrees: `alerts-iteration-ui`,
`dev`, `Mantenciones`).

**Conflicto real, no mecánico**: `dev` reemplazó por completo la clasificación de estado del
Predictivo. Antes (W34-10, basado en umbrales de `avg_ranking_30d`/`max_fm_30d`, con un 4º estado
"Sin datos" para el caso de ambos valores en `NaN`) vs. ahora (`dev`, función nueva `attach_status()`
que lee el campo `estado` directamente de `analisis_inteligente.parquet` — REQ-PR-04 — con la regla
explícita, documentada y deliberada de que una unidad sin fila en ese archivo cae a `"Normal"` para
que sólo existan tres etiquetas: Anormal/Alerta/Normal — REQ-PR-05). `dev` también añadió:
ordenamiento por clic en cabecera de columna con ascendente/descendente (REQ-PR-09/10), tarjetas de
prioridad agrupadas por estado con encabezado de sección (REQ-PR-07/11), y una tarjeta KPI de "Fecha
Ejecución Modelo".

**Decisión de reconciliación**: se adoptó `attach_status()` de `dev` como fuente de verdad del
estado (es la decisión de producto más reciente y explícita — no correspondía a esta tarea
sobreescribirla con el criterio de umbrales que W34-10 había introducido antes de que `dev` avanzara).
`classify_predictive_status()` (la función que W34-10 había extraído) quedó **sin ningún llamador**
tras adoptar `attach_status()` en los 2 sitios que antes la usaban — se eliminó por ser código muerto,
no se dejó "por si acaso". Lo que SÍ se preservó y re-aplicó sobre la nueva arquitectura de `dev`
(defecto independiente de cuál sea la fuente del `status`, y que `dev` había reintroducido sin saberlo
en su reescritura): los valores `NaN` de ranking/modo de falla se formatean como `None`→"—" gris, no
como `0.0`→verde ni como el texto literal `"nan"` — en `_failure_table` (adaptado a la nueva columna
única de ranking dirigida por `window`) y en `_priority_card`. También se preservó "Unit" como
desempate determinista en el ordenamiento, combinado con el nuevo toggle ascendente/descendente de
`dev` (`ascending=[ascending, True]`, no un `False` fijo). Cabecera "Estado" (no "Status") preservada.

`tests/test_w34_predictive_table.py` se reescribió para reflejar esto: se eliminaron las 4 pruebas que
examinaban `classify_predictive_status` directamente (función ya no existe); se actualizó la firma de
`_failure_table` en todas las llamadas (3 argumentos → 5: `sorted_df, window, sort_by, ascending,
failure_modes`); se ajustaron los valores de `status` de fixture ("Saludable"/"Crítica" → "Normal"/"Anormal");
se corrigió una prueba de `_priority_card` que asumía el layout visual anterior (`dev` intercambió qué
número es el titular grande vs. el secundario). 11/11 pruebas verdes.

### Validación con datos reales

Se copiaron (sólo lectura desde el origen, nunca se escribió nada en la copia productiva) los
siguientes archivos reales al `data/` de este worktree (gitignored, nunca aparece en `git status`):
`alerts/golden/cda/consolidated_alerts.csv` (152 alertas reales, ene-2025 a jul-2026),
`telemetry/golden/cda/alerts_detail_wide_with_gps.csv`, `oil/golden/cda/{classified,machine_status}.parquet`,
`predictive/golden/cda/{motor.csv,transmision.csv,analisis_inteligente.parquet}`,
`auxiliar/cda/Data_Date_Last_Update.csv`, y `oil/golden/enex/*.parquet` (ENEX tiene datos reales de
aceite pero no de alertas — el contraste real para "Sin Fuente" de W34-13). Se excluyó el data-lake
de telemetría particionado por semana (varios GB, no relacionado a W34) y los archivos
`*_historico*`/backups (no son los que los loaders leen).

**Confirmado contra datos reales, sin ningún bug nuevo** (además de lo ya confirmado en Fase 5 con
datos sintéticos):
- **W34-06 a escala real**: 152 alertas reales (más de un año de datos acumulados, formatos de origen
  probablemente heterogéneos) normalizan sin ninguna fila perdida — `len(prepared) == 152`,
  `alert_summary()['latest']` resuelve al instante correcto, ninguna fecha `NaT`.
- **W34-01**: nombres de componente reales de producción ("MANDO FINAL TRASERO IZQUIERDO", "CONVERTIDOR",
  "DIFERENCIAL TRASERO") traducidos correctamente, incluidos varios no catalogados que caen al
  fallback Title Case legible.
- **W34-04**: `alert_summary()['mixed'] == 33`, exactamente igual al conteo crudo de
  `Trigger_type == 'Mixto'` en las 152 filas reales.
- **W34-07**: el `mensaje_ia` real de CDA usa el formato de texto libre en español (no el JSON estilo
  Capstone usado en la Fase 5 sintética) — `parse_ia_message_sections`'s rama regex legacy extrae
  diagnóstico/causa/acciones correctamente de las 152 filas reales, sin excepciones. Ambas ramas de
  parseo quedan así confirmadas contra datos reales.
- **W34-11**: catálogo de señales cubre bien los códigos reales de producción — muestra de 20 señales
  únicas, todas traducidas, incluidas combinaciones multi-señal correctamente deduplicadas.
- **W34-13**: con datos reales, las 11 unidades de CDA muestran Telemetría "Anormal" (frescura real
  vencida hace 32-34 días) y Tribología con estados reales variados (Normal/Alerta/Anormal,
  independientes de Telemetría) — cero falsos "Normal". ENEX con datos reales de aceite: Telemetría
  "Sin Fuente" en *todas* sus unidades (servicio deshabilitado), Tribología con estado real.
- **W34-10 / reconciliación con `dev`**: la pestaña Predictivo completa, ya con la arquitectura
  `attach_status` fusionada, renderizada en navegador contra las 11 filas reales de
  `analisis_inteligente.parquet`: conteos "Unidades Anormales: 4 / Alerta: 1 / Normales: 6" (suman
  exactamente 11), tarjetas agrupadas por estado, "Fecha Ejecución Modelo: 17 Jul 2026" real, tabla de
  modos de falla con la columna única dirigida por ventana y cabecera "Estado" — **cero apariciones de
  "nan"** pese a ser datos reales de producción con toda su variabilidad.

**Limitación reconocida**: el selector de rango de fechas (`dcc.DatePickerRange`) de la Vista General
no respondió a `form_input` en el arnés de pruebas (necesita interacción real de calendario, no un
valor de texto). Se verificó el mismo camino de código directamente en Python
(`prepare_alert_rows`/`alert_summary` sobre las 152 filas reales) en lugar de a través del widget de
calendario — cobertura equivalente, interacción de navegador distinta.

Al finalizar, se eliminó la copia de datos reales de este worktree (`data/` completo) — ya cumplió su
propósito de validación y no corresponde dejar una copia de datos de producción residente en un
worktree de tarea aislada.

Estado final de la suite tras la fusión + reconciliación: **581 passed, 1 skipped, 4 failed**
(los mismos 4 preexistentes de Campbell AI de la Fase 5, sin relación con W34 ni con la sincronización).

## Fase 7 — Decisiones de dominio aplicadas al código

Las 3 decisiones pendientes (W34-04, W34-12, W34-10/dev) fueron resueltas por la persona
usuaria y aplicadas directamente al código, no sólo documentadas:

- **W34-04**: etiqueta final confirmada **"Multitécnica"** (antes "Mixto", provisional). Cambio de
  una línea en `labels.py::SOURCE_STYLE["Mixto"]` — se propaga solo a las 4 superficies (tabla,
  leyenda, KPI, badge de detalle) porque todas ya derivaban de esa única fuente. También se
  actualizó el título del KPI "Alertas mixtas" → **"Alertas multitécnicas"** en
  `tab_alerts_general.py` para la misma consistencia. El valor crudo (`Trigger_type == "Mixto"`)
  no cambió — sigue siendo el dato real del pipeline, sólo cambió el texto mostrado.
- **W34-12**: los 5 conflictos semánticos + `DeltaExh` resueltos con criterio de dominio:
  - `TCOutTemp` → "Temperatura de salida del **convertidor de torque**" (no turbocompresor)
  - `oil_level_pct` → "**Nivel de aceite**" (genérico, no "Tanque Reserva")
  - `rifle_oil_pressure_psi` → "...del **rifle**" (no "Galería")
  - `oil_diff_pressure_psi` → "Presión diferencial del **filtro de aceite**" (específico, no genérico)
  - `fuel_pump_intake_pressure_psi` → "Presión de **admisión** de la bomba de combustible" (no "Entrega")
  - `DeltaExh` confirmado equivalente a `RtLtExhTemp` ("Diferencia de temperatura de escape") — se
    agregó como entrada propia en `SIGNAL_LABELS` (mismo texto), dejando a `gear_mismatch` como el
    único código realmente exclusivo de telemetría.
  `src/charts/signals.py` (2 valores corregidos + 1 entrada nueva) y
  `dashboard/components/predictive_config.py::TELEMETRY_LABELS` (los 6 códigos ahora derivan de
  `SIGNAL_LABELS` en vez de tener su propio literal) se actualizaron en consecuencia;
  `tests/test_w34_labels.py::W34_12_ESCALATED_CONFLICTS` quedó vacío (se mantiene como set, no se
  eliminó, para que un futuro conflicto nuevo tenga un lugar obvio donde aterrizar).
- **W34-10 / decisión de `dev`**: confirmado que "unidad sin análisis de IA → estado Normal"
  (REQ-PR-05) ya fue una decisión tomada por quien escribió esos commits en `dev` — no se
  modifica ni se revierte.

Verificado: suite completa **582 passed, 1 skipped, 3 failed** (los mismos 3 preexistentes de
Campbell AI, sin relación) tras aplicar los 3 cambios; validado además visualmente contra el
arnés Dash (ver [reporte visual](W34_REPORTE_VISUAL.html), sección "Decisión aplicada en esta
iteración" en W34-04 y W34-12).

## Fase 8 — Revisión de consistencia frontend (post Fase 7)

Pedido explícito de la persona usuaria: una revisión exhaustiva "desde la perspectiva de un
frontend experimentado" de las 13 mejoras, enfocada en que el estilo/formato sea consistente con
el resto del dashboard y que el look and feel sea "ad-hoc" (uniforme), no en re-verificar
funcionalidad ya probada en las Fases 5-7.

**Método**: cada diff de las 13 mejoras se releyó línea por línea contra (a) los design tokens ya
existentes en `dashboard/assets/predictive_styles.css` (`--surface-2`, `--text-muted`,
`--border-strong`, etc. — ya globales porque Dash sirve todo `assets/` en cada página) y (b) los
patrones de componentes ya establecidos en el resto del código (convención `dbc.Badge(color=...)`,
estructura de los diccionarios `STATUS_STYLE`, `display_format` de los `DatePicker*` existentes).
Los hallazgos se verificaron visualmente contra el arnés Dash real (Selenium + Edge headless,
datos sintéticos), no sólo por lectura de código.

**5 inconsistencias reales encontradas y corregidas** (todas dentro del alcance de las 13 mejoras
— ningún archivo fuera de lo ya tocado por W34):

1. **Tres grises de "sin dato" distintos para el mismo concepto.** W34-02 (Estado de Datos),
   W34-13 (Estado x Unidad) y W34-10 (tabla Predictivo) introdujeron, cada una por su cuenta, su
   propio par hex para el badge/celda "sin datos" (`var(--surface-2)`/`var(--text-muted)` vs
   `#e2e3e5`/`#6c757d` vs `#f1f2f4`/`#5c6570`) — exactamente el tipo de divergencia que W34-04 y
   W34-12 ya habían corregido para otros conceptos, pero no para este. Unificadas las 3 al mismo
   par de tokens (`var(--surface-2)`/`var(--text-muted)`, el que W34-02 ya usaba) en
   `overview_general_callbacks.py::STATUS_STYLE` y `tab_predictive_overview.py::_score_cell_style`.
2. **Icono "Sin Fuente" rompía el lenguaje visual de puntos de estado.** Los 4 estados reales
   (🟢🟡🔴⚪) son círculos; "Sin Fuente" usaba `▪️` (cuadrado). Cambiado a `⚫` (círculo relleno) —
   distinto de `⚪` (Sin Datos) pero de la misma familia visual.
3. **Peso de fuente inconsistente para el mismo estado "sin dato".** W34-02 ya había decidido que
   "Sin Datos" se muestra en peso normal (no negrita) para no competir visualmente con un estado
   real — W34-13 no aplicó ese mismo criterio en `make_badge` (Estado x Unidad), donde "Sin
   Datos"/"Sin Fuente" seguían en negrita igual que "Anormal"/"Alerta". Corregido para igualar el
   criterio ya establecido por su tabla hermana.
4. **El badge "Fuente" del encabezado de detalle de alerta (W34-04) usaba un tratamiento visual
   distinto al de las otras 3 superficies de la misma mejora.** Tabla, leyenda y tarjeta KPI usan
   "color saturado = acento, tinte claro = fondo"; el badge nuevo usaba relleno sólido sin fijar el
   color de texto explícitamente — el único `dbc.Badge` de todo el código que no usa la convención
   `color=` establecida en el resto del dashboard. Se extrajo el helper `_light_tint` (antes
   privado a `tab_alerts_general.py`) a `dashboard/components/labels.py` como `light_tint()`
   compartido, y el badge ahora usa el mismo tratamiento tinte-claro + texto-acento que la tarjeta
   KPI de la misma mejora.
5. **W34-09 dejó un control de ventana redundante.** Se agregó el nuevo grupo de botones Dash
   "1/7/30 días" (testeable, con estado propio) pero no se quitó el `rangeselector` nativo de
   Plotly ("Última semana"/"Últimas 2 semanas"/"Último mes") que ya existía en
   `build_signal_timeseries_card` — dos controles de ventana en el mismo gráfico, con conteos de
   días ligeramente distintos para opciones de texto similar, y sin que el control antiguo
   alimentara el estado Dash que `update_signal_cards` realmente usa. Esto contradice la razón de
   diseño que el propio plan de W34-09 ya había documentado ("usar botones Dash reales, no el
   rangeselector, porque este último no es observable desde una prueba de callback"). Se quitó el
   `rangeselector`; el `rangeslider` (mini-línea de tiempo arrastrable, un control distinto y no
   redundante) se mantiene.

**Verificado sin hallazgos** (confirma el alcance real de la revisión, no sólo lo que se corrigió):
leyenda de fuente y resaltado "Multitécnica" en la tabla de Alertas, valores de la tarjeta KPI tras
mover `light_tint`, el date picker "Fecha desde" (ya coincidía en `display_format` y en el patrón
label-arriba/control-abajo con sus 3 filtros hermanos en el mismo tab), el renombre
"Status"→"Estado" (sin residuos del texto en inglés), y el grupo de botones 1/7/30 días en sí
mismo (un patrón nuevo pero coherente con el lenguaje visual azul/Bootstrap del resto del
dashboard).

**Observado pero NO corregido, por quedar fuera del alcance de las 13 mejoras**: la paleta
Normal/Alerta/Anormal de Estado x Unidad (colores tipo Bootstrap alert) y la de la tabla Predictivo
(tonos del sistema de diseño ERS) usan dos juegos de hex distintos para los mismos 3 estados —
preexistente a W34, no introducido por ninguna de las 13 mejoras; unificarlo implicaría re-temizar
código no tocado por este trabajo y no fue lo que se pidió.

**Cambios de código de esta fase**: `dashboard/components/labels.py` (nuevo `light_tint()`),
`dashboard/tabs/tab_alerts_general.py`, `dashboard/callbacks/alerts_callbacks.py`,
`dashboard/callbacks/overview_general_callbacks.py`, `dashboard/tabs/tab_predictive_overview.py`,
`dashboard/components/telemetry_charts.py`; `tests/test_w34_predictive_table.py` (1 aserción de
color literal actualizada a los tokens compartidos — no fue un cambio de comportamiento, sólo el
valor esperado). Todos los archivos ya estaban dentro del diff pendiente de W34 (ver "Archivos en
el diff pendiente" en `W34_CODEX_HANDOFF.md`) — esta fase no agrega archivos nuevos al alcance.

**Verificación**: `compileall` limpio; suite completa **581 passed, 1 skipped, 4 failed** (mismas
pruebas de Campbell AI de siempre — confirmadas de nuevo como preexistentes al correrlas en
aislamiento total, `4 failed, 53 passed`; el conteo de fallas varía 3↔4 entre corridas por
inestabilidad ya documentada, no por relación con W34); validación visual con el arnés Dash real
(Selenium + Edge headless) contra datos sintéticos, clientes CDA y ENEX, en las 5 áreas corregidas.

## Fase 9 — Segunda revisión de calidad (correctness + reuse + efficiency + conventions)

Pedido explícito de la persona usuaria: otra revisión exhaustiva para asegurar la calidad del
trabajo, esta vez con foco en corrección funcional (no sólo visual/UX como la Fase 8). Se ejecutó
con 8 ángulos de búsqueda independientes (escaneo línea por línea, auditoría de comportamiento
eliminado, rastreo cruzado de funciones/llamadores, reuse, simplificación, eficiencia, altitud de
diseño, cumplimiento de `CLAUDE.md`) y una verificación de 1 voto por candidato antes de aceptar
cada hallazgo — 9 hallazgos sobrevivieron la verificación.

**Corregidos en esta fase:**

1. **`filter_alert_rows` (alerts_report.py) tenía el mismo defecto de zona horaria que W34-06 cerró
   en todas las demás superficies** — el filtro de fecha del tab General (`alerts-date-range-picker`)
   comparaba `start_date`/`end_date` con `pd.to_datetime()` crudo contra la columna `Timestamp`
   (UTC-naive), en vez de convertir el límite con `to_utc_naive(..., source_tz="America/Santiago")`
   como ya hacía el filtro "Fecha desde" del tab Detalle. Corregido; prueba de regresión agregada en
   `tests/test_w34_timestamps.py::test_filter_alert_rows_date_from_uses_chile_calendar_day_not_utc`.
2. **Señales no catalogadas desaparecían del gráfico de tendencias sin ningún aviso visible** —
   `select_plottable_signals` las excluye correctamente (W34-11), pero antes sólo quedaba un
   `logger.warning` en el backend. Se agregó una línea visible ("N señal(es) adicional(es) no
   catalogada(s) omitida(s) de este gráfico") en el encabezado de la tarjeta de Tendencias de
   Sensores cuando corresponde.
3. **`TELEMETRY_LABELS` (predictive_config.py) sólo sincronizaba el texto, no el mecanismo** — un
   código nuevo en `SIGNAL_LABELS` que aún no se agrega como clave aquí seguía mostrando el código
   crudo en Predictivo (`tab_predictive_evidence.py`'s `telem_labels.get(signal, signal)`).
   Corregido: `_resolve_client_dicts` ahora arma `telem_labels` como
   `{**SIGNAL_LABELS, **TELEMETRY_LABELS[client]}` — el dict curado por cliente sigue ganando en los
   códigos que ya tiene, pero cualquier código del catálogo compartido que aún no se haya revisado
   para este cliente muestra su etiqueta real en vez del código crudo. Prueba agregada en
   `tests/test_w34_labels.py::test_resolve_client_dicts_falls_back_to_signal_labels_for_uncurated_codes`.
4. **Tres badges de "sin dato" (Estado de Datos, Estado x Unidad, Predictivo) repetían a mano los
   mismos literales `var(--surface-2)`/`var(--text-muted)`**, sincronizados sólo por comentario, no
   por una fuente compartida real. Se centralizaron en `dashboard/components/labels.py` como
   `NO_DATA_ICON`/`NO_DATA_BG`/`NO_DATA_TEXT`; los tres archivos ahora importan de ahí.
5. **`format_local` se llamaba fila por fila en 3 lugares** (`initialize_alert_dropdown`,
   `filter_alert_dropdown_by_criteria` en alerts_callbacks.py, y `create_alerts_report_table` en
   alerts_tables.py) en vez de una sola vez sobre toda la columna — la forma vectorizada que
   `prepare_alert_rows` ya usaba correctamente. Corregido en los 3 sitios: se calcula la Serie
   formateada una vez antes del loop y se indexa adentro.
6. **Declaración de cumplimiento de `CLAUDE.md` reformulaba "no uses la copia productiva" (regla sin
   salvedad de aprobación) como "no se modificó" (una regla más angosta)** — corregido: ahora cita
   la redacción exacta de la regla, documenta que sí se leyó (bajo pedido explícito de la persona
   usuaria en el chat) y no certifica cumplimiento de una condición distinta a la escrita.

**Documentado pero NO corregido (riesgo de la corrección mayor que el del hallazgo):**

7. **`convert_utc_to_chile` (data_freshness_callbacks.py) sigue siendo una implementación
   independiente basada en `pytz`, sin pasar por `to_local_naive`/`format_local`** (introducidas
   por W34-06 como la única fuente de esta conversión). Verificado que NO es un simple renombre:
   sus 2 llamadores (`calculate_freshness_status`, en este archivo y en
   `overview_general_callbacks.py`) restan su resultado contra un `current_time_chile` **tz-aware**
   (`datetime.now(chile_tz)`), mientras que `to_local_naive` devuelve un valor **tz-naive** —
   cambiar el tipo de retorno rompería esa resta (`TypeError`) en ambos sitios. Se dejó documentado
   en el propio docstring de la función en vez de arriesgar un cambio de comportamiento no pedido;
   unificarlo de verdad requiere tocar la aritmética de ambos llamadores a la vez, un cambio más
   grande que el que motivó este hallazgo.
8. **El fallback de `translate_component_label` para un componente no catalogado aplica `.title()`**,
   que en teoría podría convertir un acrónimo real (p. ej. "ECU") en "Ecu". Verificado que este es
   el comportamiento **intencional y probado** (`tests/test_w34_labels.py::
   test_uncatalogued_component_gets_a_readable_fallback_not_raw_text` espera exactamente
   `"UNKNOWN_THING" → "Unknown Thing"`) y que ningún componente real usado hoy en este repositorio
   (fixtures, contratos, documentación) es un acrónimo — no se modifica, queda como una limitación
   teórica conocida en vez de una regresión.

**Decisión de dominio escalada y ya resuelta:**

9. ~~`oil_filter_dp_psi` y `oil_diff_pressure_psi` compartían el mismo texto~~ — **resuelto**: la
   persona usuaria confirmó la distinción (`oil_filter_dp_psi` = presión diferencial **del filtro**;
   `oil_diff_pressure_psi` = presión diferencial **del aceite de motor**). `SIGNAL_LABELS["oil_diff_
   pressure_psi"]` actualizado a "Presión diferencial del aceite de motor"; `oil_filter_dp_psi` no
   cambia (su texto ya era correcto). `predictive_config.py::TELEMETRY_LABELS` no requirió cambio
   propio — deriva de `SIGNAL_LABELS` por lookup, así que heredó la corrección automáticamente.
   Prueba de regresión: `tests/test_w34_labels.py::test_oil_filter_and_oil_diff_pressure_are_
   distinguishable`.

**Verificación de esta fase**: `compileall` limpio; `git diff --check` limpio; suite completa
**584 passed, 1 skipped, 3 failed** (mismas Campbell AI de siempre — el conteo de fallas sigue
variando 3↔4 entre corridas por la inestabilidad ya documentada, no por relación con W34; 3 pruebas
nuevas agregadas en esta fase).

## Fase 10 — Tercera revisión, enfoque crítico (incluye auto-revisión de las Fases 8-9)

Pedido explícito de la persona usuaria: una tercera revisión con "enfoque crítico" — a diferencia
de las Fases 8 y 9, esta pasada escaneó explícitamente los propios arreglos de esas dos fases con
la misma sospecha que el código original, en vez de darlos por buenos. Método: 10 ángulos de
búsqueda independientes (incluye dos nuevos respecto a la Fase 9 — "pitfalls" específicos de
Python/pandas, y corrección de wrappers/vistas-combinadas) + verificación de 1 voto + una pasada
final de barrido buscando huecos que los 10 ángulos no hubieran cubierto.

**Hallazgo principal — bug real de zona horaria, introducido por el propio arreglo de la Fase 9:**
`src/utils/date_utils.py::to_utc_naive` tiene dos rutas (Serie y escalar) para convertir una fecha
a UTC-naive. La ruta de Serie ya pasaba `ambiguous="NaT", nonexistent="NaT"` a `tz_localize` — la
ruta escalar (la que uso el arreglo de `filter_alert_rows` en la Fase 9) no. Como la transición de
horario de verano de Chile ocurre justo a la medianoche local, cualquier fecha límite de un filtro
puede caer exactamente ahí (confirmado empíricamente: 2024-09-08, 2025-09-07, 2026-09-06 fallan).
Antes del arreglo de la Fase 9, esto no era alcanzable (`filter_alert_rows` no convertía la fecha).
Después del arreglo de la Fase 9 y antes de esta Fase 10, esa misma fecha límite lanzaba
`pytz.NonExistentTimeError` sin manejo, lo que habría roto todo el tab Alertas > General una vez al
año. Corregido en la raíz (paridad entre ambas rutas de `to_utc_naive`) y en los 2 lugares que
consumen el valor límite (`filter_alert_rows`, `filter_alert_dropdown_by_criteria`): ahora una fecha
en la transición se trata igual que una fecha inválida — se ignora ese límite del filtro, con un
log de advertencia, en vez de vaciar todo el resultado o lanzar una excepción.

**Otros hallazgos corregidos:**

- **`translate_component_label` (labels.py)**: el chequeo de `_COMPONENT_LABELS` pasó de "¿existe la
  clave?" a "¿el valor es verdadero?" — no distingue "no catalogado" de "catalogado con un valor
  vacío". Corregido a un chequeo de presencia explícito.
- **Docstring incorrecto en `tests/test_w34_callback_registration.py`**: afirmaba que
  `dash.Dash()` drena `GLOBAL_CALLBACK_LIST` al construirse. Verificado directamente contra el
  código fuente de `dash` instalado: ese drenado en realidad está registrado como un hook
  `before_request` de Flask (`Dash._setup_server`, conectado desde `init_app`) y sólo se ejecuta al
  atender una petición HTTP real — nunca al construir el objeto. La prueba en sí siempre funcionó
  correctamente, pero por un mecanismo distinto al que el docstring describía
  (`_all_output_ids()` lee `GLOBAL_CALLBACK_LIST` directamente, nunca a través de
  `app.callback_map`). Docstring corregido para reflejar el mecanismo real.
- **`W34_CODEX_HANDOFF.md`**: la lista "Qué no hacer" citaba la regla de `CLAUDE.md` como
  "...secretos ni credenciales", omitiendo "ni claves" (presente en el texto real de la regla y en
  las dos citas de `W34_HANDOFF.md`). Corregido.
- **El patrón de 3 sitios de la Fase 9 (`sorted_df` + Serie `format_local` separada + `.loc[idx]`
  dentro del loop)**: dos ángulos de revisión independientes (reuse y eficiencia) coincidieron en
  que asignar la columna formateada directamente sobre el DataFrame (el mismo patrón que
  `prepare_alert_rows` ya usaba) es más simple y ~25-30% más rápido (medido). Corregido en los 3
  sitios.
- **`STATUS_STYLE`'s regla de peso de fuente** (Estado x Unidad): estaba codificada como una
  comprobación de pertenencia a una tupla de strings, en vez de una bandera por entrada (`'muted':
  True`) — el mismo patrón opcional que la clave `'border'` ya usa en el mismo dict. Corregido;
  esta misma división (dato en un dict, regla de "cuándo aplica" en otro lugar separado) ya había
  causado que esta tabla se olvidara la regla de atenuación una vez (Fase 8).

**Documentado, no corregido (mismo criterio que la Fase 9):** `convert_utc_to_chile`
(`data_freshness_callbacks.py`) sigue sin unificarse con `date_utils.py`. Esta pasada identificó
una ruta de arreglo de menor riesgo que en la Fase 9 (agregar un helper hermano tz-aware en
`date_utils.py` y delegar) — no aplicada todavía porque requiere confirmar primero si algún
llamador real sigue pasando un valor ya con zona horaria (la propia función tiene una rama
defensiva para ese caso). Queda documentado en el propio código con la ruta de arreglo concreta
para quien lo retome.

**Verificación de esta fase**: `compileall` limpio; `git diff --check` limpio; suite completa
**588 passed, 1 skipped, 4 failed** (mismas Campbell AI de siempre; 4 pruebas nuevas de regresión
agregadas — 2 para `to_utc_naive` en aislamiento, 1 para `filter_alert_rows`, 1 para
`filter_alert_dropdown_by_criteria` — todas cubriendo específicamente la fecha de transición de
horario de verano de Chile).

## Riesgos y bloqueos abiertos

- **4 fallas preexistentes** en `test_campbell_ai_chart_types.py` (radar de grupos de ensayo, por falta de `data/oil/essays_elements.xlsx`) y `test_campbell_ai_persistence.py` (inestable por temporización, no por W34) — fuera de alcance, ver detalle en "Fase 5" arriba, no se tocan.
- ~~Filtro de fecha del tab General (`filter_alert_rows`) sin conversión de zona horaria~~ — **corregido en la Fase 9** (segunda revisión de calidad): comparaba `start_date`/`end_date` contra `Timestamp` (UTC-naive) sin pasar por `to_utc_naive`, el mismo defecto que W34-06 había cerrado en todas las demás superficies. Ver "Fase 9" arriba.
- **W34-06 — bucketing semanal no evaluado**: `create_alerts_per_week_chart` (gráfico "Evolución temporal") agrupa alertas por semana ISO-domingo usando `Timestamp` UTC-naive directamente, sin conversión a hora local. Un evento cerca de medianoche UTC podría caer en una semana distinta a la que un usuario esperaría en hora de Chile. No incluido en el alcance explícito de W34-06 (no estaba en la lista de archivos aprobada) porque cambiar el bucketing afecta también el filtro cruzado por semana (`active_filters['week']`), un cambio de mayor riesgo que no se pidió. Queda documentado para decisión futura, no corregido silenciosamente.
- **Dead code adicional encontrado** (no tocado, mismo criterio que `create_alerts_datatable` en W34-03): `create_alert_detail_card` (`alerts_tables.py`), `create_sensor_trends_chart` y `create_gps_route_map` (versiones no-"golden", `alerts_charts.py`) — sin ningún consumidor vivo.
- **`parse_ia_message_sections`** (validado en W34-07, no modificado): su guardia `not x or pd.isna(x)` lanza excepción con `pd.NA`/listas — no se activa en el pipeline real (CSV vía `pd.read_csv` sólo produce `str`/`NaN` float en esa columna). Documentado con test explícito en `test_w34_ai_panel_regression.py`.
- **Validación visual**: resuelta en la Fase 5 (arriba) con un arnés Dash real y datos sintéticos — encontró y corrigió 2 bugs reales; ampliada en la Fase 6 contra datos reales de producción, sin bugs nuevos. Sigue pendiente, por ser desproporcionado al alcance de W34: la navegación completa de la pestaña Telemetría > Detalle de unidad (requiere reconstruir el data-lake particionado de salud por unidad, en su mayoría ajeno a las 13 mejoras). Recomendado antes de integrar a `dev`, si se quiere cerrar ese último tramo: una pasada manual en un entorno con `data/telemetry/golden/{client}/unit_health/` real montado.
- **W34-10 / decisión de `dev` (Fase 6→7)**: al fusionar `origin/dev`, el 4º estado "Sin datos" que W34-10 había introducido para una unidad sin ranking calculado quedó reemplazado por la regla de `dev` (`attach_status`, REQ-PR-05, commits `9a6571a`/`436a1b7`/`0299821`): una unidad sin fila en `analisis_inteligente.parquet` se muestra como **"Normal"**. Se escaló esta pregunta y **la persona usuaria confirmó (Fase 7) que esa decisión ya fue tomada por quien escribió esos commits** — cerrado, no se modifica ni se re-discute.
- **Sincronización con `dev` (Fase 6)**: se trajeron 10 commits nuevos de `origin/dev` (hasta `6bf2307`) — no sólo el trabajo de Predictivo reconciliado arriba, también cambios en autenticación (`dashboard/callbacks/auth_callbacks.py`, `src/data/auth_events_repository.py`, `src/utils/auth_event_logger.py`), Campbell AI (`dashboard/campbell_ai/callbacks.py`), `dashboard/app.py`, `dashboard/layout.py` y `config/settings.py` — ninguno de estos se solapó con archivos de W34, se fusionaron sin conflicto y sin necesidad de revisión adicional para esta tarea.
- ~~`oil_filter_dp_psi` y `oil_diff_pressure_psi` comparten el mismo texto en `SIGNAL_LABELS`~~ — **resuelto** (ver "Fase 9" arriba): confirmado como filtro vs. aceite de motor, texto distinto aplicado.
- **`convert_utc_to_chile` (data_freshness_callbacks.py) sigue duplicando, con `pytz`, la conversión que `to_local_naive`/`format_local` centralizaron (W34-06)** (Fase 9): no es un simple renombre — sus 2 llamadores restan su resultado contra un valor tz-aware, así que unificarlo de verdad requiere tocar esa aritmética en ambos sitios a la vez. Documentado en el propio código; no se modifica el comportamiento.

## Resumen final

**Las 13 mejoras P0–P2 asignadas están cerradas**: 11 `Implementada`, 2 `Validada/no duplicar` (W34-03, W34-07 — ya estaban resueltas antes de esta tarea; se blindaron con pruebas de regresión). Cero mejoras `Bloqueada` o `No reproducible`.

- **13 archivos de prueba nuevos** + 1 archivo de prueba existente modificado (`tests/test_telemetry_report.py`, ver W34-09).
- **Estado final de la suite completa** (con `requirements.txt` íntegro instalado, `dev` fusionado, Predictivo reconciliado, las 3 decisiones de dominio aplicadas): **582 passed, 1 skipped, 3 failed** — los 3 `failed` son preexistentes, verificados uno a uno como no relacionados con ningún archivo de W34 ni con la sincronización con `dev` (detalle en Fase 5/6). No comparable en línea recta contra el baseline de Fase 0 (296 passed): ese baseline corrió con dependencias parciales, y `test_w34_predictive_table.py` se reescribió en la Fase 6 (4 pruebas de una función eliminada salieron, 1 nueva entró) — la comparación honesta es cualitativa, no una resta simple.
- **2 bugs reales encontrados y corregidos durante la Fase 5** (validación visual con datos sintéticos): normalización de timestamps con formatos genuinamente mixtos en una columna (W34-06), y texto literal "nan" en la tarjeta de prioridad de Predictivo (W34-10).
- **Fase 6**: `origin/dev` fusionado (10 commits nuevos); el conflicto real en Predictivo (`dev` reemplazó la clasificación de estado por umbrales por su propia `attach_status()`, más reciente) se reconció preservando la corrección de "nulo≠nan/0" de W34-10 sobre la arquitectura nueva de `dev`; validado además contra datos reales de producción (152 alertas reales, 11 unidades reales de Predictivo) sin encontrar ningún bug nuevo.
- **Fase 7**: las 3 decisiones pendientes (W34-04, W34-12, W34-10/dev) fueron resueltas por la persona usuaria y aplicadas al código (ver sección dedicada arriba) — ninguna mejora depende ya de una decisión de producto sin tomar.
- **Fase 8**: revisión exhaustiva de consistencia frontend (estilo/formato/look&feel contra el resto del dashboard) — 5 inconsistencias reales encontradas y corregidas, todas dentro del alcance ya tocado por las 13 mejoras (ver sección dedicada arriba). Suite final tras esta fase: **581 passed, 1 skipped, 4 failed** (mismas fallas preexistentes de Campbell AI, confirmadas de nuevo en aislamiento).
- **Fase 9**: segunda revisión de calidad, esta vez de corrección funcional (8 ángulos de búsqueda + verificación de 1 voto) — 9 hallazgos confirmados: 6 corregidos (incluye un defecto de zona horaria real en el filtro de fecha del tab General, y una señal que desaparecía sin aviso de un gráfico), 2 documentados y dejados sin tocar por ser de mayor riesgo que beneficio corregirlos ahora, y 1 escalado a la persona usuaria por requerir una decisión de dominio (ver sección dedicada arriba). Suite final: **584 passed, 1 skipped, 3 failed** (mismas Campbell AI; +3 pruebas nuevas de regresión).
- **Fase 10**: tercera revisión, enfoque crítico — 10 ángulos de búsqueda (incluye 2 nuevos: pitfalls de Python/pandas, corrección de wrappers/vistas combinadas) + verificación + barrido final, con foco explícito en re-escanear los propios arreglos de las Fases 8-9. Encontró y corrigió un bug real de zona horaria en `to_utc_naive` (introducido en la Fase 9: la ruta escalar no manejaba fechas en la transición de horario de verano de Chile, que ocurre justo a medianoche), más 5 mejoras adicionales (una comprobación de presencia vs. verdad en `translate_component_label`, un docstring técnicamente incorrecto, una cita incompleta de una regla en el handoff de Codex, un patrón de 3 sitios simplificado y ~25-30% más rápido, y una regla de atenuación visual consolidada). 1 hallazgo documentado y no corregido, con una ruta de arreglo de menor riesgo ya identificada para el futuro (ver sección dedicada arriba). Suite final: **588 passed, 1 skipped, 4 failed** (mismas Campbell AI; +4 pruebas nuevas de regresión, todas sobre la transición de horario de verano).
- **Verificación de registro de callbacks** (nueva, no pedida explícitamente por el plan pero exigida por su "definición de terminado"): confirma que General, Estado de Datos, Alertas, Telemetría y Predictivo siguen registrando sus callbacks y que cada `id` referenciado existe en el layout combinado o es un id dinámico documentado.

Comandos de verificación final (ejecutados y registrados en este documento; reproducibles con el venv en `.venv/`):

```bash
python -m compileall -q dashboard src config
python -m pytest -q tests --continue-on-collection-errors --basetemp=<tmp_dir>
git diff --check
git status --short --branch
git fetch origin && git log --oneline 506ad72f765198b32effa261f04e5319730c34bf..origin/dev  # Fase 6
```

**Cumplimiento de las reglas de `CLAUDE.md` (worktree `claude-dashboard-w34`), reafirmado al cierre:**
- **Lectura de la copia productiva local (Fase 6)** — nota de transparencia añadida en la revisión de calidad: `CLAUDE.md` dice literalmente "No uses la copia productiva local..." (sin la salvedad "sin aprobación explícita" que sí tiene la regla vecina de `git push`/despliegues). La Fase 6 leyó/copió — sólo lectura, nunca escritura — archivos reales desde `C:\Users\panch\Desktop\Coddi\CDA\Dashboard\tds_alerts_dashboard\data` hacia el `data/` de este worktree, bajo un pedido explícito de la persona usuaria en el chat (no una decisión unilateral de la sesión). Tal como está redactada la regla, esa lectura cae dentro de "usar" la copia productiva, no sólo de "modificarla" — se documenta esa distinción aquí en vez de certificar cumplimiento de una regla más angosta. Ningún código ni configuración de la copia productiva se tocó; nunca se escribió nada allí; no se tocaron otros worktrees, `.env`, secretos, credenciales ni claves.
- No se ejecutó `git push`, despliegues, Docker con servicios externos, AWS/S3 ni pipelines productivos.
- No se creó ningún commit — el worktree queda con los cambios sin confirmar (`git status` los lista) para que la persona usuaria revise el diff completo antes de decidir cómo confirmarlos.
- Se fusionó `origin/dev` **hacia** esta rama (pedido explícito de la persona usuaria, Fase 6) — dirección opuesta a lo que el plan prohíbe ("no hagas merge ni cherry-pick hacia `dev`"); en ningún momento se hizo merge ni cherry-pick de este trabajo hacia `dev`.
- La integración de este trabajo hacia `dev` sigue pendiente de revisión y aprobación humana, como exige el plan.

**Siguiente acción sugerida**: revisar este handoff, el [reporte visual](W34_REPORTE_VISUAL.html) y el diff (`git diff`) — las 3 decisiones de producto que antes quedaban pendientes ya se resolvieron y aplicaron (Fase 7), así que no falta ninguna decisión de dominio para avanzar. Ver [`W34_CODEX_HANDOFF.md`](W34_CODEX_HANDOFF.md) para el plan de revisión y la estrategia de commit propuesta.

**Nota**: `data/` no existe en este worktree — los fixtures sintéticos de la Fase 5 y la copia de datos reales de la Fase 6 se usaron y se eliminaron al terminar cada validación. Si se quiere repetir alguna, ambas fases documentan exactamente qué archivos y esquema se usaron.
