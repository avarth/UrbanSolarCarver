# Geometry

The geometry pipeline from raw meshes to the output mesh, in three modules:

1. **Surface sampling** (`surface_sampling.py`): discretizes test-surface faces into evenly spaced points with outward-facing normals, using `grid_step` and a coplanarity tolerance; also computes the `edge_taper` weights. Used by preprocessing.
2. **Voxelization** (`voxelization.py`): converts the max-volume mesh into a dense cubic boolean grid at the configured `voxel_size`. Used by preprocessing.
3. **Meshing** (`meshing.py`): removes voxel clusters smaller than `min_voxels` and converts the carved voxel mask back into a triangle mesh, either as cubic voxel faces or via SDF smoothing + marching cubes + Taubin polishing. Used by exporting.

## Surface sampling

::: urbansolarcarver.surface_sampling

## Voxelization

::: urbansolarcarver.voxelization

## Meshing

::: urbansolarcarver.meshing
