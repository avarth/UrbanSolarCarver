# Simulate: sun, sky and solar energy on the test surfaces, beside the pipeline

Date: 2026-10-26. Status: draft for the user's review. Replaces the app and service parts of the "Sun and shade check" built on
branch `feature/solar-check` (design `docs/superpowers/specs/2026-10-22-solar-check-design.md` on that branch); keeps its engine.
Background and the user's review of the first build: `vault/features/solar-check-of-result.md`.

Marking: **(user)** for what the user asked for or decided, **(proposed)** for a call made here that the user has not confirmed.

## 1. Intent

A designer carves an envelope to protect sun, sky or solar energy on test surfaces. Simulate shows how much of it actually reaches
each test point past the maximum volume (before) and past the carved envelope or the building massing (after), on meshes rather
than voxels, so the designer can see whether the carving did what it should. It is a quick check while designing, inside USC. It
does not replace the outcome validation with an external tool (`vault/features/validation.md`) **(user)**.

The first build put the check in the pipeline as step 6, with a long settings panel, a results table in the sidebar and choices
that were hard to read ("Geometries to compare" with "Compare with"). The user rejected that integration on 2026-10-23 and asked
for a tool that is "somewhat detached and independent from the whole pipeline" and does not add to the side panel **(user,
2026-10-26)**.

## 2. Goals, non-goals

Goals:
- A Simulate workspace beside the pipeline, reached from the header, that leaves the pipeline as it is.
- Studies (a metric, a period, test surface files) the user adds, edits and runs on demand.
- Before and after on the test surfaces: maximum volume, envelope, massing, and the change from the maximum volume.
- Results on the 3D view: colours, a legend with a target, a small result card.

Non-goals for this build (milestone 2) **(user)**:
- Studies on other designs (meshes added only for Simulate), generic solar studies on any geometry.
- Snapshots, "Export results" (CSV).
- Side by side views with linked cameras **(proposed, user to confirm)**.
- A `usc check` CLI command and a Grasshopper component.

Anti-goals: a Simulate change that makes a pipeline stage out of date; a run that starts by itself; settings the user must scroll
through to reach Run.

## 3. The workspace

- **Design | Simulate**, a two-way switch in the header next to the project name **(user** for detached, **proposed** for the
  switch). Simulate hides the pipeline sidebar and gives the 3D view the whole window. Design shows the step the user left, with
  its fold and scroll state.
- **Studies panel**: small, floating over the top left of the view, collapsible to an icon. One row per study: colour swatch,
  name, a short line (its test surface files, or "Out of date", "Not run yet"). A row's settings open in a popover beside it. At
  the bottom: **Add study** and **Run** **(user)**.
- **Geometry switch** at the top centre of the view: Max volume | Envelope | Massing, the last two greyed (with the reason as a
  tooltip) until they are built. Beside it a **Change** toggle: colours each point by its change from the maximum volume
  **(user)**. The baseline is always the maximum volume **(proposed, user to confirm)**.
- **Legend** along the bottom of the view, in the selected study's unit, with the **target** as a draggable mark. Points below the
  target are drawn in one muted colour. The target is stored with the study **(user)**.
- **Result card** in the bottom right corner, for the selected study and the geometry shown: mean, lowest tenth (10th percentile),
  share of points at or above the target, each with the maximum volume's value beside it, for example "mean 3.6 h (4.1)" **(user)**.
- The Layers menu and the viewer tools stay as in Design. Test surfaces of other studies and criteria are not drawn; the context
  and terrain are.
- **One study on the view at a time**: the selected row colours its test surfaces **(user)**.
- **Less text** **(user)**: no descriptions in the panel or popover; labels with units and tooltips naming the setting.

## 4. Studies

A study is stored in `project.json` apart from the criteria, under `studies` (an ordered list) **(user)**:

| Field | Meaning |
|---|---|
| `id` | stable, as a criterion's id |
| `name`, `named_by_user` | default from the metric and the period, for example "Sun hours, 21 Dec" **(proposed)** |
| `colour` | from the criteria palette, the next unused one **(proposed)** |
| `metric` | one of the metrics in section 5 |
| `settings` | the period and the mode settings the metric reads (benefit balance temperature and so on) |
| `target` | a number in the metric's unit, or none |
| `test_surface_files` | file names in the project's test surface store |

