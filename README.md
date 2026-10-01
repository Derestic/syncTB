# synctb

Sincroniza un tenant de **ThingsBoard 4.3 PE** guardado en un repositorio de *Version Control*
(ya clonado en local) contra un tenant de una instancia en marcha.

- Sincroniza todo excepto usuarios y devices.
- De los assets solo sincroniza los de tipo `Risque`. Los `Site` nunca se tocan.
- Borra del destino lo que no está en el origen, salvo assets, devices y device profiles.

Las reglas completas están en [PLAN.md](PLAN.md).

## Uso

```bash
export TB_URL=https://thingsboard.example.com
export TB_USERNAME=tenant.admin@example.com
export TB_PASSWORD=********
export TB_TENANT="Mi Tenant"

synctb ./ruta/al/repo --dry-run   # muestra lo que haría
synctb ./ruta/al/repo             # aplica los cambios
```

| Opción | Variable de entorno | Descripción |
|---|---|---|
| `repo` | — | Ruta del repositorio VC clonado |
| `--url` | `TB_URL` | URL del ThingsBoard destino |
| `--username` | `TB_USERNAME` | Usuario **tenant admin** del tenant destino |
| — | `TB_PASSWORD` | Contraseña (solo por variable de entorno) |
| `--tenant` | `TB_TENANT` | Nombre del tenant destino. Si no coincide con el del usuario, se aborta |
| `--dry-run` | — | No modifica nada, solo registra lo que haría |
| `-v` | — | Log en nivel DEBUG |

El log sale por la consola. Códigos de salida:

| Código | Significado |
|---|---|
| `0` | Correcto |
| `1` | La sincronización terminó, pero alguna entidad falló |
| `2` | Configuración incorrecta |
| `3` | Error fatal: login, tenant incorrecto o repositorio ilegible |

## Desarrollo

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
pip install -e .
pytest
```

## Build y publicación en Artifactory

```bash
pip install build twine
python -m build --wheel
twine upload --repository-url https://<artifactory>/artifactory/api/pypi/<repo-pypi> dist/*
```

Para instalarlo desde Artifactory:

```bash
pip install synctb --index-url https://<artifactory>/artifactory/api/pypi/<repo-pypi>/simple
```
