"""USC Massing Settings: floor heights, plate size, tolerance and stacking.

Generates override strings for the massing stage. Connect the output to
USC Massing's ``massing_overrides`` input.

Inputs
------
ground_floor_height : float, optional
    Height of the ground floor in metres. Default: 5.
floor_height : float, optional
    Height of every floor above the ground floor in metres. Default: 3.
min_plate_dimension : float, optional
    Bay width and minimum floor-plate width in metres. Default: 3.
plate_tolerance : float, optional
    Largest share (0-1) of a bay's volume on a floor that may lie outside
    the carved envelope. Plates never leave the maximum volume.
    Default: 0.2.
supported : bool, optional
    True: a bay is built only where it is built on the floor below.
    False: each floor is decided on its own. Default: True.

Outputs
-------
overrides : str
    Semicolon-joined key=value pairs. Connect to USC Massing's
    ``massing_overrides`` input: changes here re-run only Massing.
"""

try:
    ghenv.Component.Name = "USC Massing Settings"
    ghenv.Component.NickName = "USC_MassSet"
    ghenv.Component.Description = "Floor heights, bay width, tolerance and stacking for USC_Massing. Connect to USC_Massing's 'massing_overrides' input."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("ground_floor_height", "Height of the ground floor in metres. Default: 5."),
        ("floor_height", "Height of every floor above the ground floor in metres. Default: 3."),
        ("min_plate_dimension", "Bay width and minimum floor-plate width in metres. Bays are cut perpendicular to the facades at this spacing. Default: 3."),
        ("plate_tolerance", "Largest share (0-1) of a bay's volume on a floor that may lie outside the carved envelope. Plates never leave the maximum volume. Default: 0.2."),
        ("supported", "True: a bay is built only where it is built on the floor below. False: each floor is decided on its own. Default: True."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", "Massing settings formatted for USC_Massing's 'massing_overrides' input. Changes here re-run only Massing."
except Exception:
    pass

_items = []
if ground_floor_height is not None:
    _items.append(f"ground_floor_height={float(ground_floor_height)}")
if floor_height is not None:
    _items.append(f"floor_height={float(floor_height)}")
if min_plate_dimension is not None:
    _items.append(f"min_plate_dimension={float(min_plate_dimension)}")
if plate_tolerance is not None:
    _items.append(f"plate_tolerance={float(plate_tolerance)}")
if supported is not None:
    _items.append("plate_stacking={}".format("supported" if bool(supported) else "free"))

overrides = ";".join(_items) if _items else None
