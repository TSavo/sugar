#!/usr/bin/env bash
# itsdangerous-token-padding: the real-name logo for the python universe rung.
#
# itsdangerous (Flask's signing dependency) encodes tokens with
#
#     def base64_encode(string):
#         string = want_bytes(string)
#         return base64.urlsafe_b64encode(string).rstrip(b"=")
#
# rstrip is TOTAL: no output of base64_encode ever ends with '=' -- for any
# input, forever, by one byte literal in the vendor's own source. The lifter
# walks that shape (the no-suffix-chars family), reports its ∀⊨sample
# evidence honestly (the wheel ships no test corpus: 0 vendor vectors,
# stated on the universe record), and conjoins ¬suffix-of("=", subject)
# into the callsite's #euf# assertion.
#
# BAD twin: the token-padding confusion -- asserting the PADDED standard
# base64url value where itsdangerous' stripped tokens live (the classic
# JWT/token interop bug). equality ∧ ¬suffixof -> UNSAT, statically.
#
# Verdicts parsed from real .verify.json rows; the verdict FLIP is the
# vacuity witness (a universe that never met the equality would let both
# twins discharge).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
TARGET_DIR="${CARGO_TARGET_DIR:-$REPO/implementations/rust/target}"
BIN="$TARGET_DIR/debug/sugar"

VENV="${ITSDANGEROUS_LOGO_VENV:-/tmp/itsdangerous-logo-venv}"
export ITSDANGEROUS_LOGO_VENV="$VENV"
if [ ! -x "$VENV/bin/python" ]; then
  echo "== create venv + install the real vendor (itsdangerous) =="
  python3 -m venv "$VENV"
fi
if ! "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import blake3
import cbor2
import itsdangerous
import nacl
PY
then
  "$VENV/bin/pip" install -q itsdangerous blake3 cbor2 pynacl
fi
"$VENV/bin/python" -c "import itsdangerous; print('vendor:', 'itsdangerous', itsdangerous.__version__ if hasattr(itsdangerous,'__version__') else '(installed)')" || {
  echo "FAIL: vendor install"; exit 1; }

audit_good_source() {
  echo
  echo "== source audit: sugar lift --report itsdangerous.encoding.base64_encode =="
  local report
  report="$(mktemp)"
  ( cd "$HERE/good" && "$BIN" lift --report --json . ) > "$report" || {
    echo "FAIL: source audit lift report"
    rm -f "$report"
    return 1
  }
  python3 - "$report" <<'PY' || {
import json, sys
from collections import Counter
result = json.load(open(sys.argv[1], encoding="utf-8"))
ledger = result.get("sourceLedger") or {}
audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.translate-universe"
    and "base64_encode" in audit.get("contract", {}).get("name", "")
]
if len(audits) != 1:
    raise SystemExit(f"FAIL: expected one base64_encode universe source audit, got {len(audits)}")
audit = audits[0]
totals = audit["totals"]
if totals.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: base64 source dig has unclassified source: totals={totals}")
int_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.translate-universe"
    and "int_to_bytes" in audit.get("contract", {}).get("name", "")
]
if len(int_audits) != 1:
    raise SystemExit(f"FAIL: expected one int_to_bytes universe source audit, got {len(int_audits)}")
int_audit = int_audits[0]
int_totals = int_audit["totals"]
if int_audit.get("universe_kind") != "no-prefix-chars":
    raise SystemExit(f"FAIL: expected no-prefix-chars audit, got {int_audit.get('universe_kind')}")
if int_totals.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: int_to_bytes source dig has unclassified source: totals={int_totals}")
base64_decode_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.exception-handler-raise-universe"
    and "base64_decode" in audit.get("contract", {}).get("name", "")
]
if len(base64_decode_audits) != 1:
    raise SystemExit(
        "FAIL: expected one base64_decode exception-handler source audit, "
        f"got {len(base64_decode_audits)}"
    )
base64_decode_audit = base64_decode_audits[0]
base64_decode_totals = base64_decode_audit["totals"]
base64_decode_memento = base64_decode_audit["source_memento"]
if base64_decode_audit.get("universe_kind") != "exception-handler-raise":
    raise SystemExit(
        "FAIL: expected exception-handler-raise audit, got "
        f"{base64_decode_audit.get('universe_kind')}"
    )
if base64_decode_memento.get("source_function_name") != "base64_decode":
    raise SystemExit(
        "FAIL: base64_decode source oracle should point at function body: "
        f"{base64_decode_memento!r}"
    )
if base64_decode_memento.get("exception_handler_raise_type") != "BadData":
    raise SystemExit(
        "FAIL: base64_decode memento did not record BadData: "
        f"{base64_decode_memento!r}"
    )
if "body_text" in base64_decode_memento or "ast_template" in base64_decode_memento:
    raise SystemExit("FAIL: base64_decode source memento embeds source/template body")
if base64_decode_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: base64_decode source dig has unclassified source: "
        f"totals={base64_decode_totals}"
    )
base64_decode_warranted_lines = {
    locus.get("line")
    for locus in base64_decode_audit["loci"]
    if locus.get("status") == "warranted"
}
if not {35, 37, 38}.issubset(base64_decode_warranted_lines):
    raise SystemExit(
        "FAIL: base64_decode try/except raise lines were not warranted: "
        f"got={sorted(base64_decode_warranted_lines)}"
    )
if not any(
    locus.get("line") == 36
    and locus.get("status") == "support"
    and locus.get("ast_kind") == "Return"
    for locus in base64_decode_audit["loci"]
):
    raise SystemExit("FAIL: base64_decode successful return path was not accounted as support")
package_getattr_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.branch-selected-raise-universe"
    and audit.get("source_memento", {}).get("source_function_name")
    == "__getattr__"
]
if len(package_getattr_audits) != 1:
    raise SystemExit(
        "FAIL: expected one __getattr__ branch-selected raise source audit, "
        f"got {len(package_getattr_audits)}"
    )
package_getattr_audit = package_getattr_audits[0]
package_getattr_totals = package_getattr_audit["totals"]
package_getattr_memento = package_getattr_audit["source_memento"]
if package_getattr_audit.get("universe_kind") != "branch-selected-raise":
    raise SystemExit(
        "FAIL: expected branch-selected-raise audit, got "
        f"{package_getattr_audit.get('universe_kind')}"
    )
if package_getattr_memento.get("branch_param_name") != "name":
    raise SystemExit(
        "FAIL: __getattr__ source memento did not record guarded param: "
        f"{package_getattr_memento!r}"
    )
if package_getattr_memento.get("branch_excluded_value") != "__version__":
    raise SystemExit(
        "FAIL: __getattr__ source memento did not record return branch value: "
        f"{package_getattr_memento!r}"
    )
if package_getattr_memento.get("branch_raise_exception_type") != "AttributeError":
    raise SystemExit(
        "FAIL: __getattr__ source memento did not record AttributeError: "
        f"{package_getattr_memento!r}"
    )
if "body_text" in package_getattr_memento or "ast_template" in package_getattr_memento:
    raise SystemExit("FAIL: __getattr__ source memento embeds source/template body")
if package_getattr_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: __getattr__ source dig has unclassified source: "
        f"totals={package_getattr_totals}"
    )
package_getattr_warranted_lines = {
    locus.get("line")
    for locus in package_getattr_audit["loci"]
    if locus.get("status") == "warranted"
}
if not {25, 38}.issubset(package_getattr_warranted_lines):
    raise SystemExit(
        "FAIL: __getattr__ guard/raise lines were not warranted: "
        f"got={sorted(package_getattr_warranted_lines)}"
    )
signature_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.constant-universe"
    and "NoneAlgorithm.get_signature" in audit.get("contract", {}).get("name", "")
]
if len(signature_audits) != 1:
    raise SystemExit(f"FAIL: expected one NoneAlgorithm.get_signature constant source audit, got {len(signature_audits)}")
signature_audit = signature_audits[0]
signature_totals = signature_audit["totals"]
if signature_audit.get("universe_kind") != "constant":
    raise SystemExit(f"FAIL: expected constant audit, got {signature_audit.get('universe_kind')}")
