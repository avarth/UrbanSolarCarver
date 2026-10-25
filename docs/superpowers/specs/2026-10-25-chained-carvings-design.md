# Chained carvings: several criteria in sequence on one voxel grid

Date: 2026-10-25. Status: final (reviewed by a builder check; open question answered by the user). Replaces "carve further" (the Export step's
**Carve further with another criterion**).

## 1. Intent

A designer often protects different things with different criteria: the daylight of
the neighbours' windows, the winter sun on a school yard, the PV potential of roofs. Each
criterion has its own test surfaces, its own sky or sun model and its own threshold.
Today the browser app chains them with "carve further": the exported envelope becomes
the project's maximum volume and the next criterion carves that.

That round trip through a mesh loses information:

- **Design intent.** The maximum volume stops meaning "what may be built" and becomes
  "what is left". Massing then follows the envelope's voxel staircase instead of the
  drawn facades (Allatini, 2026-10-25: strips 0.5 to 4 m wide on every floor; see
  `vault/bugs/massing-slivers-after-carve-further.md`).
- **Precision.** Each step voxelizes the envelope again on a new grid, so surfaces drift
  by up to half a voxel per step (715 of 9,872 columns outside the drawn outlines after
  two steps).
- **Traceability.** The chain survives as moved files (`inputs/earlier_max_volumes/`)
  and a list in `project.json`. Changing step 1 cannot update step 2.

This design keeps the maximum volume as the user drew it and chains the criteria as
passes on one voxel grid. Each criterion scores the drawn maximum volume with its own
rays; its carving rule then decides among the voxels the criterion before it kept. No
mesh is made between passes, and no new geometry input is needed.

## 2. Goals

1. A project holds an ordered list of **criteria** (one carving pass each). A project
   with one criterion looks and behaves as today.
2. Each criterion has **independent settings**: mode, the mode's settings (analysis
   period, balance temperature, dew point, ...), its test surfaces, rays per patch, and
   its carving rule (threshold, `carve_fraction`, smoothing, carve above, slope limit).
   The user stated this explicitly ("a different threshold is essential").
3. **Fundamentals are shared** by the whole chain and set once: maximum volume, context
   and terrain, voxel size, grid margin, north. The user stated "apart from fundamentals
   like voxelization".
4. The envelope, massing and export are built **once, from the last criterion's result**,
   against the original maximum volume and its footprint.
5. Editing a criterion marks it and every later criterion out of date; running brings
   them up to date in order. Earlier criteria are not re-run. Later criteria re-trace
   rays only when their own settings or test surfaces changed; a change upstream only
   re-thresholds them (section 6.1).
6. The 3D view can show which criterion removed each carved voxel.
7. CLI, Python API and Grasshopper can chain passes too, without a new geometry input.

## 3. Non-goals

- **Multi-criteria weighting** (one score blended from several criteria). The user said
  this is not multicriterial. Each criterion carves on its own scores.
- **Layered input import** (one file whose layers map to roles). Wanted later; the user
  is not ready for an input rework. Because test surfaces are added inside each
  criterion (section 7.2), layers later only need a layer choice per criterion's file.
- **A different voxel size per criterion.** It would need resampling masks, which is
  the precision loss this design removes.
- **Branching** (variants: pass 2a and 2b from the same pass 1). Possible later as
  project variants; not in this design.
- **The Simulate / sun and shade check.** Its rework comes after this (see section 12).

## 4. Anti-goals (failures even if it works)

- Re-voxelizing a mesh between passes, or any mesh round trip inside the chain.
- A new user-facing geometry or path input to patch a symptom (as `footprint_mesh_path`
  did; parked on branch `fix/carve-further-footprint`, `d5e81a3`).
- Making a single-criterion project harder to use: no extra clicks, no new vocabulary
  until the user adds a second criterion.
- Silent order dependence: if order matters, the interface shows the order and lets the
  user change it.

## 5. The base of a criterion's `carve_fraction` (decided: sequential)

*My call (the user asked for a draft without further questions).* Each criterion carves
**what the criteria before it kept**: its scores, its histogram and its `carve_fraction`
refer to the voxels still there when it starts.

Why sequential:

- It matches how the user describes the workflow: feeding the result of a phase 1
  daylight carving into a second pass with another criterion.
