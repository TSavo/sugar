import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(
    "/workspace/sugar/implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py"
)

TARGETS = [
    ("numpy", "random/tests/test_random.py"),
    ("numpy", "random/tests/test_randomstate.py"),
    ("numpy", "tests/test_public_api.py"),
    ("pandas", "io/stata.py"),
    ("scipy", "optimize/tests/test__dual_annealing.py"),
    ("scipy", "sparse/csgraph/tests/test_shortest_path.py"),
    ("sklearn", "manifold/tests/test_t_sne.py"),
    ("sklearn", "utils/tests/test_sorting.py"),
    ("sklearn", "utils/tests/test_stats.py"),
]

REPEATS = 5
results = []


def run_one(rel, abspath):
    env = dict(os.environ)
    env["PYTHONFAULTHANDLER"] = "1"
    env.pop("SUGAR_KIT_MANIFEST", None)
    cmd = [sys.executable, str(SCRIPT), "--child-file", abspath, "--child-rel", rel]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, text=True, capture_output=True, timeout=30, env=env, check=False
        )
        elapsed = time.time() - t0
        out = proc.stdout.strip().splitlines()
        last_json = None
        for line in reversed(out):
            try:
                last_json = json.loads(line)
                break
            except Exception:
                continue
        signal_num = -proc.returncode if proc.returncode < 0 else None
        return {
            "file": rel,
            "elapsed_s": round(elapsed, 2),
            "returncode": proc.returncode,
            "signal": signal_num,
            "outcome": (last_json or {}).get("outcome"),
            "detail": (last_json or {}).get("mechanism")
            or (last_json or {}).get("reason"),
            "timed_out": False,
            "stderr_tail": proc.stderr[-500:] if proc.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return {
            "file": rel,
            "elapsed_s": round(elapsed, 2),
            "timed_out": True,
            "outcome": "timeout",
        }


for package, rel_suffix in TARGETS:
    spec = importlib.util.find_spec(package)
    root = Path(spec.origin).resolve().parent
    full_rel = f"{package}/{rel_suffix}"
    abspath = str(root / rel_suffix)
    for i in range(REPEATS):
        r = run_one(full_rel, abspath)
        r["repeat_index"] = i
        results.append(r)
        print(json.dumps(r), flush=True)

print("===FULL_RESULTS_JSON===")
print(json.dumps(results, indent=2))
