"""A site as the input: the sites routes, the source of the maximum volume and the joined file built from the sites."""
import pytest
import trimesh
import yaml

from local_web_test_support import VOLUME, read_events, start_run, upload

SITE = {"name": "Site 1", "points": [[0, 0, 100], [40, 0, 102], [40, 30, 106], [0, 30, 101]], "height": 20}
FLAT = {"name": "Site 2", "points": [[50, 0, 100], [70, 0, 100], [70, 20, 100]], "height": 12}


@pytest.fixture(autouse=True)
def per_site_heights(request):
    """The tests of project "p" give each site its own max height and no base: a new project starts global (base 0 m, max 50 m)."""
    if "client_with_inputs" in request.fixturenames:
        client = request.getfixturevalue("client_with_inputs")
        reply = client.put("/api/projects/p/heights", json={"max": {"for_all_sites": False}, "base": {"for_all_sites": True}})
        assert reply.status_code == 200, reply.text


def joined_max_volume(projects_folder, name="p") -> trimesh.Trimesh:
    return trimesh.load(str(projects_folder / name / "inputs" / "joined" / "max_volume.ply"), force="mesh")


def test_a_project_starts_with_the_mesh_files_and_no_site(client_with_inputs):
    reply = client_with_inputs.get("/api/projects/p/sites")
    assert reply.status_code == 200, reply.text
    assert reply.json()["source"] == "mesh" and reply.json()["sites"] == []
    assert reply.json()["joined_bounds"] is not None and reply.json()["grid_plan"] is not None


def test_sites_stored_while_the_mesh_is_the_source_leave_the_maximum_volume_as_it_is(client_with_inputs, projects_folder):
    before = joined_max_volume(projects_folder).bounds.tolist()
    reply = client_with_inputs.put("/api/projects/p/sites", json={"sites": [SITE]})
    assert reply.status_code == 200, reply.text
    assert reply.json()["sites"][0]["points"][2] == [40, 30, 106]
    assert joined_max_volume(projects_folder).bounds.tolist() == before
    assert client_with_inputs.get("/api/projects/p/sites").json()["sites"][0]["name"] == "Site 1"


def test_switching_to_the_sites_builds_the_maximum_volume_from_them_and_puts_the_criteria_out_of_date(client_with_inputs, projects_folder):
    client = client_with_inputs
    assert read_events(client, start_run(client, produce=["thresholding"])["run_id"])[-1]["type"] == "run_finished"
    client.put("/api/projects/p/sites", json={"sites": [SITE, FLAT]})
    reply = client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    assert reply.status_code == 200, reply.text
    assert reply.json()["source"] == "sites"
    assert reply.json()["joined_bounds"] == [[0, 0, 100], [70, 30, 120]]
    mesh = joined_max_volume(projects_folder)
    assert mesh.bounds.tolist() == [[0, 0, 100], [70, 30, 120]]
    status = client.get("/api/projects/p/stage-status").json()
    assert status["criteria"]["1"]["preprocessing"] == "out_of_date"


def test_a_change_of_the_sites_builds_the_maximum_volume_again_and_switching_back_restores_the_files(client_with_inputs, projects_folder):
    client = client_with_inputs
    mesh_bounds = joined_max_volume(projects_folder).bounds.tolist()
    client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    assert not (projects_folder / "p" / "inputs" / "joined" / "max_volume.ply").exists()      # no site yet: no maximum volume
    taller = {**SITE, "height": 30}
    assert client.put("/api/projects/p/sites", json={"sites": [taller]}).status_code == 200
    assert joined_max_volume(projects_folder).bounds[1][2] == 130
    reply = client.put("/api/projects/p/max-volume-source", json={"source": "mesh"})
    assert reply.json()["sites"] == [{**taller, "base_height": None, "original": None, "holes": []}] and reply.json()["source"] == "mesh"
    assert joined_max_volume(projects_folder).bounds.tolist() == mesh_bounds


def test_the_joined_maximum_volume_is_served_once_there_is_one(client_with_inputs):
    client = client_with_inputs
    assert client.get("/api/projects/p/max-volume").status_code == 200
    client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    assert client.get("/api/projects/p/max-volume").status_code == 404
    client.put("/api/projects/p/sites", json={"sites": [SITE]})
    reply = client.get("/api/projects/p/max-volume")
    assert reply.status_code == 200 and len(reply.content) > 1000