if signature_totals.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: NoneAlgorithm.get_signature source dig has unclassified source: totals={signature_totals}")
if signature_audit["source_memento"].get("source_function_name") != "NoneAlgorithm.get_signature":
    raise SystemExit(f"FAIL: source oracle function should point at method body: {signature_audit['source_memento']!r}")
if not any(
    m.get("role") == "python.constant-universe"
    and m.get("source_function_name") == "NoneAlgorithm.get_signature"
    for m in result.get("sourceMementos") or []
):
    raise SystemExit("FAIL: lift report missing class-method constant source memento")
hmac_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.instance-field-universe"
    and "HMACAlgorithm" in audit.get("contract", {}).get("name", "")
]
if len(hmac_audits) != 1:
    raise SystemExit(
        f"FAIL: expected one HMACAlgorithm digest_method audit, got {len(hmac_audits)}"
    )
hmac_audit = hmac_audits[0]
hmac_totals = hmac_audit["totals"]
if hmac_audit.get("universe_kind") != "constructor-field-getter":
    raise SystemExit(
        f"FAIL: expected constructor-field-getter audit, got {hmac_audit.get('universe_kind')}"
    )
hmac_memento = hmac_audit["source_memento"]
if hmac_memento.get("source_function_name") != "HMACAlgorithm.__init__":
    raise SystemExit(
        "FAIL: HMACAlgorithm source oracle should point at constructor: "
        f"{hmac_memento!r}"
    )
if hmac_memento.get("constructor_default_param_names") != ["digest_method"]:
    raise SystemExit(
        "FAIL: HMACAlgorithm source memento did not record the defaulted param: "
        f"{hmac_memento!r}"
    )
if hmac_memento.get("constructor_default_attr_name") != "default_digest_method":
    raise SystemExit(
        "FAIL: HMACAlgorithm source memento did not record the default attr: "
        f"{hmac_memento!r}"
    )
if "body_text" in hmac_memento or "ast_template" in hmac_memento:
    raise SystemExit("FAIL: HMACAlgorithm source memento embeds source/template body")
if hmac_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: HMACAlgorithm.digest_method source dig has unclassified source: "
        f"totals={hmac_totals}"
    )
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "If"
    and locus.get("ast_path") == "$.body[0]"
    for locus in hmac_audit["loci"]
):
    raise SystemExit("FAIL: HMACAlgorithm digest-method default branch was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Assign"
    and locus.get("ast_path") == "$.body[0].body[0]"
    for locus in hmac_audit["loci"]
):
    raise SystemExit("FAIL: HMACAlgorithm digest-method default assignment was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "AnnAssign"
    and locus.get("ast_path") == "$.body[1]"
    for locus in hmac_audit["loci"]
):
    raise SystemExit("FAIL: HMACAlgorithm digest-method field assignment was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Constant"
    and locus.get("ast_path") == "$.args.defaults[0]"
    and "default constructor argument emitted" in locus.get("reason", "")
    for locus in hmac_audit["loci"]
):
    raise SystemExit("FAIL: HMACAlgorithm digest-method default argument was not warranted")
signer_key_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.instance-field-universe"
    and "itsdangerous.signer.Signer"
    in audit.get("contract", {}).get("name", "")
    and audit.get("source_memento", {}).get("constructor_default_attr_name")
    == "default_key_derivation"
    and audit.get("source_memento", {}).get("constructor_default_param_names")
    == ["key_derivation"]
]
if len(signer_key_audits) != 1:
    raise SystemExit(
        "FAIL: expected one Signer.key_derivation constructor-field audit, "
        f"got {len(signer_key_audits)}"
    )
signer_key_audit = signer_key_audits[0]
signer_key_totals = signer_key_audit["totals"]
signer_key_memento = signer_key_audit["source_memento"]
if signer_key_memento.get("source_function_name") != "Signer.__init__":
    raise SystemExit(
        "FAIL: Signer source oracle should point at constructor: "
        f"{signer_key_memento!r}"
    )
if signer_key_memento.get("constructor_default_param_names") != ["key_derivation"]:
    raise SystemExit(
        "FAIL: Signer source memento did not record the defaulted param: "
        f"{signer_key_memento!r}"
    )
if signer_key_memento.get("constructor_default_attr_name") != "default_key_derivation":
    raise SystemExit(
        "FAIL: Signer source memento did not record the default attr: "
        f"{signer_key_memento!r}"
    )
if signer_key_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: Signer.key_derivation source dig has unclassified source: "
        f"totals={signer_key_totals}"
    )
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "If"
    and locus.get("ast_path") == "$.body[5]"
    for locus in signer_key_audit["loci"]
):
    raise SystemExit("FAIL: Signer key-derivation default branch was not warranted")
if not any(
    locus.get("status") == "support"
    and locus.get("ast_kind") == "If"
    and "validation guard" in locus.get("reason", "")
    for locus in signer_key_audit["loci"]
):
    raise SystemExit("FAIL: Signer separator validation guard was not accounted as support")
signer_secret_key_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.instance-field-universe"
    and "itsdangerous.signer.Signer" in audit.get("contract", {}).get("name", "")
    and audit.get("source_memento", {}).get("source_function_name")
    == "Signer.secret_key"
]
if len(signer_secret_key_audits) != 1:
    raise SystemExit(
        "FAIL: expected one Signer.secret_key property audit, "
        f"got {len(signer_secret_key_audits)}"
    )
signer_secret_key_audit = signer_secret_key_audits[0]
signer_secret_key_totals = signer_secret_key_audit["totals"]
signer_secret_key_memento = signer_secret_key_audit["source_memento"]
if signer_secret_key_memento.get("field_name") != "secret_keys":
    raise SystemExit(
        "FAIL: Signer.secret_key source memento did not record secret_keys: "
        f"{signer_secret_key_memento!r}"
    )
if signer_secret_key_memento.get("field_projection") != ["index", -1]:
    raise SystemExit(
        "FAIL: Signer.secret_key source memento did not record [-1] projection: "
        f"{signer_secret_key_memento!r}"
    )
if "body_text" in signer_secret_key_memento or "ast_template" in signer_secret_key_memento:
    raise SystemExit("FAIL: Signer.secret_key source memento embeds source/template body")
if signer_secret_key_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: Signer.secret_key source dig has unclassified source: "
        f"totals={signer_secret_key_totals}"
    )
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Return"
    and locus.get("line") == 180
    for locus in signer_secret_key_audit["loci"]
):
    raise SystemExit("FAIL: Signer.secret_key return was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Subscript"
    and locus.get("line") == 180
    for locus in signer_secret_key_audit["loci"]
):
    raise SystemExit("FAIL: Signer.secret_key [-1] projection was not warranted")
signer_secret_list_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.list-adapter-universe"
    and "itsdangerous.signer.Signer" in audit.get("contract", {}).get("name", "")
    and audit.get("source_memento", {}).get("source_function_name")
    == "_make_keys_list"
    and audit.get("source_memento", {}).get("list_adapter_branch") == "scalar"
]
if len(signer_secret_list_audits) != 1:
    raise SystemExit(
        "FAIL: expected one Signer.secret_key _make_keys_list audit, "
        f"got {len(signer_secret_list_audits)}"
    )
signer_secret_list_audit = signer_secret_list_audits[0]
signer_secret_list_totals = signer_secret_list_audit["totals"]
if signer_secret_list_audit["source_memento"].get("list_adapter_branch") != "scalar":
    raise SystemExit(
        "FAIL: Signer.secret_key list-adapter memento did not record scalar branch: "
        f"{signer_secret_list_audit['source_memento']!r}"
    )
if signer_secret_list_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: Signer.secret_key list-adapter source dig has unclassified source: "
        f"totals={signer_secret_list_totals}"
    )
signer_derive_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.branch-selected-universe"
    and "itsdangerous.signer.Signer.derive_key"
    in audit.get("contract", {}).get("name", "")
]
if len(signer_derive_audits) != 1:
    raise SystemExit(
        "FAIL: expected one Signer.derive_key branch-selected audit, "
        f"got {len(signer_derive_audits)}"
    )
