"""USC EPW Path: provide the weather file location.

Required for: time-based, irradiance, benefit modes.
Not used by: daylight, radiative_cooling, tilted_plane.

Inputs
------
epw_path : str
    Full file path to an EnergyPlus Weather (.epw) file.
    Accepts a text string or a File Path parameter. Unlike USC_Config's
    own epw_path input, a relative path is passed on unchanged.

Outputs
-------
overrides : str
    epw_path=<value> override for USC_Config. A missing file or a
    non-.epw extension only gives a warning.
"""

import os

try:
    ghenv.Component.Name = "USC EPW Path"
    ghenv.Component.NickName = "USC_EPW"
    ghenv.Component.Description = (
        "Provides the path to an EnergyPlus Weather (.epw) file. "
        "Required for time-based, irradiance and benefit modes. "
        "Not used by daylight, radiative_cooling or tilted_plane. "
        "Download EPW files from climate.onebuilding.org or ladybug.tools."
    )
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "epw_path", (
        "Full path to an EnergyPlus Weather (.epw) file. "
        "Right-click and choose 'Set One File Path', or connect a "
        "text panel / File Path parameter. Use an absolute path. "
        "Example: C:\\Weather\\GRC_Athens.epw"
    )
    oo[0].Name, oo[0].Description = "overrides", (
        "EPW path formatted as an override string. "
        "Connect to USC_Config 'overrides' input."
    )
except Exception:
    pass

overrides = None

if epw_path is not None:
    _path = str(epw_path).strip()
    if _path:
        if not _path.lower().endswith(".epw"):
            try:
                from Grasshopper.Kernel import GH_RuntimeMessageLevel
                ghenv.Component.AddRuntimeMessage(
                    GH_RuntimeMessageLevel.Warning,
                    "File does not have .epw extension: {}".format(_path)
                )
            except Exception:
                pass
        if not os.path.isfile(_path):
            try:
                from Grasshopper.Kernel import GH_RuntimeMessageLevel
                ghenv.Component.AddRuntimeMessage(
                    GH_RuntimeMessageLevel.Warning,
                    "File not found: {}".format(_path)
                )
            except Exception:
                pass
        overrides = "epw_path={}".format(_path)
