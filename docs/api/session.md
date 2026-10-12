# Session

Compute-session management. A `CarverSession` keeps the CUDA context alive across pipeline calls and holds a value cache for results that are expensive to rebuild (voxelized grids, Tregenza patch directions and solid angles). Compiled Warp kernels are cached by Warp itself, on disk.

The Grasshopper daemon runs one long-lived session and clears its cache after every command, so the cache saves work within one command (for example across the stages of `run_pipeline`). The Python API and CLI run without a session unless you open one with `with CarverSession():`. The `session_cache` decorator stores a function's result in the active session under a key built from its arguments.

::: urbansolarcarver.session
