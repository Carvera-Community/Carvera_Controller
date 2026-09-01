"""ObjFile loads meshes that omit the Wavefront `o` object name."""

from carveracontroller.Objloader import ObjFile


def test_objfile_loads_without_object_name(tmp_path):
    path = tmp_path / "anon.obj"
    path.write_text(
        "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 1 1 0\nvn 0 0 1\nf 1//1 2//1 3//1 4//1\n",
        encoding="utf-8",
    )
    obj = ObjFile(str(path))
    assert list(obj.objects) == ["mesh"]
    mesh = obj.objects["mesh"]
    # Quad is fan-triangulated into two triangles (6 verts, 6 indices).
    assert len(mesh.indices) == 6
    assert len(mesh.vertices) == 6 * 8
