import json

import pytest

from synctb.filters import apply_filters
from synctb.repo import load_repository
from synctb.syncer import Syncer, TenantError
from tests.fakes import TENANT_ID, FakeTb, ent, uid
from tests.helpers import SOURCE_TENANT, export, src_entity, write


def ref(entity_type, entity_uuid):
    return {"entityType": entity_type, "id": entity_uuid}


@pytest.fixture
def scenario(tmp_path):
    """Dépôt source d'un autre tenant et cible contenant déjà des entités."""
    s = {}
    s["profile"] = write(tmp_path, "asset_profile", export("ASSET_PROFILE", src_entity("ASSET_PROFILE", name="Risque")))
    s["device"] = write(tmp_path, "device", export("DEVICE", src_entity("DEVICE", name="dev-1")))
    s["site"] = write(tmp_path, "asset", export("ASSET", src_entity("ASSET", name="site-1", type="Site")))
    s["r2"] = write(tmp_path, "asset", export("ASSET", src_entity("ASSET", name="risque-2", type="Risque")))
    s["r1"] = uid()
    write(tmp_path, "asset", export(
        "ASSET",
        src_entity("ASSET", s["r1"], name="risque-1", type="Risque", assetProfileId=ref("ASSET_PROFILE", s["profile"])),
        relations=[
            {"from": ref("ASSET", s["r1"]), "to": ref("ASSET", s["r2"]), "type": "Contains", "typeGroup": "COMMON"},
            {"from": ref("ASSET", s["r1"]), "to": ref("DEVICE", s["device"]), "type": "Contains", "typeGroup": "COMMON"},
        ],
        attributes={"SERVER_SCOPE": [{"key": "limit", "longValue": 10}]},
        calculatedFields=[{"id": {"entityType": "CALCULATED_FIELD", "id": uid()}, "name": "cf1",
                           "entityId": ref("ASSET", s["r1"]), "type": "SIMPLE", "configuration": {}}],
    ))
    s["dashboard"] = write(tmp_path, "dashboard", export("DASHBOARD", src_entity(
        "DASHBOARD", title="Main", configuration={"entityAliases": {"a1": {"filter": {
            "singleEntity": ref("DEVICE", s["device"])}}, "a2": {"filter": {"singleEntity": ref("ASSET", s["r1"])}}}})))
    s["chain"] = write(tmp_path, "rule_chain", export(
        "RULE_CHAIN", src_entity("RULE_CHAIN", name="Root Rule Chain", type="CORE", root=True),
        metaData={"firstNodeIndex": 0, "nodes": [{"id": {"entityType": "RULE_NODE", "id": uid()}, "name": "n"}],
                  "connections": []}))
    s["group"] = write(tmp_path, "groups/asset", export(
        "ENTITY_GROUP", src_entity("ENTITY_GROUP", name="Risques", type="ASSET",
                                   ownerId=ref("TENANT", SOURCE_TENANT))))
    # Membres du groupe dans <id>_entities.json, comme dans le dépôt réel
    (tmp_path / "groups" / "asset" / f"{s['group']}_entities.json").write_text(
        json.dumps([ref("ASSET", s["r1"]), ref("ASSET", s["site"])]), encoding="utf-8")

    tb = FakeTb()
    owner = ref("TENANT", TENANT_ID)
    s["t_site"] = tb.add("ASSET", ent("ASSET", name="site-x", type="Site"))
    s["t_device"] = tb.add("DEVICE", ent("DEVICE", name="dev-x"))
    s["t_dprofile"] = tb.add("DEVICE_PROFILE", ent("DEVICE_PROFILE", name="old-profile"))
    s["t_old_dash"] = tb.add("DASHBOARD", ent("DASHBOARD", title="Old"))
    s["t_root"] = tb.add("RULE_CHAIN", ent("RULE_CHAIN", name="Root Rule Chain", type="CORE", root=True))
    s["t_dev_group"] = tb.add("ENTITY_GROUP", ent("ENTITY_GROUP", name="Devs", type="DEVICE", ownerId=owner))
    tb.group_members[s["t_dev_group"]["id"]["id"]] = [s["t_device"]["id"]["id"]]
    s["t_empty_group"] = tb.add("ENTITY_GROUP", ent("ENTITY_GROUP", name="Empty", type="CUSTOMER", ownerId=owner))
    s["t_all_group"] = tb.add("ENTITY_GROUP", ent("ENTITY_GROUP", name="All", type="ASSET", ownerId=owner,
                                                  groupAll=True))

    source = apply_filters(load_repository(tmp_path))
    return s, tb, source


def by_name(tb, entity_type, name):
    found = [e for e in tb.all(entity_type) if (e.get("name") or e.get("title")) == name]
    assert len(found) == 1, found
    return found[0]


def tid(e):
    return e["id"]["id"]


def test_cross_tenant_creates_new_ids_and_rewrites_references(scenario):
    s, tb, source = scenario
    report = Syncer(tb, source, "Tenant A").run()

    profile = by_name(tb, "ASSET_PROFILE", "Risque")
    r1 = by_name(tb, "ASSET", "risque-1")
    assert tid(r1) != s["r1"]
    assert r1["externalId"] == {"entityType": "ASSET", "id": s["r1"]}
    assert r1["assetProfileId"]["id"] == tid(profile)
    assert "version" not in r1 and "createdTime" not in r1
    assert report.errors == 0


