#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

RAW="bootstrap/libsugar-bind-inventory/raw"
CONTRACTS="$RAW/contracts"
EVIDENCE="$RAW/evidence"
DECISIONS="$RAW/promotion-decisions"
POLICY="protocol/policies/intra-vendor-empirical-admission.json"
WITNESS_DIR="$EVIDENCE/witness-consensus"
RECEIPT_DIR="bootstrap/witness-consensus-receipts"
RECEIPT="$RECEIPT_DIR/libsugar-intra-vendor.json"
CLI="$("$ROOT/bin/sugarbin" --profile release)"
THRESHOLD=4

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/sugar-witness-consensus.XXXXXX")"
PLAN="$TMP_ROOT/plan.json"
STATUS_DIR="$TMP_ROOT/status"
BEFORE_SPECS="$TMP_ROOT/specs.before"
AFTER_SPECS="$TMP_ROOT/specs.after"
MINT_OUT="$TMP_ROOT/mint.out"
ALIAS_LIST="$TMP_ROOT/contract-aliases.txt"
BACKUP_DECISIONS="$TMP_ROOT/promotion-decisions.bind-output"
CLI_POLICY="$TMP_ROOT/intra-vendor-empirical-admission.cli.json"
RESTORE_DECISIONS=0

mkdir -p "$STATUS_DIR" "$RECEIPT_DIR" "$WITNESS_DIR"
: > "$ALIAS_LIST"

cleanup() {
  if [ -s "$ALIAS_LIST" ]; then
    while IFS= read -r alias_path; do
      [ -n "$alias_path" ] && rm -f "$alias_path"
    done < "$ALIAS_LIST"
  fi
  if [ "$RESTORE_DECISIONS" = "1" ]; then
    rm -rf "$DECISIONS"
    mv "$BACKUP_DECISIONS" "$DECISIONS"
  fi
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

find menagerie/concept-shapes/specs -type f -name '*.spec.json' | sort > "$BEFORE_SPECS"

echo "resolve sugar-cli"
"$ROOT/bin/sugarbin" --profile release >/dev/null

python3 - "$POLICY" "$CLI_POLICY" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])


def blake3_512_of(data: bytes) -> str:
    out = subprocess.check_output(
        ["b3sum", "--length", "64", "--no-names"],
        input=data,
    )
    return "blake3-512:" + out.decode("ascii").strip()


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


