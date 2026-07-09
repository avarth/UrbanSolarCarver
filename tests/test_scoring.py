"""Unit tests for scoring: head-tail and carve-fraction thresholds."""
import numpy as np
import pytest
from urbansolarcarver.scoring import carve_fraction_threshold, headtail_threshold


# --- Carve-fraction threshold ---

def _reference_argsort_threshold(flat, fraction):
    """The original O(N log N) implementation, kept as the test oracle.

    Accumulates in float64 (the original accumulated the sorted float32
    values directly, which drifts on large arrays — the histogram method
    is exact, so the oracle must be too).
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
        implementations resolve the threshold TO that value, carving
        nothing (mask semantics are strictly-above)."""
        flat = np.full(1000, 5.0, dtype=np.float32)
        thr = carve_fraction_threshold(flat, 0.5)
        assert thr == _reference_argsort_threshold(flat, 0.5) == 5.0
        assert not (flat > thr).any()


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


def test_headtail_all_equal():
    """All-equal scores should return that value (no head to split)."""
    scores = np.full(200, 5.0)
    result = headtail_threshold(scores)
    assert result == pytest.approx(5.0)
