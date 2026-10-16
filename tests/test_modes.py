"""Smoke tests that the tilted_plane, time-based, irradiance, benefit and daylight
modes run end to end on a tiny mesh, plus checks of the benefit-mode weight formula."""
import numpy as np
import pytest
import yaml
from pathlib import Path


def _write_config(tmp_path, vol_path, srf_path, epw_path, mode, **extra):
    """Write a minimal YAML config and return loaded UserConfig."""
    from urbansolarcarver import load_config
    cfg_dict = {
        "max_volume_path": str(vol_path),
        "test_surface_path": str(srf_path),
        "out_dir": str(tmp_path / "out"),
        "mode": mode,
        "voxel_size": 2.0,
        "grid_step": 2.0,
        "ray_length": 50.0,
        "ray_batch_size": 50000,
        "threshold": 0.5,
        "apply_smoothing": False,
        "min_voxels": 1,
        "min_face_count": 1,
        "device": "cpu",
    }
    if epw_path:
        cfg_dict["epw_path"] = str(epw_path)
        cfg_dict.update(start_month=1, start_day=1, start_hour=8,
                        end_month=1, end_day=1, end_hour=16)
    cfg_dict.update(extra)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg_dict), encoding="utf-8")
    return load_config(str(cfg_path))


def _run_mode(tmp_path, vol_path, srf_path, epw_path, mode, **extra):
    """Run full pipeline for a mode and return the PipelineResult."""
    from urbansolarcarver import run_pipeline
    cfg = _write_config(tmp_path, vol_path, srf_path, epw_path, mode, **extra)
    return run_pipeline(cfg, tmp_path / "pipeline_out")


# --- tilted_plane: no EPW needed, always runs ---

def test_smoke_tilted_plane(tmp_path, tmp_mesh_files):
    vol_path, srf_path = tmp_mesh_files
    result = _run_mode(
        tmp_path, vol_path, srf_path, epw_path=None,
        mode="tilted_plane", tilted_plane_angle_deg=45.0,
        threshold=None,
    )
    assert result.exporting.export_path.exists()
    import trimesh
    mesh = trimesh.load(str(result.exporting.export_path))
    assert len(mesh.vertices) > 0


# --- EPW-dependent modes ---

# Weighted modes use the relative carve_fraction threshold: a raw numeric
# cutoff like 0.5 is meaningless against cumulative kWh/m² scores (it would
# carve every voxel any ray touched, producing an empty envelope).
@pytest.mark.parametrize("mode,extra", [
    ("time-based", {}),
    ("irradiance", {"threshold": "carve_fraction", "carve_fraction": 0.7}),
    ("benefit", {"threshold": "carve_fraction", "carve_fraction": 0.7}),
    ("daylight", {"threshold": "carve_fraction", "carve_fraction": 0.7}),
])
def test_smoke_epw_modes(tmp_path, tmp_mesh_files, example_epw_path, mode, extra):
    vol_path, srf_path = tmp_mesh_files
    result = _run_mode(
        tmp_path, vol_path, srf_path, example_epw_path,
        mode=mode, **extra,
    )
    assert result.exporting.export_path.exists()
    import trimesh
    mesh = trimesh.load(str(result.exporting.export_path))
    assert len(mesh.vertices) > 0


# --- Benefit weight semantics (documented Heaviside formula) ---