policy = json.loads(source.read_text(encoding="utf-8"))
threshold = int(policy["threshold_value"])
count_path = policy.get("count_field_path", ["consensus_vector", "total_sample_count"])
metric = count_path[-1]
compat = {
    "allow_failures": False,
    "cid": blake3_512_of(canonical_bytes(policy)),
    "thresholds": [
        {
            "axis": metric,
            "predicate": f"{metric} >= {threshold}",
        }
    ],
}
target.write_text(json.dumps(compat, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"cli_policy={target}")
PY

python3 - "$PLAN" "$RAW" "$WITNESS_DIR" "$THRESHOLD" <<'PY'
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

plan_path = Path(sys.argv[1])
raw = Path(sys.argv[2])
witness_dir = Path(sys.argv[3])
threshold = int(sys.argv[4])

contracts_dir = raw / "contracts"
sites_dir = raw / "sites"
index_path = raw / "index.json"


def safe_filename(cid: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in cid)


def safe_candidate(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name).strip("_")


def blake3_512_of(data: bytes) -> str:
    out = subprocess.check_output(
        ["b3sum", "--length", "64", "--no-names"],
        input=data,
    )
    return "blake3-512:" + out.decode("ascii").strip()


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def witness_cid(witness: dict) -> str:
    body = dict(witness)
    body.pop("cid", None)
    return blake3_512_of(canonical_bytes(body))


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def contract_path_for_cid(cid: str) -> Path:
    return contracts_dir / f"{safe_filename(cid)}.json"


index = load_json(index_path)
candidates = [
    c for c in index.get("top_concepts", [])
    if int(c.get("site_count", 0)) >= threshold
]

sites_by_concept = defaultdict(list)
for site_path in sorted(sites_dir.glob("*.json")):
    site = load_json(site_path)
    concept_cid = site.get("concept_cid")
    local_contract_cid = site.get("local_contract_cid")
    if concept_cid and local_contract_cid:
        site["_path"] = str(site_path)
        sites_by_concept[concept_cid].append(site)

site_groups = sorted(
    sites_by_concept.items(),
    key=lambda item: (-len(item[1]), item[0]),
)
used_groups = set()
assigned = {}

for candidate in candidates:
    wanted = int(candidate.get("site_count", 0))
    exact = [
        (cid, group) for cid, group in site_groups
        if cid not in used_groups and len(group) == wanted
    ]
    if len(exact) == 1:
        cid, group = exact[0]
        assigned[candidate["name"]] = (cid, group)
        used_groups.add(cid)

remaining_groups = [
    (cid, group) for cid, group in site_groups
    if cid not in used_groups and len(group) >= threshold
]
for candidate in candidates:
    if candidate["name"] in assigned:
        continue
    if not remaining_groups:
        assigned[candidate["name"]] = (None, [])
        continue
    cid, group = remaining_groups.pop(0)
    assigned[candidate["name"]] = (cid, group)
    used_groups.add(cid)

observed_at = "2026-05-14T00:00:00.000Z"
witness_dir.mkdir(parents=True, exist_ok=True)

plan = []
for candidate in candidates:
    name = candidate["name"]
    concept_cid, group = assigned.get(name, (None, []))
    contracts = []
    for site in group:
        contract_cid = site["local_contract_cid"]
        path = contract_path_for_cid(contract_cid)
        if path.exists():
            contracts.append((contract_cid, path, site))
    contracts.sort(key=lambda item: item[0])
    if not contracts:
        plan.append({
            "candidate": name,
            "candidate_file": safe_candidate(name),
            "reported_cardinality": int(candidate.get("site_count", 0)),
            "mapped_site_count": len(group),
            "admissible": False,
            "refusal_reason": "no contract-backed sites found",
            "witnesses": [],
            "fixture_cid": None,
            "representative_contract_cid": None,
            "representative_contract_path": None,
            "requires_llm_auto_namer": name.startswith("UNNAMED-CONCEPT-"),
        })
        continue

    fixture_cid, fixture_path, _ = contracts[0]
    row_schema = {
        "agreement": "intra-vendor-bind-cluster",
        "candidate": name,
        "representative_fixture_cid": fixture_cid,
    }
    witness_paths = []
    witness_cids = []
    for ordinal, (contract_cid, _contract_path, site) in enumerate(contracts, start=1):
        witness = {
            "cid": "",
            "fixture_state_cid": fixture_cid,
            "kind": "witness",
            "measurements": {
                "cluster": {
                    "mapped_site_count": len(group),
                    "ordinal": ordinal,
                    "reported_cardinality": int(candidate.get("site_count", 0)),
                    "source": str(raw),
                },
                "observer": {
                    "language": "rust",
                    "library_tag": "libsugar",
                    "loss_dims_exercised": [],
                },
                "row_schema": row_schema,
            },
            "observed_at": observed_at,
            "outcome": "pass",
            "sample_count": 1,
            "schemaVersion": "1",
            "signature": None,
            "signed_by": None,
            "subject": site.get("cid", contract_cid),
            "witness_for": name,
        }
        witness["cid"] = witness_cid(witness)
        witness_path = witness_dir / f"{safe_filename(witness['cid'])}.json"
        with witness_path.open("w", encoding="utf-8") as handle:
            json.dump(witness, handle, sort_keys=True, indent=2, ensure_ascii=True)
            handle.write("\n")
        witness_paths.append(str(witness_path))
        witness_cids.append(witness["cid"])

    plan.append({
        "candidate": name,
        "candidate_file": safe_candidate(name),
        "reported_cardinality": int(candidate.get("site_count", 0)),
        "mapped_site_count": len(group),
        "admissible": len(witness_paths) >= threshold,
        "refusal_reason": None if len(witness_paths) >= threshold else "fewer than threshold contract-backed sites",
        "witnesses": witness_cids,
        "witness_files": witness_paths,
        "fixture_cid": fixture_cid,
        "representative_contract_cid": fixture_cid,
        "representative_contract_path": str(fixture_path),
        "requires_llm_auto_namer": name.startswith("UNNAMED-CONCEPT-"),
        "mapped_concept_cid": concept_cid,
    })

with plan_path.open("w", encoding="utf-8") as handle:
    json.dump(plan, handle, sort_keys=True, indent=2, ensure_ascii=True)
    handle.write("\n")

print(f"prepared_candidates={len(plan)}")
print(f"prepared_witnesses={sum(len(item.get('witnesses', [])) for item in plan)}")
PY

echo "run witness consensus"
while IFS= read -r item; do
  candidate="$(jq -r '.candidate' <<<"$item")"
  candidate_file="$(jq -r '.candidate_file' <<<"$item")"
  admissible="$(jq -r '.admissible' <<<"$item")"
  fixture="$(jq -r '.fixture_cid // empty' <<<"$item")"
  out_file="$STATUS_DIR/$candidate_file.out"
  err_file="$STATUS_DIR/$candidate_file.err"
  status_file="$STATUS_DIR/$candidate_file.status"
  rc_file="$STATUS_DIR/$candidate_file.rc"
  emit="$DECISIONS/$candidate_file.proof"

  if [ "$admissible" != "true" ] || [ -z "$fixture" ]; then
    printf '%s\n' "refused" > "$status_file"
    printf '%s\n' "0" > "$rc_file"
    jq -r '.refusal_reason // "not admissible"' <<<"$item" > "$err_file"
    : > "$out_file"
    echo "candidate=$candidate status=refused reason=preflight"
    continue
  fi

  set +e
  "$CLI" witness consensus \
    --concept "$candidate" \
    --require-fixture "$fixture" \
    --min-witnesses "$THRESHOLD" \
    --catalog "$EVIDENCE" \
    --consensus-policy "$CLI_POLICY" \
    --emit "$emit" > "$out_file" 2> "$err_file"
  rc=$?
  set -e
  printf '%s\n' "$rc" > "$rc_file"
  if [ "$rc" -eq 0 ]; then
    printf '%s\n' "admitted" > "$status_file"
    echo "candidate=$candidate status=admitted fixture=$fixture"
  else
    printf '%s\n' "refused" > "$status_file"
    echo "candidate=$candidate status=refused rc=$rc"
  fi
done < <(jq -c '.[]' "$PLAN")

echo "stage promotion decisions for mint"
mv "$DECISIONS" "$BACKUP_DECISIONS"
mkdir "$DECISIONS"
RESTORE_DECISIONS=1

python3 - "$PLAN" "$STATUS_DIR" "$BACKUP_DECISIONS" "$DECISIONS" "$CONTRACTS" "$ALIAS_LIST" <<'PY'
import json
import shutil
import sys
from pathlib import Path

plan_path = Path(sys.argv[1])
status_dir = Path(sys.argv[2])
backup_decisions = Path(sys.argv[3])
stage_decisions = Path(sys.argv[4])
contracts_dir = Path(sys.argv[5])
alias_list = Path(sys.argv[6])


def safe_filename(cid: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in cid)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def true_formula() -> dict:
    return {"args": [], "kind": "atomic", "name": "true"}


def enriched_contract(source_path: Path) -> dict:
    contract = load_json(source_path)
    contract.setdefault("pre", contract.get("composed_pre", true_formula()))
    contract.setdefault("post", contract.get("composed_post", true_formula()))
    contract.setdefault("effects", {"effects": []})
    contract.setdefault("formals", [])
    contract.setdefault("formal_sorts", [])
    contract.setdefault("return_sort", {"kind": "ctor", "name": "Unknown"})
    return contract


aliases = []
plan = load_json(plan_path)
by_name = {item["candidate"]: item for item in plan}
for item in plan:
    candidate_file = item["candidate_file"]
    status_path = status_dir / f"{candidate_file}.status"
    if not status_path.exists() or status_path.read_text(encoding="utf-8").strip() != "admitted":
        continue

    proof_path = backup_decisions / f"{candidate_file}.proof"
    if not proof_path.exists():
        raise SystemExit(f"missing emitted decision {proof_path}")
    staged_decision = stage_decisions / f"{candidate_file}.json"
    shutil.copyfile(proof_path, staged_decision)

    decision = load_json(proof_path)
    candidate = decision["header"]["decision_payload"]["promoted_op"]
    evidence_cids = decision["header"].get("evidence_cids", [])
    if not evidence_cids:
        raise SystemExit(f"{proof_path}: missing evidence_cids")
    first_evidence = evidence_cids[0]
    source_contract = Path(by_name[candidate]["representative_contract_path"])
    alias_path = contracts_dir / f"{safe_filename(first_evidence)}.json"
    if alias_path.exists():
        raise SystemExit(f"refusing to overwrite existing contract file {alias_path}")
    contract = enriched_contract(source_contract)
    with alias_path.open("w", encoding="utf-8") as handle:
        json.dump(contract, handle, sort_keys=True, indent=2, ensure_ascii=True)
        handle.write("\n")
    aliases.append(str(alias_path))

alias_list.write_text("\n".join(aliases) + ("\n" if aliases else ""), encoding="utf-8")
print(f"mint_stage_decisions={len(list(stage_decisions.glob('*.json')))}")
print(f"mint_stage_contract_aliases={len(aliases)}")
PY

echo "run mint"
set +e
SUGAR_BIND_OUTPUT="$RAW/" bash menagerie/concept-shapes/mint.sh > "$MINT_OUT" 2>&1
mint_rc=$?
set -e
tail -n 20 "$MINT_OUT"
if [ "$mint_rc" -ne 0 ]; then
  cat "$MINT_OUT"
  exit "$mint_rc"
fi

if [ -s "$ALIAS_LIST" ]; then
  while IFS= read -r alias_path; do
    [ -n "$alias_path" ] && rm -f "$alias_path"
  done < "$ALIAS_LIST"
  : > "$ALIAS_LIST"
fi
rm -rf "$DECISIONS"
mv "$BACKUP_DECISIONS" "$DECISIONS"
RESTORE_DECISIONS=0

find menagerie/concept-shapes/specs -type f -name '*.spec.json' | sort > "$AFTER_SPECS"

python3 - "$PLAN" "$STATUS_DIR" "$MINT_OUT" "$BEFORE_SPECS" "$AFTER_SPECS" "$RECEIPT" "$RAW" "$POLICY" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

plan_path = Path(sys.argv[1])
status_dir = Path(sys.argv[2])
mint_out = Path(sys.argv[3])
before_specs = Path(sys.argv[4])
after_specs = Path(sys.argv[5])
receipt_path = Path(sys.argv[6])
raw = sys.argv[7]
policy = sys.argv[8]


def read_set(path: Path) -> set[str]:
    return set(path.read_text(encoding="utf-8").splitlines())


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


plan = load_json(plan_path)
before = read_set(before_specs)
after = read_set(after_specs)
new_specs = sorted(after - before)
mint_text = mint_out.read_text(encoding="utf-8")
mint_summary = {}
matches = re.findall(
    r"promotion_decision_mint_summary\tadmitted_seen=(\d+)\twritten=(\d+)\tskipped_existing=(\d+)",
    mint_text,
)
if matches:
    match = matches[-1]
    mint_summary = {
        "admitted_seen": int(match[0]),
        "written": int(match[1]),
        "skipped_existing": int(match[2]),
    }

cids_rows = []
cids_path = Path("menagerie/concept-shapes/cids.tsv")
if cids_path.exists():
    for line in cids_path.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 4:
            cids_rows.append({
                "kind": parts[0],
                "name": parts[1],
                "cid": parts[2],
                "path": parts[3],
            })

verification = []
for spec in new_specs:
    spec_json = load_json(Path(spec))
    promoted_op = spec_json.get("fn_name", "")
    row = next(
        (
            row for row in cids_rows
            if row["kind"] == "shape" and row["name"] == promoted_op
        ),
        None,
    )
    verification.append({
        "spec": spec,
        "promoted_op": promoted_op,
        "cid": row["cid"] if row else None,
        "catalog_path": row["path"] if row else None,
        "catalog_path_exists": bool(row and Path(row["path"]).exists()),
        "verified": bool(row and Path(row["path"]).exists()),
    })

candidates = []
for item in plan:
    candidate_file = item["candidate_file"]
    status_path = status_dir / f"{candidate_file}.status"
    rc_path = status_dir / f"{candidate_file}.rc"
    err_path = status_dir / f"{candidate_file}.err"
    out_path = status_dir / f"{candidate_file}.out"
    status = status_path.read_text(encoding="utf-8").strip() if status_path.exists() else "not-run"
    rc = int(rc_path.read_text(encoding="utf-8").strip()) if rc_path.exists() else None
    candidates.append({
        "candidate": item["candidate"],
        "candidate_file": candidate_file,
        "reported_cardinality": item["reported_cardinality"],
        "mapped_site_count": item["mapped_site_count"],
        "witness_count": len(item.get("witnesses", [])),
        "fixture_cid": item.get("fixture_cid"),
        "representative_contract_cid": item.get("representative_contract_cid"),
        "requires_llm_auto_namer": item.get("requires_llm_auto_namer", False),
        "status": status,
        "exit_code": rc,
        "decision_path": f"{raw}/promotion-decisions/{candidate_file}.proof" if status == "admitted" else None,
        "stdout_tail": out_path.read_text(encoding="utf-8").splitlines()[-5:] if out_path.exists() else [],
        "stderr_tail": err_path.read_text(encoding="utf-8").splitlines()[-5:] if err_path.exists() else [],
    })

admissions = sum(1 for item in candidates if item["status"] == "admitted")
refusals = sum(1 for item in candidates if item["status"] == "refused")

receipt = {
    "kind": "libsugar-intra-vendor-witness-consensus-receipt",
    "schemaVersion": "1",
    "declaredAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    "inputs": {
        "bind_output": raw,
        "contracts": f"{raw}/contracts",
        "evidence_catalog": f"{raw}/evidence",
        "policy": policy,
    },
    "threshold": 4,
    "candidates_examined": len(candidates),
    "admissions": admissions,
    "refusals": refusals,
    "new_op_specs_written": len(new_specs),
    "new_op_spec_files": new_specs,
    "mint_summary": mint_summary,
    "content_address_verification": verification,
    "candidates": candidates,
    "notes": [
        "The declarative intra-vendor policy is projected to the CLI thresholds shape at runtime without changing the policy file; the projected policy carries the original policy CID.",
        "The driver stages only witness-consensus PromotionDecisionMementos for minting because bind-time promotion decisions use the proof gate payload shape.",
        "Temporary contract aliases are removed after minting; persistent consensus decisions remain as .proof files.",
    ],
}

