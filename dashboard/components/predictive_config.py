"""
Configuración centralizada de modos de falla por componente.
"""

FAILURE_MODE_CONFIG = {
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
            "label": "Diferencia de temperaturas de escape",
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
}

TELEMETRY_LABELS = {
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
}

OIL_LABELS = {
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
}

OIL_THRESHOLDS = {
    "Hierro":     {"LT_1000": (48.0, 57.0, 65.0), "GE_1000": (71.0, 84.0, 93.0)},
    "Cobre":      {"LT_1000": (5.0, 8.0, 17.0), "GE_1000": (7.0, 12.0, 51.0)},
    "Plomo":      {"LT_1000": (3.0, 5.0, 8.0), "GE_1000": (4.0, 5.0, 6.0)},
    "Silicio":    {"LT_1000": (5.0, 6.0, 8.0), "GE_1000": (5.0, 6.0, 7.0)},
    "Sodio":      {"LT_1000": (7.0, 9.0, 18.0), "GE_1000": (8.0, 9.0, 10.0)},
    "Viscocidad": {"LT_1000": (16.0, 17.0, 18.0), "GE_1000": (16.0, 17.0, 18.0)},
    "Hollín":     {"LT_1000": (64.0, 73.0, 84.0), "GE_1000": (91.0, 106.0, 120.0)},
    "Cromo":      {"LT_1000": (0.0, 0.5, 1.0), "GE_1000": (0.0, 0.5, 1.0)},
}


def get_failure_modes_for_component(component: str) -> dict:
    component_key = component.lower() if component else "motor"
    return FAILURE_MODE_CONFIG.get(component_key, FAILURE_MODE_CONFIG.get("motor", {}))


def get_failure_mode_label(mode_key: str, component: str = "motor") -> str:
    component_modes = get_failure_modes_for_component(component)
    return component_modes.get(mode_key, {}).get("label", mode_key)


def get_oil_variables_for_mode(mode_key: str, component: str = "motor") -> list:
    component_modes = get_failure_modes_for_component(component)
    return component_modes.get(mode_key, {}).get("oil_variables", [])


def get_telemetry_variables_for_mode(mode_key: str, component: str = "motor") -> list:
    component_modes = get_failure_modes_for_component(component)
    return component_modes.get(mode_key, {}).get("telemetry_variables", [])


def get_telemetry_signals_for_mode(mode_key: str, component: str = "motor") -> list:
    return get_telemetry_variables_for_mode(mode_key, component)


def get_all_oil_variables() -> list:
    return list(OIL_LABELS.keys())


def get_failure_mode_options(component: str = "motor") -> list:
    component_modes = get_failure_modes_for_component(component)
    return [
        {"label": config["label"], "value": key}
        for key, config in component_modes.items()
    ]


def get_available_components() -> list:
    return list(FAILURE_MODE_CONFIG.keys())


def get_failure_modes_dict(component: str = "motor") -> dict:
    return {k: v["label"] for k, v in get_failure_modes_for_component(component).items()}