**Add study** offers, in one menu, the criteria as shortcuts ("Like Winter sun on facades" copies the criterion's metric
default, period, mode settings and files) and the plain metrics (empty files, the metric's default period). No link to the
criterion is kept **(user)**.

The popover of a study holds: name, metric (a select, the ones that need a missing weather file greyed with the reason), the
period (the period control of the Criteria step), the metric's few mode settings in a fold, and the test surface files box
**(user)**.

**Test surface files of its own (user: option b, built last, may move to milestone 2 if it runs long).** A study can use a file
the project stores already (a criterion's) and can add new files. The project's test surface store stays one store; a file is in
use while a criterion or a study lists it. Removing a file from a study, deleting a study, removing it from a criterion or
deleting a criterion discards the stored file only when nothing lists it any more. Replacing a stored file makes the criteria that
use it out of date (as now) and the studies that use it out of date.

Running or editing a study never changes a criterion, the shared settings or a pipeline stage's state **(user)**.

## 5. Metrics

As in the first build: the carving mode's quantity by default, any metric whose inputs exist can be chosen **(user, 2026-10-22)**.

| Metric | Default for mode | Unit | Needs weather file |
|---|---|---|---|
| Sun hours | time-based | h | yes |
| Solar energy (incident) | irradiance | kWh/m² | yes |
| Useful solar energy | benefit | kWh/m² | yes |
| Sky component, overcast (vertical sky component on a facade) | daylight | % | no |
| Cooling sky | radiative_cooling | % | no |
| Sky view factor | tilted_plane | % | no |

Definitions, normalisation (sky metrics as a percentage of an unobstructed horizontal surface) and the incidence cosine are as in
the first build's design, section 3, and its engine. Ground reflection is left out **(user, 2026-10-22)**.

Changes from the first build:
- **One sun position per hour** for sun hours, fixed and hidden **(user, 2026-10-23)**; each visible position counts 1 h.
- **Sky: Tregenza (145 patches)**, fixed and hidden **(user, 2026-10-23)**. Rays per patch: the user asked for 1, hidden. One ray
  per patch centre leaves the 12° gaps that caused banding in the carving (2026-10-25); the carving now traces jittered sub-rays.
  Simulate reuses the carving's sub-rays (`sky_patches.sub_ray_directions`, `ray_tracing.SkySubRays`) at the project's
  `rays_per_patch` (default 4), still hidden, instead of its own patch cells **(proposed, user to confirm)**.
- **Test points**: sampled from the study's test surfaces at the carving's spacing (`resolve_grid_step` of the shared settings) in
  the maximum volume's frame, hidden **(user)**. At most 2 million points; above that the study is refused with the spacing that
  fits, as before.

## 6. Geometry and blocking

- **Before**: the maximum volume mesh as added (not its voxels) **(user)**.
- **After**: the envelope mesh that Build envelope wrote and the massing mesh, each clipped by the maximum volume, with the first
  build's rules for own facades, skins and the clip (its design, section 5) **(user** for meshes**)**.
- **Context and terrain** block in every geometry, before and after alike, through the pipeline's own inputs (`context`,
  `terrain` roles; `context_geometry.build_blocking_mesh`). The first build's separate `surroundings` input is dropped **(user)**.
- With chained criteria the envelope is the result of the whole chain; Simulate checks that, not one criterion's pass
  **(proposed)**.

## 7. Running

- **Run** runs every study (not one per row) for every geometry that is built: the maximum volume always, the envelope and the
  massing when they exist. Switching geometry afterwards needs no rerun **(user)**.
- **One GPU job at a time** **(user)**. While a Design run is going, Run in Simulate shows that a Design run is going and stays
  unavailable until it ends; while a simulation runs, Design's run buttons say the same. Nothing is queued.
- A simulation is a run of the run worker (progress, cancel, events, as any run), of one stage, `simulate`, outside
  `PIPELINE_STAGES` so it never counts toward a pipeline stage's state **(proposed)**.
- **Out of date**: a study's result is out of date when its settings, its files, the weather file, the context, the terrain, the
  maximum volume, or a geometry mesh it traced changed since (fingerprints as in the first build). The result stays shown, dimmed,
  with the pipeline's "Out of date" stamp. No automatic rerun **(user)**.
- **On disk**: `<project>/simulate/<study id>/` with the points, the values per geometry and a summary JSON (the first build's
  `check_points.npz`, `check_values.npz`, `check_summary.json`). Reopening the project shows the last results **(user)**.

## 8. Service (proposed shape)

- `GET /projects/{name}/studies`: the studies with their state (current, out of date, not run, refused with a reason), the metrics
  with availability and default periods.
- `POST /projects/{name}/studies` (from a metric, or from a criterion id), `PATCH /projects/{name}/studies/{id}` (name, metric,
  settings, target), `DELETE /projects/{name}/studies/{id}`, `PUT /projects/{name}/studies/order`.
- Test surface files of a study: `POST`, `PUT .../{file_name}`, `DELETE .../{file_name}` under `/projects/{name}/studies/{id}/test-surfaces`,
  as the criteria's routes; the store's "in use" rule counts studies (section 4).
- `POST /projects/{name}/simulate`: runs the studies; 409 while a run is active.
- `GET /projects/{name}/studies/{id}/values`: the patches and the per-point values of each geometry as one binary, as the first
  build's values route.
- Changing a study or its files does not raise `inputs_revision`.

## 9. App

- The header switch and a Simulate workspace component beside `ProjectWorkspace`, sharing the viewer scene. `ProjectWorkspace.tsx`
  (about 580 lines) is split before this work, as the phase 3 review asked.
- A study layer in the viewer: the selected study's test point patches coloured by value (cividis from 0 to the highest value of
  the geometry shown) or by change (the first build's change ramp, losses in the carved colour), and the geometry shown drawn
  (envelope see-through). Hover labels as before.
- The change tolerance is computed once per geometry, not once per point: the first build's `changeTolerance` loop scanned the
  whole column per point (about 2.8e11 steps on District) and froze the browser **(fix)**.
- Messages follow the app's copy rules: plain labels, units beside numbers, no descriptions.

## 10. From the branch

- Keep, rebased onto `main`: `solar_check.py`, `check_settings.py`, the Warp mesh kernels in `warp_kernels.py`, their tests
  (`tests/test_solar_check.py`), the engine request `check`. Change: one sun position per hour, Tregenza with the carving's
  sub-rays, context and terrain in place of surroundings, no design columns.
- Rewrite: the service routes (`sun_check.py`) and the app (`CheckStep.tsx`, `sun_check_state.ts`) for studies and the workspace.
- Drop: commit `4c1f58d` ("wip:") as such; the `surroundings` and `check_designs` roles.
- The work starts on a new branch from `main`; `feature/solar-check` stays as a source until this is merged, then is deleted.

## 11. Verification

- Engine: the first build's tests (unobstructed values, the infinite wall, sun hours against a ray-box test, own facades, skins,
  the clip, Ladybug `RadiationStudy` to 1e-4 at one ray per patch) still pass; a new test that context and terrain block.
- Service: a study never changes a pipeline stage's state; the shared store keeps a file a study uses when its criterion is
  deleted, and the reverse; Run is refused while a Design run is active; results survive reopening; out of date after each input
  in section 7 changes.
- App: Design and Simulate keep their state across switches; the geometry switch, Change, target and result card; one study shown
  at a time; Run unavailable during a Design run; the change view on District's 527,633 points without freezing.
- In the browser on a copy of Allatini (three criteria, context): a study from each criterion, before and after on envelope and
  massing.
- User documentation: `docs/simulate.md` and the Simulate section of `docs/ui.md`.

## 12. Calls left to the builder

Names of components and files; the popover layout; the colour of points below the target; how the collapsed panel looks; the
exact study default names.
