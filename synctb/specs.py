"""Descripción REST de cada tipo de entidad que se sincroniza."""

from dataclasses import dataclass, field
from typing import Callable, Dict, Hashable, List, Optional, Tuple


def _name(e: dict) -> Hashable:
    return e.get("name")


@dataclass(frozen=True)
class TypeSpec:
    entity_type: str
    save_path: str
    # Endpoints paginados que devuelven las entidades existentes en el destino
    list_paths: Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...]
    delete_path: Optional[str] = None  # con "{id}"; None = nunca se borra
    # Clave alternativa para emparejar por nombre cuando no coincide id ni externalId
    key: Callable[[dict], Hashable] = _name
    # El listado incluye entidades del sistema: quedarse solo con las del tenant
    tenant_only: bool = False
    # Campos que no se envían al guardar (además de id, createdTime y version)
    strip: Tuple[str, ...] = field(default_factory=tuple)


SPECS: Dict[str, TypeSpec] = {s.entity_type: s for s in [
    TypeSpec("TB_RESOURCE", "/api/resource", (("/api/resource", ()),), "/api/resource/{id}",
             key=lambda e: (e.get("resourceType"), e.get("resourceKey")), tenant_only=True,
             strip=("link", "publicLink")),
    TypeSpec("WIDGET_TYPE", "/api/widgetType", (("/api/widgetTypes", (("tenantOnly", "true"),)),),
             "/api/widgetType/{id}", key=lambda e: e.get("fqn"), tenant_only=True),
    TypeSpec("WIDGETS_BUNDLE", "/api/widgetsBundle", (("/api/widgetsBundles", ()),),
             "/api/widgetsBundle/{id}", key=lambda e: e.get("alias"), tenant_only=True),
    TypeSpec("CUSTOMER", "/api/customer", (("/api/customers", ()),), "/api/customer/{id}",
             key=lambda e: e.get("title")),
    TypeSpec("ROLE", "/api/role", (("/api/roles", ()),), "/api/role/{id}"),
    TypeSpec("RULE_CHAIN", "/api/ruleChain",
             (("/api/ruleChains", (("type", "CORE"),)), ("/api/ruleChains", (("type", "EDGE"),))),
             "/api/ruleChain/{id}", key=lambda e: (e.get("type"), e.get("name")),
             strip=("firstRuleNodeId", "root")),
    TypeSpec("DASHBOARD", "/api/dashboard", (("/api/tenant/dashboards", ()),), "/api/dashboard/{id}",
             key=lambda e: e.get("title")),
    TypeSpec("ASSET_PROFILE", "/api/assetProfile", (("/api/assetProfiles", ()),), "/api/assetProfile/{id}"),
    TypeSpec("DEVICE_PROFILE", "/api/deviceProfile", (("/api/deviceProfiles", ()),), None),
    TypeSpec("CONVERTER", "/api/converter", (("/api/converters", ()),), "/api/converter/{id}"),
    TypeSpec("INTEGRATION", "/api/integration", (("/api/integrations", ()),), "/api/integration/{id}"),
    TypeSpec("ASSET", "/api/asset", (("/api/tenant/assets", ()),), None,
             key=lambda e: (e.get("type"), e.get("name"))),
    TypeSpec("NOTIFICATION_TARGET", "/api/notification/target", (("/api/notification/targets", ()),),
             "/api/notification/target/{id}"),
    TypeSpec("NOTIFICATION_TEMPLATE", "/api/notification/template", (("/api/notification/templates", ()),),
             "/api/notification/template/{id}"),
    TypeSpec("NOTIFICATION_RULE", "/api/notification/rule", (("/api/notification/rules", ()),),
             "/api/notification/rule/{id}"),
]}

# Orden de creación/actualización: cada tipo solo depende de los anteriores.
# Las referencias que aún no se pueden resolver (p. ej. profile -> dashboard) se
# completan en una segunda pasada.
SYNC_ORDER: List[str] = [
    "TB_RESOURCE", "WIDGET_TYPE", "WIDGETS_BUNDLE", "CUSTOMER", "ROLE", "RULE_CHAIN",
    "DASHBOARD", "ASSET_PROFILE", "DEVICE_PROFILE", "CONVERTER", "INTEGRATION",
    "ENTITY_GROUP", "ASSET", "NOTIFICATION_TARGET", "NOTIFICATION_TEMPLATE", "NOTIFICATION_RULE",
]

# Orden de borrado: inverso a las dependencias. Sin ASSET, DEVICE ni DEVICE_PROFILE.
DELETE_ORDER: List[str] = [
    "NOTIFICATION_RULE", "NOTIFICATION_TEMPLATE", "NOTIFICATION_TARGET", "ENTITY_GROUP",
    "INTEGRATION", "CONVERTER", "DASHBOARD", "ASSET_PROFILE", "RULE_CHAIN", "ROLE",
    "CUSTOMER", "WIDGETS_BUNDLE", "WIDGET_TYPE", "TB_RESOURCE",
]

GROUP_TYPES = ["ASSET", "CUSTOMER", "DASHBOARD", "DEVICE", "ENTITY_VIEW", "USER"]
# Grupos del destino que no se borran si tienen miembros (sus miembros no se sincronizan)
PROTECTED_GROUP_TYPES = {"ASSET", "DEVICE", "USER", "ENTITY_VIEW"}

ALWAYS_STRIP = ("id", "createdTime", "version")
