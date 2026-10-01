"""Acceso REST al ThingsBoard destino.

Se usa `tb_pe_client.ThingsboardClient` para el login, el refresco del token y los
reintentos, pero las peticiones se hacen con JSON en crudo: los ficheros del repo VC ya
tienen el formato de la API REST y así no se pierde ningún campo al pasar por los modelos.

Con dry_run=True las escrituras no se envían: se registran en el log y devuelven el propio
cuerpo con un ID ficticio, de forma que el resto del proceso puede continuar.
"""

import json
import logging
import uuid
from typing import Any, Iterator, Optional
from urllib.parse import quote

from tb_pe_client import ThingsboardClient
from tb_pe_client.exceptions import ApiException, NotFoundException

log = logging.getLogger(__name__)

PAGE_SIZE = 500
_AUTH_SETTINGS = ["ApiKeyForm", "HttpLoginForm"]

__all__ = ["TbApi", "ApiException", "NotFoundException", "api_error", "p"]


class TbApi:
    def __init__(self, client: ThingsboardClient, dry_run: bool = False):
        self._api_client = client.api_client
        self.dry_run = dry_run

    @classmethod
    def login(cls, url, username, password, dry_run=False):
        return cls(ThingsboardClient(url, username=username, password=password), dry_run=dry_run)

    # ---------------------------------------------------------------- lectura

    def get(self, path: str, **params) -> Any:
        return self._request("GET", path, params)

    def get_or_none(self, path: str, **params) -> Any:
        try:
            return self.get(path, **params)
        except NotFoundException:
            return None

    def get_all(self, path: str, **params) -> Iterator[dict]:
        """Recorre un endpoint paginado. Si el endpoint devuelve una lista, la devuelve entera."""
        page = 0
        while True:
            result = self.get(path, pageSize=PAGE_SIZE, page=page, **params)
            if isinstance(result, list):
                yield from result
                return
            yield from result.get("data", [])
            if not result.get("hasNext"):
                return
            page += 1

    # -------------------------------------------------------------- escritura

    def post(self, path: str, body: Any = None, **params) -> Any:
        if self.dry_run:
            log.debug("[dry-run] POST %s", path)
            if isinstance(body, dict) and "id" not in body:
                body = dict(body, id={"entityType": body.get("entityType", ""), "id": str(uuid.uuid4())})
            return body
        return self._request("POST", path, params, body)

    def delete(self, path: str, **params) -> None:
        if self.dry_run:
            log.debug("[dry-run] DELETE %s", path)
            return
        self._request("DELETE", path, params)

    # ------------------------------------------------------------------ interno

    def _request(self, method: str, path: str, params: Optional[dict] = None, body: Any = None) -> Any:
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        query = [(k, v) for k, v in (params or {}).items() if v is not None] or None

        m, url, headers, body, post_params = self._api_client.param_serialize(
            method=method,
            resource_path=path,
            query_params=query,
            header_params=headers,
            body=body,
            auth_settings=_AUTH_SETTINGS,
        )
        response = self._api_client.call_api(m, url, headers, body, post_params)
        response.read()
        text = response.data.decode("utf-8") if response.data else ""
        if not 200 <= response.status <= 299:
            raise ApiException.from_response(http_resp=response, body=text, data=None)
        return json.loads(text) if text else None


def p(value: str) -> str:
    """Escapa un segmento de ruta."""
    return quote(str(value), safe="")


def api_error(ex: ApiException) -> str:
    """Mensaje legible de un error de la API."""
    body = ex.body or ""
    try:
        body = json.loads(body).get("message", body)
    except (ValueError, AttributeError):
        pass
    return f"HTTP {ex.status} {body}".strip()
