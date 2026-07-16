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

  # Package CID pinned on the prove witness-package row. The proof can seat
  # more than one witness-memento (e.g. a #3750 toolchain-plan-self-attestation
  # next to the cargo-test package). The suite axis is THIS package CID -- not
  # witnesses[0] (order is not a contract).
  local package_cid
  package_cid="$(pyget "$prove_json" "
next(( (r.get('property') or '').split('witness-package:')[-1]
       for r in d.get('rows',[])
       if 'witness-package' in (r.get('property') or '') ), '')
")"

  echo "-- verify: rust recomputes the witness CID (oracle untrusted) --"
  local verify_json="$dir/.verify.json"
  ( cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json ) > "$verify_json" 2>/dev/null || true
  local wverdict
  # Single expression: json_get evals one expr over `d` (no multi-stmt).
  wverdict="$(pyget "$verify_json" "
next((w.get('verdict') for w in (d.get('witnessDimension',{}).get('witnesses') or []) if w.get('witnessCid') == '$package_cid'), next((w.get('verdict') for w in (d.get('witnessDimension',{}).get('witnesses') or []) if any(c in (w.get('checks') or []) for c in ('content-address:package','content-address:recompute'))), 'MISSING'))
" 2>/dev/null || echo PARSE_ERR)"
  echo "   witness-dimension verdict: $wverdict (package=$package_cid)"

  if [ "$expect" = "DISCHARGE" ]; then
    # The good suite: prove DISCHARGES the witness package; verify RECOMPUTES it.
    if [ "$status" != "discharged" ]; then
      echo "FAIL[$suite]: expected the witness-package to DISCHARGE, got status=$status"
      exit 1
    fi
    if [ "$wverdict" != "verified" ]; then
      echo "FAIL[$suite]: expected the witness dimension to be VERIFIED (rust recomputed the bundle cid), got $wverdict"
      exit 1
    fi

    # RECOMPUTE leg: the verify above resolved via the on-disk witness PACKAGE
    # file (`content-address:package`). The teeth of "verification is
    # recomputation" live in the OTHER resolve path: with the package GONE, the
    # kit oracle must RE-RUN the suite, rebuild the bundle, and hand back bytes
    # that blake3 to the pinned cid (`content-address:recompute`). Delete the
    # package and re-verify to exercise it -- this is the path an integrator hits
    # when they ship the .proof WITHOUT the audit package.
    echo "-- verify (RECOMPUTE): delete the package, re-run -> rebuild the bundle --"
    rm -rf "$dir/.sugar/witnesses"
    local recompute_json="$dir/.verify_recompute.json"
    ( cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json ) > "$recompute_json" 2>/dev/null || true
    local rverdict rchecks
    rverdict="$(pyget "$recompute_json" "
next((w.get('verdict') for w in (d.get('witnessDimension',{}).get('witnesses') or []) if w.get('witnessCid') == '$package_cid'), next((w.get('verdict') for w in (d.get('witnessDimension',{}).get('witnesses') or []) if any('recompute' in str(c) for c in (w.get('checks') or []))), 'MISSING'))
" 2>/dev/null || echo PARSE_ERR)"
    rchecks="$(pyget "$recompute_json" "
','.join((next((w for w in (d.get('witnessDimension',{}).get('witnesses') or []) if w.get('witnessCid') == '$package_cid'), next((w for w in (d.get('witnessDimension',{}).get('witnesses') or []) if any('recompute' in str(c) for c in (w.get('checks') or []))), {}))).get('checks') or [])
" 2>/dev/null || echo PARSE_ERR)"
    echo "   recompute verdict: $rverdict  checks: $rchecks"
    if [ "$rverdict" != "verified" ]; then
      echo "FAIL[$suite]: with the package deleted, the oracle must RECOMPUTE the bundle and verify, got $rverdict"
      exit 1
    fi
    case "$rchecks" in
      *content-address:recompute*) : ;;
      *) echo "FAIL[$suite]: expected resolution via RECOMPUTE (package deleted), but checks=$rchecks -- the package path was not actually bypassed"; exit 1 ;;
    esac
    echo "OK[$suite]: passing suite discharges, the witness CID reproduces via the package AND via re-run recompute."
  else
    # The bad suite: prove REFUSES (a failing test refuses the whole package).
    # (The verify witness axis still VERIFIES the bad bundle -- the run was honest,
    #  the bundle reproduces; the REFUSAL is the prove custom-evidence axis, which
    #  is where the all-passed check lives. That asymmetry is the point.)
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