signer_derive_audit = signer_derive_audits[0]
signer_derive_totals = signer_derive_audit["totals"]
signer_derive_memento = signer_derive_audit["source_memento"]
if signer_derive_memento.get("source_function_name") != "Signer.derive_key":
    raise SystemExit(
        "FAIL: Signer.derive_key source oracle should point at method body: "
        f"{signer_derive_memento!r}"
    )
if signer_derive_memento.get("branch_field_name") != "key_derivation":
    raise SystemExit(
        "FAIL: Signer.derive_key branch memento did not record the field: "
        f"{signer_derive_memento!r}"
    )
if signer_derive_memento.get("branch_field_value") != "none":
    raise SystemExit(
        "FAIL: Signer.derive_key branch memento did not record the selected value: "
        f"{signer_derive_memento!r}"
    )
if (
    signer_derive_memento.get("branch_return_adapter_callee")
    != "itsdangerous.encoding.want_bytes"
):
    raise SystemExit(
        "FAIL: Signer.derive_key branch memento did not record the adapter: "
        f"{signer_derive_memento!r}"
    )
if signer_derive_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: Signer.derive_key source dig has unclassified source: "
        f"totals={signer_derive_totals}"
    )
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Assign"
    and locus.get("line") == 198
    for locus in signer_derive_audit["loci"]
):
    raise SystemExit("FAIL: Signer.derive_key want_bytes normalization was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "If"
    and locus.get("line") == 210
    for locus in signer_derive_audit["loci"]
):
    raise SystemExit("FAIL: Signer.derive_key none branch was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Return"
    and locus.get("line") == 211
    for locus in signer_derive_audit["loci"]
):
    raise SystemExit("FAIL: Signer.derive_key none return was not warranted")
serializer_kwargs_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.instance-field-universe"
    and "itsdangerous.serializer.Serializer" in audit.get("contract", {}).get("name", "")
    and audit.get("source_memento", {}).get("source_function_name")
    == "Serializer.__init__"
    and audit.get("source_memento", {}).get("field_name") == "signer_kwargs"
    and audit.get("source_memento", {}).get("constructor_param_name")
    == "signer_kwargs"
]
if len(serializer_kwargs_audits) != 1:
    raise SystemExit(
        "FAIL: expected one Serializer.signer_kwargs constructor-field audit, "
        f"got {len(serializer_kwargs_audits)}"
    )
serializer_kwargs_audit = serializer_kwargs_audits[0]
serializer_kwargs_totals = serializer_kwargs_audit["totals"]
serializer_kwargs_memento = serializer_kwargs_audit["source_memento"]
if serializer_kwargs_memento.get("constructor_default_literal_kind") != "collection":
    raise SystemExit(
        "FAIL: Serializer.signer_kwargs source memento did not record a "
        f"collection default: {serializer_kwargs_memento!r}"
    )
if serializer_kwargs_memento.get("constructor_default_literal") != "dict:{}":
    raise SystemExit(
        "FAIL: Serializer.signer_kwargs source memento did not record dict:{} "
        f"default: {serializer_kwargs_memento!r}"
    )
if "body_text" in serializer_kwargs_memento or "ast_template" in serializer_kwargs_memento:
    raise SystemExit("FAIL: Serializer.signer_kwargs source memento embeds source/template body")
if serializer_kwargs_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: Serializer.signer_kwargs source dig has unclassified source: "
        f"totals={serializer_kwargs_totals}"
    )
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "AnnAssign"
    and locus.get("line") == 228
    for locus in serializer_kwargs_audit["loci"]
):
    raise SystemExit("FAIL: Serializer.signer_kwargs assignment was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "BoolOp"
    and locus.get("line") == 228
    for locus in serializer_kwargs_audit["loci"]
):
    raise SystemExit("FAIL: Serializer.signer_kwargs bool-or default was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Dict"
    and locus.get("line") == 228
    for locus in serializer_kwargs_audit["loci"]
):
    raise SystemExit("FAIL: Serializer.signer_kwargs dict default was not warranted")
load_payload_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.exception-handler-raise-universe"
    and audit.get("source_memento", {}).get("source_function_name")
    == "Serializer.load_payload"
    and audit.get("source_memento", {}).get("exception_handler_raise_type")
    == "BadPayload"
]
if len(load_payload_audits) != 1:
    raise SystemExit(
        "FAIL: expected one Serializer.load_payload exception-handler audit, "
        f"got {len(load_payload_audits)}"
    )
load_payload_audit = load_payload_audits[0]
load_payload_totals = load_payload_audit["totals"]
load_payload_memento = load_payload_audit["source_memento"]
if load_payload_audit.get("universe_kind") != "exception-handler-raise":
    raise SystemExit(
        "FAIL: expected exception-handler-raise audit, got "
        f"{load_payload_audit.get('universe_kind')}"
    )
if load_payload_memento.get("source_function_name") != "Serializer.load_payload":
    raise SystemExit(
        "FAIL: load_payload source oracle should point at method body: "
        f"{load_payload_memento!r}"
    )
if load_payload_memento.get("exception_handler_raise_type") != "BadPayload":
    raise SystemExit(
        "FAIL: load_payload source memento did not record BadPayload raise: "
        f"{load_payload_memento!r}"
    )
if "body_text" in load_payload_memento or "ast_template" in load_payload_memento:
    raise SystemExit("FAIL: load_payload source memento embeds source/template body")
if load_payload_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: Serializer.load_payload source dig has unclassified source: "
        f"totals={load_payload_totals}"
    )
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Try"
    and locus.get("line") == 261
    for locus in load_payload_audit["loci"]
):
    raise SystemExit("FAIL: Serializer.load_payload try path was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "ExceptHandler"
    and locus.get("line") == 266
    for locus in load_payload_audit["loci"]
):
    raise SystemExit("FAIL: Serializer.load_payload exception handler was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Raise"
    and locus.get("line") == 267
    for locus in load_payload_audit["loci"]
):
    raise SystemExit("FAIL: Serializer.load_payload BadPayload raise was not warranted")
urlsafe_load_payload_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.exception-handler-raise-universe"
    and audit.get("source_memento", {}).get("source_function_name")
    == "URLSafeSerializerMixin.load_payload"
    and audit.get("source_memento", {}).get("exception_handler_raise_type")
    == "BadPayload"
]
if len(urlsafe_load_payload_audits) != 1:
    raise SystemExit(
        "FAIL: expected one URLSafeSerializerMixin.load_payload "
        f"exception-handler audit, got {len(urlsafe_load_payload_audits)}"
    )
urlsafe_load_payload_audit = urlsafe_load_payload_audits[0]
urlsafe_load_payload_totals = urlsafe_load_payload_audit["totals"]
urlsafe_load_payload_memento = urlsafe_load_payload_audit["source_memento"]
if urlsafe_load_payload_audit.get("universe_kind") != "exception-handler-raise":
    raise SystemExit(
        "FAIL: expected exception-handler-raise audit, got "
        f"{urlsafe_load_payload_audit.get('universe_kind')}"
    )
if "body_text" in urlsafe_load_payload_memento or "ast_template" in urlsafe_load_payload_memento:
    raise SystemExit("FAIL: URLSafeSerializerMixin.load_payload source memento embeds source/template body")
if urlsafe_load_payload_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: URLSafeSerializerMixin.load_payload source dig has unclassified source: "
        f"totals={urlsafe_load_payload_totals}"
    )
urlsafe_warranted_lines = {
    locus.get("line")
    for locus in urlsafe_load_payload_audit["loci"]
    if locus.get("status") == "warranted"
}
if not {36, 38, 39, 40, 41, 42}.issubset(urlsafe_warranted_lines):
    raise SystemExit(
        "FAIL: URLSafeSerializerMixin.load_payload base64 exception lines "
        f"were not warranted: got={sorted(urlsafe_warranted_lines)}"
    )
if not any(
    locus.get("line") == 45
    and locus.get("status") == "support"
    and locus.get("ast_kind") == "Try"
    for locus in urlsafe_load_payload_audit["loci"]
):
    raise SystemExit("FAIL: URLSafeSerializerMixin.load_payload decompression path was not accounted as support")
