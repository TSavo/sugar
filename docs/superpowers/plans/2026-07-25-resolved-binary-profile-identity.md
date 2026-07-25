# Resolved Binary Profile Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every authoritative Python package-suite report prove that its requested Sugar profile equals the resolved binary manifest profile.

**Architecture:** Extend the existing #6290 serialized suite identity with separate requested and resolved profile fields. The report plugin writes a provisional single-use authority pre-state; the post-serialization identity gate validates the fields and atomically transitions the artifact to either authoritative/resolved or provisional/unresolved. The workflow reads resolved testimony from `<binary>.sugarbin.json`, never from path spelling.

**Tech Stack:** Python 3 standard library, pytest plugin hooks, GitHub Actions YAML, JSON artifact contracts, Bash.

## Global Constraints

- Base every measurement and change on `df408100e74d6ca073a5a6641c9fde94f6822e6a`.
- Cite path-evident override refusal as #6282; #6276 is the sccache/incremental fix.
- Profiles are exactly `release` or `debug`.
- A missing manifest `profile` is `profile-manifest-predates-boundary`, never a mismatch.
- The only accepted authority pre-state is provisional/unverified with no crimes.
- Authority transition is one-way, single-shot, and atomically written with a same-directory temporary file plus `os.replace`.
- Missing authority is refused, never synthesized.
- Authoritative reports have no `crimes` key; provisional/unresolved reports replace `crimes` with the full current list.
- Own-baseline A/B governs; trunk CI at `df40810` is independently red.
- Run the full owning top-level `tests` package, not only the focused identity file.

---

### Task 1: Plant profile and authority discrimination teeth

**Files:**
- Modify: `tests/test_python_suite_identity_gate_twins.py`

**Interfaces:**
- Consumes: `python_suite_identity_gate.gate(report, require_commit)` and `python_suite_identity_gate.main(argv)`.
- Produces: `_report()` fixtures with `requestedBinaryProfile`, `resolvedBinaryProfile`, and the provisional/unverified authority pre-state; exact red/green laws for every new branch.

- [ ] **Step 1: Capture the full owning-package baseline at the design-only HEAD**

Run:

```bash
git rev-parse HEAD
python3 -m pytest tests -q -p no:cacheprovider -rf \
  --junitxml=/tmp/chucky-profile-identity-before.xml
```

Expected: record the terminal summary and exact failed/error node-ID set. Do not require green; this is the `df40810` own baseline.

- [ ] **Step 2: Extend the green report fixture with profile and authority identity**

Add to `_report()`:

```python
"requestedBinaryProfile": "release",
"resolvedBinaryProfile": "release",
"authority": {
    "status": "provisional",
    "profileIdentity": "unverified",
},
```

The existing `assert _crimes(_report()) == []` remains the green face.

- [ ] **Step 3: Add distinct profile field teeth**

Add:

```python
def test_profile_identity_presence_enumeration_and_equality():
    assert _crimes(_report()) == []

    missing_requested = _report()
    del missing_requested["requestedBinaryProfile"]
    crimes = _crimes(missing_requested)
    assert "crime=profile-identity-absent" in _crime_kinds(crimes)

    missing_resolved = _report()
    del missing_resolved["resolvedBinaryProfile"]
    crimes = _crimes(missing_resolved)
    assert "crime=profile-manifest-predates-boundary" in _crime_kinds(crimes)
    assert any("predates the profile identity boundary" in crime for crime in crimes)
    assert not any(
        crime.startswith("crime=profile-identity-mismatch") for crime in crimes
    )

    for field in ("requestedBinaryProfile", "resolvedBinaryProfile"):
        malformed = _report()
        malformed[field] = "fast"
        crimes = _crimes(malformed)
        assert "crime=profile-identity-malformed" in _crime_kinds(crimes)

    mismatch = _report(resolvedBinaryProfile="debug")
    crimes = _crimes(mismatch)
    assert "crime=profile-identity-mismatch" in _crime_kinds(crimes)
```

- [ ] **Step 4: Add single-shot authority transition teeth**

Add:

```python
def test_authority_prestate_is_single_shot_and_not_synthesized():
    assert _crimes(_report()) == []

    already = _report(
        authority={"status": "authoritative", "profileIdentity": "resolved"}
    )
    assert "crime=authority-already-decided" in _crime_kinds(_crimes(already))

    absent = _report()
    del absent["authority"]
    assert "crime=authority-object-absent" in _crime_kinds(_crimes(absent))

    stale = _report(
        authority={
            "status": "provisional",
            "profileIdentity": "unverified",
            "crimes": ["crime=old"],
        }
    )
    assert "crime=authority-stale-crimes" in _crime_kinds(_crimes(stale))
```

