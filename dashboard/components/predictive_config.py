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
        # Motor Cummins QSK60. Modos, variables y labels validados en el
        # proyecto de origen (motor_capstone). Los nombres de telemetría
        # corresponden a las columnas reales del dataset QSK60.
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
                "telemetry_variables": [
                    "EGT-AV (F)",
                    "Fuel Delivery Pressure (PSI)",
                    "Injector Metering (PSI)",
                    "Commanded Engine Fuel Rail Pressure (kPa)",
                ],
                "description": "Combustión ineficiente o incompleta por falla en inyectores o sistema Common Rail"
            },
            "thermal_imbalance_risk": {
                "label": "Desbalance Térmico entre Bancos",
                "oil_variables": [],
                "telemetry_variables": [
                    "DeltaExh",
                    "EGT-LB (MCRS) (F)",
                    "EGT-RB (MCRS) (F)",
                    "IMP-LB (PSI)",
                    "IMP-RB (MCRS) (PSI)",
                    "IMT-LBF (F)",
                    "IMT-RBF (F)",
                ],
                "description": "Diferencia térmica persistente entre los bancos del motor V16"
            },
            "turbocharger_risk": {
                "label": "Falla de Turbocompresor",
                "oil_variables": ["Aluminio", "Hierro", "Cromo"],
                "telemetry_variables": [
                    "Turbocharger Speed (RPM)",
                    "IMP-LB (PSI)",
                    "IMP-RB (MCRS) (PSI)",
                    "IMT-LBF (F)",
                    "IMT-RBF (F)",
                    "EGT-LB (MCRS) (F)",
                    "EGT-RB (MCRS) (F)",
                ],
                "description": "Falla en el sistema de turbocompresión en dos etapas, con pérdida de boost y eficiencia"
            },
            "oil_degradation_risk": {
                "label": "Degradación de Aceite",
                "oil_variables": ["Hollín", "Viscocidad", "Oxidación", "Combustible"],
                "telemetry_variables": ["Engine Oil Temperature (F)"],
                "description": "Pérdida progresiva de propiedades lubricantes por contaminación y estrés térmico"
            },
            "coolant_contamination_risk": {
                "label": "Contaminación por Refrigerante",
                "oil_variables": ["Sodio", "Potasio"],
                "telemetry_variables": [
                    "Coolant temperature (F)",
                    "Coolant Pressure (PSI)",
                    "Engine coolant level (%)",
                ],
                "description": "Ingreso de refrigerante al aceite por falla de empaquetaduras, O-rings de liner o fisuras"
            },
            "lubrication_failure_risk": {
                "label": "Falla de Lubricación",
                "oil_variables": ["Hierro", "Plomo", "Cobre"],
                "telemetry_variables": [
                    "Rifle Oil Pressure (PSI)",
                    "Oil Differential Pressure (PSI)",
                    "Engine Oil Temperature (F)",
                ],
                "description": "Lubricación insuficiente que genera contacto metal-metal y desgaste acelerado"
            },
            "bearing_wear_risk": {
                "label": "Desgaste de Cojinetes",
                "oil_variables": ["Plomo", "Cobre", "Hierro", "Estaño"],
                "telemetry_variables": ["Rifle Oil Pressure (PSI)"],
                "description": "Desgaste progresivo de cojinetes de biela y bancada"
            },
            "blowby_risk": {
                "label": "Blow-by / Desgaste de Anillos",
                "oil_variables": ["Cromo", "Hierro", "Hollín"],
                "telemetry_variables": [
                    "Crankcase Pressure (MCRS) (in-H2O)",
                    "Oil Level - Reserve Tank ()",
                ],
                "description": "Desgaste de anillos y liner con fuga de gases de combustión al cárter"
            },
        },
    },
}


# =============================================================================
# TELEMETRY_LABELS  —  client -> {signal: label}
# =============================================================================

