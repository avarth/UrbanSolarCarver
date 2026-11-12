"""Sites imported from DXF and OBJ files, Place on terrain's heights, and DXF mesh inputs in the service (design/site-import.md)."""
import io

import ezdxf
import pytest
import trimesh

from local_web_test_support import upload

SQUARE = [(0, 0), (20, 0), (20, 15), (0, 15)]


def _dxf_bytes(build) -> bytes:
    document = ezdxf.new("R2010")
    document.header["$INSUNITS"] = 6
    build(document.modelspace())
    stream = io.StringIO()
    document.write(stream)
    return stream.getvalue().encode("utf-8")


def _import(client, file_name, data, name="p"):
    return client.post(f"/api/projects/{name}/outlines", files={"file": (file_name, data, "application/octet-stream")})


def test_a_flat_outline_lands_on_the_drawing_level_and_the_file_is_kept(client_with_inputs, projects_folder):
    data = _dxf_bytes(lambda space: space.add_lwpolyline(SQUARE, close=True, dxfattribs={"layer": "Plots", "elevation": 0}))
    reply = _import(client_with_inputs, "my plots.dxf", data)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["file"] == "myplots.dxf" and body["unit"] == "metres" and body["left_out"] == []
    [outline] = body["outlines"]
    assert outline["name"] == "Plots" and outline["area"] == pytest.approx(300) and outline["rise"] == 0
    assert outline["points"] == [[x, y, 0.0] for x, y in SQUARE]      # no sites, no surroundings: the level is 0
    assert (projects_folder / "p" / "inputs" / "sites" / "myplots.dxf").read_bytes() == data
    assert client_with_inputs.get("/api/projects/p/sites").json()["sites"] == []     # nothing added


def test_survey_elevations_become_heights_above_the_lowest_vertex_of_the_file(client_with_inputs):
    def build(space):
        space.add_polyline3d([(0, 0, 312), (20, 0, 313), (20, 15, 315), (0, 15, 312)], close=True)
        space.add_polyline3d([(30, 0, 315), (50, 0, 315), (50, 15, 315)], close=True)
    client = client_with_inputs
    client.put("/api/projects/p/sites", json={"sites": [{"name": "Old", "points": [[-50, -50, 7], [-40, -50, 7], [-40, -40, 7]], "height": 10}]})
    outlines = _import(client, "survey.dxf", _dxf_bytes(build)).json()["outlines"]
    assert [point[2] for point in outlines[0]["points"]] == [7, 8, 10, 7]      # on the lowest site, at 7 m
    assert {point[2] for point in outlines[1]["points"]} == {10}                 # 3 m above the first, as in the file
    assert outlines[0]["rise"] == 3


def test_open_polylines_and_refused_outlines_are_left_out_by_name(client_with_inputs):
    def build(space):
        space.add_lwpolyline(SQUARE, close=True, dxfattribs={"layer": "Good"})
        space.add_lwpolyline([(0, 0), (5, 0), (5, 5)], close=False)
        space.add_lwpolyline([(0, 0), (10, 10), (10, 0), (0, 10)], close=True, dxfattribs={"layer": "Bow tie"})
    body = _import(client_with_inputs, "plots.dxf", _dxf_bytes(build)).json()
    assert [outline["name"] for outline in body["outlines"]] == ["Good"]
    assert body["left_out"] == ["1 open polyline", "Bow tie: the outline crosses itself"]


def test_a_file_with_no_closed_polyline_or_of_another_type_is_refused(client_with_inputs):
    reply = _import(client_with_inputs, "lines.dxf", _dxf_bytes(lambda space: space.add_line((0, 0), (1, 1))))
    assert reply.status_code == 422 and "No closed polylines in lines.dxf" in reply.json()["detail"]
    reply = _import(client_with_inputs, "plots.ply", b"ply\n")
    assert reply.status_code == 422 and "DXF or OBJ" in reply.json()["detail"]


def test_obj_polylines_are_imported(client_with_inputs):
    data = b"o Plot A\nv 0 0 0\nv 20 0 0\nv 20 15 0\nv 0 15 0\nl 1 2 3 4 1\n"
    body = _import(client_with_inputs, "plots.obj", data).json()
    assert body["outlines"][0]["name"] == "Plot A" and len(body["outlines"][0]["points"]) == 4


def test_outlines_far_from_the_other_inputs_say_how_far(client_with_inputs):
    far = [(x + 5000, y) for x, y in SQUARE]
    body = _import(client_with_inputs, "far.dxf", _dxf_bytes(lambda space: space.add_lwpolyline(far, close=True))).json()
    assert body["distance_from_inputs"] == pytest.approx(4995)        # the max volume reaches x = 5
    near = _import(client_with_inputs, "near.dxf", _dxf_bytes(lambda space: space.add_lwpolyline(SQUARE, close=True))).json()
    assert near["distance_from_inputs"] is None


def test_an_imported_site_keeps_its_original(client_with_inputs):
    original = {"file": "plots.dxf", "points": [[0, 0, 0], [20, 0, 0], [20, 15, 0], [0, 15, 0]]}
    site = {"name": "Plots", "points": [[0, 0, 0], [20, 0, 0], [20, 15, 2], [0, 15, 0]], "height": 10, "original": original}
    reply = client_with_inputs.put("/api/projects/p/sites", json={"sites": [site]})
    assert reply.status_code == 200, reply.text
    assert client_with_inputs.get("/api/projects/p/sites").json()["sites"][0]["original"] == {**original, "holes": []}