class TestBenefitWeights:
    def test_benefit_equals_irradiance_over_cold_hours(self, example_epw_path):
        """The benefit weights must equal a plain irradiance matrix computed
        over exactly the hours below balance_temperature - balance_offset
        (the documented formula, with no hidden harm subtraction)."""
        import torch
        from ladybug.epw import EPW
        from urbansolarcarver.sky_patches import compute_EPW_based_weights

        # Shoulder-season days: a genuine mix of cold and warm hours.
        hoys = list(range(24 * 100, 24 * 110))  # ~April 10-20
        bal, off = 15.0, 2.0
        dbt = EPW(str(example_epw_path)).dry_bulb_temperature.values
        cold = [h for h in hoys if dbt[h] < bal - off]
        assert cold, "expected some cold hours in the test window"
        assert len(cold) < len(hoys), "expected some warm hours in the test window"

        w_benefit = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"),
            balance_temperature=bal, balance_offset=off,
        )
        w_cold_irr = compute_EPW_based_weights(
            "irradiance", str(example_epw_path), cold, torch.device("cpu"),
        )
        torch.testing.assert_close(w_benefit, w_cold_irr, rtol=1e-5, atol=1e-3)

    def test_no_cold_hours_warns_and_returns_zeros(self, example_epw_path):
        """An analysis period with no beneficial hours must warn and return
        all-zero weights. It must not pass the empty hour-of-year list to
        Ladybug, which treats an empty list as the whole year."""
        import torch
        from urbansolarcarver.sky_patches import compute_EPW_based_weights

        hoys = list(range(24 * 190, 24 * 195))  # July days
        with pytest.warns(UserWarning, match="no hours in the analysis period"):
            w = compute_EPW_based_weights(
                "benefit", str(example_epw_path), hoys, torch.device("cpu"),
                balance_temperature=-60.0, balance_offset=0.0,
            )
        assert float(w.sum()) == 0.0
        assert w.shape[0] == 145

    def test_include_harm_composite(self, example_epw_path):
        """include_harm=True must equal clip(cold-hour matrix − hot-hour
        matrix, 0), and can only reduce weights vs the default formula."""
        import torch
        from ladybug.epw import EPW
        from urbansolarcarver.sky_patches import compute_EPW_based_weights

        # Wide shoulder-to-summer window: guaranteed hot AND cold hours.
        hoys = list(range(24 * 100, 24 * 200))  # ~April 10 – July 19
        bal, off = 15.0, 2.0
        dbt = EPW(str(example_epw_path)).dry_bulb_temperature.values
        cold = [h for h in hoys if dbt[h] < bal - off]
        hot = [h for h in hoys if dbt[h] > bal + off]
        assert cold and hot, "expected a cold/hot mix in the test window"

        w_default = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"),
            balance_temperature=bal, balance_offset=off,
        )
        w_composite = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"),
            balance_temperature=bal, balance_offset=off, include_harm=True,
        )
        w_hot = compute_EPW_based_weights(
            "irradiance", str(example_epw_path), hot, torch.device("cpu"),
        )
        expected = torch.clamp(w_default - w_hot, min=0.0)
        torch.testing.assert_close(w_composite, expected, rtol=1e-5, atol=1e-3)
        assert (w_composite <= w_default + 1e-6).all()
        assert float(w_composite.sum()) < float(w_default.sum())

    def test_simulated_weights_all_ones_equals_irradiance(self, example_epw_path):
        """An all-ones weight schedule must reproduce plain irradiance
        weights over the same hours, because the simulated-weights path is a
        pure hourly re-weighting of the same sky integration."""
        import torch
        from urbansolarcarver.sky_patches import compute_EPW_based_weights

        hoys = list(range(24 * 40, 24 * 50))
        ones = np.ones(8760)
        zeros = np.zeros(8760)
        w_sched = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"),
            simulated_weights=(ones, zeros),
        )
        w_irr = compute_EPW_based_weights(
            "irradiance", str(example_epw_path), hoys, torch.device("cpu"),
        )
        torch.testing.assert_close(w_sched, w_irr, rtol=1e-3, atol=1e-2)

    def test_simulated_weights_binary_schedule_equals_heaviside(self, example_epw_path):
        """A 0/1 schedule built from the balance filter must reproduce the
        default benefit weights: the Heaviside step is the binary special case."""
        import torch
        from ladybug.epw import EPW
        from urbansolarcarver.sky_patches import compute_EPW_based_weights

        hoys = list(range(24 * 100, 24 * 110))
        bal, off = 15.0, 2.0
        dbt = np.asarray(EPW(str(example_epw_path)).dry_bulb_temperature.values)
        schedule = (dbt < bal - off).astype(np.float64)
        w_sched = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"),
            simulated_weights=(schedule, np.zeros(8760)),
        )
        w_default = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"),
            balance_temperature=bal, balance_offset=off,
        )
        torch.testing.assert_close(w_sched, w_default, rtol=1e-3, atol=1e-2)

    def test_simulated_weights_harm_composite(self, example_epw_path):
        """With include_harm, the simulated-weights path must equal
        clip(benefit-scaled − harm-scaled, 0)."""
        import torch
        from urbansolarcarver.sky_patches import compute_EPW_based_weights

        hoys = list(range(24 * 150, 24 * 160))
        rng = np.random.default_rng(5)
        benefit = rng.uniform(0.2, 1.0, 8760)
        harm = rng.uniform(0.0, 0.9, 8760)
        w_ben_only = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"),
            simulated_weights=(benefit, np.zeros(8760)),
        )
        w_harm_only = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"),
            simulated_weights=(harm, np.zeros(8760)),
        )
        w_composite = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"),
            simulated_weights=(benefit, harm), include_harm=True,
        )
        expected = torch.clamp(w_ben_only - w_harm_only, min=0.0)
        torch.testing.assert_close(w_composite, expected, rtol=1e-3, atol=1e-2)

    def test_simulated_weights_zero_in_period_warns(self, example_epw_path):
        import torch
        from urbansolarcarver.sky_patches import compute_EPW_based_weights

        hoys = list(range(24 * 10, 24 * 20))
        schedule = np.zeros(8760)
        schedule[24 * 300:] = 1.0  # nonzero only outside the period
        with pytest.warns(UserWarning, match="zero everywhere"):
            w = compute_EPW_based_weights(
                "benefit", str(example_epw_path), hoys, torch.device("cpu"),
                simulated_weights=(schedule, np.zeros(8760)),
            )
        assert float(w.sum()) == 0.0

    def test_include_harm_noop_without_hot_hours(self, example_epw_path):
        """With a cold-only window the composite equals the default formula
        (and the empty hot-hour list must never reach Ladybug)."""
        import torch
        from urbansolarcarver.sky_patches import compute_EPW_based_weights

        hoys = list(range(24 * 5, 24 * 15))  # early January
        kw = dict(balance_temperature=15.0, balance_offset=2.0)
        w_default = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"), **kw)
        w_composite = compute_EPW_based_weights(
            "benefit", str(example_epw_path), hoys, torch.device("cpu"),
            include_harm=True, **kw)
        torch.testing.assert_close(w_composite, w_default)


