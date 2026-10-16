"""Unit tests for scoring: head-tail and carve-fraction thresholds."""
import numpy as np
import pytest
from urbansolarcarver.scoring import carve_fraction_threshold, headtail_threshold


# --- Carve-fraction threshold ---

def _reference_argsort_threshold(flat, fraction):
    """Reference O(N log N) implementation (sort, then cumulative sum), used
    as the test oracle for the histogram method.

    It accumulates in float64: a float32 running sum drifts on large arrays,
    while the histogram method is exact, so the oracle must be exact too.
    """
    if flat.size == 0 or float(flat.max()) == 0.0:
        return 0.0
    order = np.argsort(flat)[::-1]
    csum = np.cumsum(flat[order], dtype=np.float64)
    lim = float(fraction) * float(csum[-1])
    idx = int(np.searchsorted(csum, lim, side="right"))
    return float(flat[order[idx]] if idx < len(flat) else flat.min())


class TestCarveFractionThreshold:
    @pytest.mark.parametrize("fraction", [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99])
    @pytest.mark.parametrize("dist", ["uniform", "heavy_tail", "sparse"])
    def test_matches_argsort_reference(self, dist, fraction):
        """The histogram method must reproduce the argsort cutoff (same
        carved mass within one score value)."""
        rng = np.random.default_rng(7)
        if dist == "uniform":
            flat = rng.uniform(0, 100, 200_000).astype(np.float32)
        elif dist == "heavy_tail":
            flat = (np.abs(rng.normal(size=200_000)) ** 3).astype(np.float32)
        else:  # sparse: mostly zeros, like a real score volume
            flat = np.zeros(200_000, dtype=np.float32)
            flat[rng.choice(200_000, 5_000, replace=False)] = rng.uniform(
                1, 500, 5_000
            ).astype(np.float32)

        thr = carve_fraction_threshold(flat, fraction)
        ref = _reference_argsort_threshold(flat, fraction)
        # Carved mass must match the reference to within float tolerance.
        mass = float(flat[flat > thr].sum(dtype=np.float64))
        ref_mass = float(flat[flat > ref].sum(dtype=np.float64))
        total = float(flat.sum(dtype=np.float64))
        assert abs(mass - ref_mass) <= 1e-4 * max(total, 1.0), (
            f"dist={dist} f={fraction}: thr={thr} vs ref={ref}"
        )

    def test_empty_and_zero(self):
        assert carve_fraction_threshold(np.array([], dtype=np.float32), 0.5) == 0.0
        assert carve_fraction_threshold(np.zeros(100, dtype=np.float32), 0.5) == 0.0

    def test_fraction_zero_carves_nothing(self):
        flat = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        thr = carve_fraction_threshold(flat, 0.0)
        assert not (flat > thr).any()

    def test_all_equal_scores(self):
        """With a single distinct value, carving is all-or-nothing; both
        implementations resolve the threshold to that value, carving
        nothing (mask semantics are strictly-above)."""
        flat = np.full(1000, 5.0, dtype=np.float32)
        thr = carve_fraction_threshold(flat, 0.5)
        assert thr == _reference_argsort_threshold(flat, 0.5) == 5.0
        assert not (flat > thr).any()

    def test_nan_scores_do_not_crash(self):
        """Non-finite scores must not crash (np.histogram raises on a NaN
        range); they are always carved downstream, so the cutoff is the
        one computed over the finite subset."""
        rng = np.random.default_rng(3)
        flat = rng.uniform(0, 100, 10_000).astype(np.float32)
        flat[::97] = np.nan
        thr = carve_fraction_threshold(flat, 0.5)
        assert np.isfinite(thr)
        assert thr == carve_fraction_threshold(flat[np.isfinite(flat)], 0.5)

    def test_inf_scores_do_not_crash(self):
        rng = np.random.default_rng(4)
        flat = rng.uniform(0, 100, 10_000).astype(np.float32)
        flat[::53] = np.inf
        thr = carve_fraction_threshold(flat, 0.5)
        assert np.isfinite(thr)
        assert thr == carve_fraction_threshold(flat[np.isfinite(flat)], 0.5)

    def test_all_nonfinite_returns_zero(self):
        assert carve_fraction_threshold(np.full(100, np.nan, dtype=np.float32), 0.5) == 0.0


# --- Radiative cooling protection cone (min_sky_elevation_deg) ---

