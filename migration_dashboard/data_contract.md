# Data Contract — Warning & SAP Mapping

Excerpted from the source repo's `documentation/data_contracts.md` (§4–§5) — trimmed to just what
the dashboard and its write path depend on. The pipeline-side contracts (raw signal payload
schemas, condition_label derivation per source) are omitted; the dashboard never touches raw
signals, only already-formed `Warning` records.

**Source of truth:** `agent/envelope.py` (Pydantic models) and `agent/erp/sap_adapter.py`. If this
doc and the code diverge, the code wins.

---

## 1. Warning Schema (read/displayed by both pages, written by `write_operations.py`)

| Field | Type | Allowed values / notes |
|---|---|---|
| `warning_id` | string (UUID) | Generated at creation |
| `client_id` | string | FK → client config |
| `asset_id` | string | — |
| `source` | enum | `alertas \| telemetria \| aceites \| predictivo` |
| `system` | enum | `motor \| transmision \| diferencial \| hidraulico \| convertidor \| direccion \| mando_final \| rueda \| frenos` |
| `condition_label` | enum | `alerta \| anormal`; immutable after generation |
| `severity` | enum | `low \| medium \| high \| critical` |
| `title` | string | ≤ 40 chars recommended; non-empty required for approval |
| `description` | text | required for approval |
| `recommended_action` | text | required for approval |
| `supporting_data` | object | `{raw_signal, threshold_context, pipeline_severity_hint}`; accumulates evidence entries on dedup match |
| `generated_at` | timestamp | ISO 8601, set at creation |
| `status` | enum | `pending \| validated \| rejected \| sent`; default `pending` |
| `validated_by` | string, nullable | operator ID; set on validate/reject |
| `validated_at` | timestamp, nullable | set on validate/reject |
| `operator_notes` | text, nullable | rejection reason, ERP error message, or free-form notes |
| `sent_at` | timestamp, nullable | set on successful ERP push |
| `erp_type` | enum | `sap \| ellipse \| maximo \| stub`; from client config, not the signal |
| `erp_reference` | string, nullable | SAP notification number (or synthetic stub value) |

### Lifecycle field population table

| Field | Set at `pending` | Set at `validated` | Set at `sent` | Set at `rejected` |
|---|:-:|:-:|:-:|:-:|
| `warning_id`, `client_id`, `asset_id`, `source`, `condition_label`, `severity`, `title`, `description`, `recommended_action`, `supporting_data`, `generated_at`, `erp_type` | ✅ | (carried) | (carried) | (carried) |
| `status` | `pending` | `validated` | `sent` | `rejected` |
| `validated_by` | — | ✅ | (carried) | ✅ |
| `validated_at` | — | ✅ | (carried) | ✅ |
| `operator_notes` | — | optional | (carried) / error message on failed push | ✅ (reason) |
| `sent_at` | — | — | ✅ | — |
| `erp_reference` | — | — | ✅ | — |

Also needed to render enum values as Spanish labels in the UI: `SOURCE_LABELS`, `SYSTEM_LABELS`,
`CONDITION_LABEL_LABELS`, `SEVERITY_LABELS`, `STATUS_LABELS` (all in `agent/envelope.py`, one dict
per enum above).

---

## 2. SAP IW21 Field Mapping (background for the real ERP connector — out of scope for this
handoff, but the exact mapping whoever builds it will need)

| Coddi Warning Field | SAP IW21 Field | Req. | Notes |
|---|---|:-:|---|
| *(client config `sap.notification_type`)* | Notification Type | 🔴 | e.g. `M2` |
| *(not sent — SAP-generated)* | Notification Number | 🔵 | Returned by SAP; stored as `erp_reference` |
| `title` | Short Text | 🔴 | ≤ 40 chars recommended |
| `asset_id` | Equipment / Functional Location | 🔴 | Resolved via client's `asset_id_format` — see §2.1 |
| *(client config `sap.planning_plant`)* | Planning Plant | 🔴 | e.g. `1000` |
| `validated_by` | Reported By | 🔴 | Operator who approved |
| `severity` | Priority | 🟡 | Homologation table §2.2 |
| `description` | Long Text (`[DETALLE DEL HALLAZGO]` block) | 🟡 | Full narrative |
| `recommended_action` | Long Text (`[ACCIÓN RECOMENDADA]` block) | 🟡 | Appended block |
| `operator_notes` | Long Text (`[NOTAS DEL OPERADOR]` block) | ⚪ | Omitted entirely when null |
| *(client config `sap.planner_group`)* | Planner Group | ⚪ | e.g. `MEC` |
| *(client config `sap.main_work_center`)* | Main Work Center | ⚪ | e.g. `MEC01` |
| *(operator input)* | Required Start / Required End | ⚪ | Set during validation, optional |
| `generated_at` | Malfunction Start | ⚪ | Timestamp of originating signal |

### 2.1 Technical Object Resolution (`asset_id_format`)

- `equipment` → `asset_id` populates `technicalObject.equipment`, `technicalObject.functionalLocation = null`
- `functional_location` → `asset_id` populates `technicalObject.functionalLocation`, `technicalObject.equipment = null`

### 2.2 Priority Homologation Table

| Coddi `severity` | Coddi `condition_label` | SAP Priority Code | SAP Priority Label |
|---|---|---|---|
| `low` | `alerta` | `4` | Baja |
| `medium` | `alerta` | `3` | Media |
| `high` | `alerta` / `anormal` | `2` | Alta |
| `critical` | `anormal` | `1` | Muy Alta / Urgente |

### 2.3 SAP Long Text Template

```
[DETALLE DEL HALLAZGO]
{warning.description}

[ACCIÓN RECOMENDADA]
{warning.recommended_action}

[NOTAS DEL OPERADOR]
{warning.operator_notes}   ← entire block omitted if operator_notes is null

[TRAZABILIDAD CODDI]
Fuente: {warning.source} | Clasificación: {warning.condition_label} | ID: {warning.warning_id}
```

The `[TRAZABILIDAD CODDI]` block is always appended, regardless of `operator_notes`.

### 2.4 SAP API Response (current stub — `agent/erp/sap_adapter.py`)

Success:
```json
{"success": true, "notificationNumber": "9000456789", "status": "CREATED", "message": "Maintenance notification created successfully"}
```

Failure:
```json
{"success": false, "notificationNumber": null, "status": "ERROR", "message": "Equipment 10004567 not found in plant 1000"}
```

On failure, `status` stays `validated` and `message` is written to `operator_notes`.
