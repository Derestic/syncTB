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


def test_filters_keep_only_risque_assets_and_drop_devices(tmp_path):
    site_profile = write(tmp_path, "asset_profile", export("ASSET_PROFILE", src_entity("ASSET_PROFILE", name="Site")))
    risque = write(tmp_path, "asset", export("ASSET", src_entity("ASSET", name="r", type="Risque")))
    site = write(tmp_path, "asset", export("ASSET", src_entity("ASSET", name="s", type="Site")))
    # Sin campo type: se resuelve por el nombre de su asset profile
    site2 = write(tmp_path, "asset", export("ASSET", src_entity(
        "ASSET", name="s2", assetProfileId={"entityType": "ASSET_PROFILE", "id": site_profile})))
    device = write(tmp_path, "device", export("DEVICE", src_entity("DEVICE", name="d")))

    repo = apply_filters(load_repository(tmp_path))

    kept = {e.source_id for e in repo.entities}
    assert kept == {risque, site_profile}
    assert set(repo.excluded) == {site, site2, device}