TELEMETRY_LABELS = {
    "cda": {
        "CnkcasePres": "Presión Cárter",
        "DeltaExh": "Delta Escape",
        "EngOilPres": "Presión Aceite Motor",
        "LtExhTemp": "Temp. Escape Izq.",
        "RtExhTemp": "Temp. Escape Der.",
        "LckupSlip": "Deslizamiento Lock-up",
        "TCOutTemp": "Temp. Salida Convertidor",
        "TrnLubeTemp": "Temp. Aceite Transmisión",
        "TrnSlip": "Deslizamiento Transmisión",
        "gear_mismatch": "Desajuste de Marcha",
    },

    # Nombres QSK60 reales — coinciden con las columnas del dataset de
    # telemetría de Capstone y con las señales referenciadas en los modos.
    "capstone": {
        "Commanded Engine Fuel Rail Pressure (kPa)": "Presión Riel Comandada",
        "Coolant Pressure (PSI)":                    "Presión Refrigerante",
        "Coolant temperature (F)":                   "Temp. Refrigerante",
        "Crankcase Pressure (MCRS) (in-H2O)":        "Presión Cárter",
        "DeltaExh":                                  "Delta Escape entre Bancos",
        "EGT-AV (F)":                                "Temp. Escape Promedio",
        "EGT-LB (MCRS) (F)":                         "Temp. Escape Banco Izq.",
        "EGT-RB (MCRS) (F)":                         "Temp. Escape Banco Der.",
        "Engine Oil Temperature (F)":                "Temp. Aceite Motor",
        "Engine coolant level (%)":                  "Nivel Refrigerante",
        "Fuel Delivery Pressure (PSI)":              "Presión Entrega Combustible",
        "IMP-LB (PSI)":                              "Presión Admisión Banco Izq.",
        "IMP-RB (MCRS) (PSI)":                       "Presión Admisión Banco Der.",
        "IMT-LBF (F)":                               "Temp. Admisión Banco Izq.",
        "IMT-RBF (F)":                               "Temp. Admisión Banco Der.",
        "Injector Metering (PSI)":                   "Presión Dosificación Inyectores",
        "Oil Differential Pressure (PSI)":           "Presión Diferencial Filtro Aceite",
        "Oil Level - Reserve Tank ()":               "Nivel Tanque Reserva",
        "Rifle Oil Pressure (PSI)":                  "Presión Aceite Galería",
        "Turbocharger Speed (RPM)":                  "Velocidad Turbocompresor",
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
        "Aluminio":    {"LT_1000": (2.50, 3.0, 4.50),   "GE_1000": (2.50, 3.0, 4.50)},
        "Cobre":       {"LT_1000": (2.50, 3.5, 5.25),   "GE_1000": (2.50, 3.5, 5.25)},
        "Combustible": {"LT_1000": (0.05, 0.1, 0.15),   "GE_1000": (0.05, 0.1, 0.15)},
        "Cromo":       {"LT_1000": (2.00, 3.0, 4.50),   "GE_1000": (2.00, 3.0, 4.50)},
        "Estaño":      {"LT_1000": (3.00, 5.0, 7.50),   "GE_1000": (3.00, 5.0, 7.50)},
        "Hierro":      {"LT_1000": (19.00, 24.0, 36.00), "GE_1000": (19.00, 24.0, 36.00)},
        "Hollín":      {"LT_1000": (1.50, 3.0, 4.50),   "GE_1000": (1.50, 3.0, 4.50)},
        "Oxidación":   {"LT_1000": (19.00, 24.5, 36.75), "GE_1000": (19.00, 24.5, 36.75)},
        "Plomo":       {"LT_1000": (2.00, 3.0, 4.50),   "GE_1000": (2.00, 3.0, 4.50)},
        "Potasio":     {"LT_1000": (2.50, 3.5, 5.25),   "GE_1000": (2.50, 3.5, 5.25)},
        "Silicio":     {"LT_1000": (11.00, 13.0, 19.50), "GE_1000": (11.00, 13.0, 19.50)},
        "Sodio":       {"LT_1000": (10.00, 13.0, 19.50), "GE_1000": (10.00, 13.0, 19.50)},
        "Viscocidad":  {"LT_1000": (16.10, 16.3, 24.45), "GE_1000": (16.10, 16.3, 24.45)},
    },
}


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
                "Se analiza el Hollín en aceite junto con las temperaturas de "
                "gases de escape (promedio y por banco). Hollín elevado con "
                "temperaturas de escape anómalas indica combustión deficiente."
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
                "en el aceite. Presión de cárter elevada con hollín alto indica "
                "fuga de gases de combustión (blow-by)."
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