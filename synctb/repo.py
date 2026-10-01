"""Lecture du dépôt de Version Control ThingsBoard cloné en local.

Structure attendue :
    <type>/<externalId>.json
    groups/<type_de_groupe>/<externalId>.json
    hierarchy/<ownerId>/dashboard/<externalId>.json
    hierarchy/<ownerId>/groups/<type_de_groupe>/<externalId>.json

`hierarchy/<ownerId>` contient les entités dont le propriétaire est le customer
<ownerId> (il n'y a pas d'imbrication). Les dossiers cachés (.git, ...) sont ignorés.
"""

import json
import logging
from pathlib import Path
from typing import Iterator, Tuple

from synctb.model import FOLDER_TYPES, GROUP_FOLDER_TYPES, SourceEntity, SourceRepository

log = logging.getLogger(__name__)


class RepositoryError(Exception):
    """Fichier du dépôt illisible ou JSON invalide."""


def load_repository(root: Path) -> SourceRepository:
    """Lit tous les fichiers JSON du dépôt et les renvoie sans aucun filtrage."""
    repo = SourceRepository()
    for entity_type, path in _iter_files(Path(root)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RepositoryError(f"Impossible de lire {path} : {e}") from e

        # Le champ entityType du fichier prévaut sur le dossier qui le contient
        declared = data.get("entityType")
        if declared and declared != entity_type:
            log.warning("%s déclare entityType=%s mais se trouve dans un dossier de %s ; %s est utilisé",
                        path, declared, entity_type, declared)
            entity_type = declared

        repo.entities.append(SourceEntity(entity_type=entity_type, source_id=path.stem, path=path, data=data))

    log.info("Dépôt source : %d fichiers lus depuis %s", len(repo.entities), root)
    return repo


def _iter_files(root: Path) -> Iterator[Tuple[str, Path]]:
    """Parcourt le dépôt et produit des couples (entityType, chemin du fichier)."""
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if folder.name in FOLDER_TYPES:
            yield from _json_files(folder, FOLDER_TYPES[folder.name])
        elif folder.name == "groups":
            yield from _group_files(folder)
        elif folder.name == "hierarchy":
            for owner in sorted(p for p in folder.iterdir() if p.is_dir()):
                for sub in sorted(p for p in owner.iterdir() if p.is_dir()):
                    if sub.name == "groups":
                        yield from _group_files(sub)
                    elif sub.name in FOLDER_TYPES:
                        yield from _json_files(sub, FOLDER_TYPES[sub.name])
                    else:
                        log.warning("Dossier inconnu ignoré : %s", sub)
        else:
            log.warning("Dossier inconnu ignoré : %s", folder)


def _group_files(groups_dir: Path) -> Iterator[Tuple[str, Path]]:
    """Fichiers d'un dossier groups/ : tous sont des ENTITY_GROUP, quel que soit le sous-dossier."""
    for sub in sorted(p for p in groups_dir.iterdir() if p.is_dir()):
        if sub.name not in GROUP_FOLDER_TYPES:
            log.warning("Type de groupe inconnu ignoré : %s", sub)
            continue
        yield from _json_files(sub, "ENTITY_GROUP")


def _json_files(folder: Path, entity_type: str) -> Iterator[Tuple[str, Path]]:
    for path in sorted(folder.glob("*.json")):
        yield entity_type, path