if not any(
    locus.get("line") == 53
    and locus.get("status") == "support"
    and locus.get("ast_kind") == "Return"
    for locus in urlsafe_load_payload_audit["loci"]
):
    raise SystemExit("FAIL: URLSafeSerializerMixin.load_payload return path was not accounted as support")
timed_loads_unsafe_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.delegation-universe"
    and audit.get("source_memento", {}).get("source_function_name")
    == "TimedSerializer.loads_unsafe"
]
if len(timed_loads_unsafe_audits) != 1:
    raise SystemExit(
        "FAIL: expected one TimedSerializer.loads_unsafe delegation audit, "
        f"got {len(timed_loads_unsafe_audits)}"
    )
timed_loads_unsafe_audit = timed_loads_unsafe_audits[0]
timed_loads_unsafe_totals = timed_loads_unsafe_audit["totals"]
timed_loads_unsafe_memento = timed_loads_unsafe_audit["source_memento"]
if timed_loads_unsafe_audit.get("universe_kind") != "delegation-receiver-method":
    raise SystemExit(
        "FAIL: expected receiver-method delegation audit, got "
        f"{timed_loads_unsafe_audit.get('universe_kind')}"
    )
if timed_loads_unsafe_memento.get("source_function_name") != "TimedSerializer.loads_unsafe":
    raise SystemExit(
        "FAIL: TimedSerializer.loads_unsafe source oracle should point at "
        f"method body: {timed_loads_unsafe_memento!r}"
    )
if "body_text" in timed_loads_unsafe_memento or "ast_template" in timed_loads_unsafe_memento:
    raise SystemExit("FAIL: TimedSerializer.loads_unsafe source memento embeds source/template body")
if timed_loads_unsafe_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: TimedSerializer.loads_unsafe source dig has unclassified source: "
        f"totals={timed_loads_unsafe_totals}"
    )
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Return"
    and locus.get("line") == 228
    for locus in timed_loads_unsafe_audit["loci"]
):
    raise SystemExit("FAIL: TimedSerializer.loads_unsafe return was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Call"
    and locus.get("line") == 228
    for locus in timed_loads_unsafe_audit["loci"]
):
    raise SystemExit("FAIL: TimedSerializer.loads_unsafe delegate call was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "keyword"
    and locus.get("line") == 228
    for locus in timed_loads_unsafe_audit["loci"]
):
    raise SystemExit("FAIL: TimedSerializer.loads_unsafe load_kwargs keyword was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Dict"
    and locus.get("line") == 228
    for locus in timed_loads_unsafe_audit["loci"]
):
    raise SystemExit("FAIL: TimedSerializer.loads_unsafe load_kwargs dict was not warranted")
validate_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.exception-bool-return-universe"
]


def require_validate_audit(function_name, delegate_name, expected_lines):
    matches = [
        audit for audit in validate_audits
        if audit.get("source_memento", {}).get("source_function_name")
        == function_name
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"FAIL: expected one {function_name} exception-bool-return audit, "
            f"got {len(matches)}"
        )
    audit = matches[0]
    totals = audit["totals"]
    memento = audit["source_memento"]
    if audit.get("universe_kind") != "exception-bool-return":
        raise SystemExit(
            f"FAIL: expected exception-bool-return audit for {function_name}, "
            f"got {audit.get('universe_kind')}"
        )
    if memento.get("exception_bool_return_exception_type") != "BadSignature":
        raise SystemExit(
            f"FAIL: {function_name} memento did not record BadSignature: "
            f"{memento!r}"
        )
    if memento.get("exception_bool_return_delegate") != delegate_name:
        raise SystemExit(
            f"FAIL: {function_name} memento did not record delegate "
            f"{delegate_name}: {memento!r}"
        )
    if memento.get("exception_bool_return_success_value") is not True:
        raise SystemExit(f"FAIL: {function_name} success return was not True")
    if memento.get("exception_bool_return_exception_value") is not False:
        raise SystemExit(f"FAIL: {function_name} exception return was not False")
    if "body_text" in memento or "ast_template" in memento:
        raise SystemExit(f"FAIL: {function_name} source memento embeds source/template body")
    if totals.get("unclassified_source") != 0:
        raise SystemExit(
            f"FAIL: {function_name} source dig has unclassified source: "
            f"totals={totals}"
        )
    warranted_lines = {
        locus.get("line")
        for locus in audit["loci"]
        if locus.get("status") == "warranted"
    }
    if warranted_lines != set(expected_lines):
        raise SystemExit(
            f"FAIL: {function_name} warranted lines mismatch: "
            f"got={sorted(warranted_lines)} expected={list(expected_lines)}"
        )
    return audit, totals


signer_validate_audit, signer_validate_totals = require_validate_audit(
    "Signer.validate",
    "itsdangerous.signer.Signer.unsign",
    range(258, 267),
)
timestamp_validate_audit, timestamp_validate_totals = require_validate_audit(
    "TimestampSigner.validate",
    "itsdangerous.timed.TimestampSigner.unsign",
    range(160, 168),
)
separator_guard_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.separator-guard-raise-universe"
    and "Signer.validate" in audit.get("contract", {}).get("name", "")
]
if len(separator_guard_audits) != 1:
    raise SystemExit(
        "FAIL: expected one Signer.unsign separator-guard audit, "
        f"got {len(separator_guard_audits)}"
    )
separator_guard_audit = separator_guard_audits[0]
separator_guard_totals = separator_guard_audit["totals"]
separator_guard_memento = separator_guard_audit["source_memento"]
if separator_guard_audit.get("universe_kind") != "separator-guard-raise":
    raise SystemExit(
        "FAIL: expected separator-guard-raise audit, got "
        f"{separator_guard_audit.get('universe_kind')}"
    )
if separator_guard_memento.get("source_function_name") != "Signer.unsign":
    raise SystemExit(
        "FAIL: separator guard source oracle should point at Signer.unsign: "
        f"{separator_guard_memento!r}"
    )
if separator_guard_memento.get("separator_guard_exception_type") != "BadSignature":
    raise SystemExit(
        "FAIL: separator guard memento did not record BadSignature: "
        f"{separator_guard_memento!r}"
    )
if separator_guard_memento.get("separator_guard_field_name") != "sep":
    raise SystemExit(
        "FAIL: separator guard memento did not record sep field: "
        f"{separator_guard_memento!r}"
    )
if separator_guard_memento.get("separator_guard_param_name") != "signed_value":
    raise SystemExit(
        "FAIL: separator guard memento did not record signed_value param: "
        f"{separator_guard_memento!r}"
    )
if separator_guard_memento.get("separator_guard_adapter_callee") != "itsdangerous.encoding.want_bytes":
    raise SystemExit(
        "FAIL: separator guard memento did not record want_bytes adapter: "
        f"{separator_guard_memento!r}"
    )
if "body_text" in separator_guard_memento or "ast_template" in separator_guard_memento:
    raise SystemExit("FAIL: separator guard source memento embeds source/template body")
if separator_guard_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: Signer.unsign separator guard has unclassified source: "
        f"totals={separator_guard_totals}"
    )
separator_guard_lines = {
    locus.get("line")
    for locus in separator_guard_audit["loci"]
    if locus.get("status") == "warranted"
}
if separator_guard_lines != set(range(244, 257)):
    raise SystemExit(
        "FAIL: Signer.unsign separator guard warranted lines mismatch: "
        f"got={sorted(separator_guard_lines)}"
    )
abstract_signature_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.raise-locus-universe"
    and "test_signing_algorithm_get_signature_is_abstract"
    in audit.get("contract", {}).get("name", "")
]
if len(abstract_signature_audits) != 1:
    raise SystemExit(
        "FAIL: expected one SigningAlgorithm.get_signature raise-locus "
        f"audit, got {len(abstract_signature_audits)}"
    )
abstract_signature_audit = abstract_signature_audits[0]
abstract_signature_totals = abstract_signature_audit["totals"]
if abstract_signature_audit.get("universe_kind") != "raise-locus":
    raise SystemExit(
        f"FAIL: expected raise-locus audit, got "
        f"{abstract_signature_audit.get('universe_kind')}"
    )
