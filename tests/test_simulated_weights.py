"""Tests for the simulated-weights generator (ISO 13790 5R1C).

The oracle regression replays the exact driving arrays stored in
tests/data/oracle_5r1c_reference.json (captured from ETH's
RC_BuildingSimulator under the bundled Golden TMY3 EPW) and feeds the
oracle's own derived conductances, so the Annex C recurrence is compared
implementation-to-implementation with no parameter-derivation noise.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from urbansolarcarver.simulated_weights import (
    HOURS,
    MASS_CLASSES,
    ZoneParams,
    read_simulated_weights,
    simulate,
    attribute_solar_gains,
    write_simulated_weights,
)

_REF_PATH = Path(__file__).parent / "data" / "oracle_5r1c_reference.json"
_REF = json.loads(_REF_PATH.read_text(encoding="utf-8"))


def _params_from_reference(name: str) -> ZoneParams:
    """Zone from the oracle's derived conductances (its h_tr_em convention)."""
    d = _REF["scenarios"][name]["derived"]
    return ZoneParams(
        floor_area=d["floor_area"],
        h_tr_em=d["h_tr_em"],
        h_tr_w=d["h_tr_w"],
        h_tr_is=d["h_tr_is"],
        h_tr_ms=d["h_tr_ms"],
        h_ve=d["h_ve_adj"],
        c_m=d["c_m"],
        a_m=d["mass_area"],
        a_t=d["a_t"],
        t_set_heating=d["t_set_heating"],
        t_set_cooling=d["t_set_cooling"],
    )


def _driving(name: str):
    t_out = np.asarray(_REF["driving"]["t_out"], dtype=np.float64)
    phi_int = np.asarray(_REF["driving"]["internal_gains"], dtype=np.float64)
    phi_sol = np.asarray(_REF["driving"][f"solar_{name}"], dtype=np.float64)
    return t_out, phi_int, phi_sol


# ---------------------------------------------------------------------------
# Oracle regression
# ---------------------------------------------------------------------------

class TestOracleRegression:
    @pytest.mark.parametrize("name", sorted(_REF["scenarios"]))
    def test_annual_demands_match(self, name):
        params = _params_from_reference(name)
        result = simulate(params, *_driving(name))
        annual = _REF["scenarios"][name]["annual"]
        assert result.q_heating_wh == pytest.approx(annual["Q_H_Wh"],
                                                    rel=1e-6, abs=1.0)
        assert result.q_cooling_wh == pytest.approx(annual["Q_C_Wh"],
                                                    rel=1e-6, abs=1.0)
        assert result.t_air.mean() == pytest.approx(annual["t_air_mean"],
                                                    abs=1e-4)

    @pytest.mark.parametrize("name", sorted(_REF["scenarios"]))
    def test_sampled_hours_match(self, name):
        params = _params_from_reference(name)
        result = simulate(params, *_driving(name))
        for hour_str, ref in _REF["scenarios"][name]["hourly_samples"].items():
            h = int(hour_str)
            demand = result.demand_w[h]
            assert result.t_air[h] == pytest.approx(ref["t_air"], abs=1e-4)
            assert result.t_m[h] == pytest.approx(ref["t_m_next"], abs=1e-4)
            assert max(demand, 0.0) == pytest.approx(
                ref["heating_demand"], rel=1e-6, abs=1e-3)
            assert min(demand, 0.0) == pytest.approx(
                ref["cooling_demand"], rel=1e-6, abs=1e-3)


# ---------------------------------------------------------------------------
# Physics invariants
# ---------------------------------------------------------------------------

