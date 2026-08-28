# Handoff a Codex — Dashboard W34 (revisión + commit)

Documento de trabajo dirigido a Codex. Complementa (no reemplaza) a
[`W34_HANDOFF.md`](W34_HANDOFF.md) (registro técnico completo, matriz de trazabilidad,
decisiones y riesgos) y a [`W34_REPORTE_VISUAL.html`](W34_REPORTE_VISUAL.html) (evidencia
visual). Este archivo responde a una sola pregunta: **¿qué tiene que hacer Codex ahora?**

## Objetivo

Revisar el trabajo de las 13 mejoras P0–P2 de 2026-W34 implementado por Claude en este
worktree aislado, y —si la revisión no encuentra objeciones— crear el/los commit(s)
correspondientes. Claude no creó ningún commit propio: todo el trabajo vive como diff sin
confirmar sobre el `HEAD` actual.

## Estado exacto del repositorio

```
Rama:        ai/claude/dashboard-w34
Worktree:    C:\Users\panch\Desktop\Coddi\.worktrees\tds-alerts-dashboard\claude-dashboard-w34
HEAD actual: f667254  Merge remote-tracking branch 'origin/dev' into ai/claude/dashboard-w34
             6bf2307  version change                                    } commits de origin/dev,
             436a1b7  tab evidencia - 1 kpi card                        } ya fusionados, no
             ...                                                        } tocados por Claude
Diff sin confirmar: 20 archivos modificados (+1031 -407) + 15 archivos nuevos
```

**Importante**: el merge con `origin/dev` (10 commits, hasta `6bf2307`) **ya está confirmado**
como el commit `f667254` — no requiere una acción de Codex. Lo único pendiente de commitear es
el diff de las 13 mejoras W34 (incluida la reconciliación de un conflicto real de merge en
Predictivo — ver [`W34_HANDOFF.md`, sección "Fase 6"](W34_HANDOFF.md)).

## Archivos en el diff pendiente

**21 modificados:**
```
dashboard/callbacks/{alerts,data_freshness,overview_general,predictive,telemetry}_callbacks.py
dashboard/components/{alerts_charts,alerts_report,alerts_tables,labels,predictive_config,telemetry_charts}.py
dashboard/tabs/{tab_alerts_detail,tab_alerts_general,tab_data_freshness,tab_predictive_evidence,
  tab_predictive_overview,tab_telemetry_unit_detail}.py
src/charts/signals.py
src/data/loaders.py
src/utils/date_utils.py
tests/test_telemetry_report.py   (modificado, no nuevo — ver W34-09)
```

`tab_predictive_evidence.py` se sumó recién en la Fase 9 (segunda revisión de calidad) — no estaba
en el diff original de las 13 mejoras; ver el hallazgo #3 de esa fase en `W34_HANDOFF.md`.

**15 nuevos** (13 archivos de prueba + 2 documentos):
```
tests/test_w34_{ai_panel_regression,alerts_filters,alerts_source,alerts_table,
  callback_registration,freshness_style,labels,predictive_table,signal_variables,
  source_availability,telemetry_limits,telemetry_window,timestamps}.py
documentation/general/W34_HANDOFF.md
documentation/general/W34_REPORTE_VISUAL.html
```

La correspondencia archivo ↔ mejora (qué archivo pertenece a cuál de las 13) está en la
[matriz de trazabilidad de `W34_HANDOFF.md`](W34_HANDOFF.md) — no se repite aquí para no
duplicar una fuente que puede desactualizarse.

## Checklist de revisión sugerido

1. **Confirmar contexto** — leer `CLAUDE.md` de este worktree y `.coddi-local/task.json`;
   confirmar rama/base/worktree coinciden con lo declarado arriba.
2. **Leer el diff completo**: `git diff HEAD` (o archivo por archivo desde la matriz de
   trazabilidad). Prestar especial atención a `dashboard/tabs/tab_predictive_overview.py` y
   `dashboard/callbacks/predictive_callbacks.py` — son los 2 archivos donde Claude reconcilió
   un conflicto real contra el trabajo ya fusionado de `origin/dev` (no un conflicto mecánico;
   ver "Fase 6" en el handoff para el razonamiento completo de qué se conservó de cada lado).
