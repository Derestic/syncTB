"""Correspondencia de IDs origen -> destino y reescritura de referencias en el JSON."""

import re
from typing import Any, Dict, Set

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class IdMap:
    def __init__(self):
        self._map: Dict[str, str] = {}

    def set(self, source_id: str, target_id: str) -> None:
        self._map[source_id.lower()] = target_id

    def get(self, source_id: str):
        return self._map.get(source_id.lower()) if source_id else None

    def __contains__(self, source_id) -> bool:
        return bool(source_id) and source_id.lower() in self._map

    def __len__(self):
        return len(self._map)

    def rewrite(self, value: Any, unresolved: Set[str] = None) -> Any:
        """Devuelve una copia de `value` con los UUID mapeados sustituidos.

        Se reemplazan los UUID que aparecen en cualquier cadena (también dentro de
        textos como scripts o configuraciones de dashboards). Los UUID no mapeados se
        dejan tal cual y, si se pasa `unresolved`, se añaden a ese conjunto.
        """
        if isinstance(value, dict):
            return {k: self.rewrite(v, unresolved) for k, v in value.items()}
        if isinstance(value, list):
            return [self.rewrite(v, unresolved) for v in value]
        if isinstance(value, str) and UUID_RE.search(value):
            return UUID_RE.sub(lambda m: self._replace(m.group(0), unresolved), value)
        return value

    def _replace(self, uuid: str, unresolved) -> str:
        target = self.get(uuid)
        if target is not None:
            return target
        if unresolved is not None:
            unresolved.add(uuid.lower())
        return uuid
