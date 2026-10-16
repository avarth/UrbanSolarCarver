# I/O

Mesh loading and saving through Trimesh.

- **`load_mesh`** reads a mesh file (PLY, OBJ, STL and the other formats Trimesh supports).
- **`save_mesh`** writes a mesh; for PLY it switches to double-precision vertices when float32 would round the coordinates (georeferenced models far from the origin).
- **`validate_inputs`** checks that the files a preprocessing run needs exist (meshes, and the EPW for the modes that read one).
- **`load_meshes`** loads the maximum volume and the test surfaces, and reports coordinates that a float32 PLY file has rounded.

::: urbansolarcarver.io
