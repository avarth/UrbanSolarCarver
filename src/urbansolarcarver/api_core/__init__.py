"""
Staged pipeline API of UrbanSolarCarver.

The three stages live in submodules:
 - preprocessing.py: voxelize, sample test surfaces, ray-trace scores
 - thresholding.py: smooth and threshold scores into a mask
 - exporting.py: mesh the mask and write the run report
Private helpers for these stages are in `_util`, `_diagnostics` and
`_reporting`; the geometry and ray-tracing code is in `urbansolarcarver.grid`
and `urbansolarcarver.carving`.
"""

# Staged API
from .preprocessing import preprocessing, PreprocessingResult  # noqa: F401
from .thresholding import thresholding, ThresholdingResult     # noqa: F401
from .exporting import exporting, ExportingResult              # noqa: F401

__all__ = [
    "preprocessing",
    "thresholding",
    "exporting",
    "PreprocessingResult",
    "ThresholdingResult",
    "ExportingResult",
]