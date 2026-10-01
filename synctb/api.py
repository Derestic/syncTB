"""Accès REST au ThingsBoard cible.

`tb_pe_client.ThingsboardClient` est utilisé pour l'authentification, le rafraîchissement
du jeton et les nouvelles tentatives (HTTP 429). Les requêtes, en revanche, sont envoyées
avec du JSON brut : les fichiers du dépôt VC sont déjà au format de l'API REST, et passer
par les modèles pydantic du client risquerait de perdre des champs.

Avec dry_run=True, les écritures ne sont pas envoyées : elles sont tracées dans le log et
renvoient le corps lui-même avec un identifiant fictif, afin que le reste du traitement
puisse se dérouler normalement.
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
# Noms des schémas d'authentification déclarés par le client généré
_AUTH_SETTINGS = ["ApiKeyForm", "HttpLoginForm"]

__all__ = ["TbApi", "ApiException", "NotFoundException", "api_error", "p"]


class TbApi:
    """Client REST minimal (GET / POST / DELETE en JSON) au-dessus de ThingsboardClient."""

    def __init__(self, client: ThingsboardClient, dry_run: bool = False):
        self._api_client = client.api_client
        self.dry_run = dry_run

    @classmethod
    def login(cls, url, username, password, dry_run=False):
        """Ouvre une session JWT avec utilisateur et mot de passe."""
        return cls(ThingsboardClient(url, username=username, password=password), dry_run=dry_run)

    # ---------------------------------------------------------------- lecture

    def get(self, path: str, **params) -> Any:
        return self._request("GET", path, params)

    def get_or_none(self, path: str, **params) -> Any:
        """Comme `get`, mais renvoie None si la ressource n'existe pas (HTTP 404)."""
        try:
            return self.get(path, **params)
        except NotFoundException:
            return None

    def get_all(self, path: str, **params) -> Iterator[dict]:
        """Parcourt toutes les pages d'un endpoint paginé.

        Certains endpoints renvoient directement une liste : elle est alors renvoyée entière.
        """
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

    # -------------------------------------------------------------- écriture

    def post(self, path: str, body: Any = None, **params) -> Any:
        if self.dry_run:
            log.debug("[dry-run] POST %s", path)
            # Identifiant fictif pour que les références vers cette entité puissent être résolues
            if isinstance(body, dict) and "id" not in body:
                body = dict(body, id={"entityType": body.get("entityType", ""), "id": str(uuid.uuid4())})
            return body
        return self._request("POST", path, params, body)

    def delete(self, path: str, **params) -> None:
        if self.dry_run:
            log.debug("[dry-run] DELETE %s", path)
            return
        self._request("DELETE", path, params)

    # ------------------------------------------------------------------ interne

    def _request(self, method: str, path: str, params: Optional[dict] = None, body: Any = None) -> Any:
        """Envoie la requête via l'ApiClient du client (auth + nouvelles tentatives) et décode le JSON."""
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
    """Échappe un segment de chemin d'URL."""
    return quote(str(value), safe="")


def api_error(ex: ApiException) -> str:
    """Message lisible d'une erreur de l'API (statut HTTP + message de ThingsBoard)."""
    body = ex.body or ""
    try:
        body = json.loads(body).get("message", body)
    except (ValueError, AttributeError):
        pass
    return f"HTTP {ex.status} {body}".strip()
