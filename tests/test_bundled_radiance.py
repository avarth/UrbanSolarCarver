"""The sky matrix of Solar energy and Solar heating runs the gendaymtx in the pyradiance package, a dependency, never a Radiance
installed on the computer (conftest.no_radiance_of_this_computer hides one), and reads its output whatever header lines that
Radiance version writes."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest
import torch

from urbansolarcarver import sky_patches

OLD_HEADER = b"#?RADIANCE\ngendaymtx -m 1 -d -O1 -A sky.wea\nLATLONG= 39.74 -105.18\nNROWS=146\nNCOLS=1\nNCOMP=3\nFORMAT=ascii\n\n"
NEW_HEADER = OLD_HEADER.replace(b"NCOLS=1\n", b"NCOLS=1\nNAVERAGED=8760\n")    # Radiance 6, as in pyradiance


def test_the_sky_matrix_runs_the_gendaymtx_of_pyradiance():
    program = Path(sky_patches.gendaymtx_path())
    assert program.is_file() and program.stem == "gendaymtx"
    assert Path(importlib.util.find_spec("pyradiance").origin).parent in program.parents


def test_without_pyradiance_the_error_says_what_to_install(monkeypatch):
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "pyradiance" else real_find_spec(name, *a))
    with pytest.raises(RuntimeError, match="pyradiance"):
        sky_patches.gendaymtx_path()


@pytest.mark.parametrize("header", [OLD_HEADER, NEW_HEADER], ids=["radiance 5", "radiance 6"])
def test_the_ground_patch_is_dropped_whatever_the_header_length(header):
    """Ladybug skips a fixed 8 header lines; Radiance 6 writes 9, which moved every patch one along."""
    body = b"9 9 9\n" + b"".join(f"{i} {i} {i}\n".encode() for i in range(145))   # the ground patch, then the sky
    lines = sky_patches._with_ladybug_header(header + body).split(b"\n")
    assert lines[8] == b"9 9 9" and lines[9] == b"0 0 0" and lines[-2] == b"144 144 144"


def test_output_without_a_radiance_header_is_refused():
    with pytest.raises(RuntimeError, match="header"):
        sky_patches._with_ladybug_header(b"gendaymtx: cannot open sky.wea\n")


@pytest.mark.parametrize("mode", ["irradiance", "benefit"])
def test_solar_energy_and_solar_heating_weights_need_no_radiance_of_this_computer(example_epw_path, mode):
    weights = sky_patches.compute_EPW_based_weights(mode, str(example_epw_path), list(range(8760)), torch.device("cpu"))
    assert weights.shape == (145,) and float(weights.sum()) > 0


def test_the_yearly_sky_of_the_example_weather_file_keeps_its_values(example_epw_path):
    """Values of Ladybug Tools' Radiance before 0.12.2, equal to the last digit with pyradiance's (checked 2026-11-16 for both
    modes, three north angles and two periods). A patch shift, as from a header line read as data, keeps the total but moves
    each value into the next patch: the row at 66° altitude below would start 0.0 5.24 ..., and the zenith would read 4.96."""
    weights = sky_patches.compute_EPW_based_weights("irradiance", str(example_epw_path), list(range(8760)),
                                                    torch.device("cpu")).double().numpy()
    assert weights.sum() == pytest.approx(3078.138, abs=0.01)
    row_at_66_degrees = [5.24, 5.44, 6.09, 7.30, 42.86, 53.55, 47.80, 46.25, 34.29, 7.41, 6.14, 5.44]
    np.testing.assert_allclose(weights[126:138], row_at_66_degrees, atol=0.006)
    assert weights[144] == pytest.approx(5.372, abs=0.001)     # the zenith
