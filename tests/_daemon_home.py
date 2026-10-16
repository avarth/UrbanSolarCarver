"""Environment for a daemon subprocess that must not touch the real home folder."""
import os


def isolated_home_env(home):
    """The environment of the current process with the home folder set to *home*.

    The daemon takes its authkey from ``~/.urbansolarcarver``; with a temporary
    home, a test cannot read or create the real key.  Warp puts its kernel cache
    under the home folder when it is not told otherwise, so it is pinned to the
    cache of this process (no recompiling, and no cache folder in the working
    directory).
    """
    env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home)}
    try:
        import warp
        warp.init()
        env.setdefault("WARP_CACHE_PATH", str(warp.config.kernel_cache_dir))
    except Exception:
        pass
    return env
