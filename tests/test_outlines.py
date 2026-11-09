"""Outlines from DXF and OBJ files, and the faces of DXF files for mesh inputs (outlines.py, design/site-import.md)."""
import ezdxf
import numpy as np
import pytest
from ezdxf import units

from urbansolarcarver.errors import InputError
from urbansolarcarver.io import load_mesh
from urbansolarcarver.outlines import ARC_TOLERANCE, read_outlines

SQUARE = [(0, 0), (20, 0), (20, 15), (0, 15)]


def _document(insunits=units.M):
    document = ezdxf.new("R2010")
    document.header["$INSUNITS"] = insunits
    return document


def _save(document, tmp_path, name="plots.dxf"):
    path = tmp_path / name
    document.saveas(path)
    return path


def test_closed_lwpolyline_takes_its_elevation_and_layer(tmp_path):
    document = _document()
    polyline = document.modelspace().add_lwpolyline(SQUARE, close=True, dxfattribs={"layer": "Plots", "elevation": 55.5})
    assert polyline.closed
    found = read_outlines(_save(document, tmp_path))
    assert [outline.name for outline in found.outlines] == ["Plots"]
    assert found.outlines[0].points == tuple((x, y, 55.5) for x, y in SQUARE)
    assert found.unit == "metres" and found.left_out == []


def test_3d_polyline_keeps_each_vertex_elevation(tmp_path):
    document = _document()
    points = [(0, 0, 100), (20, 0, 102), (20, 15, 104), (0, 15, 101)]
    document.modelspace().add_polyline3d(points, close=True)
    found = read_outlines(_save(document, tmp_path))
    assert np.allclose(found.outlines[0].points, points)


def test_a_polyline_that_ends_on_its_start_is_closed_and_the_repeat_dropped(tmp_path):
    document = _document()
    document.modelspace().add_lwpolyline([*SQUARE, SQUARE[0]], close=False)
    found = read_outlines(_save(document, tmp_path))
    assert len(found.outlines[0].points) == 4


def test_open_polylines_and_other_entities_are_counted_as_left_out(tmp_path):
    document = _document()
    space = document.modelspace()
    space.add_lwpolyline(SQUARE, close=True)
    space.add_lwpolyline([(0, 0), (5, 0), (5, 5)], close=False)
    space.add_lwpolyline([(10, 0), (15, 0), (15, 5)], close=False)
    space.add_line((0, 0), (1, 1))
    space.add_circle((0, 0), 3)
    found = read_outlines(_save(document, tmp_path))
    assert len(found.outlines) == 1
    assert sorted(found.left_out) == ["1 circle", "1 line", "2 open polylines"]


def test_a_file_without_closed_polylines_is_refused(tmp_path):
    document = _document()
    document.modelspace().add_line((0, 0), (1, 1))
    with pytest.raises(InputError, match="No closed polylines in plots.dxf"):
        read_outlines(_save(document, tmp_path))


def test_outlines_on_one_layer_are_numbered(tmp_path):
    document = _document()
    space = document.modelspace()
    for shift in (0, 30, 60):
        space.add_lwpolyline([(x + shift, y) for x, y in SQUARE], close=True, dxfattribs={"layer": "Plots"})
    space.add_lwpolyline([(x, y + 40) for x, y in SQUARE], close=True, dxfattribs={"layer": "Park"})
    names = [outline.name for outline in read_outlines(_save(document, tmp_path)).outlines]
    assert names == ["Plots 1", "Plots 2", "Plots 3", "Park"]


def test_millimetres_become_metres(tmp_path):
    document = _document(units.MM)
    document.modelspace().add_lwpolyline([(x * 1000, y * 1000) for x, y in SQUARE], close=True, dxfattribs={"elevation": 2500})
    found = read_outlines(_save(document, tmp_path))
    assert found.unit == "millimetres"
    assert np.allclose(found.outlines[0].points, [(x, y, 2.5) for x, y in SQUARE])


def test_a_drawing_without_a_unit_is_read_as_metres(tmp_path):
    document = _document(0)
    document.modelspace().add_lwpolyline(SQUARE, close=True)
    found = read_outlines(_save(document, tmp_path))
    assert found.unit == "metres" and found.outlines[0].points[1] == (20.0, 0.0, 0.0)


