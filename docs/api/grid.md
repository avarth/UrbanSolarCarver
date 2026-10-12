# Grid Operations

Handles the geometry pipeline from raw meshes to final output:

1. **Voxelization**: converts the max-volume mesh into a dense cubic boolean grid at the configured `voxel_size`.
2. **Surface sampling**: discretizes test-surface faces into evenly spaced points with outward-facing normals, using `grid_step` and a coplanarity tolerance; also computes the `edge_taper` weights.
3. **Pruning**: removes voxel clusters smaller than `min_voxels` using connected-component labelling.
4. **Mesh reconstruction**: converts the carved voxel mask back into a triangle mesh, either as cubic voxel faces or via SDF smoothing + marching cubes + Taubin polishing.

::: urbansolarcarver.grid
