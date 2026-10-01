"""Punto de entrada de consola: `synctb`."""

import argparse
import logging
import sys

from synctb import __version__
from synctb.api import ApiException, TbApi, api_error
from synctb.config import Config, ConfigError
from synctb.filters import apply_filters
from synctb.repo import RepositoryError, load_repository
from synctb.syncer import Syncer, TenantError

log = logging.getLogger("synctb")

EXIT_OK = 0
EXIT_SYNC_ERRORS = 1
EXIT_CONFIG = 2
EXIT_FATAL = 3


def build_parser():
    parser = argparse.ArgumentParser(
        prog="synctb",
        description="Sincroniza un repositorio de Version Control de ThingsBoard PE con un tenant en marcha.",
        epilog="La contraseña se lee siempre de la variable de entorno TB_PASSWORD.",
    )
    parser.add_argument("repo", help="Ruta local del repositorio origen ya clonado")
    parser.add_argument("--url", help="URL del ThingsBoard destino (env: TB_URL)")
    parser.add_argument("--username", help="Usuario tenant admin del tenant destino (env: TB_USERNAME)")
    parser.add_argument("--tenant", help="Nombre del tenant destino; se valida tras el login (env: TB_TENANT)")
    parser.add_argument("--dry-run", action="store_true", help="Muestra lo que se haría sin modificar el destino")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log en nivel DEBUG")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )
    # El cliente HTTP es muy verboso en DEBUG
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    try:
        config = Config.build(args.repo, url=args.url, username=args.username,
                              tenant_name=args.tenant, dry_run=args.dry_run)
    except ConfigError as e:
        log.error("%s", e)
        return EXIT_CONFIG

    try:
        source = apply_filters(load_repository(config.repo_path))
        log.info("Conectando a %s como %s", config.url, config.username)
        api = TbApi.login(config.url, config.username, config.password, dry_run=config.dry_run)
        report = Syncer(api, source, config.tenant_name).run()
    except (RepositoryError, TenantError) as e:
        log.error("%s", e)
        return EXIT_FATAL
    except ApiException as e:
        log.error("Error de la API de ThingsBoard: %s", api_error(e))
        return EXIT_FATAL

    report.log_summary(config.dry_run)
    return EXIT_SYNC_ERRORS if report.errors else EXIT_OK
