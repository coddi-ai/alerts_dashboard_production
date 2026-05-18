# Multi-Technical Alerts Dashboard - Production Deployment

Interactive web dashboard for comprehensive fleet monitoring across multiple data sources. Built with Dash and Plotly, containerized with Docker for easy deployment.

## 📋 Overview

This dashboard provides:
- **Fleet Overview**: Unified view of equipment health across all monitoring techniques
- **Alert Monitoring**: Consolidated alerts from telemetry and tribology analysis
- **Sensor Monitoring**: Real-time telemetry data and trend analysis
- **Maintenance Tracking**: Historical maintenance activity monitoring
- **Oil Analysis**: Tribology analysis with AI-generated recommendations
- **Limit Management**: Configure and monitor technical limits (Stewart, sensor thresholds)
- **Multi-Client Support**: Isolated data and configurations per client

## 🏗️ Architecture

```
alerts_dashboard_production/
├── dashboard/          # Dash application logic
│   ├── callbacks/      # Interactive callbacks per section
│   ├── components/     # Reusable UI components
│   └── tabs/           # Section content modules
├── config/            # Application configuration
├── src/               # Data processing modules
│   ├── data/          # Data transformers, loaders, schemas
│   └── utils/         # Utility functions
├── data/              # Multi-technique data layers
│   ├── oil/           # Tribology analysis data
│   │   ├── silver/{client}/     # Harmonized oil data
│   │   └── golden/{client}/     # Classified reports & limits
│   ├── telemetry/     # Sensor monitoring data
│   │   ├── silver/{client}/     # GPS & sensor readings
│   │   └── golden/{client}/     # Telemetry alerts & rules
│   ├── mantentions/   # Maintenance records
│   │   └── golden/{client}/     # Weekly maintenance reports
│   └── alerts/        # Consolidated alerts
│       └── golden/{client}/     # Cross-technique alerts
├── documentation/     # Technical documentation
│   ├── general/       # Dashboard overview and migration plan
│   ├── oil/           # Oil data contracts
│   ├── telemetry/     # Telemetry data contracts
│   ├── mantentions/   # Mantentions data contracts
│   └── alerts/        # Alerts data contracts
├── notebooks/         # Jupyter analysis notebooks
├── Dockerfile         # Container definition
├── docker-compose.yml # Docker Compose orchestration
├── requirements.txt   # Python dependencies
└── .env              # Environment configuration
```

## 🔧 Prerequisites

- **Docker**: Version 20.10 or higher
- **Docker Compose**: Version 2.0 or higher
- Git (for cloning repository)

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/portizv26/Multi-Technical-Alerts.git
cd Multi-Technical-Alerts/alerts_dashboard_production
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit configuration
nano .env  # or use your preferred editor

# Required: Set SECRET_KEY for production
# Optional: Set MAPBOX_TOKEN for GPS maps (see below)
```

#### Mapbox Token Configuration (for GPS Maps)

GPS route visualizations in the Alerts Detail tab require a Mapbox access token. You have **three options**:

**Option 1: Environment Variable (Recommended for Docker/Production)**
```bash
# In your .env file:
MAPBOX_TOKEN=pk.your.mapbox.token.here
```

**Option 2: Token File (Recommended for Local Development)**
```bash
# Create a .mapbox_token file in the project root
cp .mapbox_token.example .mapbox_token


# Edit and paste your token
echo "pk.your.mapbox.token.here" > .mapbox_token
```

**Option 3: Skip GPS Maps**
```bash
# Leave MAPBOX_TOKEN empty in .env
# GPS map section will display "No GPS data available"
```

**Get a free Mapbox token**: https://account.mapbox.com/access-tokens/

### 3. Run with Docker Compose

```bash
# Build and start the dashboard
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the dashboard
docker-compose down
```

### 4. Access Dashboard

Open your browser and navigate to:
```
http://localhost:8050
```

**Default Credentials:**
- Username: `admin`
- Password: `admin123` (change in production via `config/users.py`)

## 📦 Deployment Guide

### Local Testing Before Production

#### Step 1: Build Docker Image

```bash
# Build the image locally
docker build -t oil-dashboard:latest .

# Verify image was created
docker images | grep oil-dashboard
```

#### Step 2: Test Image Locally

```bash
# Run container with volume mount
docker run -d \
  --name oil-dashboard-test \
  -p 8050:8050 \
  -v $(pwd)/data:/app/data:ro \
  -v $(pwd)/logs:/app/logs \
  -e SECRET_KEY=test-secret-key \
  oil-dashboard:latest