class TestPhysicsInvariants:
    def _steady_conductance(self, p: ZoneParams) -> float:
        """Independent network reduction: air-to-outdoor conductance."""
        def serial(a, b):
            return 1.0 / (1.0 / a + 1.0 / b)
        g_mass_chain = serial(p.h_tr_ms, p.h_tr_em)   # surface → mass → out
        g_surface_out = p.h_tr_w + g_mass_chain        # surface → out
        return p.h_ve + serial(p.h_tr_is, g_surface_out)

    def test_steady_state_closure(self):
        """Constant 0 °C outdoors, no gains: demand converges to G·ΔT and
        the air node is held exactly at the heating set-point."""
        p = _params_from_reference("medium_office")
        zeros = np.zeros(HOURS)
        result = simulate(p, zeros, zeros, zeros)
        expected = self._steady_conductance(p) * (p.t_set_heating - 0.0)
        assert result.demand_w[-1] == pytest.approx(expected, rel=1e-6)
        assert result.t_air[-1] == pytest.approx(p.t_set_heating, abs=1e-9)

    def test_heavier_mass_flattens_temperature(self):
        """With identical driving, the heavy zone's mass temperature must
        vary less hour-to-hour than the light zone's."""
        t_out, phi_int, phi_sol = _driving("medium_office")
        base = _params_from_reference("medium_office")
        import dataclasses
        light = dataclasses.replace(base, c_m=base.c_m / 4)
        heavy = dataclasses.replace(base, c_m=base.c_m * 4)
        var_light = np.diff(simulate(light, t_out, phi_int, phi_sol).t_m).std()
        var_heavy = np.diff(simulate(heavy, t_out, phi_int, phi_sol).t_m).std()
        assert var_heavy < var_light

    def test_input_shape_validation(self):
        p = _params_from_reference("medium_office")
        with pytest.raises(ValueError, match="t_out"):
            simulate(p, np.zeros(100), np.zeros(HOURS), np.zeros(HOURS))


# ---------------------------------------------------------------------------
# Archetype constructor
# ---------------------------------------------------------------------------

class TestFromArchetype:
    _BASE = dict(floor_area=40.0, volume=120.0, u_opaque=0.6,
                 area_opaque=90.0, u_window=1.4, area_window=8.0,
                 ach_vent=1.0, ach_infiltration=0.4)

    def test_serial_opaque_split(self):
        """H_tr,em must satisfy the §12.2.2 relation 1/H_em = 1/H_op − 1/H_ms."""
        p = ZoneParams.from_archetype(**self._BASE, mass_class="medium")
        h_op = self._BASE["u_opaque"] * self._BASE["area_opaque"]
        assert 1.0 / p.h_tr_em == pytest.approx(1.0 / h_op - 1.0 / p.h_tr_ms)

    def test_mass_classes(self):
        for cls_name, (am_f, cm_m2) in MASS_CLASSES.items():
            p = ZoneParams.from_archetype(**self._BASE, mass_class=cls_name)
            assert p.a_m == pytest.approx(am_f * self._BASE["floor_area"])
            assert p.c_m == pytest.approx(cm_m2 * self._BASE["floor_area"])

    def test_heat_recovery_reduces_ventilation(self):
        p0 = ZoneParams.from_archetype(**self._BASE, heat_recovery=0.0)
        p1 = ZoneParams.from_archetype(**self._BASE, heat_recovery=0.8)
        assert p1.h_ve < p0.h_ve
        # Infiltration share is never recovered.
        ach_tot = self._BASE["ach_vent"] + self._BASE["ach_infiltration"]
        b_ek = 1.0 - (self._BASE["ach_vent"] / ach_tot) * 0.8
        assert p1.h_ve == pytest.approx(p0.h_ve * b_ek)

    def test_invalid_inputs_raise(self):
        with pytest.raises(ValueError, match="mass_class"):
            ZoneParams.from_archetype(**self._BASE, mass_class="granite")
        too_conductive = dict(self._BASE, u_opaque=50.0)
        with pytest.raises(ValueError, match="serial split"):
            ZoneParams.from_archetype(**too_conductive, mass_class="light")


# ---------------------------------------------------------------------------
# Perturbation attribution
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def weight_series():
    """One full attribution run (17 521 trajectories), shared by tests."""
    name = "medium_office"
    params = _params_from_reference(name)
    return attribute_solar_gains(params, *_driving(name))


class TestAttribution:
    def test_bounds_and_shape(self, weight_series):
        benefit, harm = weight_series
        assert benefit.shape == harm.shape == (HOURS,)
        assert benefit.min() >= 0.0 and benefit.max() <= 1.0
        assert harm.min() >= 0.0 and harm.max() <= 1.0

    def test_seasonal_structure(self, weight_series):
        """Winter gains must be mostly beneficial, summer gains mostly
        harmful — under Golden CO weather and the office archetype."""
        benefit, harm = weight_series
        jan = slice(0, 31 * 24)
        jul = slice(181 * 24, 212 * 24)
        assert benefit[jan].mean() > 0.5
        assert benefit[jan].mean() > benefit[jul].mean()
        assert harm[jul].mean() > harm[jan].mean()
        assert harm[jan].mean() < 0.2

    def test_lag_is_captured(self, weight_series):
        """Credit must extend beyond the hour of arrival: midday winter
        gains (arriving when the zone may be gain-rich) still show high
        benefit because the mass releases them into the cold night."""
        benefit, _harm = weight_series
        jan_noon = benefit[12:31 * 24:24]
        assert jan_noon.mean() > 0.5


