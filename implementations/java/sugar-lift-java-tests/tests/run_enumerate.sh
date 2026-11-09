#!/usr/bin/env bash
# Unit tests for the sugar.enumerate door of JavaTestAssertionsRpc.
#
# lift and mint are enumeration clients (sugar-cli lift_plugin.rs
# `dispatch_lift_path` -> sugar-compiler tree.rs `fold_enumerate_source_tree`):
# the CLI never sends method `lift`; it folds
#   source_files -> parameter-contract-link-units -> universe(at = file memento)
# into the ir-document. These tests drive that exact sequence over JSON-RPC and
# hold the kit to the protocol shape AND to parity with the single-shot `lift`
# door (same contract rows, same named gaps).
#
# Test suite (E — enumerate):
#   E1. kit_declaration advertises sugar.enumerate; the retired `lift` is gone
#   E2. source_files: one node per *.java under the workspace, sorted, each a
#       degenerate source-memento sealed by a blake3-512 CID; zero gaps
#   E3. parameter-contract-link-units -> {"rows": []}
#   E4. universe per census member: audit rows are the IR contract rows; the
#       fold over every member equals the `lift` ir (set parity) and the
#       int32.eq-bv-expr universe atom walked from vendor Math.java is present
#   E5. gaps carry {memento.file, memento.function_name = item, reason} so the
#       fold's diagnostics {path, reason, item} match the `lift` diagnostics
#   E6. refusals: unowned level -> JSON-RPC error -32602 (never an empty
#       census); universe before a census -> named gap; universe at a
#       non-member -> named gap; universe at a stale CID -> named gap
set -euo pipefail

command -v javac >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java  >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$(cd "$HERE/.." && pwd)"
OUT="$KIT/out"
FIXTURES="$HERE/fixtures"

echo "== build kit =="
bash "$KIT/build.sh" "$OUT" >/dev/null 2>&1

JAVA_CMD="java \
  --add-exports jdk.compiler/com.sun.source.tree=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.source.util=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED \
  -cp $OUT JavaTestAssertionsRpc"

# Drive the kit the way the CLI fold does. The universe demands need the
# census answer first (its mementos are the `at` keys), so this runs TWO kit
# processes: one to learn the census, one to replay the whole fold plus the
# `lift` door for parity. Both are the same kit binary over the same tree.
WORKSPACE="$FIXTURES/numeric-universe"

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST E1/E2/E3: declaration advertises enumerate; source_files census; link units"
echo "────────────────────────────────────────────────────────────────"
CENSUS="$(python3 - "$WORKSPACE" <<'PY' | eval "$JAVA_CMD" 2>/dev/null
import json, sys
root = sys.argv[1]
print(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}))
print(json.dumps({"jsonrpc":"2.0","id":2,"method":"sugar.plugin.kit_declaration","params":{}}))
print(json.dumps({"jsonrpc":"2.0","id":3,"method":"sugar.enumerate","params":{
    "level":"source_files","at":None,"seek":False,"workspace_root":root,
    "options":{"auditFrontier":False}}}))
print(json.dumps({"jsonrpc":"2.0","id":4,"method":"sugar.enumerate","params":{
    "level":"parameter-contract-link-units","workspace_root":root}}))
print(json.dumps({"jsonrpc":"2.0","id":5,"method":"shutdown","params":{}}))
PY
)"
python3 - "$CENSUS" "$WORKSPACE" <<'PY'
import json, os, re, sys
lines = [json.loads(l) for l in sys.argv[1].strip().split('\n') if l.strip()]
by_id = {m["id"]: m for m in lines}
root = sys.argv[2]

# E1: the declaration is the capability advertisement the CLI reads
# (`Kit::supports_rpc_method("sugar.enumerate")`); `lift` is retired.
decl = by_id[2]["result"]
names = {m["name"] for m in decl["rpc"]["methods"]}
assert "sugar.enumerate" in names, f"declaration must advertise sugar.enumerate: {sorted(names)}"
assert "lift" not in names, f"retired `lift` must not be advertised: {sorted(names)}"
required = {m["name"] for m in decl["rpc"]["methods"] if m.get("required")}
assert "sugar.enumerate" in required, "sugar.enumerate must be a required method"
print("PASS E1: declaration advertises sugar.enumerate (required) and retires lift")

