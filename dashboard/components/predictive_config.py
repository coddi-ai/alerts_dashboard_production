"""
Configuración centralizada de modos de falla por cliente y componente.

Estructura de dos ejes: client -> component.
  - "cda":      configuración original (motor, transmision). Sin cambios de valores.
  - "capstone": nuevo cliente. El vocabulario de labels (telemetría y aceite)
                reutiliza los nombres ya validados en components/alerts_charts.py.

IMPORTANTE (datos de dominio de Capstone):
  Los modos de falla, el mapeo de variables por modo y los umbrales de aceite
  (OIL_THRESHOLDS["capstone"]) NO están confirmados con dominio todavía. Las
  entradas marcadas con `# TODO(capstone): validar con dominio` son placeholders
  funcionales construidos con señales que sí existen en el vocabulario Capstone,
  para que la app funcione sin caer al fallback de CDA. No se inventan umbrales
  numéricos: OIL_THRESHOLDS["capstone"] queda vacío hasta tener valores reales
  (un umbral equivocado es peor que uno ausente).
"""

from src.utils.logger import get_logger
from src.charts.signals import SIGNAL_LABELS

logger = get_logger(__name__)


# =============================================================================
# FAILURE_MODE_CONFIG  —  client -> component -> failure_mode
# =============================================================================

