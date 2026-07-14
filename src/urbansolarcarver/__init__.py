"""
UrbanSolarCarver — GPU-accelerated solar envelope generation.

Public API is exposed lazily: ``from urbansolarcarver import run_pipeline``
triggers the heavy imports (torch, warp, api_core) on first access, but
``import urbansolarcarver`` alone does not. This keeps CLI commands like
``urbansolarcarver --help`` and ``urbansolarcarver schema`` instant.
"""

__all__ = [
    "run_pipeline",
    "preprocessing",
    "thresholding",
    "exporting",
    "PreprocessingResult",
    "ThresholdingResult",
    "ExportingResult",
    "load_config",
    "user_config",
]

# Light imports that don't touch torch/warp
from .load_config import load_config, user_config  # noqa: F401

# Static-analysis-only imports: give IDEs/type checkers the lazy names
# without triggering the heavy torch/warp imports at runtime.
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .api import (  # noqa: F401
        run_pipeline,
        preprocessing, thresholding, exporting,
        PreprocessingResult, ThresholdingResult, ExportingResult,
    )

# Everything else is deferred until actually accessed.
_api_loaded = False
_api_names = {}


def _ensure_api():
    global _api_loaded, _api_names
    if _api_loaded:
        return
    # This triggers torch, warp, api_core
    try:
        import torch as _torch  # noqa: F401
    except ImportError as _e:
        raise ImportError(
            "UrbanSolarCarver requires PyTorch but it is not installed.\n"
            "Install it before this package. Choose the command matching your CUDA version:\n"
            "  CPU only:  pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
            "  CUDA 11.8: pip install torch --index-url https://download.pytorch.org/whl/cu118\n"
            "  CUDA 12.x: pip install torch --index-url https://download.pytorch.org/whl/cu121\n"
            "See https://pytorch.org/get-started/locally/ for details."
        ) from _e
    from .api import (
        run_pipeline,
        preprocessing, thresholding, exporting,
        PreprocessingResult, ThresholdingResult, ExportingResult,
    )
    _api_names.update({
        "run_pipeline": run_pipeline,
        "preprocessing": preprocessing,
        "thresholding": thresholding,
        "exporting": exporting,
        "PreprocessingResult": PreprocessingResult,
        "ThresholdingResult": ThresholdingResult,
        "ExportingResult": ExportingResult,
    })
    _api_loaded = True


def __getattr__(name):
    # load_config / user_config are imported eagerly at module level; if that
    # import had failed, `import urbansolarcarver` itself would have raised,
    # so only the heavy lazy names can reach this hook.
    if name in __all__:
        _ensure_api()
        if name in _api_names:
            return _api_names[name]
    raise AttributeError(f"module 'urbansolarcarver' has no attribute {name!r}")
