"""Construcción de repositorios VC de prueba en disco."""

import json
from pathlib import Path

from tests.fakes import uid

SOURCE_TENANT = "22222222-2222-2222-2222-222222222222"


def export(entity_type, entity, **extra):
    data = {"entityType": entity_type, "entity": entity, "relations": [], "attributes": {"SERVER_SCOPE": []}}
    data.update(extra)
    return data


def src_entity(entity_type, entity_uuid=None, **fields):
    e = {"id": {"entityType": entity_type, "id": entity_uuid or uid()},
         "tenantId": {"entityType": "TENANT", "id": SOURCE_TENANT},
         "createdTime": 1700000000000, "version": 3}
    e.update(fields)
    return e


def write(root: Path, folder: str, data: dict) -> str:
    """Guarda `data` en <root>/<folder>/<id>.json y devuelve el id."""
    entity_uuid = data["entity"]["id"]["id"]
    path = Path(root) / folder / f"{entity_uuid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return entity_uuid
