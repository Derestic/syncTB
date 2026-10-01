"""Reglas de exclusión del origen: sin usuarios, sin devices y solo assets de tipo Risque."""

import logging

from synctb.model import SourceRepository, ref_id

log = logging.getLogger(__name__)

SYNCED_ASSET_TYPE = "Risque"
EXCLUDED_TYPES = {"DEVICE", "USER"}


def asset_type(asset, profile_names) -> str:
    """Tipo del asset: campo `type` o, si falta, el nombre de su asset profile."""
    e = asset.entity
    return e.get("type") or profile_names.get(ref_id(e.get("assetProfileId")), "")


def apply_filters(repo: SourceRepository) -> SourceRepository:
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
        log.info("Excluidos del origen: %d %s", count, key)
    return result