# ---------------------------------------------------------------------------
# End-to-end generator (EPW + archetype YAML → artifact)
# ---------------------------------------------------------------------------

class TestGenerateSimulatedWeights:
    def test_example_archetype_end_to_end(self, tmp_path):
        import yaml
        from _epw import resolve_epw
        from urbansolarcarver.simulated_weights import generate_simulated_weights

        epw = resolve_epw()
        if not epw:
            pytest.skip("No EPW available")
        arch_path = (Path(__file__).parent.parent / "configs"
                     / "archetype_example.yaml")
        arch = yaml.safe_load(arch_path.read_text(encoding="utf-8"))
        internal = arch.pop("internal_gains_w_m2")

        out = generate_simulated_weights(epw, arch, tmp_path / "u.json",
                              internal_gains_w_m2=internal)
        benefit, harm, meta = read_simulated_weights(out)
        assert meta["method"] == "iso13790-5r1c-perturbation"
        assert meta["archetype"]["mass_class"] == "medium"
        jan = slice(0, 31 * 24)
        jul = slice(181 * 24, 212 * 24)
        assert benefit[jan].mean() > benefit[jul].mean()
        assert harm[jul].mean() > harm[jan].mean()

    def test_missing_windows_raises(self, tmp_path):
        from urbansolarcarver.simulated_weights import generate_simulated_weights
        with pytest.raises(ValueError, match="windows"):
            generate_simulated_weights("dummy.epw", {"floor_area": 10.0},
                            tmp_path / "u.json")

    def test_daily_occupancy_profile(self, tmp_path):
        """A 24-value profile is tiled over the year and recorded in meta;
        wrong lengths are rejected."""
        import yaml
        from _epw import resolve_epw
        from urbansolarcarver.simulated_weights import generate_simulated_weights

        epw = resolve_epw()
        if not epw:
            pytest.skip("No EPW available")
        arch_path = (Path(__file__).parent.parent / "configs"
                     / "archetype_example.yaml")
        arch = yaml.safe_load(arch_path.read_text(encoding="utf-8"))
        arch.pop("internal_gains_w_m2")
        profile = [2.0] * 8 + [10.0] * 12 + [2.0] * 4  # office-like day
        out = generate_simulated_weights(epw, arch, tmp_path / "u.json",
                              internal_gains_w_m2=profile)
        _b, _h, meta = read_simulated_weights(out)
        assert meta["archetype"]["internal_gains_w_m2"] == profile

        with pytest.raises(ValueError, match="24-value"):
            generate_simulated_weights(epw, arch, tmp_path / "u2.json",
                            internal_gains_w_m2=[1.0, 2.0, 3.0])


# ---------------------------------------------------------------------------
# Artifact I/O
# ---------------------------------------------------------------------------

class TestArtifactIO:
    def test_roundtrip(self, tmp_path):
        benefit = np.linspace(0, 1, HOURS)
        harm = np.linspace(1, 0, HOURS)
        meta = {"method": "test", "epw": "x.epw"}
        path = write_simulated_weights(tmp_path / "u.json", benefit, harm, meta)
        b2, h2, m2 = read_simulated_weights(path)
        np.testing.assert_allclose(b2, benefit, atol=1e-6)
        np.testing.assert_allclose(h2, harm, atol=1e-6)
        assert m2["method"] == "test"

    def test_validation_rejects_bad_series(self, tmp_path):
        good = np.zeros(HOURS)
        with pytest.raises(ValueError, match="8760"):
            write_simulated_weights(tmp_path / "u.json", np.zeros(10), good, {})
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            write_simulated_weights(tmp_path / "u.json", good - 0.5, good, {})

    def test_read_rejects_wrong_schema(self, tmp_path):
        p = tmp_path / "u.json"
        p.write_text(json.dumps({"schema_version": 99, "hourly": {}}),
                     encoding="utf-8")
        with pytest.raises(ValueError, match="schema_version"):
            read_simulated_weights(p)


