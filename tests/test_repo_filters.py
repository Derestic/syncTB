import json

from synctb.filters import apply_filters
from synctb.repo import load_repository
from tests.helpers import export, src_entity, write


def test_load_repository_reads_all_folders(tmp_path):
    customer = write(tmp_path, "customer", export("CUSTOMER", src_entity("CUSTOMER", title="C1")))
    write(tmp_path, "asset", export("ASSET", src_entity("ASSET", name="r1", type="Risque")))
    write(tmp_path, "groups/device", export("ENTITY_GROUP", src_entity("ENTITY_GROUP", name="g", type="DEVICE")))
    write(tmp_path, f"hierarchy/{customer}/dashboard", export("DASHBOARD", src_entity("DASHBOARD", title="d")))
    write(tmp_path, f"hierarchy/{customer}/groups/user",
          export("ENTITY_GROUP", src_entity("ENTITY_GROUP", name="u", type="USER")))
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "x.json").write_text("{}")

    repo = load_repository(tmp_path)

    types = sorted(e.entity_type for e in repo.entities)
    assert types == ["ASSET", "CUSTOMER", "DASHBOARD", "ENTITY_GROUP", "ENTITY_GROUP"]
    assert repo.tenant_id == "22222222-2222-2222-2222-222222222222"


def test_group_members_file_is_attached_to_its_group(tmp_path):
    group = write(tmp_path, "groups/asset", export("ENTITY_GROUP", src_entity("ENTITY_GROUP", name="g", type="ASSET")))
    members = [{"entityType": "ASSET", "id": "a1"}, {"entityType": "ASSET", "id": "a2"}]
    (tmp_path / "groups" / "asset" / f"{group}_entities.json").write_text(json.dumps(members), encoding="utf-8")
    # Liste de membres d'un groupe absent du dépôt : ignorée avec un avertissement
    (tmp_path / "groups" / "asset" / "orphelin_entities.json").write_text("[]", encoding="utf-8")

    repo = load_repository(tmp_path)

    assert len(repo.entities) == 1
    assert repo.entities[0].member_ids == ["a1", "a2"]
    assert repo.unsupported == []


def test_files_that_are_not_json_objects_are_skipped(tmp_path):
    write(tmp_path, "groups/asset", export("ENTITY_GROUP", src_entity("ENTITY_GROUP", name="g", type="ASSET")))
    odd = tmp_path / "groups" / "asset" / "liste.json"
    odd.write_text('[{"id": "x"}]', encoding="utf-8")

    repo = load_repository(tmp_path)

    assert [e.entity_type for e in repo.entities] == ["ENTITY_GROUP"]
    assert repo.unsupported == [odd]
    assert apply_filters(repo).unsupported == [odd]


def test_filters_keep_only_risque_assets_and_drop_devices(tmp_path):
    site_profile = write(tmp_path, "asset_profile", export("ASSET_PROFILE", src_entity("ASSET_PROFILE", name="Site")))
    risque = write(tmp_path, "asset", export("ASSET", src_entity("ASSET", name="r", type="Risque")))
    site = write(tmp_path, "asset", export("ASSET", src_entity("ASSET", name="s", type="Site")))
    # Sans champ type : le type est déduit du nom de son asset profile
    site2 = write(tmp_path, "asset", export("ASSET", src_entity(
        "ASSET", name="s2", assetProfileId={"entityType": "ASSET_PROFILE", "id": site_profile})))
    device = write(tmp_path, "device", export("DEVICE", src_entity("DEVICE", name="d")))

    repo = apply_filters(load_repository(tmp_path))

    kept = {e.source_id for e in repo.entities}
    assert kept == {risque, site_profile}
    assert set(repo.excluded) == {site, site2, device}