FAILURE_MODE_CONFIG = {
    "cda": {
        "motor": {
            "abrasive_wear_risk": {
                "label": "Desgaste Abrasivo",
                "oil_variables": ["Hierro", "Silicio", "Cromo"],
                "telemetry_variables": [],
                "description": "Desgaste por partículas abrasivas en el motor"
            },
            "combustion_risk": {
                "label": "Combustión",
                "oil_variables": ["Hollín", "Viscocidad"],
                "telemetry_variables": ["LtExhTemp", "RtExhTemp", "DeltaExh"],
                "description": "Problemas en el proceso de combustión"
            },
            "thermal_imbalance_risk": {
                "label": "Δ T° Escape",
                "oil_variables": [],
                "telemetry_variables": ["LtExhTemp", "RtExhTemp", "DeltaExh"],
                "description": "Desequilibrio en temperaturas de escape"
            },
            "oil_degradation_risk": {
                "label": "Degradación de Aceite",
                "oil_variables": ["Viscocidad", "Hollín"],
                "telemetry_variables": [],
                "description": "Deterioro de las propiedades del aceite"
            },
            "lubrication_failure_risk": {
                "label": "Falla de Lubricación",
                "oil_variables": ["Plomo", "Cobre"],
                "telemetry_variables": ["EngOilPres"],
                "description": "Problemas con el sistema de lubricación"
            },
            "bearing_wear_risk": {
                "label": "Desgaste de Cojinetes",
                "oil_variables": ["Plomo", "Cobre"],
                "telemetry_variables": ["EngOilPres"],
                "description": "Desgaste en los cojinetes del motor"
            },
            "blowby_risk": {
                "label": "Blow-by",
                "oil_variables": ["Hollín"],
                "telemetry_variables": ["CnkcasePres"],
                "description": "Fuga de gases de combustión al cárter"
            }
        },
        "transmision": {
            "clutch_pack_risk": {
                "label": "Desgaste de Clutch Pack",
                "oil_variables": ["Hierro", "Cobre", "Aluminio"],
                "telemetry_variables": ["LckupSlip", "TrnSlip"],
                "description": "Desgaste en los discos de embrague del paquete de clutch"
            },
            "thermal_degradation_risk": {
                "label": "Degradación Térmica",
                "oil_variables": ["Viscocidad", "Agua"],
                "telemetry_variables": ["TCOutTemp", "TrnLubeTemp"],
                "description": "Degradación del aceite por exceso de temperatura"
            },
            "planetary_gear_risk": {
                "label": "Desgaste de Engranajes Planetarios",
                "oil_variables": ["Hierro", "Silicio", "Cobre"],
                "telemetry_variables": ["gear_mismatch", "TrnSlip"],
                "description": "Desgaste en el tren de engranajes planetarios"
            },
            "bearing_risk": {
                "label": "Desgaste de Rodamientos",
                "oil_variables": ["Hierro", "Cobre", "Plomo", "Estaño"],
                "telemetry_variables": ["TrnLubeTemp"],
                "description": "Desgaste en rodamientos de la transmisión"
            },
            "contamination_risk": {
                "label": "Contaminación",
                "oil_variables": ["Silicio", "Agua", "Sodio", "Potasio"],
                "telemetry_variables": [],
                "description": "Ingreso de contaminantes externos al sistema"
            },
            "torque_converter_risk": {
                "label": "Convertidor de Torque",
                "oil_variables": ["Aluminio", "Cobre", "Hierro"],
                "telemetry_variables": ["LckupSlip", "TCOutTemp"],
                "description": "Deterioro del convertidor de torque"
            },
            "shift_quality_risk": {
                "label": "Calidad de Cambio",
                "oil_variables": ["Viscocidad", "Hierro"],
                "telemetry_variables": ["TrnSlip", "gear_mismatch", "LckupSlip"],
                "description": "Degradación en la calidad de los cambios de marcha"
            }
        },
    },
    "capstone": {
        # Motor Cummins QSK60. Nombres de telemetría en snake_case / Celsius,
        # correspondientes a la fuente nueva (migración ago-2026).
        # Los modos combustion y coolant perdieron variables sin reemplazo —
        # ver comentarios inline.
        "motor": {
            "abrasive_wear_risk": {
                "label": "Desgaste Abrasivo",
                "oil_variables": ["Silicio", "Hierro", "Aluminio"],
                "telemetry_variables": [],
                "description": "Ingreso de partículas contaminantes que generan desgaste acelerado en superficies metálicas internas"
            },
            "combustion_risk": {
                "label": "Combustión / Inyectores",
                "oil_variables": ["Hollín", "Combustible"],
                # Perdidas sin reemplazo en la fuente nueva:
                # 'Injector Metering (PSI)', 'Commanded Engine Fuel Rail Pressure (kPa)',
                # 'Water In Fuel Indicator 1 (bit)' (modificador).
                "telemetry_variables": [
                    "egt_avg_c",
                    "fuel_pump_intake_pressure_psi",
                ],
                "description": "Combustión ineficiente o incompleta por falla en inyectores o sistema Common Rail"
            },
            "thermal_imbalance_risk": {
                "label": "Desbalance Térmico entre Bancos",
                "oil_variables": [],
                "telemetry_variables": [
                    "DeltaExh",
                    "egt_lb_c",
                    "egt_rb_c",
                    "imp_lb_psi",
                    "imp_rb_psi",
                    "imt_lbf_c",
                    "imt_rbf_c",
                ],
                "description": "Diferencia térmica persistente entre los bancos del motor V16"
            },
            "turbocharger_risk": {
                "label": "Falla de Turbocompresor",
                "oil_variables": ["Aluminio", "Hierro", "Cromo"],
                "telemetry_variables": [
                    "turbo_speed_rpm",
                    "imp_lb_psi",
                    "imp_rb_psi",
                    "imt_lbf_c",
                    "imt_rbf_c",
                    "egt_lb_c",
                    "egt_rb_c",
                ],
                "description": "Falla en el sistema de turbocompresión en dos etapas, con pérdida de boost y eficiencia"
            },
            "oil_degradation_risk": {
                "label": "Degradación de Aceite",
                "oil_variables": ["Hollín", "Viscocidad", "Oxidación", "Combustible"],
                "telemetry_variables": ["oil_temp_c"],
                "description": "Pérdida progresiva de propiedades lubricantes por contaminación y estrés térmico"
            },
            "coolant_contamination_risk": {
                "label": "Contaminación por Refrigerante",
                "oil_variables": ["Sodio", "Potasio"],
                # Perdida sin reemplazo: 'Engine coolant level (%)'.
                # La interacción Na×nivel se sustituyó por Na×presión.
                "telemetry_variables": [
                    "coolant_temp_c",
                    "coolant_pressure_psi",
                ],
                "description": "Ingreso de refrigerante al aceite por falla de empaquetaduras, O-rings de liner o fisuras"
            },
            "lubrication_failure_risk": {
                "label": "Falla de Lubricación",
                "oil_variables": ["Hierro", "Plomo", "Cobre"],
                # Perdidos sin reemplazo (modificadores multiplicativos):
                # 'Engine Emergency (Immediate) Shutdown Indication (bit)',
                # 'Engine Controlled Shutdown Request (bit)'.
                "telemetry_variables": [
                    "rifle_oil_pressure_psi",
                    "oil_diff_pressure_psi",
                    "oil_temp_c",
                ],
                "description": "Lubricación insuficiente que genera contacto metal-metal y desgaste acelerado"
            },
            "bearing_wear_risk": {
                "label": "Desgaste de Cojinetes",
                "oil_variables": ["Plomo", "Cobre", "Hierro", "Estaño"],
                "telemetry_variables": ["rifle_oil_pressure_psi"],
                "description": "Desgaste progresivo de cojinetes de biela y bancada"
            },
            "blowby_risk": {
                "label": "Blow-by / Desgaste de Anillos",
                "oil_variables": ["Cromo", "Hierro", "Hollín"],
                "telemetry_variables": [
                    "crankcase_pressure_inh2o",
                    "oil_level_pct",
                ],
                "description": "Desgaste de anillos y liner con fuga de gases de combustión al cárter"
            },
        },
    },
}


