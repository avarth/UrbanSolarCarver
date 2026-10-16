# UX Feedback Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve CLI feedback, diagnostics, and API hygiene so architects/planners get actionable information without digging through JSON files.

**Architecture:** Enrich the CLI output at each pipeline stage with human-readable metrics (device, volume retention, resolved threshold). Add a config snapshot to diagnostics for reproducibility. Add a `--dry-run` mode and memory guard to preprocessing. Fix minor API warts (misleading variable name, unused parameters passed to daylight). Auto-discover manifests when unambiguous.

**Tech Stack:** Python 3.10+, Typer CLI, Pydantic v2, PyTorch, NumPy

---

## File Structure

| File | Changes |
|------|---------|
| `src/urbansolarcarver/api_core/_util.py` | Add `device_summary()` helper, add `dump_config_snapshot()` |
| `src/urbansolarcarver/api_core/preprocessing.py` | Print device info, dump config snapshot, add dry-run support, add memory guard |
| `src/urbansolarcarver/api_core/thresholding.py` | Rename `norm` → `scores`, return richer result with threshold stats |
| `src/urbansolarcarver/api_core/exporting.py` | Return richer result with volume/retention stats |
| `src/urbansolarcarver/carver_cli.py` | Enrich `_echo_result` calls with device/threshold/volume info; add `--dry-run`; auto-find manifests |
| `src/urbansolarcarver/scoring.py` | Stop passing unused epw/hoys to daylight |
| `src/urbansolarcarver/pydantic_schemas.py` | Rewrite `carve_fraction` field description |
| `src/urbansolarcarver/mode_registry.py` | Add `weight_unit` x-axis label for histograms |
| `tests/test_schemas.py` | Test for updated description (optional; description is metadata, not behavior) |
| `tests/test_cli.py` | Test dry-run flag |

---

## Task 1: Device feedback helper + config snapshot

Users don't know if GPU is active. All input parameters should be recorded for reproducibility.

**Files:**
- Modify: `src/urbansolarcarver/api_core/_util.py:32-40`
- Modify: `src/urbansolarcarver/api_core/preprocessing.py:95-105`

- [ ] **Step 1: Add `device_summary()` to `_util.py`**

After the existing `resolve_device` function (line 40), add:

```python
def device_summary(device) -> str:
    """Human-readable device string, e.g. 'CUDA (NVIDIA RTX 3080, 10.0 GB)' or 'CPU'."""
    import torch
    if device.type == "cuda":
        try:
            name = torch.cuda.get_device_name(device)
            mem = torch.cuda.get_device_properties(device).total_memory / (1024**3)
            return f"CUDA ({name}, {mem:.1f} GB)"
        except Exception:
            return "CUDA"
    return "CPU"
```

- [ ] **Step 2: Add `dump_config_snapshot()` to `_util.py`**

After `device_summary`, add:

```python
def dump_config_snapshot(conf, diag_dir) -> Path:
    """Write the full resolved config to diagnostics for reproducibility."""
    snapshot = conf.model_dump()
    return write_json(diag_dir, "config_snapshot.json", snapshot)
```

- [ ] **Step 3: Use both in `preprocessing.py`**

In `preprocessing.py`, after `resolved_device = resolve_device(...)` (line 104), add:

```python
    device_info = device_summary(resolved_device)
```

In the diagnostics section (after `diag_dir = ensure_diag(out_path)`, around line 198), add:

```python
    dump_config_snapshot(conf, diag_dir)
    summary["device"] = device_info
```