- [ ] **Step 5: Add serialized rewrite tests, including atomic replacement**

Add tests that write `_report()` to a temporary `suite-report.json`, invoke `gate.main`, and re-read it:

```python
def test_gate_atomically_writes_exact_authority_verdict():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "suite-report.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(_report(), handle)

        assert gate.main(["--report", path, "--require-commit", COMMIT]) == 0
        with open(path, encoding="utf-8") as handle:
            decided = json.load(handle)
        assert decided["authority"] == {
            "status": "authoritative",
            "profileIdentity": "resolved",
        }
        assert "crimes" not in decided["authority"]
        assert not [
            name for name in os.listdir(tmp) if name.startswith(".suite-report-")
        ]

        assert gate.main(["--report", path, "--require-commit", COMMIT]) == 1
        with open(path, encoding="utf-8") as handle:
            unchanged = json.load(handle)
        assert unchanged == decided
```

Add a provisional arm:

```python
def test_gate_replaces_provisional_crimes_with_full_current_list():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "suite-report.json")
        report = _report(resolvedBinaryProfile="debug")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle)

        assert gate.main(["--report", path, "--require-commit", COMMIT]) == 1
        with open(path, encoding="utf-8") as handle:
            decided = json.load(handle)
        authority = decided["authority"]
        assert authority["status"] == "provisional"
        assert authority["profileIdentity"] == "unresolved"
        assert authority["crimes"] == [
            crime.split(" ", 1)[0] for crime in gate.gate(report, COMMIT)
        ]
```

Add an absent-authority arm which asserts the file is byte-identical after refusal.

- [ ] **Step 6: Run the twins and verify the intended red state**

Run:

```bash
python3 tests/test_python_suite_identity_gate_twins.py
```

Expected: the new profile and authority tests fail because the production gate does not yet validate or rewrite these fields. Existing teeth remain green.

- [ ] **Step 7: Commit the red tests**

```bash
git add tests/test_python_suite_identity_gate_twins.py
git commit -m "test: require resolved profile suite identity" \
  --trailer "Co-authored-by: WOPR <evilgenius@nefariousplan.com>" \
  --trailer "Signed-off-by: WOPR <evilgenius@nefariousplan.com>"
```

---

### Task 2: Implement profile validation and atomic authority transition

**Files:**
- Modify: `tools/python_package_suite_report.py`
- Modify: `tools/python_suite_identity_gate.py`
- Modify: `tools/python_package_suite_summary.py`

**Interfaces:**
- Consumes: pytest options `--suite-requested-binary-profile` and `--suite-resolved-binary-profile`.
- Produces: top-level report fields `requestedBinaryProfile: str | None`, `resolvedBinaryProfile: str | None`, and `authority: dict[str, object]`; `gate()` crime list; atomic `_write_report(path, report)` transition.

- [ ] **Step 1: Add report plugin options**

In `pytest_addoption`, add:

```python
group.addoption(
    "--suite-requested-binary-profile",
    action="store",
    default=None,
    choices=("release", "debug"),
    metavar="PROFILE",
    help="Sugar profile requested by the suite",
)
group.addoption(
    "--suite-resolved-binary-profile",
    action="store",
    default=None,
    metavar="PROFILE",
    help="profile read from the resolved binary's .sugarbin.json manifest",
)
```

Do not give the resolved option a `choices` constraint: malformed manifest testimony must reach the identity gate and be recorded as provisional, not be converted into argparse prose.

- [ ] **Step 2: Serialize the provisional authority pre-state**

In `pytest_sessionfinish`, add:

```python
"requestedBinaryProfile": self.config.getoption(
    "--suite-requested-binary-profile"
),
"resolvedBinaryProfile": self.config.getoption(
    "--suite-resolved-binary-profile"
),
"authority": {
    "status": "provisional",
    "profileIdentity": "unverified",
},
```

The plugin does not infer either value from the binary path.

- [ ] **Step 3: Add authority pre-state validation**

In `tools/python_suite_identity_gate.py`, add:

```python
PROFILES = frozenset({"release", "debug"})


def _check_authority_prestate(report, crimes):
    authority = report.get("authority")
    if not isinstance(authority, dict):
        crimes.append(
            "crime=authority-object-absent illegal shape=suite-report.json has "
            "no authority object replacement=produce the report with the current "
            "suite plugin; the gate does not manufacture testimony"
        )
        return
    if authority.get("status") == "authoritative":
        crimes.append(
            "crime=authority-already-decided illegal shape=report was already "
            "decided replacement=gate each artifact exactly once"
        )
        return
    if authority.get("status") != "provisional" or authority.get(
        "profileIdentity"
    ) != "unverified":
        crimes.append(
            "crime=authority-prestate-malformed illegal shape=authority is not "
            "provisional/unverified replacement=start from the plugin's exact "
            "single-use pre-state"
        )
    if "crimes" in authority:
        crimes.append(
            "crime=authority-stale-crimes illegal shape=unverified report "
            "already carries crimes replacement=do not recycle a decided artifact"
        )
```

