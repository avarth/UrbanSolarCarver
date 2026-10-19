"""What importing the package costs, and which names it offers."""
import json
import subprocess
import sys


def test_every_public_name_resolves():
    import urbansolarcarver
    missing = [name for name in urbansolarcarver.__all__ if not hasattr(urbansolarcarver, name)]
    assert missing == []


# The light entry points, each with the modules it must not load. One fresh interpreter runs them in this order and
# lists, after each, which of its modules are loaded. Modules stay loaded from one entry point to the next, so an empty
# list means neither this entry point nor any before it loads them; the API, which loads torch, comes last.
LIGHT_ENTRY_POINTS = [
    ("importing the package", "import urbansolarcarver", ["torch"]),
    ("importing the CLI", "import urbansolarcarver.carver_cli", ["torch", "fastapi"]),
    ("usc daemon status",
     "from typer.testing import CliRunner\n"
     "from urbansolarcarver.carver_cli import app\n"
     "CliRunner().invoke(app, ['daemon', 'status'])",
     ["torch"]),
    ("importing the stage records and the run worker",
     "import urbansolarcarver.local_web_service.stage_records, urbansolarcarver.local_web_service.run_worker",
     ["torch"]),
    ("importing score_points and run_summary",
     "import urbansolarcarver.local_web_service.score_points, urbansolarcarver.local_web_service.run_summary",
     ["torch"]),
    ("importing the web service", "import urbansolarcarver.local_web_service.server", ["torch"]),
    ("importing the API", "import urbansolarcarver.api", ["matplotlib"]),
]

_RUN_EACH_ENTRY_POINT = """
import json, sys
for name, code, unwanted in json.loads(sys.argv[1]):
    exec(code, {})
    print('LOADED_AFTER ' + json.dumps([name, [module for module in unwanted if module in sys.modules]]))
"""


def test_light_entry_points_do_not_load_torch_matplotlib_or_the_web_service(tmp_path):
    from _daemon_home import isolated_home_env
    result = subprocess.run([sys.executable, "-c", _RUN_EACH_ENTRY_POINT, json.dumps(LIGHT_ENTRY_POINTS)],
                            capture_output=True, text=True, env=isolated_home_env(tmp_path))  # daemon status reads ~
    assert result.returncode == 0, result.stderr
    # Warp prints a banner on import, so only the marked lines are read.
    loaded = dict(json.loads(line.split(" ", 1)[1]) for line in result.stdout.splitlines()
                  if line.startswith("LOADED_AFTER "))
    assert loaded == {name: [] for name, _code, _unwanted in LIGHT_ENTRY_POINTS}