def _terrain_bytes() -> bytes:
    """A plane sloping up 1 m per 10 m in x, from x = -100 to 100, at z = 50 at x = 0."""
    plane = trimesh.Trimesh(vertices=[[-100, -100, 40], [100, -100, 60], [100, 100, 60], [-100, 100, 40]], faces=[[0, 1, 2], [0, 2, 3]])
    return plane.export(file_type="ply")


def test_terrain_heights_are_the_top_of_the_terrain_under_each_point(client_with_inputs):
    client = client_with_inputs
    assert client.post("/api/projects/p/terrain-heights", json={"points": [[0, 0]]}).status_code == 404     # no terrain yet
    assert upload(client, "p", "terrain", ("ground.ply", _terrain_bytes())).status_code == 200
    reply = client.post("/api/projects/p/terrain-heights", json={"points": [[0, 0], [50, 20], [500, 0]]})
    assert reply.status_code == 200, reply.text
    heights = reply.json()["heights"]
    assert heights[0] == pytest.approx(50) and heights[1] == pytest.approx(55) and heights[2] is None


def test_a_drawing_level_follows_the_terrain_for_the_first_sites(client_with_inputs):
    client = client_with_inputs
    upload(client, "p", "terrain", ("ground.ply", _terrain_bytes()))
    outline = _import(client, "plots.dxf", _dxf_bytes(lambda space: space.add_lwpolyline(SQUARE, close=True))).json()["outlines"][0]
    assert outline["points"][0][2] == pytest.approx(40)       # the terrain's lowest level


def test_a_dxf_mesh_is_an_input_and_a_dxf_of_outlines_is_refused_with_a_pointer_to_import(client_with_inputs):
    def faces(space):
        face = space.add_polyface()
        corners = [(-20, -20, 0), (-10, -20, 0), (-10, -10, 0), (-20, -10, 0), (-20, -20, 6), (-10, -20, 6), (-10, -10, 6), (-20, -10, 6)]
        for quad in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
            face.append_face([corners[index] for index in quad])
    reply = upload(client_with_inputs, "p", "context", ("block.dxf", _dxf_bytes(faces)))
    assert reply.status_code == 200, reply.text
    reply = upload(client_with_inputs, "p", "context", ("plots.dxf", _dxf_bytes(lambda space: space.add_lwpolyline(SQUARE, close=True))))
    assert reply.status_code == 422
    assert reply.json()["detail"].startswith("plots.dxf has polylines but no faces")
    assert reply.json()["detail"].endswith("use Import in the Sites box.")


# ---- Nesting into holes (design/site-holes.md) ----

def _rectangle(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_an_outline_inside_another_is_its_hole_and_one_inside_the_hole_is_a_site_again(client_with_inputs):
    def build(space):
        space.add_lwpolyline(_rectangle(0, 0, 60, 40), close=True, dxfattribs={"layer": "Block"})
        space.add_lwpolyline(_rectangle(10, 10, 50, 30), close=True, dxfattribs={"layer": "Courtyard"})
        space.add_lwpolyline(_rectangle(20, 15, 30, 25), close=True, dxfattribs={"layer": "Pavilion"})
    body = _import(client_with_inputs, "block.dxf", _dxf_bytes(build)).json()
    assert body["left_out"] == []
    assert [(outline["name"], len(outline["holes"])) for outline in body["outlines"]] == [("Block", 1), ("Pavilion", 0)]
    block = body["outlines"][0]
    assert block["holes"][0] == [[x, y, 0.0] for x, y in _rectangle(10, 10, 50, 30)]
    assert block["area"] == pytest.approx(60 * 40 - 40 * 20)
    # The block with its courtyard is a site the service accepts as it is
    site = {"name": "Block", "points": block["points"], "holes": block["holes"], "height": 20}
    reply = client_with_inputs.put("/api/projects/p/sites", json={"sites": [site]})
    assert reply.status_code == 200, reply.text
    assert reply.json()["overlaps"] == []


def test_outlines_that_partly_overlap_stay_two_sites(client_with_inputs):
    def build(space):
        space.add_lwpolyline(_rectangle(0, 0, 30, 20), close=True, dxfattribs={"layer": "A"})
        space.add_lwpolyline(_rectangle(20, 5, 50, 15), close=True, dxfattribs={"layer": "B"})
    body = _import(client_with_inputs, "two.dxf", _dxf_bytes(build)).json()
    assert [(outline["name"], outline["holes"]) for outline in body["outlines"]] == [("A", []), ("B", [])]


def test_holes_that_touch_each_other_are_left_out_and_the_outline_stays_a_site(client_with_inputs):
    def build(space):
        space.add_lwpolyline(_rectangle(0, 0, 60, 40), close=True, dxfattribs={"layer": "Block"})
        space.add_lwpolyline(_rectangle(10, 10, 30, 30), close=True, dxfattribs={"layer": "West"})
        space.add_lwpolyline(_rectangle(30, 10, 50, 30), close=True, dxfattribs={"layer": "East"})
    body = _import(client_with_inputs, "touching.dxf", _dxf_bytes(build)).json()
    assert [(outline["name"], outline["holes"]) for outline in body["outlines"]] == [("Block", [])]
    assert body["left_out"] == ["the holes of Block: hole 1 and hole 2 touch or cross"]