3. **Ejecutar la suite completa** y comparar contra el resultado ya registrado
   (588 passed, 1 skipped, 4 failed — los mismos preexistentes de Campbell AI, sin relación con
   W34; el conteo de fallas varía 3↔4 entre corridas por inestabilidad ya documentada, confirmada
   de nuevo al correr esos archivos en aislamiento total):
   ```bash
   python -m compileall -q dashboard src config
   python -m pytest -q tests --basetemp=<tmp_dir>
   git diff --check
   ```
4. **Revisar visualmente** el [reporte con capturas](W34_REPORTE_VISUAL.html) — cada una de
   las 13 mejoras tiene evidencia real (arnés Dash + datos sintéticos, y por separado contra
   datos reales de producción).
5. ~~Decidir los 3 puntos abiertos~~ — **ya resueltos**: la persona usuaria confirmó las 3
   decisiones de producto (etiqueta "Multitécnica" para W34-04, los 5 conflictos semánticos de
   W34-12, y que "unidad sin análisis → Normal" en W34-10/dev ya fue decidido por quien escribió
   esos commits) y quedaron aplicadas al código antes de este handoff — ver "Fase 7" en
   [`W34_HANDOFF.md`](W34_HANDOFF.md). **Actualización (Fase 9)**: la segunda revisión de calidad
   encontró un 4º punto — `oil_filter_dp_psi` y `oil_diff_pressure_psi` habían quedado con el mismo
   texto en `SIGNAL_LABELS` — **ya resuelto también**: la persona usuaria confirmó la distinción
   (filtro vs. aceite de motor) y quedó aplicada al código. No queda ninguna decisión de dominio
   pendiente.
6. **Revisión de consistencia frontend** (ver "Fase 8" en [`W34_HANDOFF.md`](W34_HANDOFF.md)):
   una pasada dedicada, pedida explícitamente por la persona usuaria, comparó las 13 mejoras contra
   el estilo/formato ya establecido en el resto del dashboard. Encontró y corrigió 5
   inconsistencias reales (3 grises de "sin dato" distintos para el mismo concepto, un icono de
   estado que rompía el lenguaje de círculos de color, un badge que no seguía la convención
   `dbc.Badge(color=...)` del resto del código, y un control de ventana de tiempo duplicado en el
   gráfico de telemetría) — ninguna agregó archivos nuevos al diff, todas caen dentro de los
   archivos ya listados abajo.
7. **Segunda revisión de calidad, foco en corrección funcional** (nueva, ver "Fase 9" en
   [`W34_HANDOFF.md`](W34_HANDOFF.md)): 8 ángulos de búsqueda independientes + verificación de
   1 voto por hallazgo. 9 hallazgos confirmados: 6 corregidos (incluye un defecto real de zona
   horaria en el filtro de fecha del tab General — el mismo tipo de bug que W34-06 cerró en todo
   lo demás, sólo que faltaba ahí — y una señal que desaparecía de un gráfico sin ningún aviso
   visible), 2 documentados y dejados sin tocar por riesgo de regresión desproporcionado, y 1
   escalado como nueva decisión de dominio pendiente (ver punto 5 arriba, ya resuelta también).
   Esta fase sí agregó un archivo nuevo al diff: `dashboard/tabs/tab_predictive_evidence.py` (ya
   reflejado en la lista de archivos arriba).
8. **Tercera revisión, enfoque crítico** (nueva, ver "Fase 10" en [`W34_HANDOFF.md`](W34_HANDOFF.md)):
   10 ángulos de búsqueda + verificación + barrido final, re-escaneando explícitamente los propios
   arreglos de las Fases 8-9. Encontró y corrigió un **bug real introducido por el arreglo de la
   Fase 9**: `to_utc_naive`'s ruta escalar no manejaba fechas en la transición de horario de verano
   de Chile (que ocurre justo a medianoche, coincidiendo con cualquier límite de un filtro de
   fechas) — antes lanzaba una excepción no capturada; corregido en la raíz y en los 2 sitios que
   consumen el límite. Más 5 mejoras adicionales (ver "Fase 10"). No agregó archivos nuevos al
   diff.

## Estrategia de commit recomendada

**Un solo commit** para todo el diff pendiente. Razón: el trabajo se hizo, probó y verificó
como una unidad (una tarea, un plan aprobado, una validación final); dividirlo ahora
retroactivamente en 13 commits arriesga separar mal archivos que varias mejoras comparten
(p. ej. `alerts_callbacks.py` lo tocan W34-01/05/06/07/11 a la vez) sin ganar nada — la
trazabilidad por mejora ya existe en `W34_HANDOFF.md`, no depende de la granularidad del commit.

