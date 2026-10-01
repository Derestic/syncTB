"""Configuración de ejecución: argumentos de CLI con fallback a variables de entorno."""

import os
from dataclasses import dataclass
from pathlib import Path

ENV_URL = "TB_URL"
ENV_USERNAME = "TB_USERNAME"
ENV_PASSWORD = "TB_PASSWORD"
ENV_TENANT = "TB_TENANT"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    repo_path: Path
    url: str
    username: str
    password: str
    tenant_name: str
    dry_run: bool = False

    @classmethod
    def build(cls, repo_path, url=None, username=None, tenant_name=None, dry_run=False, environ=None):
        env = os.environ if environ is None else environ
        values = {
            ENV_URL: url or env.get(ENV_URL),
            ENV_USERNAME: username or env.get(ENV_USERNAME),
            # La contraseña solo por entorno para que no quede en el historial ni en los logs de la pipeline
            ENV_PASSWORD: env.get(ENV_PASSWORD),
            ENV_TENANT: tenant_name or env.get(ENV_TENANT),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfigError("Faltan valores obligatorios: " + ", ".join(missing))

        repo = Path(repo_path)
        if not repo.is_dir():
            raise ConfigError(f"El repositorio origen no existe o no es un directorio: {repo}")

        return cls(
            repo_path=repo,
            url=values[ENV_URL].rstrip("/"),
            username=values[ENV_USERNAME],
            password=values[ENV_PASSWORD],
            tenant_name=values[ENV_TENANT],
            dry_run=dry_run,
        )