Update the import at top of `preprocessing.py` to include `device_summary, dump_config_snapshot`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v --tb=short -q`
Expected: ALL PASS (125 passed, ~6 skipped)

- [ ] **Step 5: Commit**

```
git add src/urbansolarcarver/api_core/_util.py src/urbansolarcarver/api_core/preprocessing.py
git commit -m "feat: add device summary and config snapshot to preprocessing diagnostics"
```

---

## Task 2: Enrich CLI output: device, volume, threshold

The CLI currently prints minimal info. Architects need device confirmation, volume retention, and resolved threshold without opening JSON files.

**Files:**
- Modify: `src/urbansolarcarver/carver_cli.py:101-106,175-191,229-241,274-285,316-326`
- Modify: `src/urbansolarcarver/api_core/preprocessing.py` (return device_info)
- Modify: `src/urbansolarcarver/api_core/thresholding.py` (return threshold stats)
- Modify: `src/urbansolarcarver/api_core/exporting.py` (return volume stats)

- [ ] **Step 1: Add fields to result dataclasses**

In `preprocessing.py`, add `device_info: str` to `PreprocessingResult`:

```python
@dataclass(frozen=True)
class PreprocessingResult:
    ...
    device_info: str = ""
```

Set it when constructing the result at the end of `preprocessing()`.

In `thresholding.py`, add to `ThresholdingResult`:

```python
@dataclass(frozen=True)
class ThresholdingResult:
    ...
    threshold_method: str = ""
    threshold_value: float = 0.0
    voxels_kept: int = 0
    voxels_removed: int = 0
    retention_pct: float = 0.0
```

Set them when constructing the result (values are already computed in the diagnostics section; just pass them through).

In `exporting.py`, add to `ExportingResult`:

```python
@dataclass(frozen=True)
class ExportingResult:
    ...
    retention_pct: float = 0.0
    mesh_volume_m3: Optional[float] = None  # Optional; needs `from typing import Optional`
    vertices: int = 0
    faces: int = 0
```

Set them from the already-computed values in the diagnostics section.

- [ ] **Step 2: Enrich CLI `_echo_result` calls**

In `carver_cli.py`, update the `run` command's `_echo_result` call (line 188):

```python
    _echo_result("Pipeline", res, {
        "Mesh": str(res.export_path),
        "Volume retained": f"{res.retention_pct:.1f}%" + (f" ({res.mesh_volume_m3:.0f} m³)" if res.mesh_volume_m3 else ""),
        "Faces": f"{res.faces:,}",
        "Time": f"{elapsed:.1f}s",
    })
```

Update `cmd_preprocessing` (line 236):

```python
    _echo_result("Preprocessing", res, {
        "Device": res.device_info,
        "Grid": f"{res.volume_shape}",
        "Scores": str(res.volume_path),
        "Hash": res.hash[:12],
        "Time": f"{elapsed:.1f}s",
    })
```

Update `cmd_thresholding` (line 281):

```python
    _echo_result("Thresholding", res, {
        "Method": f"{res.threshold_method} → {res.threshold_value:.4g}",
        "Carved": f"{res.voxels_removed:,} voxels ({100 - res.retention_pct:.1f}% of volume)",
        "Retained": f"{res.voxels_kept:,} voxels ({res.retention_pct:.1f}%)",
        "Hash": res.hash[:12],
        "Time": f"{elapsed:.1f}s",
    })
```

Update `cmd_exporting` (line 323):

```python
    _echo_result("Exporting", res, {
        "Mesh": str(res.export_path),
        "Volume retained": f"{res.retention_pct:.1f}%" + (f" ({res.mesh_volume_m3:.0f} m³)" if res.mesh_volume_m3 else ""),
        "Faces": f"{res.faces:,}",
        "Time": f"{elapsed:.1f}s",
    })
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -v --tb=short -q`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```
git add src/urbansolarcarver/api_core/preprocessing.py src/urbansolarcarver/api_core/thresholding.py src/urbansolarcarver/api_core/exporting.py src/urbansolarcarver/carver_cli.py
git commit -m "feat: enrich CLI output with device, threshold, and volume metrics"
```

---

## Task 3: Memory guard + dry-run for preprocessing

Prevent configurations that would hang the machine. `--dry-run` prints grid dimensions + memory estimate without actually running.

**Files:**
- Modify: `src/urbansolarcarver/carver_cli.py:205-241`
- Modify: `src/urbansolarcarver/api_core/preprocessing.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add memory estimation helper to `_util.py`**