# =============================================================================
# TELEMETRY_LABELS  —  client -> {signal: label}
# =============================================================================

# W34-12 — every code below reads its label from src/charts/signals.py's
# shared SIGNAL_LABELS catalogue instead of retyping its own copy; the small
# number of codes where the two used to name genuinely different things
# (not just different phrasing) were resolved by explicit domain decisions —
# see "Fase 7"/"Fase 9" in documentation/general/W34_HANDOFF.md for the
# per-code history. gear_mismatch is the only code with no SIGNAL_LABELS
# entry (genuinely telemetry-only) and keeps its own literal below.
TELEMETRY_LABELS = {
    "cda": {
        "CnkcasePres": SIGNAL_LABELS["CnkcasePres"],
        "DeltaExh": SIGNAL_LABELS["DeltaExh"],
        "EngOilPres": SIGNAL_LABELS["EngOilPres"],
        "LtExhTemp": SIGNAL_LABELS["LtExhTemp"],
        "RtExhTemp": SIGNAL_LABELS["RtExhTemp"],
        "LckupSlip": SIGNAL_LABELS["LckupSlip"],
        "TCOutTemp": SIGNAL_LABELS["TCOutTemp"],
        "TrnLubeTemp": SIGNAL_LABELS["TrnLubeTemp"],
        "TrnSlip": SIGNAL_LABELS["TrnSlip"],
        "gear_mismatch": "Desajuste de Marcha",  # no SIGNAL_LABELS entry
    },
    # Nombres QSK60 en snake_case (fuente nueva, temperaturas en Celsius).
    # Se eliminaron 3 señales que no existen en la fuente nueva:
    # Commanded Engine Fuel Rail Pressure, Engine coolant level, Injector Metering.
    "capstone": {
        "DeltaExh": SIGNAL_LABELS["DeltaExh"],
        "coolant_pressure_psi": SIGNAL_LABELS["coolant_pressure_psi"],
        "coolant_temp_c": SIGNAL_LABELS["coolant_temp_c"],
        "crankcase_pressure_inh2o": SIGNAL_LABELS["crankcase_pressure_inh2o"],
        "egt_avg_c": SIGNAL_LABELS["egt_avg_c"],
        "egt_lb_c": SIGNAL_LABELS["egt_lb_c"],
        "egt_rb_c": SIGNAL_LABELS["egt_rb_c"],
        "fuel_pump_intake_pressure_psi": SIGNAL_LABELS["fuel_pump_intake_pressure_psi"],
        "imp_lb_psi": SIGNAL_LABELS["imp_lb_psi"],
        "imp_rb_psi": SIGNAL_LABELS["imp_rb_psi"],
        "imt_lbf_c": SIGNAL_LABELS["imt_lbf_c"],
        "imt_rbf_c": SIGNAL_LABELS["imt_rbf_c"],
        "oil_diff_pressure_psi": SIGNAL_LABELS["oil_diff_pressure_psi"],
        "oil_level_pct": SIGNAL_LABELS["oil_level_pct"],
        "oil_temp_c": SIGNAL_LABELS["oil_temp_c"],
        "rifle_oil_pressure_psi": SIGNAL_LABELS["rifle_oil_pressure_psi"],
        "turbo_speed_rpm": SIGNAL_LABELS["turbo_speed_rpm"],
    },
}