# --- Light modules: mode facts and archetype defaults ---

import subprocess
import sys

LIGHT_MODULES = ("mode_registry", "archetype_defaults", "errors", "run_context")


@pytest.mark.parametrize("name", LIGHT_MODULES)
def test_light_module_imports_with_the_standard_library_alone(name):
    """Import the module with only the standard library on the path.

    The module's folder is exposed as a bare package (without the package
    ``__init__``, which imports numpy), so ``run_context`` can reach its
    sibling ``errors`` module.
    """
    folder = Path(__file__).parents[1] / "src" / "urbansolarcarver"
    code = ("import importlib, sys, types; "
            "sys.path = [p for p in sys.path if 'site-packages' not in p]; "
            f"pkg = types.ModuleType('bare'); pkg.__path__ = [r'{folder}']; "
            "sys.modules['bare'] = pkg; "
            f"importlib.import_module('bare.{name}')")
    subprocess.run([sys.executable, "-I", "-c", code], check=True)


@pytest.mark.parametrize("mode", ["benefit", "irradiance", "time-based",
                                  "tilted_plane", "radiative_cooling", "daylight"])
def test_example_configs_agree_with_the_starting_values(mode):
    from urbansolarcarver.mode_registry import MODES
    from urbansolarcarver.pydantic_schemas import expand_analysis_period
    path = Path(__file__).parents[1] / "configs" / f"config_{mode.replace('-', '_')}.yaml"
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    values = expand_analysis_period(yaml.safe_load(raw.decode("utf-8")))
    for key, value in MODES[mode].starting_values.items():
        assert values[key] == value


