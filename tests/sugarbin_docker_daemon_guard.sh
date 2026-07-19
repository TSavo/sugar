#!/usr/bin/env bash
set -euo pipefail

# Twin for #5914: on battleaxe, `systemctl is-active docker` reports "active"
# even when /var/run/docker.sock is a dead symlink into Docker Desktop's WSL2
# shared sockets and nothing actually works -- a false-healthy reading.
# sugarbin must prove the daemon answers the real API (`docker info`) before
# routing any command through it, and must fail LOUDLY, attributing the real
# cause, instead of syncing the workspace and silently producing no result.

repo="${1:?usage: sugarbin_docker_daemon_guard.sh REPO_ROOT}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
fail() { echo "FAIL: $*" >&2; exit 1; }

# Fake ssh: `docker info` fails with the exact kind of message a dead-socket
# WSL2 host produces; anything else (rsync-adjacent mkdir/rm, wslpath, real
# docker run) succeeds so the test isolates the daemon-liveness gate.
cat >"$tmp/bin/ssh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_SSH_LOG"
case "$*" in
  *"docker info"*)
    echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?" >&2
    exit 1
    ;;
  *"wslpath -w"*)
    path="${*#*wslpath -w \'}"; path="${path%%\'*}"
    printf 'C:\\wsl%s\r\n' "${path//\//\\}"
    exit 0
    ;;
  *"'docker' 'run'"*)
    printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"
    ;;
esac
exit 0
SH
cat >"$tmp/bin/rsync" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_RSYNC_LOG"
exit 0
SH
chmod +x "$tmp/bin/"*
: >"$tmp/ssh.log"; : >"$tmp/rsync.log"; : >"$tmp/docker.log"

status=0
(cd "$repo/implementations/python" && PATH="$tmp/bin:$PATH" \
  BCARGO_SSH="$tmp/bin/ssh" BCARGO_RSYNC="$tmp/bin/rsync" \
  BCARGO_REMOTE_ROOT=/home/tsavo/remote/sugar-bcargo-daemon-guard \
  BCARGO_REAP_DAYS=0 \
  FAKE_SSH_LOG="$tmp/ssh.log" FAKE_RSYNC_LOG="$tmp/rsync.log" FAKE_DOCKER_LOG="$tmp/docker.log" \
  "$repo/bin/sugarbin" run --host bx --task python-unit -- -q) \
  >"$tmp/run.out" 2>"$tmp/run.err" || status=$?

[[ "$status" == 70 ]] || fail "unreachable daemon did not fail loudly (status=$status)"
grep -Fq 'crime=false-healthy-docker-daemon' "$tmp/run.err" \
  || fail "daemon failure is not named: $(cat "$tmp/run.err")"
grep -Fq 'Cannot connect to the Docker daemon' "$tmp/run.err" \
  || fail "real cause was not attributed: $(cat "$tmp/run.err")"
[[ ! -s "$tmp/docker.log" ]] \
  || fail "docker run was invoked despite the daemon being unreachable"
[[ ! -s "$tmp/run.out" ]] \
  || fail "a measurement result was produced despite the daemon being unreachable"

echo "PASS: sugarbin Docker daemon liveness guard contract"