if (
    abstract_signature_audit["source_memento"].get("source_function_name")
    != "SigningAlgorithm.get_signature"
):
    raise SystemExit(
        "FAIL: abstract signature source oracle should point at method body: "
        f"{abstract_signature_audit['source_memento']!r}"
    )
if abstract_signature_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: SigningAlgorithm.get_signature raise-locus source dig has "
        f"unclassified source: totals={abstract_signature_totals}"
    )
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Raise"
    for locus in abstract_signature_audit["loci"]
):
    raise SystemExit("FAIL: SigningAlgorithm.get_signature raise statement was not warranted")
message_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.instance-field-universe"
    and "BadData.__str__" in audit.get("contract", {}).get("name", "")
]
message_by_function = {
    audit.get("source_memento", {}).get("source_function_name"): audit
    for audit in message_audits
}
if set(message_by_function) != {"BadData.__init__", "BadData.__str__"}:
    raise SystemExit(
        "FAIL: expected BadData constructor/getter instance-field audits, "
        f"got {sorted(str(k) for k in message_by_function)}"
    )
for function_name, message_audit in message_by_function.items():
    message_totals = message_audit["totals"]
    if message_totals.get("unclassified_source") != 0:
        raise SystemExit(
            f"FAIL: {function_name} instance-field source dig has "
            f"unclassified source: totals={message_totals}"
        )
init_audit = message_by_function["BadData.__init__"]
str_audit = message_by_function["BadData.__str__"]
if not any(
    locus.get("status") == "support"
    and locus.get("ast_kind") == "Expr"
    for locus in init_audit["loci"]
):
    raise SystemExit("FAIL: BadData.__init__ super call was not explicit support")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Assign"
    for locus in init_audit["loci"]
):
    raise SystemExit("FAIL: BadData.__init__ field assignment was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Return"
    for locus in str_audit["loci"]
):
    raise SystemExit("FAIL: BadData.__str__ return was not warranted")
payload_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.instance-field-universe"
    and "BadSignature" in audit.get("contract", {}).get("name", "")
]
if len(payload_audits) != 1:
    raise SystemExit(f"FAIL: expected one BadSignature payload audit, got {len(payload_audits)}")
payload_audit = payload_audits[0]
payload_totals = payload_audit["totals"]
if payload_audit.get("universe_kind") != "constructor-field-getter":
    raise SystemExit(f"FAIL: expected constructor-field-getter audit, got {payload_audit.get('universe_kind')}")
if payload_audit["source_memento"].get("source_function_name") != "BadSignature.__init__":
    raise SystemExit(f"FAIL: payload source oracle should point at constructor: {payload_audit['source_memento']!r}")
if payload_totals.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: BadSignature.payload source dig has unclassified source: totals={payload_totals}")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "AnnAssign"
    for locus in payload_audit["loci"]
):
    raise SystemExit("FAIL: BadSignature.payload field assignment was not warranted")
bad_payload_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.instance-field-universe"
    and "BadPayload" in audit.get("contract", {}).get("name", "")
]
if len(bad_payload_audits) != 1:
    raise SystemExit(f"FAIL: expected one BadPayload default-field audit, got {len(bad_payload_audits)}")
bad_payload_audit = bad_payload_audits[0]
bad_payload_totals = bad_payload_audit["totals"]
if bad_payload_audit.get("universe_kind") != "constructor-field-getter":
    raise SystemExit(f"FAIL: expected constructor-field-getter audit, got {bad_payload_audit.get('universe_kind')}")
bad_payload_memento = bad_payload_audit["source_memento"]
if bad_payload_memento.get("source_function_name") != "BadPayload.__init__":
    raise SystemExit(f"FAIL: BadPayload source oracle should point at constructor: {bad_payload_memento!r}")
if bad_payload_memento.get("constructor_default_param_names") != ["original_error"]:
    raise SystemExit(f"FAIL: BadPayload source memento did not record the defaulted field: {bad_payload_memento!r}")
if "body_text" in bad_payload_memento or "ast_template" in bad_payload_memento:
    raise SystemExit("FAIL: BadPayload source memento embeds source/template body")
if bad_payload_totals.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: BadPayload.original_error source dig has unclassified source: totals={bad_payload_totals}")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Constant"
    and locus.get("ast_path") == "$.args.defaults[0]"
    and "default constructor argument emitted" in locus.get("reason", "")
    for locus in bad_payload_audit["loci"]
):
    raise SystemExit("FAIL: BadPayload.original_error default argument was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "AnnAssign"
    for locus in bad_payload_audit["loci"]
):
    raise SystemExit("FAIL: BadPayload.original_error field assignment was not warranted")
header_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.instance-field-universe"
    and "BadHeader" in audit.get("contract", {}).get("name", "")
]
if len(header_audits) != 1:
    raise SystemExit(f"FAIL: expected one BadHeader header audit, got {len(header_audits)}")
header_audit = header_audits[0]
header_totals = header_audit["totals"]
if header_audit.get("universe_kind") != "constructor-field-getter":
    raise SystemExit(f"FAIL: expected constructor-field-getter audit, got {header_audit.get('universe_kind')}")
if header_audit["source_memento"].get("source_function_name") != "BadHeader.__init__":
    raise SystemExit(f"FAIL: header source oracle should point at constructor: {header_audit['source_memento']!r}")
if header_totals.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: BadHeader.header source dig has unclassified source: totals={header_totals}")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "AnnAssign"
    and locus.get("line") == 85
    for locus in header_audit["loci"]
):
    raise SystemExit("FAIL: BadHeader.header field assignment was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "AnnAssign"
    and locus.get("line") == 89
    for locus in header_audit["loci"]
):
    raise SystemExit("FAIL: BadHeader.original_error field assignment was not accounted")
stdlib_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.delegation-universe"
    and audit.get("universe_kind") == "delegation-stdlib"
    and "_CompactJSON.loads" in audit.get("contract", {}).get("name", "")
]
if len(stdlib_audits) != 1:
    raise SystemExit(f"FAIL: expected one _CompactJSON.loads stdlib delegation audit, got {len(stdlib_audits)}")
stdlib_audit = stdlib_audits[0]
stdlib_totals = stdlib_audit["totals"]
if stdlib_audit["source_memento"].get("source_function_name") != "_CompactJSON.loads":
    raise SystemExit(f"FAIL: stdlib delegation source oracle should point at staticmethod: {stdlib_audit['source_memento']!r}")
if stdlib_totals.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: _CompactJSON.loads source dig has unclassified source: totals={stdlib_totals}")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Call"
    for locus in stdlib_audit["loci"]
):
    raise SystemExit("FAIL: _CompactJSON.loads stdlib call was not warranted")
stdlib_dumps_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.delegation-universe"
    and audit.get("universe_kind") == "delegation-stdlib"
    and "_CompactJSON.dumps" in audit.get("contract", {}).get("name", "")
]
if len(stdlib_dumps_audits) != 1:
    raise SystemExit(
        "FAIL: expected one _CompactJSON.dumps stdlib delegation audit, "
        f"got {len(stdlib_dumps_audits)}"
    )
stdlib_dumps_audit = stdlib_dumps_audits[0]
stdlib_dumps_totals = stdlib_dumps_audit["totals"]
stdlib_dumps_memento = stdlib_dumps_audit["source_memento"]
if stdlib_dumps_memento.get("source_function_name") != "_CompactJSON.dumps":
    raise SystemExit(
        "FAIL: stdlib dumps source oracle should point at staticmethod: "
        f"{stdlib_dumps_memento!r}"
    )
if "body_text" in stdlib_dumps_memento or "ast_template" in stdlib_dumps_memento:
    raise SystemExit("FAIL: _CompactJSON.dumps source memento embeds source/template body")
if stdlib_dumps_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: _CompactJSON.dumps source dig has unclassified source: "
        f"totals={stdlib_dumps_totals}"
    )
if not any(
    locus.get("status") == "support"
    and locus.get("ast_kind") == "Expr"
    and locus.get("line") in {16, 17}
    for locus in stdlib_dumps_audit["loci"]
):
    raise SystemExit("FAIL: _CompactJSON.dumps kwargs defaults were not accounted as support")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Return"
    and locus.get("line") == 18
    for locus in stdlib_dumps_audit["loci"]
):
    raise SystemExit("FAIL: _CompactJSON.dumps return was not warranted")