Call it first from `_check_identity`.

- [ ] **Step 4: Add profile validation with distinct missing branches**

Add:

```python
def _check_profile_identity(report, crimes):
    requested = report.get("requestedBinaryProfile")
    resolved_present = "resolvedBinaryProfile" in report
    resolved = report.get("resolvedBinaryProfile")

    if requested in (None, ""):
        crimes.append(
            "crime=profile-identity-absent illegal shape=no "
            "requestedBinaryProfile replacement=state the requested profile"
        )
    elif requested not in PROFILES:
        crimes.append(
            f"crime=profile-identity-malformed illegal shape=requested profile "
            f"{requested!r} replacement=profile is release or debug"
        )

    if not resolved_present or resolved in (None, ""):
        crimes.append(
            "crime=profile-manifest-predates-boundary illegal shape=resolved "
            "binary manifest has no profile replacement=this manifest predates "
            "the profile identity boundary; rebuild it"
        )
    elif resolved not in PROFILES:
        crimes.append(
            f"crime=profile-identity-malformed illegal shape=resolved profile "
            f"{resolved!r} replacement=profile is release or debug"
        )

    if requested in PROFILES and resolved in PROFILES and requested != resolved:
        crimes.append(
            f"crime=profile-identity-mismatch illegal shape=requested "
            f"{requested!r} != resolved {resolved!r} replacement=measure the "
            "profile the report claims"
        )
```

Call it after the authority pre-state check.

- [ ] **Step 5: Implement atomic single-shot report rewriting**

Add imports `os` and `tempfile`, then:

```python
def _crime_ids(crimes):
    return [crime.split(" ", 1)[0] for crime in crimes]


def _write_report_atomic(path, report):
    directory = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix=".suite-report-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
```

In the report CLI path:

- refuse missing authority without writing;
- refuse already-authoritative without writing;
- otherwise replace `authority` exactly:

```python
if crimes:
    report["authority"] = {
        "status": "provisional",
        "profileIdentity": "unresolved",
        "crimes": _crime_ids(crimes),
    }
else:
    report["authority"] = {
        "status": "authoritative",
        "profileIdentity": "resolved",
    }
_write_report_atomic(path, report)
```

Preserve the full human-readable crime output and nonzero exit on provisional.

- [ ] **Step 6: Render profile and authority fields in the summary**

Add summary lines:

```python
authority = report.get("authority") or {}
...
f"- authority: {_field(authority.get('status'))}"
f" / profile identity {_field(authority.get('profileIdentity'))}",
f"- Sugar profile: requested {_field(report.get('requestedBinaryProfile'))}"
f" / resolved {_field(report.get('resolvedBinaryProfile'))}",
```

Do not infer authority from the absence of crimes.

- [ ] **Step 7: Run standalone twins and verify green**

Run:

```bash
python3 tests/test_python_suite_identity_gate_twins.py
```

Expected: zero failing teeth. Re-running the CLI on the authoritative fixture must fail with `crime=authority-already-decided`.

- [ ] **Step 8: Commit the implementation**

```bash
git add tools/python_package_suite_report.py \
  tools/python_suite_identity_gate.py \
  tools/python_package_suite_summary.py
git commit -m "feat: gate suite authority on resolved profile" \
  --trailer "Co-authored-by: WOPR <evilgenius@nefariousplan.com>" \
  --trailer "Signed-off-by: WOPR <evilgenius@nefariousplan.com>"
```

---

### Task 3: Wire manifest-authenticated profile testimony into CI

**Files:**
- Modify: `.github/workflows/python-package-suite.yml`
- Modify: `tests/test_python_suite_identity_gate_twins.py`

**Interfaces:**
- Consumes: `profile` from `<resolved-binary>.sugarbin.json`.
- Produces: workflow outputs `requested-profile` and `resolved-profile`, pytest plugin arguments carrying both values, and a pre-pytest missing-field refusal.

- [ ] **Step 1: Add a workflow source-contract test**

Add a test that reads `.github/workflows/python-package-suite.yml` and asserts it contains:

```python
def test_workflow_carries_manifest_profile_into_suite_report():
    workflow = open(
        os.path.join(REPO_ROOT, ".github/workflows/python-package-suite.yml"),
        encoding="utf-8",
    ).read()
    assert 'requested_profile="release"' in workflow
    assert 'manifest.get("profile")' in workflow
    assert "predates the profile identity boundary; rebuild it" in workflow
    assert "--suite-requested-binary-profile=" in workflow
    assert "--suite-resolved-binary-profile=" in workflow
```

