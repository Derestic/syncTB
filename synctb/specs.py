"""Description REST de chaque type d'entité synchronisé et ordres de traitement.

Les ENTITY_GROUP n'apparaissent pas dans SPECS : leurs listes dépendent du propriétaire
(tenant ou customer) et ils sont traités à part dans `syncer`.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, Hashable, List, Optional, Tuple


def _name(e: dict) -> Hashable:
    return e.get("name")


@dataclass(frozen=True)
class TypeSpec:
    entity_type: str
    # Endpoint de création / mise à jour (POST)
    save_path: str
    # Endpoints paginés renvoyant les entités existantes dans la cible : ((chemin, paramètres), ...)
    list_paths: Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...]
    # Endpoint de suppression avec « {id} » ; None = jamais supprimé
    delete_path: Optional[str] = None
    # Clé de rapprochement par nom, utilisée quand ni l'id ni l'externalId ne correspondent
    key: Callable[[dict], Hashable] = _name
    # La liste contient aussi des entités système : ne garder que celles du tenant
    tenant_only: bool = False
    # Champs à ne pas envoyer lors de l'enregistrement (en plus de ALWAYS_STRIP)
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
             # La racine et le premier nœud sont gérés par leurs propres endpoints
             strip=("firstRuleNodeId", "root")),
    TypeSpec("DASHBOARD", "/api/dashboard", (("/api/tenant/dashboards", ()),), "/api/dashboard/{id}",
             key=lambda e: e.get("title")),
    TypeSpec("ASSET_PROFILE", "/api/assetProfile", (("/api/assetProfiles", ()),), "/api/assetProfile/{id}"),
    # Les device profiles de la cible ne sont jamais supprimés
    TypeSpec("DEVICE_PROFILE", "/api/deviceProfile", (("/api/deviceProfiles", ()),), None),
    TypeSpec("CONVERTER", "/api/converter", (("/api/converters", ()),), "/api/converter/{id}"),
    TypeSpec("INTEGRATION", "/api/integration", (("/api/integrations", ()),), "/api/integration/{id}"),
    # Les assets de la cible ne sont jamais supprimés (ni « Site » ni « Risque »)
    TypeSpec("ASSET", "/api/asset", (("/api/tenant/assets", ()),), None,
             key=lambda e: (e.get("type"), e.get("name"))),
    TypeSpec("NOTIFICATION_TARGET", "/api/notification/target", (("/api/notification/targets", ()),),
             "/api/notification/target/{id}"),
    TypeSpec("NOTIFICATION_TEMPLATE", "/api/notification/template", (("/api/notification/templates", ()),),
             "/api/notification/template/{id}"),
    TypeSpec("NOTIFICATION_RULE", "/api/notification/rule", (("/api/notification/rules", ()),),
             "/api/notification/rule/{id}"),
]}

# Ordre de création / mise à jour : chaque type ne dépend que des précédents.
# Les références encore impossibles à résoudre (par ex. profile -> dashboard) sont
# complétées lors d'une seconde passe.
SYNC_ORDER: List[str] = [
    "TB_RESOURCE", "WIDGET_TYPE", "WIDGETS_BUNDLE", "CUSTOMER", "ROLE", "RULE_CHAIN",
    "DASHBOARD", "ASSET_PROFILE", "DEVICE_PROFILE", "CONVERTER", "INTEGRATION",
    "ENTITY_GROUP", "ASSET", "NOTIFICATION_TARGET", "NOTIFICATION_TEMPLATE", "NOTIFICATION_RULE",
]

# Ordre de suppression : inverse des dépendances. Sans ASSET, DEVICE ni DEVICE_PROFILE.
DELETE_ORDER: List[str] = [
    "NOTIFICATION_RULE", "NOTIFICATION_TEMPLATE", "NOTIFICATION_TARGET", "ENTITY_GROUP",
    "INTEGRATION", "CONVERTER", "DASHBOARD", "ASSET_PROFILE", "RULE_CHAIN", "ROLE",
    "CUSTOMER", "WIDGETS_BUNDLE", "WIDGET_TYPE", "TB_RESOURCE",
]

GROUP_TYPES = ["ASSET", "CUSTOMER", "DASHBOARD", "DEVICE", "ENTITY_VIEW", "USER"]
# Groupes de la cible qui ne sont pas supprimés s'ils ont des membres (ces membres ne sont pas synchronisés)
PROTECTED_GROUP_TYPES = {"ASSET", "DEVICE", "USER", "ENTITY_VIEW"}

# Champs propres à l'instance source, jamais envoyés à la cible.
# « version » sert au verrouillage optimiste : sans elle, ThingsBoard ne vérifie pas la version.
ALWAYS_STRIP = ("id", "createdTime", "version")
