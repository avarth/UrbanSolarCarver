"""
UrbanSolarCarver: GPU-accelerated solar envelope generation.

Public API is exposed lazily: ``from urbansolarcarver import run_pipeline``
triggers the heavy imports (torch, warp, api_core) on first access, but
``import urbansolarcarver`` alone does not. This keeps CLI commands like
``urbansolarcarver --help`` and ``urbansolarcarver schema`` fast.
"""
from importlib.metadata import PackageNotFoundError, version as _distribution_version

__all__ = [
    "run_pipeline",
    "PipelineResult",
    "stages_to_rerun",
    "preprocessing",
    "thresholding",
    "exporting",
    "massing",
    "PreprocessingResult",
    "ThresholdingResult",
    "ExportingResult",
    "MassingResult",
    "load_config",
    "load_chain",
    "ChainConfig",
    "Criterion",
    "build_config",
    "user_config",
]

# The version is written once, in pyproject.toml, and read from the
# installed distribution's metadata.
try:
    __version__ = _distribution_version("urbansolarcarver")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0+unknown"

# Light imports that don't touch torch/warp
from .chain_config import ChainConfig, Criterion, load_chain  # noqa: E402,F401
from .load_config import build_config, load_config, user_config  # noqa: E402,F401

# Static-analysis-only imports: give IDEs/type checkers the lazy names
# without triggering the heavy torch/warp imports at runtime.
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover
    from .api import (  # noqa: F401
        run_pipeline, PipelineResult, stages_to_rerun,
        preprocessing, thresholding, exporting, massing,
        PreprocessingResult, ThresholdingResult, ExportingResult, MassingResult,
    )


def __getattr__(name):
    """Import ``.api`` (and with it torch, warp and api_core) on first use of
    one of its names in ``__all__``; ``tests/test_package_imports.py`` checks
    that every name in ``__all__`` resolves."""
    if name not in __all__:
        raise AttributeError(f"module 'urbansolarcarver' has no attribute {name!r}")
    try:
        import torch  # noqa: F401
    except ImportError as exc:
        # Install instructions instead of an ImportError from deep inside api_core.
        raise ImportError(
            "UrbanSolarCarver requires PyTorch, which is not installed. Run "
            "`python setup_env.py` from the repository: it installs the PyTorch "
            "build for your GPU driver (or the CPU build). See "
            "https://pytorch.org/get-started/locally/ to install it by hand."
        ) from exc
    from . import api
    value = getattr(api, name)
    globals()[name] = value  # later lookups skip this hook
    return value
