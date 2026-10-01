# synctb

Outil en ligne de commande qui synchronise un tenant **ThingsBoard 4.3 PE** enregistré dans
un dépôt de *Version Control* (déjà cloné en local) avec un tenant d'une instance en service.

- Synchronise tout, sauf les utilisateurs et les devices.
- Parmi les assets, seuls ceux de type `Risque` sont synchronisés. Les assets `Site` ne sont jamais touchés.
- Supprime de la cible ce qui n'existe pas dans la source, sauf les assets, les devices et les device profiles.
- La cible peut être le même tenant que la source ou un autre tenant, sur la même instance ou sur une autre.

Les règles détaillées et les décisions de conception sont décrites dans [PLAN.md](PLAN.md).

## Utilisation

```bash
export TB_URL=https://thingsboard.example.com
export TB_USERNAME=tenant.admin@example.com
export TB_PASSWORD=********
export TB_TENANT="Mon Tenant"

synctb ./chemin/du/depot --dry-run   # affiche ce qui serait fait
synctb ./chemin/du/depot             # applique les modifications
```

| Option | Variable d'environnement | Description |
|---|---|---|
| `repo` | — | Chemin du dépôt VC cloné |
| `--url` | `TB_URL` | URL du ThingsBoard cible |
| `--username` | `TB_USERNAME` | Utilisateur **tenant admin** du tenant cible |
| — | `TB_PASSWORD` | Mot de passe (uniquement par variable d'environnement) |
| `--tenant` | `TB_TENANT` | Nom du tenant cible. S'il ne correspond pas à celui de l'utilisateur, l'exécution s'arrête |
| `--dry-run` | — | Ne modifie rien, trace seulement ce qui serait fait |
| `-v` | — | Log au niveau DEBUG |

Les arguments de la ligne de commande ont la priorité sur les variables d'environnement.

### Journalisation et codes de sortie

Le log est écrit uniquement sur la sortie standard. Il se termine par un résumé par type
d'entité : créés, mis à jour, supprimés, conservés et échecs.

| Code | Signification |
|---|---|
| `0` | Synchronisation terminée sans erreur |
| `1` | Synchronisation terminée, mais au moins une entité a échoué |
| `2` | Configuration incomplète ou invalide |
| `3` | Erreur fatale : connexion, mauvais tenant ou dépôt illisible |

Les avertissements ne changent pas le code de sortie. Exemples d'avertissements : une
référence vers un device absent de la cible, ou une suppression refusée par ThingsBoard.

## Fonctionnement

1. **Lecture du dépôt.** Le dépôt VC est lu, puis filtré : pas d'utilisateurs, pas de devices, assets `Risque` uniquement.
2. **Vérification du tenant.** Connexion en tant que tenant admin et vérification du nom du tenant. Le tenant n'est jamais créé.
3. **Création et mise à jour.** Elles suivent l'ordre des dépendances.
   - Chaque entité est rapprochée de la cible par son `id`, puis par son `externalId`, puis par son nom.
   - Tous les identifiants connus sont réécrits dans le JSON.
   - Les entités créées enregistrent l'id source dans `externalId`, ce qui rend les exécutions suivantes idempotentes.
4. **Seconde passe.** Elle traite les références vers des entités créées plus tard.
5. **Contenu associé.** Métadonnées des rule chains, widgets des bundles, membres et permissions des groupes, relations, attributs `SERVER_SCOPE` et calculated fields.
6. **Suppression.** Ce qui est en trop dans la cible est supprimé, avec des protections : rule chain racine, profile par défaut, groupes « All », customers qui possèdent des assets ou des devices, groupes non vides.

## Développement

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows  (Linux/macOS : source .venv/bin/activate)
pip install -r requirements-dev.txt
pip install -e .
pytest
```

Les tests utilisent un faux ThingsBoard en mémoire (`tests/fakes.py`). Aucune instance réelle n'est nécessaire.

### Organisation du code

| Module | Rôle |
|---|---|
| `synctb/cli.py` | Point d'entrée, arguments, log et codes de sortie |
| `synctb/config.py` | Arguments et variables d'environnement |
| `synctb/model.py` | Représentation des fichiers du dépôt |
| `synctb/repo.py` | Lecture du dépôt VC |
| `synctb/filters.py` | Règles d'exclusion |
| `synctb/api.py` | Accès REST via `tb_pe_client.ThingsboardClient`, mode dry-run |
| `synctb/specs.py` | Endpoints par type, ordre de synchronisation et de suppression |
| `synctb/idmap.py` | Correspondance des identifiants et réécriture des références |
| `synctb/syncer.py` | Orchestration |
| `synctb/report.py` | Compteurs et résumé |

## Build et publication sur Artifactory

```bash
pip install build twine
python -m build --wheel
twine upload --repository-url https://<artifactory>/artifactory/api/pypi/<depot-pypi> dist/*
```

Installation depuis Artifactory :

```bash
pip install synctb --index-url https://<artifactory>/artifactory/api/pypi/<depot-pypi>/simple
```
