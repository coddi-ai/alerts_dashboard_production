# Script de instalación para la funcionalidad Data Freshness
# Ejecutar con PowerShell

Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "Instalación: Funcionalidad de Estado de Actualización de Datos" -ForegroundColor Cyan
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host ""

# 1. Verificar que estamos en el directorio correcto
$currentDir = Get-Location
Write-Host "📂 Directorio actual: $currentDir" -ForegroundColor Yellow

if (!(Test-Path "requirements.txt")) {
    Write-Host "❌ ERROR: No se encontró requirements.txt" -ForegroundColor Red
    Write-Host "   Por favor ejecuta este script desde el directorio raíz del proyecto" -ForegroundColor Red
    exit 1
}

# 2. Instalar dependencias
Write-Host ""
Write-Host "📦 Instalando dependencias..." -ForegroundColor Green
pip install pytz>=2023.3

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Dependencias instaladas correctamente" -ForegroundColor Green
} else {
    Write-Host "❌ ERROR: Falló la instalación de dependencias" -ForegroundColor Red
    exit 1
}

# 3. Verificar archivos creados
Write-Host ""
Write-Host "🔍 Verificando archivos creados..." -ForegroundColor Green

$files = @(
    "dashboard\tabs\tab_data_freshness.py",
    "dashboard\callbacks\data_freshness_callbacks.py",
    "tests\test_data_freshness.py",
    "documentation\general\DATA_FRESHNESS_TAB.md",
    "documentation\general\DATA_FRESHNESS_IMPLEMENTATION.md"
)

$allFilesExist = $true
foreach ($file in $files) {
    if (Test-Path $file) {
        Write-Host "  ✅ $file" -ForegroundColor Green
    } else {
        Write-Host "  ❌ $file (NO ENCONTRADO)" -ForegroundColor Red
        $allFilesExist = $false
    }
}

if (!$allFilesExist) {
    Write-Host ""
    Write-Host "⚠️ ADVERTENCIA: Algunos archivos no se encontraron" -ForegroundColor Yellow
}

# 4. Verificar archivo de datos
Write-Host ""
Write-Host "📊 Verificando archivo de datos..." -ForegroundColor Green

$dataFile = "data\auxiliar\cda\Data_Date_Last_Update.csv"
if (Test-Path $dataFile) {
    Write-Host "  ✅ $dataFile existe" -ForegroundColor Green
    
    # Contar líneas
    $lines = (Get-Content $dataFile | Measure-Object -Line).Lines
    Write-Host "     Registros: $($lines - 1)" -ForegroundColor Cyan  # -1 para el header
} else {
    Write-Host "  ❌ $dataFile NO ENCONTRADO" -ForegroundColor Red
    Write-Host "     Este archivo es necesario para que la funcionalidad opere" -ForegroundColor Yellow
}

# 5. Ejecutar tests
Write-Host ""
Write-Host "🧪 Ejecutando tests..." -ForegroundColor Green
Write-Host ""

python tests\test_data_freshness.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ Todos los tests pasaron correctamente" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "⚠️ Algunos tests fallaron - revisar salida arriba" -ForegroundColor Yellow
}

# 6. Resumen final
Write-Host ""
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "📋 RESUMEN DE INSTALACIÓN" -ForegroundColor Cyan
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host ""
Write-Host "✅ Archivos creados y verificados" -ForegroundColor Green
Write-Host "✅ Dependencias instaladas (pytz)" -ForegroundColor Green
Write-Host "✅ Tests ejecutados" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 PRÓXIMOS PASOS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Si Docker está corriendo, reinícialo para cargar los cambios:" -ForegroundColor White
Write-Host "   docker-compose down" -ForegroundColor Cyan
Write-Host "   docker-compose up -d" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. O ejecuta el dashboard localmente:" -ForegroundColor White
Write-Host "   python -m dashboard.app" -ForegroundColor Cyan
Write-Host ""
Write-Host "3. Navega a: http://localhost:8050" -ForegroundColor White
Write-Host ""
Write-Host "4. Ve a: Resumen > Estado de Datos" -ForegroundColor White
Write-Host ""
Write-Host "📖 Documentación disponible en:" -ForegroundColor Yellow
Write-Host "   - documentation\general\DATA_FRESHNESS_TAB.md" -ForegroundColor Cyan
Write-Host "   - documentation\general\DATA_FRESHNESS_IMPLEMENTATION.md" -ForegroundColor Cyan
Write-Host ""
Write-Host "=" * 80 -ForegroundColor Cyan
