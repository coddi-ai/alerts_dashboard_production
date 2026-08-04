"""Client configuration loader (design.md §3.3, REQ-019)."""
from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

CLIENTS_DIR = Path(__file__).resolve().parent.parent / "config" / "clients"


class ErpType(str, Enum):
    sap = "sap"
    ellipse = "ellipse"
    maximo = "maximo"
    stub = "stub"


class AssetIdFormat(str, Enum):
    equipment = "equipment"
    functional_location = "functional_location"


class SapConfig(BaseModel):
    notification_type: str
    planning_plant: str
    planner_group: str | None = None
    main_work_center: str | None = None


class ClientConfig(BaseModel):
    client_id: str
    client_erp_type: ErpType
    asset_id_format: AssetIdFormat
    sap: SapConfig
    dedup_time_window_minutes: int = 1440


def load_client_config(client_id: str, clients_dir: Path = CLIENTS_DIR) -> ClientConfig:
    """Read and validate `config/clients/{client_id}.yaml`."""
    path = clients_dir / f"{client_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No client config found for '{client_id}' at {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return ClientConfig(**raw)