- [ ] **Step 2: Run the new contract test red**

Run:

```bash
python3 tests/test_python_suite_identity_gate_twins.py
```

Expected: only the new workflow source-contract test fails.

- [ ] **Step 3: Read manifest profile with a distinct missing-field refusal**

In the binary resolution step:

```bash
requested_profile="release"
sugar_bin="$(bin/sugarbin --profile "$requested_profile")"
...
resolved_profile="$(
  python3 - "$manifest" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
profile = manifest.get("profile")
if profile is None:
    print(
        "resolved binary manifest predates the profile identity boundary; rebuild it",
        file=sys.stderr,
    )
    raise SystemExit(3)
print(profile)
PY
)"
echo "requested-profile=$requested_profile" >> "$GITHUB_OUTPUT"
echo "resolved-profile=$resolved_profile" >> "$GITHUB_OUTPUT"
```

Keep the existing sourceStamp read and validation.

- [ ] **Step 4: Pass both values into the report plugin**

Add:

```bash
--suite-requested-binary-profile="$SUITE_REQUESTED_BINARY_PROFILE" \
--suite-resolved-binary-profile="$SUITE_RESOLVED_BINARY_PROFILE" \
```

and bind:

```bash
SUITE_REQUESTED_BINARY_PROFILE='${{ steps.binary.outputs.requested-profile }}' \
SUITE_RESOLVED_BINARY_PROFILE='${{ steps.binary.outputs.resolved-profile }}' \
```

- [ ] **Step 5: Run standalone twins green**

Run:

```bash
python3 tests/test_python_suite_identity_gate_twins.py
```

Expected: zero failing teeth, including workflow source contract.

- [ ] **Step 6: Commit workflow wiring**

```bash
git add .github/workflows/python-package-suite.yml \
  tests/test_python_suite_identity_gate_twins.py
git commit -m "ci: authenticate suite binary profile" \
  --trailer "Co-authored-by: WOPR <evilgenius@nefariousplan.com>" \
  --trailer "Signed-off-by: WOPR <evilgenius@nefariousplan.com>"
```

---

### Task 4: Full own-baseline verification and publication

**Files:**
- Verify: `tests/`
- Verify: all files changed by Tasks 1-3

**Interfaces:**
- Consumes: before JUnit receipt from Task 1.
- Produces: exact A/B node-ID comparison, clean diff, signed commits, pushed branch, and draft PR.

- [ ] **Step 1: Run the full owning top-level test package**

Run:

```bash
git rev-parse HEAD
python3 -m pytest tests -q -p no:cacheprovider -rf \
  --junitxml=/tmp/chucky-profile-identity-after.xml
```

Expected: capture terminal summary. Extract sorted failed/error node IDs from both JUnit files and require no additions outside the new intentionally red-before/green-after teeth. If the baseline was red, report retained red identities explicitly.

- [ ] **Step 2: Re-run standalone teeth and structural checks**

Run:

```bash
python3 tests/test_python_suite_identity_gate_twins.py
git diff --check origin/main...HEAD
git status --short
```

Expected: zero failing teeth, no whitespace errors, no uncommitted source changes.

- [ ] **Step 3: Verify commit trailers**

Run:

```bash
git log origin/main..HEAD --format=full
```

Expected: every commit carries matching `Co-authored-by` and `Signed-off-by` trailers for `WOPR <evilgenius@nefariousplan.com>`.

- [ ] **Step 4: Push the branch**

Run:

```bash
git push -u origin chucky/resolved-profile-identity
```

- [ ] **Step 5: Open a draft PR**

The PR body must state:

- manifest profile is authenticated testimony; #6282 is only the path-evident fast refusal;
- missing manifest profile and mismatch are distinct crimes;
- authority rewrite is one-way, single-shot, and atomic;
- authoritative reports have no crimes; provisional reports carry the exact full crime identifiers;
- `df40810` own-baseline A/B receipts and retained trunk reds;
- no claim that broadly red trunk CI is green.

Use:

```bash
env -u GH_TOKEN -u GITHUB_TOKEN gh pr create \
  --repo TSavo/sugar \
  --base main \
  --head chucky/resolved-profile-identity \
  --draft \
  --title "feat: authenticate suite binary profile identity" \
  --body-file /tmp/chucky-profile-identity-pr.md
```

- [ ] **Step 6: Verify the remote handoff**

Run:

```bash
env -u GH_TOKEN -u GITHUB_TOKEN gh pr view --repo TSavo/sugar \
  --json url,isDraft,state,headRefOid,baseRefName,files
```

Expected: OPEN, draft, base `main`, head equals local HEAD, and only the planned files are present.
