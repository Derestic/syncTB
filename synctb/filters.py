"""Règles d'exclusion de la source : pas d'utilisateurs, pas de devices, assets « Risque » uniquement.

Les assets de type « Site » stockent des données propres à chaque instance : ils ne sont
jamais envoyés vers la cible. Les entités exclues sont conservées à part afin de pouvoir
avertir lorsqu'une entité synchronisée y fait référence.
"""

import logging

from synctb.model import SourceRepository, ref_id

log = logging.getLogger(__name__)

SYNCED_ASSET_TYPE = "Risque"
EXCLUDED_TYPES = {"DEVICE", "USER"}


def asset_type(asset, profile_names) -> str:
    """Type de l'asset : son champ `type` ou, à défaut, le nom de son asset profile."""
    e = asset.entity
    return e.get("type") or profile_names.get(ref_id(e.get("assetProfileId")), "")


def apply_filters(repo: SourceRepository) -> SourceRepository:
    """Renvoie un nouveau dépôt ne contenant que les entités à synchroniser."""
    profile_names = {p.source_id: p.name for p in repo.of_type("ASSET_PROFILE")}
    result = SourceRepository()
    skipped = {}

    for e in repo.entities:
        excluded = e.entity_type in EXCLUDED_TYPES or (
            e.entity_type == "ASSET" and asset_type(e, profile_names) != SYNCED_ASSET_TYPE
        )
        if excluded:
            result.excluded[e.source_id] = e
            key = e.entity_type if e.entity_type != "ASSET" else f"ASSET ({asset_type(e, profile_names) or '?'})"
            skipped[key] = skipped.get(key, 0) + 1
        else:
            result.entities.append(e)

    for key, count in sorted(skipped.items()):
        log.info("Exclus de la source : %d %s", count, key)
    return result
