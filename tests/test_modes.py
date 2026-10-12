"""Smoke tests: every carving mode runs without crashing on a tiny mesh."""
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
    """Run full pipeline for a mode and return export result."""
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
    assert result.export_path.exists()
    import trimesh
    mesh = trimesh.load(str(result.export_path))
    assert len(mesh.vertices) > 0


# --- EPW-dependent modes ---

# Weighted modes use the relative carve_fraction threshold: a raw numeric
# cutoff like 0.5 is meaningless against cumulative Wh/m² scores (it would
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
    assert result.export_path.exists()
    import trimesh
    mesh = trimesh.load(str(result.export_path))
    assert len(mesh.vertices) > 0


# --- Benefit weight semantics (documented Heaviside formula) ---

class TestBenefitWeights:
    def test_benefit_equals_irradiance_over_cold_hours(self, example_epw_path):
        """The benefit weights must equal a plain irradiance matrix computed
        over exactly the hours below balance_temperature - balance_offset —
        the documented formula, with no hidden harm subtraction."""
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
        """An analysis period with no beneficial hours must warn loudly and
        return all-zero weights — NOT fall through to Ladybug, which treats
        an empty hoy list as the whole year."""
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
        weights over the same hours — the artifact path is a pure hourly
        re-weighting of the same sky integration."""
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
        default benefit weights — the Heaviside is the binary special case."""
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
        """With include_harm, the artifact path must equal
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