text_serializer_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.return-isinstance-universe"
    and "is_text_serializer" in audit.get("contract", {}).get("name", "")
]
if len(text_serializer_audits) != 1:
    raise SystemExit(
        "FAIL: expected one is_text_serializer return-isinstance audit, "
        f"got {len(text_serializer_audits)}"
    )
text_serializer_audit = text_serializer_audits[0]
text_serializer_totals = text_serializer_audit["totals"]
if text_serializer_audit.get("universe_kind") != "return-isinstance":
    raise SystemExit(
        "FAIL: expected return-isinstance audit, got "
        f"{text_serializer_audit.get('universe_kind')}"
    )
if (
    text_serializer_audit["source_memento"].get("source_function_name")
    != "is_text_serializer"
):
    raise SystemExit(
        "FAIL: is_text_serializer source oracle should point at function body: "
        f"{text_serializer_audit['source_memento']!r}"
    )
if text_serializer_totals.get("unclassified_source") != 0:
    raise SystemExit(
        "FAIL: is_text_serializer source dig has unclassified source: "
        f"totals={text_serializer_totals}"
    )
if "body_text" in text_serializer_audit["source_memento"] or "ast_template" in text_serializer_audit["source_memento"]:
    raise SystemExit("FAIL: is_text_serializer source memento embeds source/template body")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Return"
    for locus in text_serializer_audit["loci"]
):
    raise SystemExit("FAIL: is_text_serializer return was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Call"
    and "isinstance" in locus.get("reason", "")
    for locus in text_serializer_audit["loci"]
):
    raise SystemExit("FAIL: is_text_serializer isinstance call was not warranted")
package_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "python.package-source"
    and audit.get("package") == "itsdangerous"
]
if len(package_audits) != 1:
    raise SystemExit(f"FAIL: expected one itsdangerous package accounting audit, got {len(package_audits)}")
package_totals = package_audits[0]["totals"]
if package_totals.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: itsdangerous package audit still has unclassified source: {package_totals}")
if ledger.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: source ledger still has unclassified source: ledger={ledger}")
serializer_overload_loci = [
    locus for locus in package_audits[0]["loci"]
    if str(locus.get("file", "")).endswith("/serializer.py")
    and any(
        str(locus.get("ast_path", "")).startswith(f"$.module.body[12].body[{index}]")
        for index in range(4, 9)
    )
]
if not serializer_overload_loci:
    raise SystemExit("FAIL: serializer overload metadata loci missing from package audit")
serializer_overload_totals = Counter(locus.get("status") for locus in serializer_overload_loci)
if serializer_overload_totals.get("unclassified", 0):
    raise SystemExit(
        "FAIL: serializer overload metadata still has unclassified source: "
        f"{serializer_overload_totals}"
    )
if not any(
    locus.get("status") == "support"
    and "overload" in locus.get("reason", "")
    for locus in serializer_overload_loci
):
    raise SystemExit("FAIL: serializer overload declaration metadata was not support")
if not any(
    locus.get("status") == "inactive"
    and "overload" in locus.get("reason", "")
    for locus in serializer_overload_loci
):
    raise SystemExit("FAIL: serializer overload ellipsis body was not inactive")
if audit.get("universe_kind") != "no-suffix-chars":
    raise SystemExit(f"FAIL: expected no-suffix-chars audit, got {audit.get('universe_kind')}")
if "body_text" in audit["source_memento"] or "ast_template" in audit["source_memento"]:
    raise SystemExit("FAIL: source audit memento embeds source/template body")
mementos = result.get("sourceMementos") or []
roles = {m.get("role") for m in mementos}
if "python.translate-universe" not in roles:
    raise SystemExit(f"FAIL: lift report missing python source mementos: roles={sorted(str(r) for r in roles)}")
memento = next(m for m in mementos if m.get("role") == "python.translate-universe")
if not memento.get("claimName", "").endswith("::assertion") or not memento.get("contractName", "").endswith("::assertion"):
    raise SystemExit(f"FAIL: source memento does not link to assertion contract: {memento!r}")
if "body_text" in memento or "ast_template" in memento:
    raise SystemExit(f"FAIL: source memento embeds source/template body: {memento!r}")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Attribute"
    and locus.get("ast_path") == "$.body[2].value.func"
    for locus in audit["loci"]
):
    raise SystemExit("FAIL: rstrip AST path was not warranted")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "Attribute"
    and locus.get("ast_path") == "$.body[0].value.func"
    for locus in int_audit["loci"]
):
    raise SystemExit("FAIL: lstrip AST path was not warranted")
