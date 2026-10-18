# Local web UI, round 2: design addendum

- Date: 2026-10-18
- Status: approved by the user on 2026-10-18
- Amends: `2026-10-17-local-web-ui-ux-design.md` (the "UX spec"). Where this document and the UX spec differ, this document applies. Section numbers prefixed "UX" refer to the UX spec.
- Source: the user's hands-on review of the merged app (main at 90cb20b) on 2026-10-18, their answers in the same session, and three read-only investigations.

Marking: **(user)** for what the user asked for or decided, **(proposed)** for a call made here that the user has not confirmed.

## 1. What this round covers

The user tried the app on the three examples and listed what was wrong or awkward. The bugs are fixed separately (section 9). This document covers the design changes: how the 3D view's ground aids behave, how modes are shown and ordered, how ranged settings are entered, the analysis period, the split of the envelope and the building massing, new names, and project management.

Out of scope here: simulated benefit weights (milestone 2, **user**), detecting the cold period automatically (section 8), drawing tools.

## 2. The 3D view

- **Axis gizmo:** no background box. The three lettered axes are drawn straight on the viewport, with the letters in `ink` on the light viewport and `ink_on_dark` on the dark one **(user**; colours **proposed)**.
- **No north arrow on the ground** **(user)**. North is shown by the compass overlay (UX 8.1) and, when chosen, by the compass ring below.
- **Ground aid, one button cycling three states** **(user)**: off, ground grid (UX 8.1), compass ring. The compass ring lies on the ground around the scene: a circle with tick marks every 10 degrees, longer ticks and the letters N, E, S, W every 90 degrees, rotated by North direction. The button sits in the viewport toolbar, shows the state it will switch to, and the choice is remembered on the computer like the viewport theme **(proposed)**.
- **Sized to the whole scene** **(user)**: the compass ring, the sun path and the sky dome are centred on, and sized to, the bounds of everything loaded (maximum volume and test surfaces together), not the maximum volume alone. Radius 1.5 times the larger horizontal side of those bounds, centre at the bounds' footprint centre, at the lowest z of the scene (UX 8.2's rule, applied to the scene bounds) **(proposed)**.

## 3. Mode step

- **Tiles show the symbol and the name only** **(user)**. The one-line description moves into the tooltip, which keeps the description, what the mode needs and the engine name (UX 5.3).
- **Every symbol is in colour** **(user)**. Sun discs stay in `sun`; skies, planes and the night sky use `accent`, `test_surface_on_dark` or `muted` strokes, so no symbol is black and white **(proposed)**.
- **Order and names** **(user)**, in a 3 x 2 grid read left to right:

| Order | Name | Engine mode |
|---|---|---|
| 1 | Angle rule | `tilted_plane` |
| 2 | Solar time-based | `time-based` |
| 3 | Solar energy | `irradiance` |
| 4 | Solar usefulness | `benefit` |
| 5 | Daylight | `daylight` |
| 6 | Night cooling | `radiative_cooling` |

"Solar time-based" replaces "Sun at set hours" and "Solar usefulness" replaces "Solar heat when cold" everywhere in the interface (summaries, legends, messages) **(user)**.

## 4. Entering values

### 4.1 Ranged values use sliders

Every numeric setting with a valid range is entered with a slider and a number field next to it; the number field accepts any value the engine accepts, the slider covers the range people normally use **(user)**. The slider range of each setting is listed in `setting_presentation.json` next to its label; where the engine gives no upper limit, the list gives a practical one (for example voxel size 0.1 to 5 m) and the number field still accepts more **(proposed)**. Settings that are counts or switches keep their current controls.

A field with a slider takes a full row of its group, so the building massing fields of UX 5.6 are no longer three side by side: at three across, each slider was about 86 px wide and could not be dragged to a value **(proposed**, found in the final review on 2026-10-18**)**.

### 4.2 Balance temperature