# =============================================================================
# OIL_LABELS  —  client -> {variable: label}
# =============================================================================

OIL_LABELS = {
    "cda": {
        "Hierro": "Hierro (ppm)",
        "Silicio": "Silicio (ppm)",
        "Plomo": "Plomo (ppm)",
        "Cromo": "Cromo (ppm)",
        "Cobre": "Cobre (ppm)",
        "Sodio": "Sodio (ppm)",
        "Hollín": "Hollín (%)",
        "Viscocidad": "Viscosidad (cSt)",
        "Estaño": "Estaño (ppm)",
        "Aluminio": "Aluminio (ppm)",
        "Agua": "Agua (%)",
        "Potasio": "Potasio (ppm)",
        "Boro": "Boro (ppm)",
    },

    # Ensayos de aceite QSK60 — cubren todas las variables referenciadas por
    # los 9 modos de falla de Capstone.
    "capstone": {
        "Aluminio":    "Aluminio (ppm)",
        "Cobre":       "Cobre (ppm)",
        "Combustible": "Dilución Combustible (%)",
        "Cromo":       "Cromo (ppm)",
        "Estaño":      "Estaño (ppm)",
        "Hierro":      "Hierro (ppm)",
        "Hollín":      "Hollín (%)",
        "Oxidación":   "Oxidación (Abs/cm)",
        "Plomo":       "Plomo (ppm)",
        "Potasio":     "Potasio (ppm)",
        "Silicio":     "Silicio (ppm)",
        "Sodio":       "Sodio (ppm)",
        "Viscocidad":  "Viscosidad (cSt)",
    },
}


# =============================================================================
# OIL_THRESHOLDS  —  client -> {variable: {rango: (normal, alerta, critico)}}
# =============================================================================