print(
    "source audit base64:",
    f"loci={totals['source_loci']}",
    f"warranted={totals['source_warranted']}",
    f"inactive={totals['source_inactive']}",
    f"support={totals.get('source_support', 0)}",
    f"refused={totals['source_refused']}",
    f"unclassified={totals['unclassified_source']}",
)
print(
    "source audit int_to_bytes:",
    f"loci={int_totals['source_loci']}",
    f"warranted={int_totals['source_warranted']}",
    f"inactive={int_totals['source_inactive']}",
    f"support={int_totals.get('source_support', 0)}",
    f"refused={int_totals['source_refused']}",
    f"unclassified={int_totals['unclassified_source']}",
)
print(
    "source audit base64_decode:",
    f"loci={base64_decode_totals['source_loci']}",
    f"warranted={base64_decode_totals['source_warranted']}",
    f"inactive={base64_decode_totals['source_inactive']}",
    f"support={base64_decode_totals.get('source_support', 0)}",
    f"refused={base64_decode_totals['source_refused']}",
    f"unclassified={base64_decode_totals['unclassified_source']}",
)
print(
    "source audit __getattr__:",
    f"loci={package_getattr_totals['source_loci']}",
    f"warranted={package_getattr_totals['source_warranted']}",
    f"inactive={package_getattr_totals['source_inactive']}",
    f"support={package_getattr_totals.get('source_support', 0)}",
    f"refused={package_getattr_totals['source_refused']}",
    f"unclassified={package_getattr_totals['unclassified_source']}",
)
print(
    "source audit NoneAlgorithm.get_signature:",
    f"loci={signature_totals['source_loci']}",
    f"warranted={signature_totals['source_warranted']}",
    f"inactive={signature_totals['source_inactive']}",
    f"support={signature_totals.get('source_support', 0)}",
    f"refused={signature_totals['source_refused']}",
    f"unclassified={signature_totals['unclassified_source']}",
)
print(
    "source audit HMACAlgorithm.digest_method:",
    f"loci={hmac_totals['source_loci']}",
    f"warranted={hmac_totals['source_warranted']}",
    f"inactive={hmac_totals['source_inactive']}",
    f"support={hmac_totals.get('source_support', 0)}",
    f"refused={hmac_totals['source_refused']}",
    f"unclassified={hmac_totals['unclassified_source']}",
)
print(
    "source audit Signer.key_derivation:",
    f"loci={signer_key_totals['source_loci']}",
    f"warranted={signer_key_totals['source_warranted']}",
    f"inactive={signer_key_totals['source_inactive']}",
    f"support={signer_key_totals.get('source_support', 0)}",
    f"refused={signer_key_totals['source_refused']}",
    f"unclassified={signer_key_totals['unclassified_source']}",
)
print(
    "source audit Signer.secret_key:",
    f"loci={signer_secret_key_totals['source_loci']}",
    f"warranted={signer_secret_key_totals['source_warranted']}",
    f"inactive={signer_secret_key_totals['source_inactive']}",
    f"support={signer_secret_key_totals.get('source_support', 0)}",
    f"refused={signer_secret_key_totals['source_refused']}",
    f"unclassified={signer_secret_key_totals['unclassified_source']}",
)
print(
    "source audit Signer.derive_key:",
    f"loci={signer_derive_totals['source_loci']}",
    f"warranted={signer_derive_totals['source_warranted']}",
    f"inactive={signer_derive_totals['source_inactive']}",
    f"support={signer_derive_totals.get('source_support', 0)}",
    f"refused={signer_derive_totals['source_refused']}",
    f"unclassified={signer_derive_totals['unclassified_source']}",
)
print(
    "source audit Serializer.signer_kwargs:",
    f"loci={serializer_kwargs_totals['source_loci']}",
    f"warranted={serializer_kwargs_totals['source_warranted']}",
    f"inactive={serializer_kwargs_totals['source_inactive']}",
    f"support={serializer_kwargs_totals.get('source_support', 0)}",
    f"refused={serializer_kwargs_totals['source_refused']}",
    f"unclassified={serializer_kwargs_totals['unclassified_source']}",
)
print(
    "source audit Serializer.load_payload:",
    f"loci={load_payload_totals['source_loci']}",
    f"warranted={load_payload_totals['source_warranted']}",
    f"inactive={load_payload_totals['source_inactive']}",
    f"support={load_payload_totals.get('source_support', 0)}",
    f"refused={load_payload_totals['source_refused']}",
    f"unclassified={load_payload_totals['unclassified_source']}",
)
print(
    "source audit URLSafeSerializerMixin.load_payload:",
    f"loci={urlsafe_load_payload_totals['source_loci']}",
    f"warranted={urlsafe_load_payload_totals['source_warranted']}",
    f"inactive={urlsafe_load_payload_totals['source_inactive']}",
    f"support={urlsafe_load_payload_totals.get('source_support', 0)}",
    f"refused={urlsafe_load_payload_totals['source_refused']}",
    f"unclassified={urlsafe_load_payload_totals['unclassified_source']}",
)
print(
    "source audit TimedSerializer.loads_unsafe:",
    f"loci={timed_loads_unsafe_totals['source_loci']}",
    f"warranted={timed_loads_unsafe_totals['source_warranted']}",
    f"inactive={timed_loads_unsafe_totals['source_inactive']}",
    f"support={timed_loads_unsafe_totals.get('source_support', 0)}",
    f"refused={timed_loads_unsafe_totals['source_refused']}",
    f"unclassified={timed_loads_unsafe_totals['unclassified_source']}",
)
print(
    "source audit Signer.validate:",
    f"loci={signer_validate_totals['source_loci']}",
    f"warranted={signer_validate_totals['source_warranted']}",
    f"inactive={signer_validate_totals['source_inactive']}",
    f"support={signer_validate_totals.get('source_support', 0)}",
    f"refused={signer_validate_totals['source_refused']}",
    f"unclassified={signer_validate_totals['unclassified_source']}",
)
print(
    "source audit Signer.unsign separator guard:",
    f"loci={separator_guard_totals['source_loci']}",
    f"warranted={separator_guard_totals['source_warranted']}",
    f"inactive={separator_guard_totals['source_inactive']}",
    f"support={separator_guard_totals.get('source_support', 0)}",
    f"refused={separator_guard_totals['source_refused']}",
    f"unclassified={separator_guard_totals['unclassified_source']}",
)
print(
    "source audit TimestampSigner.validate:",
    f"loci={timestamp_validate_totals['source_loci']}",
    f"warranted={timestamp_validate_totals['source_warranted']}",
    f"inactive={timestamp_validate_totals['source_inactive']}",
    f"support={timestamp_validate_totals.get('source_support', 0)}",
    f"refused={timestamp_validate_totals['source_refused']}",
    f"unclassified={timestamp_validate_totals['unclassified_source']}",
)
print(
    "source audit SigningAlgorithm.get_signature:",
    f"loci={abstract_signature_totals['source_loci']}",
    f"warranted={abstract_signature_totals['source_warranted']}",
    f"inactive={abstract_signature_totals['source_inactive']}",
    f"support={abstract_signature_totals.get('source_support', 0)}",
    f"refused={abstract_signature_totals['source_refused']}",
    f"unclassified={abstract_signature_totals['unclassified_source']}",
)
message_totals = {
    key: sum(audit["totals"][key] for audit in message_by_function.values())
    for key in (
        "source_loci",
        "source_warranted",
        "source_inactive",
        "source_support",
        "source_refused",
        "unclassified_source",
    )
}
print(
    "source audit BadData.__str__:",
    f"loci={message_totals['source_loci']}",
    f"warranted={message_totals['source_warranted']}",
    f"inactive={message_totals['source_inactive']}",
    f"support={message_totals.get('source_support', 0)}",
    f"refused={message_totals['source_refused']}",
    f"unclassified={message_totals['unclassified_source']}",
)
print(
    "source audit BadSignature.payload:",
    f"loci={payload_totals['source_loci']}",
    f"warranted={payload_totals['source_warranted']}",
    f"inactive={payload_totals['source_inactive']}",
    f"support={payload_totals.get('source_support', 0)}",
    f"refused={payload_totals['source_refused']}",
    f"unclassified={payload_totals['unclassified_source']}",
)
print(
    "source audit BadPayload.original_error:",
    f"loci={bad_payload_totals['source_loci']}",
    f"warranted={bad_payload_totals['source_warranted']}",
    f"inactive={bad_payload_totals['source_inactive']}",
    f"support={bad_payload_totals.get('source_support', 0)}",
    f"refused={bad_payload_totals['source_refused']}",
    f"unclassified={bad_payload_totals['unclassified_source']}",
)
print(
    "source audit BadHeader.header:",
    f"loci={header_totals['source_loci']}",
    f"warranted={header_totals['source_warranted']}",
    f"inactive={header_totals['source_inactive']}",
    f"support={header_totals.get('source_support', 0)}",
    f"refused={header_totals['source_refused']}",
    f"unclassified={header_totals['unclassified_source']}",
)
print(
    "source audit _CompactJSON.loads:",
    f"loci={stdlib_totals['source_loci']}",
    f"warranted={stdlib_totals['source_warranted']}",
    f"inactive={stdlib_totals['source_inactive']}",
    f"support={stdlib_totals.get('source_support', 0)}",
    f"refused={stdlib_totals['source_refused']}",
    f"unclassified={stdlib_totals['unclassified_source']}",
)
print(
    "source audit _CompactJSON.dumps:",
    f"loci={stdlib_dumps_totals['source_loci']}",
    f"warranted={stdlib_dumps_totals['source_warranted']}",
    f"inactive={stdlib_dumps_totals['source_inactive']}",
    f"support={stdlib_dumps_totals.get('source_support', 0)}",
    f"refused={stdlib_dumps_totals['source_refused']}",
    f"unclassified={stdlib_dumps_totals['unclassified_source']}",
)
print(
    "source audit is_text_serializer:",
    f"loci={text_serializer_totals['source_loci']}",
    f"warranted={text_serializer_totals['source_warranted']}",
    f"inactive={text_serializer_totals['source_inactive']}",
    f"support={text_serializer_totals.get('source_support', 0)}",
    f"refused={text_serializer_totals['source_refused']}",
    f"unclassified={text_serializer_totals['unclassified_source']}",
)
print(
    "source audit package:",
    f"loci={package_totals['source_loci']}",
    f"unclassified={package_totals['unclassified_source']}",
)
print(
    "source audit serializer overload metadata:",
    f"loci={len(serializer_overload_loci)}",
    f"support={serializer_overload_totals.get('support', 0)}",
    f"inactive={serializer_overload_totals.get('inactive', 0)}",
    f"unclassified={serializer_overload_totals.get('unclassified', 0)}",
)
PY
    rm -f "$report"
    return 1
  }
  rm -f "$report"
}

echo "== build the CLI =="
cargo build --manifest-path "$REPO/implementations/rust/Cargo.toml" -p sugar-cli --bin sugar >/dev/null || {
  echo "FAIL: sugar build"; exit 1; }
[ -x "$BIN" ] || { echo "FAIL: sugar binary missing at $BIN"; exit 1; }