# E2: the census is every *.java under the workspace (vendor trees included,
# exactly what the single-shot lift walked with source_paths ["."]).
census = by_id[3]["result"]
assert census["gaps"] == [], f"source census must have zero gaps: {census['gaps']}"
expected = []
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d not in {".sugar", "target", "build", ".git"}]
    for f in filenames:
        if f.endswith(".java"):
            expected.append(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/"))
expected.sort()
files = [n["memento"]["file"] for n in census["nodes"]]
assert files == expected, f"census must list every *.java sorted:\n got {files}\n want {expected}"
assert "NumericUniverseLift.java" in files and "vendor/jdk21/java/lang/Math.java" in files
cid_re = re.compile(r"^blake3-512:[0-9a-f]{128}$")
for n in census["nodes"]:
    m = n["memento"]
    assert m["kind"] == "source-memento", m
    assert m["function_name"] == "" and m["span"] is None and m["param_names"] == [], m
    assert cid_re.match(m["source_cid"] or ""), f"census memento must be sealed by a blake3-512 CID: {m}"
    assert m["template_cid"] is None, m
    assert n["audit"] is None and n["payload"] is None, n
print(f"PASS E2: source_files census = {len(files)} sealed file mementos, zero gaps")

# E3: this kit links no parameter contracts; the preconstruction row set is empty.
assert by_id[4]["result"] == {"rows": []}, by_id[4]
print("PASS E3: parameter-contract-link-units -> {rows: []}")

json.dump(census["nodes"], open(os.environ.get("CENSUS_OUT", "/dev/null"), "w"))
PY

CENSUS_JSON="$(mktemp)"
trap 'rm -f "$CENSUS_JSON"' EXIT
CENSUS_OUT="$CENSUS_JSON" python3 - "$CENSUS" <<'PY'
import json, os, sys
lines = [json.loads(l) for l in sys.argv[1].strip().split('\n') if l.strip()]
census = next(m for m in lines if m["id"] == 3)["result"]
json.dump(census["nodes"], open(os.environ["CENSUS_OUT"], "w"))
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST E4/E5/E6: universe fold == lift (parity); gap shape; refusals"
echo "────────────────────────────────────────────────────────────────"
FOLD="$(python3 - "$WORKSPACE" "$CENSUS_JSON" <<'PY' | eval "$JAVA_CMD" 2>/dev/null
import json, sys
root, census_path = sys.argv[1], sys.argv[2]
nodes = json.load(open(census_path))
msg_id = 1
def send(method, params):
    global msg_id
    print(json.dumps({"jsonrpc":"2.0","id":msg_id,"method":method,"params":params}))
    msg_id += 1
send("initialize", {})
# E6a: universe BEFORE any census in this process -> named gap, not a lift.
send("sugar.enumerate", {"level":"universe","at":nodes[0]["memento"],"seek":False,
                         "workspace_root":root,"options":{"auditFrontier":False}})
# E6b: an unowned level -> JSON-RPC error.
send("sugar.enumerate", {"level":"functions","at":None,"seek":False,
                         "workspace_root":root,"options":{"auditFrontier":False}})
# The fold proper: census, link units, one universe demand per member.
send("sugar.enumerate", {"level":"source_files","at":None,"seek":False,
                         "workspace_root":root,"options":{"auditFrontier":False}})
send("sugar.enumerate", {"level":"parameter-contract-link-units","workspace_root":root})
for n in nodes:
    send("sugar.enumerate", {"level":"universe","at":n["memento"],"seek":False,
                             "workspace_root":root,
                             "options":{"auditFrontier":False,"resolvedContinuationMementos":[]}})
# E6c: a non-member; E6d: a member at a stale CID.
send("sugar.enumerate", {"level":"universe","at":{"kind":"source-memento","file":"NotInCensus.java"},
                         "seek":False,"workspace_root":root,"options":{}})
stale = dict(nodes[0]["memento"]); stale["source_cid"] = "blake3-512:" + "0"*128
send("sugar.enumerate", {"level":"universe","at":stale,"seek":False,"workspace_root":root,"options":{}})
# Parity oracle: the single-shot lift over the same tree.
send("lift", {"workspace_root":root,"source_paths":["."]})
send("shutdown", {})
PY
)"
python3 - "$FOLD" "$CENSUS_JSON" <<'PY'
import json, sys
lines = [json.loads(l) for l in sys.argv[1].strip().split('\n') if l.strip()]
nodes = json.load(open(sys.argv[2]))
by_id = {m["id"]: m for m in lines}
n_files = len(nodes)