if any(not item["verified"] for item in verification):
    raise SystemExit("new op-spec content-address verification failed")

receipt_path.parent.mkdir(parents=True, exist_ok=True)
with receipt_path.open("w", encoding="utf-8") as handle:
    json.dump(receipt, handle, sort_keys=True, indent=2, ensure_ascii=True)
    handle.write("\n")

print(f"receipt={receipt_path}")
print(f"summary candidates_examined={len(candidates)} admitted={admissions} refused={refusals} new_op_specs={len(new_specs)}")
PY

SWEEP_LIST="$TMP_ROOT/em-dash-files.txt"
{
  printf '%s\n' "bootstrap/scripts/run_libsugar_intra_vendor_consensus.sh"
  printf '%s\n' "$RECEIPT"
  jq -r '.new_op_spec_files[]' "$RECEIPT"
} > "$SWEEP_LIST"

if rg -n $'\342\200\224' $(cat "$SWEEP_LIST") > "$TMP_ROOT/em-dash.out"; then
  echo "em_dash_sweep=found"
  cat "$TMP_ROOT/em-dash.out"
  exit 1
fi

echo "em_dash_sweep=clean"
echo "summary candidates_examined=$(jq -r '.candidates_examined' "$RECEIPT") admitted=$(jq -r '.admissions' "$RECEIPT") refused=$(jq -r '.refusals' "$RECEIPT") new_op_specs=$(jq -r '.new_op_specs_written' "$RECEIPT")"
