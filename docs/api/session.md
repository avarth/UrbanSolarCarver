# Session

Compute-session management. A `CarverSession` keeps the CUDA context alive across pipeline calls and holds a value cache for results that are expensive to rebuild (voxelized grids, Tregenza patch directions and solid angles). Compiled Warp kernels are cached by Warp itself, on disk.

Cache keys cover everything a value depends on (for a voxel grid: a hash of the mesh, voxel size, margin and device), so an entry stays valid for later runs. The cache holds at most `max_cache_bytes` (1 GiB by default) and drops the least recently used entries beyond that. The Grasshopper daemon runs one long-lived session and keeps its cache between commands, so re-running preprocessing on unchanged geometry skips voxelization; after each command it returns only unused GPU memory to the driver. The Python API and CLI run without a session unless you open one with `with CarverSession():`. The `session_cache` decorator stores a function's result in the active session under a key built from its arguments.

::: urbansolarcarver.session

## Choosing the compute device

`compute_device.resolve_compute_device` is the one rule every part of the package uses to turn a device choice into a `torch.device`: `"auto"` (or None) gives CUDA when torch sees a CUDA GPU, else the CPU; `"cpu"`, `"cuda"` and `"cuda:N"` are taken as given, and a CUDA choice on a machine without CUDA raises at once. `warp_device_name` gives the matching Warp device name.

::: urbansolarcarver.compute_device
