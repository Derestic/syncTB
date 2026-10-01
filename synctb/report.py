"""Contadores de la ejecución y resumen final por consola."""

import logging
from collections import defaultdict

log = logging.getLogger(__name__)

ACTIONS = ("created", "updated", "deleted", "kept", "failed")


class Report:
    def __init__(self):
        self.counts = defaultdict(lambda: defaultdict(int))
        self.warnings = 0
        self.errors = 0

    def count(self, entity_type: str, action: str, n: int = 1) -> None:
        self.counts[entity_type][action] += n

    def warn(self, msg, *args) -> None:
        self.warnings += 1
        log.warning(msg, *args)

    def error(self, msg, *args) -> None:
        self.errors += 1
        log.error(msg, *args)

    def log_summary(self, dry_run: bool) -> None:
        log.info("=" * 72)
        log.info("Resumen%s", " (DRY-RUN, no se ha modificado nada)" if dry_run else "")
        log.info("%-24s %s", "tipo", " ".join(f"{a:>8}" for a in ACTIONS))
        for entity_type in sorted(self.counts):
            row = self.counts[entity_type]
            log.info("%-24s %s", entity_type, " ".join(f"{row.get(a, 0):>8}" for a in ACTIONS))
        log.info("Avisos: %d  Errores: %d", self.warnings, self.errors)
        log.info("=" * 72)