def test_a_bulge_becomes_segments_close_to_the_arc(tmp_path):
    document = _document()
    # A half circle of radius 10 centred on (10, 0): a bulge of magnitude 1 on the segment from (20, 0) back to (0, 0)
    document.modelspace().add_lwpolyline([(0, 0, 0), (0, 10, 0), (20, 10, 0), (20, 0, -1)], format="xyb", close=True)
    ring = np.asarray(read_outlines(_save(document, tmp_path)).outlines[0].points)
    assert len(ring) > 10
    on_arc = ring[np.abs(ring[:, 1]) > 1e-6]
    on_arc = on_arc[np.abs(on_arc[:, 1] - 10) > 1e-6]     # not the corners at y = 10
    assert len(on_arc) > 5
    assert np.allclose(np.hypot(on_arc[:, 0] - 10, on_arc[:, 1]), 10, atol=ARC_TOLERANCE)     # vertices near the arc
    middles = (on_arc[1:] + on_arc[:-1]) / 2
    assert np.all(10 - np.hypot(middles[:, 0] - 10, middles[:, 1]) <= ARC_TOLERANCE)              # segments near it too


def test_outlines_in_a_block_are_read_with_its_transform(tmp_path):
    document = _document()
    block = document.blocks.new("PLOT")
    block.add_lwpolyline(SQUARE, close=True, dxfattribs={"layer": "Plots"})
    document.modelspace().add_blockref("PLOT", (100, 200, 5))
    points = read_outlines(_save(document, tmp_path)).outlines[0].points
    assert points[0] == (100.0, 200.0, 5.0) and points[2] == (120.0, 215.0, 5.0)


def test_polyface_meshes_in_an_outline_file_are_left_out(tmp_path):
    document = _document()
    space = document.modelspace()
    space.add_lwpolyline(SQUARE, close=True)
    face = space.add_polyface()
    face.append_face([(0, 0, 0), (1, 0, 0), (1, 1, 0)])
    assert read_outlines(_save(document, tmp_path)).left_out == ["1 mesh"]


def test_obj_line_elements_closed_by_repeating_their_first_index(tmp_path):
    path = tmp_path / "plots.obj"
    path.write_text("o Plot A\nv 0 0 100\nv 20 0 101\nv 20 15 102\nv 0 15 101\nl 1 2 3 4 1\n"
                    "o Path\nv 50 0 0\nv 60 0 0\nv 60 5 0\nl 5 6 7\n"
                    "g Plot B\nv 100 0 3\nv 110 0 3\nv 110 10 3\nl -3 -2 -1 -3\n"
                    "f 1 2 3\n", encoding="utf-8")
    found = read_outlines(path)
    assert [outline.name for outline in found.outlines] == ["Plot A", "Plot B"]
    assert found.outlines[0].points == ((0, 0, 100), (20, 0, 101), (20, 15, 102), (0, 15, 101))
    assert found.outlines[1].points[0] == (100.0, 0.0, 3.0)
    assert found.left_out == ["1 open polyline", "plots.obj has faces: it was read for its polylines only"]


def test_another_file_type_is_refused(tmp_path):
    path = tmp_path / "plots.ply"
    path.write_text("ply\n", encoding="utf-8")
    with pytest.raises(InputError, match="DXF or OBJ"):
        read_outlines(path)


# ---- DXF faces for mesh inputs ---------------------------------------------------------------------------------------------------

def test_load_mesh_reads_dxf_3dfaces_polyfaces_and_meshes_in_metres(tmp_path):
    document = _document(units.CM)
    space = document.modelspace()
    space.add_3dface([(0, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0)])          # a quad: 2 triangles
    space.add_3dface([(0, 0, 0), (100, 0, 0), (0, 0, 100), (0, 0, 100)])            # a triangle (last corner repeated)
    face = space.add_polyface()
    face.append_face([(200, 0, 0), (300, 0, 0), (300, 100, 0)])
    mesh_entity = space.add_mesh()
    with mesh_entity.edit_data() as data:
        data.vertices = [(400, 0, 0), (500, 0, 0), (500, 100, 0), (400, 100, 0)]
        data.faces = [(0, 1, 2, 3)]
    mesh = load_mesh(str(_save(document, tmp_path, "context.dxf")), fix_normals=False)
    assert len(mesh.faces) == 2 + 1 + 1 + 2
    assert np.allclose(mesh.bounds, [[0, 0, 0], [5, 1, 1]])


def test_load_mesh_refuses_a_dxf_of_outlines(tmp_path):
    document = _document()
    document.modelspace().add_lwpolyline(SQUARE, close=True)
    with pytest.raises(InputError, match="has polylines but no faces"):
        load_mesh(str(_save(document, tmp_path, "plots.dxf")))


def test_load_mesh_reads_a_closed_dxf_box_as_watertight(tmp_path):
    document = _document()
    face = document.modelspace().add_polyface()
    corners = [(0, 0, 0), (2, 0, 0), (2, 3, 0), (0, 3, 0), (0, 0, 4), (2, 0, 4), (2, 3, 4), (0, 3, 4)]
    for quad in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
        face.append_face([corners[index] for index in quad])
    mesh = load_mesh(str(_save(document, tmp_path, "box.dxf")))
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(24.0)