# Check container logs
docker logs -f oil-dashboard-test

# Test the dashboard
curl http://localhost:8050

# Stop and remove test container
docker stop oil-dashboard-test
docker rm oil-dashboard-test
```

#### Step 3: Run Integration Tests

```bash
# Test with Docker Compose (recommended)
docker-compose up

# Open browser to http://localhost:8050
# Verify:
# ✓ Login page loads
# ✓ Authentication works
# ✓ All tabs render correctly
# ✓ Charts display data
# ✓ Filters work properly
# ✓ No console errors

# Stop when testing is complete
docker-compose down
```

#### Step 4: Tag Image for Registry

```bash
# Tag for Docker Hub
docker tag oil-dashboard:latest yourusername/oil-dashboard:v1.0.0
docker tag oil-dashboard:latest yourusername/oil-dashboard:latest

# Or tag for GitHub Container Registry
docker tag oil-dashboard:latest ghcr.io/portizv26/oil-dashboard:v1.0.0
docker tag oil-dashboard:latest ghcr.io/portizv26/oil-dashboard:latest
```

#### Step 5: Push to Registry

**Option A: Docker Hub**
```bash
# Login to Docker Hub
docker login

# Push images
docker push yourusername/oil-dashboard:v1.0.0
docker push yourusername/oil-dashboard:latest
```

**Option B: GitHub Container Registry**
```bash
# Create GitHub Personal Access Token (PAT) with write:packages scope
# Login to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u portizv26 --password-stdin

# Push images
docker push ghcr.io/portizv26/oil-dashboard:v1.0.0
docker push ghcr.io/portizv26/oil-dashboard:latest
```

#### Step 6: Deploy to Production Server

```bash
# On production server, pull the image
docker pull ghcr.io/portizv26/oil-dashboard:latest

# Create production docker-compose.yml
# Set environment variables
# Start the service
docker-compose -f docker-compose.prod.yml up -d
```

## 🔐 Production Configuration

### Environment Variables

Create a `.env` file for production (use `.env.example` as template):

```bash
# Security
SECRET_KEY=your-production-secret-key-here-min-32-chars

# Server Configuration
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8050
DEBUG_MODE=False

# API Keys
OPENAI_API_KEY=sk-your-openai-key-here  # Optional, for AI features
MAPBOX_TOKEN=pk.your.mapbox.token.here  # Required for GPS maps

# Clients
CLIENTS=CDA,EMIN

# Optional: Logging
LOG_LEVEL=INFO
```

**Important Notes:**
- **SECRET_KEY**: Generate with `python -c "import secrets; print(secrets.token_hex(32))"`
- **MAPBOX_TOKEN**: Get free token at https://account.mapbox.com/access-tokens/
  - Can also be provided via `.mapbox_token` file
  - Required for GPS route visualizations in Alerts Detail tab
- **OPENAI_API_KEY**: Only needed if using AI recommendation features

### Update User Credentials

Edit `config/users.py` and update default passwords:

```python
USERS = {
    "admin": "your-secure-password-here",
    "viewer": "another-secure-password"
}
```

### Data Updates

To update dashboard data:

```bash
# Update CDA client data
cp new_classified.parquet data/oil/golden/cda/classified.parquet
cp new_machine_status.parquet data/oil/golden/cda/machine_status.parquet
cp new_stewart_limits.parquet data/oil/golden/cda/stewart_limits.parquet

# Update EMIN client data
cp new_classified.parquet data/oil/golden/emin/classified.parquet
cp new_machine_status.parquet data/oil/golden/emin/machine_status.parquet
cp new_stewart_limits.parquet data/oil/golden/emin/stewart_limits.parquet

# Restart dashboard to load new data
docker-compose restart
```

**Note**: Data files must include `componentNameNormalized` field (added Feb 2026) for proper component granularity support.

## 🐳 Docker Commands Reference

### Build & Run
```bash
# Build image
docker build -t oil-dashboard .

# Run container
docker run -d -p 8050:8050 --name dashboard oil-dashboard

# Run with docker-compose
docker-compose up -d
```

### Management
```bash
# View logs
docker logs -f oil-dashboard
docker-compose logs -f

# Stop containers
docker stop oil-dashboard
docker-compose down

# Restart containers
docker restart oil-dashboard
docker-compose restart

