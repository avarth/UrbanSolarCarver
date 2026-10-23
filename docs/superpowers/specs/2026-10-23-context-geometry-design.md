# Context geometry: design

Date: 2026-10-23. Status: for review by the user. Decisions marked **(user)** were made by the user in conversation;
those marked **(proposed)** are the designer's calls and can be changed by the user or settled by the builder.

## 1. Intent

Urban Solar Carver (USC) carves a maximum building volume so that test surfaces keep their sun or sky. Today the
engine sees only the maximum volume and the test surfaces. Existing buildings, large trees and terrain around (or
inside) the site are not modelled. Two consequences:

- **Over-carving.** A voxel can be scored as an obstruction for a ray that an existing neighbour blocks anyway.
  Carving it gains no sun or sky and loses buildable volume. In dense streets this is most marked on lower floors.
- **No true baseline.** Any later check of performance (the parked Simulate tool) cannot show the real current
  situation, because the surroundings that already shade the test surfaces are missing.

This feature adds **context geometry** as an optional input: opaque meshes that block rays and are never carved. It
is the input most other planned features depend on (Simulate's "now" scene, views, baseline comparisons, energy).

## 2. Goals, non-goals, anti-goals

Goals:

1. An optional input, **context**, next to the maximum volume and the test surfaces, in the CLI/config, the Python
   API, the browser app and Grasshopper **(user)**.
2. In the ray-based modes (time-based, irradiance, benefit, daylight, radiative_cooling), every ray from a test point
   that hits context is dropped before scoring: that sun or sky is already lost, so no voxel is blamed for it **(user)**.
3. Voxels of the maximum volume that intersect context are removed from the buildable mass before scoring. Context is
   assumed to stay in place whatever is built on the site (example: a chimney kept in a brownfield regeneration)
   **(user)**.
4. The angle rule (`tilted_plane`) ignores context for its planes; only the intersecting voxels are removed **(user)**.
5. The run report states what context did: voxels removed from the maximum volume, and the share of rays (and of ray
   weight) it blocked **(proposed)**.
6. A separate optional **terrain** input that blocks rays like context but removes only the voxels below the ground,
   so a sloping site stays buildable above it **(user)**.
7. Whole voxel columns go wherever context overlaps the maximum volume: no building over, under or beside kept
   context within its columns **(user)**.

Non-goals for this version:

- Simulate / the sun and shade check (parked on branch `feature/solar-check`, to be reworked on top of this feature).
- Partial transparency (tree leaf cover, seasonal transmittance): context is opaque **(user: "we're playing it safe")**.
- Importing context from OpenStreetMap (milestone 2, vault note `features/osm-site-import`).
- New real-world example projects (a separate, prioritised follow-up; see section 8).
- Repairing or simplifying context meshes ("not a geometry doctor", standing UI preference).

Anti-goals (a failure even if it works):

- Context that is carved, scored, or changes shape in any output.
- A test surface lying on a context building blocked by its own building's face.
- A run without context that gives different results from today's engine (bit-for-bit, or within the existing test
  tolerances).
- Context offered late in the pipeline (as the parked check branch's "Surroundings" option did): it is an input.

## 3. What context is

**(user)** Buildings and large trees, and terrain (which can block sky and sun). **Not** context: shading elements of
lesser importance such as balconies, external shading devices and billboards. Context may lie partly or wholly inside
the maximum volume, and may extend far beyond the voxel grid.

**Terrain is a separate input** **(user)**, because the column rule of 4.2 would otherwise clear every column that a
sloping ground touches. Terrain blocks rays exactly like context (4.3) but removes **only the voxels below the ground**,
never whole columns (4.2).

## 4. Behaviour

### 4.1 Input

- Config key `context_path` (path to one mesh file, possibly several bodies), optional, default none **(proposed
  name)**. Same file formats and the same loading path as `max_volume_path` and `test_surface_path`.
- Config key `terrain_path` (one mesh, usually an open sheet), optional, default none **(separate input: user; name
  proposed)**. Same formats.
- Context is not sampled for test points. If context buildings also carry protected facades, those facades are given
  as test surfaces, as today (the OSM idea of milestone 2 generates both from one source).
- No context, or an empty file: identical behaviour to today.

### 4.2 Effect on the voxel grid

- After voxelizing the maximum volume, voxelize the context on the **same lattice** and clear those voxels from the
  maximum volume's occupancy, in every mode **(user)**.
- "Intersecting" means **the voxel's centre lies inside a closed context body** **(designer's call)**. The maximum
  volume's own rule (centre inside by parity vote, or the surface passing through the voxel) is not reused for
  context: where context shares a face with the maximum volume (party walls, a maximum volume standing on terrain),
  the surface-through rule would remove a one-voxel strip that belongs to the site. Only the part of the context
  inside the grid matters here.
