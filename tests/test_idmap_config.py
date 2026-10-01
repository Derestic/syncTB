import pytest

from synctb.config import Config, ConfigError
from synctb.idmap import IdMap

A = "aaaaaaaa-0000-0000-0000-000000000001"
B = "bbbbbbbb-0000-0000-0000-000000000002"
C = "cccccccc-0000-0000-0000-000000000003"


def test_rewrite_replaces_nested_and_embedded_ids():
    idmap = IdMap()
    idmap.set(A, B)
    unresolved = set()

    result = idmap.rewrite({
        "ref": {"entityType": "ASSET", "id": A},
        "list": [A.upper(), C],
        "script": f"return msg.id == '{A}';",
        "n": 5,
    }, unresolved)

    assert result == {
        "ref": {"entityType": "ASSET", "id": B},
        "list": [B, C],
        "script": f"return msg.id == '{B}';",
        "n": 5,
    }
    assert unresolved == {C}


def test_config_reads_environment(tmp_path):
    env = {"TB_URL": "http://tb/", "TB_USERNAME": "u", "TB_PASSWORD": "p", "TB_TENANT": "T"}
    config = Config.build(tmp_path, environ=env)
    assert (config.url, config.username, config.password, config.tenant_name) == ("http://tb", "u", "p", "T")


def test_config_cli_overrides_environment(tmp_path):
    env = {"TB_URL": "http://tb", "TB_USERNAME": "u", "TB_PASSWORD": "p", "TB_TENANT": "T"}
    config = Config.build(tmp_path, url="http://other", tenant_name="X", environ=env)
    assert (config.url, config.tenant_name) == ("http://other", "X")


def test_config_requires_password_env(tmp_path):
    with pytest.raises(ConfigError, match="TB_PASSWORD"):
        Config.build(tmp_path, url="http://tb", username="u", tenant_name="T", environ={})


def test_config_requires_existing_repo(tmp_path):
    env = {"TB_URL": "http://tb", "TB_USERNAME": "u", "TB_PASSWORD": "p", "TB_TENANT": "T"}
    with pytest.raises(ConfigError, match="n'existe pas"):
        Config.build(tmp_path / "missing", environ=env)
