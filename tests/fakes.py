"""Faux ThingsBoard en mémoire, avec la même interface que synctb.api.TbApi.

Il simule uniquement les endpoints utilisés par synctb et enregistre tous les appels
d'écriture dans `calls` pour que les tests puissent les vérifier.
"""

import copy
import re
import uuid

from tb_pe_client.exceptions import NotFoundException

from synctb.specs import SPECS

TENANT_ID = "11111111-1111-1111-1111-111111111111"

# Endpoint de liste -> type
LIST_PATHS = {path: t for t, spec in SPECS.items() for path, _ in spec.list_paths}
LIST_PATHS["/api/tenant/devices"] = "DEVICE"
# Endpoint d'enregistrement -> type
SAVE_PATHS = {spec.save_path: t for t, spec in SPECS.items()}
SAVE_PATHS["/api/entityGroup"] = "ENTITY_GROUP"
SAVE_PATHS["/api/calculatedField"] = "CALCULATED_FIELD"


class _Resp:
    status = 404
    reason = "Not Found"
    headers = {}
    data = b""

    def getheaders(self):
        return {}


def not_found():
    return NotFoundException(http_resp=_Resp(), body='{"message": "not found"}', data=None)


def uid():
    return str(uuid.uuid4())


def ent(entity_type, entity_uuid=None, **fields):
    """Entité telle que la renvoie l'API."""
    e = {"id": {"entityType": entity_type, "id": entity_uuid or uid()},
         "tenantId": {"entityType": "TENANT", "id": TENANT_ID}}
    e.update(fields)
    return e


class FakeTb:
    def __init__(self, tenant_title="Tenant A", authority="TENANT_ADMIN", tenant_id=TENANT_ID):
        self.tenant_id = tenant_id
        self.tenant_title = tenant_title
        self.authority = authority
        self.dry_run = False
        self.store = {t: {} for t in list(SPECS) + ["DEVICE", "ENTITY_GROUP", "CALCULATED_FIELD"]}
        self.group_members = {}
        self.calls = []  # (méthode, chemin, corps)

    # ---------------------------------------------------- données initiales

    def add(self, entity_type, entity):
        self.store[entity_type][entity["id"]["id"]] = entity
        return entity

    def all(self, entity_type):
        return list(self.store[entity_type].values())

    def posts(self, path_prefix):
        return [b for m, pth, b in self.calls if m == "POST" and pth.startswith(path_prefix)]

    def deletes(self):
        return [pth for m, pth, _ in self.calls if m == "DELETE"]

    # ------------------------------------------------------------ interface API

    def get(self, path, **params):
        if path == "/api/auth/user":
            return {"authority": self.authority, "tenantId": {"entityType": "TENANT", "id": self.tenant_id}}
        if path == f"/api/tenant/{self.tenant_id}":
            return {"id": {"entityType": "TENANT", "id": self.tenant_id}, "title": self.tenant_title}
        m = re.fullmatch(r"/api/entityGroup/([^/]+)/entities", path)
        if m:
            return {"data": [], "totalElements": len(self.group_members.get(m.group(1), [])), "hasNext": False}
        m = re.fullmatch(r"/api/customer/([^/]+)/(assets|devices)", path)
        if m:
            kind = "ASSET" if m.group(2) == "assets" else "DEVICE"
            n = sum(1 for e in self.all(kind) if (e.get("customerId") or {}).get("id") == m.group(1))
            return {"data": [], "totalElements": n, "hasNext": False}
        if re.fullmatch(r"/api/userGroup/[^/]+/groupPermissions", path):
            return []
        m = re.fullmatch(r"/api/entityGroup/([A-Z]+)/([^/]+)/([A-Z_]+)/(.+)", path)
        if m:
            for g in self.all("ENTITY_GROUP"):
                if (g["ownerId"]["id"], g["type"], g["name"]) == (m.group(2), m.group(3), m.group(4)):
                    return g
            raise not_found()
        raise not_found()

    def get_or_none(self, path, **params):
        try:
            return self.get(path, **params)
        except NotFoundException:
            return None

    def get_all(self, path, **params):
        if path in LIST_PATHS:
            items = self.all(LIST_PATHS[path])
            if path == "/api/ruleChains":
                items = [i for i in items if i.get("type", "CORE") == params.get("type")]
            return [copy.deepcopy(i) for i in items]
        m = re.fullmatch(r"/api/entityGroups/([A-Z]+)/([^/]+)/([A-Z_]+)", path)
        if m:
            return [copy.deepcopy(g) for g in self.all("ENTITY_GROUP")
                    if g["ownerId"]["id"] == m.group(2) and g["type"] == m.group(3)]
        m = re.fullmatch(r"/api/calculatedField/[A-Z_]+/([^/]+)", path)
        if m:
            return [copy.deepcopy(cf) for cf in self.all("CALCULATED_FIELD") if cf["entityId"]["id"] == m.group(1)]
        return []

    def post(self, path, body=None, **params):
        self.calls.append(("POST", path, copy.deepcopy(body)))
        if path in SAVE_PATHS:
            entity_type = SAVE_PATHS[path]
            saved = copy.deepcopy(body)
            if "id" not in saved:
                saved["id"] = {"entityType": entity_type, "id": uid()}
            saved["tenantId"] = {"entityType": "TENANT", "id": self.tenant_id}
            return self.add(entity_type, saved)
        m = re.fullmatch(r"/api/entityGroup/([^/]+)/addEntities", path)
        if m:
            self.group_members.setdefault(m.group(1), []).extend(body)
        return body

    def delete(self, path, **params):
        self.calls.append(("DELETE", path, None))
        for store in self.store.values():
            for key in list(store):
                if path.endswith("/" + key):
                    del store[key]
