"""The test run keeps out of the user's own folders (conftest.py)."""
import os
from pathlib import Path

from urbansolarcarver.daemon_client import daemon_authkey_path


def test_every_test_has_a_home_folder_of_its_own(tmp_path_factory):
    assert Path.home().is_relative_to(tmp_path_factory.getbasetemp())
    assert daemon_authkey_path().is_relative_to(Path.home())


def test_the_warp_kernel_cache_is_not_in_the_working_folder():
    cache = Path(os.environ["WARP_CACHE_PATH"])
    assert cache.is_absolute()
    assert not cache.is_relative_to(Path.cwd())
