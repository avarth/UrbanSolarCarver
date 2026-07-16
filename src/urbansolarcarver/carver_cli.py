#!/usr/bin/env python
"""UrbanSolarCarver command-line interface.

Exposes the three-stage pipeline (preprocessing -> thresholding -> exporting)
as individual subcommands, plus a one-shot ``run`` that chains all three.
Performance evaluation is out of scope — use Ladybug/Honeybee/Radiance on the
exported mesh.

Utility commands:
  - ``validate``: load and validate a YAML config without running anything.
  - ``schema``:   print a filterable parameter reference (by mode or keyword).
  - ``daemon``:   start / stop / status of the persistent GPU daemon used by
                  Grasshopper and the ``--daemon`` flag on pipeline commands.

Design decisions
~~~~~~~~~~~~~~~~
All heavy imports (torch, warp, api_core) are deferred to function bodies so
that lightweight commands (``--help``, ``schema``, ``validate``, ``daemon``)
start instantly (~0.3 s) without initialising CUDA or compiling Warp kernels.
The ``_api()`` helper loads ``urbansolarcarver.api`` lazily on first access.

The ``--daemon`` flag on each pipeline command sends the job to a running
daemon over localhost TCP (``multiprocessing.connection``), sharing the same
RPC mechanism used by the Grasshopper plugin.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import typer
from typer import Option

# Light imports only — no torch, no warp, no api_core at module level.
from .load_config import load_config, user_config

# Windows consoles may use legacy code pages (cp1252/cp125x); when output is
# piped or redirected, printing schema descriptions containing ≥ / ° / —
# would raise UnicodeEncodeError.  Degrade unencodable characters to '?'
# instead of crashing.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Version — read from installed package metadata; fall back to hardcoded.
# ---------------------------------------------------------------------------
try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("urbansolarcarver")
except Exception:
    __version__ = "0.9.0"

# ---------------------------------------------------------------------------
# Daemon connection defaults (localhost-only, not network-accessible).
# ---------------------------------------------------------------------------
daemon_host = "localhost"
daemon_port = 6000

# ---------------------------------------------------------------------------
# Lazy API accessor
# ---------------------------------------------------------------------------
_api_mod = None


def _api(attr: str):
    """Return an attribute from ``urbansolarcarver.api``, imported lazily.

    First call triggers the heavy import chain (torch -> warp -> api_core).
    Subsequent calls reuse the cached module.
    """
    global _api_mod
    if _api_mod is None:
        from urbansolarcarver import api as mod
        _api_mod = mod
    return getattr(_api_mod, attr)


# ---------------------------------------------------------------------------
# Daemon helpers
# ---------------------------------------------------------------------------
def _daemon_authkey() -> bytes:
    """Read the shared authkey used to authenticate daemon connections."""
    from .daemon import _resolve_authkey
    return _resolve_authkey()


def _daemon_send(payload: dict) -> dict:
    """Send an RPC command to the daemon and return its response.

    Uses ``multiprocessing.connection.Client`` over localhost TCP.
    Raises ``ConnectionRefusedError`` if the daemon is not running.
    """
    from multiprocessing.connection import Client
    conn = Client((daemon_host, daemon_port), authkey=_daemon_authkey())
    try:
        conn.send(payload)
        return conn.recv()
    finally:
        conn.close()


def _echo_result(label: str, key_fields: dict):
    """Print a human-friendly summary after a stage completes."""
    typer.secho(f"\n  {label} complete", fg="green", bold=True)
    for k, v in key_fields.items():
        typer.echo(f"    {k}: {v}")
    typer.echo()


# ---------------------------------------------------------------------------
# App — Typer instance with no shell-completion overhead.
# ---------------------------------------------------------------------------
app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _version_callback(value: bool):
    """Eager callback for ``--version`` / ``-V``."""
    if value:
        typer.echo(f"urbansolarcarver {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = Option(
        False, "--version", "-V", callback=_version_callback,
        is_eager=True, help="Show version and exit",
    ),
    quiet: bool = Option(
        False, "--quiet", "-q",
        help="Suppress torch/warp banners and non-essential output",
    ),
):
    """GPU-accelerated solar envelope generation for urban design."""
    if quiet:
        os.environ["WP_QUIET"] = "1"
        os.environ["WARP_LOG_LEVEL"] = "error"
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


# ---------------------------------------------------------------------------
# run — one-shot full pipeline
# ---------------------------------------------------------------------------
@app.command(help="Run the full pipeline (preprocessing + thresholding + exporting)")
def run(
    config: Path = Option(..., "-c", "--config", exists=True, readable=True, help="YAML config path"),
    override: List[str] = Option([], "-o", "--override", help="Override config KEY=VALUE"),
    out_dir: Optional[Path] = Option(None, "--out", help="Output root directory"),
    daemon: bool = Option(False, "--daemon", help="Send to running daemon instead of running locally"),
    quiet: bool = Option(False, "-q", "--quiet", help="Minimal output"),
):
    """Chain all three stages and write the final carved mesh.

    This is the simplest entry point — equivalent to calling preprocessing,
    thresholding, and exporting in sequence.  For iterating on threshold
    parameters without re-computing scores, use the individual stage commands.
    """
    if daemon:
        resp = _daemon_send({
            "cmd": "run_pipeline", "config": str(config),
            "overrides": override, "out_dir": str(out_dir) if out_dir else None,
        })
        typer.echo(json.dumps(resp, indent=2))
        return

    cfg = load_config(str(config), override)
    out = out_dir or Path(cfg.out_dir)

    if not quiet:
        typer.secho(f"  Mode: {cfg.mode}", bold=True)
        typer.secho(f"  Voxel size: {cfg.voxel_size}m")
        typer.secho(f"  Output: {out}\n")

    run_pipeline = _api("run_pipeline")

    if not quiet:
        typer.secho("  Running pipeline (preprocessing + thresholding + exporting)...", fg="yellow")
    t0 = time.perf_counter()
    res = run_pipeline(cfg, out)
    elapsed = time.perf_counter() - t0

    _echo_result("Pipeline", {
        "Mesh": str(res.export_path),
        "Volume retained": f"{res.retention_pct:.1f}%" + (f" ({res.mesh_volume_m3:.0f} m³)" if res.mesh_volume_m3 is not None else ""),
        "Faces": f"{res.faces:,}",
        "Time": f"{elapsed:.1f}s",
    })


# ---------------------------------------------------------------------------
# Individual stage commands
#
# Each stage can run standalone:
#   - preprocessing: reads config + meshes, writes scores.npy + manifest
#   - thresholding:  reads preprocessing manifest, writes mask.npy + manifest
#   - exporting:     reads thresholding manifest, writes carved_mesh.ply
#
# The --daemon flag sends the job to the GPU daemon over localhost RPC,
# sharing the warm CUDA context.  Without --daemon, the stage runs in-process.
# ---------------------------------------------------------------------------
@app.command("preprocessing", help="Stage 1: compute per-voxel obstruction scores")
def cmd_preprocessing(
    config: Path = Option(..., "-c", "--config", exists=True, readable=True, help="YAML config path"),
    override: List[str] = Option([], "-o", "--override", help="Override config fields"),
    out_dir: Optional[Path] = Option(None, "--out", help="Output directory"),
    daemon: bool = Option(False, "--daemon", help="Send to running daemon"),
    quiet: bool = Option(False, "-q", "--quiet", help="Minimal output"),
    dry_run: bool = Option(False, "--dry-run", help="Estimate grid size and memory, then exit without running"),
):
    """Voxelize, sample surfaces, trace rays, and write scores.

    Outputs ``scores.npy``, ``voxel_grid.npy``, and ``manifest.json`` into
    the output directory.  The manifest is consumed by the thresholding stage.
    """
    if daemon:
        resp = _daemon_send({
            "cmd": "preprocessing", "config": str(config),
            "overrides": override, "out_dir": str(out_dir) if out_dir else None,
        })
        typer.echo(json.dumps(resp, indent=2))
        return

    cfg = load_config(str(config), override)
    out_dir = out_dir or (Path(cfg.out_dir) / "preprocessing")

    if dry_run:
        from .api_core._reporting import estimate_grid_memory
        est = estimate_grid_memory(cfg.voxel_size, cfg.max_volume_path, cfg.margin_frac)
        typer.secho(f"\n  Dry-run estimate ({cfg.mode})", fg="cyan", bold=True)
        typer.echo(f"    Grid: {est['grid_dims'][0]} x {est['grid_dims'][1]} x {est['grid_dims'][2]}")
        typer.echo(f"    Voxels: {est['total_voxels']:,}")
        typer.echo(f"    Est. memory: {est['memory_mb']:,.0f} MB")
        if est['warning']:
            typer.secho(f"    Warning: {est['warning']}", fg="yellow")
        else:
            typer.secho(f"    Grid size looks reasonable", fg="green")
        typer.echo()
        raise typer.Exit(0)

    if not quiet:
        typer.secho(f"  Preprocessing [{cfg.mode}] -> {out_dir}", fg="yellow")

    t0 = time.perf_counter()
    res = _api("preprocessing")(cfg, out_dir)
    elapsed = time.perf_counter() - t0

    _echo_result("Preprocessing", {
        "Device": res.device_info,
        "Grid": f"{res.volume_shape}",
        "Scores": str(res.volume_path),
        "Hash": res.hash[:12],
        "Time": f"{elapsed:.1f}s",
    })


@app.command("thresholding", help="Stage 2: apply threshold to scores -> binary mask")
def cmd_thresholding(
    from_manifest: Optional[Path] = Option(None, "-f", "--from", help="Path to preprocessing manifest.json (auto-detected if omitted)"),
    config: Path = Option(..., "-c", "--config", exists=True, readable=True, help="YAML config path"),
    override: List[str] = Option([], "-o", "--override", help="Override config fields"),
    out_dir: Optional[Path] = Option(None, "--out", help="Output directory"),
    daemon: bool = Option(False, "--daemon", help="Send to running daemon"),
    quiet: bool = Option(False, "-q", "--quiet", help="Minimal output"),
):
    """Normalize scores and apply the selected thresholding strategy.

    Reads the preprocessing manifest (``-f``) to locate ``scores.npy``,
    applies the threshold from the config, and writes ``mask.npy``.

    This is the cheapest stage — designed for rapid iteration.  Re-run with
    different ``-o threshold=...`` or ``-o carve_fraction=...`` values without
    recomputing scores.
    """
    if daemon:
        resp = _daemon_send({
            "cmd": "thresholding", "from": str(from_manifest),
            "config": str(config), "overrides": override,
            "out_dir": str(out_dir) if out_dir else None,
        })
        typer.echo(json.dumps(resp, indent=2))
        return

    cfg = load_config(str(config), override)
    out_dir = out_dir or (Path(cfg.out_dir) / "thresholding")

    if from_manifest is None:
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

    if not quiet:
        typer.secho(f"  Thresholding [{cfg.threshold}] -> {out_dir}", fg="yellow")

    t0 = time.perf_counter()
    res = _api("thresholding")(from_manifest, cfg, out_dir)
    elapsed = time.perf_counter() - t0

    _echo_result("Thresholding", {
        "Method": f"{res.threshold_method} -> {res.threshold_value:.4g}",
        "Carved": f"{res.voxels_removed:,} voxels ({100 - res.retention_pct:.1f}% of volume)",
        "Retained": f"{res.voxels_kept:,} voxels ({res.retention_pct:.1f}%)",
        "Hash": res.hash[:12],
        "Time": f"{elapsed:.1f}s",
    })


@app.command("exporting", help="Stage 3: reconstruct mesh from mask -> PLY")
def cmd_exporting(
    from_manifest: Optional[Path] = Option(None, "-f", "--from", help="Path to thresholding manifest.json (auto-detected if omitted)"),
    config: Path = Option(..., "-c", "--config", exists=True, readable=True, help="YAML config path"),
    override: List[str] = Option([], "-o", "--override", help="Override config fields"),
    out_dir: Optional[Path] = Option(None, "--out", help="Output directory"),
    daemon: bool = Option(False, "--daemon", help="Send to running daemon"),
    quiet: bool = Option(False, "-q", "--quiet", help="Minimal output"),
):
    """Reconstruct a triangle mesh from the binary carving mask.

    Reads the thresholding manifest (``-f``) to locate ``mask.npy``,
    prunes small disconnected clusters, reconstructs a triangle mesh
    (cubic faces or SDF-smoothed marching cubes), and writes
    ``export.<format>`` (format from ``final_mesh_format``, default ply).
    """
    if daemon:
        resp = _daemon_send({
            "cmd": "exporting", "from": str(from_manifest),
            "config": str(config), "overrides": override,
            "out_dir": str(out_dir) if out_dir else None,
        })
        typer.echo(json.dumps(resp, indent=2))
        return

    cfg = load_config(str(config), override)
    out_dir = out_dir or (Path(cfg.out_dir) / "exporting")

    if from_manifest is None:
        parent = out_dir.parent if out_dir.name == "exporting" else out_dir
        candidate = parent / "thresholding" / "manifest.json"
        if candidate.is_file():
            from_manifest = candidate
            if not quiet:
                typer.secho(f"  Auto-detected manifest: {candidate}", fg="cyan")
        else:
            typer.secho(
                "  No -f/--from given and no thresholding/manifest.json found in the default layout. "
                "Use -f to specify the manifest path, or use the default output directory structure.",
                fg="red",
            )
            raise typer.Exit(1)

    if not quiet:
        typer.secho(f"  Exporting -> {out_dir}", fg="yellow")

    t0 = time.perf_counter()
    res = _api("exporting")(from_manifest, cfg, out_dir)
    elapsed = time.perf_counter() - t0

    _echo_result("Exporting", {
        "Mesh": str(res.export_path),
        "Volume retained": f"{res.retention_pct:.1f}%" + (f" ({res.mesh_volume_m3:.0f} m³)" if res.mesh_volume_m3 is not None else ""),
        "Faces": f"{res.faces:,}",
        "Time": f"{elapsed:.1f}s",
    })


# ---------------------------------------------------------------------------
# warmup — precompile Warp kernels so the first run isn't misleadingly slow
# ---------------------------------------------------------------------------
@app.command(help="Precompile GPU/CPU compute kernels (one-time, cached on disk)")
def warmup(
    device: str = Option("auto", "--device", "-d", help="Target device: 'auto', 'cpu', or 'cuda'"),
):
    """Compile the Warp compute kernels ahead of time.

    Warp JIT-compiles kernels on first use — a one-time ~3-10 s cost per
    machine and per code version, cached on disk afterwards.  Run this once
    after installation or after updating UrbanSolarCarver so your first
    carving run reflects real compute time.  (``setup_env.py`` and the
    daemon do this automatically.)
    """
    if device not in ("auto", "cpu", "cuda"):
        typer.secho(f"  Invalid device {device!r} — use 'auto', 'cpu', or 'cuda'", fg="red")
        raise typer.Exit(1)

    typer.secho(f"  Compiling Warp kernels (device={device})...", fg="yellow")
    t0 = time.perf_counter()
    from .raytracer import warmup_kernels
    ok = warmup_kernels(None if device == "auto" else device)
    elapsed = time.perf_counter() - t0
    if ok:
        typer.secho(f"  Kernels ready in {elapsed:.1f}s (cached on disk for future runs)", fg="green")
    else:
        typer.secho(
            "  Warp backend not available on the requested device — "
            "kernels will compile lazily on first use.", fg="yellow",
        )
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# validate — quick config check without loading heavy deps
# ---------------------------------------------------------------------------
@app.command(name="simulate-weights", help="Generate a simulated-weights artifact (ISO 13790 5R1C) for benefit mode")
def simulate_weights(
    epw: Path = Option(..., "-e", "--epw", exists=True, readable=True,
                       help="EPW weather file"),
    archetype: Path = Option(..., "-a", "--archetype", exists=True, readable=True,
                             help="Archetype YAML (see configs/archetype_example.yaml)"),
    out: Path = Option(Path("simulated_weights.json"), "-o", "--out",
                       help="Output artifact path"),
    eps: float = Option(1.0, "--eps",
                        help="Perturbation size in W (central differences)"),
):
    """Simulated benefit weights: hourly marginal benefit + harm of solar gain from the
    ISO 13790 Annex C simple hourly model (5R1C), by perturbation.

    The artifact feeds benefit mode's ``simulated_weights_path`` config key,
    replacing the balance-point Heaviside hour filter with physics-derived
    hourly weights. See design/simulated-weights.md.
    """
    import yaml
    from urbansolarcarver.simulated_weights import generate_simulated_weights

    arch = yaml.safe_load(archetype.read_text(encoding="utf-8"))
    if not isinstance(arch, dict):
        typer.secho("  Archetype file must be a YAML mapping", fg="red")
        raise typer.Exit(1)
    typer.echo(f"  Running 5R1C perturbation attribution ({epw.name}) ...")
    try:
        path = generate_simulated_weights(str(epw), arch, out, eps=eps)
    except (ValueError, TypeError) as exc:
        typer.secho(f"  {exc}", fg="red")
        raise typer.Exit(1)
    typer.secho(f"  Wrote {path}", fg="green")
    preview = path.with_suffix(".png")
    if preview.exists():
        typer.echo(f"  Weights preview: {preview}")


# Shoebox archetype template written by `usc archetype`. Values are the
# neutral example set; -s overrides replace them before writing.
_ARCHETYPE_TEMPLATE = """\
# Building archetype for `usc simulate-weights` (simulated benefit weights).
# Shoebox form: floor area, volume, facade and window areas are derived.
# NEUTRAL EXAMPLE VALUES: source real ones from TABULA (EU), DOE prototypes
# (US), or your national code tables. See design/simulated-weights.md.

