"""The EPW memo of tests/conftest.py gives every read a copy of its own and follows the file's content."""
import shutil

from ladybug.epw import EPW


def test_a_changed_epw_object_does_not_change_the_next_read(example_epw_path):
    first = EPW(str(example_epw_path))
    first_hour_temperature = first.dry_bulb_temperature.values[0]
    first.dry_bulb_temperature.values = [99.0] * 8760
    first.location.city = "Changed"
    second = EPW(str(example_epw_path))
    assert second.dry_bulb_temperature.values[0] == first_hour_temperature
    assert second.location.city != "Changed"


def test_a_rewritten_file_is_parsed_again(example_epw_path, tmp_path):
    copy_path = tmp_path / "weather.epw"
    shutil.copyfile(example_epw_path, copy_path)
    original = EPW(str(copy_path)).dry_bulb_temperature.values
    lines = copy_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    fields = lines[8].split(",")
    fields[6] = "42.0"                      # dry-bulb temperature of the first data row
    lines[8] = ",".join(fields)
    copy_path.write_text("".join(lines), encoding="utf-8")
    reread = EPW(str(copy_path))
    changed_hours = [hour for hour, (before, after) in enumerate(zip(original, reread.dry_bulb_temperature.values))
                     if before != after]
    assert reread.file_path == str(copy_path)
    assert len(changed_hours) == 1 and reread.dry_bulb_temperature.values[changed_hours[0]] == 42.0
