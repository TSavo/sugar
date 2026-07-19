import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "corpus_fatal_triage.py"
manifest_path = str(
    SCRIPT.resolve().parent.parent / "kit_manifests" / "numpy_families_5907.json"
)
assert Path(manifest_path).exists(), manifest_path

# Files that flipped outcome between no-manifest and with-manifest in the
# first pass, or crashed outright. Rerun each config 3x to check determinism.
TARGETS = [
    ("pandas", "tests/frame/test_reductions.py"),
    ("pandas", "tests/indexes/test_old_base.py"),
    ("pandas", "tests/io/test_parquet.py"),
    ("pandas", "tests/copy_view/test_indexing.py"),
    ("numpy", "_core/tests/test_defchararray.py"),
    ("numpy", "_core/tests/test_einsum.py"),
    ("numpy", "_core/tests/test_mem_overlap.py"),
    ("numpy", "_core/tests/test_datetime.py"),
]

REPEATS = 3
results = []


def run_one(rel, abspath, with_manifest):
    env = dict(os.environ)
    env["PYTHONFAULTHANDLER"] = "1"
    if with_manifest:
        env["SUGAR_KIT_MANIFEST"] = manifest_path
    else:
        env.pop("SUGAR_KIT_MANIFEST", None)
    cmd = [sys.executable, str(SCRIPT), "--child-file", abspath, "--child-rel", rel]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=30, env=env, check=False)
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
            "with_manifest": with_manifest,
            "elapsed_s": round(elapsed, 2),
            "returncode": proc.returncode,
            "signal": signal_num,
            "outcome": (last_json or {}).get("outcome"),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return {
            "file": rel,
            "with_manifest": with_manifest,
            "elapsed_s": round(elapsed, 2),
            "timed_out": True,
        }


for package, rel_suffix in TARGETS:
    spec = importlib.util.find_spec(package)
    root = Path(spec.origin).resolve().parent
    full_rel = f"{package}/{rel_suffix}"
    abspath = str(root / rel_suffix)
    for wm in (False, True):
        for i in range(REPEATS):
            r = run_one(full_rel, abspath, wm)
            r["repeat_index"] = i
            results.append(r)

print(json.dumps(results, indent=2))
