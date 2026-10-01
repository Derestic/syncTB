"""Correspondance des identifiants source -> cible et réécriture des références dans le JSON.

Lorsque la cible est un autre tenant, les entités créées reçoivent de nouveaux UUID.
Toutes les références entre entités (asset -> asset profile, dashboard -> asset,
nœud de rule chain -> rule chain, ...) doivent donc être recalculées. Plutôt que de
connaître chaque champ de chaque type, on remplace tout UUID connu, où qu'il apparaisse.
"""

import re
from typing import Any, Dict, Set

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class IdMap:
    """Table UUID source -> UUID cible (insensible à la casse)."""

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
        """Renvoie une copie de `value` où les UUID connus sont remplacés.

        Les UUID sont remplacés dans n'importe quelle chaîne, y compris à l'intérieur de
        textes (scripts, configuration de dashboards, ...). Les UUID inconnus sont laissés
        tels quels et, si `unresolved` est fourni, ajoutés à cet ensemble (en minuscules).
        Les clés des dictionnaires ne sont pas modifiées.
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
