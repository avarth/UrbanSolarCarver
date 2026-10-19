"""USC Grid Settings: control voxel grid resolution and padding.

Inputs
------
voxel_size : float, optional
    Voxel edge length in meters. Smaller = finer but slower. Default: 1.0
grid_step : float, optional
    Surface sampling spacing in meters; must not exceed voxel_size.
    Default: half the voxel size
margin_frac : float, optional
    Padding on each side of the grid, as a fraction of the longest side
    of the max volume's bounding box. Default: 0.01

Outputs
-------
overrides : str
    Semicolon-joined key=value pairs for the connected inputs.
"""

try:
    ghenv.Component.Name = "USC Grid Settings"
    ghenv.Component.NickName = "USC_Grid"
    ghenv.Component.Description = "Controls voxel grid resolution and bounding-box padding. Smaller voxel_size = finer detail but slower. Start coarse (2-3 m) and refine."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("voxel_size", "Edge length of each voxel cube in meters. Smaller values = finer resolution but slower computation. Start with 2.0 for testing, use 1.0 or 0.5 for final results. Typical range: 0.5 to 5.0 m. Leave grid_step unset and it follows the voxel size (half of it)."),
        ("grid_step", "Spacing between sample points on the test surfaces, in meters. Rays are cast from each point, so this controls how densely rays are cast. Leave it unset for half the voxel size. A value you set must be less than or equal to voxel_size (the config rejects a larger value)."),
        ("margin_frac", "Empty padding added on each side of the voxel grid, as a fraction of the longest side of the max volume's bounding box. Default 0.01 (1%). Increase to 0.05 if you see clipping at boundaries."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", "Grid settings formatted for USC_Config. Connect to Config's 'overrides' input."
except Exception:
    pass

_items = []
for key, val in [
    ("voxel_size", voxel_size),
    ("grid_step", grid_step),
    ("margin_frac", margin_frac),
]:
    if val is not None:
        _items.append(f"{key}={float(val)}")
overrides = ";".join(_items) if _items else None