- It matches today's carve-further results, so existing projects can be converted
  without changing what a setting means.
- Each criterion's histogram and cutoff line describe exactly the voxels that criterion
  decides about; with independent passes the histogram would include voxels already gone.
- The column rules (`carve_above`, slope limit) act on the shape that exists at that
  point, so later criteria never resurrect mass an earlier rule removed.

Consequences, shown in the interface: order matters, so the list is ordered, can be
reordered by dragging, and the step summary reads as a sequence ("Daylight 70 %, then
Winter sun 80 %"). A voxel's score barely depends on the order (scores sum the rays
through a voxel, whatever else remains); what changes with order is the base each
percentage refers to and which voxels the column rules see.

An "independent" combination (each criterion on the full maximum volume, keep only what
all keep) is left as a possible later option, not built now.

## 6. Engine

### 6.1 Where the chain link sits (decided: at thresholding)

A voxel's score is the sum of the weights of the rays that cross it; it does not depend
on which other voxels remain. In `carving.py` the occupancy grid changes scores in one
place only, the skin rule (a facade's own building does not obstruct it). The skin rule
of every criterion reads the **chain root's solid**: the drawn maximum volume plus
context and ground, as a single-criterion run does today. *My call, from the code
(builder check, 2026-10-25).*

So:

- **Preprocessing of each criterion** traces its rays over the chain root's grid. Its
  scores equal, bit for bit, those of an unchained run of the same settings on the drawn
  maximum volume, and depend on nothing upstream.
- **Thresholding of criterion *n* > 1** takes the previous criterion's thresholding result
  as a stage input and decides only among the voxels it kept: `carve_fraction` is a share
  of the score over those voxels, the histogram covers them, and the column rules
  (`carve_above`, slope limit) act on that shape. This is the sequential base of
  section 5.
- Editing, reordering or bypassing an earlier criterion re-thresholds later criteria
  (seconds) instead of re-tracing them (the slow part). Dragging criterion 1's cutoff can
  update the whole chain live.

Interfaces:

- Python: `thresholding(pre_result, cfg, out_dir, start_from=thr_result_of_previous)`.
- CLI: `usc threshold -c criterion2.yaml --start-from run/criteria/<id>/thresholding`
  (named `--after` if `start_from` clashes with the service's `RunRequest.start_from`;
  builder's call on the name).
- Grasshopper: `USC_ThresholdStage` gets an optional input wired from the previous
  `USC_ThresholdStage`.

### 6.2 The chain root

The chain root is the grid built from the fundamentals alone: voxelized maximum volume,
context columns and ground removed, footprint saved. It does not belong to any
criterion, so bypassing, moving or deleting criterion 1 does not change it. Every
criterion's preprocessing builds or reuses the same root (same settings give the same
grid; whether the root gets its own stage folder, `run/root/`, or is cached in the
session is the builder's call). A criterion whose grid settings differ from the root's
is impossible in the app (fundamentals live outside the criteria) and a
`StageChainError` naming the setting in the CLI and API.

### 6.3 What each manifest records

- The thresholding manifest of a chained criterion records the previous thresholding
  manifest and its run id; the usual `StageChainError` rule applies (an upstream manifest
  re-run after this one makes it stale).
- Preprocessing manifests record the root they were traced on.

### 6.4 Exporting and massing

Both read the **last** active criterion's thresholding result. Massing measures plates
against the chain root: the drawn maximum volume's occupancy for the "stays in the
maximum volume" test and its saved footprint for the facades, and the last kept mask as
the carved envelope. This removes the need for any footprint input.

### 6.5 Config file for a chain

A config without a chain is valid as today. A chain in one file:

```yaml
max_volume_path: ...          # fundamentals at the top level
voxel_size: 1.0
context_path: ...
criteria:
  - name: Daylight on windows
    mode: daylight
    test_surface_path: windows.ply
    carve_fraction: 0.7
  - name: Winter sun on the yard
    mode: benefit
    test_surface_path: yard.ply
    start_month: 11 ...
    carve_fraction: 0.8
```

`usc run -c chain.yaml` runs the criteria in order into `run/criteria/<id>/` (the id is
the criterion's position unless the file gives one) and then exporting and massing from
the last. Top-level carving keys (mode, threshold, ...) next
to `criteria:` are refused, so a file never means two things.

## 7. Browser app

Modern tools with ordered operations (Blender's modifier stack, Figma and Photoshop
layers, Rhino Grasshopper's chained components, Autodesk Forma's analysis list) agree on
a few patterns: an ordered list of cards, each with a status and a one-line summary;
add at the end; drag to reorder; a bypass toggle to compare with and without; selecting
a card shows its settings and its effect. This design follows them.

### 7.1 Steps

Today: Inputs, Mode, Settings, Carving, Envelope and massing, Export.

New:

1. **Inputs**: the site only: maximum volume, context, terrain, weather file. Test
   surfaces move into the criteria (section 7.2). *User, 2026-10-25.*
2. **Site and grid** (today's Settings minus the mode-specific group): north, voxel
   size, surroundings switch, grid budget line, detail settings.
3. **Criteria** (replaces Mode and Carving): the list of criterion cards, then the
   selected card's settings.
4. **Envelope and massing**, 5. **Export**: unchanged, built from the last criterion.
   The Export step loses **Carve further**.

With one criterion the Criteria step opens straight on that criterion's settings (mode
tiles, its settings, the carving rule and histogram), so the single-criterion flow is
the current Mode + Carving content in one step.

### 7.2 Criterion cards

Each card shows, in one line each:

- a colour swatch (the criterion's colour in the 3D view), its name and mode symbol;
- its result: "70 % of the score carved, 18,400 m³ removed";
- its status: current, out of date, running, or bypassed.

Card actions: drag handle (reorder), bypass toggle (skips the criterion without deleting
it; later criteria then start from the one before), and a menu with Rename, Duplicate,
Delete. **Add criterion** sits under the last card and opens the mode tiles. A new
criterion copies nothing but the fundamentals; its name defaults to "<Mode> on <first
test surface file>", editable. Duplicate copies the settings and the test surfaces.

Selecting a card shows below the list:

- **Protects** (the criterion's test surfaces; *user, 2026-10-25*): a drop box for
  files, as the Inputs boxes are today, and **Use a file from another criterion**, a
  short list of the files other criteria use. A criterion has no test surfaces until
  some are added; its card then shows "Add test surfaces" and the run refuses to start
  until every criterion that is on protects something. The mode tile may hint at what
  to add (daylight: windows or facades; solar energy: roofs); hints only. Later, a
  layered file in this box lists its layers as check boxes, and the same file in another
  criterion can tick other layers.
- **Mode settings**: today's mode-specific group for its mode (period, balance
  temperature, rays per sky patch, ...);
- **Carving rule**: today's Carving step (Manual or Automatic, carve amount, histogram
  with the draggable cutoff, Update when I change the threshold).

The same file used by two criteria is stored once (files are compared by content);
replacing it updates every criterion that uses it, and removing it from one criterion
leaves it in the others.

### 7.3 Running

**Run analysis** (in the Criteria step) traces the rays of every criterion whose own
settings or test surfaces changed, then thresholds the chain in order; progress shows on
each card. The carving rule of the selected criterion re-thresholds live as today, and
with "Update when I change the threshold" on, the later criteria re-threshold with it,
so the 3D view shows the final effect of moving an earlier cutoff. A later criterion
that only needs re-thresholding says so on its card ("Updates from Daylight on
windows").

### 7.4 3D view

- Selecting a card shows the state **after that criterion**: kept voxels coloured by
  that criterion's score (today's colouring), carved voxels hidden by default.
- A layer "Carved voxels, by criterion" colours each carved voxel with the swatch of the
  criterion that removed it, with a legend. This answers "which criterion took this?"
  at a glance.
- The selected criterion's test surfaces are drawn highlighted; the other criteria's are
  dimmed, so the view always shows what the selected card protects.
- The envelope and massing layers show the final result whatever card is selected.

### 7.5 Run report

One section per criterion (as today's preprocessing and thresholding sections), then the
chain summary: volume after each criterion and the share of the maximum volume kept.

## 8. Project and service

- `project.json` holds `criteria`: an ordered list of `{id, name, colour, bypassed,
  test_surface_files, settings}`; `config.yaml` keeps the fundamentals and, per
  criterion, the engine config is assembled from fundamentals plus that criterion's
  settings. *Builder's call*: one `config.yaml` with a `criteria:` list (section 6.5) is
  preferred, so the project folder is a valid CLI input.
- Test surface files are stored once in `inputs/test_surfaces/`, named as uploaded; each
  criterion lists the file names it uses. An upload with the same content as a stored
  file reuses it; an upload with the name of a stored file but other content replaces
  it, in every criterion that uses it (as an upload with the same name does today). Each criterion's joined test surfaces go to
  `inputs/joined/test_surfaces_<id>.ply`. A stored file no criterion uses any more is
  deleted.
- Run folder: `run/criteria/<id>/{preprocessing,thresholding}`, then `run/exporting`,
  `run/massing`. Stage records gain the criterion id; out-of-date logic compares each
  criterion's settings and its upstream run id.
- What goes out of date (*my call*): a change to the maximum volume, context, terrain,
  weather file or a fundamental setting puts everything out of date, as today's
  project-wide `inputs_revision` does. A change to a criterion's test surfaces (a file
  added, removed or replaced) puts out of date only the criteria using that file (their
  preprocessing) and the thresholding of every criterion after the first one affected.
  Stage records keep a fingerprint of each criterion's joined test surfaces for this,
  next to `inputs_revision`.
- The criterion id is stable across reordering; folders are named by id, not position.

## 9. Existing projects

- **Single-criterion projects**: read as a chain of one, and their test surface files
  (today in the Inputs step) become criterion 1's when the project opens, so what they
  protect does not change. Their `run/preprocessing` and `run/thresholding` are read as
  criterion 1 until the next run writes the new layout; results stay current.
- **Projects carved further** (for example Allatini): no converter (user, 2026-10-25).
  They keep working as they are: a chain of one criterion, with the envelope of the last
  step as their maximum volume, and their recorded `carving_chain` and
  `inputs/earlier_max_volumes/` stay as a record. The user recreates such a project by
  hand with criteria. The app no longer offers **Carve further**, so no new project
  gets this form.

## 10. Constraints

- One voxel grid per project; the grid budget check applies once.
- Stage records, manifests and `StageChainError` keep their contract
  (`docs/superpowers/specs/2026-10-16-stage-contract-design.md`).
- No change to scoring, thresholding or massing rules beyond what the chain needs.
- Writing style of messages and docs as in the rest of the app (plain labels, units
  beside values).

## 11. Testing

- Engine: in a chain of two, criterion 2's scores equal bit for bit those of an unchained
  run of its settings on the drawn maximum volume; its kept voxels equal thresholding
  those scores over criterion 1's kept voxels with criterion 2's carving rule; massing of
  a chain follows the drawn footprint (the Allatini staircase case as a typology scene);
  grid settings that differ from the root are refused.
- Monte Carlo oracle: chained cases for daylight then benefit, and time-based then
  daylight.
- Service: reordering, bypass and deleting mark the right criteria out of date; a
  project carved further with an earlier version opens and runs as a chain of one.
- App: one criterion shows no list chrome; two criteria show cards in order; the carved
  by criterion layer and legend; a file added to two criteria is stored once and
  replacing it puts both out of date; a project from an earlier version shows its test
  surfaces in criterion 1.

## 12. Order of work and related branches

1. Engine (chain root, thresholding after a previous criterion, massing against the
   root, `criteria:` in config and CLI), merged alone.
2. Service (project model, run layout, stage status, conversion).
3. App (steps, cards, 3D layer, report).
4. Then the Simulate rework from `feature/solar-check` (frozen; its engine moves onto a
   fresh branch from main). "Check inputs or results" then means the maximum volume, the
   result after any criterion, or the final envelope and massing.

One branch changes the service and app at a time.

## 13. Left to the builder

- Whether the chain root gets its own stage folder or a session cache (6.2).
- Folder names by position in the CLI and by id in the app (both read as ids).
- Exact card layout, colours of criterion swatches (distinct from the score colour map),
  and whether bypassed cards collapse.
- Whether `usc run` accepts several config files as an alternative to `criteria:`.
- Grasshopper ergonomics beyond the new input of `USC_ThresholdStage`.
