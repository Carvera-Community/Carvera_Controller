"""Built-in bed catalog (one entry per bundled OBJ)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .materials import MATERIAL_ALUMINUM, MATERIAL_MDF

KNOWN_MACHINES = ("C1", "CA1", "Z1")

CUSTOM_CATALOG_ID = "custom"

_MESHES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "GcodeViewer", "beds"))


@dataclass(frozen=True)
class CatalogPlate:
    """One built-in bed."""

    id: str
    machine: str
    label: str
    default_material: str
    mesh_name: str

    def mesh_path(self) -> str:
        return os.path.join(_MESHES_DIR, self.mesh_name)


def meshes_dir() -> str:
    return _MESHES_DIR


_PLATES: tuple[CatalogPlate, ...] = (
    CatalogPlate("C1_MDF", "C1", "MDF", MATERIAL_MDF, "C1_MDF.obj"),
    CatalogPlate("C1_SMW_Metric", "C1", "SMW (Metric)", MATERIAL_ALUMINUM, "C1_SMW_Metric.obj"),
    CatalogPlate("C1_SMW_Inches", "C1", "SMW (Inches)", MATERIAL_ALUMINUM, "C1_SMW_Inches.obj"),
    CatalogPlate("CA1_MDF", "CA1", "MDF", MATERIAL_MDF, "CA1_MDF.obj"),
    CatalogPlate("CA1_SMW_Metric", "CA1", "SMW (Metric)", MATERIAL_ALUMINUM, "CA1_SMW_Metric.obj"),
    CatalogPlate("CA1_SMW_Inches", "CA1", "SMW (Inches)", MATERIAL_ALUMINUM, "CA1_SMW_Inches.obj"),
    CatalogPlate("Z1_MDF", "Z1", "MDF", MATERIAL_MDF, "Z1_MDF.obj"),
    CatalogPlate("Z1_SMW_Metric", "Z1", "SMW (Metric)", MATERIAL_ALUMINUM, "Z1_SMW_Metric.obj"),
    CatalogPlate("Z1_SMW_Inches", "Z1", "SMW (Inches)", MATERIAL_ALUMINUM, "Z1_SMW_Inches.obj"),
)

_BY_ID = {p.id: p for p in _PLATES}


def all_plates() -> tuple[CatalogPlate, ...]:
    return _PLATES


def plates_for_machine(model: str) -> tuple[CatalogPlate, ...]:
    machine = (model or "").strip()
    return tuple(p for p in _PLATES if p.machine == machine)


def plate_by_id(catalog_id: str | None) -> CatalogPlate | None:
    if not catalog_id:
        return None
    return _BY_ID.get(str(catalog_id).strip())


def is_known_machine(model: str | None) -> bool:
    return (model or "").strip() in KNOWN_MACHINES
