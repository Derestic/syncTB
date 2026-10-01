"""Lectura del repositorio de Version Control de ThingsBoard clonado en local.

Estructura esperada:
    <tipo>/<externalId>.json
    groups/<tipo_grupo>/<externalId>.json
    hierarchy/<ownerId>/dashboard/<externalId>.json
    hierarchy/<ownerId>/groups/<tipo_grupo>/<externalId>.json
"""

import json
import logging
from pathlib import Path
from typing import Iterator, Tuple

from synctb.model import FOLDER_TYPES, GROUP_FOLDER_TYPES, SourceEntity, SourceRepository

log = logging.getLogger(__name__)


class RepositoryError(Exception):
    pass


def load_repository(root: Path) -> SourceRepository:
    repo = SourceRepository()
    for entity_type, path in _iter_files(Path(root)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RepositoryError(f"No se puede leer {path}: {e}") from e

        declared = data.get("entityType")
        if declared and declared != entity_type:
            log.warning("%s declara entityType=%s pero está en una carpeta de %s; se usa %s",
                        path, declared, entity_type, declared)
            entity_type = declared

        repo.entities.append(SourceEntity(entity_type=entity_type, source_id=path.stem, path=path, data=data))

    log.info("Repositorio origen: %d ficheros leídos de %s", len(repo.entities), root)
    return repo


def _iter_files(root: Path) -> Iterator[Tuple[str, Path]]:
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
                        log.warning("Carpeta desconocida ignorada: %s", sub)
        else:
            log.warning("Carpeta desconocida ignorada: %s", folder)


def _group_files(groups_dir: Path) -> Iterator[Tuple[str, Path]]:
    for sub in sorted(p for p in groups_dir.iterdir() if p.is_dir()):
        if sub.name not in GROUP_FOLDER_TYPES:
            log.warning("Tipo de grupo desconocido ignorado: %s", sub)
            continue
        yield from _json_files(sub, "ENTITY_GROUP")


def _json_files(folder: Path, entity_type: str) -> Iterator[Tuple[str, Path]]:
    for path in sorted(folder.glob("*.json")):
        yield entity_type, path