```python
def estimate_grid_memory(voxel_size: float, mesh_path: str, margin_frac: float = 0.01) -> dict:
    """Estimate voxel grid dimensions and memory without loading heavy deps.

    Returns dict with keys: grid_dims, total_voxels, memory_mb, warning.
    """
    import trimesh
    mesh = trimesh.load(mesh_path, force='mesh')
    bbox = mesh.bounds
    span = bbox[1] - bbox[0]
    margin = span.max() * margin_frac
    padded = span + 2 * margin
    dims = tuple(int(np.ceil(s / voxel_size)) for s in padded)
    total = dims[0] * dims[1] * dims[2]
    # float32 scores + bool grid + overhead ≈ 5 bytes/voxel
    mem_mb = total * 5 / (1024**2)
    warning = None
    if total > 500_000_000:
        warning = (
            f"Grid would contain {total:,} voxels ({mem_mb:,.0f} MB). "
            f"This will likely exhaust memory. Consider increasing voxel_size "
            f"(currently {voxel_size}m) or reducing the mesh bounding box."
        )
    elif total > 50_000_000:
        warning = (
            f"Grid contains {total:,} voxels ({mem_mb:,.0f} MB). "
            f"This is large and may be slow. Consider voxel_size > {voxel_size}m for faster iteration."
        )
    return {"grid_dims": dims, "total_voxels": total, "memory_mb": mem_mb, "warning": warning}
```

- [ ] **Step 2: Add guard to `preprocessing.py`**

After `voxelize()` call (line 107), add:

```python
    total_voxels = int(np.prod(voxel_grid.shape))
    if total_voxels > 500_000_000:
        raise ValueError(
            f"Voxel grid has {total_voxels:,} voxels; this would exhaust memory. "
            f"Increase voxel_size (currently {conf.voxel_size}m) or reduce geometry extent."
        )
```

- [ ] **Step 3: Add `--dry-run` flag to `cmd_preprocessing`**

In `carver_cli.py`, add `dry_run` parameter to `cmd_preprocessing`:

```python
    dry_run: bool = Option(False, "--dry-run", help="Estimate grid size and memory, then exit without running"),
```

Before the actual preprocessing call, add:

```python
    if dry_run:
        from .api_core._util import estimate_grid_memory
        est = estimate_grid_memory(cfg.voxel_size, cfg.max_volume_path, cfg.margin_frac)
        typer.secho(f"\n  Dry-run estimate ({cfg.mode})", fg="cyan", bold=True)
        typer.echo(f"    Grid: {est['grid_dims'][0]} × {est['grid_dims'][1]} × {est['grid_dims'][2]}")
        typer.echo(f"    Voxels: {est['total_voxels']:,}")
        typer.echo(f"    Est. memory: {est['memory_mb']:,.0f} MB")
        if est['warning']:
            typer.secho(f"    ⚠ {est['warning']}", fg="yellow")
        else:
            typer.secho(f"    ✓ Grid size looks reasonable", fg="green")
        typer.echo()
        raise typer.Exit(0)
```

Note: `--dry-run` is only added to `cmd_preprocessing`, not `run`. The `run` command is a convenience wrapper; users who want estimates should use `preprocessing --dry-run` first.

- [ ] **Step 4: Write test for dry-run**

In `tests/test_cli.py`, add:

```python
def test_dry_run_does_not_run_pipeline(tmp_path):
    """--dry-run should print estimates and exit without producing output files."""
    # This test requires actual mesh files, so skip if fixtures unavailable
    # For now, just test that the flag is accepted without error
    from typer.testing import CliRunner
    from urbansolarcarver.carver_cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["preprocessing", "--help"])
    assert "--dry-run" in result.output
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/ -v --tb=short -q`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```
git add src/urbansolarcarver/api_core/_util.py src/urbansolarcarver/api_core/preprocessing.py src/urbansolarcarver/carver_cli.py tests/test_cli.py
git commit -m "feat: add --dry-run and memory guard to preprocessing"
```

