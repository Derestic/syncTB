"""Compteurs de l'exécution et résumé final sur la console."""

import logging
from collections import defaultdict

log = logging.getLogger(__name__)

# Clés internes des actions -> en-têtes affichés dans le résumé
ACTIONS = {
    "created": "créés",
    "updated": "màj",
    "deleted": "suppr.",
    "kept": "conservés",
    "failed": "échecs",
}


class Report:
    """Accumule les actions par type d'entité ainsi que le nombre d'avertissements et d'erreurs."""

    def __init__(self):
        self.counts = defaultdict(lambda: defaultdict(int))
        self.warnings = 0
        self.errors = 0

    def count(self, entity_type: str, action: str, n: int = 1) -> None:
        self.counts[entity_type][action] += n

    def warn(self, msg, *args) -> None:
        """Avertissement : n'affecte pas le code de sortie."""
        self.warnings += 1
        log.warning(msg, *args)

    def error(self, msg, *args) -> None:
        """Erreur sur une entité : le traitement continue, mais le code de sortie sera 1."""
        self.errors += 1
        log.error(msg, *args)

    def log_summary(self, dry_run: bool) -> None:
        log.info("=" * 72)
        log.info("Résumé%s", " (DRY-RUN, rien n'a été modifié)" if dry_run else "")
        log.info("%-24s %s", "type", " ".join(f"{h:>9}" for h in ACTIONS.values()))
        for entity_type in sorted(self.counts):
            row = self.counts[entity_type]
            log.info("%-24s %s", entity_type, " ".join(f"{row.get(a, 0):>9}" for a in ACTIONS))
        log.info("Avertissements : %d  Erreurs : %d", self.warnings, self.errors)
        log.info("=" * 72)
