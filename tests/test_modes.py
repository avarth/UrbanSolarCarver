"""What the tilted_plane, time-based, irradiance and daylight modes carve on a plot across the street from a
neighbour's facade (tests/_plot_scene.py), a site turned by north_deg, and checks of the benefit-mode weight formula.
Benefit's carving is checked by test_pipeline.py::test_full_pipeline_benefit."""
import math

import numpy as np
import pytest
import yaml
from pathlib import Path

from _plot_scene import FACADE_NORTHING, assert_carves_the_north_side, plot_scene

# Weighted modes use the relative carve_fraction threshold: a raw numeric cutoff like 0.5 is meaningless against
# cumulative kWh/m² scores (it would carve every voxel any ray touched).
CARVE_FRACTION = {"threshold": "carve_fraction", "carve_fraction": 0.7}

# Ladybug's SkyMatrix takes north as metadata only: it does not pass it to gendaymtx, so the patch values of the
# irradiance and benefit weights do not turn with north_deg (sky_patches.compute_EPW_based_weights). A turned site
# then gets the sun from the model's -Y whichever way north points.
NORTH_IGNORED_BY_THE_SKY_MATRIX = ("Bug: compute_EPW_based_weights passes north to Ladybug's SkyMatrix, which only "
                                   "records it; the weights of every north_deg are those of north_deg 0")


def _carve(folder, mode, epw_path=None, north_deg=0.0, **values):
    """Run *mode* to exporting on the plot scene written into *folder*; return the scene's voxels of the run."""
    from urbansolarcarver import run_pipeline
    scene = plot_scene(folder, north_deg=north_deg)
    config = scene.config(folder / "run", mode, epw_path, **values)
    result = run_pipeline(config, folder / "run")
    return scene.voxels(result.thresholding.out_dir)


def test_tilted_plane_removes_what_rises_above_the_plane_from_the_facades_foot(tmp_path):
    # 30 degrees, not the starting 45, at which an angle measured from the vertical would give the same plane.
    angle = 30.0
    voxels = _carve(tmp_path, "tilted_plane", tilted_plane_angle_deg=angle, threshold=None)
    assert_carves_the_north_side(voxels)
    # The plane rises from the facade's foot (its lowest sample points) across the street and over the plot. The
    # ray crosses a voxel column at heights between the plane's values at the column's two edges, and every voxel
    # at or above a cell it crosses goes: no voxel whose top lies below the plane goes, and none whose bottom lies
    # above it stays.
    rise = math.tan(math.radians(angle))
    plane_low = (FACADE_NORTHING - (voxels.northing + 0.5)) * rise
    plane_high = (FACADE_NORTHING - (voxels.northing - 0.5)) * rise
    assert not (voxels.removed & (voxels.height + 0.5 < plane_low)).any()
    assert not (voxels.kept & (voxels.height - 0.5 > plane_high)).any()


# The removed voxels measured 2026-11-02 on the scene's settings, on the CPU. After a deliberate change of the scene
# or of the scoring, take the new value from the run's thresholding diagnostics (voxels_original - voxels_kept).
@pytest.mark.parametrize("mode,extra,removed", [
    ("time-based", {}, 2077),
    ("irradiance", CARVE_FRACTION, 1272),
    ("daylight", CARVE_FRACTION, 1297),
])
def test_each_sun_and_sky_mode_carves_the_plots_side_toward_the_neighbour(tmp_path, request, mode, extra, removed):
    epw_path = None if mode == "daylight" else request.getfixturevalue("example_epw_path")
    voxels = _carve(tmp_path, mode, epw_path, **extra)
    assert_carves_the_north_side(voxels)
    # Within 2 %: irradiance with its weights taken from the opposite sky (each patch given the value of the one
    # 180 degrees round) removes 1532 voxels, still on the north side.
    assert int(voxels.removed.sum()) == pytest.approx(removed, rel=0.02)


@pytest.mark.parametrize("mode,extra", [
    ("time-based", {}),
    pytest.param("irradiance", CARVE_FRACTION,
                 marks=pytest.mark.xfail(strict=True, reason=NORTH_IGNORED_BY_THE_SKY_MATRIX)),
    pytest.param("benefit", CARVE_FRACTION,
                 marks=pytest.mark.xfail(strict=True, reason=NORTH_IGNORED_BY_THE_SKY_MATRIX)),
])
def test_a_site_turned_by_north_deg_is_carved_as_the_same_site_unturned(tmp_path, example_epw_path, mode, extra):
    # Daylight is left out: the overcast sky is the same in every direction.
    unturned = _carve(tmp_path / "unturned", mode, example_epw_path, **extra)
    turned = _carve(tmp_path / "turned", mode, example_epw_path, north_deg=90.0, **extra)
    # A quarter turn maps the 1 m voxel grid onto itself, so in the site's frame the same voxels go. (The
    # irradiance weights, which stay unturned, remove 1463 voxels on the turned site against 1272 on the plain one.)
    def removed(voxels):
        return {tuple(np.round(row, 3)) for row in voxels.site[voxels.removed]}
    assert removed(turned) == removed(unturned)
    assert_carves_the_north_side(turned)


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

    @pytest.mark.slow
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
    assert all(spec.description for spec in MODES.values())


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