- **Only closed (watertight) context bodies remove voxels** **(designer's call)**. Open context bodies (a tree drawn
  as surfaces, a city-model shell that is not watertight) only block rays (4.3), which works on open meshes. The run
  report and the app say how many context bodies were open and therefore block rays only, without repairing them
  ("not a geometry doctor"). Overlapping closed bodies are voxelized per body and combined, so an overlap (a context
  building extruded below the ground) does not flip the parity.
- **Terrain removes only what lies below ground** **(user)**: for each column, the ground height is where the terrain
  surface crosses the column's vertical centre line (the highest crossing if there are several); voxels whose centre
  lies below it are removed and the rest of the column stays buildable. This works for an open terrain sheet. A column
  the terrain does not cover keeps all its voxels. The column rule below does not apply to terrain.
- **Whole columns go** **(user)**: if context overlaps a single voxel of a column (a vertical stack of voxels with the
  same x, y), the whole column is removed from the buildable mass, above and below the context. No building on top of
  kept buildings, under tree crowns or beside a chimney within its columns. To build on or over an existing building
  (replacement, adding height), the user removes it from the context. The same holds for buildings at different
  terrain heights.
- The removed voxels are not scored, not carved, not part of the envelope or the massing. Downstream stages
  (thresholding, carve_above, slope limit, export, massing) see the reduced occupancy as their maximum volume. The
  massing footprint must not include the removed columns (today it comes from the maximum volume's mesh footprint,
  `footprint.json`), so plates never stand in a removed column.

### 4.3 Effect on rays (ray-based modes only)

- Before scoring, each ray from a test point (sky-patch rays in the weighted modes, sun rays in time-based) is tested
  against the context and terrain meshes. A ray that hits context or terrain within the ray length is dropped: it adds nothing to any voxel,
  wherever the voxel lies along it **(user)**.
- The test is against the **mesh**, not voxels, so context outside the grid counts and no voxel staircase is
  introduced **(proposed)**. Reuse or adapt the Warp mesh-ray kernel built on branch `feature/solar-check`
  (commit `4a213be`, `mesh_visible_weight_kernel` in `warp_kernels.py`, `wp.Mesh` + `wp.mesh_query_ray`) rather than
  merging that branch **(user: build from main and borrow the kernel)**.
