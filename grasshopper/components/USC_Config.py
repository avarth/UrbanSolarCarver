"""USC Config — Assemble a carving configuration.

Creates a config handle from a mode selection and optional base YAML.
Connect parameter components (AnalysisPeriod, GridSettings, etc.) to
the overrides input for full control.

Inputs
------
session : dict
    Session handle from USC_Session.
mode : str
    Carving mode. One of: time-based, irradiance, benefit, daylight,
    tilted_plane, radiative_cooling.
epw_path : str, optional
    Path to EPW weather file. Required for all modes except tilted_plane.
out_dir : str
    Output directory for all pipeline artifacts.
config_yaml : str, optional
    Path to a base YAML config. If None, uses the mode-specific default
    from configs/.
overrides : list of str, optional
    Key=value override strings from parameter components.
    Multiple sources are merged (last wins for duplicate keys).

Outputs
-------
config : dict
    Opaque config handle for pipeline components.
    Contains: yaml_path, overrides_dict, mode, out_dir, session.
summary : str
    Human-readable summary of the configuration.
"""

from pathlib import Path


class USCConfig:
    """Opaque config handle. Not iterable — GH treats it as a single item."""
    __slots__ = ("session", "yaml_path", "overrides", "mode", "out_dir")

    def __init__(self, session, yaml_path, overrides, mode, out_dir):
        self.session = session
        self.yaml_path = yaml_path
        self.overrides = overrides
        self.mode = mode
        self.out_dir = out_dir

    def __repr__(self):
        return "USCConfig({})".format(self.mode)


# -- GH UI rollovers --------------------------------------------------------
try:
    ghenv.Component.Name = "USC Config"
    ghenv.Component.NickName = "USC_Config"
    ghenv.Component.Description = "Assembles a complete configuration from mode selection, file paths, and parameter overrides. Wire parameter components (Period, Grid, Threshold, etc.) into the 'overrides' input. Outputs a config handle for pipeline components."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "session", "Session handle from the USC_Session component. Drag a wire from USC_Session's 'session' output to here."
    ii[1].Name, ii[1].Description = "mode", "Carving algorithm. Options: 'benefit' (heating-benefit envelope; hour weighting via balance point or, with USC_SimulateWeights, a 5R1C building simulation), 'time-based' (shadow-hour envelope), 'irradiance' (total solar radiation envelope), 'daylight' (CIE overcast daylight envelope), 'tilted_plane' (geometric daylight access angle), 'radiative_cooling' (experimental night-sky cooling)."
    ii[2].Name, ii[2].Description = "epw_path", "Full path to an EnergyPlus Weather (.epw) file for your location. Required for all modes except 'tilted_plane' and 'daylight'. Download from climate.onebuilding.org or ladybug.tools."
    ii[3].Name, ii[3].Description = "out_dir", "Folder where all results will be saved. A subfolder structure (preprocessing/, thresholding/, exporting/) is created automatically. Tip: use a fresh folder for each experiment."
    ii[4].Name, ii[4].Description = "config_yaml", "Optional. Path to a base YAML configuration file. If omitted, the tool picks a sensible default for your chosen mode. Only needed for advanced customisation."
    ii[5].Name, ii[5].Description = "overrides", "Optional parameter overrides from other USC components (Period, Grid, Threshold, etc.). Connect multiple override wires here -- they are merged automatically. Set this input to List Access."
    # CRITICAL: set overrides input to List Access so GH passes all items
    # at once instead of running the component once per item.
    import Grasshopper
    ii[5].Access = Grasshopper.Kernel.GH_ParamAccess.list
    oo[0].Name, oo[0].Description = "config", "Configuration handle passed to pipeline components (USC_Preprocess, USC_RunAll, etc.). Contains all settings for the run. Do not modify."
    oo[1].Name, oo[1].Description = "summary", "Human-readable text showing the active mode, config file, output folder, and all override parameters. Check this to verify your setup before running."
except Exception:
    pass

# -- Helpers -----------------------------------------------------------------

