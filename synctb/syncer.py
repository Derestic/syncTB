"""Orquestación de la sincronización repo VC -> tenant destino.

Pasos:
  1. Verificar que el usuario es tenant admin del tenant indicado.
  2. Cargar lo que ya existe en el destino.
  3. Crear/actualizar entidades en orden de dependencias (SYNC_ORDER), emparejando
     por id, externalId o nombre. Las creadas guardan externalId = id de origen.
  4. Segunda pasada para las referencias a entidades que aún no existían.
  5. Metadata de rule chains, widgets de bundles, miembros y permisos de grupos,
     relaciones, atributos y calculated fields.
  6. Borrar del destino lo que no está en el origen (salvo assets, devices y device profiles).
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

WRITABLE_ATTRIBUTE_SCOPES = ("SERVER_SCOPE",)


class TenantError(Exception):
    pass


def _uid(entity: Optional[dict]) -> Optional[str]:
    uid = ref_id(entity.get("id")) if entity else None
    return uid.lower() if uid else None


def _strip(entity: dict, extra=()) -> dict:
    body = copy.deepcopy(entity)
    for f in ALWAYS_STRIP + tuple(extra):
        body.pop(f, None)
    return body


def attribute_value(attr: dict):
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

        self.target: Dict[str, List[dict]] = {}
        self.target_ids: Set[str] = set()
        # source_id -> entidad guardada/emparejada en el destino
        self.matched: Dict[str, dict] = {}
        # IDs del destino que corresponden a algo del origen (no se borran)
        self.kept_target_ids: Set[str] = set()
        self.pending: Dict[str, SourceEntity] = {}
        self._second_pass = False

        self._add_embedded_widget_types()
        self.sync_ids = {e.source_id.lower() for e in source.entities}
        self.excluded = {k.lower(): v for k, v in source.excluded.items()}

    # ================================================================== flujo

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

    # ============================================================ tenant/destino

    def verify_tenant(self) -> None:
        user = self.api.get("/api/auth/user")
        if user.get("authority") != "TENANT_ADMIN":
            raise TenantError(f"El usuario debe ser TENANT_ADMIN y es {user.get('authority')}")
        self.tenant_id = ref_id(user.get("tenantId")).lower()

        tenant = self.api.get(f"/api/tenant/{p(self.tenant_id)}")
        title = tenant.get("title") or tenant.get("name")
        if title != self.tenant_name:
            raise TenantError(f"El usuario pertenece al tenant '{title}', no a '{self.tenant_name}'")

        source_tenant = self.source.tenant_id
        self.same_tenant = bool(source_tenant) and source_tenant.lower() == self.tenant_id
        if source_tenant:
            self.idmap.set(source_tenant, self.tenant_id)
        log.info("Tenant destino '%s' (%s). %s", title, self.tenant_id,
                 "Mismo tenant que el origen: se conservan los IDs" if self.same_tenant
                 else "Tenant distinto al origen: las entidades nuevas tendrán IDs nuevos")

    def load_target(self) -> None:
        for entity_type, spec in SPECS.items():
            items = []
            for path, params in spec.list_paths:
                items.extend(self.api.get_all(path, **dict(params)))
            if spec.tenant_only:
                items = [i for i in items if (ref_id(i.get("tenantId")) or "").lower() == self.tenant_id]
            self.target[entity_type] = items

        customers = self.target["CUSTOMER"]
        for c in customers:
            self.target["DASHBOARD"].extend(self.api.get_all(f"/api/customer/{p(_uid(c))}/dashboards"))
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
            log.info("Destino: %d %s", len(unique), entity_type)

    # ================================================================ emparejado

    def find_match(self, e: SourceEntity) -> Optional[dict]:
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
        if entity_type == "ENTITY_GROUP":
            owner = ref_id(entity.get("ownerId")) or ""
            if mapped:
                owner = self.idmap.get(owner) or owner
            return entity.get("type"), owner.lower(), entity.get("name")
        key = SPECS[entity_type].key(entity)
        if key is None or (isinstance(key, tuple) and None in key):
            return None
        return key

    # =================================================================== guardado

    def save(self, e: SourceEntity) -> None:
        if e.entity_type == "ENTITY_GROUP":
            return self._save_group(e)

        spec = SPECS[e.entity_type]
        target = self.find_match(e)
        unresolved: Set[str] = set()
        body = self.idmap.rewrite(_strip(e.entity, spec.strip), unresolved)
        self._set_identity(e, body, target)

        if e.entity_type in ("ASSET_PROFILE", "DEVICE_PROFILE"):
            # El profile por defecto se cambia con su endpoint propio, no al guardar
            body["default"] = bool(target and target.get("default"))

        try:
            saved = self._post_entity(e, spec.save_path, body, target)
        except ApiException as ex:
            self._fail(e, "guardar", ex)
            return
        self._register(e, saved, created=target is None)
        self._check_unresolved(e, unresolved)

        if e.entity_type in ("ASSET_PROFILE", "DEVICE_PROFILE") and e.entity.get("default") \
                and not saved.get("default"):
            path = "assetProfile" if e.entity_type == "ASSET_PROFILE" else "deviceProfile"
            self._try(e, "marcar como profile por defecto",
                      lambda: self.api.post(f"/api/{path}/{p(_uid(saved))}/default"))

    def _post_entity(self, e: SourceEntity, path: str, body: dict, target) -> dict:
        try:
            return self.api.post(path, body)
        except ApiException as ex:
            # El routingKey de una integración es único en toda la instancia: si otro tenant
            # ya lo usa, se crea con uno nuevo.
            if e.entity_type == "INTEGRATION" and target is None and body.get("routingKey") \
                    and ex.status == 400:
                body["routingKey"] = str(uuid.uuid4())
                self.report.warn("%s: routingKey en uso, se crea con uno nuevo (%s)", e, body["routingKey"])
                return self.api.post(path, body)
            raise

    def _save_group(self, e: SourceEntity) -> None:
        src = e.entity
        unresolved: Set[str] = set()
        body = self.idmap.rewrite(_strip(src), unresolved)
        owner = body.get("ownerId") or entity_id("TENANT", self.tenant_id)
        body["ownerId"] = owner

        target = self.find_match(e)
        if target is None:
            # Al crear un customer, ThingsBoard crea sus grupos por defecto: se buscan por nombre
            try:
                target = self.api.get_or_none(
                    f"/api/entityGroup/{owner['entityType']}/{p(owner['id'])}/{src.get('type')}/{p(src.get('name'))}")
            except ApiException:
                target = None

        if target is not None and (target.get("groupAll") or src.get("groupAll")):
            # Los grupos "All" los gestiona ThingsBoard: solo se emparejan
            self._register(e, target, created=False, action="kept")
            return
        if target is None and src.get("groupAll"):
            self.report.warn("%s: grupo 'All' sin equivalente en el destino, se omite", e)
            return

        self._set_identity(e, body, target)
        try:
            saved = self.api.post("/api/entityGroup", body)
        except ApiException as ex:
            self._fail(e, "guardar", ex)
            return
        self._register(e, saved, created=target is None)
        self._check_unresolved(e, unresolved)

    def _set_identity(self, e: SourceEntity, body: dict, target: Optional[dict]) -> None:
        if target is not None:
            body["id"] = target["id"]
        if target is None or _uid(target) != e.source_id.lower():
            body["externalId"] = entity_id(e.entity_type, e.source_id)

    def _register(self, e: SourceEntity, saved: dict, created: bool, action: str = None) -> None:
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
            log.info("Creado %s -> %s", e, tid)
        else:
            log.debug("%s %s -> %s", action, e, tid)

    def _check_unresolved(self, e: SourceEntity, unresolved: Set[str]) -> None:
        for uid in sorted(unresolved):
            if uid in self.sync_ids and uid not in self.idmap:
                if not self._second_pass:
                    self.pending[e.source_id.lower()] = e
                else:
                    self.report.warn("%s referencia a %s, que no se ha podido sincronizar", e, uid)
            elif uid in self.excluded and uid not in self.target_ids:
                self.report.warn("%s referencia a %s, que no existe en el destino; se deja tal cual",
                                 e, self.excluded[uid])

    def resave_pending(self) -> None:
        self._second_pass = True
        pending = [e for e in self.pending.values() if e.entity_type != "ENTITY_GROUP"]
        if pending:
            log.info("Segunda pasada: %d entidades con referencias pendientes", len(pending))
        for e in pending:
            self.save(e)

    # ============================================================ pasos finales

    def sync_rule_chain_metadata(self) -> None:
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
                if self._try(e, "guardar metadata", lambda: self.api.post("/api/ruleChain/metadata", meta)):
                    self._check_unresolved(e, unresolved)

            if e.entity.get("root") and not chain.get("root"):
                self._try(e, "marcar como rule chain raíz",
                          lambda: self.api.post(f"/api/ruleChain/{p(_uid(chain))}/root"))

    def sync_widget_bundle_fqns(self) -> None:
        for e in self._registered("WIDGETS_BUNDLE"):
            fqns = e.data.get("fqns") or [w.get("fqn") for w in e.data.get("widgets") or [] if w.get("fqn")]
            if fqns:
                bundle_id = _uid(self.matched[e.source_id.lower()])
                self._try(e, "asignar widgets",
                          lambda: self.api.post(f"/api/widgetsBundle/{p(bundle_id)}/widgetTypeFqns", fqns))

    def sync_groups_content(self) -> None:
        for e in self._registered("ENTITY_GROUP"):
            group = self.matched[e.source_id.lower()]
            if group.get("groupAll"):
                continue
            gid = _uid(group)

            members = [self.idmap.get(m) for m in e.data.get("memberIds") or []
                       if m and m.lower() in self.sync_ids and m in self.idmap]
            if members:
                if self._try(e, "añadir miembros",
                             lambda: self.api.post(f"/api/entityGroup/{p(gid)}/addEntities", members)):
                    self.report.count("GROUP_MEMBER", "created", len(members))

            if e.entity.get("type") == "USER" and e.data.get("permissions"):
                self._sync_permissions(e, gid, e.data["permissions"])

    def _sync_permissions(self, e: SourceEntity, gid: str, permissions: List[dict]) -> None:
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
                self.report.warn("%s: permiso omitido, el rol o el grupo destino no existe (%s)", e, perm)
                continue
            if (role, group) in keys:
                self.report.count("GROUP_PERMISSION", "kept")
                continue
            body["userGroupId"] = entity_id("ENTITY_GROUP", gid)
            if self._try(e, "crear permiso", lambda: self.api.post("/api/groupPermission", body)):
                self.report.count("GROUP_PERMISSION", "created")

    def sync_relations(self) -> None:
        seen = set()
        broken = 0
        for e in self._registered():
            for r in e.relations:
                src_from, src_to = r.get("from") or {}, r.get("to") or {}
                key = (ref_id(src_from), ref_id(src_to), r.get("type"), r.get("typeGroup"))
                if key in seen:
                    continue
                seen.add(key)

                # Los assets sincronizados no se relacionan con devices
                if "DEVICE" in (src_from.get("entityType"), src_to.get("entityType")):
                    broken += 1
                    continue
                from_id, to_id = self._resolve(src_from), self._resolve(src_to)
                if not from_id or not to_id:
                    broken += 1
                    log.debug("Relación rota (algún extremo no existe en el destino): %s", r)
                    continue

                body = {
                    "from": entity_id(src_from.get("entityType"), from_id),
                    "to": entity_id(src_to.get("entityType"), to_id),
                    "type": r.get("type"),
                    "typeGroup": r.get("typeGroup") or "COMMON",
                    "additionalInfo": self.idmap.rewrite(r.get("additionalInfo")),
                }
                if self._try(e, "guardar relación", lambda: self.api.post("/api/v2/relation", body)):
                    self.report.count("RELATION", "updated")
        if broken:
            log.info("Relaciones del origen descartadas (extremo inexistente o device): %d", broken)

    def _resolve(self, ref: dict) -> Optional[str]:
        uid = (ref_id(ref) or "").lower()
        if not uid:
            return None
        if uid in self.idmap:
            return self.idmap.get(uid)
        return uid if uid in self.target_ids else None

    def sync_attributes(self) -> None:
        for e in self._registered():
            tid = _uid(self.matched[e.source_id.lower()])
            for scope, items in e.attributes.items():
                if scope not in WRITABLE_ATTRIBUTE_SCOPES or not items:
                    continue
                values = {a["key"]: attribute_value(a) for a in items if a.get("key")}
                values = self.idmap.rewrite(values)
                path = f"/api/plugins/telemetry/{e.entity_type}/{p(tid)}/attributes/{scope}"
                if self._try(e, "guardar atributos", lambda: self.api.post(path, values)):
                    self.report.count("ATTRIBUTE", "updated", len(values))

    def sync_calculated_fields(self) -> None:
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
                if self._try(e, f"guardar calculated field '{cf.get('name')}'",
                             lambda: self.api.post("/api/calculatedField", body)):
                    self.report.count("CALCULATED_FIELD", "updated" if match else "created")
                    self._check_unresolved(e, unresolved)

            # Los calculated fields de assets del destino se conservan como el resto de su contenido
            if e.entity_type != "ASSET":
                for cf in existing.values():
                    if self._try(e, f"borrar calculated field '{cf.get('name')}'",
                                 lambda: self.api.delete(f"/api/calculatedField/{p(_uid(cf))}")):
                        self.report.count("CALCULATED_FIELD", "deleted")

    # =================================================================== borrado

    def delete_obsolete(self) -> None:
        for entity_type in DELETE_ORDER:
            path = SPECS[entity_type].delete_path if entity_type in SPECS else "/api/entityGroup/{id}"
            for t in self.target.get(entity_type, []):
                tid = _uid(t)
                if tid in self.kept_target_ids:
                    continue
                label = f"{entity_type} '{t.get('name') or t.get('title')}' [{tid}]"
                reason = self._protected(entity_type, t)
                if reason:
                    log.info("Se mantiene %s: %s", label, reason)
                    self.report.count(entity_type, "kept")
                    continue
                try:
                    self.api.delete(path.format(id=p(tid)))
                except ApiException as ex:
                    self.report.warn("No se puede borrar %s: %s", label, api_error(ex))
                    continue
                log.info("Borrado %s", label)
                self.report.count(entity_type, "deleted")

    def _protected(self, entity_type: str, t: dict) -> Optional[str]:
        tid = _uid(t)
        if entity_type == "RULE_CHAIN" and t.get("root"):
            return "es la rule chain raíz"
        if entity_type == "ASSET_PROFILE" and t.get("default"):
            return "es el asset profile por defecto"
        if entity_type == "CUSTOMER":
            if t.get("isPublic") or (t.get("additionalInfo") or {}).get("isPublic"):
                return "es el customer público"
            for kind in ("assets", "devices"):
                if self._count(f"/api/customer/{p(tid)}/{kind}"):
                    return f"tiene {kind} (se borrarían con él)"
        if entity_type == "ENTITY_GROUP":
            if t.get("groupAll"):
                return "es un grupo 'All'"
            if t.get("type") in PROTECTED_GROUP_TYPES and self._count(f"/api/entityGroup/{p(tid)}/entities"):
                return "contiene entidades del destino"
        return None

    def _count(self, path: str) -> int:
        try:
            page = self.api.get(path, pageSize=1, page=0)
        except ApiException:
            return 1  # ante la duda, no borrar
        return page.get("totalElements", len(page.get("data", []))) if isinstance(page, dict) else len(page)

    # ================================================================== utilidades

    def _ordered(self, entity_type: str) -> List[SourceEntity]:
        entities = self.source.of_type(entity_type)
        if entity_type == "CUSTOMER":
            # Primero los customers cuyo owner es el tenant
            entities.sort(key=lambda c: (c.entity.get("ownerId") or {}).get("entityType") == "CUSTOMER")
        return entities

    def _registered(self, entity_type: str = None) -> List[SourceEntity]:
        return [e for e in self.source.entities
                if e.source_id.lower() in self.matched and (entity_type is None or e.entity_type == entity_type)]

    def _try(self, e: SourceEntity, what: str, fn) -> bool:
        try:
            fn()
            return True
        except ApiException as ex:
            self._fail(e, what, ex)
            return False

    def _fail(self, e: SourceEntity, what: str, ex: ApiException) -> None:
        self.report.count(e.entity_type, "failed")
        self.report.error("Error al %s %s: %s", what, e, api_error(ex))

    def _add_embedded_widget_types(self) -> None:
        """Los bundles incluyen sus widgets; se añaden los que no están en widget_type/."""
        known = {e.entity.get("fqn") for e in self.source.of_type("WIDGET_TYPE")}
        for bundle in self.source.of_type("WIDGETS_BUNDLE"):
            for w in bundle.data.get("widgets") or []:
                wid = ref_id(w.get("id"))
                if w.get("fqn") and w["fqn"] not in known and wid:
                    known.add(w["fqn"])
                    self.source.entities.append(
                        SourceEntity("WIDGET_TYPE", wid, bundle.path, {"entityType": "WIDGET_TYPE", "entity": w}))

