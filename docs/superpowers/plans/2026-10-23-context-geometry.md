# Context Geometry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional context and terrain meshes as inputs: context removes the voxel columns it overlaps, terrain removes the voxels below ground, and both drop the rays that hit them before scoring.

**Architecture:** A new engine module `context_geometry.py` holds the voxel operations (centre-inside voxelization of context on the max volume's lattice, the column rule, ground heights from terrain) and the blocking mesh. A new Warp any-hit kernel gives a per-ray blocked mask, applied inside the two ray carvers right after their ray sets are built. Preprocessing loads the optional meshes in the same local frame, reduces the occupancy before scoring, saves the reduced `voxel_grid.npy` so every later stage sees it, trims `footprint.json`, and reports what context did. The browser service and the app gain two optional input roles.

**Tech Stack:** Python 3.10, NumPy, PyTorch, NVIDIA Warp (`wp.Mesh`, `wp.mesh_query_ray`), trimesh, pydantic v2, pytest; React + TypeScript + three.js + vitest for `app/`.

**Spec:** `docs/superpowers/specs/2026-10-23-context-geometry-design.md` (approved by the user on 2026-10-23). Read it before starting; this plan argues from it.

## Global Constraints

- **Simple solutions that work:** the first version takes the simplest path that gives correct results; everything in spec section 8 stays out.
- **No context, no change:** a run without `context_path` and `terrain_path` gives the same `scores.npy`, `voxel_grid.npy` and outputs as `main` (bit-for-bit). Existing tests pass unchanged, including the Monte Carlo sweep.
- Config keys exactly `context_path` and `terrain_path`, both `Optional[str] = None`.
- Context voxel test: **voxel centre inside** (parity votes only, no surface-through rule), on the max volume's lattice.
- Column rule: a column with at least one context voxel loses **all** its max volume voxels. Terrain never triggers the column rule.
- Terrain: per column, ground height = highest crossing of the terrain with the column's vertical centre line; remove voxels whose centre z is below it.
- Ray drop: modes `time-based`, `irradiance`, `benefit`, `daylight`, `radiative_cooling`. `tilted_plane` has no ray drop (voxel removal still applies).
- Ray test against the **meshes** (context and terrain combined into one BVH), max distance `settings.ray_length`, origin offset `0.01` m along the test surface normal, minimum hit distance `1e-3` m (values from `feature/solar-check`).
- A context mesh that is not watertight: `report_issue("context_not_closed", ...)`, carry on.
- Context and terrain are opaque. No Grasshopper changes in this plan (follow-up).
- Follow `CLAUDE.md` test tiers. Work on branch `20261023_context_geometry` in your own worktree; do not merge into `main`. The worktree has no `.venv`: `PYTHONPATH=src "D:/RESEARCH_CENTER/ACTIVE_PROJECTS/RSBenvelope_generation/urbanSolarCarver/.venv/Scripts/python.exe" -m pytest ...`.
- Docs and UI text: plain words, no em dashes, no code names in the interface; every app setting has a plain label (`docs/ui.md` wording rules).

## Review Focus

1. **Georeferenced coordinates** (vertices near x = 500 km, y = 4500 km): context, terrain, max volume and test points must share the same frame shift before anything goes to float32 Warp meshes; expected: same result as the scene at the origin. Test in Task 5.
2. **Context far larger than the grid** (a city model or terrain kilometres wide around a small plot): the parity voxelization must still be correct inside the grid (its column rays start outside the grid) and the ray drop must still see context outside the grid. Tests in Tasks 2, 3 and 4.
3. **Context or terrain covering the whole max volume**: nothing is left to carve; expected a clear `InputError` naming context or terrain, not a crash downstream. Test in Task 5.
4. **A test surface whose normal points into its own context building** (flipped normals): all its rays are blocked; expected the run completes and the report counts those points as fully blocked. Test in Task 5.
5. **Removing the context file in the app after a run**: the config must lose `context_path`, the analysis must show as out of date, and a new run must not fail on a missing file. Test in Task 7.

---

### Task 1: Config keys, loading and settings

**Files:**
- Modify: `src/urbansolarcarver/pydantic_schemas.py` (UserConfig near line 270; `PreprocessingManifest` lines 774-800)
- Modify: `src/urbansolarcarver/stage_settings.py:100-127` (PreprocessingSettings fields)
- Modify: `src/urbansolarcarver/load_config.py:27` (`PATH_FIELDS`)
- Modify: `src/urbansolarcarver/io.py:146-190` (`validate_inputs`, `load_meshes`)
- Modify: `tests/test_local_web_packaging.py:107` (`NOT_IN_THE_FORM`, until Task 7 makes them service-owned)
- Modify: `configs/REFERENCE_all_options.yaml` (lines 1-4), `docs/getting-started/configuration.md` (line 9 and the paths)
- Test: `tests/test_context_config.py` (new)

**Interfaces:**
- Produces: `UserConfig.context_path`, `UserConfig.terrain_path`, `PreprocessingSettings.context_path`, `PreprocessingSettings.terrain_path` (all `Optional[str] = None`); `PreprocessingManifest.context_path`, `.terrain_path` (`Optional[str] = None`); `io.load_optional_mesh(path: Optional[str], name: str) -> Optional[trimesh.Trimesh]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_context_config.py`:
  - `test_context_and_terrain_default_to_none`: a minimal config (use the `tmp_mesh_files` fixture) gives `cfg.context_path is None and cfg.terrain_path is None`, and `PreprocessingSettings.from_config(cfg).context_path is None`.
  - `test_relative_context_paths_resolve_against_the_yaml_folder`: a YAML in `tmp_path/sub/` with `context_path: ctx.ply` loads to `str(tmp_path/"sub"/"ctx.ply")`.
  - `test_missing_context_file_is_an_input_error`: `validate_inputs` raises `InputError` naming `context_path` when the file does not exist.
  - `test_empty_context_file_counts_as_absent`: `load_optional_mesh(path_to_ply_with_zero_faces, "context")` returns `None` and emits `UrbanSolarCarverWarning` (via `report_issue("context_empty", ...)`); `load_optional_mesh(None, "context") is None`.
- [ ] **Step 2: Run** `pytest tests/test_context_config.py -m "not slow"`; expected FAIL (unknown keys).
- [ ] **Step 3: Implement.** Declare both fields on `UserConfig` (description: one sentence each, from spec 4.1) and `PreprocessingSettings`; add them to `PATH_FIELDS`; extend `validate_inputs` to check them when not `None`; add `load_optional_mesh` in `io.py` (uses `load_mesh`; zero triangles: `report_issue(f"{name}_empty", ...)` and `None`). `load_meshes` stays unchanged. Add both keys to `NOT_IN_THE_FORM`. Add the two manifest fields. Document both keys in `REFERENCE_all_options.yaml` (under "# Mesh and weather files") and `configuration.md`.
- [ ] **Step 4: Run** `pytest tests/test_context_config.py tests/test_stage_settings.py tests/test_local_web_packaging.py -m "not slow"`; expected PASS.
- [ ] **Step 5: Commit** `feat(config): optional context_path and terrain_path inputs`.

### Task 2: Context voxels on the max volume's lattice, and the column rule

**Files:**
- Create: `src/urbansolarcarver/context_geometry.py`
- Modify: `src/urbansolarcarver/voxelization.py:262-320` (`voxelize_solid_warp`)
- Modify: `src/urbansolarcarver/warp_kernels.py:726-827` (`_parity_voxelize_kernel`: ray start and span as inputs)
- Test: `tests/test_context_geometry.py` (new)

**Interfaces:**
- Produces:
  - `voxelize_solid_warp(vertices, faces, grid_origin, voxel_size, resolution, device, *, centre_only: bool = False, span_min: np.ndarray | None = None, span_max: np.ndarray | None = None) -> np.ndarray | None`. With `centre_only`, returns `votes >= 2` only. `span_min/span_max` (local coordinates) widen where the per-axis rays start and end, so a mesh extending beyond the grid keeps a correct parity inside it; votes are still written only for cells inside the grid. Defaults reproduce today's behaviour exactly.
  - `context_occupancy(vertices: np.ndarray, faces: np.ndarray, grid_origin: np.ndarray, voxel_size: float, resolution: int, device) -> np.ndarray` (bool, shape `(R, R, R)`): centre-inside cells of the context, spans set from the context's bounds.
  - `@dataclass(frozen=True) class ColumnRemoval: occupancy: np.ndarray` (uint8, `(R,R,R)`), `removed_columns: np.ndarray` (bool, `(R,R)`), `voxels_removed: int`.
  - `remove_context_columns(occupancy: np.ndarray, inside: np.ndarray) -> ColumnRemoval`: a column `(i, j)` is removed where `(inside[i, j, :] & occupancy[i, j, :]).any()`; all its occupied voxels go.

- [ ] **Step 1: Write the failing tests** in `tests/test_context_geometry.py` (grid built with `plan_voxel_grid` around a 10 m cube max volume, 1 m voxels):
  - `test_default_voxelization_is_unchanged`: `voxelize_solid_warp(...)` with defaults equals the result before this task for the cube (store the expected count, `np.count_nonzero`).
  - `test_context_box_inside_removes_its_whole_columns`: a 2 x 2 x 2 m context box at mid-height inside the cube removes the 4 columns under it, full height (`voxels_removed == 4 * 10`), and no other voxel.
  - `test_shared_face_removes_no_site_voxel`: a context box touching the cube's +x face from outside (party wall) gives `voxels_removed == 0`.
  - `test_context_much_larger_than_the_grid_voxelizes_correctly`: a context slab 1 km x 1 km x 2 m crossing the cube at z = 4-6 m removes every column (`removed_columns.all()` over the cube's footprint), with no parity inversion.
  - `test_context_outside_the_grid_changes_nothing`: a context box 100 m away gives `voxels_removed == 0`.
- [ ] **Step 2: Run** `pytest tests/test_context_geometry.py -m "not slow"`; expected FAIL (module missing).
- [ ] **Step 3: Implement** the kernel inputs for start and span, the `centre_only` path (skip the surface-through OR and the cavity fill), `context_occupancy`, `ColumnRemoval` and `remove_context_columns`. The kernel keeps computing cell indices relative to `grid_origin`; only where the ray starts and how far it runs change.
- [ ] **Step 4: Run** `pytest tests/test_context_geometry.py tests/test_voxelization.py -m "not slow"`; expected PASS.
- [ ] **Step 5: Commit** `feat(context): context voxels on the max volume lattice and the column rule`.

### Task 3: Terrain ground heights and below-ground removal

**Files:**
- Modify: `src/urbansolarcarver/context_geometry.py`
- Modify: `src/urbansolarcarver/warp_kernels.py` (new kernel inside the `if _warp_available:` block)
- Test: `tests/test_context_geometry.py`

**Interfaces:**
- Consumes: none from Task 2 beyond the module.
- Produces:
  - `ground_heights(vertices: np.ndarray, faces: np.ndarray, grid_origin: np.ndarray, voxel_size: float, resolution: int, device) -> np.ndarray` (float64, `(R, R)`, local z; `NaN` where the terrain does not cross the column centre line). One downward ray per column centre from above the terrain's top with `wp.mesh_query_ray`; the first hit is the highest crossing.
  - `remove_below_ground(occupancy: np.ndarray, heights: np.ndarray, grid_origin: np.ndarray, voxel_size: float) -> tuple[np.ndarray, int]`: clears voxels with centre z < height (NaN columns untouched); returns the new uint8 occupancy and the count removed.

- [ ] **Step 1: Write the failing tests:**
  - `test_flat_terrain_at_three_metres_removes_three_layers`: terrain plane z = 3 m (open sheet, two triangles, larger than the grid) under the 10 m cube removes exactly the 3 bottom layers.
  - `test_sloping_terrain_keeps_columns_above_ground`: a plane rising from z = 0 to z = 6 m across the cube removes only voxels below it, and every column keeps its voxels above the plane.
  - `test_terrain_not_covering_a_column_leaves_it`: a terrain sheet covering half the footprint leaves the other half's columns intact (`NaN` heights there).
  - `test_terrain_far_larger_than_the_grid`: a 5 km x 5 km sheet at z = 2 m gives the same result as a 100 m sheet.
- [ ] **Step 2: Run** the new tests; expected FAIL.
- [ ] **Step 3: Implement** the kernel and both functions.
- [ ] **Step 4: Run** `pytest tests/test_context_geometry.py -m "not slow"`; expected PASS.
- [ ] **Step 5: Commit** `feat(context): terrain ground heights and below-ground removal`.

### Task 4: Blocking mesh and per-ray blocked mask

**Files:**
- Modify: `src/urbansolarcarver/context_geometry.py`
- Modify: `src/urbansolarcarver/warp_kernels.py` (new `_mesh_any_hit_kernel`)
- Modify: `src/urbansolarcarver/ray_tracing.py` (launch wrapper, conventions as in `trace_point_access_dda`)
- Test: `tests/test_context_rays.py` (new)

**Interfaces:**
- Produces:
  - `@dataclass class BlockingMesh: mesh: "wp.Mesh"`, `device: str`, `triangle_count: int`.
  - `build_blocking_mesh(meshes: list[trimesh.Trimesh], device) -> BlockingMesh | None` (meshes already in the local frame; concatenated; `None` for an empty list). Build the `wp.Mesh` as `feature/solar-check` does (float32 points, int32 indices; try `bvh_constructor="sah"`, fall back on `TypeError`).
  - `mesh_blocks_rays(blocking: BlockingMesh, origins: torch.Tensor, directions: torch.Tensor, point_ids: torch.Tensor, surface_normals: torch.Tensor, max_t: float, origin_offset: float = 0.01, min_hit: float = 1e-3) -> torch.Tensor` (bool, `(N,)`, True = blocked) in `ray_tracing.py`. One thread per ray: origin `+ surface_normals[point_ids] * origin_offset`; a hit closer than `min_hit` is skipped by querying again from just beyond it; any other hit within `max_t` blocks.

- [ ] **Step 1: Write the failing tests** in `tests/test_context_rays.py` (CUDA when available, CPU otherwise, as in `tests/test_ray_tracing.py`):
  - `test_box_between_point_and_direction_blocks`: point at origin, normal +x, ray +x, box at x = 5-6 m: blocked.
  - `test_ray_grazing_past_a_box_is_kept`: same box, ray direction tilted so it passes 0.2 m beside it: not blocked.
  - `test_point_on_a_context_face_is_not_blocked_by_that_face`: point on the +x face of a context box, normal +x, rays in the facing hemisphere: none blocked.
  - `test_second_wing_blocks`: an L-shaped context building; a ray from one wing's facade toward the other wing: blocked.
  - `test_open_sheet_blocks`: an open terrain sheet above the point blocks an upward ray.
  - `test_context_beyond_the_grid_blocks`: a box 500 m away along the ray blocks (no grid involved).
- [ ] **Step 2: Run** the tests; expected FAIL.
- [ ] **Step 3: Implement** kernel, wrapper and `build_blocking_mesh`.
- [ ] **Step 4: Run** `pytest tests/test_context_rays.py -m "not slow"`; expected PASS.
- [ ] **Step 5: Commit** `feat(context): blocking mesh and per-ray blocked mask`.

### Task 5: Wire context and terrain into preprocessing, footprint and report

**Files:**
- Modify: `src/urbansolarcarver/api_core/preprocessing.py` (`_run_preprocessing` lines 280-475; `_max_volume_footprint` line 81)
- Modify: `src/urbansolarcarver/carving.py` (`carve_with_sun_rays` after line 493, `carve_with_sky_patch_rays` after line 614)
- Modify: `src/urbansolarcarver/context_geometry.py` (`subtract_columns`)
- Modify: `src/urbansolarcarver/api_core/_reporting.py` (Preprocessing section, lines 133-163)
- Modify: `docs/modes.md` (new section "Context and terrain"), `docs/project-map.md` (new module), `CHANGELOG.md` (`### Added (context geometry)` under `[Unreleased]`)
- Test: `tests/test_context_preprocessing.py` (new), `tests/test_massing.py` or the existing massing test file (one test)

**Interfaces:**
- Consumes: Task 1 settings and `load_optional_mesh`; Task 2 `context_occupancy`, `remove_context_columns`; Task 3 `ground_heights`, `remove_below_ground`; Task 4 `build_blocking_mesh`, `mesh_blocks_rays`.
- Produces:
  - `carve_with_sun_rays(..., blocking_mesh: BlockingMesh | None = None)` and `carve_with_sky_patch_rays(..., blocking_mesh: BlockingMesh | None = None)`: after the ray set is built, drop blocked rays from origins, directions, point_ids (and patch_ids) with the same `keep` indexing as the edge_taper drop at `carving.py:376-381`, before both the scoring pass and `_follow_mass_behind_skin`. With `None`, the code path is today's. Both return their ray statistics (rays total and dropped, weight total and dropped, test points with every ray dropped) to preprocessing without generating rays a second time; the plumbing is the builder's choice (a field on `SkyPatchCarvingResult`, an extra element behind a keyword for the sun carver). `access_evaluation.py` keeps calling the ray-set helpers unchanged.
  - `subtract_columns(polygons: list[Polygon], removed_columns: np.ndarray, grid_origin_world: np.ndarray, voxel_size: float) -> list[Polygon]`: the footprint minus the union of the removed columns' squares.
  - Preprocessing summary key `summary["context"]` = `{"context_used": bool, "terrain_used": bool, "context_closed": bool | None, "voxels_removed_by_context": int, "voxels_removed_below_ground": int, "volume_removed_m3": float, "share_of_max_volume_removed": float, "rays_total": int, "rays_dropped": int, "weight_dropped_share": float, "test_points_fully_blocked": int}`, present only when context or terrain is used.

- [ ] **Step 1: Write the failing tests** in `tests/test_context_preprocessing.py` (small scenes on `tmp_path`, daylight and time-based with `example_epw_path`, tilted_plane without weather):
  - `test_no_context_is_bit_for_bit_unchanged`: same config with and without `context_path: None`: identical `scores.npy` and `voxel_grid.npy` bytes, no `"context"` key in the diagnostics.
  - `test_context_neighbour_drops_rays_and_lowers_scores` (daylight): a context box shading the test surface gives `rays_dropped > 0`, every score `<=` the no-context score, and the total score lower.
  - `test_time_based_drops_sun_rays`: same with time-based; `rays_dropped > 0`.
  - `test_tilted_plane_only_loses_context_columns`: with a context box inside the max volume, the tilted_plane mask equals the no-context mask with the context columns removed.
  - `test_reduced_occupancy_is_saved`: `voxel_grid.npy` has the context columns and below-ground voxels cleared, and `summary["context"]["voxels_removed_by_context"]` / `["voxels_removed_below_ground"]` match.
  - `test_context_covering_everything_is_an_input_error`: a context box enclosing the whole max volume raises `InputError` whose message names the context.
  - `test_inward_facing_test_surface_is_counted_fully_blocked`: a test panel on a context face with its normal pointing into the context: run completes, `test_points_fully_blocked` equals that panel's sample count.
  - `test_georeferenced_scene_matches_the_scene_at_origin`: the daylight context scene translated by (500 000, 4 500 000, 0) gives the same scores (tolerance as in the existing georeferenced tests).
  - `test_open_context_warns_context_not_closed`: an open context mesh gives the `context_not_closed` issue and the run completes.
  - In the massing test file: `test_plates_avoid_removed_columns`: a context box inside the max volume; no massing plate polygon intersects the removed columns' area (beyond 1e-6 m²).
- [ ] **Step 2: Run** `pytest tests/test_context_preprocessing.py -m "not slow"`; expected FAIL.
- [ ] **Step 3: Implement** in `_run_preprocessing`: load context and terrain with `load_optional_mesh`; shift them by the same `frame` with the same rounding as the max volume; after `voxelize`, apply `remove_context_columns` then `remove_below_ground`; raise `InputError` when no occupied voxel is left; report `context_not_closed` when the context is not watertight; build the blocking mesh from context and terrain; pass it to the two ray carvers (not to `carve_with_planes`); save the reduced occupancy as `voxel_grid.npy`; write `footprint.json` from `subtract_columns(...)`; record both paths in the manifest; add `summary["context"]`; add a "Context and terrain" bullet block to the run report when the key is present. Docs: `docs/modes.md` section (what context and terrain do, the column rule, terrain below ground, angle rule removes voxels only, the not-closed warning), project map row, CHANGELOG entry.
- [ ] **Step 4: Run** `pytest tests/test_context_preprocessing.py -m "not slow"`, then the after-a-change tier `python -m pytest -m "not slow" -n 8`; expected PASS.
- [ ] **Step 5: Commit** `feat(context): context and terrain in preprocessing, footprint and run report`.

### Task 6: Typology scenes with neighbour masses, end to end

**Files:**
- Modify: `tests/typologies.py` (`neighbour_masses`, `Scene.context`, `Scene.write_context`)
- Test: `tests/test_context_typologies.py` (new, `pytestmark = pytest.mark.slow`)

**Interfaces:**
- Produces: `neighbour_masses(spec: SceneSpec) -> list[trimesh.Trimesh]` (one closed box behind each neighbour facade quad, its front face coincident with the quad, depth 10 m, height `neigh_h`); `Scene.context: trimesh.Trimesh | None` (set by `build` when `spec.neighbours`); `Scene.write_context(folder: Path) -> Path | None` writing `context.ply`. `Scene.write` keeps its return value.

- [ ] **Step 1: Write the failing tests** (daylight, three typologies: courtyard, rows, lshape, seed 0):
  - `test_context_carving_keeps_at_least_as_much`: threshold both runs at the **same numeric score cutoff** (the cutoff the no-context run used at `carve_fraction` 0.7); every voxel kept without context and not removed by context is also kept with context. This holds because dropping rays can only lower each voxel's score, and carve_above and the slope limit only remove voxels (a fixed `carve_fraction` does not guarantee it, since the total score changes).
  - `test_neighbour_facades_are_not_blocked_by_their_own_mass`: `test_points_fully_blocked == 0` (the facades are coincident with the masses' front faces).
- [ ] **Step 2: Run** `pytest tests/test_context_typologies.py`; expected FAIL.
- [ ] **Step 3: Implement** the generator additions.
- [ ] **Step 4: Run** the tests; expected PASS.
- [ ] **Step 5: Commit** `test(context): typology scenes with neighbour masses as context`.

### Task 7: Browser service roles

**Files:**
- Modify: `src/urbansolarcarver/local_web_service/projects.py` (lines 37-59, `write_config_from_values` 388, `_service_paths_for_mode` 464, `add_input` 480, `remove_input` 507, `_add_mesh_file` 729, `_write_joined_temporary_file` 773)
- Modify: `src/urbansolarcarver/local_web_service/stage_records.py:206` (`missing_inputs`), `server.py` (`project_detail` 265, `_example_input_files` 234), `api_models.py` (`ExampleProject` 230, `MissingInputsReply` 302)
- Modify: `tests/test_local_web_packaging.py` (move the two keys from `NOT_IN_THE_FORM` to the service-owned treatment)
- Test: `tests/test_local_web_projects.py`, `tests/test_local_web_stage_records.py`

**Interfaces:**
- Produces: `REQUIRED_MESH_ROLES = ("max_volume", "test_surfaces")`, `OPTIONAL_MESH_ROLES = ("context", "terrain")`, `MESH_ROLES = REQUIRED_MESH_ROLES + OPTIONAL_MESH_ROLES`; joined files `inputs/joined/context.ply`, `inputs/joined/terrain.ply`; `context_path` and `terrain_path` in `SERVICE_OWNED_SETTINGS`; the project's `config.yaml` carries each optional path **exactly when its joined file exists**, rewritten by `add_input` and `remove_input` as well as by `write_config_from_values`. Routes `/projects/{name}/inputs/{role}` accept the two new roles; `project_detail` lists them.

- [ ] **Step 1: Write the failing tests:**
  - `test_context_upload_adds_context_path_to_config`: `add_input(name, "context", "ctx.ply", box_bytes(...))` makes `config.yaml` contain `context_path: inputs/joined/context.ply`.
  - `test_removing_the_context_drops_the_path_and_marks_the_run_out_of_date`: after a recorded preprocessing run, `remove_input` of the only context file removes `context_path` from `config.yaml`, bumps `inputs_revision`, and the preprocessing stage reads out of date.
  - `test_optional_roles_are_not_missing_inputs`: a project with max volume and test surfaces only has no missing inputs.
  - `test_existing_project_without_role_folders_accepts_context`: deleting `inputs/context` before `add_input` still works.
  - `test_carve_further_keeps_context_and_terrain`: after `replace_max_volume_with_envelope`, both joined files and paths are unchanged.
- [ ] **Step 2: Run** the new tests; expected FAIL.
- [ ] **Step 3: Implement.** Join context and terrain uploads the way `max_volume` is joined (concatenate, `merge_vertices`, `save_mesh`).
- [ ] **Step 4: Run** `pytest tests/test_local_web_projects.py tests/test_local_web_stage_records.py tests/test_local_web_server.py tests/test_local_web_packaging.py -m "not slow"`; expected PASS.
- [ ] **Step 5: Commit** `feat(ui-service): optional context and terrain input roles`.

### Task 8: App input boxes and 3D layers

**Files:**
- Modify: `app/src/steps/InputsStep.tsx` (lines 13-14, 42-46, 59-113, 166), `app/src/messages.ts` (152-159, 444-453), `app/src/steps/input_meshes.ts`, `app/src/steps/ProjectWorkspace.tsx` (40-47, 116-153), `app/src/viewer/layers.ts` (17-20, 129-140), `app/src/viewer_overlays/ViewerPane.tsx` (41-42, 149-150, 178-202), `app/src/steps/step_summaries.ts`
- Regenerate: API types (`npm run api-types`), `src/urbansolarcarver/ui_static` (`npm run build`)
- Modify: `docs/ui.md` (Inputs step at line 59, the 3D view at line 129)
- Test: `app/src/steps/InputsStep.test.tsx`, `app/src/viewer/layers.test.ts`, `app/src/viewer_overlays/ViewerPane.test.tsx`, `app/src/steps/step_summaries.test.ts`

**Interfaces:**
- Consumes: Task 7 roles `"context"`, `"terrain"`.
- Produces: `InputRole = "max_volume" | "test_surfaces" | "context" | "terrain" | "weather"`; messages `contextTitle: "Existing surroundings (optional)"`, `contextHint: "Buildings and large trees that stay. They block sun and sky, and nothing is built in their place."`, `terrainTitle: "Terrain (optional)"`, `terrainHint: "The ground. It blocks sun and sky; the site stays buildable above it."`; layer names `"context"` and `"terrain"` (neutral grey solid for context, a ground surface for terrain), on by default in every step; camera framing and `localOrigin` unchanged (max volume and test surfaces).

- [ ] **Step 1: Write the failing tests:**
  - InputsStep: the two optional boxes render after Test surfaces with the titles above and no "Required" badge.
  - layers: `contextLayer` and `terrainLayer` exist and appear in `LAYER_NAMES` after the test surfaces.
  - ViewerPane: with context geometry present, the layers menu lists "Existing surroundings" and it is visible by default.
  - step_summaries: the Inputs summary mentions the context file count when present.
- [ ] **Step 2: Run** `npx vitest run src/steps/InputsStep.test.tsx src/viewer/layers.test.ts src/viewer_overlays/ViewerPane.test.tsx src/steps/step_summaries.test.ts`; expected FAIL.
- [ ] **Step 3: Implement**, regenerate the API types, update `docs/ui.md`.
- [ ] **Step 4: Run** `npm test && npm run typecheck`, then `npm run build`, then `python -m pytest tests/test_local_web_packaging.py`; expected PASS.
- [ ] **Step 5: Commit** `feat(ui): existing surroundings and terrain inputs and layers` (include the rebuilt `ui_static`).

### Task 9: Branch verification

**Files:** none new.

- [ ] **Step 1: Run** the before-a-merge tier once: front end `npm test && npm run build` (no diff in `ui_static` afterwards), then `python -m pytest -n 8` (all markers, includes the Monte Carlo sweep). Expected: all pass; report the counts.
- [ ] **Step 2: Run** the app on the perimeter block example with a hand-made context box (one neighbour mass) added in Inputs; check the layers show it, the analysis runs, and the run report has the "Context and terrain" block. Take one screenshot.
- [ ] **Step 3:** Do not merge. In the final report, list: commits, test counts, the screenshot, and notes for the vault (the vault is read-only from a worktree): what was built, anything deferred, any surprise.
