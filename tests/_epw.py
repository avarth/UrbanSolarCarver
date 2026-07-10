"""Shared EPW resolution for tests.

Order: the ``USC_EPW_PATH`` environment variable (any local EPW), else the
public-domain NREL TMY3 file bundled under ``examples/weather/``.
"""
import os
from pathlib import Path

BUNDLED_EPW = (
    Path(__file__).resolve().parent.parent
    / "examples" / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw"
)


def resolve_epw() -> str:
    """Return a usable EPW path, or "" if none is available."""
    env = os.environ.get("USC_EPW_PATH", "")
    if env and Path(env).is_file():
        return env
    if BUNDLED_EPW.is_file():
        return str(BUNDLED_EPW)
    return ""
