"""A site as the input: the sites routes, the source of the maximum volume and the joined file built from the sites."""
import trimesh

from local_web_test_support import VOLUME, read_events, start_run, upload

SITE = {"name": "Site 1", "points": [[0, 0, 100], [40, 0, 102], [40, 30, 106], [0, 30, 101]], "height": 20}
FLAT = {"name": "Site 2", "points": [[50, 0, 100], [70, 0, 100], [70, 20, 100]], "height": 12}


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
    assert reply.json()["sites"] == [taller] and reply.json()["source"] == "mesh"
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
