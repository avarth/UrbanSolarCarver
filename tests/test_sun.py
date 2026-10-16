"""Sun and weather input (sun.py)."""
import pytest


def test_epw_cache_rereads_a_replaced_file(tmp_path):
    import os
    import shutil
    from _epw import resolve_epw
    from urbansolarcarver.sun import _load_epw
    src = resolve_epw()
    if not src:
        pytest.skip("No EPW available")
    path = tmp_path / "w.epw"
    shutil.copy(src, path)
    first = _load_epw(str(path))
    text = path.read_text(encoding="utf-8", errors="replace").splitlines(True)
    text[0] = text[0].replace(text[0].split(",")[1], "Renamed City", 1)
    path.write_text("".join(text), encoding="utf-8")
    os.utime(path, ns=(first_mtime := os.stat(path).st_mtime_ns, first_mtime + 10**9))
    assert _load_epw(str(path)).location.city == "Renamed City"