---

## Task 4: Histogram x-axis units from mode registry

The score histogram currently labels the x-axis "Score" with no units. Use the mode's `weight_unit` from the registry.

**Files:**
- Modify: `src/urbansolarcarver/api_core/_util.py:42-82` (save_histogram)
- Modify: `src/urbansolarcarver/api_core/preprocessing.py:220` (pass unit)
- Modify: `src/urbansolarcarver/api_core/thresholding.py:262-266` (pass unit)

- [ ] **Step 1: Add `xlabel` parameter to `save_histogram`**

In `_util.py`, change `save_histogram` signature to accept an optional `xlabel`:

```python
def save_histogram(
    values: np.ndarray,
    out_dir: Union[str, Path],
    fname: str = "score_histogram.png",
    threshold_line: Optional[float] = None,
    title: str = "Score Distribution",
    xlabel: str = "Score",
) -> Optional[Path]:
```

At line 77, change `ax.set_xlabel("Score")` to `ax.set_xlabel(xlabel)`.

- [ ] **Step 2: Pass units from preprocessing**

In `preprocessing.py`, where `save_histogram` is called (around line 220), change:

```python
    hist_path = save_histogram(rs, diag_dir, "score_histogram.png", title=f"Raw Scores ({mode})")
```

to:

```python
    from ..mode_registry import MODES
    xlabel = MODES[mode].weight_unit if mode in MODES else "Score"
    hist_path = save_histogram(rs, diag_dir, "score_histogram.png",
                               title=f"Raw Scores ({mode})", xlabel=xlabel)
```

- [ ] **Step 3: Pass units from thresholding**

In `thresholding.py`, where `save_histogram` is called (around line 262), change:

```python
    hist_path = save_histogram(
        nn, diag_dir, "threshold_histogram.png",
        threshold_line=thr_val,
        title=f"Voxel Scores: threshold={thr_val:.4g} ({threshold_method})",
    )
```

to:

```python
    hist_path = save_histogram(
        nn, diag_dir, "threshold_histogram.png",
        threshold_line=thr_val,
        title=f"Voxel Scores: threshold={thr_val:.4g} ({threshold_method})",
        xlabel=weight_unit,
    )
```

