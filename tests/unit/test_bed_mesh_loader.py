"""Indexed OBJ loading and Kivy uint16 mesh chunking for beds."""

from carveracontroller.addons.beds.mesh_loader import (
    FLOATS_PER_VERTEX,
    BedMeshData,
    load_bed_mesh,
    pack_bed_mesh_chunks,
)


def _packed_normal(vertices: list[float], slot: int) -> tuple[float, float, float]:
    base = slot * FLOATS_PER_VERTEX + 3
    return (vertices[base], vertices[base + 1], vertices[base + 2])


def _tiny_obj(path, extra: str = "") -> str:
    path.write_text(
        "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 1 1 0\nvn 0 0 1\nf 1//1 2//1 3//1 4//1\n" + extra,
        encoding="utf-8",
    )
    return str(path)


def test_load_bed_mesh_keeps_shared_vertices(tmp_path):
    mesh = load_bed_mesh(_tiny_obj(tmp_path / "plate.obj"))
    # Quad uses 4 unique vertices, two triangles.
    assert len(mesh.positions) == 4
    assert len(mesh.indices) == 6
    assert mesh.indices == [0, 1, 2, 0, 2, 3]


def test_load_bed_mesh_without_object_name(tmp_path):
    mesh = load_bed_mesh(_tiny_obj(tmp_path / "anon.obj"))
    assert len(mesh.positions) == 4
    assert abs(mesh.thickness_mm) >= 0.0


def test_load_bed_mesh_without_vertex_normals(tmp_path):
    path = tmp_path / "flat.obj"
    path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    mesh = load_bed_mesh(str(path))
    assert len(mesh.positions) == 3
    assert mesh.indices == [0, 1, 2]
    nx, ny, nz = mesh.normals[0]
    assert abs(nx) < 1e-6 and abs(ny) < 1e-6 and abs(nz - 1.0) < 1e-6


def test_pack_chunks_stays_in_one_mesh_when_small():
    mesh = BedMeshData(
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        indices=[0, 1, 2],
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(1.0, 1.0, 0.0),
        thickness_mm=0.0,
    )
    chunks = pack_bed_mesh_chunks(mesh, scale=1.0, albedo_rgb=(1.0, 1.0, 1.0), max_vertices=65535)
    assert len(chunks) == 1
    vertices, indices = chunks[0]
    assert indices == [0, 1, 2]
    assert len(vertices) == 3 * FLOATS_PER_VERTEX


def test_pack_chunks_splits_when_over_uint16_limit():
    # Two triangles that share no vertices; force a split after 3 verts.
    mesh = BedMeshData(
        positions=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (2.0, 0.0, 0.0),
            (3.0, 0.0, 0.0),
            (2.0, 1.0, 0.0),
        ],
        normals=[(0.0, 0.0, 1.0)] * 6,
        indices=[0, 1, 2, 3, 4, 5],
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(3.0, 1.0, 0.0),
        thickness_mm=0.0,
    )
    chunks = pack_bed_mesh_chunks(mesh, scale=1.0, albedo_rgb=(1.0, 0.0, 0.0), max_vertices=3)
    assert len(chunks) == 2
    for vertices, indices in chunks:
        assert max(indices) < 65535
        assert len(vertices) // FLOATS_PER_VERTEX <= 3
        assert indices == [0, 1, 2]


def test_pack_chunks_splits_when_index_count_exceeds_uint16():
    # Few unique vertices, many triangles — Kivy still caps the *index list*.
    n_tris = 8
    mesh = BedMeshData(
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        indices=[0, 1, 2] * n_tris,
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(1.0, 1.0, 0.0),
        thickness_mm=0.0,
    )
    chunks = pack_bed_mesh_chunks(mesh, scale=1.0, albedo_rgb=(1.0, 1.0, 1.0), max_vertices=65535, max_indices=9)
    assert len(chunks) == 3
    assert sum(len(idx) for _verts, idx in chunks) == n_tris * 3
    for vertices, indices in chunks:
        assert len(indices) <= 9
        assert len(vertices) // FLOATS_PER_VERTEX == len(indices)


def test_pack_uses_face_normals_not_smoothed_weld():
    """A hole-rim edge shared by the top and a wall keeps two GPU normals."""
    mesh = BedMeshData(
        positions=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, -1.0),
        ],
        normals=[(0.0, 0.0, 0.0)] * 4,
        indices=[0, 1, 2, 0, 3, 1],
        bbox_min=(0.0, 0.0, -1.0),
        bbox_max=(1.0, 1.0, 0.0),
        thickness_mm=1.0,
    )
    chunks = pack_bed_mesh_chunks(mesh, scale=1.0, albedo_rgb=(1.0, 1.0, 1.0))
    assert len(chunks) == 1
    vertices, indices = chunks[0]
    assert indices == [0, 1, 2, 3, 4, 5]
    nx, ny, nz = _packed_normal(vertices, 0)
    assert abs(nx) < 1e-6 and abs(ny) < 1e-6 and abs(nz - 1.0) < 1e-6
    nx, ny, nz = _packed_normal(vertices, 3)
    assert abs(nx) < 1e-6 and abs(ny + 1.0) < 1e-6 and abs(nz) < 1e-6


def test_catalog_smw_mesh_is_split_to_fit_kivy_index_limit():
    from carveracontroller.addons.beds.catalog import plate_by_id
    from carveracontroller.addons.beds.mesh_loader import KIVY_MESH_MAX_INDICES, KIVY_MESH_MAX_VERTICES

    plate = plate_by_id("CA1_SMW_Metric")
    assert plate is not None
    mesh = load_bed_mesh(plate.mesh_path())
    assert len(mesh.indices) > KIVY_MESH_MAX_INDICES

    chunks = pack_bed_mesh_chunks(mesh, scale=1.0, albedo_rgb=(0.5, 0.5, 0.5))
    assert len(chunks) >= 2
    assert sum(len(idx) for _verts, idx in chunks) == len(mesh.indices)
    for vertices, indices in chunks:
        assert len(indices) <= KIVY_MESH_MAX_INDICES
        n_verts = len(vertices) // FLOATS_PER_VERTEX
        assert n_verts == len(indices)
        assert n_verts <= KIVY_MESH_MAX_VERTICES
        assert max(indices) < n_verts


def test_catalog_mdf_fits_one_chunk_with_flat_top_normals():
    from carveracontroller.addons.beds.catalog import plate_by_id
    from carveracontroller.addons.beds.mesh_loader import KIVY_MESH_MAX_INDICES

    plate = plate_by_id("CA1_MDF")
    assert plate is not None
    mesh = load_bed_mesh(plate.mesh_path())
    assert len(mesh.indices) <= KIVY_MESH_MAX_INDICES

    chunks = pack_bed_mesh_chunks(mesh, scale=1.0, albedo_rgb=(0.5, 0.5, 0.5))
    assert len(chunks) == 1
    vertices, indices = chunks[0]
    assert len(indices) == len(mesh.indices)

    top_tris = 0
    for t in range(0, len(mesh.indices) - 2, 3):
        pts = [mesh.positions[mesh.indices[t + k]] for k in range(3)]
        if min(p[2] for p in pts) < -0.5:
            continue
        top_tris += 1
        for k in range(3):
            nx, ny, nz = _packed_normal(vertices, t + k)
            assert abs(nx) < 0.05 and abs(ny) < 0.05
            assert abs(abs(nz) - 1.0) < 0.05
    assert top_tris > 100