def test_mode_order_matches_the_grasshopper_menu():
    from urbansolarcarver.mode_registry import MODES
    assert list(MODES) == ["time-based", "irradiance", "benefit", "daylight",
                           "radiative_cooling", "tilted_plane"]


def test_every_mode_has_a_description_and_the_listed_starting_values():
    from urbansolarcarver.mode_registry import MODES
    assert all(spec.description for spec in MODES.values())
    assert MODES["time-based"].description.startswith("Classical solar envelope")
    assert MODES["daylight"].starting_values == {}
    assert MODES["tilted_plane"].starting_values == {"tilted_plane_angle_deg": 45.0}
    assert MODES["radiative_cooling"].starting_values == {"carve_fraction": 0.35}
    assert MODES["benefit"].starting_values == dict(
        start_month=10, start_day=15, start_hour=7, end_month=4, end_day=15, end_hour=19)


def test_canonical_mode_name_maps_the_alternative_spellings():
    from urbansolarcarver.mode_registry import MODE_ALIASES, canonical_mode_name
    assert canonical_mode_name("  TimeBased ") == "time-based"
    assert canonical_mode_name("time_based") == "time-based"
    assert canonical_mode_name("tilted-plane") == "tilted_plane"
    assert canonical_mode_name("radiativecooling") == "radiative_cooling"
    assert canonical_mode_name("Benefit") == "benefit"
    assert canonical_mode_name("nonsense") == "nonsense"
    assert set(MODE_ALIASES.values()) <= set(__import__(
        "urbansolarcarver.mode_registry", fromlist=["MODES"]).MODES)


def test_archetype_defaults_module_holds_the_shoebox_defaults():
    from urbansolarcarver.archetype_defaults import (
        ARCHETYPE_DEFAULTS, ARCHETYPE_OPTIONAL_KEYS, WINDOW_TO_WALL_DEFAULTS)
    assert "wwr" not in ARCHETYPE_DEFAULTS
    assert ARCHETYPE_DEFAULTS["internal_gains_w_m2"] == 5.0
    assert ARCHETYPE_DEFAULTS["mass_class"] == "medium"
    assert WINDOW_TO_WALL_DEFAULTS == {"south": 0.35, "east": 0.15, "west": 0.15, "north": 0.0}
    assert ARCHETYPE_OPTIONAL_KEYS == ("shading_permanent", "shading_hot", "hot_months")


def test_simulated_weights_read_the_archetype_defaults():
    from urbansolarcarver.archetype_defaults import ARCHETYPE_DEFAULTS
    from urbansolarcarver.simulated_weights import ZoneParams, expand_shoebox
    zone = ZoneParams.from_archetype(
        floor_area=100.0, volume=300.0, u_opaque=0.6, area_opaque=200.0,
        u_window=1.6, area_window=20.0, ach_vent=0.8, ach_infiltration=0.3)
    assert zone.t_set_heating == ARCHETYPE_DEFAULTS["t_set_heating"]
    assert zone.t_set_cooling == ARCHETYPE_DEFAULTS["t_set_cooling"]
    shoebox = expand_shoebox({"width": 10, "length": 10, "height": 3, "wwr": {"south": 0.3}})
    assert shoebox["windows"][0][2] == ARCHETYPE_DEFAULTS["g_value"]


def test_starting_values_cannot_be_changed_in_place():
    from urbansolarcarver.mode_registry import MODES
    for spec in MODES.values():
        with pytest.raises(TypeError):
            spec.starting_values["voxel_size"] = 99.0
