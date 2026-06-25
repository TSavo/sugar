#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: tests/compiler_warning_delta_epsilon.sh [--input WARNINGS.jsonl] [--epsilon PREDICTION]

With --input, parse an existing Cargo --message-format=json JSONL stream.
Without --input, run:
  ${CARGO:-cargo} check --manifest-path implementations/rust/Cargo.toml --workspace --all-targets --message-format=json

The instrument reports current R. Delta R is read by comparing this run with a
previous run. Epsilon R is the prediction supplied by the change about to land.
USAGE
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd "$script_dir/.." && pwd -P)"
cargo_bin="${SUGAR_WARNING_DE_CARGO:-${CARGO:-cargo}}"
input=""
epsilon="${SUGAR_WARNING_DE_EPSILON:-<unspecified>}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      if [[ $# -lt 2 ]]; then
        echo "compiler-warning-DE: --input requires a path" >&2
        exit 2
      fi
      input="$2"
      shift 2
      ;;
    --epsilon)
      if [[ $# -lt 2 ]]; then
        echo "compiler-warning-DE: --epsilon requires a prediction" >&2
        exit 2
      fi
      epsilon="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "compiler-warning-DE: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

tmp_dir=""
cleanup() {
  if [[ -n "$tmp_dir" ]]; then
    rm -rf "$tmp_dir"
  fi
}
trap cleanup EXIT

cargo_status=0
source_label="$input"
if [[ -z "$input" ]]; then
  tmp_dir="$(mktemp -d)"
  input="$tmp_dir/cargo-check-warnings.jsonl"
  source_label="live cargo check"
  set +e
  (
    cd "$repo_root"
    "$cargo_bin" check \
      --manifest-path implementations/rust/Cargo.toml \
      --workspace \
      --all-targets \
      --message-format=json
  ) >"$input" 2>&1
  cargo_status=$?
  set -e
fi

if [[ ! -f "$input" ]]; then
  echo "compiler-warning-DE: input not found: $input" >&2
  exit 2
fi

python3 - "$input" "$source_label" "$epsilon" "$cargo_status" <<'PY'
import collections
import json
import os
import sys

input_path, source_label, epsilon, cargo_status_text = sys.argv[1:5]
cargo_status = int(cargo_status_text)


def warning_kind(message: str) -> str:
    if message.startswith("unused import"):
        return "unused_imports"
    if message.startswith("unused variable"):
        return "unused_variables"
    if message.startswith("unreachable pattern"):
        return "unreachable_patterns"
    if message.startswith("unused doc comment"):
        return "unused_doc_comments"
    if "field `" in message and "never read" in message:
        return "dead_fields"
    if "function `" in message and "never used" in message:
        return "dead_functions"
    if "method" in message and "never used" in message:
        return "dead_methods"
    if "struct `" in message and "never constructed" in message:
        return "dead_structs"
    if "enum `" in message and "never used" in message:
        return "dead_enums"
    if "variant" in message and "never constructed" in message:
        return "dead_variants"
    if "constant `" in message and "never used" in message:
        return "dead_constants"
    if "associated" in message and "never used" in message:
        return "dead_associated_items"
    return "other"


def replacement_plan(kind: str, message: str, file_name: str) -> str:
    if kind == "unused_imports":
        return "remove the unused import or wire it into live code"
    if kind == "unused_variables":
        return "use the value in live behavior, or prefix it with '_' only if the value is intentionally residual"
    if kind == "unreachable_patterns":
        return "remove the unreachable arm, or restore the missing variant path that makes it reachable"
    if kind == "unused_doc_comments":
        return "convert the orphan doc comment to a line comment, or attach docs to the generated item"
    if kind.startswith("dead_"):
        if "sugar-lift-rust-tests/src/sugar/" in file_name:
            return "delete the dead sugar helper or route it through the tiny sugar/floor owner that needs it"
        if file_name == "sugar-lift-rust-tests/src/lib.rs":
            return "move the live behavior into a tiny sugar/floor owner, or delete the dead monolith helper"
        if "try_fold_eval.rs" in file_name:
            return "wire the evaluator into a live sugar recognizer, or delete the orphan evaluator"
        if "kit_declaration.rs" in file_name:
            return "wire the declaration loader into CLI dispatch, or remove the dormant loader surface"
        return "wire the item into live behavior, delete it, or add a justified local allow with the floor it protects"
    return "classify this warning and give it a tiny owner or delete the dead path"


def package_name(package_id: str, manifest_path: str) -> str:
    if manifest_path:
        parent = os.path.basename(os.path.dirname(manifest_path))
        if parent:
            return parent
    if "/implementations/rust/" in package_id:
        return package_id.split("/implementations/rust/", 1)[1].split("#", 1)[0]
    return package_id


warnings = {}
parse_errors = 0
raw_workspace_warning_count = 0

with open(input_path, encoding="utf-8", errors="replace") as handle:
    for line in handle:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            parse_errors += 1
            continue
        if obj.get("reason") != "compiler-message":
            continue
        msg = obj.get("message") or {}
        if msg.get("level") != "warning":
            continue
        package_id = obj.get("package_id", "")
        manifest_path = obj.get("manifest_path", "")
        if not package_id.startswith("path+file://"):
            continue
        if "/implementations/rust/" not in package_id and "/implementations/rust/" not in manifest_path:
            continue
        spans = msg.get("spans") or []
        primary = next((span for span in spans if span.get("is_primary")), spans[0] if spans else {})
        file_name = primary.get("file_name") or "<no-file>"
        line_no = primary.get("line_start") or 0
        column = primary.get("column_start") or 0
        code = (msg.get("code") or {}).get("code") or "<none>"
        message = msg.get("message") or ""
        package = package_name(package_id, manifest_path)
        target = obj.get("target") or {}
        target_name = target.get("name") or "<unknown-target>"
        kind = warning_kind(message)
        key = (package, file_name, line_no, column, code, message)
        raw_workspace_warning_count += 1
        warning = warnings.setdefault(
            key,
            {
                "package": package,
                "file": file_name,
                "line": line_no,
                "column": column,
                "code": code,
                "message": message,
                "kind": kind,
                "targets": set(),
                "raw": 0,
                "plan": replacement_plan(kind, message, file_name),
            },
        )
        warning["targets"].add(target_name)
        warning["raw"] += 1

rows = sorted(warnings.values(), key=lambda w: (w["package"], w["file"], w["line"], w["column"], w["message"]))
current_r = len(rows)

print("compiler_warning_delta_epsilon")
print(f"source = {source_label}")
print(f"cargo_status = {cargo_status}")
print(f"R.compiler_warnings.current = {current_r}")
print("Delta R: compare this run to the previous instrument run")
print(f"Epsilon R.predicted = {epsilon}")
print(f"raw_warning_emissions = {raw_workspace_warning_count}")
print(f"parse_errors = {parse_errors}")
print("stable_zero = " + ("yes" if current_r == 0 and epsilon in {"0", "compiler_warnings=0"} else "no"))

if rows:
    print()
    print("warning_kind_counts:")
    for kind, count in collections.Counter(row["kind"] for row in rows).most_common():
        print(f"- {kind}: {count}")
    print()
    print("package_counts:")
    for package, count in collections.Counter(row["package"] for row in rows).most_common():
        print(f"- {package}: {count}")
    print()
    print("offenders:")
    for index, row in enumerate(rows, 1):
        targets = ",".join(sorted(row["targets"]))
        print(
            f"{index}. {row['file']}:{row['line']}:{row['column']} "
            f"| package={row['package']} | kind={row['kind']} | code={row['code']} | targets={targets}"
        )
        print(f"   warning: {row['message']}")
        print(f"   replacement_plan: {row['plan']}")

if cargo_status != 0:
    sys.exit(2)
if current_r != 0:
    sys.exit(1)
if epsilon not in {"0", "compiler_warnings=0"}:
    sys.exit(1)
sys.exit(0)
PY
