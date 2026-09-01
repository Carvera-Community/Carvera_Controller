"""Per-machine bed JSON store, including custom mesh copy/delete."""

from __future__ import annotations

from carveracontroller.addons.beds import store as bed_store
from carveracontroller.addons.beds.catalog import CUSTOM_CATALOG_ID
from carveracontroller.addons.beds.materials import MATERIAL_ALUMINUM, MATERIAL_MDF


def _patch_config_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(bed_store.ConfigUtils, "CONFIG_DIR", str(tmp_path))


def _sample_bed(**overrides):
    bed = {
        "id": "bed-1",
        "name": "MDF",
        "catalog_id": "C1_MDF",
        "mesh_file": None,
        "material": MATERIAL_MDF,
        "mcs_x": -375.0,
        "mcs_y": -250.0,
        "mcs_z": 0.0,
    }
    bed.update(overrides)
    return bed


def test_load_save_roundtrip(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)
    data = bed_store._empty_store()
    bed_store.upsert_bed(data, "C1", _sample_bed())
    bed_store.set_selected_id(data, "C1", "bed-1")
    bed_store.save_store(data)

    loaded = bed_store.load_store()
    assert bed_store.selected_id(loaded, "C1") == "bed-1"
    beds = bed_store.list_beds(loaded, "C1")
    assert len(beds) == 1
    assert beds[0]["name"] == "MDF"
    assert beds[0]["mcs_x"] == -375.0


def test_per_model_isolation(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)
    data = bed_store._empty_store()
    bed_store.upsert_bed(data, "C1", _sample_bed(id="c1", name="C1 plate"))
    bed_store.upsert_bed(data, "Z1", _sample_bed(id="z1", name="Z1 plate", catalog_id="Z1_MDF"))
    bed_store.set_selected_id(data, "C1", "c1")
    bed_store.save_store(data)

    loaded = bed_store.load_store()
    assert [b["id"] for b in bed_store.list_beds(loaded, "C1")] == ["c1"]
    assert [b["id"] for b in bed_store.list_beds(loaded, "Z1")] == ["z1"]
    assert bed_store.list_beds(loaded, "CA1") == []
    assert bed_store.selected_id(loaded, "C1") == "c1"
    assert bed_store.selected_id(loaded, "Z1") is None


def test_none_selection_clears_selected_id(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)
    data = bed_store._empty_store()
    bed_store.upsert_bed(data, "C1", _sample_bed())
    bed_store.set_selected_id(data, "C1", "bed-1")
    bed_store.set_selected_id(data, "C1", None)
    assert bed_store.selected_id(data, "C1") is None
    bed_store.set_selected_id(data, "C1", "missing")
    assert bed_store.selected_id(data, "C1") is None


def test_custom_mesh_copy_and_delete(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)
    src = tmp_path / "source.obj"
    src.write_text("o plate\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")

    data = bed_store._empty_store()
    mesh_file = bed_store.copy_custom_mesh(str(src))
    copied = tmp_path / "beds" / "meshes" / mesh_file
    assert copied.is_file()

    bed = _sample_bed(
        id="custom-1",
        name="Custom",
        catalog_id=CUSTOM_CATALOG_ID,
        mesh_file=mesh_file,
        material=MATERIAL_ALUMINUM,
    )
    bed_store.upsert_bed(data, "C1", bed)
    bed_store.set_selected_id(data, "C1", "custom-1")
    bed_store.save_store(data)

    resolved = bed_store.resolve_mesh_path(bed_store.get_bed(data, "C1", "custom-1"))
    assert resolved == str(copied)

    assert bed_store.delete_bed(data, "C1", "custom-1") is True
    assert not copied.exists()
    assert bed_store.selected_id(data, "C1") is None
    assert bed_store.list_beds(data, "C1") == []


def test_upsert_catalog_plate_drops_unused_custom_mesh(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)
    src = tmp_path / "source.obj"
    src.write_text("o plate\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")

    data = bed_store._empty_store()
    mesh_file = bed_store.copy_custom_mesh(str(src))
    copied = tmp_path / "beds" / "meshes" / mesh_file
    bed_store.upsert_bed(
        data,
        "C1",
        _sample_bed(id="custom-1", name="Custom", catalog_id=CUSTOM_CATALOG_ID, mesh_file=mesh_file),
    )

    bed_store.upsert_bed(data, "C1", _sample_bed(id="custom-1", name="MDF", catalog_id="C1_MDF", mesh_file=None))

    assert not copied.exists()
    saved = bed_store.get_bed(data, "C1", "custom-1")
    assert saved is not None
    assert saved["catalog_id"] == "C1_MDF"
    assert saved["mesh_file"] is None


def test_upsert_catalog_keeps_custom_mesh_shared_by_another_bed(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)
    src = tmp_path / "source.obj"
    src.write_text("o plate\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")

    data = bed_store._empty_store()
    mesh_file = bed_store.copy_custom_mesh(str(src))
    copied = tmp_path / "beds" / "meshes" / mesh_file
    bed_store.upsert_bed(
        data,
        "C1",
        _sample_bed(id="a", name="A", catalog_id=CUSTOM_CATALOG_ID, mesh_file=mesh_file),
    )
    bed_store.upsert_bed(
        data,
        "Z1",
        _sample_bed(id="b", name="B", catalog_id=CUSTOM_CATALOG_ID, mesh_file=mesh_file),
    )

    bed_store.upsert_bed(data, "C1", _sample_bed(id="a", name="MDF", catalog_id="C1_MDF", mesh_file=None))

    assert copied.is_file()
    assert bed_store.get_bed(data, "Z1", "b")["mesh_file"] == mesh_file


def test_upsert_same_custom_mesh_does_not_delete_file(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)
    src = tmp_path / "source.obj"
    src.write_text("o plate\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")

    data = bed_store._empty_store()
    mesh_file = bed_store.copy_custom_mesh(str(src))
    copied = tmp_path / "beds" / "meshes" / mesh_file
    bed_store.upsert_bed(
        data,
        "C1",
        _sample_bed(id="custom-1", name="Custom", catalog_id=CUSTOM_CATALOG_ID, mesh_file=mesh_file),
    )

    bed_store.upsert_bed(
        data,
        "C1",
        _sample_bed(
            id="custom-1",
            name="Renamed",
            catalog_id=CUSTOM_CATALOG_ID,
            mesh_file=mesh_file,
            mcs_z=-12.0,
        ),
    )

    assert copied.is_file()
    assert bed_store.get_bed(data, "C1", "custom-1")["mesh_file"] == mesh_file
