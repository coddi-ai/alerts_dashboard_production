# Menace Control - Nueva Pestaña

## Resumen

Se ha creado una nueva pestaña llamada "**Control de Amenazas**" (Menace Control) que proporciona una vista crítica del estado de los equipos basada en alertas y análisis de tribología.

## Ubicación en el Dashboard

La nueva pestaña se encuentra en:
- **Sección**: Monitoreo
- **Nombre**: Control de Amenazas
- **Posición**: Segunda pestaña después de "Alertas" en la sección de Monitoreo

## Funcionalidades Implementadas

### 1. Selector de Rango Temporal
- Permite seleccionar el período de análisis:
  - Últimos 30 días
  - Últimos 60 días
  - **Últimos 90 días (predeterminado)**
  - Últimos 180 días
  - Último año

### 2. Tarjetas de Resumen (KPIs)
Muestra 4 métricas clave:
1. **Total de Alertas**: Número total de eventos en el período seleccionado
2. **Equipos Monitoreados**: Cantidad de equipos con alertas
3. **Sistemas Afectados**: Número de sistemas diferentes con alertas
4. **Equipos Críticos**: Top 10% de equipos con más alertas

### 3. Tabla de Estado General de Equipos

**Propósito**: Vista consolidada del estado de cada equipo basada en alertas por sistema.

**Estructura de la tabla**:
```
| Equipo | Sistema1 | Sistema2 | ... | SistemaN | Eventos_Totales |
|--------|----------|----------|-----|----------|-----------------|
| CAT001 |    45    |    23    | ... |    12    |       180       |
| CAT002 |    32    |    15    | ... |     8    |       125       |
```

**Características**:
- Los equipos están ordenados por número total de eventos (descendente)
- Codificación por colores en la columna "Eventos_Totales":
  - **Rojo** (≥50 eventos): Estado crítico
  - **Naranja** (≥20 eventos): Estado de advertencia
  - **Amarillo** (≥10 eventos): Estado de precaución
  - **Sin color** (<10 eventos): Estado normal
- Las celdas vacías (0 eventos) se muestran en blanco para mejor legibilidad
- Muestra todos los equipos que tuvieron al menos una alerta en el período

### 4. Tabla de Sistemas Más Críticos

**Propósito**: Ranking de las combinaciones equipo-sistema con mayor criticidad.

**Estructura de la tabla**:
```
| Rank | Equipo | Sistema | Componente_Principal | Criticidad | Estado_Tribologia | Ultima_Muestra |
|------|--------|---------|---------------------|------------|-------------------|----------------|
|  🏆  | CAT001 | Motor   | Cárter              |     85     | Anormal           | 2026-04-15     |
|  🥈  | CAT005 | Hidráu. | Bomba Principal     |     67     | Precaución        | 2026-04-20     |
```

**Características**:
- Ordenado por criticidad (número de alertas) descendente
- Muestra los **top 50 sistemas más críticos**
- **Columna Rank**:
  - 🏆 Medalla dorada para #1
  - 🥈 Medalla plateada para #2
  - 🥉 Medalla bronce para #3
- **Columna Criticidad**:
  - Codificación por colores similar a la tabla anterior
  - Muestra el número exacto de alertas
- **Columna Estado_Tribologia**:
  - Integra información del último análisis de aceite
  - Badges con colores:
    - Verde: Normal
    - Rojo: Anormal/Crítico
    - Amarillo: Precaución/Advertencia
    - Gris: Sin datos
- **Columna Ultima_Muestra**: Fecha del último análisis de tribología
- **Componente_Principal**: El componente más mencionado en las alertas de ese sistema

## Cálculo de Criticidad

La criticidad se calcula como:
```
Criticidad = Número de alertas del par (Equipo, Sistema) en el período seleccionado
```

Este valor refleja:
- Equipos con múltiples fallas en el mismo sistema
- Sistemas que requieren atención inmediata
- Tendencias de deterioro progresivo

## Integración con Datos de Tribología

La tabla de sistemas críticos integra automáticamente:
- Estado del último reporte de análisis de aceite (`report_status`)
- Fecha de la última muestra analizada
- Esta información ayuda a correlacionar alertas con resultados de laboratorio

## Archivos Creados/Modificados

### Nuevos Archivos
1. `dashboard/tabs/tab_menace_control.py` - Layout de la pestaña
2. `dashboard/callbacks/menace_control_callbacks.py` - Lógica de callbacks

### Archivos Modificados
1. `dashboard/layout.py` - Agregada la nueva pestaña al menú de navegación
2. `dashboard/app.py` - Importados los callbacks de la nueva pestaña

## Datos Utilizados

### Fuentes de Datos
1. **Alertas**: `load_alerts_data(client)` 
   - Archivo: `data/alerts/golden/{client}/consolidated_alerts.csv`
   - Columnas clave: `Timestamp`, `UnitId`, `sistema`, `componente`

2. **Tribología**: `load_oil_classified(client)`
   - Archivo: `data/oil/golden/{client}/classified.parquet`
   - Columnas clave: `unitId`, `report_status`, `sampleDate`

### Columnas Utilizadas
- `Timestamp`: Para filtrar por rango de fechas
- `UnitId` / `Unidad`: Identificador del equipo
- `sistema` / `Sistema`: Sistema del equipo (Motor, Hidráulico, etc.)
- `componente` / `Componente`: Componente específico
- `report_status`: Estado del análisis de aceite
- `sampleDate`: Fecha de la muestra de aceite

## Casos de Uso

1. **Identificar equipos en riesgo**: La tabla de estado general permite ver de un vistazo qué equipos tienen más problemas

2. **Priorizar mantenimiento**: La tabla de sistemas críticos indica exactamente qué sistemas de qué equipos requieren atención inmediata

3. **Correlación multi-técnica**: La integración con tribología permite validar si las alertas están respaldadas por análisis de laboratorio

4. **Análisis de tendencias**: Cambiar el rango temporal permite ver cómo evoluciona la criticidad en el tiempo

## Consideraciones Técnicas

- Los callbacks se actualizan automáticamente cuando:
  - Se cambia el rango de días
  - Se cambia el cliente seleccionado
- Manejo robusto de datos faltantes (equipos sin datos de tribología)
- Rendimiento optimizado para grandes volúmenes de alertas
- Interfaz responsive adaptable a diferentes tamaños de pantalla

## Próximos Pasos Sugeridos

1. Agregar capacidad de exportar las tablas a Excel/CSV
2. Implementar filtros adicionales (por tipo de sistema, nivel de criticidad)
3. Agregar gráficos de evolución temporal de criticidad
4. Crear alertas automáticas cuando un equipo supera umbrales de criticidad
5. Integrar con sistema de órdenes de trabajo para mantenimiento