- **Own surface:** a test point on a context building's facade must not be blocked by that facade. The user expects
  **many test surfaces to be faces of the context itself** (a neighbour's facade is part of its context building),
  so this is the normal case, not an edge case, and boundary conditions (coincident faces, shared faces) must not
  disturb the calculation **(user)**. Test surfaces and context may also come from different sources (a facade drawn
  by hand on a city-model mass), so the test point can sit some way inside the context mass, not only on its face. Reuse the start-inside tolerance of `feature/solar-check`
  (`_check_near_surface` / `_check_start` in `4a213be`: a ray that starts inside or just behind a context face is
  allowed to leave it when it faces outward, within a reach limit) **(designer's call)**. Test points whose rays are
  still all blocked are counted and reported, and shown in the app, so the user can fix the geometry in CAD. Other
  parts of the same building (a second wing) block normally.
- Weights are not renormalised: a point whose sky is half blocked by context keeps half its weight in play.
- `tilted_plane`: no ray test **(user)**; context columns and below-ground voxels are still removed.

### 4.4 Interactions

- **Test points inside context**: handled by the start-inside tolerance of 4.3; test points whose rays are all still
  blocked are counted and reported **(proposed)**.
- **Carve further** (the app's chain that replaces the maximum volume with the last envelope): context and terrain
  stay the same inputs at every step; the terrain removal and the column rule apply again (idempotent, since removed
  voxels stay removed) **(proposed)**.
- **test_point_access_evaluation** (voxel evaluation, Python API): applies the same context ray drop, so its numbers
  agree with what the carving saw **(proposed)**.
- **Fingerprint:** the context and terrain files are part of the preprocessing settings, so changing it reruns preprocessing; it
  appears in the manifest and the config snapshot.

### 4.5 Reporting

Run report and preprocessing diagnostics **(proposed)**: whether context and terrain were used; voxels removed from
the maximum volume by the context columns and by the ground, separately (count and m³, share of the maximum volume);
open context bodies that only block rays; rays dropped (count, share) and ray weight dropped (share), per
mode's unit; test points with all rays blocked.

## 5. Clients

- **CLI / config / Python API:** `context_path` and `terrain_path`, documented in `docs/getting-started/configuration.md`,
  `configs/REFERENCE_all_options.yaml`, and the mode pages where it matters (`docs/modes.md`: ray drop for ray-based
  modes, column and below-ground removal in every mode including the angle rule).
- **Browser app:** two optional file boxes in the Inputs step, after Maximum volume and Test surfaces: context and
  terrain, labelled in plain words (for example "Existing surroundings (optional)" and "Terrain (optional)",
  builder's choice within the wording rules of `docs/ui.md`). The context box hints at what belongs there (buildings,
  large trees; not balconies or shading devices); the terrain box that the ground stays buildable above it
  **(proposed)**. The service treats them as two more mesh roles (today `MESH_ROLES = ("max_volume",
  "test_surfaces")` in `local_web_service/projects.py`). The 3D view shows context as neutral grey massing and terrain
  as a ground surface, on by default, each with its own entry in the layers menu **(proposed)**. Follow the standing UI preferences in
  the vault (`ui-ux/backlog.md`): plain labels, units, tooltips naming the config key, minimal text.
- **Grasshopper:** `context` and `terrain` inputs (Mesh or Brep, list) on `USC_Preprocess`, next to `max_volume`
  and `test_surfaces`, rebuilt `.ghuser`, `docs/grasshopper.md`.

## 6. Constraints

- No change to results when context is absent (anti-goal). The existing suites, including the Monte Carlo sweep
  (`pytest -n 8`, merge tier), must pass unchanged.
- Performance: the ray test should add little to preprocessing on the bundled examples; context meshes can be large
  (terrain), so the mesh test must be BVH-based on the GPU, with a CPU path where Warp's CPU backend allows, as for the
  existing kernels.
- Memory guard: context voxelization uses the existing grid; context far outside the grid costs nothing there.
- Follow the test tiers in `CLAUDE.md`. Work on a branch from `main` (this design lives on
  `20261023_context_geometry`); do not merge without the user.

## 7. Testing (proposed)

- Unit: a ray-mask test (a context box between a test point and a patch drops exactly the expected rays; a ray
  grazing past the box is kept; a test point on a context facade is not blocked by that facade).
- Voxel removal: a context box inside the maximum volume clears its whole columns (above and below the box), which
  are then unscored; context outside the grid changes nothing in the grid; a context face shared with the maximum
  volume (party wall) removes no site voxels; an open context body removes nothing and is reported.
- Terrain: a sloping sheet through the bottom of the maximum volume removes only the voxels below it, column by
  column, and the columns stay buildable above it; rays that hit the terrain are dropped.
- Test surfaces that are faces of context buildings (coincident), and test surfaces drawn just inside a context mass,
  are not blocked by their own building; points still fully blocked are counted.
- Mode coverage: time-based and one weighted mode drop rays; `tilted_plane` removes context columns and below-ground
  voxels and otherwise matches the no-context result.
- End to end on synthetic scenes from `tests/typologies.py`, building the neighbours as context masses (the generator
  has neighbour facades; it needs their volumes too): the carving removes no more of the remaining buildable
  volume than without context, and points shaded by a neighbour stop driving the carving there.
- No-context regression: existing tests unchanged.

## 8. Follow-up work, not in this version

- Real-world example projects with context (vault `features/real-world-examples`, prioritised by the user): the
  current examples are arbitrary and have no context, so they cannot show the effect of this feature.
- Simulate rework on top of context (scenes: now = context + test surfaces; worst case = context + maximum volume;
  proposal = context + envelope or massing; change read against "now") (vault `features/solar-check-of-result`).
- OSM site import (milestone 2).
- Tree transmittance.
- Massing on terrain: massing still counts floors from the maximum volume's lowest point (flat-ground assumption,
  vault `backend/known-limitations`); floors that follow the terrain are later work.

## 9. Left to the builder

- Exact config key name and UI label wording, within the rules above.
- Where the ray mask lives (a separate pass that produces a keep-mask per ray, or a check inside the scoring kernels).
- Epsilon and origin offset values, and how they scale with the model's units and size.
- Report wording and layout.