def test_a_site_that_cannot_make_a_volume_is_refused_by_name_and_nothing_is_stored(client_with_inputs):
    client = client_with_inputs
    too_low = {**SITE, "name": "Plot B", "height": 4}
    crossing = {"name": "Plot C", "points": [[0, 0, 0], [10, 10, 0], [10, 0, 0], [0, 10, 0]], "height": 5}
    reply = client.put("/api/projects/p/sites", json={"sites": [SITE, too_low, crossing]})
    assert reply.status_code == 422
    detail = reply.json()["detail"]
    assert "Plot B: this site rises 6.00 m, so its height must be more than 6.00 m." in detail
    assert "Plot C: the outline crosses itself." in detail
    assert client.get("/api/projects/p/sites").json()["sites"] == []


def test_a_malformed_site_is_refused_by_the_request_model(client_with_inputs):
    for site in ({**SITE, "points": [[0, 0], [1, 0], [1, 1]]}, {**SITE, "height": 0}, {**SITE, "name": ""}):
        assert client_with_inputs.put("/api/projects/p/sites", json={"sites": [site]}).status_code == 422


def test_a_project_that_uses_its_sites_takes_no_maximum_volume_file(client_with_inputs):
    client = client_with_inputs
    client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    refused = upload(client, "p", "max_volume", VOLUME)
    assert refused.status_code == 422 and "sites" in refused.json()["detail"]
    removal = client.delete("/api/projects/p/inputs/max_volume/" + VOLUME[0])
    assert removal.status_code == 422


def test_a_run_of_a_project_with_the_sites_as_source_and_no_site_is_refused_for_the_missing_maximum_volume(client_with_inputs):
    client = client_with_inputs
    client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    reply = client.post("/api/projects/p/runs", json={"produce": ["thresholding"]})
    assert reply.status_code == 422 and "max_volume" in reply.json()["missing_inputs"]


def test_a_changed_maximum_volume_file_in_the_folder_is_not_joined_while_the_sites_are_the_source(client_with_inputs, projects_folder):
    client = client_with_inputs
    client.put("/api/projects/p/sites", json={"sites": [SITE]})
    client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    stored = projects_folder / "p" / "inputs" / "max_volume" / VOLUME[0]
    box = trimesh.creation.box(extents=(3, 3, 3))
    box.export(str(stored))
    assert client.get("/api/projects/p").status_code == 200       # the open looks for changed files
    assert joined_max_volume(projects_folder).bounds.tolist() == [[0, 0, 100], [40, 30, 120]]


# Heights (design/base-height.md)

def kept_files(projects_folder, name="p"):
    return sorted((projects_folder / name / "inputs" / "joined").glob("kept_volume_*.ply"))


def config_of(projects_folder, name="p") -> dict:
    return yaml.safe_load((projects_folder / name / "config.yaml").read_text(encoding="utf-8"))


def test_a_project_starts_with_each_site_s_own_max_height_and_no_base(client_with_inputs, projects_folder):
    heights = client_with_inputs.get("/api/projects/p/sites").json()["heights"]
    assert heights == {"max": {"for_all_sites": False, "value": None}, "base": {"for_all_sites": True, "value": None}}
    assert kept_files(projects_folder) == [] and "kept_volume_path" not in config_of(projects_folder)


