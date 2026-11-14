#!/usr/bin/env bash
# The rust cargo-test WITNESS showcase: the pytest-witness story, in Rust.
#
#   lift/mint - `cargo test` runs the crate's suite; each test's pass/fail is
#               content-addressed into ONE witness package (bundle cid =
#               blake3(bundle bytes)). One .proof carries the witness-package
#               CONTRACT (custom evidence, tool="cargo-test") + the signed
#               WitnessPackageMemento (64-byte pointer + signature over the cid).
#   prove     - the custom evidence is settled by the rust verifier: the kit
#               resolves bundle bytes, then rust recomputes the pinned package
#               cid and reads every committed per-test outcome from the body.
#   verify    - the witness axis: rust asks the kit oracle to RESOLVE the bundle
#               body (package file, or re-run), blake3's the bytes ITSELF, and
#               compares to the pinned witness_cid. The oracle is untrusted.
#
# Two suites, because the witness package is whole-suite:
#   good/ - all tests pass  -> the package DISCHARGES.
#   bad/  - one test fails   -> the bundle still reproduces (honest run), but
#           discharge REFUSES on the all-passed check. You cannot witness a suite
#           right that runs wrong.
#
# Everything is kit-side; the .proof is the transport; rust stays proof-blind and
# recomputes the witness CID itself.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"

echo "== resolve the CLI + the cargo-test-witness kit binaries via sugarbin =="
SUGAR="$("$REPO/bin/sugarbin" --profile debug)"
BIN_DIR="$(dirname "$SUGAR")"
"$REPO/bin/sugarbin" --profile debug --bin witness_rpc >/dev/null
"$REPO/bin/sugarbin" --profile debug --bin discharge_cli >/dev/null

[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not built at $SUGAR"; exit 1; }
[ -x "$BIN_DIR/witness_rpc" ] || { echo "FAIL: witness_rpc not built"; exit 1; }
[ -x "$BIN_DIR/discharge_cli" ] || { echo "FAIL: discharge_cli not built"; exit 1; }

# Materialize the per-crate manifests with the absolute binary dir.
for suite in good bad; do
  mfin="$HERE/$suite/.sugar/lift/rust-cargo-test-witness/manifest.toml.in"
  mf="$HERE/$suite/.sugar/lift/rust-cargo-test-witness/manifest.toml"
  sed "s#@BIN_DIR@#$BIN_DIR#g" "$mfin" > "$mf"
done

# Clean any prior run artifacts so the witness package is rebuilt from scratch.
# Minted .proof files are named by their CID WITH a colon (blake3-512:...proof).
for suite in good bad; do
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" "$HERE/$suite/.sugar/witnesses" 2>/dev/null || true
  rm -rf "$HERE/$suite/target" 2>/dev/null || true
done

# json_field <json-file> <python-expr-over-`d`> : parse a CLI --json report.
pyget() { python3 "$REPO/tools/showcase/json_get.py" "$1" "$2"; }

write_lying_discharge() {
  local script="$1"
  cat > "$script" <<'SH'
#!/usr/bin/env sh
echo '{"verdict":"DISCHARGED","reason":"lying discharge regression"}'
SH
  chmod +x "$script"
}

run_suite() {
  local suite="$1" expect="$2"  # expect = DISCHARGE | REFUSE
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite (expect $expect) ===================="

  echo "-- mint: run the suite -> witness-package .proof --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null

  # Exactly one witness-package .proof should exist now (CID-named, colon form).
  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  echo "-- prove: discharge the custom evidence by recompute --"
  # NOTE: prove's PROCESS EXIT CODE is unreliable here -- a pure-witness proof has
  # zero call-site obligations, and report_exit_code() treats totalCallsites==0 as
  # a failure regardless of the witness verdict. So we read the witness-package
  # ROW's status from --json, which carries the real discharge/refuse verdict.
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json ) > "$prove_json" 2>/dev/null || true

  # The witness-package row's status. Status is lowercase: "discharged" on the
  # all-passed suite; "unsatisfied" when a per-test witness failed.
  local status
  status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows',[]) if 'witness-package' in (r.get('property','') or '')), 'MISSING')
")"
  echo "   witness-package row status: $status"

  # Step 9: prove decides the witness-package row from the package body the
  # proof states; a recomputed body carries `resolvedBy` on the row's witness
  # verification. No kit and no on-disk witness store is consulted.
  local resolved_by
  resolved_by="$(pyget "$prove_json" "
next((((r.get('verification') or {}).get('resolvedBy') or 'MISSING') for r in d.get('rows',[]) if 'witness-package' in (r.get('property','') or '')), 'MISSING')
" 2>/dev/null || echo PARSE_ERR)"
  echo "   witness package body recomputed by: $resolved_by"

  if [ "$expect" = "DISCHARGE" ]; then
    # The good suite: prove DISCHARGES the witness package from its body.
    if [ "$status" != "discharged" ]; then
      echo "FAIL[$suite]: expected the witness-package to DISCHARGE, got status=$status"
      exit 1
    fi
    if [ "$resolved_by" = "MISSING" ] || [ "$resolved_by" = "PARSE_ERR" ]; then
      echo "FAIL[$suite]: expected the witness package body in the proof to be recomputed, got $resolved_by"
      exit 1
    fi
    echo "OK[$suite]: passing suite discharges from the package body the proof states."
  else
    # The bad suite: prove REFUSES (a failing test refuses the whole package).
    # (The package body still recomputes -- the run was honest; the REFUSAL is
    #  the all-passed check on that body. That asymmetry is the point.)
    if [ "$status" = "discharged" ]; then
      echo "FAIL[$suite]: a suite with a FAILING test must NOT discharge, but status=discharged"
      exit 1
    fi
    if [ "$status" = "MISSING" ]; then
      echo "FAIL[$suite]: no witness-package row found in the prove report"
      exit 1
    fi
    echo "-- prove (LYING DISCHARGE): stdout says DISCHARGED, package body still has a failed outcome --"
    local lie="$dir/.sugar/lying-discharge.sh"
    write_lying_discharge "$lie"
    local lie_json="$dir/.prove_lie.json"
    ( cd "$dir" && SUGAR_WITNESS_DISCHARGE_CARGO_TEST="$lie" "$SUGAR" prove . --json ) > "$lie_json" 2>/dev/null || true
    local lie_status
    lie_status="$(pyget "$lie_json" "
next((r.get('status') for r in d.get('rows',[]) if 'witness-package' in (r.get('property','') or '')), 'MISSING')
")"
    echo "   lying-discharge witness-package row status: $lie_status"
    if [ "$lie_status" = "discharged" ]; then
      echo "FAIL[$suite]: lying discharge stdout flipped a failing witness package to discharged"
      exit 1
    fi
    echo "OK[$suite]: a failing test refuses the witness package (status=$status, not discharged)."
  fi
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "==================== SELF-CHECK PASSED ===================="
echo "good/ : passing suite -> witness package DISCHARGES + CID reproduces."
echo "bad/  : failing test  -> witness package REFUSED (cannot witness wrong-running code)."
[ -z "${SHOWCASE_SUBJECT_WITNESS:-}" ] || printf '%s\n' "${SHOWCASE_SUBJECT_ID:?}" > "$SHOWCASE_SUBJECT_WITNESS"