# ---------------------------------------------------------------------------
# Shoebox geometry shorthand
# ---------------------------------------------------------------------------

class TestExpandShoebox:
    BASE = {
        "width": 10.0, "length": 8.0, "height": 3.0,
        "wwr": {"south": 0.4, "east": 0.2},
        "u_opaque": 0.6, "u_window": 1.6,
        "ach_vent": 0.8, "ach_infiltration": 0.3, "heat_recovery": 0.0,
        "mass_class": "medium", "t_set_heating": 20.0, "t_set_cooling": 26.0,
    }

    def test_derived_areas(self):
        from urbansolarcarver.simulated_weights import expand_shoebox
        arch = expand_shoebox(self.BASE)
        assert arch["floor_area"] == pytest.approx(80.0)
        assert arch["volume"] == pytest.approx(240.0)
        # south facade 10x3=30 at wwr 0.4 -> 12; east 8x3=24 at 0.2 -> 4.8
        assert arch["area_window"] == pytest.approx(16.8)
        # gross walls 2*(30+24)=108, minus glazing, plus roof 80
        assert arch["area_opaque"] == pytest.approx(108 - 16.8 + 80)
        windows = {az: (area, g) for az, area, g in arch["windows"]}
        assert windows[180.0][0] == pytest.approx(12.0)
        assert windows[90.0][0] == pytest.approx(4.8)
        assert all(g == pytest.approx(0.6) for _, g in windows.values())
        # geometry keys consumed
        assert "width" not in arch and "wwr" not in arch

    def test_orientation_rotates_azimuths(self):
        from urbansolarcarver.simulated_weights import expand_shoebox
        arch = expand_shoebox({**self.BASE, "orientation": 30.0})
        azimuths = sorted(az for az, _, _ in arch["windows"])
        assert azimuths == [pytest.approx(120.0), pytest.approx(210.0)]

    def test_passthrough_without_shoebox_keys(self):
        from urbansolarcarver.simulated_weights import expand_shoebox
        explicit = {"floor_area": 100.0, "windows": [[180, 10, 0.6]]}
        assert expand_shoebox(explicit) == explicit

    def test_rejects_mixed_forms(self):
        from urbansolarcarver.simulated_weights import expand_shoebox
        with pytest.raises(ValueError, match="not both"):
            expand_shoebox({**self.BASE, "floor_area": 100.0})

    def test_rejects_incomplete_geometry(self):
        from urbansolarcarver.simulated_weights import expand_shoebox
        bad = {k: v for k, v in self.BASE.items() if k != "height"}
        with pytest.raises(ValueError, match="height"):
            expand_shoebox(bad)

    def test_rejects_bad_wwr(self):
        from urbansolarcarver.simulated_weights import expand_shoebox
        with pytest.raises(ValueError, match="wwr keys"):
            expand_shoebox({**self.BASE, "wwr": {"southeast": 0.3}})
        with pytest.raises(ValueError, match=r"\[0, 1\)"):
            expand_shoebox({**self.BASE, "wwr": {"south": 1.0}})
        with pytest.raises(ValueError, match="no windows"):
            expand_shoebox({**self.BASE, "wwr": {}})


class TestGainsFromArchetype:
    """generate_simulated_weights reads internal gains from the archetype."""

    def _epw(self):
        from tests._epw import resolve_epw
        return resolve_epw() or None

    def test_gains_key_inside_archetype(self, tmp_path):
        epw = self._epw()
        if epw is None:
            pytest.skip("no EPW available")
        from urbansolarcarver.simulated_weights import (
            generate_simulated_weights, read_simulated_weights,
        )
        arch = dict(TestExpandShoebox.BASE)
        arch["internal_gains_w_m2"] = 7.5
        out = generate_simulated_weights(epw, arch, tmp_path / "w.json")
        _b, _h, meta = read_simulated_weights(out)
        assert meta["archetype"]["internal_gains_w_m2"] == pytest.approx(7.5)

    def test_both_gains_keys_raise(self, tmp_path):
        epw = self._epw()
        if epw is None:
            pytest.skip("no EPW available")
        from urbansolarcarver.simulated_weights import generate_simulated_weights
        arch = dict(TestExpandShoebox.BASE)
        arch["internal_gains_w_m2"] = 5.0
        arch["internal_gains_profile_w_m2"] = [5.0] * 24
        with pytest.raises(ValueError, match="not both"):
            generate_simulated_weights(epw, arch, tmp_path / "w.json")


