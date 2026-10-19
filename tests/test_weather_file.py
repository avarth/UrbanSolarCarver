"""The cached EPW reader (weather_file.py): read once per unchanged file, copies for every caller."""
import os
import shutil

import numpy as np
import pytest

from urbansolarcarver.weather_file import read_weather_file


@pytest.fixture
def copied_epw_path(tmp_path, example_epw_path):
    """A copy of the example EPW that a test may change; its own path, so its own cache entries."""
    path = tmp_path / "weather.epw"
    shutil.copy(example_epw_path, path)
    return path


def rename_city(epw_path, new_city: str) -> None:
    """Write *new_city* as the city of the LOCATION line (the second field)."""
    lines = epw_path.read_text(encoding="utf-8", errors="replace").splitlines(True)
    fields = lines[0].split(",")
    fields[1] = new_city
    lines[0] = ",".join(fields)
    epw_path.write_text("".join(lines), encoding="utf-8")


class TestReadOncePerUnchangedFile:
    def test_an_unchanged_file_is_parsed_once(self, copied_epw_path):
        assert read_weather_file(copied_epw_path) is read_weather_file(str(copied_epw_path))

    def test_spellings_of_one_path_share_the_parse(self, copied_epw_path, monkeypatch):
        monkeypatch.chdir(copied_epw_path.parent)
        spelled_with_a_detour = os.path.join(str(copied_epw_path.parent), "..", copied_epw_path.parent.name,
                                             copied_epw_path.name)
        assert read_weather_file(copied_epw_path.name) is read_weather_file(spelled_with_a_detour)

    def test_a_new_modification_time_reads_the_file_again(self, copied_epw_path):
        first_city = read_weather_file(copied_epw_path).location.city
        modification_time_ns = os.stat(copied_epw_path).st_mtime_ns
        rename_city(copied_epw_path, first_city[::-1])      # same length, so only the time tells the change
        os.utime(copied_epw_path, ns=(modification_time_ns, modification_time_ns + 10**9))
        assert read_weather_file(copied_epw_path).location.city == first_city[::-1]

    def test_a_new_size_with_the_same_modification_time_reads_the_file_again(self, copied_epw_path):
        read_weather_file(copied_epw_path)
        modification_time_ns = os.stat(copied_epw_path).st_mtime_ns
        rename_city(copied_epw_path, "A Longer Name Than Before")
        os.utime(copied_epw_path, ns=(modification_time_ns, modification_time_ns))
        assert read_weather_file(copied_epw_path).location.city == "A Longer Name Than Before"


class TestCallersCannotAffectEachOther:
    def test_changing_a_location_leaves_the_next_one_unchanged(self, copied_epw_path):
        location = read_weather_file(copied_epw_path).location
        original_city, original_latitude = location.city, location.latitude
        location.city, location.latitude = "Elsewhere", 0.0
        unchanged = read_weather_file(copied_epw_path).location
        assert (unchanged.city, unchanged.latitude) == (original_city, original_latitude)

    def test_changing_the_dry_bulb_array_leaves_the_next_one_unchanged(self, copied_epw_path):
        temperatures = read_weather_file(copied_epw_path).dry_bulb_temperature()
        original = temperatures.copy()
        temperatures[:] = 99.0
        np.testing.assert_array_equal(read_weather_file(copied_epw_path).dry_bulb_temperature(), original)

    def test_changing_a_wea_leaves_the_next_one_unchanged(self, copied_epw_path):
        wea = read_weather_file(copied_epw_path).solar_irradiance_wea()
        original = wea.direct_normal_irradiance.values
        wea.direct_normal_irradiance.values = [0.0] * len(original)
        wea.location.city = "Elsewhere"
        unchanged = read_weather_file(copied_epw_path).solar_irradiance_wea()
        assert unchanged.direct_normal_irradiance.values == original
        assert unchanged.location.city != "Elsewhere"


class TestSameValuesAsLadybug:
    def test_location_and_dry_bulb_match_ladybugs_epw(self, example_epw_path):
        from ladybug.epw import EPW
        epw = EPW(str(example_epw_path))
        weather = read_weather_file(example_epw_path)
        assert weather.location.to_dict() == epw.location.to_dict()
        np.testing.assert_array_equal(weather.dry_bulb_temperature(), epw.dry_bulb_temperature.values)

    def test_solar_irradiance_wea_matches_ladybugs_wea_from_epw_file(self, example_epw_path):
        from ladybug.wea import Wea
        expected = Wea.from_epw_file(str(example_epw_path))
        wea = read_weather_file(example_epw_path).solar_irradiance_wea()
        assert wea.to_file_string() == expected.to_file_string()
        assert wea.direct_normal_irradiance.values == expected.direct_normal_irradiance.values
        assert wea.diffuse_horizontal_irradiance.values == expected.diffuse_horizontal_irradiance.values
        assert (wea.timestep, wea.is_leap_year) == (expected.timestep, expected.is_leap_year)


class TestRefusals:
    def test_a_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_weather_file(tmp_path / "absent.epw")

    def test_an_empty_path_raises_value_error(self):
        with pytest.raises(ValueError):
            read_weather_file("")

    def test_a_file_that_is_not_an_epw_raises_io_error(self, tmp_path):
        not_weather = tmp_path / "notes.epw"
        not_weather.write_text("not a weather file\n", encoding="utf-8")
        with pytest.raises(IOError, match="Cannot read the EPW weather file"):
            read_weather_file(not_weather)
