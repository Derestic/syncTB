"""Orchestration de la synchronisation dépôt VC -> tenant cible.

Étapes :
  1. Vérifier que l'utilisateur est tenant admin du tenant indiqué.
  2. Charger ce qui existe déjà dans la cible.
  3. Créer / mettre à jour les entités dans l'ordre des dépendances (SYNC_ORDER), en les
     rapprochant par id, externalId ou nom. Les entités créées enregistrent
     externalId = id source, ce qui permet de les retrouver lors des exécutions suivantes.
  4. Seconde passe pour les références vers des entités qui n'existaient pas encore.
  5. Métadonnées des rule chains, widgets des bundles, membres et permissions des groupes,
     relations, attributs et calculated fields.
  6. Supprimer de la cible ce qui n'est pas dans la source (sauf assets, devices et
     device profiles), avec des protections.

Identifiants :
  - Même tenant que la source : les entités gardent leur id (rapprochement direct).
  - Autre tenant : les entités créées reçoivent un nouvel id, et toutes les références
    sont réécrites grâce à `IdMap`.
"""

import copy
import json
import logging
import uuid
from typing import Dict, List, Optional, Set

from synctb.api import ApiException, TbApi, api_error, p
from synctb.idmap import IdMap
from synctb.model import SourceEntity, SourceRepository, entity_id, ref_id
from synctb.report import Report
from synctb.specs import (ALWAYS_STRIP, DELETE_ORDER, GROUP_TYPES, PROTECTED_GROUP_TYPES, SPECS,
                          SYNC_ORDER)

log = logging.getLogger(__name__)

# Seuls les attributs serveur sont écrits ; ceux qui n'existent que dans la cible sont conservés
WRITABLE_ATTRIBUTE_SCOPES = ("SERVER_SCOPE",)


class TenantError(Exception):
    """L'utilisateur n'est pas tenant admin ou n'appartient pas au tenant attendu."""


def _uid(entity: Optional[dict]) -> Optional[str]:
    """UUID (en minuscules) du champ `id` d'une entité."""
    uid = ref_id(entity.get("id")) if entity else None
    return uid.lower() if uid else None


def _strip(entity: dict, extra=()) -> dict:
    """Copie de l'entité sans les champs propres à l'instance source."""
    body = copy.deepcopy(entity)
    for f in ALWAYS_STRIP + tuple(extra):
        body.pop(f, None)
    return body


def attribute_value(attr: dict):
    """Valeur d'un AttributeExportData (un seul des champs *Value est renseigné)."""
    for field in ("booleanValue", "strValue", "longValue", "doubleValue"):
        if attr.get(field) is not None:
            return attr[field]
    raw = attr.get("jsonValue")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