run_twin() {
  local twin="$1" expect="$2"
  local dir="$HERE/$twin"
  echo
  echo "==================== twin: $twin (expect: $expect) ===================="
  rm -f "$dir"/blake3-512_*.proof 2>/dev/null
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/__pycache__" 2>/dev/null
  rm -f "$dir"/.prove*.json "$dir"/.verify*.json 2>/dev/null

  ( cd "$dir" && "$BIN" mint --out . ) >/dev/null || { echo "FAIL: mint ($twin)"; return 1; }
  ( cd "$dir" && "$BIN" verify --project . --json > .verify.json ) || true
  [ -s "$dir/.verify.json" ] || { echo "FAIL: no verify receipt ($twin)"; return 1; }

  EXPECT="$expect" TWIN="$twin" python3 - "$dir/.verify.json" <<'PY' || return 1
import json, os, sys
expect, twin = os.environ["EXPECT"], os.environ["TWIN"]
doc = json.load(open(sys.argv[1]))
found = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "base64_encode" in str(r.get("property", ""))
]
if not found:
    print(f"FAIL({twin}): no base64_encode property rows in receipt"); sys.exit(1)
statuses = {s for _, s in found}
print(f"rows({twin}):")
for n, s in found:
    print(f"  {s:14s} {n[:110]}")
ok_words = {"discharged", "proven", "consistent", "sat"}
bad_words = {"unsatisfied", "refused", "unsat", "contradictory", "inconsistent", "violation", "violated"}
if expect == "discharged":
    verdict_ok = statuses & ok_words and not (statuses & bad_words)
else:
    verdict_ok = bool(statuses & bad_words)
if not verdict_ok:
    print(f"FAIL({twin}): expected {expect}, statuses={sorted(statuses)}"); sys.exit(1)
decode = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "base64_decode" in str(r.get("property", ""))
]
if not decode:
    print(f"FAIL({twin}): no base64_decode property rows in receipt"); sys.exit(1)
decode_statuses = {s for _, s in decode}
print(f"base64_decode rows({twin}):")
for n, s in decode:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    decode_ok = decode_statuses & ok_words and not (decode_statuses & bad_words)
else:
    decode_ok = bool(decode_statuses & bad_words)
if not decode_ok:
    print(
        f"FAIL({twin}): expected base64_decode {expect}, "
        f"statuses={sorted(decode_statuses)}"
    )
    sys.exit(1)
package_getattr = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "test_package_getattr_missing_attr" in str(r.get("property", ""))
]
if not package_getattr:
    print(f"FAIL({twin}): no __getattr__ raises rows in receipt"); sys.exit(1)
package_getattr_statuses = {s for _, s in package_getattr}
print(f"__getattr__ rows({twin}):")
for n, s in package_getattr:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    package_getattr_ok = (
        package_getattr_statuses & ok_words
        and not (package_getattr_statuses & bad_words)
    )
else:
    package_getattr_ok = bool(package_getattr_statuses & bad_words)
if not package_getattr_ok:
    print(
        f"FAIL({twin}): expected __getattr__ {expect}, "
        f"statuses={sorted(package_getattr_statuses)}"
    )
    sys.exit(1)
derive = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "Signer.derive_key" in str(r.get("property", ""))
]
if not derive:
    print(f"FAIL({twin}): no Signer.derive_key property rows in receipt"); sys.exit(1)
derive_statuses = {s for _, s in derive}
print(f"derive_key rows({twin}):")
for n, s in derive:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    derive_ok = derive_statuses & ok_words and not (derive_statuses & bad_words)
else:
    derive_ok = bool(derive_statuses & bad_words)
if not derive_ok:
    print(
        f"FAIL({twin}): expected derive_key {expect}, "
        f"statuses={sorted(derive_statuses)}"
    )
    sys.exit(1)
serializer_kwargs = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "itsdangerous.serializer.Serializer@test_token_padding.py" in str(r.get("property", ""))
]
if not serializer_kwargs:
    print(f"FAIL({twin}): no Serializer constructor property rows in receipt"); sys.exit(1)
serializer_kwargs_statuses = {s for _, s in serializer_kwargs}
print(f"Serializer.signer_kwargs rows({twin}):")
for n, s in serializer_kwargs:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    signer_kwargs_ok = (
        serializer_kwargs_statuses & ok_words
        and not (serializer_kwargs_statuses & bad_words)
    )
else:
    signer_kwargs_ok = bool(serializer_kwargs_statuses & bad_words)
if not signer_kwargs_ok:
    print(
        f"FAIL({twin}): expected Serializer.signer_kwargs {expect}, "
        f"statuses={sorted(serializer_kwargs_statuses)}"
    )
    sys.exit(1)
load_payload = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "test_serializer_load_payload_bad_payload" in str(r.get("property", ""))
]
if not load_payload:
    print(f"FAIL({twin}): no Serializer.load_payload raises rows in receipt"); sys.exit(1)
load_payload_statuses = {s for _, s in load_payload}
print(f"Serializer.load_payload rows({twin}):")
for n, s in load_payload:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    load_payload_ok = load_payload_statuses & ok_words and not (load_payload_statuses & bad_words)
else:
    load_payload_ok = bool(load_payload_statuses & bad_words)
if not load_payload_ok:
    print(
        f"FAIL({twin}): expected Serializer.load_payload {expect}, "
        f"statuses={sorted(load_payload_statuses)}"
    )
    sys.exit(1)
urlsafe_load_payload = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if "test_urlsafe_load_payload_bad_payload" in str(r.get("property", ""))
]
if not urlsafe_load_payload:
    print(f"FAIL({twin}): no URLSafeSerializerMixin.load_payload raises rows in receipt"); sys.exit(1)
urlsafe_statuses = {s for _, s in urlsafe_load_payload}
print(f"URLSafeSerializerMixin.load_payload rows({twin}):")
for n, s in urlsafe_load_payload:
    print(f"  {s:14s} {n[:110]}")
if expect == "discharged":
    urlsafe_ok = urlsafe_statuses & ok_words and not (urlsafe_statuses & bad_words)
else:
    urlsafe_ok = bool(urlsafe_statuses & bad_words)
if not urlsafe_ok:
    print(
        f"FAIL({twin}): expected URLSafeSerializerMixin.load_payload {expect}, "
        f"statuses={sorted(urlsafe_statuses)}"
    )
    sys.exit(1)
validate_rows = [
    (r.get("property", ""), r.get("status", ""))
    for r in doc.get("rows", [])
    if ".validate@test_token_padding.py" in str(r.get("property", ""))
]
if len(validate_rows) != 2:
    print(f"FAIL({twin}): expected two validate rows, got {len(validate_rows)}")
    sys.exit(1)
print(f"validate rows({twin}):")
for n, s in validate_rows:
    print(f"  {s:14s} {n[:110]}")

def row_statuses(needle):
    statuses = {s for n, s in validate_rows if needle in str(n)}
    if not statuses:
        print(f"FAIL({twin}): no validate row matching {needle}")
        sys.exit(1)
    return statuses

signer_validate_statuses = row_statuses("itsdangerous.signer.Signer.validate")
timestamp_validate_statuses = row_statuses(
    "itsdangerous.timed.TimestampSigner.validate"
)
if twin == "bad":
    signer_validate_ok = bool(signer_validate_statuses & bad_words)
else:
    signer_validate_ok = (
        signer_validate_statuses & ok_words
        and not (signer_validate_statuses & bad_words)
    )
if not signer_validate_ok:
    print(
        f"FAIL({twin}): unexpected Signer.validate statuses="
        f"{sorted(signer_validate_statuses)}"
    )
    sys.exit(1)
timestamp_validate_ok = (
    timestamp_validate_statuses & ok_words
    and not (timestamp_validate_statuses & bad_words)
)
if not timestamp_validate_ok:
    print(
        f"FAIL({twin}): expected TimestampSigner.validate to discharge, "
        f"statuses={sorted(timestamp_validate_statuses)}"
    )
    sys.exit(1)
print(f"OK({twin}): {expect}")
PY
}

fail=0
audit_good_source || fail=1
run_twin good discharged || fail=1
run_twin bad refused || fail=1

echo
if [ "$fail" -ne 0 ]; then
  echo "==== itsdangerous-token-padding: FAIL ===="
  exit 1
fi
echo "==== itsdangerous-token-padding: PASS ===="
echo "the padded-token confusion refuted statically by one byte literal"
echo "(rstrip(b'=')) from itsdangerous' own source -- the real-name logo."
