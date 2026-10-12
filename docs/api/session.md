# Session

Compute-session management. A `CarverSession` keeps the CUDA context alive across pipeline calls and holds a value cache for results that are expensive to rebuild (voxelized grids, Tregenza patch directions and solid angles). Compiled Warp kernels are cached by Warp itself, on disk.

Cache keys cover everything a value depends on (for a voxel grid: a hash of the mesh, voxel size, margin and device), so an entry stays valid for later runs. The cache holds at most `max_cache_bytes` (1 GiB by default) and drops the least recently used entries beyond that. The Grasshopper daemon runs one long-lived session and keeps its cache between commands, so re-running preprocessing on unchanged geometry skips voxelization; after each command it returns only unused GPU memory to the driver. The Python API and CLI run without a session unless you open one with `with CarverSession():`. The `session_cache` decorator stores a function's result in the active session under a key built from its arguments.

::: urbansolarcarver.session
