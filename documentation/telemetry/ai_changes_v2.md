# AI Comments — Recent Changes

**Date**: June 2026  
**Scope**: Schema restructuring, language change, field semantics

---

## Summary

The AI Comments module has been restructured to improve clarity, actionability, and alignment with the Spanish-speaking maintenance teams that consume the dashboard.

---

## Changes

### 1. Language: All AI output is now in Spanish

All prompts, system messages, and generated text are now in Spanish. This applies to `description`, `explaining`, and `recommended_action` fields at every level.

**Before**: English text (e.g., "Transmission showing worsening lockup slip...")  
**After**: Spanish text (e.g., "Transmisión mostrando deslizamiento de lockup en deterioro...")

---

### 2. Replaced `comment` with `description` + `explaining`

The single `comment` field has been split into two structured fields at all three levels (signal, system, unit):

| Field | Purpose | Length |
|-------|---------|--------|
| `description` | Brief headline of what was detected | ~20 words max |
| `explaining` | Detailed explanation of findings and why they are relevant | 2-4 sentences |

This supports **progressive disclosure** in the dashboard: show `description` by default, reveal `explaining` on demand.

---

### 3. `recommended_action` only at system and unit level

Actions require sufficient context to be meaningful. Signal-level observations alone don't provide enough information for actionable recommendations.

| Level | `description` | `explaining` | `recommended_action` |
|-------|:---:|:---:|:---:|
| Signal | ✓ | ✓ | ✗ |
| System | ✓ | ✓ | ✓ |
| Unit | ✓ | ✓ | ✓ |

---

### 4. Structured JSON output from LLM

The LLM is now instructed to respond in JSON format, which is parsed directly into fields. This replaces the previous approach of splitting free-text responses on "Recommended action:" markers.

**Before**:
```
Diagnosis text paragraph...
Recommended action: Do something.
```

**After** (LLM response):
```json
{
  "description": "Breve resumen del hallazgo.",
  "explaining": "Explicación detallada de lo encontrado y por qué es relevante...",
  "recommended_action": "Acción recomendada."
}
```

Fallback handling is in place if JSON parsing fails (logs a warning, uses raw text as `description`).

---

## Affected Files

| File | Change |
|------|--------|
| `src/techniques/ai_comments.py` | Prompts in Spanish, JSON output format, `description`/`explaining` fields |
| `src/config/settings.py` | Increased token budgets (400/600/700) |
| `src/main.py` | Added `--skip-ai-comments` CLI flag |
| `documentation/telemetry/data_contracts.md` | Updated schemas for sections 6-8, Pydantic validators |
| `documentation/telemetry/dashboard_proposal.md` | Updated display rules for Spanish + two-field structure |
| `documentation/telemetry/ai_integration_changes.md` | Updated schema tables and benefits section |

---

## Data Contract Impact

### Signal Comments (`signal_comments.parquet`)

Removed: `comment`  
Added: `description` (string, not null), `explaining` (string, not null)

### System Comments (`system_comments.parquet`)

Removed: `comment`  
Added: `description` (string, not null), `explaining` (string, not null)  
Kept: `recommended_action` (string, nullable)

### Unit Comments (`unit_comments.parquet`)

Removed: `comment`  
Added: `description` (string, not null), `explaining` (string, not null)  
Kept: `recommended_action` (string, nullable), `urgency` (string, not null)

---

## Dashboard Impact

- Default text for Normal entities changed to: "Operando dentro de parámetros normales."
- `description` shown as headline/summary in tables and cards
- `explaining` shown expanded or on-demand (progressive disclosure)
- `recommended_action` shown as callout at system/unit level only

---

## Migration Notes

- This is a **breaking change** for any consumer reading the `comment` column from AI comment parquet files
- Re-running the pipeline will regenerate comments with the new schema, overwriting the current week's partition
- Previous weeks' data retains the old `comment` field — dashboard code should handle both gracefully during transition
