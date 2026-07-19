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

sk_spec = importlib.util.find_spec("sklearn")
sk_root = Path(sk_spec.origin).resolve().parent
sk_path = sk_root / "utils" / "tests" / "test_stats.py"
assert sk_path.exists(), sk_path

results = []


def run_one(with_manifest):
    env = dict(os.environ)
    env["PYTHONFAULTHANDLER"] = "1"
    if with_manifest:
        env["SUGAR_KIT_MANIFEST"] = manifest_path
    else:
        env.pop("SUGAR_KIT_MANIFEST", None)
    cmd = [sys.executable, str(SCRIPT), "--child-file", str(sk_path), "--child-rel", "sklearn/utils/tests/test_stats.py"]
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
            "with_manifest": with_manifest,
            "elapsed_s": round(elapsed, 2),
            "returncode": proc.returncode,
            "signal": signal_num,
            "outcome": (last_json or {}).get("outcome"),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return {"with_manifest": with_manifest, "elapsed_s": round(elapsed, 2), "timed_out": True}


for wm in (False, True):
    for i in range(3):
        r = run_one(wm)
        r["repeat_index"] = i
        results.append(r)

print(json.dumps(results, indent=2))
