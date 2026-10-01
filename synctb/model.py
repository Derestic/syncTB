"""Modelo en memoria de las entidades leídas del repositorio origen."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Carpeta del repo VC -> entityType de ThingsBoard
FOLDER_TYPES = {
    "asset": "ASSET",
    "asset_profile": "ASSET_PROFILE",
    "converter": "CONVERTER",
    "customer": "CUSTOMER",
    "dashboard": "DASHBOARD",
    "device": "DEVICE",
    "device_profile": "DEVICE_PROFILE",
    "integration": "INTEGRATION",
    "notification_rule": "NOTIFICATION_RULE",
    "notification_target": "NOTIFICATION_TARGET",
    "notification_template": "NOTIFICATION_TEMPLATE",
    "role": "ROLE",
    "rule_chain": "RULE_CHAIN",
    "tb_resource": "TB_RESOURCE",
    "widget_type": "WIDGET_TYPE",
    "widget_bundle": "WIDGETS_BUNDLE",
}

# Subcarpeta de groups/ -> tipo de entidad que contiene el grupo
GROUP_FOLDER_TYPES = {
    "asset": "ASSET",
    "customer": "CUSTOMER",
    "dashboard": "DASHBOARD",
    "device": "DEVICE",
    "entity_view": "ENTITY_VIEW",
    "user": "USER",
}


def entity_id(entity_type: str, uuid: str) -> dict:
    return {"entityType": entity_type, "id": uuid}


def ref_id(ref) -> Optional[str]:
    """UUID de una referencia {"entityType", "id"} o None."""
    if isinstance(ref, dict):
        return ref.get("id")
    return None


@dataclass
class SourceEntity:
    """Un fichero EntityExportData del repo VC."""

    entity_type: str
    source_id: str
    path: Path
    data: dict

    @property
    def entity(self) -> dict:
        return self.data.get("entity") or {}

    @property
    def name(self) -> str:
        e = self.entity
        return e.get("name") or e.get("title") or e.get("fqn") or self.source_id

    @property
    def relations(self) -> List[dict]:
        return self.data.get("relations") or []

    @property
    def attributes(self) -> Dict[str, List[dict]]:
        return self.data.get("attributes") or {}

    @property
    def calculated_fields(self) -> List[dict]:
        return self.data.get("calculatedFields") or []

    @property
    def group_type(self) -> Optional[str]:
        """Solo ENTITY_GROUP: tipo de entidad que agrupa."""
        return self.entity.get("type") if self.entity_type == "ENTITY_GROUP" else None

    def __str__(self):
        return f"{self.entity_type} '{self.name}' [{self.source_id}]"


@dataclass
class SourceRepository:
    entities: List[SourceEntity] = field(default_factory=list)
    # Entidades del repo que no se sincronizan (devices, assets que no son Risque).
    # Se usan para avisar cuando otra entidad las referencia.
    excluded: Dict[str, SourceEntity] = field(default_factory=dict)

    def of_type(self, entity_type: str) -> List[SourceEntity]:
        return [e for e in self.entities if e.entity_type == entity_type]

    def by_id(self) -> Dict[str, SourceEntity]:
        return {e.source_id: e for e in self.entities}

    @property
    def tenant_id(self) -> Optional[str]:
        for e in self.entities:
            tid = ref_id(e.entity.get("tenantId"))
            if tid:
                return tid
        return None