Mensaje sugerido (ajustar libremente al estilo real de commits de este repo):

```
feat: implement W34-01..W34-13 dashboard improvements (Francisco Vilches, 2026-W34)

- Unify component/signal/source labels across Alerts, General and Predictive
  (W34-01, W34-04, W34-11, W34-12)
- Normalize alert timestamps to a single UTC-naive source of truth, local
  time only at display (W34-06); fix a mixed-timestamp-format data loss bug
  found during visual QA
- Simplify Alerts detail filters and the telemetry signal chart default view
  (W34-05, W34-08, W34-09)
- Distinguish "no data" from "healthy" in the Predictive table and the
  per-unit status summary, instead of defaulting missing values to 0/green
  (W34-10, W34-13); fix a second nan-rendering bug found in the priority
  card, and reconcile with origin/dev's independent Predictive rewrite
  (attach_status/REQ-PR-04/05)
- W34-03 and W34-07 already implemented; added regression tests
- Apply the user's domain decisions on the 3 previously-open questions:
  final "Multitécnica" label (W34-04), 5 semantic variable-naming conflicts
  (W34-12), and confirm origin/dev's "no analysis -> Normal" rule (W34-10)
  stands as-is
- Frontend consistency pass: unify 3 divergent "no data" greys (Estado de
  Datos, Estado x Unidad, Predictivo table) onto the same design tokens;
  fix a status icon that broke the circular-dot visual language; align the
  alert-detail Fuente badge with the rest of W34-04's own accent-on-tint
  treatment instead of an untested solid fill; remove a redundant Plotly
  rangeselector left over after W34-09 added its own window-size buttons
- Quality-review pass (correctness/reuse/efficiency): fix a real timezone
  bug in the Alertas General tab's own date filter (the same class W34-06
  closed everywhere else, just missed here); show a visible note when a
  telemetry signal is uncatalogued instead of silently vanishing from its
  chart; make Predictivo's per-client label dict fall back to the shared
  signal catalogue instead of a raw code; consolidate the "no data" style
  tokens the frontend pass introduced into one shared source; vectorize 3
  call sites that formatted alert timestamps once per row

- Critical-focus review pass: fix a real DST bug the quality-review pass's
  own timezone fix introduced (to_utc_naive's scalar branch didn't handle
  Chile's DST transition, which lands on local midnight); harden both its
  callers against the same edge case; fix a truthiness-vs-presence bug in
  translate_component_label; correct a factually wrong docstring about when
  dash.Dash drains its callback registry; simplify and speed up (~25-30%)
  the 3 vectorized timestamp-formatting call sites; consolidate a
  de-emphasis rule that had already gone missing once into the same dict
  it belongs in

188+ new tests across 13 files (7 added across the quality-review and
critical-focus passes). Full suite: 588 passed, 4 pre-existing failures
unrelated to this work (Campbell AI, documented; count varies 3-4 between
runs due to already-documented flakiness).

A domain question surfaced during the quality-review pass — oil_filter_dp_psi
and oil_diff_pressure_psi had ended up sharing an identical label in
SIGNAL_LABELS — was resolved by the user (filter vs. engine oil) and is
already applied (see "Fase 9" in W34_HANDOFF.md).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

**Alternativa** (si se prefiere granularidad por mejora pese al costo de dividir a mano):
la matriz de trazabilidad de `W34_HANDOFF.md` lista, para cada `W34-XX`, sus archivos y
pruebas — es el material de partida para un `git add -p`/split manual, pero **no fue
diseñada ni verificada por Claude para ese propósito** (se verificó como un solo diff
consistente).

## Qué no hacer

- No `git push`, no merge ni cherry-pick hacia `dev` — la integración queda para revisión y
  aprobación humana explícita.
- No regenerar ni reemplazar `CLAUDE.md` ni `AGENTS.md`.
- No tocar la copia productiva local, otros worktrees, `.env`, secretos, credenciales ni claves.

## Comandos de verificación (reproducibles)

```bash
git -c safe.directory="*" log --oneline -5
git -c safe.directory="*" diff --stat HEAD
git -c safe.directory="*" diff --check
python -m compileall -q dashboard src config
python -m pytest -q tests --basetemp=<tmp_dir>
```
