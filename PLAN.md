# synctb — Plan du projet

`synctb` est un outil en ligne de commande, écrit en Python 3.10, utilisé avec un `.venv` et
empaqueté avec `setup.py`. Il synchronise un tenant ThingsBoard 4.3.0 PE avec un tenant d'une
instance en service. Le tenant source est stocké dans un dépôt git, au format du *Version
Control* natif de ThingsBoard, et ce dépôt est déjà cloné en local.

L'outil est publié sur Artifactory et exécuté dans des pipelines CI/CD. Le log ne s'affiche que sur la console.

## Exigences validées

| Sujet | Décision |
|---|---|
| Format de la source | Dépôt du Version Control natif de TB (un seul tenant) |
| Ce qui est synchronisé | Tout, sauf les utilisateurs et les devices |
| Assets | Uniquement ceux de type `Risque` ; jamais ceux de type `Site` |
| Asset profiles / device profiles | Tous synchronisés, y compris le profile `Site` |
| Identifiants | Même tenant : ils sont conservés. Autre tenant : nouveaux identifiants et références recalculées |
| Assets `Site` | Jamais créés, mis à jour ni supprimés dans la cible : ils stockent des données propres à chaque instance |
| Relations de la source | Créées seulement si les deux extrémités existent dans la cible ; sinon elles sont ignorées (« cassées ») |
| Relations de la cible | Toujours conservées, même si elles ne sont pas dans la source |
| Suppressions | Ce qui n'existe pas dans la source est supprimé de la cible, **sauf** les assets (y compris `Risque`), les devices et les device profiles |
| Tenant cible | Connexion avec un **tenant admin** du tenant cible et vérification que son nom correspond à `--tenant`. Sinon : erreur. Le tenant n'est jamais créé |
| Même tenant ou non | Comparaison du `tenantId` des entités du dépôt avec celui de l'utilisateur connecté |
| Références vers des devices / `Site` dans les dashboards (alias) et les rule chains | Laissées telles quelles, avec un avertissement par référence non résoluble |
| Entity views | Il n'y en a pas ; non gérées |
| Entity groups | Synchronisés, y compris les groupes vides. Seuls les membres synchronisés sont ajoutés. Les devices et assets de la cible ne sont jamais retirés de leurs groupes. Un groupe qui contient des assets ou des devices de la cible n'est jamais supprimé |
| Relation présente dans la source et dans la cible | La source l'emporte (`additionalInfo` écrasé) |
| `calculatedFields` avec références vers des devices / `Site` | Synchronisés tels quels, avec un avertissement par référence |
| Attributs (`SERVER_SCOPE`) | Ceux de la source sont écrits (création ou mise à jour). Ceux qui n'existent que dans la cible sont conservés et jamais supprimés |
| Permissions des groupes d'utilisateurs (`permissions`) | Créées seulement si elles n'existent pas dans la cible ; les permissions existantes ne sont ni modifiées ni supprimées |
| Client REST | `tb-pe-client` (PyPI, 4.3.1.x, Python >= 3.10), classe `tb_pe_client.ThingsboardClient(url, username, password)` |
| Identifiants de connexion | Utilisateur et mot de passe, fournis par des variables d'environnement de la pipeline |
| Journalisation | Sortie standard uniquement |
| Tests | Tests unitaires avec mocks, sans instance réelle |
| Langue | Documentation, commentaires et messages de l'outil en français |

## Décisions d'implémentation (à valider)

Ces décisions ont été prises pendant le développement, sans discussion explicite :

| Sujet | Décision |
|---|---|
| Relations avec des devices | Jamais créées depuis la source, même si le device existe dans la cible (même tenant) |
| Rapprochement par nom | Si ni l'`id` ni l'`externalId` ne correspondent, rapprochement par nom quand il n'y a qu'un seul candidat. Cela couvre la rule chain racine, les profiles par défaut et les groupes créés automatiquement par TB |
| Groupes « All » | Seulement rapprochés ; jamais créés, modifiés ni supprimés |
| Customers | Ni un customer qui possède des assets ou des devices (TB PE les supprimerait en cascade), ni le customer public ne sont supprimés |
| Calculated fields | La source l'emporte. Ceux en trop sont supprimés, sauf sur les assets |
| Intégrations | Si le `routingKey` est déjà utilisé sur l'instance lors de la création, l'intégration est créée avec une nouvelle clé et un avertissement est émis |
| Nœuds des rule chains | Recréés (sans identifiants de nœud) à chaque enregistrement des métadonnées |
| Rule chain racine / profile par défaut | Définis via leurs propres endpoints si la source l'indique |
| Échecs de suppression | Par exemple un profile encore utilisé : enregistrés comme avertissement, pas comme erreur |

## Reste à faire

- Valider les formats avec de vrais fichiers du dépôt VC, en particulier `groups/` et les types propres à PE.
- Tester contre une vraie instance ThingsBoard 4.3.0 PE, d'abord avec `--dry-run`.

## Structure du dépôt source (Version Control)

Chaque dossier final contient un fichier JSON par entité, nommé `<externalId>.json`.

```
asset/  asset_profile/  converter/  customer/  dashboard/  device/  device_profile/
integration/  notification_rule/  notification_target/  notification_template/
role/  rule_chain/  tb_resource/  widget_type/  widget_bundle/
groups/{asset,customer,dashboard,device,entity_view,user}/
hierarchy/<ID>/dashboard/
hierarchy/<ID>/groups/{asset,customer,dashboard,device,entity_view,user}/
```