def test_site_assets_and_devices_are_never_written(scenario):
    s, tb, source = scenario
    Syncer(tb, source, "Tenant A").run()

    assert [a["name"] for a in tb.all("ASSET") if a.get("type") == "Site"] == ["site-x"]
    assert not tb.posts("/api/device")


def test_relations_only_between_existing_entities_and_never_with_devices(scenario):
    s, tb, source = scenario
    Syncer(tb, source, "Tenant A").run()

    r1, r2 = by_name(tb, "ASSET", "risque-1"), by_name(tb, "ASSET", "risque-2")
    relations = tb.posts("/api/v2/relation")
    assert [(r["from"]["id"], r["to"]["id"]) for r in relations] == [(tid(r1), tid(r2))]


def test_attributes_and_calculated_fields_use_target_ids(scenario):
    s, tb, source = scenario
    Syncer(tb, source, "Tenant A").run()

    r1 = by_name(tb, "ASSET", "risque-1")
    assert tb.posts(f"/api/plugins/telemetry/ASSET/{tid(r1)}/attributes/SERVER_SCOPE") == [{"limit": 10}]
    cf = tb.posts("/api/calculatedField")[0]
    assert cf["entityId"] == {"entityType": "ASSET", "id": tid(r1)}
    assert "id" not in cf


def test_dashboard_second_pass_and_device_reference_warning(scenario):
    s, tb, source = scenario
    report = Syncer(tb, source, "Tenant A").run()

    r1 = by_name(tb, "ASSET", "risque-1")
    dashboard = by_name(tb, "DASHBOARD", "Main")
    aliases = dashboard["configuration"]["entityAliases"]
    # L'asset a été créé après le dashboard : corrigé lors de la seconde passe
    assert aliases["a2"]["filter"]["singleEntity"]["id"] == tid(r1)
    # Le device n'existe pas dans la cible : référence laissée telle quelle, avec avertissement
    assert aliases["a1"]["filter"]["singleEntity"]["id"] == s["device"]
    assert report.warnings >= 1


def test_rule_chain_matched_by_name_keeps_target_id(scenario):
    s, tb, source = scenario
    Syncer(tb, source, "Tenant A").run()

    chains = tb.all("RULE_CHAIN")
    assert [tid(c) for c in chains] == [tid(s["t_root"])]
    meta = tb.posts("/api/ruleChain/metadata")[0]
    assert meta["ruleChainId"]["id"] == tid(s["t_root"])
    assert "id" not in meta["nodes"][0]


def test_group_members_only_include_synced_entities(scenario):
    s, tb, source = scenario
    Syncer(tb, source, "Tenant A").run()

    group = by_name(tb, "ENTITY_GROUP", "Risques")
    r1 = by_name(tb, "ASSET", "risque-1")
    assert tb.group_members[tid(group)] == [tid(r1)]


def test_deletes_obsolete_but_keeps_protected(scenario):
    s, tb, source = scenario
    Syncer(tb, source, "Tenant A").run()

    deleted = tb.deletes()
    assert f"/api/dashboard/{tid(s['t_old_dash'])}" in deleted
    assert f"/api/entityGroup/{tid(s['t_empty_group'])}" in deleted
    for kept in ("t_site", "t_device", "t_dprofile", "t_dev_group", "t_all_group"):
        assert not any(tid(s[kept]) in d for d in deleted), kept


def test_same_tenant_keeps_ids(tmp_path):
    asset_id = uid()
    write(tmp_path, "asset", export("ASSET", src_entity("ASSET", asset_id, name="r", type="Risque",
                                                          tenantId={"entityType": "TENANT", "id": TENANT_ID})))
    tb = FakeTb()
    tb.add("ASSET", ent("ASSET", asset_id, name="r-old", type="Risque"))

    report = Syncer(tb, apply_filters(load_repository(tmp_path)), "Tenant A").run()

    assert [tid(a) for a in tb.all("ASSET")] == [asset_id]
    assert tb.all("ASSET")[0]["name"] == "r"
    assert "externalId" not in tb.all("ASSET")[0]
    assert report.counts["ASSET"]["updated"] == 1


def test_rerun_is_idempotent(scenario):
    s, tb, source = scenario
    Syncer(tb, source, "Tenant A").run()
    counts = {t: len(tb.all(t)) for t in tb.store}

    report = Syncer(tb, source, "Tenant A").run()

    assert {t: len(tb.all(t)) for t in tb.store} == counts
    assert not any(row.get("created") for t, row in report.counts.items() if t not in ("GROUP_MEMBER",))


def test_wrong_tenant_name_aborts(tmp_path):
    with pytest.raises(TenantError, match="Tenant A"):
        Syncer(FakeTb(), apply_filters(load_repository(tmp_path)), "Otro").run()


def test_requires_tenant_admin(tmp_path):
    with pytest.raises(TenantError, match="TENANT_ADMIN"):
        Syncer(FakeTb(authority="SYS_ADMIN"), apply_filters(load_repository(tmp_path)), "Tenant A").run()
