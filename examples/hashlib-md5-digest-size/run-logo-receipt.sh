#!/usr/bin/env bash
# hashlib.md5 digest_size dual-assert logo receipt (CI ratchet).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
source "$REPO/scripts/showcase-terminal-identity.sh"
BIN="$("$REPO/bin/sugarbin" --profile release)"
export PYTHONPATH="$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$(dirname "$BIN"):${PATH:-}"
[ -x "$BIN" ] || { echo "FAIL: sugar missing"; exit 1; }
dir="$HERE/dual"
find "$dir" -maxdepth 1 -name 'blake3-512_*.proof' -delete 2>/dev/null || true
rm -rf "$dir/.sugar/runs" 2>/dev/null || true
(cd "$dir" && showcase_run_with_terminal sugar.mint "$BIN" mint --out .) >/dev/null || { echo "FAIL: mint"; exit 1; }
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
    print(f"  {r.get('status',''):14s} {str(r.get('property',''))[:60]:60s} {str(r.get('reason',''))[:120]}")
# The dual's call is not bridged: no proof in .sugar/imports answers it, so
# the call is an undecided member and prove owes it by name (#7836, #7839).
# Green means decided (#7849): neither half is decided on an owed call, and
# the verdict is not-decided.
verdict = obj.get("verdict")
owed = [r for r in rows if str(r.get("reason", "")).startswith("owed:")]
halves = {
    str(r.get("property", "")): str(r.get("status", ""))
    for r in rows
    if str(r.get("property", "")) in ("consistency:test_true", "consistency:test_lie")
}
fail = []
if verdict != "not-decided":
    fail.append(f"verdict {verdict!r}, expected 'not-decided'")
if not owed or not obj.get("owed"):
    fail.append("no owed row: the unbridged call must be owed by name")
for half in ("consistency:test_true", "consistency:test_lie"):
    status = halves.get(half)
    if status not in ("refused", "undecidable"):
        fail.append(f"{half}: {status or 'no row'}, expected not decided (refused or undecidable)")
if fail:
    for line in fail:
        print(f"FAIL: {line}")
    sys.exit(1)
print(f"==== hashlib-md5-digest-size logo: PASS (not-decided; {len(owed)} owed) ====")
INNER
[ -z "${SHOWCASE_SUBJECT_WITNESS:-}" ] || printf '%s\n' "${SHOWCASE_SUBJECT_ID:?}" > "$SHOWCASE_SUBJECT_WITNESS"