def test_a_base_height_keeps_a_volume_and_puts_only_thresholding_out_of_date(client_with_inputs, projects_folder):
    client = client_with_inputs
    client.put("/api/projects/p/sites", json={"sites": [SITE, FLAT]})
    client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    assert read_events(client, start_run(client, produce=["thresholding"])["run_id"])[-1]["type"] == "run_finished"
    reply = client.put("/api/projects/p/heights", json={"max": {"for_all_sites": False}, "base": {"for_all_sites": True, "value": 8}})
    assert reply.status_code == 200, reply.text
    assert reply.json()["heights"]["base"] == {"for_all_sites": True, "value": 8}
    [kept] = kept_files(projects_folder)
    mesh = trimesh.load(str(kept), force="mesh")
    assert mesh.bounds[1][2] == 108 and mesh.bounds[0][2] < 100        # each site's lowest vertex is at 100
    shown = client.get("/api/projects/p/base-volume")
    assert shown.status_code == 200
    base = trimesh.load(str(projects_folder / "p" / "inputs" / "joined" / "base_volume.ply"), force="mesh")
    assert base.bounds.tolist() == [[0, 0, 100], [70, 30, 108]] and base.is_watertight     # the maximum volume below the base
    assert config_of(projects_folder)["kept_volume_path"] == f"inputs/joined/{kept.name}"
    status = client.get("/api/projects/p/stage-status").json()["criteria"]["1"]
    assert status["preprocessing"] == "current" and status["thresholding"] == "out_of_date"
    assert read_events(client, start_run(client, produce=["thresholding"])["run_id"])[-1]["type"] == "run_finished"
    status = client.get("/api/projects/p/stage-status").json()["criteria"]["1"]
    assert status["preprocessing"] == "current" and status["thresholding"] == "current"
    client.put("/api/projects/p/heights", json={"max": {"for_all_sites": False}, "base": {"for_all_sites": True, "value": 9}})
    assert [path.name for path in kept_files(projects_folder)] != [kept.name] and len(kept_files(projects_folder)) == 1
    client.put("/api/projects/p/heights", json={"max": {"for_all_sites": False}, "base": {"for_all_sites": True, "value": None}})
    assert kept_files(projects_folder) == [] and "kept_volume_path" not in config_of(projects_folder)
    assert client.get("/api/projects/p/base-volume").status_code == 404


def test_a_max_height_not_above_the_base_is_refused_by_site_name_and_nothing_is_stored(client_with_inputs):
    client = client_with_inputs
    client.put("/api/projects/p/sites", json={"sites": [SITE, FLAT]})
    client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    reply = client.put("/api/projects/p/heights", json={"max": {"for_all_sites": False}, "base": {"for_all_sites": True, "value": 15}})
    assert reply.status_code == 422
    assert reply.json()["detail"] == "Site 2: its base height (15 m) must be less than its max height (12 m)."
    assert client.get("/api/projects/p/sites").json()["heights"]["base"]["value"] is None
    per_site = {**FLAT, "base_height": 12}
    stored = client.put("/api/projects/p/sites", json={"sites": [SITE, per_site]})
    assert stored.status_code == 200      # the base is one for all sites (none), so the site's own base does not count
    per_site_base = client.put("/api/projects/p/heights", json={"max": {"for_all_sites": False}, "base": {"for_all_sites": False}})
    assert per_site_base.status_code == 422 and per_site_base.json()["detail"].startswith("Site 2: its base height (12 m)")


def test_a_max_height_for_all_sites_builds_them_at_that_height_and_keeps_their_own(client_with_inputs, projects_folder):
    client = client_with_inputs
    client.put("/api/projects/p/sites", json={"sites": [SITE, FLAT]})
    client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    reply = client.put("/api/projects/p/heights", json={"max": {"for_all_sites": True, "value": 40}, "base": {"for_all_sites": True}})
    assert reply.status_code == 200, reply.text
    assert joined_max_volume(projects_folder).bounds[1][2] == 140
    assert [site["height"] for site in reply.json()["sites"]] == [20, 12]
    back = client.put("/api/projects/p/heights", json={"max": {"for_all_sites": False}, "base": {"for_all_sites": True}})
    assert back.status_code == 200 and joined_max_volume(projects_folder).bounds[1][2] == 120
    assert client.put("/api/projects/p/heights", json={"max": {"for_all_sites": True}, "base": {"for_all_sites": True}}).status_code == 422


