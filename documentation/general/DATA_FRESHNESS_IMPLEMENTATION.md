# Implementación: Pestaña de Estado de Actualización de Datos

## 📅 Fecha
12 de Mayo, 2026

## 🎯 Objetivo
Crear una nueva pestaña en el dashboard que monitoree el estado de actualización de datos de Telemetría y Tribología, mostrando información con codificación por colores basada en la frescura de los datos.

## ✅ Archivos Creados

### 1. Layout de la Pestaña
**Archivo**: `dashboard/tabs/tab_data_freshness.py`
- Definición del layout con:
  - Encabezado descriptivo
  - Leyenda de estados (Verde/Amarillo/Rojo)
  - Tarjetas de resumen (contadores por estado)
  - Tabla de datos con loading spinner

### 2. Callbacks y Lógica de Negocio
**Archivo**: `dashboard/callbacks/data_freshness_callbacks.py`
- Funciones implementadas:
  - `load_data_freshness()`: Carga del CSV
  - `convert_utc_to_chile()`: Conversión de zona horaria UTC+0 → Chile
  - `calculate_freshness_status()`: Cálculo de estado según tiempo transcurrido
  - `process_freshness_data()`: Procesamiento completo del pipeline
  - `update_data_freshness()`: Callback principal para actualizar la UI

### 3. Tests
**Archivo**: `tests/test_data_freshness.py`
- Suite de pruebas que verifica:
  - Carga correcta del CSV
  - Conversión de zona horaria
  - Cálculo de estados
  - Pipeline completo de procesamiento

### 4. Documentación
**Archivo**: `documentation/general/DATA_FRESHNESS_TAB.md`
- Documentación completa de la funcionalidad
- Descripción de criterios de color
- Guía de uso
- Notas técnicas

## 🔧 Archivos Modificados

### 1. Layout Principal
**Archivo**: `dashboard/layout.py`
- **Línea agregada**: Import de `create_data_freshness_tab`
- **Modificación**: Agregada nueva subsección en navigation_items:
  ```python
  {'id': 'overview-data-freshness', 'label': 'Estado de Datos', 'tab': create_data_freshness_tab}
  ```

### 2. Aplicación Principal
**Archivo**: `dashboard/app.py`
- **Línea agregada**: Import de `dashboard.callbacks.data_freshness_callbacks`

### 3. Dependencias
**Archivo**: `requirements.txt`
- **Línea agregada**: `pytz>=2023.3` (para conversión de zonas horarias)

## 📊 Criterios de Estado Implementados

### Telemetría
- 🟢 **Verde (Actualizado)**: < 1 hora
- 🟡 **Amarillo (Atención Requerida)**: 1-4 horas
- 🔴 **Rojo (Crítico)**: > 4 horas

### Tribología
- 🟢 **Verde (Actualizado)**: < 1 semana
- 🟡 **Amarillo (Atención Requerida)**: 1-2 semanas
- 🔴 **Rojo (Crítico)**: > 2 semanas

## 🌍 Gestión de Zona Horaria

- **Datos de origen**: UTC+0 (archivo `Data_Date_Last_Update.csv`)
- **Visualización**: Hora de Chile (America/Santiago)
- **Biblioteca**: `pytz` para conversión automática con manejo de DST

## 🎨 Características de la UI

1. **Tabla Interactiva**:
   - Ordenamiento nativo
   - Filtrado por columnas
   - Exportación a Excel
   - Paginación (20 registros por página)
   - Colores condicionales en celdas

2. **Tarjetas de Resumen**:
   - Contador de unidades actualizadas
   - Contador de unidades con atención requerida
   - Contador de unidades críticas
   - Hora de última actualización del dashboard

3. **Leyenda Visual**:
   - Explicación clara de criterios
   - Iconos emoji para fácil identificación

## 🚀 Cómo Usar

### Para Desarrolladores

1. **Instalar dependencias**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Ejecutar tests**:
   ```bash
   python tests/test_data_freshness.py
   ```

3. **Iniciar dashboard**:
   ```bash
   docker-compose up -d
   # o
   python -m dashboard.app
   ```

### Para Usuarios

1. Navegar a **Resumen > Estado de Datos**
2. Revisar tarjetas de resumen
3. Consultar tabla para detalles específicos
4. Exportar a Excel si es necesario

## 📝 Notas de Implementación

### Decisiones de Diseño

1. **Ordenamiento automático**: La tabla se ordena por criticidad (Crítico → Atención → Actualizado)
2. **Estado general**: El peor estado entre Telemetría y Tribología define el estado general de la unidad
3. **Formato de tiempo**: Muestra días/horas/minutos de forma legible
4. **Colores consistentes**: Se usan los colores de Bootstrap para mantener consistencia visual

### Mejoras Futuras Sugeridas

1. **Auto-refresh**: Actualización automática cada X minutos
2. **Notificaciones**: Alertas cuando unidades entran en estado crítico
3. **Historial**: Registro de estados para análisis de tendencias
4. **Gráficos**: Visualización de evolución temporal del estado

## ✅ Checklist de Implementación

- [x] Crear layout de la pestaña
- [x] Implementar callbacks y lógica de negocio
- [x] Agregar conversión de zona horaria UTC → Chile
- [x] Implementar sistema de colores según criterios
- [x] Integrar en el menú de navegación
- [x] Agregar dependencia `pytz`
- [x] Crear tests unitarios
- [x] Documentar funcionalidad
- [ ] Probar en Docker
- [ ] Validar con datos reales
- [ ] Obtener feedback de usuarios

## 🐛 Posibles Issues

1. **Archivo CSV no encontrado**: Verificar que `data/auxiliar/cda/Data_Date_Last_Update.csv` existe
2. **Zona horaria incorrecta**: Verificar que `pytz` está instalado correctamente
3. **Datos vacíos**: Verificar formato del CSV (columnas requeridas)

## 📞 Contacto

Para dudas o sugerencias sobre esta implementación, contactar al equipo de desarrollo.
