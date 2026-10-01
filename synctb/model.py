"""Modèle en mémoire des entités lues dans le dépôt source.

Chaque fichier du dépôt Version Control est un `EntityExportData` de ThingsBoard :

    {
      "entityType": "ASSET",
      "entity": { ... },            # l'entité telle que la renvoie l'API REST
      "relations": [ ... ],
      "attributes": {"SERVER_SCOPE": [ ... ]},
      "calculatedFields": [ ... ],
      ...                           # champs propres au type (metaData, memberIds, ...)
    }

Le nom du fichier est l'identifiant de l'entité dans l'instance source (son externalId).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Dossier du dépôt VC -> entityType ThingsBoard
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

# Sous-dossier de groups/ -> type d'entité contenu dans le groupe
GROUP_FOLDER_TYPES = {
    "asset": "ASSET",
    "customer": "CUSTOMER",
    "dashboard": "DASHBOARD",
    "device": "DEVICE",
    "entity_view": "ENTITY_VIEW",
    "user": "USER",
}


def entity_id(entity_type: str, uuid: str) -> dict:
    """Référence ThingsBoard {"entityType", "id"}."""
    return {"entityType": entity_type, "id": uuid}


def ref_id(ref) -> Optional[str]:
    """UUID d'une référence {"entityType", "id"}, ou None."""
    if isinstance(ref, dict):
        return ref.get("id")
    return None


@dataclass
class SourceEntity:
    """Un fichier EntityExportData du dépôt VC."""

    entity_type: str
    source_id: str   # identifiant dans l'instance source (= nom du fichier)
    path: Path
    data: dict       # contenu complet du fichier
    # Uniquement ENTITY_GROUP : membres lus dans <id>_entities.json ([{"entityType", "id"}, ...])
    members: List[dict] = field(default_factory=list)

    @property
    def entity(self) -> dict:
        """Corps de l'entité, au format de l'API REST."""
        return self.data.get("entity") or {}

    @property
    def name(self) -> str:
        """Nom lisible pour les logs (name, title ou fqn selon le type)."""
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
    def member_ids(self) -> List[str]:
        """Uniquement ENTITY_GROUP : identifiants source des membres.

        Ils proviennent du fichier <id>_entities.json et, le cas échéant, du champ
        `memberIds` du groupe lui-même (format des versions plus récentes).
        """
        ids = [m["id"] for m in self.members] + list(self.data.get("memberIds") or [])
        return list(dict.fromkeys(i for i in ids if i))

    @property
    def group_type(self) -> Optional[str]:
        """Uniquement pour ENTITY_GROUP : type d'entité regroupé."""
        return self.entity.get("type") if self.entity_type == "ENTITY_GROUP" else None

    def __str__(self):
        return f"{self.entity_type} '{self.name}' [{self.source_id}]"


@dataclass
class SourceRepository:
    """Ensemble des entités du dépôt source, après lecture et filtrage."""

    entities: List[SourceEntity] = field(default_factory=list)
    # Entités du dépôt qui ne sont pas synchronisées (devices, assets non « Risque »).
    # Elles servent à avertir lorsqu'une autre entité y fait référence.
    excluded: Dict[str, SourceEntity] = field(default_factory=dict)
    # Fichiers ignorés car leur format n'est pas reconnu
    unsupported: List[Path] = field(default_factory=list)

    def of_type(self, entity_type: str) -> List[SourceEntity]:
        return [e for e in self.entities if e.entity_type == entity_type]

    def by_id(self) -> Dict[str, SourceEntity]:
        return {e.source_id: e for e in self.entities}

    @property
    def tenant_id(self) -> Optional[str]:
        """Tenant d'origine du dépôt (lu dans le champ tenantId des entités)."""
        for e in self.entities:
            tid = ref_id(e.entity.get("tenantId"))
            if tid:
                return tid
        return None