OIL_THRESHOLDS = {
    "cda": {
        "Hierro":     {"LT_1000": (48.0, 57.0, 65.0), "GE_1000": (71.0, 84.0, 93.0)},
        "Cobre":      {"LT_1000": (5.0, 8.0, 17.0), "GE_1000": (7.0, 12.0, 51.0)},
        "Plomo":      {"LT_1000": (3.0, 5.0, 8.0), "GE_1000": (4.0, 5.0, 6.0)},
        "Silicio":    {"LT_1000": (5.0, 6.0, 8.0), "GE_1000": (5.0, 6.0, 7.0)},
        "Sodio":      {"LT_1000": (7.0, 9.0, 18.0), "GE_1000": (8.0, 9.0, 10.0)},
        "Viscocidad": {"LT_1000": (16.0, 17.0, 18.0), "GE_1000": (16.0, 17.0, 18.0)},
        "Hollín":     {"LT_1000": (64.0, 73.0, 84.0), "GE_1000": (91.0, 106.0, 120.0)},
        "Cromo":      {"LT_1000": (0.0, 0.5, 1.0), "GE_1000": (0.0, 0.5, 1.0)},
    },

    # TODO(capstone): sin umbrales de dominio confirmados. Se deja vacío a
    # propósito — las variables sin entrada simplemente no muestran zonas de
    # severidad (mismo comportamiento que una variable sin threshold en CDA).
    # Un umbral numérico equivocado sería peor que su ausencia.
    # Umbrales de aceite QSK60 (Capstone). El dataset de Capstone no separa por
    # rango de horas, así que ambos rangos (LT_1000 / GE_1000) apuntan al mismo
    # set (normal, alerta, crítico) — así el lookup por oilHourRange funciona
    # igual que en CDA sin tocar las funciones de charts/tablas.
    "capstone": {
        "Aluminio":    {"LT_1000": (3.0, 4.0, 5.0),   "GE_1000": (3.0, 4.0, 5.0)},
        "Boro":        {"LT_1000": (61.0, 63.0, 64.5),   "GE_1000": (61.0, 63.0, 64.5)},
        "Cobre":       {"LT_1000": (1.5, 5.0, 6.5),   "GE_1000": (1.5, 5.0, 6.5)},
        "Cromo":       {"LT_1000": (2.00, 3.0, 4.0),   "GE_1000": (2.00, 3.0, 4.0)},
        "Estaño":      {"LT_1000": (3.00, 3.0, 4.0),   "GE_1000": (3.00, 3.0, 4.0)},
        "Hierro":      {"LT_1000": (18.00, 19.0, 21.00), "GE_1000": (18.00, 19.0, 21.00)},
        "Hollín":      {"LT_1000": (1.50, 3.0, 4.50),   "GE_1000": (1.50, 3.0, 4.50)},
        "Oxidación":   {"LT_1000": (19.00, 24.5, 36.75), "GE_1000": (19.00, 24.5, 36.75)},
        "Plomo":       {"LT_1000": (2.5, 4.0, 6.0),   "GE_1000": (2.5, 4.0, 6.0)},
        "Potasio":     {"LT_1000": (3.0, 4.0, 10.5),   "GE_1000":  (3.0, 4.0, 10.5)},
        "Silicio":     {"LT_1000": (11.00, 12.0, 13.0), "GE_1000": (11.00, 12.0, 13.0)},
        "Sodio":       {"LT_1000": (4.0, 6.0, 13.5), "GE_1000": (4.0, 6.0, 13.5)},
        "Viscocidad":  {"LT_1000": (16.0, 17.0, 18.0), "GE_1000": (16.0, 17.0, 18.0)},
    },
}


# =============================================================================
# Four-limit Stewart lookup for the predictive oil-evidence view (v2.8)
# =============================================================================
#
# OIL_THRESHOLDS above is the legacy hardcoded 3-tuple table (kept only for
# historical reference - no live code path reads it anymore). The predictive
# oil-evidence view (predictive > {component} > evidence > oil evidence) now
# sources its limits from stewart_limits_four.parquet instead, via
# load_predictive_oil_limits_four() below.

# Machine dimension for the Stewart Limits lookup. Every predictive component
# today (motor, transmision) is a haul-truck subsystem - confirmed directly
# against stewart_limits_four.parquet, whose `machine` column is 'camion' for
# every row, for both CDA and CAPSTONE.
PREDICTIVE_STEWART_MACHINE = 'camion'


