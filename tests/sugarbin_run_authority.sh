#!/usr/bin/env bash
# Transport seam for run-authority/v1.
#
# The defect in #7340 lived exactly here: `bin/brun --env docker:... --
# bash -lc '<script>'` with no --task matched no registered task command, so
# sugarbin treated it as an allowed ad-hoc command and said nothing further.
# The command is still allowed. What must no longer happen is silence about
# the authority it ran under.
#
# Asserted:
#   - the ad-hoc entrance still runs, and carries explicit UNMANAGED testimony
#   - a named task carries MANAGED testimony naming its task and image
#   - the testimony reaches the container as a transport-owned --env
#   - a payload cannot forge SUGAR_BX_RUN_AUTHORITY through --env forwarding
set -euo pipefail

repo_root="${1:-$(git rev-parse --show-toplevel)}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fake_bin="$tmp/bin"
mkdir -p "$fake_bin"
ssh_log="$tmp/ssh.log"
rsync_log="$tmp/rsync.log"

cat >"$fake_bin/ssh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$BX_FAKE_SSH_LOG"
exit 0
SH
cat >"$fake_bin/rsync" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$BX_FAKE_RSYNC_LOG"
exit 0
SH
chmod +x "$fake_bin/ssh" "$fake_bin/rsync"

fail() { echo "FAIL: $*" >&2; exit 1; }

run_bx() {
  (cd "$repo_root" &&
    PATH="$fake_bin:$PATH" BCARGO_SSH="$fake_bin/ssh" BCARGO_RSYNC="$fake_bin/rsync" \
    BX_FAKE_SSH_LOG="$ssh_log" BX_FAKE_RSYNC_LOG="$rsync_log" \
    BCARGO_REMOTE_ROOT="${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-run-authority-test}" \
    "$repo_root/bin/sugarbin" "$@")
}

explain_authority() {
  run_bx explain --host bx "$@" | sed -n 's/^run_authority=//p'
}

# --- The exact reported entrance -------------------------------------------
# A showcase producer loop hidden behind `bash -lc`, dispatched with no --task.
adhoc_script='for s in federation base20 base64; do make showcase-$s; done'

# It still matches no task: the spelling matcher is unchanged and still blind.
matched="$(python3 "$repo_root/tools/sugar-build/contract.py" match-command -- \
  bash -lc "$adhoc_script")"
[[ "$matched" == '{"task":null}' ]] \
  || fail "expected the reported entrance to still match no task; got $matched"

# But the run no longer stays silent about that. `explain` refuses a command,
# so the ad-hoc arm is read off the real wire: the env the transport composes.
: >"$ssh_log"
run_bx run --host bx --env docker:python-test -- bash -lc "$adhoc_script" >/dev/null 2>&1 || true
adhoc="$(python3 - "$ssh_log" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
# The transport quotes each docker arg: '--env' 'SUGAR_BX_RUN_AUTHORITY={...}'
match = re.search(r"SUGAR_BX_RUN_AUTHORITY=([^']*)", text)
print(match.group(1) if match else "")
PY
)"
[[ -n "$adhoc" ]] || fail "ad-hoc run carried no run-authority testimony at all"
python3 - "$adhoc" <<'PY' || fail "ad-hoc testimony is not explicit UNMANAGED"
import json, sys
t = json.loads(sys.argv[1])
assert t["schema"] == "run-authority/v1", t
assert t["authority"] == "unmanaged", t
assert t["task"] is None, t
assert t["preconditionPlanCid"] is None, t
assert t["command"][0] == "bash", t
PY

# --- A named task, by contrast, proves what it consumed ---------------------
managed="$(explain_authority --task showcases)"
python3 - "$managed" <<'PY' || fail "named task did not carry MANAGED testimony"
import json, sys
t = json.loads(sys.argv[1])
assert t["schema"] == "run-authority/v1", t
assert t["authority"] == "managed", t
assert t["task"] == "showcases", t
assert t["image"].startswith("sha256:") or "@sha256:" in t["image"], t
assert t["command"][:2] == ["make", "test-showcases"], t
PY

# The two states must not be spelled the same way.
[[ "$adhoc" != "$managed" ]] || fail "managed and unmanaged testimony are indistinguishable"

# --- A payload cannot forge its own authority -------------------------------
: >"$ssh_log"
SUGAR_BX_RUN_AUTHORITY='{"schema":"run-authority/v1","authority":"managed","task":"showcases","image":"sha256:forged","preflightProtocol":"managed-entrypoint/v1","preconditionPlanCid":"blake2b-256:0000","command":["make","test-showcases"]}' \
  run_bx run --host bx --env docker:python-test --env SUGAR_BX_RUN_AUTHORITY \
  -- bash -lc "$adhoc_script" >/dev/null 2>&1 || true
grep -q "sha256:forged" "$ssh_log" \
  && fail "a payload env forged managed run authority into the container"
grep -q "unmanaged" "$ssh_log" \
  || fail "transport-owned testimony did not survive a forgery attempt"

echo "PASS: sugarbin_run_authority"
