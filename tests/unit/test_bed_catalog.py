"""Built-in bed catalog filtering."""

import os

from carveracontroller.addons.beds.catalog import (
    CUSTOM_CATALOG_ID,
    all_plates,
    is_known_machine,
    plate_by_id,
    plates_for_machine,
)
from carveracontroller.addons.beds.materials import MATERIAL_ALUMINUM, MATERIAL_MDF


def test_each_machine_has_mdf_and_two_smw_plates():
    for model in ("C1", "CA1", "Z1"):
        plates = plates_for_machine(model)
        ids = {p.id for p in plates}
        assert ids == {f"{model}_MDF", f"{model}_SMW_Metric", f"{model}_SMW_Inches"}
        by_id = {p.id: p for p in plates}
        assert by_id[f"{model}_MDF"].default_material == MATERIAL_MDF
        assert by_id[f"{model}_SMW_Metric"].default_material == MATERIAL_ALUMINUM
        assert by_id[f"{model}_SMW_Inches"].default_material == MATERIAL_ALUMINUM
        assert by_id[f"{model}_MDF"].label == "MDF"
        assert by_id[f"{model}_SMW_Metric"].label == "SMW (Metric)"
        assert by_id[f"{model}_SMW_Inches"].label == "SMW (Inches)"


def test_unknown_machine_has_empty_catalog():
    assert plates_for_machine("") == ()
    assert plates_for_machine("X1") == ()
    assert is_known_machine("C1") is True
    assert is_known_machine("X1") is False


def test_plate_by_id_and_catalog_size():
    assert len(all_plates()) == 9
    assert plate_by_id("C1_MDF") is not None
    assert plate_by_id("missing") is None
    assert plate_by_id(CUSTOM_CATALOG_ID) is None
    assert plate_by_id("C1_MDF").mesh_name == "C1_MDF.obj"


def test_catalog_mesh_files_exist():
    from carveracontroller.addons.beds.mesh_loader import read_obj_metadata

    for plate in all_plates():
        path = plate.mesh_path()
        assert os.path.isfile(path), path
        meta = read_obj_metadata(path)
        assert float(meta["thickness_mm"]) > 0