def load_predictive_oil_limits_four(client: str, component: str) -> dict:
    """
    Resolve the four-limit Stewart dict (LIC/LIM/LSM/LSC, data contract v2.8)
    for one predictive component ('motor', 'transmision', ...), or {} if
    unavailable.

    The predictive module's `component` key-space does not always match
    stewart_limits_four.parquet's `component` field 1:1 - e.g. CDA's Stewart
    component is literally 'motor' (an exact match), but CAPSTONE splits
    engine components into 'motor diesel'/'motor traccion derecho'/'motor
    traccion izquierdo' (no unambiguous match to predictive's generic
    'motor'). Rather than guess which Capstone sub-component to use - a wrong
    limit is worse than an absent one, the same principle already applied to
    OIL_THRESHOLDS["capstone"] above - this only resolves limits when
    `component` matches a Stewart Limits component name EXACTLY for that
    client; otherwise it returns {} (no limits shown for that combination),
    never falling back to the legacy OIL_THRESHOLDS table above.

    Args:
        client: Client key, any case ('cda', 'CDA', 'capstone', ...).
        component: Predictive component key ('motor', 'transmision', ...).

    Returns:
        Nested dict {essay: {oilHourRange: {LIC, LIM, LSM, LSC, ...}}}, or {}.
    """
    from config.settings import get_settings
    from src.data.loaders import load_stewart_limits_four

    settings = get_settings()
    limits_file = settings.get_stewart_limits_four_path(client)
    if not limits_file.exists():
        return {}

    limits = load_stewart_limits_four(limits_file)
    return limits.get(client.upper(), {}).get(PREDICTIVE_STEWART_MACHINE, {}).get(component, {})


# =============================================================================
# FAILURE_MODE_METHODOLOGY  —  client -> component -> {mode: descripción}
# =============================================================================

