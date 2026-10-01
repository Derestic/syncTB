"""Point d'entrée en ligne de commande : `synctb`."""

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

# Codes de sortie, exploitables par la pipeline CI/CD
EXIT_OK = 0            # synchronisation terminée sans erreur
EXIT_SYNC_ERRORS = 1   # synchronisation terminée, mais au moins une entité a échoué
EXIT_CONFIG = 2        # configuration incomplète ou invalide
EXIT_FATAL = 3         # échec de connexion, mauvais tenant ou dépôt illisible


def build_parser():
    parser = argparse.ArgumentParser(
        prog="synctb",
        description="Synchronise un dépôt de Version Control ThingsBoard PE avec un tenant en service.",
        epilog="Le mot de passe est toujours lu dans la variable d'environnement TB_PASSWORD.",
    )
    parser.add_argument("repo", help="Chemin local du dépôt source déjà cloné")
    parser.add_argument("--url", help="URL du ThingsBoard cible (env : TB_URL)")
    parser.add_argument("--username", help="Utilisateur tenant admin du tenant cible (env : TB_USERNAME)")
    parser.add_argument("--tenant", help="Nom du tenant cible, vérifié après la connexion (env : TB_TENANT)")
    parser.add_argument("--dry-run", action="store_true", help="Affiche ce qui serait fait sans modifier la cible")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log au niveau DEBUG")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def setup_logging(verbose: bool) -> None:
    """Log uniquement sur la sortie standard (exécution en pipeline)."""
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )
    # Le client HTTP est très bavard en DEBUG
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
        log.info("Connexion à %s en tant que %s", config.url, config.username)
        api = TbApi.login(config.url, config.username, config.password, dry_run=config.dry_run)
        report = Syncer(api, source, config.tenant_name).run()
    except (RepositoryError, TenantError) as e:
        log.error("%s", e)
        return EXIT_FATAL
    except ApiException as e:
        log.error("Erreur de l'API ThingsBoard : %s", api_error(e))
        return EXIT_FATAL

    report.log_summary(config.dry_run)
    return EXIT_SYNC_ERRORS if report.errors else EXIT_OK