| Dossier | Traitement |
|---|---|
| `device/` | Ignoré |
| `asset/` | Type `Risque` uniquement |
| `groups/*`, `hierarchy/<ID>/groups/*` | Entity groups (voir les règles des groupes) |
| `hierarchy/<ID>/...` | Entités dont le propriétaire est le customer `<ID>` (customerId / ownerId). Pas d'imbrication |
| `groups/{user,device,entity_view}` | Le groupe est créé même s'il reste vide (ses membres ne sont pas synchronisés) |
| Autres | Synchronisés entièrement |

## Formats JSON (EntityExportData)

**Source.** Ces formats viennent du dépôt officiel `thingsboard/thingsboard` : la classe
`common/data/.../sync/ie/EntityExportData.java` (branche `release-4.3`) et ses sous-classes.

**À valider.** Le code PE 4.3 n'est pas public. Les types propres à PE (groupes, converter,
integration, role) ont été repris de la branche `master`, qui les contient déjà. **Ils
restent à valider avec de vrais fichiers.**

Structure commune à tous les fichiers (confirmée par l'exemple d'`asset_profile`) :

```json
{
  "entityType": "ASSET_PROFILE",
  "entity": { ... },                       // l'entité telle que la renvoie l'API REST (id, externalId, tenantId...)
  "relations": [ EntityRelation ],          // {from:{entityType,id}, to:{entityType,id}, type, typeGroup, additionalInfo}
  "attributes": { "SERVER_SCOPE": [ AttributeExportData ] },
  "calculatedFields": [ CalculatedField ]
}
```

Champs d'un `AttributeExportData` :
- `key` et `lastUpdateTs` ;
- un seul champ de valeur parmi `booleanValue`, `strValue`, `longValue`, `doubleValue` et `jsonValue`.

Champs supplémentaires par type :

| entityType | Champs supplémentaires | Traitement |
|---|---|---|
| `DEVICE` | `credentials` | Ignoré (pas de synchronisation des devices) |
| `RULE_CHAIN` | `metaData` (`firstNodeIndex`, `nodes`, `connections`, `ruleChainConnections`) | La chaîne est enregistrée, puis ses métadonnées |
| `WIDGET_TYPE` | — | `entity` est un `WidgetTypeDetails` |
| `WIDGETS_BUNDLE` | `widgets` (liste de widget types), `fqns` (FQN des widgets) | Les widget types sont associés au bundle par FQN |
| `ENTITY_GROUP` | `permissions` (groupes USER), `groupOtaPackages` (groupes DEVICE), `groupEntities`, `memberIds` (externalIds des membres) | `memberIds` filtré aux entités synchronisées ; `groupOtaPackages` ignoré |
| `DASHBOARD` | — | `entity.configuration.entityAliases` peut contenir des identifiants de devices / `Site` : avertissement |
| `ASSET`, `ASSET_PROFILE`, `DEVICE_PROFILE`, `CUSTOMER`, `TB_RESOURCE`, `NOTIFICATION_*`, `CONVERTER`, `INTEGRATION`, `ROLE` | — | Structure commune uniquement |

## Structure du projet

```
syncTB/
├── setup.py              # paquet « synctb », commande console « synctb »
├── requirements.txt      # tb-pe-client
├── requirements-dev.txt  # + pytest
├── README.md
├── synctb/
│   ├── cli.py            # argparse, log et codes de sortie
│   ├── config.py         # arguments + variables d'environnement
│   ├── model.py          # SourceEntity, SourceRepository, dossiers -> types
│   ├── repo.py           # lecture du dépôt VC
│   ├── filters.py        # exclusion des utilisateurs, devices et assets non « Risque »
│   ├── api.py            # REST brut au-dessus de tb_pe_client.ThingsboardClient (+ dry-run)
│   ├── specs.py          # endpoints par type, ordre de synchronisation et de suppression
│   ├── idmap.py          # table source -> cible et réécriture des UUID dans le JSON
│   ├── syncer.py         # orchestration
│   └── report.py         # compteurs et résumé final
└── tests/                # pytest avec un faux ThingsBoard en mémoire
```

## Déroulement implémenté

1. **Lecture.** Lire le dépôt VC et appliquer les filtres.
2. **Vérification.** Se connecter en tant que tenant admin et vérifier que le nom du tenant correspond à `--tenant`.
3. **Chargement de la cible.** Charger les entités existantes de la cible. Les devices servent uniquement à vérifier les références. Les groupes sont chargés pour chaque propriétaire.
4. **Création et mise à jour**, dans l'ordre des dépendances :
   resources → widget types → bundles → customers → rôles → rule chains → dashboards →
   asset/device profiles → converters → intégrations → entity groups → assets `Risque` →
   notification targets/templates/rules.
   - Rapprochement par `id`, puis `externalId`, puis nom.
   - Réécriture de tous les UUID connus dans le JSON.
   - Les nouvelles entités enregistrent `externalId` = id source.
5. **Seconde passe.** Réenregistrer les entités qui faisaient référence à une entité qui n'existait pas encore.
6. **Contenu associé.**
   - Métadonnées et racine des rule chains.
   - Widgets des bundles.
   - Membres et permissions des groupes.
   - Relations, attributs `SERVER_SCOPE` et calculated fields.
7. **Suppression.** Supprimer ce qui est en trop, dans l'ordre inverse et avec des protections.
8. **Résumé.** Afficher un résumé par type (créés, mis à jour, supprimés, conservés, échecs).
   Codes de sortie : 0 succès, 1 erreurs sur des entités, 2 configuration, 3 erreur fatale.

**Mode `--dry-run`.** Aucune écriture n'est envoyée : chaque écriture est tracée au niveau DEBUG et le traitement continue avec des identifiants fictifs.