class Syncer:
    def __init__(self, api: TbApi, source: SourceRepository, tenant_name: str, report: Report = None):
        self.api = api
        self.source = source
        self.tenant_name = tenant_name
        self.report = report or Report()

        self.idmap = IdMap()
        self.tenant_id: Optional[str] = None
        self.same_tenant = False

        # Entités existantes dans la cible, par type
        self.target: Dict[str, List[dict]] = {}
        # Tous les UUID existants dans la cible (pour vérifier les références et les relations)
        self.target_ids: Set[str] = set()
        # source_id -> entité enregistrée / rapprochée dans la cible
        self.matched: Dict[str, dict] = {}
        # UUID de la cible qui correspondent à une entité source (jamais supprimés)
        self.kept_target_ids: Set[str] = set()
        # Entités à réenregistrer lors de la seconde passe
        self.pending: Dict[str, SourceEntity] = {}
        self._second_pass = False

        self._add_embedded_widget_types()
        self.sync_ids = {e.source_id.lower() for e in source.entities}
        self.excluded = {k.lower(): v for k, v in source.excluded.items()}

    # ================================================================== flux

    def run(self) -> Report:
        self.verify_tenant()
        self.load_target()

        for entity_type in SYNC_ORDER:
            for e in self._ordered(entity_type):
                self.save(e)
        self.resave_pending()

        self.sync_rule_chain_metadata()
        self.sync_widget_bundle_fqns()
        self.sync_groups_content()
        self.sync_relations()
        self.sync_attributes()
        self.sync_calculated_fields()
        self.delete_obsolete()
        return self.report

    # ============================================================ tenant / cible

    def verify_tenant(self) -> None:
        """Vérifie l'utilisateur connecté et détermine si la cible est le tenant d'origine.

        Le tenant n'est jamais créé : s'il n'existe pas, la connexion a déjà échoué.
        """
        user = self.api.get("/api/auth/user")
        if user.get("authority") != "TENANT_ADMIN":
            raise TenantError(f"L'utilisateur doit être TENANT_ADMIN, il est {user.get('authority')}")
        self.tenant_id = ref_id(user.get("tenantId")).lower()

        tenant = self.api.get(f"/api/tenant/{p(self.tenant_id)}")
        title = tenant.get("title") or tenant.get("name")
        if title != self.tenant_name:
            raise TenantError(f"L'utilisateur appartient au tenant '{title}', et non à '{self.tenant_name}'")

        source_tenant = self.source.tenant_id
        self.same_tenant = bool(source_tenant) and source_tenant.lower() == self.tenant_id
        # Le tenantId source est remplacé par celui de la cible dans toutes les entités
        if source_tenant:
            self.idmap.set(source_tenant, self.tenant_id)
        log.info("Tenant cible '%s' (%s). %s", title, self.tenant_id,
                 "Même tenant que la source : les identifiants sont conservés" if self.same_tenant
                 else "Tenant différent de la source : les nouvelles entités auront de nouveaux identifiants")

    def load_target(self) -> None:
        """Charge les entités existantes de la cible (y compris devices et groupes de chaque propriétaire)."""
        for entity_type, spec in SPECS.items():
            items = []
            for path, params in spec.list_paths:
                items.extend(self.api.get_all(path, **dict(params)))
            if spec.tenant_only:
                items = [i for i in items if (ref_id(i.get("tenantId")) or "").lower() == self.tenant_id]
            self.target[entity_type] = items

        customers = self.target["CUSTOMER"]
        # Les dashboards appartenant à un customer ne sont pas toujours listés au niveau du tenant
        for c in customers:
            self.target["DASHBOARD"].extend(self.api.get_all(f"/api/customer/{p(_uid(c))}/dashboards"))
        # Les devices ne sont jamais écrits : ils servent seulement à vérifier les références
        self.target["DEVICE"] = list(self.api.get_all("/api/tenant/devices"))

        owners = [("TENANT", self.tenant_id)] + [("CUSTOMER", _uid(c)) for c in customers]
        groups = []
        for owner_type, owner_id in owners:
            for group_type in GROUP_TYPES:
                groups.extend(self.api.get_all(f"/api/entityGroups/{owner_type}/{p(owner_id)}/{group_type}"))
        self.target["ENTITY_GROUP"] = groups

        for entity_type, items in self.target.items():
            unique = {_uid(i): i for i in items if _uid(i)}
            self.target[entity_type] = list(unique.values())
            self.target_ids.update(unique)
            log.info("Cible : %d %s", len(unique), entity_type)

    # =========================================================== rapprochement

    def find_match(self, e: SourceEntity) -> Optional[dict]:
        """Cherche dans la cible l'entité qui correspond à `e`.

        Ordre : entité déjà traitée, même id, externalId = id source, puis clé par nom
        (uniquement s'il y a un seul candidat qui n'est pas déjà rapproché). Le nom permet
        de réutiliser les entités créées automatiquement par ThingsBoard (rule chain racine,
        profiles par défaut, groupes d'un nouveau customer, ...).
        """
        sid = e.source_id.lower()
        if sid in self.matched:
            return self.matched[sid]
        candidates = self.target.get(e.entity_type, [])
        for t in candidates:
            if _uid(t) == sid:
                return t
        for t in candidates:
            if (ref_id(t.get("externalId")) or "").lower() == sid:
                return t

        key = self._key(e.entity_type, e.entity, mapped=True)
        if key is None:
            return None
        found = [t for t in candidates
                 if _uid(t) not in self.kept_target_ids and self._key(e.entity_type, t) == key]
        return found[0] if len(found) == 1 else None

    def _key(self, entity_type: str, entity: dict, mapped: bool = False):
        """Clé de rapprochement par nom. Pour un groupe : (type, propriétaire, nom)."""
        if entity_type == "ENTITY_GROUP":
            owner = ref_id(entity.get("ownerId")) or ""
            if mapped:
                owner = self.idmap.get(owner) or owner
            return entity.get("type"), owner.lower(), entity.get("name")
        key = SPECS[entity_type].key(entity)
        if key is None or (isinstance(key, tuple) and None in key):
            return None
        return key

    # =========================================================== enregistrement

    def save(self, e: SourceEntity) -> None:
        """Crée ou met à jour une entité dans la cible (le contenu de la source l'emporte)."""
        if e.entity_type == "ENTITY_GROUP":
            return self._save_group(e)

        spec = SPECS[e.entity_type]
        target = self.find_match(e)
        unresolved: Set[str] = set()
        body = self.idmap.rewrite(_strip(e.entity, spec.strip), unresolved)
        self._set_identity(e, body, target)

        if e.entity_type in ("ASSET_PROFILE", "DEVICE_PROFILE"):
            # Le profile par défaut se change via son propre endpoint, pas à l'enregistrement
            body["default"] = bool(target and target.get("default"))

        try:
            saved = self._post_entity(e, spec.save_path, body, target)
        except ApiException as ex:
            self._fail(e, "enregistrement", ex)
            return
        self._register(e, saved, created=target is None)
        self._check_unresolved(e, unresolved)

        if e.entity_type in ("ASSET_PROFILE", "DEVICE_PROFILE") and e.entity.get("default") \
                and not saved.get("default"):
            path = "assetProfile" if e.entity_type == "ASSET_PROFILE" else "deviceProfile"
            self._try(e, "définition du profile par défaut",
                      lambda: self.api.post(f"/api/{path}/{p(_uid(saved))}/default"))

    def _post_entity(self, e: SourceEntity, path: str, body: dict, target) -> dict:
        try:
            return self.api.post(path, body)
        except ApiException as ex:
            # Le routingKey d'une intégration est unique sur toute l'instance : si un autre
            # tenant l'utilise déjà, l'intégration est créée avec une nouvelle clé.
            if e.entity_type == "INTEGRATION" and target is None and body.get("routingKey") \
                    and ex.status == 400:
                body["routingKey"] = str(uuid.uuid4())
                self.report.warn("%s : routingKey déjà utilisé, création avec une nouvelle clé (%s)",
                                 e, body["routingKey"])
                return self.api.post(path, body)
            raise

    def _save_group(self, e: SourceEntity) -> None:
        """Enregistre un entity group (ses membres et permissions sont traités plus tard).

        Les groupes « All » sont gérés par ThingsBoard : ils sont seulement rapprochés.
        Les groupes sont créés même s'ils resteront vides (device, user, entity_view).
        """
        src = e.entity
        unresolved: Set[str] = set()
        body = self.idmap.rewrite(_strip(src), unresolved)
        owner = body.get("ownerId") or entity_id("TENANT", self.tenant_id)
        body["ownerId"] = owner

        target = self.find_match(e)
        if target is None:
            # À la création d'un customer, ThingsBoard crée ses groupes par défaut : on les cherche par nom
            try:
                target = self.api.get_or_none(
                    f"/api/entityGroup/{owner['entityType']}/{p(owner['id'])}/{src.get('type')}/{p(src.get('name'))}")
            except ApiException:
                target = None

        if target is not None and (target.get("groupAll") or src.get("groupAll")):
            self._register(e, target, created=False, action="kept")
            return
        if target is None and src.get("groupAll"):
            self.report.warn("%s : groupe 'All' sans équivalent dans la cible, ignoré", e)
            return

        self._set_identity(e, body, target)
        try:
            saved = self.api.post("/api/entityGroup", body)
        except ApiException as ex:
            self._fail(e, "enregistrement", ex)
            return
        self._register(e, saved, created=target is None)
        self._check_unresolved(e, unresolved)

    def _set_identity(self, e: SourceEntity, body: dict, target: Optional[dict]) -> None:
        """Mise à jour : reprend l'id de la cible. Si l'id diffère de la source, mémorise
        l'id source dans externalId pour retrouver l'entité lors de la prochaine exécution."""
        if target is not None:
            body["id"] = target["id"]
        if target is None or _uid(target) != e.source_id.lower():
            body["externalId"] = entity_id(e.entity_type, e.source_id)

    def _register(self, e: SourceEntity, saved: dict, created: bool, action: str = None) -> None:
        """Mémorise la correspondance source -> cible et compte l'action."""
        tid = _uid(saved)
        sid = e.source_id.lower()
        self.idmap.set(sid, tid)
        self.matched[sid] = saved
        self.kept_target_ids.add(tid)
        self.target_ids.add(tid)
        if self._second_pass:
            return
        action = action or ("created" if created else "updated")
        self.report.count(e.entity_type, action)
        if created:
            log.info("Créé %s -> %s", e, tid)
        else:
            log.debug("%s %s -> %s", action, e, tid)

    def _check_unresolved(self, e: SourceEntity, unresolved: Set[str]) -> None:
        """Traite les UUID qui n'ont pas pu être réécrits dans une entité.

        - Entité source pas encore créée : l'entité sera réenregistrée en seconde passe.
        - Entité exclue (device, asset « Site ») absente de la cible : la référence est
          laissée telle quelle et un avertissement est émis.
        - Autres UUID (identifiants internes de widgets, alias, ...) : ignorés.
        """
        for uid in sorted(unresolved):
            if uid in self.sync_ids and uid not in self.idmap:
                if not self._second_pass:
                    self.pending[e.source_id.lower()] = e
                else:
                    self.report.warn("%s fait référence à %s, qui n'a pas pu être synchronisé", e, uid)
            elif uid in self.excluded and uid not in self.target_ids:
                self.report.warn("%s fait référence à %s, qui n'existe pas dans la cible ; référence laissée telle quelle",
                                 e, self.excluded[uid])

    def resave_pending(self) -> None:
        """Seconde passe : réenregistre les entités dont des références sont désormais résolubles."""
        self._second_pass = True
        pending = [e for e in self.pending.values() if e.entity_type != "ENTITY_GROUP"]
        if pending:
            log.info("Seconde passe : %d entités avec des références en attente", len(pending))
        for e in pending:
            self.save(e)

    # ========================================================== étapes finales

    def sync_rule_chain_metadata(self) -> None:
        """Enregistre les nœuds et connexions de chaque rule chain, puis la racine si besoin.

        Les identifiants des nœuds sont retirés : ThingsBoard recrée les nœuds. Les
        connexions référencent les nœuds par leur index, elles restent donc valides.
        """
        for e in self._registered("RULE_CHAIN"):
            chain = self.matched[e.source_id.lower()]
            meta = e.data.get("metaData")
            if meta:
                meta = copy.deepcopy(meta)
                meta.pop("ruleChainId", None)
                meta.pop("version", None)
                for node in meta.get("nodes") or []:
                    for f in ("id", "ruleChainId", "createdTime"):
                        node.pop(f, None)
                unresolved: Set[str] = set()
                meta = self.idmap.rewrite(meta, unresolved)
                meta["ruleChainId"] = chain["id"]
                if self._try(e, "enregistrement des métadonnées",
                             lambda: self.api.post("/api/ruleChain/metadata", meta)):
                    self._check_unresolved(e, unresolved)

            if e.entity.get("root") and not chain.get("root"):
                self._try(e, "définition de la rule chain racine",
                          lambda: self.api.post(f"/api/ruleChain/{p(_uid(chain))}/root"))

    def sync_widget_bundle_fqns(self) -> None:
        """Associe à chaque bundle ses widget types, identifiés par leur FQN."""
        for e in self._registered("WIDGETS_BUNDLE"):
            fqns = e.data.get("fqns") or [w.get("fqn") for w in e.data.get("widgets") or [] if w.get("fqn")]
            if fqns:
                bundle_id = _uid(self.matched[e.source_id.lower()])
                self._try(e, "association des widgets",
                          lambda: self.api.post(f"/api/widgetsBundle/{p(bundle_id)}/widgetTypeFqns", fqns))

    def sync_groups_content(self) -> None:
        """Ajoute les membres synchronisés aux groupes et crée les permissions manquantes.

        Seuls les membres synchronisés (assets « Risque », customers, dashboards, ...) sont
        ajoutés. Aucun membre n'est jamais retiré : les devices et assets de la cible
        restent dans leurs groupes.
        """
        for e in self._registered("ENTITY_GROUP"):
            group = self.matched[e.source_id.lower()]
            if group.get("groupAll"):
                continue
            gid = _uid(group)

            members = [self.idmap.get(m) for m in e.member_ids
                       if m.lower() in self.sync_ids and m in self.idmap]
            if members:
                if self._try(e, "ajout des membres",
                             lambda: self.api.post(f"/api/entityGroup/{p(gid)}/addEntities", members)):
                    self.report.count("GROUP_MEMBER", "created", len(members))

            if e.entity.get("type") == "USER" and e.data.get("permissions"):
                self._sync_permissions(e, gid, e.data["permissions"])

    def _sync_permissions(self, e: SourceEntity, gid: str, permissions: List[dict]) -> None:
        """Crée les permissions d'un groupe d'utilisateurs qui n'existent pas encore.

        Une permission est identifiée par (rôle, groupe d'entités). Les permissions
        existantes ne sont ni modifiées ni supprimées.
        """
        try:
            existing = self.api.get(f"/api/userGroup/{p(gid)}/groupPermissions") or []
        except ApiException:
            existing = []
        keys = {(ref_id(x.get("roleId")), ref_id(x.get("entityGroupId"))) for x in existing}

        for perm in permissions:
            unresolved: Set[str] = set()
            body = self.idmap.rewrite(_strip(perm, ("userGroupId", "tenantId")), unresolved)
            role, group = ref_id(body.get("roleId")), ref_id(body.get("entityGroupId"))
            if (role and role.lower() in unresolved) or (group and group.lower() in unresolved):
                self.report.warn("%s : permission ignorée, le rôle ou le groupe n'existe pas dans la cible (%s)",
                                 e, perm)
                continue
            if (role, group) in keys:
                self.report.count("GROUP_PERMISSION", "kept")
                continue
            body["userGroupId"] = entity_id("ENTITY_GROUP", gid)
            if self._try(e, "création de la permission", lambda: self.api.post("/api/groupPermission", body)):
                self.report.count("GROUP_PERMISSION", "created")

    def sync_relations(self) -> None:
        """Crée les relations de la source dont les deux extrémités existent dans la cible.

        - Les relations avec des devices ne sont jamais créées : les assets synchronisés
          n'ont pas de relation avec des devices.
        - Les relations dont une extrémité n'existe pas sont ignorées (« cassées »).
        - Les relations qui n'existent que dans la cible sont conservées.
        - Si la relation existe déjà, la source l'emporte (additionalInfo écrasé).
        """
        seen = set()
        broken = 0
        for e in self._registered():
            for r in e.relations:
                src_from, src_to = r.get("from") or {}, r.get("to") or {}
                # Une même relation apparaît dans le fichier de ses deux extrémités
                key = (ref_id(src_from), ref_id(src_to), r.get("type"), r.get("typeGroup"))
                if key in seen:
                    continue
                seen.add(key)

                if "DEVICE" in (src_from.get("entityType"), src_to.get("entityType")):
                    broken += 1
                    continue
                from_id, to_id = self._resolve(src_from), self._resolve(src_to)
                if not from_id or not to_id:
                    broken += 1
                    log.debug("Relation cassée (une extrémité n'existe pas dans la cible) : %s", r)
                    continue

                body = {
                    "from": entity_id(src_from.get("entityType"), from_id),
                    "to": entity_id(src_to.get("entityType"), to_id),
                    "type": r.get("type"),
                    "typeGroup": r.get("typeGroup") or "COMMON",
                    "additionalInfo": self.idmap.rewrite(r.get("additionalInfo")),
                }
                if self._try(e, "enregistrement de la relation", lambda: self.api.post("/api/v2/relation", body)):
                    self.report.count("RELATION", "updated")
        if broken:
            log.info("Relations de la source ignorées (extrémité inexistante ou device) : %d", broken)

    def _resolve(self, ref: dict) -> Optional[str]:
        """UUID cible d'une extrémité de relation, ou None si elle n'existe pas dans la cible."""
        uid = (ref_id(ref) or "").lower()
        if not uid:
            return None
        if uid in self.idmap:
            return self.idmap.get(uid)
        return uid if uid in self.target_ids else None

    def sync_attributes(self) -> None:
        """Écrit les attributs SERVER_SCOPE de la source (création ou mise à jour).

        Les attributs qui n'existent que dans la cible sont conservés.
        """
        for e in self._registered():
            tid = _uid(self.matched[e.source_id.lower()])
            for scope, items in e.attributes.items():
                if scope not in WRITABLE_ATTRIBUTE_SCOPES or not items:
                    continue
                values = {a["key"]: attribute_value(a) for a in items if a.get("key")}
                values = self.idmap.rewrite(values)
                path = f"/api/plugins/telemetry/{e.entity_type}/{p(tid)}/attributes/{scope}"
                if self._try(e, "enregistrement des attributs", lambda: self.api.post(path, values)):
                    self.report.count("ATTRIBUTE", "updated", len(values))

    def sync_calculated_fields(self) -> None:
        """Synchronise les calculated fields de chaque entité, rapprochés par nom.

        La source l'emporte. Les calculated fields en trop sont supprimés, sauf sur les
        assets, dont le contenu propre à la cible est conservé. Les références vers des
        devices ou des « Site » sont laissées telles quelles avec un avertissement.
        """
        for e in self._registered():
            if not e.calculated_fields:
                continue
            tid = _uid(self.matched[e.source_id.lower()])
            try:
                existing = {cf.get("name"): cf for cf in
                            self.api.get_all(f"/api/calculatedField/{e.entity_type}/{p(tid)}")}
            except ApiException:
                existing = {}

            for cf in e.calculated_fields:
                unresolved: Set[str] = set()
                body = self.idmap.rewrite(_strip(cf), unresolved)
                body["entityId"] = entity_id(e.entity_type, tid)
                match = existing.pop(cf.get("name"), None)
                if match:
                    body["id"] = match["id"]
                if self._try(e, f"enregistrement du calculated field '{cf.get('name')}'",
                             lambda: self.api.post("/api/calculatedField", body)):
                    self.report.count("CALCULATED_FIELD", "updated" if match else "created")
                    self._check_unresolved(e, unresolved)

            if e.entity_type != "ASSET":
                for cf in existing.values():
                    if self._try(e, f"suppression du calculated field '{cf.get('name')}'",
                                 lambda: self.api.delete(f"/api/calculatedField/{p(_uid(cf))}")):
                        self.report.count("CALCULATED_FIELD", "deleted")

    # ============================================================== suppression

    def delete_obsolete(self) -> None:
        """Supprime de la cible les entités absentes de la source, dans l'ordre inverse des dépendances.

        Les assets, devices et device profiles ne sont jamais supprimés (absents de DELETE_ORDER).
        Un échec de suppression (par ex. profile encore utilisé) est un avertissement, pas une erreur.
        """
        for entity_type in DELETE_ORDER:
            path = SPECS[entity_type].delete_path if entity_type in SPECS else "/api/entityGroup/{id}"
            for t in self.target.get(entity_type, []):
                tid = _uid(t)
                if tid in self.kept_target_ids:
                    continue
                label = f"{entity_type} '{t.get('name') or t.get('title')}' [{tid}]"
                reason = self._protected(entity_type, t)
                if reason:
                    log.info("Conservé %s : %s", label, reason)
                    self.report.count(entity_type, "kept")
                    continue
                try:
                    self.api.delete(path.format(id=p(tid)))
                except ApiException as ex:
                    self.report.warn("Impossible de supprimer %s : %s", label, api_error(ex))
                    continue
                log.info("Supprimé %s", label)
                self.report.count(entity_type, "deleted")

    def _protected(self, entity_type: str, t: dict) -> Optional[str]:
        """Raison de ne pas supprimer une entité de la cible, ou None si elle peut l'être."""
        tid = _uid(t)
        if entity_type == "RULE_CHAIN" and t.get("root"):
            return "c'est la rule chain racine"
        if entity_type == "ASSET_PROFILE" and t.get("default"):
            return "c'est l'asset profile par défaut"
        if entity_type == "CUSTOMER":
            if t.get("isPublic") or (t.get("additionalInfo") or {}).get("isPublic"):
                return "c'est le customer public"
            # ThingsBoard PE supprimerait en cascade les entités appartenant au customer
            for kind in ("assets", "devices"):
                if self._count(f"/api/customer/{p(tid)}/{kind}"):
                    return f"il possède des {kind} (ils seraient supprimés avec lui)"
        if entity_type == "ENTITY_GROUP":
            if t.get("groupAll"):
                return "c'est un groupe 'All'"
            if t.get("type") in PROTECTED_GROUP_TYPES and self._count(f"/api/entityGroup/{p(tid)}/entities"):
                return "il contient des entités de la cible"
        return None

    def _count(self, path: str) -> int:
        """Nombre d'éléments d'un endpoint paginé (une seule page de taille 1)."""
        try:
            page = self.api.get(path, pageSize=1, page=0)
        except ApiException:
            return 1  # dans le doute, ne pas supprimer
        return page.get("totalElements", len(page.get("data", []))) if isinstance(page, dict) else len(page)

    # ================================================================ utilitaires

    def _ordered(self, entity_type: str) -> List[SourceEntity]:
        entities = self.source.of_type(entity_type)
        if entity_type == "CUSTOMER":
            # D'abord les customers dont le propriétaire est le tenant
            entities.sort(key=lambda c: (c.entity.get("ownerId") or {}).get("entityType") == "CUSTOMER")
        return entities

    def _registered(self, entity_type: str = None) -> List[SourceEntity]:
        """Entités source correctement enregistrées ou rapprochées dans la cible."""
        return [e for e in self.source.entities
                if e.source_id.lower() in self.matched and (entity_type is None or e.entity_type == entity_type)]

    def _try(self, e: SourceEntity, what: str, fn) -> bool:
        """Exécute un appel API ; en cas d'échec, enregistre l'erreur et continue."""
        try:
            fn()
            return True
        except ApiException as ex:
            self._fail(e, what, ex)
            return False

    def _fail(self, e: SourceEntity, what: str, ex: ApiException) -> None:
        self.report.count(e.entity_type, "failed")
        self.report.error("Échec (%s) pour %s : %s", what, e, api_error(ex))

    def _add_embedded_widget_types(self) -> None:
        """Les bundles contiennent leurs widgets : on ajoute ceux absents du dossier widget_type/."""
        known = {e.entity.get("fqn") for e in self.source.of_type("WIDGET_TYPE")}
        for bundle in self.source.of_type("WIDGETS_BUNDLE"):
            for w in bundle.data.get("widgets") or []:
                wid = ref_id(w.get("id"))
                if w.get("fqn") and w["fqn"] not in known and wid:
                    known.add(w["fqn"])
                    self.source.entities.append(
                        SourceEntity("WIDGET_TYPE", wid, bundle.path, {"entityType": "WIDGET_TYPE", "entity": w}))
