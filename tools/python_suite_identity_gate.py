"""Identity gate for the authoritative Python-package-suite artifact.

WHAT WENT WRONG WITHOUT IT
--------------------------
Suite run 30175741263 at main d94f67a31 concluded `success` while publishing:

    sourceStamp        : {"unavailable": "CalledProcessError: Command '[...]"}
    testExtraInputHash : None
    suite-report.json  : no commit, no sourceStamp

Its counts were perfectly conserved -- 1212 collected, 1212 verdicts, 1063
passed, 132 failed, 5 error, 12 skipped, 0 collectionError, 0 notReported. That
run is a COMPLETE BUT IDENTITY-UNRESOLVED measurement: attended, conserved, and
not authoritative, because nothing in it proves which authenticated source and
which test-input universe produced those verdicts.

The reason nothing fired is not that a check was missing a case. It is that
`{"unavailable": ...}` is a non-empty dict, so it passed every truthiness test a
null would have failed -- including the summary's own
`(identity.get('sourceStamp') or {}).get('value')`, whose `or {}` catches None
and waves an excuse through. A marker that downstream code treats as a value is
the defect. This gate therefore has no notion of a "field that says why it is
missing": an unavailable marker anywhere under identity is UNRESOLVED.

WHAT IT CHECKS -- and it checks the ARTIFACT, not a variable
------------------------------------------------------------
This runs on `suite-report.json` as serialized, after the sweep, before the
artifact is published. A populated intermediate that never reached the file is
exactly the loss this ordering catches.

  1. measuredCommit present and equal to --require-commit.
  2. sourceStamp resolved, well-formed `blake3-512_<128 hex>`, matching the
     embedded environment identity.
  3. testExtraInputHash non-null, 64 hex, matching the embedded identity, and
     the declared `[test]` extra it covers is non-empty.
  4. environmentIdentityHash present and matching the embedded identity.
  5. no unavailable marker anywhere in the report.
  6. testimony agrees: measuredCommit vs runnerIdentity.githubSha, and
     sourceStamp vs binarySourceStamp (the stamp the resolved binary's
     .sugarbin.json manifest actually carries).
  7. collection and verdict conservation: every collected node has exactly one
     verdict, every count equals len() of the list it summarises.

Exit 0 only when every one of those holds. Exit 1 names every failure at once,
because "fix this, re-run, learn the next one" is how an identity defect takes
five runs to surface.

Usage:
    python3 tools/python_suite_identity_gate.py \
        --report suite-report.json --require-commit "$GITHUB_SHA"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile

STAMP_PATTERN = re.compile(r"blake3-512_[0-9a-f]{128}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{7,40}")
PROFILES = frozenset({"release", "debug"})

# The fields that make a report authoritative. Absent, malformed or marked
# unavailable, any one of them makes the artifact a provisional receipt.
IDENTITY_FIELDS = (
    "measuredCommit",
    "sourceStamp",
    "testExtraInputHash",
    "environmentIdentityHash",
)

# Keys that mean "we could not resolve this", in any nesting. The whole point
# is that these never read as values.
UNAVAILABLE_KEYS = ("unavailable", "unresolved")


def unavailable_marker(node, path="$"):
    """Return the JSON path of the first unavailable marker, or None.

    Deep, not top-level: the run that started this hid its marker two levels
    down, inside a field whose parent object was perfectly well-formed.
    """
    if isinstance(node, dict):
        for key in UNAVAILABLE_KEYS:
            if key in node:
                return f"{path}.{key}"
        for key, value in node.items():
            found = unavailable_marker(value, f"{path}.{key}")
            if found is not None:
                return found
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found = unavailable_marker(value, f"{path}[{index}]")
            if found is not None:
                return found
    return None


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


def _check_identity(report, require_commit, crimes):
    _check_authority_prestate(report, crimes)
    _check_profile_identity(report, crimes)
    marker = unavailable_marker(report)
    if marker is not None:
        crimes.append(
            f"crime=identity-unresolved illegal shape=unavailable marker at "
            f"{marker} replacement=resolve the field; an excuse is not a value"
        )

    for field in IDENTITY_FIELDS:
        if report.get(field) in (None, "", {}, []):
            crimes.append(
                f"crime=identity-absent illegal shape=suite-report.json has no "
                f"`{field}` replacement=the report must carry its own identity, "
                f"not point at a second file for it"
            )

    identity = report.get("environmentIdentity")
    if not isinstance(identity, dict) or not identity:
        crimes.append(
            "crime=identity-absent illegal shape=no embedded environmentIdentity "
            "replacement=embed the environment identity the sweep ran under"
        )
        identity = {}

    stamp = report.get("sourceStamp")
    if stamp is not None and not STAMP_PATTERN.fullmatch(str(stamp)):
        crimes.append(
            f"crime=identity-malformed illegal shape=sourceStamp {stamp!r} is not "
            f"blake3-512_<128 hex> replacement=record the stamp bin/sugarbin "
            f"resolves the binary by, not a digest of our own choosing"
        )
    embedded_stamp = (identity.get("sourceStamp") or {}).get("value")
    if stamp is not None and embedded_stamp is not None and stamp != embedded_stamp:
        crimes.append(
            f"crime=contradictory-testimony illegal shape=report sourceStamp "
            f"{stamp!r} != embedded identity sourceStamp {embedded_stamp!r} "
            f"replacement=one source universe per measurement"
        )

    extras_hash = report.get("testExtraInputHash")
    if extras_hash is not None and not SHA256_PATTERN.fullmatch(str(extras_hash)):
        crimes.append(
            f"crime=identity-malformed illegal shape=testExtraInputHash "
            f"{extras_hash!r} is not 64 hex replacement=hash the declared "
            f"dependency authority"
        )
    authority = identity.get("dependencyAuthority") or {}
    embedded_extras = authority.get("testExtraInputHash")
    if (
        extras_hash is not None
        and embedded_extras is not None
        and extras_hash != embedded_extras
    ):
        crimes.append(
            f"crime=contradictory-testimony illegal shape=report "
            f"testExtraInputHash {extras_hash!r} != embedded "
            f"{embedded_extras!r} replacement=one test-input universe per "
            f"measurement"
        )
    declared_test = ((authority.get("declared") or {}).get("optional-dependencies") or {}).get(
        "test"
    )
    if identity and not declared_test:
        crimes.append(
            "crime=identity-covers-nothing illegal shape=testExtraInputHash "
            "covers an empty or absent [test] extra replacement=a hash of no "
            "declared extras does not identify a test-input universe"
        )

    env_hash = report.get("environmentIdentityHash")
    embedded_env = identity.get("environmentIdentityHash")
    if env_hash is not None and embedded_env is not None and env_hash != embedded_env:
        crimes.append(
            f"crime=contradictory-testimony illegal shape=report "
            f"environmentIdentityHash {env_hash!r} != embedded {embedded_env!r} "
            f"replacement=copy the identity that ran, or do not copy it"
        )

    commit = report.get("measuredCommit")
    if commit is not None and not COMMIT_PATTERN.fullmatch(str(commit)):
        crimes.append(
            f"crime=identity-malformed illegal shape=measuredCommit {commit!r} "
            f"is not a git object name replacement=record the measured commit"
        )
    if require_commit and commit is not None and commit != require_commit:
        crimes.append(
            f"crime=contradictory-testimony illegal shape=measuredCommit "
            f"{commit!r} != the commit this job checked out {require_commit!r} "
            f"replacement=measure the commit you are reporting for"
        )
    runner_sha = (report.get("runnerIdentity") or {}).get("githubSha")
    if commit is not None and runner_sha and commit != runner_sha:
        crimes.append(
            f"crime=contradictory-testimony illegal shape=measuredCommit "
            f"{commit!r} != runnerIdentity.githubSha {runner_sha!r} "
            f"replacement=two commits cannot both be the measured one"
        )

    binary_stamp = report.get("binarySourceStamp")
    if not binary_stamp:
        crimes.append(
            "crime=identity-absent illegal shape=no binarySourceStamp "
            "replacement=read sourceStamp from the resolved binary's "
            "<binary>.sugarbin.json manifest; the source identity must be the "
            "one the MEASURED BINARY has, not one we recomputed beside it"
        )
    elif stamp is not None and binary_stamp != stamp:
        crimes.append(
            f"crime=contradictory-testimony illegal shape=environment "
            f"sourceStamp {stamp!r} != measured binary sourceStamp "
            f"{binary_stamp!r} replacement=the suite must run the binary its "
            f"identity describes"
        )


def _check_conservation(report, crimes):
    conservation = report.get("conservation")
    if not isinstance(conservation, dict) or not conservation:
        crimes.append(
            "crime=conservation-absent illegal shape=suite-report.json states no "
            "conservation totals replacement=state collected/verdict totals in "
            "the artifact itself"
        )
        return

    collected = report.get("collectedNodeIds")
    if not isinstance(collected, list):
        crimes.append(
            "crime=conservation-absent illegal shape=no collectedNodeIds list "
            "replacement=the node-ID lists are the evidence"
        )
        return

    if conservation.get("collected") != len(collected):
        crimes.append(
            f"crime=conservation-broken illegal shape=conservation.collected "
            f"{conservation.get('collected')} != len(collectedNodeIds) "
            f"{len(collected)} replacement=every count is len() of a list "
            f"shipped beside it"
        )

    buckets = conservation.get("buckets") or {}
    axis_lists = {
        "passed": "passedNodeIds",
        "failed": "failedNodeIds",
        "error": "errorNodeIds",
        "skipped": "skippedNodeIds",
        "xfailed": "xfailedNodeIds",
        "xpassed": "xpassedNodeIds",
        "notReported": "notReportedNodeIds",
    }
    total = 0
    for axis, list_key in axis_lists.items():
        node_ids = report.get(list_key)
        if not isinstance(node_ids, list):
            crimes.append(
                f"crime=conservation-absent illegal shape=no {list_key} list "
                f"replacement=ship the evidence, not only its count"
            )
            continue
        if buckets.get(axis) != len(node_ids):
            crimes.append(
                f"crime=conservation-broken illegal shape=conservation.buckets."
                f"{axis} {buckets.get(axis)} != len({list_key}) {len(node_ids)} "
                f"replacement=derive counts from the lists"
            )
        total += len(node_ids)

    if total != len(collected):
        crimes.append(
            f"crime=conservation-broken illegal shape=verdict buckets sum to "
            f"{total} over {len(collected)} collected node IDs replacement=every "
            f"collected node gets exactly one verdict, including notReported"
        )

    not_reported = len(report.get("notReportedNodeIds") or [])
    if conservation.get("verdicts") != len(collected) - not_reported:
        crimes.append(
            f"crime=conservation-broken illegal shape=conservation.verdicts "
            f"{conservation.get('verdicts')} != collected {len(collected)} minus "
            f"notReported {not_reported} replacement=a collected node either got "
            f"a verdict or is named in notReportedNodeIds"
        )

    counts = report.get("counts") or {}
    for axis, list_key in axis_lists.items():
        node_ids = report.get(list_key)
        if isinstance(node_ids, list) and counts.get(axis) != len(node_ids):
            crimes.append(
                f"crime=conservation-broken illegal shape=counts.{axis} "
                f"{counts.get(axis)} != len({list_key}) {len(node_ids)} "
                f"replacement=one number per fact"
            )


def gate(report, require_commit=None):
    """Return the list of crimes. Empty list means authoritative."""
    crimes = []
    _check_identity(report, require_commit, crimes)
    _check_conservation(report, crimes)
    return crimes


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


def gate_environment_identity(identity):
    """The same law, applied to environment-identity.json on its own.

    Checked where it is MINTED as well as where it is consumed: an identity
    that leaves the minting step already unresolved would otherwise travel to
    a job that has no way to tell a resolved field from a populated excuse.
    """
    crimes = []
    marker = unavailable_marker(identity)
    if marker is not None:
        crimes.append(
            f"crime=identity-unresolved illegal shape=unavailable marker at "
            f"{marker} replacement=resolve the field; an excuse is not a value"
        )
    stamp = (identity.get("sourceStamp") or {}).get("value")
    if not stamp or not STAMP_PATTERN.fullmatch(str(stamp)):
        crimes.append(
            f"crime=identity-malformed illegal shape=sourceStamp {stamp!r} is not "
            f"blake3-512_<128 hex> replacement=mint with cargo on PATH"
        )
    authority = identity.get("dependencyAuthority") or {}
    extras_hash = authority.get("testExtraInputHash")
    if not extras_hash or not SHA256_PATTERN.fullmatch(str(extras_hash)):
        crimes.append(
            f"crime=identity-malformed illegal shape=testExtraInputHash "
            f"{extras_hash!r} is not 64 hex replacement=hash the declared "
            f"dependency authority"
        )
    if not ((authority.get("declared") or {}).get("optional-dependencies") or {}).get(
        "test"
    ):
        crimes.append(
            "crime=identity-covers-nothing illegal shape=testExtraInputHash covers "
            "an empty or absent [test] extra replacement=declare the extras the "
            "suite may import"
        )
    if not identity.get("environmentIdentityHash"):
        crimes.append(
            "crime=identity-absent illegal shape=no environmentIdentityHash "
            "replacement=two runs are comparable only through this hash"
        )
    return crimes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", help="suite-report.json AS UPLOADED")
    parser.add_argument(
        "--environment-identity",
        help="environment-identity.json, checked at the minting step",
    )
    parser.add_argument(
        "--require-commit",
        default=None,
        help="the commit this job checked out; report must agree with it",
    )
    args = parser.parse_args(argv)
    path = args.report or args.environment_identity
    if not path or (args.report and args.environment_identity):
        parser.error("pass exactly one of --report / --environment-identity")

    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as exc:
        print(
            f"crime=artifact-unreadable owner=tools/python_suite_identity_gate.py "
            f"illegal shape={path}: {type(exc).__name__}: {exc} "
            f"replacement=publish a readable suite report or publish nothing",
            file=sys.stderr,
        )
        return 1

    if args.environment_identity:
        crimes = gate_environment_identity(document)
        if crimes:
            print("### Environment identity: UNRESOLVED\n")
            for crime in crimes:
                print(f"- `{crime}`")
                print(f"::error::{crime}", file=sys.stderr)
            return 1
        print(
            "### Environment identity resolved\n\n"
            f"- sourceStamp: `{(document.get('sourceStamp') or {}).get('value')}`\n"
            f"- testExtraInputHash: "
            f"`{(document.get('dependencyAuthority') or {}).get('testExtraInputHash')}`\n"
            f"- environmentIdentityHash: `{document.get('environmentIdentityHash')}`"
        )
        return 0

    report = document
    crimes = gate(report, args.require_commit)
    authority = report.get("authority")
    authority_is_exact_prestate = authority == {
        "status": "provisional",
        "profileIdentity": "unverified",
    }
    if authority_is_exact_prestate:
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
    if crimes:
        print("### Suite identity gate: UNRESOLVED — not authoritative\n")
        for crime in crimes:
            print(f"- `{crime}`")
            print(f"::error::{crime}", file=sys.stderr)
        print(
            "\nThis measurement may be complete and conserved. It is not "
            "authoritative: it does not prove which authenticated source and "
            "test-input universe produced these verdicts."
        )
        return 1

    print("### Suite identity gate: R_identity = 0\n")
    print(f"- measuredCommit: `{report.get('measuredCommit')}`")
    print(f"- sourceStamp: `{report.get('sourceStamp')}`")
    print(f"- binarySourceStamp: `{report.get('binarySourceStamp')}` (agrees)")
    print(f"- testExtraInputHash: `{report.get('testExtraInputHash')}`")
    print(f"- environmentIdentityHash: `{report.get('environmentIdentityHash')}`")
    conservation = report.get("conservation") or {}
    print(
        f"- conservation: `{conservation.get('collected')}` collected, "
        f"`{conservation.get('verdicts')}` verdicts, buckets sum to collected"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