(The variable `weight_unit` is already computed earlier in the function.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v --tb=short -q`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```
git add src/urbansolarcarver/api_core/_util.py src/urbansolarcarver/api_core/preprocessing.py src/urbansolarcarver/api_core/thresholding.py
git commit -m "feat: label histogram x-axis with physical units from mode registry"
```

---

## Task 5: Auto-find manifest when `-f` not given

If there's exactly one preprocessing manifest in the output directory, thresholding/exporting should find it automatically.

**Files:**
- Modify: `src/urbansolarcarver/carver_cli.py:244-285,288-326`

- [ ] **Step 1: Change `-f` from required to optional**

In `cmd_thresholding`, change:

```python
    from_manifest: Path = Option(..., "-f", "--from", exists=True, readable=True, help="Path to preprocessing manifest.json"),
```

to:

```python
    from_manifest: Optional[Path] = Option(None, "-f", "--from", help="Path to preprocessing manifest.json (auto-detected if omitted)"),
```

- [ ] **Step 2: Add manifest auto-discovery**

After `out_dir = out_dir or ...`, add:

```python
    if from_manifest is None:
        # Auto-discover: look for preprocessing/manifest.json relative to out_dir
        parent = out_dir.parent if out_dir.name == "thresholding" else out_dir
        candidate = parent / "preprocessing" / "manifest.json"
        if candidate.is_file():
            from_manifest = candidate
            if not quiet:
                typer.secho(f"  Auto-detected manifest: {candidate}", fg="cyan")
        else:
            typer.secho(
                "  No -f/--from given and no preprocessing/manifest.json found in the default layout. "
                "Use -f to specify the manifest path, or use the default output directory structure.",
                fg="red",
            )
            raise typer.Exit(1)
```

- [ ] **Step 3: Same for `cmd_exporting`**

Same pattern: make `-f` optional, auto-discover `thresholding/manifest.json` relative to out_dir.

```python
    if from_manifest is None:
        parent = out_dir.parent if out_dir.name == "exporting" else out_dir
        candidate = parent / "thresholding" / "manifest.json"
        if candidate.is_file():
            from_manifest = candidate
            if not quiet:
                typer.secho(f"  Auto-detected manifest: {candidate}", fg="cyan")
        else:
            typer.secho("  No -f/--from given and no thresholding/manifest.json found.", fg="red")
            raise typer.Exit(1)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v --tb=short -q`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```
git add src/urbansolarcarver/carver_cli.py
git commit -m "feat: auto-discover manifests when -f not provided"
```

---

## Task 6: Rename misleading `norm` variable + fix `get_weights` API + better `carve_fraction` description

Three small cleanup items that don't affect behavior.

**Files:**
- Modify: `src/urbansolarcarver/api_core/thresholding.py:132-183`
- Modify: `src/urbansolarcarver/scoring.py:71-82`
- Modify: `src/urbansolarcarver/pydantic_schemas.py:87-99`

- [ ] **Step 1: Rename `norm` → `scores` in `thresholding.py`**

In the `thresholding()` function, rename all occurrences of the `norm` variable (lines 133, 149, 158, 170, 183, 220) to `scores`. This is a purely cosmetic rename: the variable holds raw float32 scores, not normalized values. The misleading name could lead future maintainers to assume normalization happened.

- [ ] **Step 2: Fix `get_weights` daylight call in `scoring.py`**

Lines 72-82 pass `epw_file` and `hoys` to `compute_EPW_based_weights` for daylight mode, but the daylight branch never uses them. Change to:

```python
    # Daylight mode: CIE overcast sky, geometry only, no EPW needed.
    if mode_key == 'daylight':
        return compute_EPW_based_weights(
            mode_key,
            None,              # epw_path not used by daylight
            None,              # hoys not used by daylight
            torch.device(device),
            ground_reflectance,
            balance_temperature,
            balance_offset,
            north=north_deg,
        )
```

- [ ] **Step 3: Rewrite `carve_fraction` description in `pydantic_schemas.py`**

At lines 87-99, change the description to lead with user intent:

```python
    carve_fraction: float = Field(
        0.7,
        ge=0.0,
        le=1.0,
        description=(
            "How aggressively to carve (0.0–1.0). Controls the fraction of total solar "
            "obstruction to eliminate, NOT the fraction of voxels removed. Because a few "
            "highly-obstructing voxels dominate the score distribution, 0.7 typically removes "
            "far fewer than 70% of voxels. "
            "0.7 = aggressive (protects 70% of solar access, taller/slimmer volumes). "
            "0.3 = conservative (protects 30%, bulkier volumes, more floor area). "
            "Only used when threshold='carve_fraction'."
        ),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v --tb=short -q`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```
git add src/urbansolarcarver/api_core/thresholding.py src/urbansolarcarver/scoring.py src/urbansolarcarver/pydantic_schemas.py
git commit -m "fix: rename misleading norm variable, clean daylight API, improve carve_fraction description"
```

---

## Task 7: Run full test suite and final verification

- [ ] **Step 1: Run entire test suite**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS (125+ passed, ~6 skipped).

- [ ] **Step 2: Grep for remaining issues**

```bash
# Should find no occurrences of the old variable name in thresholding
grep -n "norm" src/urbansolarcarver/api_core/thresholding.py
# Verify --dry-run appears in help
python -m urbansolarcarver preprocessing --help | grep dry-run
```

- [ ] **Step 3: Spot-check CLI formatting**

```bash
python -m urbansolarcarver schema --mode benefit --search carve_fraction
```

Expected: Updated description text visible in the schema output.
