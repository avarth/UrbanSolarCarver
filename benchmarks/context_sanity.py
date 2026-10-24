"""Context and terrain: sanity checks against independent references, on synthetic typology scenes.

Not a test suite: a check to run after changing how context or terrain affect the carving. Each scene
(courtyard, rows, lshape from tests/typologies.py, daylight unless said) runs on the CPU with three
context sets:

    neighbours    the four 12 m neighbour masses behind the neighbour facades (the test surfaces)
    tall south    the same, with the south mass 30 % taller (15.6 m)
    full          the neighbours, a 30 m chimney inside the plot, a tree crown above the max volume,
                  and a sloping terrain patch through the bottom of the plot (where it rises above the ground, it
                  buries the plot's own facade points sampled at their foot, z = 0: they show up as fully blocked
                  test points and the test_points_blocked warning)

and compares them with independent references that share no code with the engine's context path:

    occupancy     the reduced voxel grid against trimesh point-in-mesh tests (column rule) and trimesh
                  downward rays (ground heights)
    ray drop      the rays dropped against trimesh ray-mesh intersection
    scoring       the scores against the CPU reference march of tests/oracle.py, fed the rays the engine
                  kept (so it checks the scoring of what is kept, not the ray test again)

and checks the properties the method promises: at the same score cutoff nothing is lost; no score
rises (except next to columns the context removed, where a sliver of the max volume can be left
standing alone); a taller south neighbour keeps more only on the south side of the plot (daylight and
sun hours on 21 Dec: all of it; daylight, an even overcast sky: most of it, since the low southern rays it
now blocks start at the north facades and cross the whole plot); a context that blocks nothing changes nothing, bit for bit; a canopy blocks
exactly the rays that reach it within the ray length.

    python benchmarks/context_sanity.py [--out runs/context_sanity] [--cases courtyard,rows,lshape]

Writes <out>/results.json and <out>/summary.md; exits 1 if a check fails. Takes a few minutes.
"""
import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import torch
import trimesh
from scipy import ndimage as ndi

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import cases  # noqa: E402
import oracle  # noqa: E402
from typologies import SceneSpec, build, footprint, neighbour_masses  # noqa: E402
from urbansolarcarver.io import _export_ply_double  # noqa: E402
from urbansolarcarver.sky_patches import fetch_tregenza_patch_directions  # noqa: E402

