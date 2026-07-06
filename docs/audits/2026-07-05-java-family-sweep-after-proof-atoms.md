# Java Family Sweep After Proof-Atom Derive

Base: `0783399e8` (`origin/main` after the Java proof-atom derive reader and subsequent Python-only register/pandas merges).

Command:

```sh
python3 - <<'PY'
import json, pathlib, sys, time
root = pathlib.Path.cwd()
sys.path.insert(0, str(root / "tools"))
import examples_gate
scripts = sorted(p.relative_to(root).as_posix() for p in (root / "examples").glob("java-*/run.sh"))
rows = [
    examples_gate.run_script(
        root=root,
        script=script,
        index=index,
        total=len(scripts),
        log_dir=pathlib.Path(".out/java-family-sweep-logs"),
        timeout_seconds=3600,
        nice=10,
        output=sys.stdout,
    )
    for index, script in enumerate(scripts, start=1)
]
pathlib.Path(".out/java-family-sweep-summary.json").write_text(json.dumps({
    "version": 1,
    "suite": "java-family-sweep",
    "root": str(root),
    "generated_at_unix": int(time.time()),
    "examples": rows,
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
```

Summary: 23 Java examples; 2 GREEN; 21 NAMED_RED. The remaining red bucket is `prove-output/empty-json-receipt`.

## Movement Table

| example | baseline | observed | movement |
| --- | --- | --- | --- |
| `examples/java-abs-bound/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-abs-flagship/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-abs-model/run.sh` | `missing-universe-atom/int32-eq-bv-expr` | `GREEN` | red -> green |
| `examples/java-abs-universe/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-assertion-consistency/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-b64-strong/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-b64-tails/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-bound-federation/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-callbind-consistency/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-codec-universe/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-commons-codec-crc32/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-crc32-universe/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-crc32-valuepin/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-forall-loop/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-instance-universe/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-mt-reference/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-mt-strong/run.sh` | `GREEN` | `GREEN` | still green |
| `examples/java-panama-bridge/run.sh` | `kit-transform/callsite-line-null` | `prove-output/empty-json-receipt` | changed red |
| `examples/java-pattern-regex/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-testng-consistency/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-urlsafe-seam/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-voltron/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |
| `examples/java-witness-recompute/run.sh` | `prove-output/empty-json-receipt` | `prove-output/empty-json-receipt` | same red |

## Moved Rows

`java-abs-model` now reaches green through the typed proof-graph atom reader:

```text
minted .proof carries 3 int32.eq-bv-expr universe row(s) (walked from Math.java).
PASS[from-proof]: derived -2147483648 reading directly from the minted .proof.
java-abs-model showcase: PASS
```

The sweep also found stale example plumbing in this row: the script checked
`sugar derive --from-proof ... | grep -q` under `set -o pipefail`, so a
successful early `grep -q` could turn into a false failure if the producer saw
SIGPIPE. The script now captures the output first, then checks it.

`java-panama-bridge` moved past the previous `kit-transform/callsite-line-null` layer into the same proof-output family as the other red Java examples:

```text
contract-row: decoded_len_estimate#euf#c:callresult_decoded_len_estimate_a1(i:4)::assertion present in minimal proof
examples/java-panama-bridge/native-contract/.verify.json: expected JSON receipt, got non-JSON output: <empty output>
```

Direct probe of the `prove-output/empty-json-receipt` class showed the current underlying failure is before JSON emission:

```text
error: Java workspace detected at src/test/java/demo/AbsBoundBadTest.java, but no Sugar Java kit component claimed it.
Try: apt install sugar-kit-java, then try again.
```

That is the next Java family layer; this sweep only ratchets the rows exposed by the proof-atom derive change.
