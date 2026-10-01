"""Configuration d'exécution : arguments de la CLI avec repli sur les variables d'environnement.

En pipeline CI/CD, les valeurs sont normalement fournies par des variables d'environnement.
Les arguments de la ligne de commande, s'ils sont présents, ont la priorité.
"""

import os
from dataclasses import dataclass
from pathlib import Path

ENV_URL = "TB_URL"
ENV_USERNAME = "TB_USERNAME"
ENV_PASSWORD = "TB_PASSWORD"
ENV_TENANT = "TB_TENANT"


class ConfigError(Exception):
    """Configuration incomplète ou invalide."""


@dataclass(frozen=True)
class Config:
    """Paramètres validés d'une exécution."""

    repo_path: Path    # dépôt Version Control cloné en local
    url: str           # URL de base du ThingsBoard cible, sans « / » final
    username: str      # tenant admin du tenant cible
    password: str
    tenant_name: str   # nom attendu du tenant cible (garde-fou)
    dry_run: bool = False

    @classmethod
    def build(cls, repo_path, url=None, username=None, tenant_name=None, dry_run=False, environ=None):
        """Construit la configuration en combinant arguments et variables d'environnement.

        `environ` permet d'injecter un environnement de test ; par défaut `os.environ`.
        Lève `ConfigError` si une valeur obligatoire manque ou si le dépôt n'existe pas.
        """
        env = os.environ if environ is None else environ
        values = {
            ENV_URL: url or env.get(ENV_URL),
            ENV_USERNAME: username or env.get(ENV_USERNAME),
            # Le mot de passe ne vient que de l'environnement : il ne doit apparaître
            # ni dans l'historique du shell ni dans les logs de la pipeline.
            ENV_PASSWORD: env.get(ENV_PASSWORD),
            ENV_TENANT: tenant_name or env.get(ENV_TENANT),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfigError("Valeurs obligatoires manquantes : " + ", ".join(missing))

        repo = Path(repo_path)
        if not repo.is_dir():
            raise ConfigError(f"Le dépôt source n'existe pas ou n'est pas un répertoire : {repo}")

        return cls(
            repo_path=repo,
            url=values[ENV_URL].rstrip("/"),
            username=values[ENV_USERNAME],
            password=values[ENV_PASSWORD],
            tenant_name=values[ENV_TENANT],
            dry_run=dry_run,
        )