# E6a: universe before census -> gap naming the missing census, zero nodes.
pre = by_id[2]["result"]
assert pre["nodes"] == [], pre
assert len(pre["gaps"]) == 1 and "prepared source_files census" in pre["gaps"][0]["reason"], pre
print("PASS E6a: universe before a census -> named gap, zero nodes")

# E6b: unowned level -> error -32602 (a false zero would be nodes: []).
err = by_id[3]
assert "error" in err and err["error"]["code"] == -32602, err
assert "not served" in err["error"]["message"] and "false zero" in err["error"]["message"], err
print("PASS E6b: unowned level 'functions' -> JSON-RPC error -32602, not an empty census")

census = by_id[4]["result"]
assert [n["memento"] for n in census["nodes"]] == [n["memento"] for n in nodes], "census must be stable across processes"
assert by_id[5]["result"] == {"rows": []}

# E4: fold the universe demands exactly as tree.rs does.
ir, diags = [], []
first_universe_id = 6
for i, n in enumerate(nodes):
    reply = by_id[first_universe_id + i]
    assert "result" in reply, reply
    res = reply["result"]
    for node in res["nodes"]:
        assert node["memento"] == n["memento"], f"universe node must carry the sealed file memento: {node['memento']} vs {n['memento']}"
        assert node["payload"] is None, node
        audit = node["audit"]
        assert isinstance(audit, dict) and audit.get("kind") == "contract", f"audit must be an IR contract row: {audit}"
        ir.append(audit)
    for gap in res["gaps"]:
        m = gap["memento"]
        assert m is not None and m["file"], f"gap memento must name a file: {gap}"
        diags.append({"path": m["file"], "reason": gap["reason"], "item": m["function_name"] or None})
universe_rows = [c for c in ir if json.dumps(c).find("int32.eq-bv-expr") >= 0]
assert universe_rows, "fold must carry the int32.eq-bv-expr universe atom walked from vendor Math.java"

lift = by_id[first_universe_id + n_files + 2]["result"]
assert lift["kind"] == "ir-document"
def key(c): return json.dumps(c, sort_keys=True)
fold_set, lift_set = {key(c) for c in ir}, {key(c) for c in lift["ir"]}
assert fold_set == lift_set, (
    "universe fold must equal the single-shot lift ir:\n"
    f" only in fold: {sorted(fold_set - lift_set)[:3]}\n only in lift: {sorted(lift_set - fold_set)[:3]}")
assert len(ir) == len(lift["ir"]), f"row count: fold {len(ir)} vs lift {len(lift['ir'])}"
print(f"PASS E4: universe fold over {n_files} members == lift ir ({len(ir)} rows, {len(universe_rows)} int32.eq-bv-expr)")

# E5: every lift-gap the single-shot door reported reaches the fold as a gap
# with the same (path, reason, item) triple; nothing extra is invented.
def triple(d): return (d.get("path"), d.get("reason"), d.get("item"))
lift_triples = {triple(d) for d in lift["diagnostics"] if d.get("kind") == "lift-gap"}
fold_triples = {triple(d) for d in diags}
assert lift_triples <= fold_triples, f"lift gaps missing from fold: {sorted(lift_triples - fold_triples)[:3]}"
assert fold_triples <= lift_triples, f"fold invented gaps: {sorted(fold_triples - lift_triples)[:3]}"
print(f"PASS E5: {len(fold_triples)} gaps carry (path, reason, item) in parity with lift diagnostics")

# E6c/E6d: non-member and stale identity are named gaps, not lifts.
non_member = by_id[first_universe_id + n_files]["result"]
assert non_member["nodes"] == [] and "not a member of the sealed source_files census" in non_member["gaps"][0]["reason"], non_member
stale = by_id[first_universe_id + n_files + 1]["result"]
assert stale["nodes"] == [] and "does not match the sealed source_files identity" in stale["gaps"][0]["reason"], stale
print("PASS E6c/E6d: non-member and stale-CID universe demands -> named gaps, zero nodes")
PY

echo
echo "== all enumerate tests PASS (E1-E6) =="
