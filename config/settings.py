"""
Application settings for Multi-Technical-Alerts.

Uses Pydantic Settings for configuration management with environment variable support.
"""

from pathlib import Path
from typing import Dict, List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from src.data.catalog import dashboard_data_root


# Dashboard release version, shown as a footnote on the login page.
# Bump this manually whenever a new version is deployed.
APP_VERSION = "2.1.18"


class Settings(BaseSettings):
    """Application configuration with validation."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # API Keys
    openai_api_key: str = Field(default="", description="OpenAI API key for recommendations")
    mapbox_token: str = Field(default="", description="Mapbox access token for maps")
    
    # Paths - managed internally, not via .env
    logs_dir: Path = Field(default=Path("logs"), description="Logs directory")
    
    @property
    def data_root(self) -> Path:
        """Get the same mounted data root used by all read-only loaders."""
        return dashboard_data_root()
    
    # Dashboard
    secret_key: str = Field(default="dev-secret-key-change-in-production", description="Secret key for sessions")
    dashboard_host: str = Field(default="0.0.0.0", description="Dashboard host")
    dashboard_port: int = Field(default=8050, description="Dashboard port")
    debug_mode: bool = Field(default=False, description="Enable debug mode")
    
    # Processing
    max_workers: int = Field(default=18, description="Max parallel workers for AI processing")
    min_machine_samples: int = Field(default=5, description="Minimum samples per machine")
    min_component_samples: int = Field(default=3, description="Minimum samples per component")
    
    # Stewart Limits
    percentile_marginal: int = Field(default=90, description="Percentile for Marginal threshold")
    percentile_condenatorio: int = Field(default=95, description="Percentile for Condenatorio threshold")
    percentile_critico: int = Field(default=98, description="Percentile for Critico threshold")
    
    # AI Configuration
    openai_model: str = Field(default="gpt-4o-mini", description="OpenAI model")
    openai_temperature: float = Field(default=0.9, description="Temperature for AI generation")
    openai_max_tokens: int = Field(default=500, description="Max tokens per response")
    
    # Classification Thresholds
    essay_points_marginal: int = Field(default=1, description="Points for Marginal essays")
    essay_points_condenatorio: int = Field(default=3, description="Points for Condenatorio essays")
    essay_points_critico: int = Field(default=5, description="Points for Critico essays")
    
    report_threshold_normal: int = Field(default=3, description="Report threshold for Normal (<)")
    report_threshold_anormal: int = Field(default=5, description="Report threshold for Anormal (>=)")
    
    # Clients
    clients: List[str] = Field(default=["CDA", "EMIN", "ENEX", "CAPSTONE"], description="List of client names")
    
    # Module access control - clients allowed to access specific modules.
    # Predictive module access is now centralized in config/client_services.json
    # (service id 'predictive') - see config/client_services.py::is_service_enabled.
    component_hours_allowed_clients: List[str] = Field(
        default=["CDA", "ENEX"],
        description="Clients with access to the Component Hours (Horómetro) module"
    )

    # Laboratory Compliance - per-client threshold (days) for the compliance window
    lab_compliance_default_threshold_days: float = Field(
        default=2.0,
        description="Default laboratory compliance threshold (days) when a client has no override"
    )
    lab_compliance_threshold_days_by_client: Dict[str, float] = Field(
        default_factory=dict,
        description="Per-client laboratory compliance threshold (days), keyed by uppercase client id"
    )

    def get_lab_compliance_threshold_days(self, client: str) -> float:
        """Get the laboratory compliance threshold (days) for a client, falling back to the default."""
        return self.lab_compliance_threshold_days_by_client.get(
            str(client or "").upper(), self.lab_compliance_default_threshold_days
        )

    @field_validator("logs_dir", mode="before")
    @classmethod
    def ensure_path(cls, v):
        """Convert string to Path if needed."""
        if isinstance(v, str):
            return Path(v)
        return v
    
    @field_validator("clients", mode="before")
    @classmethod
    def parse_clients(cls, v):
        """Parse comma-separated clients if string."""
        if isinstance(v, str):
            return [c.strip() for c in v.split(",")]
        return v
    
    # Generic multi-technique path methods
    def get_technique_path(self, technique: str, layer: str, client: str) -> Path:
        """
        Get path for any technique following data/{technique}/{layer}/{client} pattern.
        
        Args:
            technique: 'oil', 'telemetry', 'mantentions', or 'alerts'
            layer: 'bronze', 'silver', or 'golden'
            client: Client identifier
        
        Returns:
            Path to technique data
        """
        return self.data_root / technique / layer / client.lower()
    
    def get_technique_file(self, technique: str, layer: str, client: str, filename: str) -> Path:
        """
        Get specific file path for any technique.
        
        Args:
            technique: 'oil', 'telemetry', 'mantentions', or 'alerts'
            layer: 'bronze', 'silver', or 'golden'
            client: Client identifier
            filename: File name (e.g., 'classified.parquet')
        
        Returns:
            Full file path
        """
        return self.get_technique_path(technique, layer, client) / filename
    
    # Oil-specific convenience methods
    def get_bronze_path(self, client: str) -> Path:
        """Get bronze (raw) data path for oil technique."""
        return self.get_technique_path('oil', 'bronze', client)
    
    def get_silver_path(self, client: str) -> Path:
        """Get silver (harmonized) data file path for oil technique."""
        return self.get_technique_path('oil', 'silver', client) / f"{client.upper()}.parquet"
    
    def get_golden_path(self, client: str) -> Path:
        """Get golden (analysis-ready) data path for oil technique."""
        return self.get_technique_path('oil', 'golden', client)
    
    def get_classified_reports_path(self, client: str) -> Path:
        """Get classified reports path for oil technique."""
        return self.get_technique_file('oil', 'golden', client, 'classified.parquet')
    
    def get_machine_status_path(self, client: str) -> Path:
        """Get machine status path for oil technique."""
        return self.get_technique_file('oil', 'golden', client, 'machine_status.parquet')
    
    def get_stewart_limits_path(self, client: str) -> Path:
        """Get Stewart limits path for oil technique."""
        return self.get_technique_file('oil', 'golden', client, 'stewart_limits.parquet')

    def get_stewart_limits_inferior_path(self, client: str) -> Path:
        """Get lower-bound Stewart limits path for oil technique (v2.7)."""
        return self.get_technique_file('oil', 'golden', client, 'stewart_limits_inferior.parquet')

    def get_stewart_limits_four_path(self, client: str) -> Path:
        """Get four-limit (LIC/LIM/LSM/LSC) Stewart limits path for oil technique (v2.8)."""
        return self.get_technique_file('oil', 'golden', client, 'stewart_limits_four.parquet')

    def get_component_hours_path(self, client: str) -> Path:
        """Get cleaned component hours path for oil technique."""
        return self.get_technique_file('oil', 'golden', client, 'cleaned_component_hours.parquet')
    
    # Telemetry-specific convenience methods
    def get_telemetry_gps_path(self, client: str) -> Path:
        """Get GPS data path for telemetry."""
        return self.get_technique_file('telemetry', 'silver', client, 'gps.parquet')
    
    def get_telemetry_data_path(self, client: str) -> Path:
        """Get telemetry sensor data path."""
        return self.get_technique_file('telemetry', 'silver', client, 'telemetry.parquet')
    
    def get_telemetry_alerts_path(self, client: str) -> Path:
        """Get telemetry alerts data path."""
        return self.get_technique_file('telemetry', 'golden', client, 'alerts_data.csv')
    
    def get_telemetry_rules_path(self, client: str) -> Path:
        """Get telemetry data rules path."""
        return self.get_technique_file('telemetry', 'golden', client, 'data_rules.csv')
    
    # Mantentions-specific convenience methods
    def get_mantentions_report_path(self, client: str, week: str) -> Path:
        """
        Get mantentions weekly report path.
        
        Args:
            client: Client identifier
            week: Week in format 'ww-yyyy' (e.g., '32-2025')
        
        Returns:
            Path to weekly maintenance report
        """
        return self.get_technique_file('mantentions', 'golden', client, f'{week}.csv')
    
    # Alerts-specific convenience methods
    def get_consolidated_alerts_path(self, client: str) -> Path:
        """Get consolidated alerts path."""
        return self.get_technique_file('alerts', 'golden', client, 'consolidated_alerts.csv')

    # ERP (Conexión ERP) convenience methods
    def get_erp_warning_path(self, client: str, state: str) -> Path:
        """Get Parquet path for one client's warnings in a given lifecycle state.

        Layout is `data/warnings/{client}/{state}.parquet` — client nested
        under a top-level `warnings` folder (not the technique/layer/client
        shape used by oil/telemetry/alerts), matching where the ERP pipeline
        actually writes this data.
        """
        return self.data_root / 'warnings' / client.lower() / f'{state}.parquet'
    
    def create_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        # Create logs directory (writable)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Note: Data directories (bronze, silver, golden) are managed by the data pipeline
        # and mounted read-only in Docker, so we don't create them here


# Global settings instance
_settings = None


def get_settings() -> Settings:
    """Get global settings instance (singleton pattern)."""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.create_directories()
    return _settings
