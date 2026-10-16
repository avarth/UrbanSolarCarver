"""
Staged pipeline API of UrbanSolarCarver.

The three stages live in submodules:
 - preprocessing.py: voxelize, sample test surfaces, ray-trace scores
 - thresholding.py: smooth and threshold scores into a mask
 - exporting.py: mesh the mask and write the run report
 - massing.py: stacked floor plates that follow the footprint
Private helpers for these stages are in `_util`, `_diagnostics` and
`_reporting`; the geometry code is in `urbansolarcarver.surface_sampling`,
`urbansolarcarver.voxelization` and `urbansolarcarver.meshing`, and the
ray-tracing code in `urbansolarcarver.carving`.
"""

# Staged API
from .preprocessing import preprocessing, PreprocessingResult  # noqa: F401
from .thresholding import thresholding, ThresholdingResult     # noqa: F401
from .exporting import exporting, ExportingResult              # noqa: F401
from .massing import massing, MassingResult                    # noqa: F401

__all__ = [
    "preprocessing",
    "thresholding",
    "exporting",
    "massing",
    "PreprocessingResult",
    "ThresholdingResult",
    "ExportingResult",
    "MassingResult",
]