One slider from 10 to 30 °C with two handles **(user)**: the right handle is the balance temperature, the left handle is the balance temperature minus the dead band. The band between them is labelled "Dead band", and both values show as numbers that can be typed **(proposed)**. Moving the right handle moves the band with it.

### 4.3 Analysis period

The six dropdowns become one control **(user** asked for something more intuitive; design **proposed)**:

- a year strip of twelve months with a draggable date range (start and end day, snapping to days); a range across the new year (start after end, as in October to April) is drawn wrapped, which Ladybug's analysis period accepts;
- below it an hour strip with handles on the hours 0 to 23; the engine's end hour is inclusive (10 to 14 h samples 10:00 through 14:00), so the strip draws the range up to the end of the end hour's mark and the words read "10 to 14 h"; a range that crosses midnight is drawn wrapped;
- a row of presets that set the dates only and keep the hours: "21 December", "21 June", "Heating season, October to April" (1 October to 30 April), "Whole year" (1 January to 31 December) **(proposed)**;
- the chosen period in words under the strips ("21 Dec, 10 to 14 h"), which can be clicked to type exact values.

Keyboard: each handle is focusable; arrow keys move it by one day or one hour, Page Up and Page Down by a month or six hours.

### 4.4 Sample spacing follows voxel size

The engine requires the sample spacing on test surfaces to be no larger than the voxel size. When the voxel size goes below the sample spacing, the interface lowers the sample spacing to the voxel size and says so under Voxel size: "Sample spacing lowered to 0.5 m to match the voxel size." **(user** chose the interface over an engine change; text **proposed)**. Raising the voxel size later does not raise the sample spacing back. The sample spacing always has a value (1 m by default, never "automatic"). A sample spacing the user types above the voxel size is not changed: it shows as an error on the Sample spacing field, which opens its fold (the bug fix of section 9) **(proposed)**.

### 4.5 Settings groups

"Computer" disappears as a group: Rays per batch and Detailed statistics move to the end of "More detail settings" **(user)**. Detailed statistics only change the run report, which says so in the tooltip **(proposed)**.

## 5. Envelope and massing: one step, two builds

The step keeps its name and place, and holds two independent parts **(user)**:

- **Envelope:** its settings (smooth surface, smoothing passes, drop pieces, drop fragments), a **Build envelope** button (`produce: ["exporting"]`), its results (envelope volume) and its own out-of-date state.
- **Building massing:** its settings (floor heights, grid module, permitted volume exceedance, stacking), a **Build massing** button (`produce: ["massing"]`), its results (gross floor area, storeys, the per-storey table) and its own out-of-date state.

Neither waits for the other: massing reads the carving, not the envelope. The step summary names what exists ("Envelope built, massing not built"). Export offers each file once it exists. The run report link stays at the bottom of the step.

## 6. Names

| Now | New | Engine setting |
|---|---|---|
| Bay width | Grid module **(proposed)**; help: "The square module the storeys are built from, and the narrowest piece of floor allowed." | `min_plate_dimension` |
| Allowed overhang | Permitted volume exceedance **(user)**; help: "Share of a module on a storey that may lie outside the carved envelope. The massing never leaves the maximum volume." | `plate_tolerance` |
| Sun at set hours | Solar time-based **(user)** | mode `time-based` |
| Solar heat when cold | Solar usefulness **(user)** | mode `benefit` |

## 7. Projects

### 7.1 Where projects live

- The start screen shows the projects folder under "Open a project", with **Change folder** **(user)**.
- **Change folder** asks the service to open the operating system's folder picker on this computer (the service shows it with Python's tkinter). The browser never sends a path, so UX and technical-spec rule "no paths from the browser" holds **(proposed)**.
- The chosen folder is remembered in a small settings file of the user (`~/.urbansolarcarver/ui.json`) and used at the next launch; `--projects-folder` on the command line still wins for that launch **(user** asked for the preference to be stored; place **proposed)**.
- Existing projects are not moved; the list shows the projects of the new folder.
- **Change folder** is offered on the start screen only, with no project open and no run active; the service then switches to the new folder for the rest of the session **(proposed)**.
- If the folder picker cannot open (no display, tkinter missing), the start screen says so and names the way that always works: start with `--projects-folder <folder>`. The old folder stays **(proposed)**.