FAILURE_MODE_METHODOLOGY = {
    "cda": {
        "motor": {
            "abrasive_wear_risk": (
                "Se evalúa la concentración de partículas metálicas (Hierro, Cromo) "
                "y contaminantes abrasivos (Silicio) en el aceite. Incrementos en "
                "Hierro y Cromo sugieren desgaste interno de componentes, mientras "
                "que Silicio elevado indica ingreso de contaminantes externos."
            ),
            "combustion_risk": (
                "Se analiza la calidad de combustión a través del Hollín y la "
                "Viscosidad del aceite, junto con las temperaturas de escape "
                "(izquierda, derecha y diferencial). Hollín elevado con cambios "
                "de viscosidad y temperaturas anómalas indican combustión deficiente."
            ),
            "thermal_imbalance_risk": (
                "Se monitorea el diferencial entre las temperaturas de escape "
                "izquierda y derecha. Un delta elevado o sostenido puede indicar "
                "problemas en inyectores, válvulas, turbo o distribución de aire "
                "entre cilindros."
            ),
            "oil_degradation_risk": (
                "Se evalúa la condición del aceite a través de su Viscosidad y "
                "contenido de Hollín. Cambios fuera de los rangos esperados indican "
                "degradación acelerada, comprometiendo la capacidad de lubricación "
                "y protección del motor."
            ),
            "lubrication_failure_risk": (
                "Se correlacionan los metales de cojinetes (Plomo, Cobre) con la "
                "Presión de Aceite del motor. Metales elevados combinados con "
                "presión baja son indicadores de falla en el sistema de lubricación."
            ),
            "bearing_wear_risk": (
                "Se monitorea Plomo y Cobre (materiales de cojinetes) junto con "
                "la Presión de Aceite. Un incremento sostenido de estos metales "
                "indica desgaste progresivo de los cojinetes del motor."
            ),
            "blowby_risk": (
                "Se correlaciona la Presión del Cárter (CnkcasePres) con el "
                "contenido de Hollín en el aceite. Presión de cárter elevada "
                "acompañada de hollín alto indica fuga de gases de combustión "
                "al cárter (blow-by)."
            ),
        },
        "transmision": {
            "clutch_pack_risk": (
                "Se evalúa el desgaste de los discos de embrague mediante Hierro, "
                "Cobre y Aluminio en el aceite, correlacionado con deslizamientos "
                "de lock-up y transmisión. Metales elevados con deslizamiento "
                "anormal indican desgaste del clutch pack."
            ),
            "thermal_degradation_risk": (
                "Se monitorea la degradación del aceite por temperatura excesiva, "
                "evaluando Viscosidad y Agua junto con temperaturas de salida del "
                "convertidor y aceite de transmisión."
            ),
            "planetary_gear_risk": (
                "Se analiza Hierro, Silicio y Cobre provenientes del desgaste de "
                "engranajes, correlacionado con desajustes de marcha y "
                "deslizamiento de transmisión."
            ),
            "bearing_risk": (
                "Se monitorean Hierro, Cobre, Plomo y Estaño (materiales de "
                "rodamientos) junto con la temperatura del aceite de transmisión. "
                "Incrementos sostenidos sugieren desgaste progresivo de rodamientos."
            ),
            "contamination_risk": (
                "Se evalúa el ingreso de contaminantes externos al sistema mediante "
                "Silicio, Agua, Sodio y Potasio. Estos elementos no son generados "
                "por desgaste interno y su presencia indica contaminación del "
                "circuito hidráulico."
            ),
            "torque_converter_risk": (
                "Se analiza el desgaste del convertidor de torque mediante "
                "Aluminio, Cobre y Hierro, correlacionado con deslizamiento de "
                "lock-up y temperatura de salida del convertidor."
            ),
            "shift_quality_risk": (
                "Se evalúa la calidad de los cambios de marcha mediante Viscosidad "
                "y Hierro en aceite, correlacionado con deslizamientos, desajustes "
                "de marcha y lock-up."
            ),
        },
    },

    "capstone": {
        # Metodología provisional para los modos de Capstone (motor QSK60).
        # El texto describe la intención según las señales asignadas; conviene
        # que lo revise un experto de dominio.
        "motor": {
            "abrasive_wear_risk": (
                "Se evalúa la concentración de partículas metálicas (Hierro, "
                "Aluminio) y contaminantes abrasivos (Silicio) en el aceite. "
                "Incrementos sostenidos sugieren desgaste interno o ingreso de "
                "contaminantes externos."
            ),
            "combustion_risk": (
                "Se analiza el Hollín y la dilución por Combustible en aceite, "
                "junto con la temperatura promedio de gases de escape y la presión "
                "de entrega de combustible. Hollín elevado con escape caliente "
                "indica combustión deficiente; dilución con presión de combustible "
                "baja sugiere inyector con fuga. Nota: la fuente actual no expone "
                "presión de dosificación de inyectores, riel comandado ni el "
                "indicador de agua en combustible, por lo que la detección de "
                "fallas de inyección se apoya mayoritariamente en análisis de aceite."
            ),
            "thermal_imbalance_risk": (
                "Se monitorea el diferencial entre las temperaturas de escape de "
                "los bancos izquierdo y derecho. Un delta sostenido puede indicar "
                "problemas de inyección, turbo o distribución entre cilindros."
            ),
            "oil_degradation_risk": (
                "Se evalúa la condición del aceite mediante Hollín y Oxidación, "
                "correlacionado con la temperatura del aceite. Cambios fuera de "
                "rango indican degradación acelerada del lubricante."
            ),
            "lubrication_failure_risk": (
                "Se correlacionan los metales de cojinetes (Plomo, Cobre) con las "
                "presiones del sistema de lubricación (rifle y diferencial de "
                "aceite). Metales altos con presión baja indican falla de "
                "lubricación."
            ),
            "bearing_wear_risk": (
                "Se monitorea Plomo, Cobre y Estaño (materiales de cojinetes) "
                "junto con la presión de aceite del rifle. Incrementos sostenidos "
                "indican desgaste progresivo de cojinetes."
            ),
            "blowby_risk": (
                "Se correlaciona la presión del cárter con el contenido de Hollín "
                "y Cromo en el aceite, junto con el nivel del tanque de reserva. "
                "Presión de cárter elevada con hollín alto indica fuga de gases de "
                "combustión (blow-by); Cromo creciente confirma desgaste de anillos."
            ),
            "turbocharger_risk": (
                "Se monitorea la velocidad del turbo y las presiones de admisión "
                "por banco. Desviaciones sostenidas pueden indicar deterioro o "
                "falla del turbocompresor."
            ),
            "coolant_contamination_risk": (
                "Se evalúa Sodio y Potasio en aceite junto con la temperatura y "
                "presión del refrigerante. Su presencia indica ingreso de "
                "refrigerante al circuito de aceite."
            ),
        },
    },
}


