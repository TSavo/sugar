import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "corpus_fatal_triage.py"

TARGETS = {
    "numpy": [
        "_core/tests/test_cpu_features.py",
        "_core/tests/test_defchararray.py",
        "_core/tests/test_einsum.py",
        "_core/tests/test_mem_overlap.py",
        "ma/core.py",
        "_core/tests/test_datetime.py",
    ],
    "pandas": [
        "tests/frame/test_reductions.py",
        "tests/indexes/test_old_base.py",
        "tests/indexing/test_partial.py",
        "tests/io/excel/test_openpyxl.py",
        "tests/io/test_parquet.py",
        "tests/copy_view/test_indexing.py",
        "tests/frame/methods/test_diff.py",
        "tests/frame/test_nonunique_indexes.py",
        "tests/frame/test_stack_unstack.py",
        "tests/frame/test_subclass.py",
    ],
}

manifest_path = str(
    SCRIPT.resolve().parent.parent / "kit_manifests" / "numpy_families_5907.json"
)
assert Path(manifest_path).exists(), f"manifest not found at {manifest_path}"

results = []


def run_one(rel, abspath, with_manifest):
    env = dict(os.environ)
    env["PYTHONFAULTHANDLER"] = "1"
    if with_manifest and manifest_path:
        env["SUGAR_KIT_MANIFEST"] = manifest_path
    else:
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
            "with_manifest": with_manifest,
            "elapsed_s": round(elapsed, 2),
            "returncode": proc.returncode,
            "signal": signal_num,
            "outcome": (last_json or {}).get("outcome"),
            "stderr_tail": proc.stderr[-1500:],
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


for package, rels in TARGETS.items():
    spec = importlib.util.find_spec(package)
    root = Path(spec.origin).resolve().parent
    for rel in rels:
        abspath = str(root / rel)
        full_rel = f"{package}/{rel}"
        if not (root / rel).exists():
            results.append(
                {"file": full_rel, "error": "file not found in installed package"}
            )
            continue
        for wm in (False, True):
            results.append(run_one(full_rel, abspath, wm))

sk_spec = importlib.util.find_spec("sklearn")
if sk_spec and sk_spec.origin:
    sk_root = Path(sk_spec.origin).resolve().parent
    sk_path = sk_root / "utils" / "tests" / "test_stats.py"
    if sk_path.exists():
        for wm in (False, True):
            results.append(
                run_one("sklearn/utils/tests/test_stats.py", str(sk_path), wm)
            )
    else:
        results.append(
            {
                "file": "sklearn/utils/tests/test_stats.py",
                "error": "not found under sklearn root",
            }
        )
else:
    results.append(
        {"file": "sklearn/utils/tests/test_stats.py", "error": "sklearn not installed"}
    )

print(json.dumps(results, indent=2))