class TestShadingCoefficients:
    """Declared shading multipliers: permanent + hot-period, scalar or per-facade."""

    def test_normalize_scalar_and_mapping(self):
        from urbansolarcarver.simulated_weights import _normalize_shading
        assert _normalize_shading(0.8, "x") == {
            "north": 0.8, "east": 0.8, "south": 0.8, "west": 0.8}
        out = _normalize_shading({"south": 0.5}, "x")
        assert out["south"] == 0.5 and out["north"] == 1.0

    def test_normalize_rejects_bad_values(self):
        from urbansolarcarver.simulated_weights import _normalize_shading
        with pytest.raises(ValueError, match="facade keys"):
            _normalize_shading({"southeast": 0.5}, "x")
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            _normalize_shading(1.5, "x")

    def test_hot_months_mask(self):
        from urbansolarcarver.simulated_weights import _hot_months_mask
        mask = _hot_months_mask([6, 7, 8, 9])
        assert mask.sum() == (30 + 31 + 31 + 30) * 24
        assert not mask[0]                      # Jan 1
        assert mask[(31+28+31+30+31) * 24]      # Jun 1, hour 0
        with pytest.raises(ValueError, match="1-12"):
            _hot_months_mask([0, 13])

    def test_nearest_cardinal_binning(self):
        from urbansolarcarver.simulated_weights import _nearest_cardinal
        assert _nearest_cardinal(350) == "north"
        assert _nearest_cardinal(44) == "north"
        assert _nearest_cardinal(46) == "east"
        assert _nearest_cardinal(180) == "south"
        assert _nearest_cardinal(225) == "west"

    def test_hot_requires_months_and_vice_versa(self):
        from urbansolarcarver.simulated_weights import _shading_factors
        windows = [[180.0, 10.0, 0.6]]
        with pytest.raises(ValueError, match="requires hot_months"):
            _shading_factors(windows, None, 0.5, None)
        with pytest.raises(ValueError, match="no effect"):
            _shading_factors(windows, None, None, [7])

    def test_hot_only_leaves_cold_season_untouched(self, tmp_path):
        from tests._epw import resolve_epw
        epw = resolve_epw()
        if not epw:
            pytest.skip("no EPW available")
        from urbansolarcarver.simulated_weights import (
            generate_simulated_weights, read_simulated_weights,
        )
        arch = dict(TestExpandShoebox.BASE)
        plain = read_simulated_weights(
            generate_simulated_weights(epw, dict(arch), tmp_path / "p.json"))
        arch.update(shading_hot=0.3, hot_months=[7, 8])
        shaded = read_simulated_weights(
            generate_simulated_weights(epw, arch, tmp_path / "s.json"))
        b_plain, h_plain = plain[0].reshape(365, 24), plain[1].reshape(365, 24)
        b_shad, h_shad = shaded[0].reshape(365, 24), shaded[1].reshape(365, 24)
        # January identical (no permanent factor, hot shading inactive)
        np.testing.assert_allclose(b_shad[:31], b_plain[:31], atol=1e-6)
        # July harm strictly reduced
        assert h_shad[181:212].mean() < 0.6 * h_plain[181:212].mean()
        # provenance recorded
        assert shaded[2]["archetype"]["hot_months"] == [7, 8]

    def test_scalar_equals_uniform_mapping(self, tmp_path):
        from tests._epw import resolve_epw
        epw = resolve_epw()
        if not epw:
            pytest.skip("no EPW available")
        from urbansolarcarver.simulated_weights import (
            generate_simulated_weights, read_simulated_weights,
        )
        arch = dict(TestExpandShoebox.BASE)
        arch["shading_permanent"] = 0.8
        a = read_simulated_weights(generate_simulated_weights(
            epw, dict(arch), tmp_path / "a.json"))
        arch["shading_permanent"] = {
            "north": 0.8, "east": 0.8, "south": 0.8, "west": 0.8}
        b = read_simulated_weights(generate_simulated_weights(
            epw, arch, tmp_path / "b.json"))
        np.testing.assert_allclose(a[0], b[0], atol=1e-6)
        np.testing.assert_allclose(a[1], b[1], atol=1e-6)
