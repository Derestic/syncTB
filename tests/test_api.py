from unittest.mock import MagicMock

import pytest

from synctb.api import ApiException, TbApi


def make_api(responses, dry_run=False):
    """TbApi sobre un ApiClient simulado que devuelve `responses` en orden."""
    client = MagicMock()
    api_client = client.api_client
    api_client.param_serialize.side_effect = lambda **kw: (kw["method"], kw["resource_path"], {}, kw["body"], None)

    def call_api(method, url, headers, body, post):
        status, data = responses.pop(0)
        resp = MagicMock(status=status, data=data.encode(), reason="x")
        resp.getheaders.return_value = {}
        return resp

    api_client.call_api.side_effect = call_api
    return TbApi(client, dry_run=dry_run), api_client


def test_get_all_follows_pages():
    api, _ = make_api([
        (200, '{"data": [{"n": 1}], "hasNext": true}'),
        (200, '{"data": [{"n": 2}], "hasNext": false}'),
    ])
    assert [x["n"] for x in api.get_all("/api/x")] == [1, 2]


def test_get_all_accepts_plain_lists():
    api, _ = make_api([(200, '[{"n": 1}, {"n": 2}]')])
    assert len(list(api.get_all("/api/x"))) == 2


def test_errors_raise_api_exception():
    api, _ = make_api([(400, '{"message": "bad"}')])
    with pytest.raises(ApiException):
        api.post("/api/x", {"a": 1})


def test_dry_run_does_not_write():
    api, api_client = make_api([], dry_run=True)
    saved = api.post("/api/asset", {"name": "a"})
    api.delete("/api/asset/1")
    assert api_client.call_api.call_count == 0
    assert saved["name"] == "a" and saved["id"]["id"]