EPW = str(REPO / "examples" / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw")
RAY_LENGTH = 200.0          # cases.config
SOUTH_FACTOR = 1.3


def box(lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    mesh = trimesh.creation.box(extents=hi - lo)
    mesh.apply_translation((lo + hi) / 2)
    return mesh


def patch(x0, x1, y0, y1, z_of):
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return trimesh.Trimesh([(x, y, z_of(x, y)) for x, y in corners], [[0, 1, 2], [0, 2, 3]], process=False)


def combined(*meshes):
    return trimesh.util.concatenate([mesh for mesh in meshes if mesh is not None])


class Scene:
    """One typology scene and its context sets."""

    def __init__(self, typology):
        self.typology = typology
        self.spec = SceneSpec(typology=typology, seed=0)
        self.scene = build(self.spec)
        fp = footprint(self.spec)
        px, py = np.asarray(fp.representative_point().coords[0])
        self.chimney = box((px - 1.7, py - 1.3, 0), (px + 1.9, py + 2.1, 30))
        from shapely.geometry import box as plan_box
        for dx, dy in ((8, 0), (-8, 0), (0, 8), (0, -8), (6, 6), (-6, -6), (4, 0)):
            if fp.contains(plan_box(px + dx - 1.7, py + dy - 2.3, px + dx + 1.7, py + dy + 2.3)):
                break
        h = self.spec.max_h
        self.crown = box((px + dx - 1.7, py + dy - 2.3, h + 1.1), (px + dx + 1.7, py + dy + 2.3, h + 4.3))
        plot = self.spec.plot + 2
        # Ground rising to the east, at most 0.7 m: it takes the lowest voxels on the east side, and buries the own facade
        # points sampled at their foot (z = 0) there.
        self.terrain = patch(-plot, plot, -plot, plot, lambda x, y: 0.1 * x - 1.5)
        masses = neighbour_masses(self.spec)         # north, south, east, west (rotation 0: +y is north)
        south = masses[1].copy()
        v = south.vertices.copy()
        v[v[:, 2] > self.spec.neigh_h - 1e-6, 2] = SOUTH_FACTOR * self.spec.neigh_h
        south.vertices = v
        self.neighbours = self.scene.context
        self.tall_south = combined(masses[0], south, masses[2], masses[3])

    def run(self, root, name, mode, context=None, terrain=None, **over):
        folder = root / self.typology / name
        for key, mesh in (("context_path", context), ("terrain_path", terrain)):
            if mesh is not None:
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{key[:-5]}.ply"
                _export_ply_double(mesh, str(path))
                over[key] = str(path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return cases.run(self.scene, folder, EPW, mode, **over)


def first_hits(mesh, origins, normals, dirs, ray_length=RAY_LENGTH):
    """Distance along each ray (from origin + 1 cm along the normal) to its first hit beyond 1 mm; inf for none."""
    starts = origins + 0.01 * normals
    locations, ray_index, _ = mesh.ray.intersects_location(starts, dirs, multiple_hits=True)
    first = np.full(len(origins), np.inf)
    if len(ray_index):
        dist = np.einsum("ij,ij->i", locations - starts[ray_index], dirs[ray_index])
        ok = (dist >= 1e-3) & (dist <= ray_length)
        np.minimum.at(first, ray_index[ok], dist[ok])
    return first


def sky_rays(run):
    dirs = fetch_tregenza_patch_directions(torch.device("cpu")).numpy().astype(float)
    o, n, d, pi, di = oracle.pairs(run.points, run.normals, dirs)
    return o, n, d / np.linalg.norm(d, axis=1, keepdims=True), pi, di


def reference_scores(run, keep):
    """The CPU reference scores of the sky rays in *keep*."""
    pw = np.load(run.pre / "patch_weights.npy").astype(float)
    o, n, d, _pi, di = sky_rays(run)
    scores, own = oracle.march(run, o[keep], n[keep], d[keep], weights=pw[di][keep], ray_length=RAY_LENGTH)
    area = float(json.loads((run.pre / "manifest.json").read_text())["grid_step"]) ** 2
    return oracle.follow_own_skin(scores, own) * area


def cutoff(run):
    return json.loads((run.thr / "diagnostics" / "diagnostic.json").read_text())["threshold_value"]


def context_report(run):
    return json.loads((run.pre / "diagnostics" / "diagnostic.json").read_text())["context"]


def column_centres(run):
    R = run.occ.shape[0]
    c = run.origin[:2, None] + (np.arange(R) + 0.5)[None, :] * run.vs
    return np.meshgrid(c[0], c[1], indexing="ij")


def check_scene(s, root, results):
    def add(name, ok, detail):
        results.append({"scene": s.typology, "check": name, "ok": bool(ok) if ok is not None else None, "detail": detail})
        print(f"{'PASS' if ok else ('INFO' if ok is None else 'FAIL'):4}  {s.typology}: {name}: {detail}", flush=True)

    plain = s.run(root, "plain", "daylight", carve_fraction=0.7)
    cut = cutoff(plain)
    runs = {
        "neighbours": s.run(root, "neighbours", "daylight", context=s.neighbours, threshold=cut),
        "tall south": s.run(root, "tall_south", "daylight", context=s.tall_south, threshold=cut),
        "full": s.run(root, "full", "daylight", context=combined(s.neighbours, s.chimney, s.crown), terrain=s.terrain,
                      threshold=cut),
    }
    blockers = {"neighbours": s.neighbours, "tall south": s.tall_south,
                "full": combined(s.neighbours, s.chimney, s.crown, s.terrain)}

    # Occupancy of the full set against trimesh: point-in-mesh for the column rule, downward rays for the ground.
    full = runs["full"]
    occ0 = plain.occ
    R = occ0.shape[0]
    idx = np.stack(np.meshgrid(*[np.arange(R)] * 3, indexing="ij"), -1).reshape(-1, 3)
    centres = plain.origin + (idx + 0.5) * plain.vs
    inside = np.zeros(len(idx), bool)
    for body in list(s.neighbours.split(only_watertight=False)) + [s.chimney, s.crown]:
        lo, hi = body.bounds
        near = np.all((centres > lo) & (centres < hi), axis=1)
        if near.any():
            inside[near] |= body.contains(centres[near])
    inside = inside.reshape(occ0.shape)
    gx, gy = column_centres(plain)
    starts = np.stack([gx.ravel(), gy.ravel(), np.full(gx.size, 500.0)], 1)
    ground = np.full(gx.size, np.nan)
    loc, ray_i, _ = s.terrain.ray.intersects_location(starts, np.tile([0, 0, -1.0], (len(starts), 1)), multiple_hits=True)
    for i, z in zip(ray_i, loc[:, 2]):
        ground[i] = z if np.isnan(ground[i]) else max(ground[i], z)
    ground = ground.reshape(R, R)
    cz = plain.origin[2] + (np.arange(R) + 0.5) * plain.vs
    expected = occ0 & ~(inside.any(axis=2) & occ0.any(axis=2))[:, :, None]
    with np.errstate(invalid="ignore"):
        expected &= ~(cz[None, None, :] < ground[:, :, None] - 1e-3 * plain.vs)
    report = context_report(full)
    differ = int((expected != full.occ).sum())
    add("full: occupancy vs trimesh", differ == 0 and report["voxels_removed_below_ground"] > 0,
        f"{differ} voxels differ; removed by context {report['voxels_removed_by_context']}, "
        f"below ground {report['voxels_removed_below_ground']}")

    for name in ("neighbours", "full"):
        run, rep = runs[name], context_report(runs[name])
        o, n, d, pi, di = sky_rays(run)
        hit = np.isfinite(first_hits(blockers[name], o, n, d))
        add(f"{name}: rays dropped vs trimesh", abs(rep["rays_dropped"] - int(hit.sum())) <= 0.001 * len(o),
            f"engine {rep['rays_dropped']}, trimesh {int(hit.sum())} of {len(o)} (differences: exact edge grazes)")
        # The reference fed the rays the engine keeps (its own any-hit, as the engine runs it).
        from urbansolarcarver.context_geometry import build_blocking_mesh
        from urbansolarcarver.ray_tracing import mesh_blocks_rays
        frame = np.asarray(s.scene.volume.bounds[0])
        local = blockers[name].copy()
        local.vertices = np.round(local.vertices - frame, 6)
        blocking = build_blocking_mesh([local], torch.device("cpu"))
        dropped = mesh_blocks_rays(blocking, torch.tensor(o - frame, dtype=torch.float32), torch.tensor(d, dtype=torch.float32),
                                   torch.arange(len(o)), torch.tensor(n, dtype=torch.float32), RAY_LENGTH).numpy()
        ref = reference_scores(run, ~dropped)[run.occ]
        usc = run.scores[run.occ].astype(float)
        tol = 1e-4 * np.maximum(ref, usc) + 1e-9 * max(ref.max(), 1e-30)
        short = int(((ref - usc) > tol).sum())
        add(f"{name}: scores vs the CPU reference", short == 0,
            f"voxels short {short}; extra score {100 * (usc.sum() - ref.sum()) / ref.sum():.2f}% "
            f"(the reference's fixed steps miss corner clips)")

    kept0 = plain.mask.astype(bool)
    for name, run in runs.items():
        kept = run.mask.astype(bool)
        lost = kept0 & run.occ & ~kept
        removed = occ0 & ~run.occ
        rises = run.occ & (run.scores > plain.scores * (1 + 1e-5) + 1e-9)
        far = rises & ~ndi.binary_dilation(removed, structure=np.ones((3, 3, 3), bool))
        rep = context_report(run)
        add(f"{name}: same cutoff keeps a superset, no score rises", not lost.any() and not far.any(),
            f"kept {int(kept0.sum())} -> {int(kept.sum())} (+{int((kept & ~kept0).sum())}), lost {int(lost.sum())}; "
            f"rises {int(rises.sum())} ({int((rises & ~far).sum())} next to removed columns); rays dropped "
            f"{rep['rays_dropped']}/{rep['rays_total']}; score on the max volume "
            f"{100 * (1 - run.scores[run.occ].sum() / plain.scores[run.occ].sum()):.1f}% lower; "
            f"test points fully blocked {rep['test_points_fully_blocked']}")

    # A taller south neighbour keeps more, only on the south side, in daylight and in sun hours.
    tb_plain = s.run(root, "tb_plain", "time-based")
    pairs = {"daylight": (runs["neighbours"], runs["tall south"]),
             "sun hours 21 Dec": (s.run(root, "tb_neighbours", "time-based", context=s.neighbours),
                                  s.run(root, "tb_tall_south", "time-based", context=s.tall_south))}
    for label, (equal, tall) in pairs.items():
        extra = tall.mask.astype(bool) & ~equal.mask.astype(bool)
        lost = equal.mask.astype(bool) & ~tall.mask.astype(bool)
        y = plain.origin[1] + (np.argwhere(extra)[:, 1] + 0.5) * plain.vs if extra.any() else np.array([0.0])
        least = 0.9 if label.startswith("sun") else 0.5
        add(f"tall south vs neighbours, {label}", not lost.any() and extra.any() and (y < 0).mean() > least,
            f"+{int(extra.sum())} kept, {int(lost.sum())} lost; {100 * (y < 0).mean():.0f}% of the extra kept voxels on the "
            f"south half (y < 0; at least {100 * least:.0f}% expected)")
    del tb_plain

    # A context that blocks nothing (below everything, outside the grid columns): bit for bit.
    buried = s.run(root, "buried", "daylight", context=box((-300, -300, -50), (300, 300, -30)), carve_fraction=0.7)
    same = np.array_equal(plain.scores, buried.scores) and np.array_equal(plain.occ, buried.occ)
    add("context that blocks nothing: bit for bit", same and context_report(buried)["rays_dropped"] == 0,
        f"identical {same}, rays dropped {context_report(buried)['rays_dropped']}")

    # A canopy 150 m up: it blocks exactly the rays steep enough to reach it within the 200 m ray length.
    canopy = s.run(root, "canopy", "daylight", context=box((-2000, -2000, 150), (2000, 2000, 151)), carve_fraction=0.7)
    o, n, d, _pi, _di = sky_rays(canopy)
    reach = int(((150.0 - (o[:, 2] + 0.01 * n[:, 2])) / np.maximum(d[:, 2], 1e-12) <= RAY_LENGTH).sum())
    add("canopy within the ray length", context_report(canopy)["rays_dropped"] == reach,
        f"engine {context_report(canopy)['rays_dropped']}, rays that reach it {reach} of {len(o)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "runs" / "context_sanity"))
    ap.add_argument("--cases", default="courtyard,rows,lshape")
    args = ap.parse_args(argv)
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    results = []
    for typology in args.cases.split(","):
        check_scene(Scene(typology), root, results)
    (root / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    lines = ["# Context sanity checks", "", "| Scene | Check | Result | Detail |", "|---|---|---|---|"]
    lines += [f"| {r['scene']} | {r['check']} | {'pass' if r['ok'] else ('info' if r['ok'] is None else 'FAIL')} | {r['detail']} |"
              for r in results]
    (root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    failed = [r for r in results if r["ok"] is False]
    print(f"\n{len(results)} checks, {len(failed)} failed; {root / 'summary.md'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