# =============================================================================
# HELPERS  —  todos aceptan `client` (default "cda" para retro-compat).
# El fallback ante un cliente desconocido loguea y cae a "cda", nunca a un
# componente de otro cliente por accidente.
# =============================================================================

def _resolve_client_config(config: dict, client: str) -> dict:
    """
    Devuelve la sub-config del cliente pedido dentro de `config` (uno de los
    diccionarios anidados por cliente). Si el cliente no existe, loguea un
    warning y cae a "cda".
    """
    client_key = (client or "cda").lower()
    client_config = config.get(client_key)
    if client_config is None:
        logger.warning(
            "Unknown client '%s' in predictive_config, falling back to 'cda'",
            client,
        )
        client_config = config.get("cda", {})
    return client_config


def get_failure_modes_for_component(component: str, client: str = "cda") -> dict:
    """Config completa de modos de falla de un componente para un cliente."""
    client_config = _resolve_client_config(FAILURE_MODE_CONFIG, client)
    component_key = (component or "").lower()
    return client_config.get(component_key, {})


def get_failure_mode_label(mode_key: str, component: str = "motor",
                           client: str = "cda") -> str:
    """Label legible de un modo de falla."""
    component_modes = get_failure_modes_for_component(component, client)
    return component_modes.get(mode_key, {}).get("label", mode_key)


def get_oil_variables_for_mode(mode_key: str, component: str = "motor",
                               client: str = "cda") -> list:
    """Variables de aceite asociadas a un modo de falla."""
    component_modes = get_failure_modes_for_component(component, client)
    return component_modes.get(mode_key, {}).get("oil_variables", [])


def get_telemetry_variables_for_mode(mode_key: str, component: str = "motor",
                                     client: str = "cda") -> list:
    """Variables de telemetría asociadas a un modo de falla."""
    component_modes = get_failure_modes_for_component(component, client)
    return component_modes.get(mode_key, {}).get("telemetry_variables", [])


def get_telemetry_signals_for_mode(mode_key: str, component: str = "motor",
                                   client: str = "cda") -> list:
    """Alias de get_telemetry_variables_for_mode (compatibilidad)."""
    return get_telemetry_variables_for_mode(mode_key, component, client)


def get_failure_mode_methodology(mode_key: str, component: str = "motor",
                                 client: str = "cda") -> str:
    """Descripción de la metodología de análisis de un modo de falla."""
    client_methodology = _resolve_client_config(FAILURE_MODE_METHODOLOGY, client)
    component_key = (component or "").lower()
    return client_methodology.get(component_key, {}).get(mode_key, "")


def get_all_oil_variables(client: str = "cda") -> list:
    """Todas las variables de aceite disponibles para un cliente."""
    client_labels = _resolve_client_config(OIL_LABELS, client)
    return list(client_labels.keys())


def get_failure_mode_options(component: str = "motor",
                             client: str = "cda") -> list:
    """Opciones {label, value} para dropdown de modos de falla."""
    component_modes = get_failure_modes_for_component(component, client)
    return [
        {"label": config["label"], "value": key}
        for key, config in component_modes.items()
    ]


def get_available_components(client: str = "cda") -> list:
    """Lista de componentes con configuración para un cliente."""
    client_config = _resolve_client_config(FAILURE_MODE_CONFIG, client)
    return list(client_config.keys())


def get_failure_modes_dict(component: str = "motor",
                           client: str = "cda") -> dict:
    """Mapa {mode_key: label} para un componente/cliente."""
    return {
        k: v["label"]
        for k, v in get_failure_modes_for_component(component, client).items()
    }