### 7.2 Managing a project

Each project in the list, and the project name in the top bar, has a menu with **(user)**:

- **Open folder:** opens the project's folder in Explorer (Finder, or the file manager on Linux) on this computer.
- **Rename:** a dialog with the new name, checked by the project-name rule; the folder is renamed.
- **Delete:** a dialog that names the project and its folder, and asks the user to type the project name to confirm.
- **Reset to the example** (example projects only): replaces the project's inputs, settings and results with a fresh copy of its example, after a confirmation **(user**: a fresh copy only through a reset**)**. The old content goes to the recycle bin under the guardrails of 7.3, and the project keeps its name **(proposed)**.

Rename, delete and reset are refused while the project's run is active.

### 7.3 Guardrails for deleting

Deleting must never remove anything but that one project folder **(user)**. The service deletes only when every check passes **(proposed)**:

1. the name passes the project-name rule;
2. the folder is a direct child of the projects folder after resolving every link, and is not the projects folder itself;
3. it holds a `project.json` that reads as a USC project of that name;
4. neither the folder nor anything inside it is a symbolic link or a junction (a link could lead outside);
5. no run of that project is active.

The folder then goes to the recycle bin (Windows) or trash (macOS, Linux), not a permanent delete, so a mistake can be undone **(proposed**: needs the small `send2trash` package in the `ui` extra**)**. Any failed check, or a failure to move it, leaves everything in place and says why.

### 7.4 Examples

**Try an example** opens the project made from that example if one exists, and creates it only the first time **(user)**. `project.json` records which example a project came from, so a renamed example project is still found **(proposed)**. Projects made before this field existed count as from an example when their name is exactly the example's title; numbered copies ("Perimeter block 2") stay ordinary projects. When several projects come from one example, the most recently modified one opens **(proposed)**.

## 8. Engine proposal, not part of this round

Detecting the cold period automatically for Solar usefulness, from the weather file with Ladybug's tools, would add a preset "Cold period from the weather file" to the analysis period. It needs engine work and comes back to the user as its own proposal **(user** asked; deferred **proposed)**.

Decided and built on 2026-10-18 after round 2 **(user)**: two sources are foreseen, the weather file now and the 5R1C simulation later, with simulated weights in milestone 2. The weather-file source takes the daily mean dry-bulb of the EPW, a 31-day running mean wrapping across the new year, and the base temperature balance_temperature - balance_offset (the threshold Solar usefulness applies to each hour); the cold period is the longest run of days below it, possibly across the new year. The preset sets the dates and keeps the hours; it is a one-time choice, so a later change of the balance temperature does not move the dates set **(proposed**, shown to the user before building**)**.

## 9. Bugs fixed in the same round (for the record)

- Test surfaces lost their panel boundaries when the service joined the uploaded files (normals dropped), so the perimeter block's courtyard was never protected and the district example failed. Fixed in the service.
- Massing started the ground floor below the maximum volume's base, contrary to `docs/massing.md`, so "New building among neighbours" built no massing. Fixed in the engine, approved by the user.
- Settings form: field-less errors shown raw, "1 setting to fix" on the wrong step, stale errors after a mode change, a refused mode change leaving Carving unlocked, 0 accepted where the engine needs more, "automatic" defaults unexplained.
- Mode tooltips that stayed open and swallowed clicks.

## 10. Left to the builder

- The exact strip drawing of the analysis period control and its preset positions.
- The practical slider ranges, within the engine limits.
- The ground aid button's icon.
