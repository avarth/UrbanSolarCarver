# I/O

Mesh loading and saving through Trimesh.

- **`load_mesh`** reads a mesh file (PLY, OBJ, STL and the other formats Trimesh supports).
- **`save_mesh`** writes a mesh; for PLY it switches to double-precision vertices when float32 would round the coordinates (georeferenced models far from the origin).

::: urbansolarcarver.io