def test_a_base_height_with_a_mesh_maximum_volume_is_one_level_above_its_lowest_point(client_with_inputs, projects_folder):
    client = client_with_inputs
    low = joined_max_volume(projects_folder).bounds[0][2]
    client.put("/api/projects/p/heights", json={"max": {"for_all_sites": False}, "base": {"for_all_sites": True, "value": 5}})
    [kept] = kept_files(projects_folder)
    assert trimesh.load(str(kept), force="mesh").bounds[1][2] == low + 5
    base = trimesh.load(str(projects_folder / "p" / "inputs" / "joined" / "base_volume.ply"), force="mesh")
    assert base.bounds[1][2] == low + 5 and base.bounds[0][2] == low
    assert config_of(projects_folder)["kept_volume_path"].endswith(kept.name)


def test_a_new_project_starts_with_global_heights_a_base_of_0_and_a_max_of_50(client, projects_folder):
    assert client.post("/api/projects", json={"name": "fresh", "mode": "daylight"}).status_code in (200, 201)
    heights = client.get("/api/projects/fresh/sites").json()["heights"]
    assert heights == {"max": {"for_all_sites": True, "value": 50.0}, "base": {"for_all_sites": True, "value": 0.0}}
    client.put("/api/projects/fresh/max-volume-source", json={"source": "sites"})
    assert client.put("/api/projects/fresh/sites", json={"sites": [SITE]}).status_code == 200
    assert joined_max_volume(projects_folder, "fresh").bounds[1][2] == 150       # the global 50 m, not the site's own 20 m
    assert kept_files(projects_folder, "fresh") == []


def test_a_base_height_of_0_is_no_lower_limit(client_with_inputs, projects_folder):
    client = client_with_inputs
    client.put("/api/projects/p/sites", json={"sites": [SITE]})
    client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    reply = client.put("/api/projects/p/heights", json={"max": {"for_all_sites": True, "value": 50}, "base": {"for_all_sites": True, "value": 0}})
    assert reply.status_code == 200, reply.text
    assert kept_files(projects_folder) == [] and client.get("/api/projects/p/base-volume").status_code == 404
    assert joined_max_volume(projects_folder).bounds[1][2] == 150
    assert client.put("/api/projects/p/heights", json={"max": {"for_all_sites": True, "value": 0}, "base": {"for_all_sites": True}}).status_code == 422


# ---- Holes and overlaps (design/site-holes.md) ----

def _flat(x0, y0, x1, y1, z=100):
    return [[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]]


def test_a_site_with_a_hole_makes_a_maximum_volume_without_it_and_a_hole_outside_is_refused(client_with_inputs, projects_folder):
    client = client_with_inputs
    client.put("/api/projects/p/max-volume-source", json={"source": "sites"})
    block = {"name": "Block", "points": _flat(0, 0, 40, 30), "holes": [_flat(10, 10, 30, 20)], "height": 20}
    reply = client.put("/api/projects/p/sites", json={"sites": [block]})
    assert reply.status_code == 200, reply.text
    volume = joined_max_volume(projects_folder)
    assert volume.volume == pytest.approx((40 * 30 - 20 * 10) * 20)
    assert not volume.contains([[20, 15, 110]])[0]
    outside = {**block, "holes": [_flat(30, 10, 50, 20)]}
    refused = client.put("/api/projects/p/sites", json={"sites": [outside]})
    assert refused.status_code == 422 and "Block: hole 1 is not strictly inside the outline." in refused.json()["detail"]


def test_the_reply_names_sites_that_overlap_and_a_site_inside_another(client_with_inputs):
    client = client_with_inputs
    sites = [
        {"name": "Block", "points": _flat(0, 0, 40, 30), "height": 20},
        {"name": "Inner", "points": _flat(10, 10, 20, 20), "height": 20},              # wholly inside Block
        {"name": "Across", "points": _flat(35, 5, 60, 25), "height": 20},              # partly over Block
        {"name": "Beside", "points": _flat(60, 0, 80, 30), "height": 20},              # shares an edge with Across only
    ]
    overlaps = client.put("/api/projects/p/sites", json={"sites": sites}).json()["overlaps"]
    assert overlaps == [{"first": 1, "second": 0, "inside": True}, {"first": 0, "second": 2, "inside": False}]
    # A site inside another's hole overlaps nothing
    sites[0]["holes"] = [_flat(5, 5, 25, 25)]
    assert client.put("/api/projects/p/sites", json={"sites": sites}).json()["overlaps"] == [{"first": 0, "second": 2, "inside": False}]
