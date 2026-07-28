# TDS Alerts Dashboard

<div align="center">

**Sistema integral de monitoreo de condición de flotas mineras**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Dash](https://img.shields.io/badge/Dash-2.0+-green.svg)](https://dash.plotly.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

[Módulos](#-módulos) • [Instalación](#-instalación) • [Docker](#-docker) • [Datos](#-datos) • [Configuración](#-configuración)

</div>

---

## 🎯 Propósito

Dashboard multi-técnica que consolida **análisis de aceite**, **alertas operacionales**, **modelos predictivos** y **estado general de equipos** en una interfaz unificada. Soporta múltiples clientes con datos aislados.

---

## ✨ Módulos

### Activos

| Módulo | Descripción | Datos Clave |
|--------|-------------|-------------|
| 🛡️ **Menace Control** | Condición general de máquinas | Estado de flota, criticidad, tendencias |
| 🕐 **Update Data** | Frescura de datos | Hora de última actualización por fuente |
| 🚨 **Alerts** | Alertas enriquecidas | Telemetría + aceite + GPS + diagnóstico |
| 🧪 **Oil** | Análisis tribológico | Muestras, límites Stewart, clasificación AI |
| 🔮 **Predictive** | Modelos predictivos por componente | Ranking 0-100 por modo de falla (motor, transmisión) |

### Integraciones Futuras

| Módulo | Descripción |
|--------|-------------|
| 📡 **Telemetry** | Monitoreo de sensores y señales operacionales |
| 🔧 **Mantentions** | Estudio de registros de mantenimiento |
| 📊 **Reportability** | Reportes generados con AI sobre los datos |

---

## 🚀 Instalación

### Requisitos Previos

- Python 3.9+
- Docker 20.10+ y Docker Compose 2.0+
- Git

### Instalación Local

```bash
# Clonar repositorio
git clone <repository-url>
cd alerts_dashboard_production

# Crear entorno virtual
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar
python -m dashboard.app
```

El dashboard estará disponible en: **http://localhost:8050**

---

## 🐳 Docker

### Docker Compose (Recomendado)

```bash
# Configurar entorno
cp .env.example .env
# Editar .env con SECRET_KEY y tokens necesarios

# Construir y ejecutar
docker-compose up -d

# Ver logs
docker-compose logs -f

# Detener
docker-compose down
```

### Docker Directo

```bash
docker build -t tds-dashboard .
docker run -d -p 8050:8050 --env-file .env -v ./data:/data:ro tds-dashboard
```

El dashboard estará disponible en: **http://localhost:8050**

**Credenciales por defecto:** `admin` / `admin123` (cambiar en producción)

---

## 📊 Datos

### Arquitectura

```
data/{técnica}/{capa}/{cliente}/{archivo}
```

| Técnica | Capa | Contenido |
|---------|------|-----------|
| `oil` | `golden` | Clasificaciones, límites Stewart, estado máquinas |
| `alerts` | `golden` | Alertas consolidadas con diagnóstico |
| `predictive` | `golden` | Rankings por componente (motor.csv, transmision.csv) |
| `telemetry` | `golden` | Alertas de sensores y reglas |
| `auxiliar` | `cda` | Datos auxiliares por cliente |

### Actualizar Datos

```bash
# Copiar nuevos archivos a data/{técnica}/golden/{cliente}/
# Reiniciar para cargar
docker-compose restart
```

---

## 🔧 Configuración

### Variables de Entorno

```bash
# .env
SECRET_KEY=your-secret-key-min-32-chars
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8050
DEBUG_MODE=False
CLIENTS=CDA,EMIN
MAPBOX_TOKEN=pk.xxx          # Opcional, para mapas GPS
OPENAI_API_KEY=sk-xxx        # Opcional, para features AI
```

### Credenciales

Editar `config/users.py`:
```python
USERS = {
    "admin": "your-secure-password",
}
```

---

## 🏗️ Estructura del Proyecto

```
├── dashboard/              # Aplicación Dash
│   ├── callbacks/          # Callbacks interactivos por sección
│   ├── components/         # Componentes UI reutilizables
│   ├── tabs/              # Módulos de contenido por sección
│   └── assets/            # CSS y recursos estáticos
├── config/                # Configuración (settings, users)
├── src/                   # Procesamiento de datos
│   ├── data/              # Loaders y transformers
│   └── utils/             # Utilidades
├── data/                  # Datos por técnica/capa/cliente
├── documentation/         # Contratos de datos
├── notebooks/             # Notebooks de exploración
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## 🔍 Troubleshooting

| Problema | Solución |
|----------|----------|
| Dashboard no inicia | `docker-compose logs` para ver errores |
| No muestra datos | Verificar archivos en `data/{técnica}/golden/{cliente}/` |
| Error de login | Verificar `config/users.py` y SECRET_KEY en `.env` |
| Puerto ocupado | Cambiar `DASHBOARD_PORT` en `.env` |

---

## 📋 Documentación

- [Oil Data Contracts](documentation/oil/DATA_CONTRACTS.md)
- [Telemetry Data Contracts](documentation/telemetry/data_contracts.md)
- [Alerts Data Contracts](documentation/alerts/data_contracts.md)
- [Mantentions Data Contracts](documentation/mantentions/data_contracts.md)

