# synctb — Plan del proyecto

Herramienta de consola (Python 3.10, `.venv`, empaquetada con `setup.py`) que sincroniza
un tenant de ThingsBoard 4.3.0 PE almacenado en un repositorio git (Version Control nativo
de ThingsBoard, ya clonado en local) contra un tenant de una instancia en marcha.

Se publica en Artifactory y se ejecuta en pipelines CI/CD (log solo por consola).

## Requisitos confirmados

| Tema | Decisión |
|---|---|
| Formato de origen | Repo del Version Control nativo de TB (un único tenant) |
| Qué se sincroniza | Todo excepto usuarios y devices |
| Assets | Solo los de tipo `Risque`; nunca los de tipo `Site` (ni otros tipos) |
| Asset profiles / device profiles | Se sincronizan todos (incluido el profile `Site`) |
| Identificadores | Mismo tenant → se conservan. Otro tenant → IDs nuevos y se recalculan las referencias |
| Assets `Site` | Nunca se crean, actualizan ni borran en el destino (almacenan datos propios de cada instancia) |
| Relaciones del origen | Se crean solo si ambos extremos existen en el destino; si no, se descartan (se "rompen") |
| Relaciones del destino | Se mantienen siempre (no se borran por no estar en origen) |
| Borrados | Lo que no está en origen se borra del destino, **excepto** assets (incluidos `Risque`), devices y device profiles |
| Tenant de destino | Login con un **tenant admin** del tenant objetivo; se valida que el nombre del tenant coincide con `--tenant`. Si no coincide o no existe: error, no se crea |
| Mismo tenant o no | Se compara el `tenantId` de las entidades del repo con el del usuario logueado |
| Referencias a devices / `Site` en dashboards (alias) y rule chains | Se dejan tal cual y se registra un warning por cada referencia no resoluble |
| Entity views | No existen; no se gestionan |
| Entity groups | Se sincronizan; solo se añaden miembros sincronizados. No se quitan devices/assets del destino de sus grupos y no se borra un grupo que contenga assets o devices del destino |
| Relación presente en origen y destino | Gana el origen (se sobrescribe `additionalInfo`) |
| `calculatedFields` con referencias a devices / `Site` | Se sincronizan tal cual y se registra un warning por cada referencia |
| Atributos (`SERVER_SCOPE`) | Se escriben los del origen (crear/actualizar). Los que solo existen en el destino se mantienen, nunca se borran |
| Permisos de grupos de usuarios (`permissions`) | Se crean solo si no existen en el destino; los existentes no se modifican ni se borran |
| Cliente REST | `tb-pe-client` (PyPI, 4.3.1.x, Python >=3.10). Clase `tb_pe_client.ThingsboardClient(url, username, password)`; expone todos los controllers (asset, entity_group, group_permission, rule_chain, tenant, auth…) |
| Credenciales | Usuario y contraseña (variables de entorno de la pipeline) |
| Logging | Solo stdout/stderr |
| Tests | Unitarios con mocks, sin instancia real |

## Decisiones de implementación (a revisar)

Tomadas durante el desarrollo, no discutidas explícitamente:

| Tema | Decisión |
|---|---|
| Relaciones con devices | Nunca se crean desde el origen, aunque el device exista en el destino (mismo tenant) |
| Emparejado por nombre | Si no coincide `id` ni `externalId`, se empareja por nombre cuando hay un único candidato (rule chain raíz, profiles `default`, grupos creados automáticamente por TB…) |
| Grupos "All" | Solo se emparejan; nunca se crean, modifican ni borran |
| Customers | No se borra un customer que tenga assets o devices (TB PE los borraría en cascada) ni el customer público |
| Calculated fields | Gana el origen. Se borran los sobrantes, salvo en assets |
| Integraciones | Si al crear una el `routingKey` ya está en uso en la instancia, se crea con uno nuevo y se avisa |
| Nodos de rule chain | Se recrean (sin IDs de nodo) cada vez que se guarda la metadata |
| Rule chain raíz / profile por defecto | Se marcan con sus endpoints propios si el origen lo indica |
| Borrados fallidos | Por ejemplo, un profile en uso: se registran como aviso, no como error |

## Pendiente

- Validar los formatos con ficheros reales del repo VC, sobre todo `groups/` y los tipos exclusivos de PE.
- Probar contra una instancia real de ThingsBoard 4.3.0 PE (primero con `--dry-run`).

## Estructura del repo origen (Version Control)

Cada carpeta final contiene un JSON por entidad, con nombre `<externalId>.json`.
Cada tipo tiene su propio formato de JSON (pendiente de recibir ejemplos).

```
asset/  asset_profile/  converter/  customer/  dashboard/  device/  device_profile/
integration/  notification_rule/  notification_target/  notification_template/
role/  rule_chain/  tb_resource/  widget_type/  widget_bundle/
groups/{asset,customer,dashboard,device,entity_view,user}/
hierarchy/<ID>/dashboard/
hierarchy/<ID>/groups/{asset,customer,dashboard,device,entity_view,user}/
```