def _flatten(x):
    """Flatten GH tree/lists/semicolon-joined strings into key=value pairs."""
    if x is None:
        return []
    if isinstance(x, str):
        # Split semicolon-delimited strings from parameter components
        return [s.strip() for s in x.split(";") if s.strip()]
    try:
        from ghpythonlib import treehelpers as th
        items = th.tree_to_list(x, retrieve_items=True)
    except Exception:
        items = x
    flat, stack = [], [items]
    while stack:
        cur = stack.pop()
        if isinstance(cur, (list, tuple)):
            stack.extend(reversed(cur))
        elif cur is not None:
            # Each item might also be semicolon-joined
            for s in str(cur).split(";"):
                s = s.strip()
                if s:
                    flat.append(s)
    return flat


def _mode_default_yaml(root, mode_str):
    """Return the mode-specific default config YAML path."""
    mode_map = {
        "time-based": "config_time_based.yaml",
        "timebased": "config_time_based.yaml",
        "time_based": "config_time_based.yaml",
        "irradiance": "config_irradiance.yaml",
        "benefit": "config_benefit.yaml",
        "daylight": "config_daylight.yaml",
        "tilted_plane": "config_tilted_plane.yaml",
        "tiltedplane": "config_tilted_plane.yaml",
        "radiative_cooling": "config_radiative_cooling.yaml",
        "radiativecooling": "config_radiative_cooling.yaml",
    }
    # Normalize: strip hyphens/underscores for flexible matching
    key = mode_str.replace("-", "").replace("_", "")
    fname = mode_map.get(mode_str) or mode_map.get(key)
    return Path(root) / "configs" / fname if fname else None


# -- Main logic --------------------------------------------------------------

config = None
summary = ""

if session is None:
    summary = "ERROR: connect a USC Session component"
elif mode is None:
    summary = "ERROR: select a carving mode"
elif out_dir is None:
    summary = "ERROR: specify an output directory"
else:
    # session is a USCSession object (attribute access, not dict)
    root = session.root
    mode_str = str(mode).strip().lower()

    # Normalize mode aliases to canonical form (what the schema validator expects)
    _mode_canonical = {
        "timebased": "time-based", "time_based": "time-based",
        "tiltedplane": "tilted_plane", "tilted-plane": "tilted_plane",
        "radiativecooling": "radiative_cooling", "radiative-cooling": "radiative_cooling",
    }
    mode_str = _mode_canonical.get(mode_str, mode_str)

    # Resolve YAML path
    if config_yaml is not None and str(config_yaml).strip():
        yaml_path = str(config_yaml)
    else:
        _default = _mode_default_yaml(root, mode_str)
        yaml_path = str(_default) if _default is not None else None

    if yaml_path is None:
        summary = "ERROR: unknown mode '{}'".format(mode_str)
    else:
        # Parse overrides into dict (last wins)
        override_items = _flatten(overrides)
        overrides_dict = {}
        for item in override_items:
            if "=" in item:
                k, v = item.split("=", 1)
                overrides_dict[k.strip()] = v.strip()

        # Always inject mode and out_dir
        overrides_dict["mode"] = mode_str
        overrides_dict["out_dir"] = str(out_dir)

        # Inject EPW if provided
        if epw_path is not None and str(epw_path).strip():
            overrides_dict["epw_path"] = str(epw_path)

        # Build config handle (non-iterable object, not dict)
        config = USCConfig(
            session=session,
            yaml_path=yaml_path,
            overrides=overrides_dict,
            mode=mode_str,
            out_dir=str(out_dir),
        )

        # Summary
        lines = [
            f"Mode: {mode_str}",
            f"YAML: {Path(yaml_path).name}",
            f"Output: {out_dir}",
        ]
        if epw_path:
            lines.append(f"EPW: {Path(str(epw_path)).name}")
        if overrides_dict:
            param_keys = [k for k in overrides_dict if k not in ("mode", "out_dir", "epw_path")]
            if param_keys:
                lines.append(f"Overrides: {', '.join(param_keys)}")
        summary = "\n".join(lines)