# --- Geometry ---
width: {width}              # m, east-west dimension
length: {length}             # m, north-south dimension
height: {height}             # m, storey height
wwr:                     # window-to-wall ratio per facade (omit = no windows)
{wwr_block}g_value: {g_value}             # glazing solar transmittance
{orientation_line}
# --- Fabric and systems ---
u_opaque: {u_opaque}            # W/m2K, area-weighted opaque envelope U-value
u_window: {u_window}            # W/m2K, glazing U-value
ach_vent: {ach_vent}            # 1/h intentional ventilation
ach_infiltration: {ach_infiltration}    # 1/h infiltration
heat_recovery: {heat_recovery}       # 0-1 ventilation heat-recovery efficiency
mass_class: {mass_class}       # very_light | light | medium | heavy | very_heavy
t_set_heating: {t_set_heating}      # deg C
t_set_cooling: {t_set_cooling}      # deg C
internal_gains_w_m2: {internal_gains_w_m2} # W per m2 floor area, flat schedule
{shading_block}"""

_SHADING_TEMPLATE = """\

# --- Shading coefficients (declared multipliers; no device geometry) ---
# Transmission factors in [0, 1]: 1 = no shading. Scalar applies to all
# facades; a mapping (north/east/south/west) sets them per facade.
{shading_permanent_line}
{shading_hot_line}
{hot_months_line}
"""

_ARCHETYPE_DEFAULTS = {
    "width": 10.0, "length": 10.0, "height": 3.0,
    "wwr": {"south": 0.35, "east": 0.15, "west": 0.15},
    "g_value": 0.6, "orientation": 0.0,
    "u_opaque": 0.6, "u_window": 1.6,
    "ach_vent": 0.8, "ach_infiltration": 0.3, "heat_recovery": 0.0,
    "mass_class": "medium",
    "t_set_heating": 20.0, "t_set_cooling": 26.0,
    "internal_gains_w_m2": 5.0,
}
_WWR_SIDES = ("north", "east", "south", "west")
# Optional keys with no default (absent = feature off).
_ARCHETYPE_OPTIONAL = ("shading_permanent", "shading_hot", "hot_months")


@app.command(help="Create and validate a shoebox archetype YAML for simulate-weights")
def archetype(
    out: Path = Option(Path("archetype.yaml"), "-o", "--out",
                       help="Output archetype YAML path"),
    set_: List[str] = Option([], "-s", "--set",
                             help="Override a field, e.g. -s width=12 "
                                  "-s wwr_south=0.4 -s mass_class=heavy"),
    from_: Optional[Path] = Option(None, "--from",
                                   help="Start from an existing shoebox "
                                        "archetype YAML instead of defaults"),
    force: bool = Option(False, "--force",
                         help="Overwrite the output file if it exists"),
):
    """Build a shoebox archetype, validate it, and report derived quantities.

    The file is validated through the same code path the generator uses
    (``expand_shoebox`` + ``ZoneParams.from_archetype``) before writing, and
    the derived floor area, volume, and per-facade window areas are printed
    so mistakes surface here rather than inside a simulation.

    Only the shoebox form is built by this command; explicit-area archetypes
    are edited directly in YAML (see configs/archetype_example.yaml).
    """
    import yaml
    from urbansolarcarver.simulated_weights import (
        ZoneParams, expand_shoebox,
    )

    values = dict(_ARCHETYPE_DEFAULTS)
    values["wwr"] = dict(values["wwr"])

    if from_ is not None:
        base = yaml.safe_load(from_.read_text(encoding="utf-8"))
        if not isinstance(base, dict):
            typer.secho("  --from file must be a YAML mapping", fg="red")
            raise typer.Exit(1)
        explicit = {"floor_area", "volume", "area_opaque", "area_window",
                    "windows"} & base.keys()
        if explicit:
            typer.secho(f"  --from file uses explicit areas {sorted(explicit)}; "
                        "only shoebox-form archetypes can be edited here — "
                        "edit that YAML directly instead", fg="red")
            raise typer.Exit(1)
        unknown = (set(base) - set(_ARCHETYPE_DEFAULTS) - {"wwr"}
                   - set(_ARCHETYPE_OPTIONAL))
        if unknown:
            typer.secho(f"  Unknown archetype keys in --from file: "
                        f"{sorted(unknown)}", fg="red")
            raise typer.Exit(1)
        wwr = base.pop("wwr", None)
        values.update(base)
        if wwr is not None:
            values["wwr"] = dict(wwr)

    for item in set_:
        if "=" not in item:
            typer.secho(f"  Bad -s override {item!r}: expected KEY=VALUE",
                        fg="red")
            raise typer.Exit(1)
        key, _, raw = item.partition("=")
        key = key.strip()
        raw = raw.strip()
        if key.startswith("wwr_"):
            side = key[4:]
            if side not in _WWR_SIDES:
                typer.secho(f"  Unknown facade {side!r}: use wwr_north / "
                            "wwr_east / wwr_south / wwr_west", fg="red")
                raise typer.Exit(1)
            values["wwr"][side] = float(raw)
            continue
        if key == "hot_months":
            values[key] = [int(m) for m in raw.split(",") if m.strip()]
            continue
        if key in ("shading_permanent", "shading_hot"):
            values[key] = float(raw)
            continue
        if key not in _ARCHETYPE_DEFAULTS or key == "wwr":
            typer.secho(f"  Unknown archetype key {key!r}", fg="red")
            raise typer.Exit(1)
        if key == "mass_class":
            values[key] = raw
        else:
            values[key] = float(raw)

    # Drop zero-WWR facades so the written file stays minimal.
    values["wwr"] = {s: v for s, v in values["wwr"].items() if v > 0.0}

    # Validate through the generator's own code path and derive quantities.
    arch = {k: v for k, v in values.items()
            if k not in ("internal_gains_w_m2",) + _ARCHETYPE_OPTIONAL
            and not (k == "orientation" and not v)}
    try:
        expanded = expand_shoebox(arch)
        windows = expanded.pop("windows")
        ZoneParams.from_archetype(**expanded)
        if any(k in values for k in _ARCHETYPE_OPTIONAL):
            from urbansolarcarver.simulated_weights import _shading_factors
            _shading_factors(windows,
                             values.get("shading_permanent"),
                             values.get("shading_hot"),
                             values.get("hot_months"))
    except (ValueError, TypeError) as exc:
        typer.secho(f"  INVALID archetype: {exc}", fg="red")
        raise typer.Exit(1)

    if out.exists() and not force:
        typer.secho(f"  {out} exists — use --force to overwrite", fg="red")
        raise typer.Exit(1)

    wwr_block = "".join(f"  {side}: {values['wwr'][side]}\n"
                        for side in _WWR_SIDES if side in values["wwr"])
    orientation_line = (
        f"orientation: {values['orientation']}        # deg, rotate the box clockwise from north"
        if values.get("orientation") else
        "# orientation: 0.0       # deg, rotate the box clockwise from north"
    )
    shading_block = _SHADING_TEMPLATE.format(
        shading_permanent_line=(
            f"shading_permanent: {values['shading_permanent']}"
            if "shading_permanent" in values else
            "# shading_permanent: 0.9"),
        shading_hot_line=(
            f"shading_hot: {values['shading_hot']}"
            if "shading_hot" in values else
            "# shading_hot: 0.5"),
        hot_months_line=(
            f"hot_months: {values['hot_months']}"
            if "hot_months" in values else
            "# hot_months: [6, 7, 8, 9]"),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_ARCHETYPE_TEMPLATE.format(
        wwr_block=wwr_block, orientation_line=orientation_line,
        shading_block=shading_block,
        **{k: v for k, v in values.items()
           if k not in ("wwr", "orientation") + _ARCHETYPE_OPTIONAL},
    ), encoding="utf-8")

    typer.secho(f"  Wrote {out}", fg="green", bold=True)
    typer.echo("  Derived from the shoebox geometry:")
    typer.echo(f"    floor_area:  {expanded['floor_area']:.1f} m2")
    typer.echo(f"    volume:      {expanded['volume']:.1f} m3")
    typer.echo(f"    area_opaque: {expanded['area_opaque']:.1f} m2 (opaque walls + roof)")
    typer.echo(f"    area_window: {expanded['area_window']:.1f} m2")
    for az, area, g in windows:
        typer.echo(f"      window: azimuth {az:5.1f} deg, {area:.1f} m2, g={g}")
    typer.echo(f"  Next: usc simulate-weights -e <weather.epw> -a {out}")


@app.command(help="Validate a config file without running the pipeline")
def validate(
    config: Path = Option(..., "-c", "--config", exists=True, readable=True, help="YAML config path"),
    override: List[str] = Option([], "-o", "--override", help="Override config fields"),
):
    """Parse and validate the YAML config through Pydantic.

    Checks schema validity, value bounds, and that referenced file paths
    (meshes, EPW) exist on disk.  Does not initialise CUDA or import torch.
    """
    try:
        cfg = load_config(str(config), override)
    except Exception as e:
        typer.secho(f"  INVALID: {e}", fg="red")
        raise typer.Exit(1)

    typer.secho("  Config OK", fg="green", bold=True)
    typer.echo(f"    mode:       {cfg.mode}")
    typer.echo(f"    voxel_size: {cfg.voxel_size}")
    typer.echo(f"    threshold:  {cfg.threshold}")
    typer.echo(f"    device:     {cfg.device}")
    typer.echo(f"    out_dir:    {cfg.out_dir}")

    # Warn about missing file paths (non-fatal — user may fix before running)
    problems = []
    if cfg.max_volume_path and not Path(cfg.max_volume_path).exists():
        problems.append(f"max_volume_path not found: {cfg.max_volume_path}")
    if cfg.test_surface_path and not Path(cfg.test_surface_path).exists():
        problems.append(f"test_surface_path not found: {cfg.test_surface_path}")
    if cfg.epw_path and not Path(cfg.epw_path).exists():
        problems.append(f"epw_path not found: {cfg.epw_path}")
    if getattr(cfg, "simulated_weights_path", None):
        # Validate the artifact itself, not just the path: a wrong-schema
        # or truncated file should fail here, not mid-preprocessing.
        try:
            from urbansolarcarver.simulated_weights import read_simulated_weights
            _b, _h, meta = read_simulated_weights(cfg.simulated_weights_path)
            typer.echo(f"    weights:    {cfg.simulated_weights_path} "
                       f"({meta.get('method', 'unknown method')})")
        except (ValueError, OSError) as exc:
            problems.append(f"simulated_weights_path invalid: {exc}")

    if problems:
        typer.echo()
        for p in problems:
            typer.secho(f"    WARNING: {p}", fg="yellow")
    typer.echo()


# ---------------------------------------------------------------------------
# schema — filterable parameter reference printed to terminal
# ---------------------------------------------------------------------------
@app.command(help="Show config parameters (optionally filtered by --mode or --search)")
def schema(
    mode: Optional[str] = Option(None, "--mode", "-m", help="Show only parameters relevant to this mode"),
    search: Optional[str] = Option(None, "--search", "-s", help="Filter parameters by name or description substring"),
):
    """Print the full ``UserConfig`` parameter table.

    Reads field metadata from the Pydantic schema — no heavy imports needed.
    Filter by mode (``--mode benefit``) to see only the parameters that mode
    uses, or search by keyword (``--search threshold``).
    """
    import shutil
    import textwrap

    from .mode_registry import MODES
    # Derive per-mode parameter sets from the registry.
    MODE_PARAMS = {name: set(spec.extra_params) for name, spec in MODES.items()}
    # Parameters shared by all modes.
    COMMON = {"max_volume_path", "test_surface_path", "out_dir", "mode", "voxel_size", "grid_step",
              "ray_length", "ray_batch_size", "threshold", "carve_fraction", "apply_smoothing",
              "min_voxels", "device", "diagnostics", "edge_taper"}

    if mode and mode not in MODE_PARAMS:
        typer.secho(f"  Unknown mode {mode!r}. Valid modes: {', '.join(sorted(MODE_PARAMS))}", fg="red")
        raise typer.Exit(1)

    rows = []
    for name, fld in user_config.model_fields.items():
        if mode:
            allowed = COMMON | MODE_PARAMS[mode]
            if name not in allowed:
                continue

        typ = fld.annotation
        tnm = getattr(typ, "__name__", str(typ))
        default = "<required>" if fld.is_required() else repr(fld.default) if fld.default is not None else "<none>"
        desc = fld.description or ""

        if search and search.lower() not in name.lower() and search.lower() not in desc.lower():
            continue

        rows.append((name, tnm, default, desc))

    if not rows:
        typer.secho("  No matching parameters found.", fg="yellow")
        raise typer.Exit()

    # Format as a fixed-width table that adapts to terminal width.
    total_width = shutil.get_terminal_size(fallback=(100, 20)).columns
    name_w, type_w, def_w = 24, 14, 14
    sep = "  "
    desc_w = max(20, total_width - (name_w + type_w + def_w + len(sep) * 3))

    header_fmt = f"{{:<{name_w}}}{sep}{{:<{type_w}}}{sep}{{:<{def_w}}}{sep}{{}}"
    typer.echo()
    typer.secho(header_fmt.format("Name", "Type", "Default", "Description"), bold=True)
    typer.echo("-" * min(total_width, name_w + type_w + def_w + desc_w + len(sep) * 3))

    for name, tnm, default, desc in rows:
        wrapped = textwrap.wrap(desc, width=desc_w) or [""]
        typer.echo(f"{name:<{name_w}}{sep}{tnm:<{type_w}}{sep}{default:<{def_w}}{sep}{wrapped[0]}")
        for line in wrapped[1:]:
            typer.echo(f"{'':<{name_w}}{sep}{'':<{type_w}}{sep}{'':<{def_w}}{sep}{line}")

    if mode:
        typer.echo(f"\n  Showing parameters for mode: {mode}")
    typer.echo(f"  {len(rows)} parameters\n")


# ---------------------------------------------------------------------------
# Daemon management
#
# The daemon keeps a CarverSession alive (warm CUDA context + compiled Warp
# kernels) so that consecutive pipeline calls avoid the ~2 s cold-start.
# Used by: Grasshopper plugin (via USC_Session component) and CLI --daemon.
# Binds to localhost only; authenticated with a random authkey.
# ---------------------------------------------------------------------------
daemon_app = typer.Typer(help="Control the persistent Warp/CUDA daemon")
app.add_typer(daemon_app, name="daemon")


@daemon_app.command("start", help="Launch daemon (detached by default)")
def daemon_start(
    foreground: bool = Option(False, "-F", "--foreground", help="Run daemon in this console (blocks)"),
    python: Optional[Path] = Option(None, "--python", help="Python interpreter to use for the daemon process"),
):
    """Start the GPU daemon as a detached background process.

    On Windows, uses ``pythonw.exe`` by default to avoid a visible console
    window.  Use ``-F`` to run in the foreground (useful for debugging).
    Polls until the daemon accepts connections, then prints a confirmation.
    """
    if python is not None:
        py = python
    else:
        # On Windows, prefer pythonw.exe (no console window) for background.
        if platform.system() == "Windows":
            exe = Path(sys.executable)
            py = exe.with_name("pythonw.exe") if exe.name.lower().endswith("python.exe") else exe
        else:
            py = Path(sys.executable)

    daemon_py = Path(__file__).with_name("daemon.py")
    cmd = [str(py), str(daemon_py), "--host", daemon_host, "--port", str(daemon_port)]

    if foreground:
        subprocess.call(cmd)
    else:
        # Launch detached subprocess.
        if platform.system() == "Windows":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        else:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setpgrp)

        # Poll until daemon responds to a ping (up to 30 s).
        typer.echo("  Starting daemon...")
        interval = 1.0
        max_retries = 30
        for attempt in range(max_retries):
            try:
                resp = _daemon_send({"cmd": "ping"})
                if resp.get("status") == "ok":
                    break
            except (ConnectionRefusedError, OSError):
                pass
            time.sleep(interval)
        else:
            typer.secho(f"  Daemon did not become ready after {max_retries}s", fg="red")
            raise typer.Exit(1)
        typer.secho(f"  Daemon ready on {daemon_host}:{daemon_port}", fg="green")


@daemon_app.command("stop", help="Shutdown the running daemon")
def daemon_stop():
    """Send a shutdown command to the running daemon."""
    try:
        resp = _daemon_send({"cmd": "shutdown"})
        typer.secho(f"  Daemon stopped: {resp}", fg="green")
    except Exception as e:
        typer.secho(f"  Could not contact daemon: {e}", fg="red")
        raise typer.Exit(1)


@daemon_app.command("status", help="Check if the daemon is running")
def daemon_status():
    """Probe the daemon with a ping to check if it's alive and accepting commands."""
    try:
        resp = _daemon_send({"cmd": "ping"})
        pid = resp.get("pid", "?")
        typer.secho(f"  Daemon running on {daemon_host}:{daemon_port} (pid={pid})", fg="green")
    except (ConnectionRefusedError, OSError):
        typer.secho("  Daemon not running", fg="yellow")
    except Exception as e:
        typer.secho(f"  Error: {e}", fg="red")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