| Carpeta | Tratamiento |
|---|---|
| `device/` | Se ignora |
| `asset/` | Solo tipo `Risque` |
| `groups/*`, `hierarchy/<ID>/groups/*` | Entity groups (ver reglas de grupos) |
| `hierarchy/<ID>/...` | Entidades cuyo owner es el customer `<ID>` (customerId / ownerId). Sin anidamiento |
| `groups/{user,device,entity_view}` | El grupo se crea aunque quede vacío (no se sincronizan sus miembros) |
| Resto | Se sincroniza completo |

## Formatos JSON (EntityExportData)

Fuente: repo oficial `thingsboard/thingsboard`, clase
`common/data/.../sync/ie/EntityExportData.java` (rama `release-4.3`) y sus subclases.
El código PE 4.3 no es público: los tipos exclusivos de PE (grupos, converter,
integration, role) se han tomado de la rama `master`, que ya los incluye. **Validar con ficheros reales.**

Estructura común a todos los ficheros (confirmada con el ejemplo de `asset_profile`):

```json
{
  "entityType": "ASSET_PROFILE",
  "entity": { ... },                       // la entidad tal cual la devuelve la API REST (incluye id, externalId, tenantId...)
  "relations": [ EntityRelation ],          // {from:{entityType,id}, to:{entityType,id}, type, typeGroup, additionalInfo}
  "attributes": { "SERVER_SCOPE": [ AttributeExportData ] },
  "calculatedFields": [ CalculatedField ]
}
```

`AttributeExportData`: `key`, `lastUpdateTs`, y uno de `booleanValue` / `strValue` /
`longValue` / `doubleValue` / `jsonValue`.

Campos adicionales por tipo:

| entityType | Campos extra | Notas para la sincronización |
|---|---|---|
| `DEVICE` | `credentials` | Se ignora (no se sincronizan devices) |
| `RULE_CHAIN` | `metaData` (`firstNodeIndex`, `nodes`, `connections`, `ruleChainConnections`) | Se guarda la cadena y luego su metadata; los nodos pueden referenciar otras rule chains, devices o assets |
| `WIDGET_TYPE` | — | `entity` es un `WidgetTypeDetails` |
| `WIDGETS_BUNDLE` | `widgets` (lista de widget types), `fqns` (lista de FQN de widgets) | Se asocian los widget types al bundle por FQN |
| `ENTITY_GROUP` | `permissions` (solo grupos USER), `groupOtaPackages` (solo grupos DEVICE), `groupEntities`, `memberIds` (externalIds de los miembros) | `memberIds` filtrado a entidades sincronizadas; `groupOtaPackages` se ignora (sin OTA) |
| `DASHBOARD` | — | `entity.configuration.entityAliases` puede contener IDs de devices/`Site` → warning |
| `ASSET`, `ASSET_PROFILE`, `DEVICE_PROFILE`, `CUSTOMER`, `TB_RESOURCE`, `NOTIFICATION_*`, `CONVERTER`, `INTEGRATION`, `ROLE` | — | Solo la estructura común |

## Estructura del proyecto

```
syncTB/
├── setup.py              # paquete "synctb", comando de consola "synctb"
├── requirements.txt      # tb-pe-client
├── requirements-dev.txt  # + pytest
├── README.md
├── synctb/
│   ├── cli.py            # argparse, logging y códigos de salida
│   ├── config.py         # argumentos + variables de entorno
│   ├── model.py          # SourceEntity, SourceRepository, carpetas -> tipos
│   ├── repo.py           # lectura del repo VC
│   ├── filters.py        # exclusión de usuarios, devices y assets != Risque
│   ├── api.py            # REST en crudo sobre tb_pe_client.ThingsboardClient (+ dry-run)
│   ├── specs.py          # endpoints por tipo, orden de sincronización y de borrado
│   ├── idmap.py          # tabla origen -> destino y reescritura de UUID en el JSON
│   ├── syncer.py         # orquestación
│   └── report.py         # contadores y resumen final
└── tests/                # pytest con un ThingsBoard falso en memoria
```

## Flujo implementado

1. Leer el repo VC y aplicar los filtros.
2. Login como tenant admin y comprobar que el nombre del tenant coincide con `--tenant`.
3. Cargar las entidades existentes en el destino, incluidos los devices (solo para comprobar referencias) y los grupos de cada owner.
4. Crear o actualizar en orden de dependencias:
   resources → widget types → bundles → customers → roles → rule chains → dashboards →
   asset/device profiles → converters → integrations → entity groups → assets `Risque` →
   notification targets/templates/rules.
   - Se empareja por `id`, luego `externalId` y luego nombre.
   - Todos los UUID mapeados se reescriben en el JSON.
   - Las entidades nuevas guardan `externalId` = id de origen.
5. Segunda pasada para las entidades que referenciaban algo que aún no existía.
6. Metadata y raíz de rule chains, widgets de bundles, miembros y permisos de grupos,
   relaciones, atributos `SERVER_SCOPE` y calculated fields.
7. Borrar lo sobrante en orden inverso, con protecciones.
8. Resumen por tipo con creados, actualizados, borrados, mantenidos y fallidos.
   Código de salida: 0 correcto, 1 errores de entidades, 2 configuración, 3 fatal.

Con `--dry-run` las escrituras no se envían. Se registran en DEBUG y el proceso sigue con IDs ficticios.
