"""Hypothesis test: does distributed ground CLUTTER (distinct objects) improve VIO
data-association in a landmark-sparse, ground-dominated scene -- more than ground texture?

Holds terrain + ground (patchy) CONSTANT, varies only PLACEMENT density, and benchmarks
each config with vio_bench at a ground-dominated pose (low AGL, steep down-pitch so the
frame is mostly ground). Predicts: `bare` starves (few inliers, ALIASING/MARGINAL);
scattered rocks/clutter lift `inliers/pair` toward GOOD. Also validates that vio_bench
detects the failure AND the fix. Run in wildseed:egl:  python3 tools/vio_clutter_exp.py
"""
import json
import os
import subprocess

WS = os.environ.get("WS", os.getcwd())
CLI = ["python3", "-m", "wildseed.cli.main"]
FR = os.path.join(WS, "frames")

# Realistic drone pose (agl 12, gentle down-pitch) -- a WIDE footprint so scattered
# landmarks actually fall in view (a steep low pose sees only a ~15 m ground patch, too
# small for the pipeline's sparse scatter, so nothing appears). bare uses EXPLICIT zeros
# (empty {} silently falls back to DEFAULT density). Tests whether distinct landmarks add
# confident matches over bare de-tiled ground.
POSE = ["--region", "full", "--agl", "12", "--pitch", "0.35",
        "--step", "0.5", "--yaw-amp-deg", "4", "--frames", "12"]
CONFIGS = [
    ("bare", {"tree": 0, "rock": 0, "bush": 0, "grass": 0, "sand": 0}),
    ("trees", {"tree": 60, "rock": 0, "bush": 0, "grass": 0, "sand": 0}),
    ("full", {"tree": 60, "rock": 42, "bush": 100, "grass": 150, "sand": 0}),
]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        print("ERR", " ".join(cmd[:6]), (r.stderr or "")[-300:], flush=True)
    return r


# build terrain + a constant patchy ground ONCE
run(CLI + ["terraingen", "--preset", "hilly", "--seed", "3", "--amplitude", "12",
           "--feature", "140", "--size", "192", "--pixel", "1.6", "-o", "dem/synth.tif"])
run(CLI + ["terrain", "--dem", "dem/synth.tif"])
run(CLI + ["ground", "--mode", "patchy", "--biome", "desert", "--seed", "7", "--res", "4096"])

rows = []
for tag, dens in CONFIGS:
    print(f"=== config={tag} density={dens} ===", flush=True)
    run(CLI + ["generate", "--density", json.dumps(dens), "--seed", "7"])
    run(["python3", f"{WS}/tools/vio_bench.py", "--tag", f"clutter_{tag}", "--viz"] + POSE)
    jp = f"{FR}/vio_bench_clutter_{tag}.json"
    if os.path.exists(jp):
        m = json.load(open(jp))["results"][0]
        m["config"] = tag
        rows.append(m)

print("\n==== ground clutter vs VIO data-association (ground-dominated pose) ====")
print("| config | ORB/fr | ratio_reject | inlier_ratio | inliers/pair | self_amb | verdict |")
print("|--------|--------|--------------|--------------|--------------|----------|---------|")
for m in rows:
    print(f"| {m['config']:<6} | {m['orb_per_frame']:6.0f} | {m['ratio_reject']:12.2f} | "
          f"{m['inlier_ratio']:12.2f} | {m['inliers_per_pair']:12.0f} | "
          f"{m['self_ambiguity']:8.2f} | {m['verdict']} |")
json.dump(rows, open(f"{FR}/vio_clutter_summary.json", "w"), indent=2)
print("\nwrote frames/vio_clutter_summary.json")
