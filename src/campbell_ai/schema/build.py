"""Regenerate `dataset_columns.json` from the data on disk.

Run by hand when the ETL genuinely changes a schema, never automatically:

    python -m src.campbell_ai.schema.build

The output is committed, so a schema change arrives as a reviewable diff instead of as
behaviour that shifted under the service. Deliberately records only format and column names -
no sizes, no timestamps - so regenerating on unchanged data produces no diff at all, and any
diff that does appear is a real schema change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.campbell_ai.data import DATASETS, DashboardDataRepository  # noqa: E402
from src.campbell_ai.schema import SCHEMA_FILE  # noqa: E402

# Clients to declare. A client absent from the file simply falls back to reading headers, so
# omitting one degrades performance rather than correctness.
CLIENTS = ("cda", "capstone", "emin", "enex")

NOTE = (
    "Generado por `python -m src.campbell_ai.schema.build`. Columnas declaradas por cliente: "
    "cuatro de los once datasets traen columnas distintas segun el cliente, asi que una lista "
    "compartida seria incorrecta para alguno. Un cliente o dataset ausente aqui no es un error: "
    "se lee la cabecera como antes."
)


def build(data_root: str | Path = "data") -> dict:
    repository = DashboardDataRepository(data_root)
    clients: dict[str, dict] = {}
    for client in CLIENTS:
        datasets: dict[str, dict] = {}
        for spec in DATASETS:
            try:
                path = repository.dataset_path(spec.key, client)
            except Exception:
                continue
            if not path.exists():
                continue
            try:
                columns = repository.read_columns(path)
            except Exception as exc:  # noqa: BLE001 - report and skip, do not guess
                print(f"  ! {client}/{spec.key}: {type(exc).__name__}: {exc}")
                continue
            datasets[spec.key] = {
                "format": path.suffix.lstrip(".").lower(),
                "columns": columns,
            }
        if datasets:
            clients[client] = datasets
            total = sum(len(d["columns"]) for d in datasets.values())
            print(f"  {client:10s} {len(datasets):2d} datasets, {total:4d} columnas")
    return {"note": NOTE, "clients": clients}


def main() -> int:
    print(f"Leyendo cabeceras reales para regenerar {SCHEMA_FILE.name}")
    document = build()
    if not document["clients"]:
        print("Sin datos legibles: no se escribe nada.")
        return 1
    SCHEMA_FILE.write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"Escrito {SCHEMA_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
