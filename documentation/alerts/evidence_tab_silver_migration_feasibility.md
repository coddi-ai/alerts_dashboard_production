# Evidence Tab — Feasibility of Decoupling from Golden `alerts_detail_wide_with_gps.csv`

**Date:** 2026-09-01
**Scope:** Monitoring → Alerts → Evidence tab ("Vista Detallada"), Telemetry Evidence block only.
**Question:** Can this tab read from `telemetry/silver` instead of `telemetry/golden`, without losing functionality?
**Verdict:** Yes, feasible. Not a drop-in swap — one real gap, two things that need a small transform, everything else maps 1:1.

---

## 1. What "alerts_details" actually refers to

There is no file literally named `alerts_details` in the repo. The thing that would be decoupled is:

```
data/telemetry/golden/{client}/alerts_detail_wide_with_gps.csv
```

This is read only by the **Telemetry Evidence** section of the Evidence tab (`create_telemetry_evidence_section`, [alerts_callbacks.py:899](../../dashboard/callbacks/alerts_callbacks.py#L899)), which renders the sensor-trends chart, the GPS route map, and 4 context KPI cards for a single selected alert. The rest of the Evidence tab (alert header, oil evidence, maintenance evidence) reads from other files entirely and is out of scope here.

---

## 2. Current inputs — golden layer

**Source:** `alerts_detail_wide_with_gps.csv`, one row per telemetry sample, wide format (a `_Value`/`_Upper_Limit`/`_Lower_Limit` column triplet per sensor), already pre-joined to alerts.

| Input | Role in the Evidence tab |
|---|---|
| `AlertID`, `Unit` | Row selection — filters the file to the rows for the selected alert |
| `TimeStart` | X-axis of the sensor chart; window filter (~90 min before / 10 min after alert time); nearest-point lookup for GPS/KPIs |
| `Trigger` | Identifies which signal fired the alert (bolds/orders that panel first) |
| `State` | Marker color per point (Potencia / Transición / Ralentí / Alta en Vacío) |
| `GPSLat`, `GPSLon`, `GPSElevation` | Route map + "Elevación" KPI |
| `{feature}_Value` (per sensor, client-specific set) | One subplot per feature in the sensor-trends chart |
| `{feature}_Upper_Limit`, `{feature}_Lower_Limit` | Dashed threshold lines per feature |
| `Payload_Value` | "Carga (Payload)" KPI — CDA only, always null for Capstone |
| `EngLoad_Value` / `engine_load_pct_Value` | "Carga de Motor" KPI |
| `EngSpd_Value` / `engine_speed_rpm_Value` | "Velocidad de Motor" KPI |
| `SubState`, `PayloadState` | Present in the file but **not read** by the current code (dead columns) |

Key property of golden: it is **pre-joined to alerts** (has `AlertID`) and **pre-computed** (limit columns already resolved per row). Silver has neither.

---

## 3. Desired inputs — silver layer

**Source:** `data/telemetry/silver/{client}/Telemetry_Wide_With_States/Week{WW}Year{YYYY}.parquet` — weekly partitions, one row per raw sample, no alert concept.

Confirmed schema (read directly from parquet):

**Capstone** (66 cols): `Fecha, Unit, Estado, EstadoMaquina, EstadoCarga, GPSLat, GPSLon, GPSElevation, GroundSpeed, AlertGatePassed, OperationSessionId, ...` + raw signals: `coolant_pressure_psi, coolant_temp_c, fan_speed_rpm, engine_speed_rpm, engine_load_pct, egt_01_c..egt_16_c, egt_avg_c, oil_temp_c, oil_level_pct, power_hp, ...` (full list in loaders/exploration output).

**CDA** (41 cols): `Fecha, Unit, Estado, EstadoMaquina, EstadoCarga, GPSLat, GPSLon, GPSElevation, AmbAirTemp, BoostPres, EngCoolTemp, EngOilPres, EngSpd, GroundSpd, Payload, RtExhTemp, ...` (no `EngLoad`).

There is **no per-alert concept in silver at all** — no `AlertID`, no `Trigger`, no pre-computed limits. Alerts are a downstream product (`consolidated_alerts.csv`) that only references telemetry via `Unit` + `Timestamp`, not via any silver column.

---

## 4. Column-by-column mapping

| Golden input | Silver equivalent | Status |
|---|---|---|
| `Unit` | `Unit` | ✅ Direct match |
| `TimeStart` | `Fecha` | ✅ Direct match (rename) |
| `GPSLat`, `GPSLon`, `GPSElevation` | Same names, both clients | ✅ Direct match |
| `State` | `EstadoMaquina` (**not** `Estado` — verified against real data that golden `State` values match `EstadoMaquina`'s vocabulary) | ✅ Derivable — pick the right column |
| CDA raw signals (`EngCoolTemp`, `EngOilPres`, `EngSpd`, `GroundSpd`, `Payload`, brake/exhaust temps, etc.) | Same names | ✅ Direct match |
| Capstone raw signals (`coolant_temp_c`, `engine_speed_rpm`, `egt_*`, `oil_temp_c`, etc.) | Same names | ✅ Direct match |
| — | Capstone-only silver extras: `egt_avg_c`, `power_hp`, `oil_level_pct`, `fuel_pump_intake_pressure_psi`, etc. | ➕ Bonus — newly plottable, not in golden today |
| `AlertID` (row selection) | No equivalent | ❌ N/A in silver — replaced by `Unit` + time-window filter sourced from `consolidated_alerts.csv` |
| `Trigger` | Not in silver | ✅ Derivable — already available from `consolidated_alerts.csv.Trigger_Var`, which the callback already loads for the alert header |
| `{feature}_Upper_Limit` / `{feature}_Lower_Limit` | `silver/{client}/limits/` or `silver/{client}/baselines/` — **neither directory exists on disk today**, for either client | ❌ **Real gap** — see §5 |
| `EngLoad_Value` (CDA "Carga de Motor" KPI) | No `EngLoad` (or equivalent) column found anywhere in CDA silver, checked across 8 weeks of files | ❌ **Real gap** — source unclear |
| `Payload_Value` (Capstone) | No `Payload` column in Capstone silver | ⚪ Not a real gap — already null in golden too (no payload sensor on this equipment) |
| `SubState`, `PayloadState` | `EstadoMaquina`/`EstadoCarga` carry similar info | ⚪ Not needed — current UI doesn't read these columns anyway |

---

## 5. The two real gaps

### Gap A — Threshold lines (Upper/Lower limits)
Silver's `limits/` and `baselines/` subfolders don't exist on disk for CDA or Capstone. This looks like a blocker, but it isn't a new one: it's already the case for the existing **Monitoring → Telemetry → Detalle de Unidad** tab, which reads raw signals straight from this same silver parquet today. That tab's loader (`load_telemetry_limits`) and chart builder (`build_signal_timeseries_card`) are both already written to degrade gracefully — an empty limits frame just means no dashed threshold lines, nothing breaks.

**Implication:** migrating the Evidence tab to silver would (for now) mean losing the threshold-line overlay, same as the Telemetry tab already tolerates. Not a functional loss unique to this migration — it's an existing, accepted gap elsewhere in the product. Worth flagging to the team as "do we backfill `limits/`/`baselines/` before or after this migration?"

### Gap B — CDA `EngLoad` ("Carga de Motor" KPI)
No raw signal in CDA silver corresponds to golden's `EngLoad_Value`. Needs a conversation with whoever owns the silver ETL: either the raw source was never mirrored into `Telemetry_Wide_With_States`, or it's derived differently upstream. Until resolved, this KPI could keep reading from golden as a stopgap while everything else moves to silver, or drop from the CDA view.

---

## 6. What needs to change, mechanically

1. **New loader**: given `client`, `Unit`, and the alert's `Timestamp` (from `consolidated_alerts.csv`), resolve the 1–2 weekly silver partitions the `[-90min, +10min]` window falls into and return the filtered, concatenated slice. (A window near a week boundary spans two files — golden's pre-joined CSV never had this problem.)
2. **Rename/repoint** in `create_telemetry_evidence_section`: `State`→`EstadoMaquina`, `TimeStart`→`Fecha`, drop the `AlertID` filter in favor of the new time-window loader.
3. **Re-source `Trigger`** from `consolidated_alerts.csv.Trigger_Var` (already loaded) instead of the telemetry file.
4. **Wire limit lines** through the existing `load_telemetry_limits` (already empty-safe) so behavior matches the Telemetry tab until `limits/`/`baselines/` are materialized.
5. **Resolve CDA `EngLoad`** sourcing before cutting that KPI over (or keep it on golden as a stopgap).
6. **Validate**: for a sample of real alerts on both clients, confirm plotted signals, GPS route, and KPI values match today's golden-based output before removing the golden read path.

---

## 7. Bottom line for discussion

- **Feasible**: yes, for the large majority of the tab's functionality — GPS, sensor traces, state coloring, and the trigger highlight all map cleanly or derive from data already loaded elsewhere.
- **Not feasible today, without a decision**: threshold lines (accepted gap, mirrors existing Telemetry tab behavior) and CDA engine-load KPI (needs upstream clarification).
- **Net new capability**: several Capstone signals in silver aren't even exposed in golden today — decoupling is also an opportunity to add them.
