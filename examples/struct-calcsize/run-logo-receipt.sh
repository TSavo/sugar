#!/usr/bin/env bash
# struct.calcsize dual-assert logo receipt (CI ratchet).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
if [ -x "$REPO/implementations/rust/target/release/sugar" ]; then
  BIN="$REPO/implementations/rust/target/release/sugar"
else
  BIN="$("$REPO/bin/sugarbin" --profile release)"
fi
export PYTHONPATH="$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$(dirname "$BIN"):${PATH:-}"
[ -x "$BIN" ] || { echo "FAIL: sugar missing"; exit 1; }
dir="$HERE/dual"
find "$dir" -maxdepth 1 -name 'blake3-512_*.proof' -delete 2>/dev/null || true
rm -rf "$dir/.sugar/runs" 2>/dev/null || true
(cd "$dir" && "$BIN" mint --out .) >/dev/null || { echo "FAIL: mint"; exit 1; }
(cd "$dir" && "$BIN" prove --allow-failed-components --json .) >"$dir/.prove.raw" 2>"$dir/.prove.err" || true
python3 - "$dir/.prove.raw" <<'INNER' || exit 1
import json, re, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
text = re.sub(r"\x1b\[[0-9;]*m", "", text)
dec = json.JSONDecoder()
obj = None
for i, ch in enumerate(text):
    if ch != "{":
        continue
    try:
        o, _ = dec.raw_decode(text[i:])
    except Exception:
        continue
    if isinstance(o, dict) and "rows" in o:
        obj = o
        break
if not obj:
    print("FAIL: no prove JSON")
    sys.exit(1)
rows = obj.get("rows") or []
print("rows:")
for r in rows:
    print(f"  {r.get('status',''):14s} {str(r.get('property',''))[:100]}")
statuses = {str(r.get("status", "")) for r in rows}
if "unsatisfied" not in statuses and not (statuses & {"unsat", "contradictory", "inconsistent"}):
    print(f"FAIL: expected dual unsatisfied, got {sorted(statuses)}")
    sys.exit(1)
print("==== struct-calcsize logo: PASS (dual unsatisfied) ====")
INNER