# Remove containers
docker rm oil-dashboard
docker-compose down -v
```

### Debugging
```bash
# Access container shell
docker exec -it oil-dashboard bash

# Inspect container
docker inspect oil-dashboard

# View resource usage
docker stats oil-dashboard
```

## 📊 Data Format

The dashboard uses a **multi-technique data architecture** with the following structure:

### Data Organization
```
data/{technique}/{layer}/{client}/{datafile}
```

Where:
- **technique**: `oil`, `telemetry`, `mantentions`, `alerts`
- **layer**: `silver` (harmonized) or `golden` (analysis-ready)
- **client**: Client identifier (e.g., `cda`, `emin`)

### Available Techniques

#### 1. Oil (Tribology Analysis) - ✅ Implemented
- **Silver**: Harmonized oil sample data
- **Golden**: Classified reports, machine status, Stewart limits
- **Status**: Fully operational with AI recommendations

#### 2. Telemetry (Sensor Monitoring) - 🔄 In Progress
- **Silver**: GPS location, sensor readings with alerts
- **Golden**: Alert data, sensor rules
- **Status**: Data contracts defined, implementation pending

#### 3. Mantentions (Maintenance Records) - 🔄 In Progress
- **Golden**: Weekly maintenance reports with activity details
- **Status**: Data contracts defined, implementation pending

#### 4. Alerts (Consolidated) - 🔄 In Progress
- **Golden**: Cross-technique alerts with AI diagnosis
- **Status**: Data contracts defined, implementation pending

See individual data contracts for detailed schemas:
- [Oil Data Contracts](documentation/oil/DATA_CONTRACTS.md)
- [Telemetry Data Contracts](documentation/telemetry/data_contracts.md)
- [Mantentions Data Contracts](documentation/mantentions/data_contracts.md)
- [Alerts Data Contracts](documentation/alerts/data_contracts.md)

## 🔍 Troubleshooting

### Dashboard Won't Start

```bash
# Check logs
docker-compose logs

# Verify data files exist
ls -la data/oil/processed/

# Check port availability
netstat -an | grep 8050
```

### Login Issues

- Verify credentials in `config/users.py`
- Check SECRET_KEY is set in `.env`
- Clear browser cache and cookies

### No Data Displayed

- Ensure Parquet files exist in `data/oil/golden/{client}/`
- Verify required files: `classified.parquet`, `machine_status.parquet`, `stewart_limits.parquet`
- Check Parquet format is valid (use `pd.read_parquet()` to test)
- Verify container has read access to data volume
- Ensure data includes `componentNameNormalized` field for proper limits matching

### Performance Issues

```bash
# Increase container resources in docker-compose.yml
services:
  dashboard:
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '1.0'
```

## 📝 Maintenance

### Update Dependencies

```bash
# Update requirements.txt
# Rebuild image
docker-compose build --no-cache

# Restart services
docker-compose up -d
```

### Backup Data

```bash
# Backup processed data
tar -czf dashboard-data-backup-$(date +%Y%m%d).tar.gz data/

# Backup logs
tar -czf dashboard-logs-backup-$(date +%Y%m%d).tar.gz logs/
```

## 📚 Additional Documentation

- **General**:
  - [Dashboard Overview](documentation/general/dashboard_overview.md) - High-level architecture and features
  - [Migration Plan](documentation/general/migration_plan.md) - Multi-technique integration roadmap
- **Data Contracts**:
  - [Oil Data Contracts](documentation/oil/DATA_CONTRACTS.md) - Tribology data specifications
  - [Telemetry Data Contracts](documentation/telemetry/data_contracts.md) - Sensor data specifications
  - [Mantentions Data Contracts](documentation/mantentions/data_contracts.md) - Maintenance data specifications
  - [Alerts Data Contracts](documentation/alerts/data_contracts.md) - Consolidated alerts specifications

## 🤝 Support

For issues or questions:
1. Check troubleshooting section above
2. Review application logs: `docker-compose logs`
3. Contact development team

## 📄 License

Internal use only - Proprietary software

---

**Version**: 2.0.0  
**Last Updated**: February 2026  
**Maintained by**: Technical Alerts Team

**Recent Updates:**
- ✨ Component granularity preservation (left/right positions)
- 🏗️ Migrated to Bronze/Silver/Golden data architecture
- 🔧 Enhanced Stewart Limits calculation with component normalization
- 📊 Improved data contracts and documentation