class TestRadiativeCoolingCone:
    def _weights(self, cutoff):
        import torch
        from urbansolarcarver.sky_patches import compute_radiative_cooling_weights
        return compute_radiative_cooling_weights(
            14.0, 1.8, torch.device("cpu"), min_elevation_deg=cutoff
        )

    def _elevations(self):
        import torch
        from urbansolarcarver.sky_patches import fetch_tregenza_patch_directions
        dirs = fetch_tregenza_patch_directions(torch.device("cpu"))
        return np.degrees(np.arcsin(np.clip(dirs[:, 2].numpy(), -1, 1)))

    def test_zero_cutoff_is_pure_model(self):
        w = self._weights(0.0)
        assert abs(float(w.sum()) - 1.0) < 1e-5
        assert (w.numpy() > 0).all(), "full hemisphere: every patch contributes"

    def test_cutoff_zeroes_low_patches_and_renormalizes(self):
        w = self._weights(30.0).numpy()
        elev = self._elevations()
        assert (w[elev < 30.0] == 0.0).all()
        assert (w[elev >= 30.0] > 0.0).all()
        assert abs(w.sum() - 1.0) < 1e-5
        # Renormalization: surviving patches gain weight vs the full model.
        w0 = self._weights(0.0).numpy()
        zenith = int(np.argmax(elev))
        assert w[zenith] > w0[zenith]

    def test_high_cutoff_keeps_zenith(self):
        w = self._weights(85.0).numpy()
        elev = self._elevations()
        assert (w[elev < 85.0] == 0.0).all()
        assert abs(w.sum() - 1.0) < 1e-5

    def test_cutoff_excluding_everything_raises(self):
        with pytest.raises(ValueError, match="excludes every"):
            self._weights(95.0)


# --- Head-tail threshold ---

def test_headtail_empty():
    result = headtail_threshold(np.array([]))
    assert result == 0.0


def test_headtail_uniform():
    """Uniform distribution should converge to a reasonable value."""
    scores = np.arange(100, dtype=float)
    thr = headtail_threshold(scores, max_iterations=20)
    assert 0 < thr < 100


def test_headtail_single():
    result = headtail_threshold(np.array([7.0]))
    assert result == pytest.approx(7.0)


def test_headtail_heavy_tail():
    """Heavy-tailed distribution: threshold should be above the median."""
    rng = np.random.default_rng(42)
    bulk = rng.uniform(0, 10, 900)
    tail = rng.uniform(50, 100, 100)
    scores = np.concatenate([bulk, tail])
    thr = headtail_threshold(scores)
    assert thr > np.median(scores), "Head-tail should split above median for heavy-tailed data"


def test_headtail_returns_deepest_minority_break():
    """Jiang (2013): keep splitting while the head is a minority."""
    scores = np.array([1.0] * 80 + [10.0] * 16 + [100.0] * 4)
    assert headtail_threshold(scores) == pytest.approx(28.0)  # breaks 6.4, 28


def test_headtail_no_heavy_tail_returns_mean():
    """A majority head at the first split means no tail to isolate."""
    scores = np.arange(100, dtype=float)
    assert headtail_threshold(scores) == pytest.approx(49.5)


def test_headtail_all_equal():
    """All-equal scores should return that value (no head to split)."""
    scores = np.full(200, 5.0)
    result = headtail_threshold(scores)
    assert result == pytest.approx(5.0)


# --- Sky weights cached in the session ---

class TestSkyWeightsCachedInTheSession:
    """get_weights runs the sky matrix once per distinct request within a
    CarverSession; a changed EPW file or setting computes new weights."""

    HOURS_OF_ONE_SUMMER_DAY = list(range(4344, 4368))  # keeps the sky matrix small

    @staticmethod
    def _count_sky_matrix_runs(monkeypatch):
        from urbansolarcarver import scoring
        runs = []
        compute = scoring.compute_EPW_based_weights

        def counting(*args, **kwargs):
            runs.append(1)
            return compute(*args, **kwargs)

        monkeypatch.setattr(scoring, "compute_EPW_based_weights", counting)
        return runs

    def _weights(self, epw, **settings):
        from urbansolarcarver.scoring import get_weights
        return get_weights("irradiance", device="cpu", epw_file=str(epw),
                           hoys=self.HOURS_OF_ONE_SUMMER_DAY, **settings)

    def test_the_same_request_reuses_the_weights(self, monkeypatch, example_epw_path):
        from urbansolarcarver.session import CarverSession
        runs = self._count_sky_matrix_runs(monkeypatch)
        with CarverSession("cpu"):
            first = self._weights(example_epw_path)
            second = self._weights(example_epw_path)
        assert len(runs) == 1
        assert second is first

    def test_a_changed_epw_at_the_same_path_is_read_again(self, tmp_path, monkeypatch, example_epw_path):
        import shutil
        from urbansolarcarver.session import CarverSession
        epw = tmp_path / "weather.epw"
        shutil.copy(example_epw_path, epw)
        runs = self._count_sky_matrix_runs(monkeypatch)
        with CarverSession("cpu"):
            self._weights(epw)
            lines = epw.read_text(encoding="utf-8", errors="replace").splitlines(True)
            lines[0] = lines[0].replace(lines[0].split(",")[1], "Renamed City", 1)
            epw.write_text("".join(lines), encoding="utf-8")
            self._weights(epw)
        assert len(runs) == 2

    def test_a_changed_setting_computes_new_weights(self, monkeypatch, example_epw_path):
        from urbansolarcarver.session import CarverSession
        runs = self._count_sky_matrix_runs(monkeypatch)
        with CarverSession("cpu"):
            self._weights(example_epw_path, north_deg=0.0)
            self._weights(example_epw_path, north_deg=30.0)
        assert len(runs) == 2

    def test_without_a_session_nothing_is_kept(self, monkeypatch, example_epw_path):
        runs = self._count_sky_matrix_runs(monkeypatch)
        self._weights(example_epw_path)
        self._weights(example_epw_path)
        assert len(runs) == 2
