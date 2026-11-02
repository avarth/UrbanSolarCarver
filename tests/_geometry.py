"""Small meshes that several tests build."""
import numpy as np
import trimesh


def box_between(lower, upper, offset=(0.0, 0.0, 0.0)):
    """The axis-aligned box from corner *lower* to corner *upper*, moved by *offset*."""
    lower, upper = np.asarray(lower, float), np.asarray(upper, float)
    mesh = trimesh.creation.box(extents=upper - lower)
    mesh.apply_translation((lower + upper) / 2 + np.asarray(offset, float))
    return mesh
