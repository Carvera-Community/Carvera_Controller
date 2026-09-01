#!/usr/bin/env python3
"""Convert bed STEP files to millimetre OBJ meshes (dev-only).

In order to run this script, execute the following commands with the STEP files in
the ``carveracontroller/data/GcodeViewer/beds/`` directory:

    poetry run pip install cascadio trimesh
    poetry run python scripts/convert_beds.py

The runtime loader computes vertex normals, so these preview OBJs omit ``vn``.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BEDS_DIR = ROOT / "carveracontroller" / "data" / "GcodeViewer" / "beds"
STEP_DIR = BEDS_DIR
OUT_DIR = BEDS_DIR

TOL_LINEAR_MDF = 1.0
TOL_LINEAR_SMW = 2.0
TOL_ANGULAR = 0.60
WELD_DIGITS = 3


def _require_cascadio():
    try:
        import cascadio
    except ImportError as exc:
        raise SystemExit(
            "cascadio is required for STEP conversion.\nInstall once with:  poetry run pip install cascadio trimesh"
        ) from exc
    return cascadio


def _require_trimesh():
    try:
        import trimesh
    except ImportError as exc:
        raise SystemExit(
            "trimesh is required for STEP conversion.\nInstall once with:  poetry run pip install cascadio trimesh"
        ) from exc
    return trimesh


def tessellate_step(step_path: Path):
    """Return a trimesh.Trimesh for *step_path*."""
    cascadio = _require_cascadio()
    trimesh = _require_trimesh()
    tol_linear = TOL_LINEAR_SMW if "SMW" in step_path.stem else TOL_LINEAR_MDF
    with tempfile.TemporaryDirectory(prefix="bed_") as tmp:
        tmp_dir = Path(tmp)
        if hasattr(cascadio, "step_to_obj"):
            raw_path = tmp_dir / "raw.obj"
            cascadio.step_to_obj(
                step_path.as_posix(),
                raw_path.as_posix(),
                tol_linear=tol_linear,
                tol_angular=TOL_ANGULAR,
                use_colors=False,
            )
        else:
            raw_path = tmp_dir / "raw.glb"
            cascadio.step_to_glb(
                step_path.as_posix(),
                raw_path.as_posix(),
                tol_linear=tol_linear,
                tol_angular=TOL_ANGULAR,
            )
        loaded = trimesh.load(raw_path.as_posix(), force="mesh")
        if isinstance(loaded, trimesh.Scene):
            geoms = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not geoms:
                raise RuntimeError(f"no triangles in {step_path.name}")
            loaded = trimesh.util.concatenate(geoms)
        if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
            raise RuntimeError(f"no triangles in {step_path.name}")
        return loaded


def to_millimetres(vertices: np.ndarray) -> tuple[np.ndarray, str]:
    """Scale coordinates to millimetres using AABB heuristics."""
    extents = vertices.max(axis=0) - vertices.min(axis=0)
    longest = float(np.max(extents))
    if longest <= 0:
        return vertices, "unknown"
    # GLB export is often metres; a Carvera plate is 200–400 mm.
    if longest < 2.0:
        return vertices * 1000.0, "metres->mm"
    # SMW STEP files store inch coordinates when OCCT does not convert.
    if longest < 50.0:
        return vertices * 25.4, "inches->mm"
    return vertices, "mm"


def rotate_thin_axis_to_z(vertices: np.ndarray) -> tuple[np.ndarray, str]:
    """Rotate so the smallest AABB axis becomes Z (plate lies in XY)."""
    extents = vertices.max(axis=0) - vertices.min(axis=0)
    thin = int(np.argmin(extents))
    if thin == 2:
        return vertices, "z-up"
    if thin == 0:
        rot = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])
        return vertices @ rot.T, "x->z"
    rot = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
    return vertices @ rot.T, "y->z"


def reorigin_front_left_top(vertices: np.ndarray) -> np.ndarray:
    """Translate so min X, min Y, max Z is the origin (solid hangs into −Z)."""
    mins = vertices.min(axis=0)
    maxs = vertices.max(axis=0)
    origin = np.array([mins[0], mins[1], maxs[2]])
    return vertices - origin


def weld_mesh(vertices: np.ndarray, faces: np.ndarray, digits: int = WELD_DIGITS) -> tuple[np.ndarray, np.ndarray]:
    """Merge duplicate tessellation vertices and drop degenerate / repeated faces."""
    trimesh = _require_trimesh()
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.merge_vertices(digits_vertex=int(digits), merge_norm=True, merge_tex=True)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    if len(mesh.faces) == 0 or len(mesh.vertices) < 3:
        raise RuntimeError("empty mesh after weld")
    return np.asarray(mesh.vertices, dtype=np.float64), np.asarray(mesh.faces, dtype=np.int64)


def write_obj(
    path: Path,
    name: str,
    vertices: np.ndarray,
    faces: np.ndarray,
) -> None:
    mins = vertices.min(axis=0)
    maxs = vertices.max(axis=0)
    thickness = float(maxs[2] - mins[2])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Bed mesh (millimetres)\n")
        handle.write(f"# bbox_min {mins[0]:.5f} {mins[1]:.5f} {mins[2]:.5f}\n")
        handle.write(f"# bbox_max {maxs[0]:.5f} {maxs[1]:.5f} {maxs[2]:.5f}\n")
        handle.write(f"# thickness_mm {thickness:.5f}\n")
        handle.write(f"o {name}\n")
        for v in vertices:
            handle.write(f"v {v[0]:.3f} {v[1]:.3f} {v[2]:.3f}\n")
        # 1-based OBJ indices. Vertex normals are computed at load time.
        for a, b, c in faces:
            handle.write(f"f {a + 1} {b + 1} {c + 1}\n")


def convert_one(step_path: Path, out_path: Path) -> dict:
    mesh = tessellate_step(step_path)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    raw_tris = int(len(faces))
    vertices, unit_note = to_millimetres(vertices)
    vertices, rot_note = rotate_thin_axis_to_z(vertices)
    vertices = reorigin_front_left_top(vertices)
    vertices, faces = weld_mesh(vertices, faces)
    write_obj(out_path, step_path.stem, vertices, faces)
    mins = vertices.min(axis=0)
    maxs = vertices.max(axis=0)
    return {
        "id": step_path.stem,
        "triangles": int(len(faces)),
        "raw_triangles": raw_tris,
        "vertices": int(len(vertices)),
        "size_xy": (float(maxs[0] - mins[0]), float(maxs[1] - mins[1])),
        "thickness_mm": float(maxs[2] - mins[2]),
        "unit": unit_note,
        "orient": rot_note,
        "bytes": out_path.stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ids",
        nargs="*",
        help="Optional plate ids (filenames without .step). Default: all.",
    )
    args = parser.parse_args(argv)
    steps = sorted(STEP_DIR.glob("*.step"))
    if args.ids:
        wanted = set(args.ids)
        steps = [p for p in steps if p.stem in wanted]
        missing = wanted - {p.stem for p in steps}
        if missing:
            print(f"unknown ids: {sorted(missing)}", file=sys.stderr)
            return 1
    if not steps:
        print(f"no STEP files in {STEP_DIR}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for step_path in steps:
        out_path = OUT_DIR / f"{step_path.stem}.obj"
        print(f"converting {step_path.name} ...")
        info = convert_one(step_path, out_path)
        sx, sy = info["size_xy"]
        print(
            f"  {info['id']}: {sx:.1f} x {sy:.1f} x {info['thickness_mm']:.2f} mm, "
            f"{info['vertices']} verts, {info['triangles']} tris "
            f"(from {info['raw_triangles']}), {info['unit']}, {info['orient']}, "
            f"{info['bytes'] / 1024:.0f} KiB -> {out_path.relative_to(ROOT)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
