#!/usr/bin/env python3
"""The nine-step lane: every file of a pinned corpus through real mint + prove.

One script for every corpus (pandas, numpy, ...). A corpus is a package
directory and a label; nothing here knows which package it is reading.

Seat mode (one slice of the corpus):

    python tools/nine_step_lift_lane.py --corpus-root ROOT --label LABEL \\
        --slice I/K --out-dir DIR

A seat runs in two phases, the way two packages federate
(examples/python-base64-federation/run.sh): every module mints its own
``.proof``, then each module is proved with the proofs it imports staged in
``.sugar/imports/``, so a call into another module of the same corpus joins
that module's contract at step 9 instead of standing unbound.

1. MINT. For each enrolled file of slice I of K, the file alone is staged in
   its own project directory at its package-relative path and the shipping
   binary runs ``sugar mint`` (steps 1 to 8, the packaged ``.proof``) and
   ``sugar dump --json`` (reads the members the proof states). The proof is
   kept in ``DIR/store/<file>/`` and one JSON row per file is appended to
   ``DIR/minted.jsonl``. A file alone mints the same symbols it would mint
   inside the whole package: the module name is spelled from the path
   (``import_binding.module_name_for_path``), and the lifter never opens an
   imported module.
2. PROVE. For each minted file, a fresh project holds the file's source, its
   own ``.proof`` at the root, and in ``.sugar/imports/`` every same-corpus
   ``.proof`` that answers one of its call edges (a ``bridge`` member whose
   ``sourceSymbol`` is the edge's symbol and whose target is a contract of
   that proof). ``sugar prove`` (step 9) reads exactly those files
   (``load_all_proofs::run_prove_inputs``) and joins each unanswered call
   member to the bridge stating its symbol
   (``consistency::collect_ambient_posts``). The final row is appended to
   ``DIR/rows.jsonl``.

A re-run of the same seat resumes: files with a final row are skipped, and a
file minted earlier (its proof still in the store) is not minted again.

How a seat spends its wall (#8416 follow-up, run 43960179946 took 3 h and
left 822 of 1421 pandas files without a row):

* Files run in parallel inside the seat, in both phases: ``--workers`` at
  once (default: the CPUs this process may use, bounded by available memory).
  A new file starts only while ``MemAvailable`` stays above
  ``--mem-floor-gb`` and the 1-minute load stays under ``--max-load`` x CPUs
  (one file always runs, so the seat never stalls). The lane's processes raise
  their own ``oom_score_adj``, so under memory pressure the kernel takes a
  lane file (re-run once, then recorded) before it takes the runner.
* The slowest files start first: ``--prior`` names rows.jsonl files (or
  directories holding them) from an earlier run, used ONLY to order this
  seat's work (longest first, by the earlier mint seconds in phase 1 and the
  earlier prove seconds in phase 2) and to size phase 2's reservation; no
  result is carried from them. A file the prior has not seen is estimated
  from its size.
* The per-file ceiling (``--file-cap``, the product's 300 s) is one budget
  for the file: ``sugar mint`` gets all of it and ``sugar prove`` gets what
  mint left. ``sugar dump`` is the instrument reading the proof and has its
  own small cap. Every command runs in its own process group and the whole
  group is killed when the command ends or times out, so a kit plugin or
  solver never outlives its file.
* ``--seat-budget S``: phase 1 starts no mint after S minus the reservation
  for phase 2 (the prior's prove seconds over the workers, or half of S with
  no prior) minus one file ceiling; phase 2 starts no prove after S minus one
  file ceiling. A file never minted has no row and is counted missing by the
  join (never invented). A file minted but never proved gets its row (its
  mint and members are real) with ``prove.error = "unreached"``.
* ``--profile-timeouts N`` (instrument only): every phase-1 mint runs with
  the kit's stack sampler on (``SUGAR_KIT_PROFILE_DIR``,
  ``sugar_lift_py_tests.kit_sample_profile``), which rewrites its aggregate
  every few seconds, so the profile survives the kill at the kit's response
  deadline or the file ceiling. Up to N files whose mint stalled keep theirs
  in ``DIR/profiles/<file>/``, one row per file in ``DIR/profiles.jsonl``
  (rc, seconds, top frames); every other file's profile is removed. The
  profile is the very mint the row measures: no file is minted twice, so no
  profile waits on the seat budget (the lane at 13e3413ad reached prove's
  last start before a single re-mint, and uploaded none).
  ``rows.jsonl`` and every count are untouched.

Every row carries ``status``: ``lifted``, ``refused``, ``timeout`` (mint hit
the file ceiling, or the kit's own plugin transport deadline), or ``crash``
(a panic, a signal, or the instrument's own failure). ``status`` is a label
on the row; the counts below are computed exactly as before.

Join mode (all seats):

    python tools/nine_step_lift_lane.py --join DIR1 DIR2 ... --label LABEL \\
        --enrolled N --out SUMMARY.json --refusals REFUSALS.json \\
        [--edge-misses EDGE_MISSES.json]

writes SUMMARY.json and REFUSALS.json and prints one line:

    LABEL_lift_files=M/N LABEL_lift_funcs=F/T LABEL_refused=R

then the edge line:

    LABEL_edges: corpus=B/C cross_module=XB/X same_module=SB/S missed=M ...

Count mode: ``--corpus-root ROOT --count`` prints the enrolled file count.

WHAT THE NUMBERS MEAN

* Enrolled files: every ``*.py`` under the corpus root, by the one
  enumeration the kit itself uses (``SourceTree.paths``: sorted, no
  ``__pycache__``). Tests are enrolled exactly as the pandas corpus enrolls
  them: nothing is excluded.
* A file is LIFTED when mint packaged a ``.proof`` for it and that proof
  states no refusal (no ``undecided`` member whose reason is ``refused``).
  An ``undecided`` member whose reason is ``unanswered`` is a call edge no
  contract in this proof answers; whether it binds is the edge count below,
  never a refusal.
* REFUSED counts named refusals: every ``undecided`` member with a
  ``refused`` reason (a function, class or module body the lifter refuses
  by name, with its owner), plus one per file for which mint packaged no
  proof at all (owner ``mint-exit-<rc>`` or ``mint-timeout``). Such a row
  carries ``diagnostic``: the kit's JSON-RPC error read whole from mint's
  output (``owner``, ``blame``, ``observed``, ``requested``, ``fix``,
  ``exceptionType``), so the refusal that killed the file is named.
* Functions: the denominator is every ``def`` / ``async def`` in the
  enrolled files, counted by ``ast`` from the source (independent of the
  lifter). A function is lifted when its file packaged a proof and no
  ``refused`` member names it; a file with no proof lifts none of its
  functions. Refused members with a symbol are subtracted from their file's
  ``def`` count (never below zero).

WHAT THE EDGE NUMBERS MEAN

Every ``undecided`` member with reason ``unanswered`` and a ``symbol`` in a
minted proof is one call edge, sorted by its symbol (the shares mark after
``#`` dropped, as the join drops it):

* CORPUS edge: ``python:<pkg>`` or ``python:<pkg>.<...>``, where ``<pkg>``
  is the corpus root's name and the longest module prefix of the symbol is an
  enrolled ``.py`` file (``same_module`` when that file is the caller's own,
  ``cross_module`` otherwise), or no module of the corpus at all.
* BOUNDARY edge (leaves the corpus, never a miss): any other package's
  symbol, or a ``<pkg>`` symbol whose longest module prefix is a compiled
  module of the corpus (a ``.so``/``.pyd``/``.pyx``, or a ``.pyi`` with no
  ``.py``), i.e. a call into C.
* DISPATCH edge: ``python:dispatch:<method>``, a method call on a receiver
  whose class the call site does not decide; prove answers it where a read
  binds the receiver's class (step 8). Counted apart; names no module.

A corpus edge is BOUND when ``sugar prove`` joined it: the member has no
``undecided`` row in prove's report (``report::add_undecided_members`` skips
exactly the members ``consistency::joined_member_cids`` joined). Every other
corpus edge is a MISS, with one reason:

* ``prove-timeout`` / ``prove-error`` / ``prove-unreached``: prove gave no
  report (it ran out of the file's ceiling, failed, or never started).
* ``target-module-not-enrolled``: no enrolled module of the corpus is a
  prefix of the symbol.
* ``target-module-no-proof``: the defining module is enrolled but packaged
  no proof (refused, timed out or crashed at mint, or never minted).
* ``target-module-other-seat``: the defining module belongs to another
  seat's slice (only with K > 1; the workflows run one seat).
* ``target-not-stated``: the defining module's proof states no bridge for
  the symbol (a re-export, an attribute, a refused or unread definition).
* ``not-joined`` (or ``not-joined:<label>``): an answering proof was staged
  but prove kept the member owed; ``<label>`` is the join's own drop reason
  where a row names it (``ambiguous-target``, ``recursive-contract``, ...).

Exit code is 0 whenever the instrument itself ran; the numbers, not the exit
code, are the measurement.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
SOURCE_TREE_SRC = REPO / "implementations/python/sugar-source-tree/src"

FILE_CAP_S_DEFAULT = 300  # the product's per-file ceiling (docs/path-forward.md)
DUMP_CAP_S = 120  # the instrument reading a packaged proof
ADMIT_MARGIN_S = 60  # seat-budget slack after the last file may start
KILL_GRACE_S = 10  # reading a killed command's pipes
MEM_FLOOR_GB_DEFAULT = 6.0
WORKER_MEM_GB = 2.0  # assumed peak of one file, for the default worker count
MAX_LOAD_DEFAULT = 1.25  # x CPUs: above this 1-minute load no new file starts
OOM_SCORE_ADJ = 500  # the lane's files go before the runner under OOM
KIT_DEADLINE_MARK = "transport stalled"  # the kit's own plugin deadline
# The kit's opt-in stack sampler (sugar_lift_py_tests.kit_sample_profile).
KIT_PROFILE_DIR_ENV = "SUGAR_KIT_PROFILE_DIR"
PROFILE_TOP_FRAMES = 8
OBSERVED_CHARS = 240
ERROR_CHARS = 400
PROVE_RESERVE_MAX_SHARE = 0.75  # phase 2 never reserves more of the budget

# The symbol vocabulary the join reads (sugar-verifier consistency.rs).
PYTHON_SYMBOL_PREFIX = "python:"
DISPATCH_SYMBOL_PREFIX = "python:dispatch:"  # DISPATCH_SYMBOL_PREFIX
SHARES_MARK = "#"  # DISPATCH_SHARES_MARK: the operands that may share an object
COMPILED_SUFFIXES = (".so", ".pyd", ".pyx")
STUB_SUFFIX = ".pyi"
CID_KEY_CHARS = 32  # the tail of a member CID the lane keys an edge by
# DroppedAmbientPostReason::label, the join's own names for a dropped answer.
JOIN_DROP_LABELS = frozenset(
    {
        "open-after-specialization",
        "opaque-call-subject",
        "call-term-decode-failed",
        "ambiguous-target",
        "import-signature-mismatch",
        "wrong-contract-kind",
        "wrong-provider",
        "stale-or-malformed-contract-ref",
        "recursive-contract",
        "unanswered",
    }
)
DROP_REASON_RE = re.compile(r"([a-z][a-z-]*) for (python:[^\s,()]+)")
# One field of a kit refusal's testimony (owner, blame, observed, requested,
# fix) as the row keeps it: long enough for the owner and the coordinate,
# which the 400-char error line cut off (run 43960179946, #9132).
DIAGNOSTIC_FIELD_CHARS = 2000
DIAGNOSTIC_KEYS = ("owner", "blame", "observed", "requested", "fix")


# --------------------------------------------------------------------------
# Enrollment


def enrolled_files(root: Path) -> list[Path]:
    """The kit's own enumeration (``SourceTree.paths``), never a second one."""
    if str(SOURCE_TREE_SRC) not in sys.path:
        sys.path.insert(0, str(SOURCE_TREE_SRC))
    from sugar_source_tree.tree import SourceTree

    return list(SourceTree(root).paths())


def parse_slice(text: str) -> tuple[int, int]:
    index, _, count = text.partition("/")
    i, k = int(index), int(count)
    if k < 1 or not 0 <= i < k:
        raise argparse.ArgumentTypeError(f"bad --slice {text!r}: want I/K, 0<=I<K")
    return i, k


def defs_in_source(path: Path) -> tuple[int, set[str], str | None]:
    """Every def / async def in the file (count, names), or the parse error."""
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (SyntaxError, ValueError, OSError) as exc:
        return 0, set(), f"{type(exc).__name__}: {exc}"[:ERROR_CHARS]
    names: set[str] = set()
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count += 1
            names.add(node.name)
    return count, names, None


def module_name(package: str, rel: str) -> str:
    """The module a staged ``<package>/<rel>`` is: the kit's one speller
    (``import_binding.module_name_for_path``: no ``.py``, no ``__init__``)."""
    parts = [package, *Path(rel).with_suffix("").parts]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class CorpusModules:
    """Which module of the corpus a symbol names, by its longest prefix.

    ``python``: module name -> enrolled file (rel). ``compiled``: module names
    of the corpus that are compiled extensions (a call into one is a call into
    C: it leaves the corpus).
    """

    def __init__(self, package: str, python: dict[str, str], compiled: set[str]):
        self.package = package
        self.python = python
        self.compiled = compiled

    @classmethod
    def scan(cls, root: Path, files: list[Path]) -> "CorpusModules":
        package = root.name
        python = {
            module_name(package, path.relative_to(root).as_posix()): path.relative_to(root).as_posix()
            for path in files
        }
        compiled: set[str] = set()
        for suffix in (*COMPILED_SUFFIXES, STUB_SUFFIX):
            for path in root.rglob(f"*{suffix}"):
                if "__pycache__" in path.parts:
                    continue
                rel = path.relative_to(root)
                # ``lib.cpython-312-x86_64-linux-gnu.so`` is the module ``lib``.
                stem = rel.name.split(".", 1)[0]
                parts = [package, *rel.parent.parts]
                if stem != "__init__":
                    parts.append(stem)
                name = ".".join(parts)
                if suffix == STUB_SUFFIX and name in python:
                    continue  # a stub beside its own .py is not compiled code
                compiled.add(name)
        return cls(package, python, compiled)

    def target(self, dotted: str) -> tuple[str, str | None]:
        """``("python", rel)``, ``("compiled", module)`` or ``("absent", None)``."""
        parts = dotted.split(".")
        for n in range(len(parts), 0, -1):
            name = ".".join(parts[:n])
            if name in self.python:
                return "python", self.python[name]
            if name in self.compiled:
                return "compiled", name
        return "absent", None


def join_symbol(symbol: str) -> str:
    """The symbol the join looks a bridge up by: a Python symbol's shares
    mark dropped (``consistency::dispatch_shares``)."""
    if symbol.startswith(PYTHON_SYMBOL_PREFIX) and not symbol.startswith(DISPATCH_SYMBOL_PREFIX):
        return symbol.split(SHARES_MARK, 1)[0]
    return symbol


def edge_kind(symbol: str, corpus: CorpusModules) -> str:
    """``dispatch``, ``corpus`` or ``boundary`` (see WHAT THE EDGE NUMBERS MEAN)."""
    if symbol.startswith(DISPATCH_SYMBOL_PREFIX):
        return "dispatch"
    if not symbol.startswith(PYTHON_SYMBOL_PREFIX):
        return "boundary"
    dotted = join_symbol(symbol)[len(PYTHON_SYMBOL_PREFIX):]
    if dotted.split(".", 1)[0] != corpus.package:
        return "boundary"
    kind, _ = corpus.target(dotted)
    return "boundary" if kind == "compiled" else "corpus"


def cid_key(cid: str) -> str:
    """The tail of a member CID: the same key whatever prefix spells it."""
    return cid.strip()[-CID_KEY_CHARS:]


# --------------------------------------------------------------------------
# The binary


def resolve_sugar_bin(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("SUGAR_BIN")
    if env:
        return env
    result = subprocess.run(
        [str(REPO / "bin/sugarbin"), "--profile", "release"],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"sugarbin resolve failed: {result.stderr.strip()}")
    return result.stdout.strip()


def kill_group(pgid: int) -> None:
    """SIGKILL every process left in the command's own process group."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run(
    cmd: list[str], *, cwd: Path, timeout: float, env: dict[str, str] | None = None,
) -> tuple[int | None, str, str, float]:
    """(rc or None on timeout, stdout, stderr, seconds).

    ``env``: variables added to this process's environment for the command
    (the kit inherits them through ``sugar``).

    The command leads its own process group (``start_new_session``); when it
    ends or times out the whole group is killed, so the kit's plugin process
    and any solver it started never outlive the file and keep a CPU busy.
    """
    t0 = time.monotonic()
    if timeout <= 0:
        return None, "", "", 0.0
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        text=True,
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env={**os.environ, **env} if env else None,
    )
    rc: int | None
    try:
        out, err = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        kill_group(proc.pid)
        try:
            out, err = proc.communicate(timeout=KILL_GRACE_S)
        except subprocess.TimeoutExpired:
            # A process that left the group still holds the pipes.
            proc.kill()
            try:
                proc.wait(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                pass
            out, err = "", ""
        rc = None
    finally:
        kill_group(proc.pid)
    return rc, out or "", err or "", time.monotonic() - t0


def json_objects(text: str):
    """Every top-level JSON object in mixed output, in order."""
    decoder = json.JSONDecoder()
    at = 0
    while True:
        at = text.find("{", at)
        if at < 0:
            return
        try:
            value, end = decoder.raw_decode(text, at)
        except json.JSONDecodeError:
            at += 1
            continue
        if isinstance(value, dict):
            yield value
        at = end


def first_object_with(text: str, key: str) -> dict | None:
    for value in json_objects(text):
        if key in value:
            return value
    return None


def last_line(text: str) -> str:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line:
            return line[:ERROR_CHARS]
    return ""


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def error_block(text: str) -> str:
    """The last error mint printed, whole and ANSI-stripped: from its last
    line that opens with ``error`` to the end.

    An error whose message spans lines (a kit's raw output or a decode
    failure inside the path-execution wrapper) kept only its last line in
    ``last_line``: the lane at 13e3413ad recorded 18 files as nothing but
    ``; fix=Inspect the lift PathAlgebra step ...``, the cause cut away."""
    lines = _ANSI.sub("", text).strip().splitlines()
    for at in range(len(lines) - 1, -1, -1):
        if lines[at].lstrip().lower().startswith("error"):
            return "\n".join(lines[at:]).strip()
    return "\n".join(lines).strip()


def link_or_copy(source: Path, target: Path) -> None:
    """A hard link (the store and the projects share one filesystem), or a copy."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def _clip(value: object) -> object:
    if isinstance(value, str):
        return value[:DIAGNOSTIC_FIELD_CHARS]
    return value


def mint_diagnostic(text: str) -> dict | None:
    """The kit's own refusal testimony in a failed mint's output, structured.

    A refusal that escapes the kit answers a JSON-RPC error and ``sugar
    mint`` prints that error object whole inside its error line (``lift
    plugin returned error: {...}``). Its ``data.diagnostic`` names the
    refusal's ``owner`` and ``blame`` (the coordinate) with ``observed`` /
    ``requested`` / ``fix``; ``data.exception_type`` names its class. The
    error line itself is kept to ERROR_CHARS, which cut every owner off.
    An error whose ``data`` is a traceback (an exception that is not a
    refusal) keeps the traceback's tail. A fatal factory panic prints its
    diagnostic object bare (``diagnostic={...}``); it is read the same way.
    The last such object wins (the error is the last thing mint prints).
    None when the output carries no such object.
    """
    found: dict | None = None
    for value in json_objects(text):
        if "code" in value and "message" in value:
            got: dict = {"code": value.get("code"), "message": _clip(value.get("message"))}
            data = value.get("data")
            if isinstance(data, dict):
                if "exception_type" in data:
                    got["exceptionType"] = data.get("exception_type")
                diagnostic = data.get("diagnostic")
                if isinstance(diagnostic, dict):
                    for key in DIAGNOSTIC_KEYS:
                        if key in diagnostic:
                            got[key] = _clip(diagnostic[key])
            elif isinstance(data, str):
                got["traceback"] = data[-DIAGNOSTIC_FIELD_CHARS:]
            found = got
        elif "owner" in value and any(key in value for key in ("observed", "fix", "blame")):
            found = {key: _clip(value[key]) for key in DIAGNOSTIC_KEYS if key in value}
    return found


# --------------------------------------------------------------------------
# Phase 1: one file's mint


def read_members(sugar_bin: str, proof: Path, cwd: Path, cap: float) -> tuple[dict | None, str]:
    rc, out, err, _ = run([sugar_bin, "dump", str(proof), "--json"], cwd=cwd, timeout=cap)
    if rc is None:
        return None, "dump timeout"
    if rc != 0:
        return None, f"dump rc={rc}: {last_line(err or out)}"
    payload = first_object_with(out, "members")
    if payload is None:
        return None, "dump printed no members object"
    return payload["members"], ""


def member_field(member: dict, name: str):
    """A member's field wherever its envelope keeps it (``StoredMember::field``:
    header, then body, then metadata, for both envelope shapes)."""
    for layer in ("header", "body", "metadata"):
        value = (member.get(layer) or {}).get(name) if isinstance(member.get(layer), dict) else None
        if value is not None:
            return value
    envelope = member.get("envelope")
    if isinstance(envelope, dict):
        for layer in ("header", "metadata"):
            section = envelope.get(layer)
            if isinstance(section, dict) and section.get(name) is not None:
                return section[name]
    return None


def member_kind(member: dict) -> str | None:
    kind = member_field(member, "kind")
    return kind if isinstance(kind, str) else None


def classify_members(
    members: dict, def_names: set[str], file_rel: str, corpus: CorpusModules | None = None
) -> dict:
    contracts = 0
    unanswered = 0
    refusals: list[dict] = []
    edges: list[list[str]] = []
    dispatch: list[str] = []
    boundary = 0
    contract_keys = {
        cid_key(cid) for cid, member in members.items() if member_kind(member or {}) == "contract"
    }
    answers: set[str] = set()
    for cid, member in members.items():
        member = member or {}
        header = member.get("header") or {}
        kind = header.get("kind") or member_kind(member)
        if kind == "contract":
            contracts += 1
            continue
        if kind == "bridge":
            # A bridge answers its symbol from THIS proof only when its target
            # is one of this proof's own contracts (bridge_answer reads the
            # target by member CID).
            source_symbol = member_field(member, "sourceSymbol")
            target = member_field(member, "targetContractCid")
            if isinstance(source_symbol, str) and isinstance(target, str) and cid_key(target) in contract_keys:
                answers.add(source_symbol)
            continue
        if kind != "undecided":
            continue
        reason = header.get("reason") or {}
        if "unanswered" in reason:
            unanswered += 1
            symbol = header.get("symbol")
            if corpus is not None and isinstance(symbol, str) and symbol:
                which = edge_kind(symbol, corpus)
                if which == "corpus":
                    edges.append([symbol, cid_key(cid)])
                elif which == "dispatch":
                    dispatch.append(cid_key(cid))
                else:
                    boundary += 1
            continue
        refused = reason.get("refused")
        if refused is None:
            continue
        symbol = header.get("symbol")
        site = header.get("site") or {}
        observed = refused.get("observed")
        if not isinstance(observed, str):
            observed = json.dumps(observed, sort_keys=True)
        tail = symbol.rsplit(".", 1)[-1] if isinstance(symbol, str) else None
        refusals.append(
            {
                "owner": str(refused.get("owner")),
                "symbol": symbol,
                "isDef": bool(tail and tail in def_names),
                "file": site.get("file") or file_rel,
                "line": site.get("startLine"),
                "observed": observed[:OBSERVED_CHARS],
            }
        )
    return {
        "contracts": contracts,
        "unanswered": unanswered,
        "refusals": refusals,
        "edges": edges,
        "dispatchEdges": dispatch,
        "boundaryEdges": boundary,
        "answers": sorted(answers),
    }


def stage_source(root: Path, rel: str, project: Path) -> None:
    staged = project / root.name / rel
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / rel, staged)


def mint_one(
    sugar_bin: str, root: Path, path: Path, work: Path, store: Path, cap: float,
    corpus: CorpusModules, profiles: Path | None = None,
) -> dict:
    """One file's mint: its row, its proof kept in ``store``.

    ``profiles`` (``--profile-timeouts``): the kit runs with its stack
    sampler on (``SUGAR_KIT_PROFILE_DIR`` = ``profiles/<rel slug>``), which
    rewrites its aggregate every few seconds, so a mint the kit's response
    deadline kills still leaves where its time went. The profile is kept
    only when the mint stalled (``mint_stalled``); it is the very run the
    row measures, never a second mint.
    """
    rel = path.relative_to(root).as_posix()
    defs, def_names, parse_error = defs_in_source(path)
    row: dict = {
        "file": rel,
        "defs": defs,
        "parseError": parse_error,
        "mint": None,
        "minted": False,
        "proof": None,
        "stored": None,
        "contracts": 0,
        "unanswered": 0,
        "refusals": [],
        "refusedDefs": 0,
        "edges": [],
        "dispatchEdges": [],
        "boundaryEdges": 0,
        "answers": [],
        "prove": None,
        "binding": None,
    }
    t0 = time.monotonic()
    # One scratch directory per file: files of one seat run side by side.
    scratch = Path(tempfile.mkdtemp(prefix="mint-", dir=work))
    project = scratch / "project"
    sampled = None
    if profiles is not None:
        sampled = profiles / profile_slug(rel)
        shutil.rmtree(sampled, ignore_errors=True)
        sampled.mkdir(parents=True, exist_ok=True)
    try:
        stage_source(root, rel, project)
        rc, out, err, secs = run(
            [sugar_bin, "mint", "--project", str(project), "--out", str(project), "--json"],
            cwd=project,
            timeout=cap,
            env={KIT_PROFILE_DIR_ENV: str(sampled)} if sampled is not None else None,
        )
        receipt = first_object_with(out, "proofFile") if rc == 0 else None
        proof_file = receipt.get("proofFile") if receipt else None
        proofs = sorted(project.glob("blake3-512_*.proof"))
        proof = Path(proof_file) if proof_file and Path(proof_file).is_file() else (proofs[0] if proofs else None)
        row["mint"] = {
            "rc": rc,
            "seconds": round(secs, 2),
            "error": None if rc == 0 else ("timeout" if rc is None else last_line(err or out)),
        }
        if rc != 0 or proof is None:
            owner = "mint-timeout" if rc is None else f"mint-exit-{rc}"
            if rc == 0:
                owner = "mint-no-proof"
            diagnostic = mint_diagnostic(f"{err}\n{out}") if rc not in (0, None) else None
            if diagnostic is None and rc not in (0, None):
                # No kit error object: the error itself, whole (its last
                # line alone can be the wrapper's ``fix=`` tail).
                block = error_block(err or out)
                diagnostic = {"message": _clip(block)} if block else None
            row["mint"]["diagnostic"] = diagnostic
            observed = row["mint"]["error"] or ""
            if diagnostic and diagnostic.get("owner"):
                # The kit's owner and coordinate first: the error line's own
                # prefix (the transport's wrapping) never names them.
                observed = (
                    f"{diagnostic['owner']} at {diagnostic.get('blame')}: "
                    f"{diagnostic.get('observed') or diagnostic.get('message') or ''}"
                )
            refusal = {
                "owner": owner,
                "symbol": None,
                "isDef": False,
                "file": rel,
                "line": None,
                "observed": observed[:OBSERVED_CHARS],
            }
            if diagnostic:
                refusal["diagnostic"] = diagnostic
            row["refusals"] = [refusal]
            row["seconds"] = round(time.monotonic() - t0, 2)
            row["status"] = file_status(row)
            return row
        row["minted"] = True
        row["proof"] = proof.name
        members, dump_error = read_members(sugar_bin, proof, project, min(cap, DUMP_CAP_S))
        if members is None:
            row["dumpTimeout"] = dump_error == "dump timeout"
            row["refusals"] = [
                {
                    "owner": "dump-failed",
                    "symbol": None,
                    "isDef": False,
                    "file": rel,
                    "line": None,
                    "observed": dump_error[:OBSERVED_CHARS],
                }
            ]
        else:
            got = classify_members(members, def_names, f"{root.name}/{rel}", corpus)
            for key in ("contracts", "unanswered", "refusals", "edges", "dispatchEdges",
                        "boundaryEdges", "answers"):
                row[key] = got[key]
            row["refusedDefs"] = sum(1 for r in got["refusals"] if r["isDef"])
        # The proof is kept for phase 2: its own prove, and every caller that
        # imports it. Same filename (its CID: prove's trust root).
        stored = Path(rel) / proof.name
        (store / stored).parent.mkdir(parents=True, exist_ok=True)
        os.replace(proof, store / stored)
        row["stored"] = stored.as_posix()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        if sampled is not None and not mint_stalled(row):
            shutil.rmtree(sampled, ignore_errors=True)
    row["seconds"] = round(time.monotonic() - t0, 2)
    row["status"] = file_status(row)
    return row


def mint_stalled(row: dict) -> bool:
    """The mint hit the file ceiling or the kit's response deadline."""
    mint = row.get("mint") or {}
    if not mint:
        return False
    return mint.get("rc") is None or KIT_DEADLINE_MARK in (mint.get("error") or "")


def profile_slug(rel: str) -> str:
    return rel.replace("/", "__")


def read_profile_summary(directory: Path) -> dict | None:
    """The heaviest kit profile in ``directory``, cut to its top frames."""
    best: dict | None = None
    for path in sorted(directory.glob("kit-profile-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if best is None or data.get("samples", 0) > best.get("samples", 0):
            best = {**data, "path": path.name}
    if best is None:
        return None
    return {
        "path": best["path"],
        "samples": best.get("samples"),
        "elapsedSeconds": best.get("elapsedSeconds"),
        "request": best.get("request"),
        "requests": best.get("requests"),
        "self": (best.get("self") or [])[:PROFILE_TOP_FRAMES],
        "inclusive": (best.get("inclusive") or [])[:PROFILE_TOP_FRAMES],
    }


def profile_row(row: dict, profiles: Path) -> dict:
    """The profiles.jsonl row of a stalled file: its own mint's rc, seconds
    and error, and the heaviest kit profile that very mint left in
    ``profiles/<rel slug>/`` (instrument only: ``row`` is not changed)."""
    rel = row["file"]
    mint = row.get("mint") or {}
    target = profiles / profile_slug(rel)
    return {
        "file": rel,
        "status": "profiled",
        "profile": {
            "rc": mint.get("rc"),
            "seconds": mint.get("seconds"),
            "error": mint.get("error"),
            "dir": target.name,
            "summary": read_profile_summary(target),
        },
        "seconds": mint.get("seconds"),
    }


def file_status(row: dict) -> str:
    """lifted / refused / timeout / crash: a label, never a second count.

    ``timeout``: mint hit the file ceiling, the kit's own plugin transport
    deadline fired (``transport stalled``), or the dump timed out. ``crash``:
    the instrument failed, or mint died by a panic or a signal. A file whose
    proof was packaged is lifted or refused by its members, whatever prove
    did with the time left (the prove row says that).
    """
    if "instrumentError" in row:
        return "crash"
    mint = row.get("mint") or {}
    rc = mint.get("rc")
    if not mint or rc is None:
        return "timeout"
    if rc not in (0, 1):
        return "crash"
    if rc == 1 and KIT_DEADLINE_MARK in (mint.get("error") or ""):
        return "timeout"
    if row.get("dumpTimeout"):
        return "timeout"
    if row.get("minted") and not row.get("refusals"):
        return "lifted"
    return "refused"


# --------------------------------------------------------------------------
# Phase 2: one file's prove, its imported same-corpus proofs staged


class BindIndex:
    """What phase 2 reads of phase 1: who answers each symbol, and where."""

    def __init__(self, corpus: CorpusModules, minted: dict[str, dict], seat: set[str]):
        self.corpus = corpus
        self.seat = seat
        # rel -> store path of its proof (only files that packaged one).
        self.proofs: dict[str, str] = {
            rel: row["stored"] for rel, row in minted.items() if row.get("stored")
        }
        # symbol -> files whose proof answers it.
        self.answering: dict[str, list[str]] = {}
        for rel in sorted(self.proofs):
            for symbol in minted[rel].get("answers") or []:
                self.answering.setdefault(symbol, []).append(rel)

    def imports_for(self, row: dict) -> list[str]:
        """The other files whose proofs answer one of this file's corpus edges."""
        wanted: set[str] = set()
        for symbol, _key in row.get("edges") or []:
            for rel in self.answering.get(join_symbol(symbol), ()):
                if rel != row["file"]:
                    wanted.add(rel)
        return sorted(wanted)


def owed_member_keys(report: dict) -> set[str]:
    """The project's members prove kept owed: their ``undecided`` rows."""
    keys: set[str] = set()
    for row in report.get("rows") or []:
        if row.get("dischargeMethod") != "undecided":
            continue
        cid = row.get("propertyCid")
        if isinstance(cid, str) and cid:
            keys.add(cid_key(cid))
    return keys


def drop_labels(report: dict) -> dict[str, set[str]]:
    """symbol -> the join's drop labels a row's reason names for it."""
    labels: dict[str, set[str]] = {}
    for row in report.get("rows") or []:
        reason = row.get("reason")
        if not isinstance(reason, str):
            continue
        for label, symbol in DROP_REASON_RE.findall(reason):
            if label in JOIN_DROP_LABELS and label != "unanswered":
                labels.setdefault(symbol, set()).add(label)
    return labels


def bind_edges(row: dict, report: dict | None, failure: str | None, index: BindIndex) -> dict:
    """Each corpus edge bound by prove, or a miss with its reason."""
    rel = row["file"]
    owed = owed_member_keys(report) if report is not None else None
    labels = drop_labels(report) if report is not None else {}
    counts = Counter()
    misses: list[dict] = []
    for symbol, key in row.get("edges") or []:
        sym = join_symbol(symbol)
        kind, target_rel = index.corpus.target(sym[len(PYTHON_SYMBOL_PREFIX):])
        side = "same_module" if target_rel == rel else "cross_module"
        counts[side] += 1
        if owed is not None and key not in owed:
            counts[f"{side}_bound"] += 1
            continue
        if owed is None:
            reason = failure or "prove-error"
        elif kind == "absent" or target_rel is None:
            reason = "target-module-not-enrolled"
        elif index.answering.get(sym):
            found = sorted(labels.get(sym, ()))
            reason = "not-joined" + (":" + ",".join(found) if found else "")
        elif target_rel not in index.seat:
            reason = "target-module-other-seat"
        elif target_rel not in index.proofs:
            reason = "target-module-no-proof"
        else:
            reason = "target-not-stated"
        misses.append({"symbol": sym, "reason": reason, "target": target_rel})
    dispatch = row.get("dispatchEdges") or []
    dispatch_answered = 0 if owed is None else sum(1 for key in dispatch if key not in owed)
    return {
        "corpusEdges": counts["same_module"] + counts["cross_module"],
        "bound": counts["same_module_bound"] + counts["cross_module_bound"],
        "crossModule": counts["cross_module"],
        "crossModuleBound": counts["cross_module_bound"],
        "sameModule": counts["same_module"],
        "sameModuleBound": counts["same_module_bound"],
        "misses": misses,
        "boundaryEdges": int(row.get("boundaryEdges") or 0),
        "dispatchEdges": len(dispatch),
        "dispatchAnswered": dispatch_answered,
    }


def prove_one(
    sugar_bin: str, root: Path, row: dict, work: Path, store: Path, cap: float, index: BindIndex
) -> dict:
    row = dict(row)
    t0 = time.monotonic()
    imports = index.imports_for(row)
    scratch = Path(tempfile.mkdtemp(prefix="prove-", dir=work))
    project = scratch / "project"
    try:
        stage_source(root, row["file"], project)
        own = store / row["stored"]
        link_or_copy(own, project / own.name)
        staged = project / ".sugar" / "imports"
        staged.mkdir(parents=True, exist_ok=True)
        for rel in imports:
            proof = store / index.proofs[rel]
            link_or_copy(proof, staged / proof.name)
        # mint and prove share the one per-file ceiling: prove gets what
        # mint left of it (the dump is the instrument, not the file).
        prove_budget = cap - float((row.get("mint") or {}).get("seconds") or 0.0)
        rc, out, err, secs = run(
            [sugar_bin, "prove", "--allow-failed-components", str(project), "--json"],
            cwd=project,
            timeout=prove_budget,
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    rows_report = first_object_with(out, "rows")
    report = rows_report or first_object_with(out, "verdict") or {}
    error = None if report else ("timeout" if rc is None else last_line(err or out))
    row["prove"] = {
        "rc": rc,
        "seconds": round(secs, 2),
        "budget": round(max(prove_budget, 0.0), 2),
        "verdict": report.get("verdict"),
        "byStatus": report.get("byStatus"),
        "owed": report.get("owed"),
        "discharged": report.get("discharged"),
        "imports": len(imports),
        # A staged proof prove could not load is named here (the report's own
        # loadErrors), so a bind that failed on loading is never silent.
        "loadErrors": len(report.get("loadErrors") or []),
        "error": error,
    }
    failure = None
    if rows_report is None:
        failure = "prove-timeout" if rc is None else "prove-error"
    row["binding"] = bind_edges(row, rows_report, failure, index)
    row["seconds"] = round(float(row.get("seconds") or 0.0) + time.monotonic() - t0, 2)
    row["status"] = file_status(row)
    return row


def unproved_row(row: dict, index: BindIndex, why: str) -> dict:
    """A minted file prove never reached: its mint is real, its edges unmeasured."""
    row = dict(row)
    row["prove"] = {"rc": None, "seconds": 0.0, "budget": 0.0, "verdict": None,
                    "byStatus": None, "owed": None, "discharged": None, "imports": 0,
                    "error": why}
    row["binding"] = bind_edges(row, None, f"prove-{why}", index)
    row["status"] = file_status(row)
    return row


# --------------------------------------------------------------------------
# The host: how many files at once


def usable_cpus() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def mem_available_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        return None
    return None


def load_1m() -> float | None:
    try:
        return os.getloadavg()[0]
    except (AttributeError, OSError):
        return None


def default_workers(mem_floor_gb: float) -> int:
    cpus = usable_cpus()
    mem = mem_available_gb()
    if mem is None:
        return cpus
    return max(1, min(cpus, int((mem - mem_floor_gb) // WORKER_MEM_GB)))


def host_has_room(args: argparse.Namespace, cpus: int) -> tuple[bool, str]:
    mem = mem_available_gb()
    if mem is not None and mem < args.mem_floor_gb:
        return False, f"MemAvailable {mem:.1f} GB < floor {args.mem_floor_gb} GB"
    load = load_1m()
    if load is not None and load > args.max_load * cpus:
        return False, f"load {load:.1f} > {args.max_load} x {cpus} CPUs"
    return True, ""


def raise_own_oom_score() -> None:
    """Children inherit it: under OOM the kernel takes a lane file first."""
    try:
        Path("/proc/self/oom_score_adj").write_text(f"{OOM_SCORE_ADJ}\n", encoding="ascii")
    except OSError:
        pass


# --------------------------------------------------------------------------
# The order: slowest first, by an earlier run's rows (order only)


def prior_rows_files(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(path.rglob("rows.jsonl")))
    return found


def prior_seconds(row: dict, phase: str | None) -> float:
    """The seconds an earlier row spent in ``phase`` (mint, prove) or in all."""
    if phase is not None:
        part = row.get(phase)
        if isinstance(part, dict) and part.get("seconds") is not None:
            return float(part["seconds"])
        if phase == "prove":
            return 0.0
    return float(row["seconds"])


def load_prior(paths: list[str], phase: str | None = None) -> dict[str, float]:
    """file -> seconds it took in an earlier run (the slowest seen wins)."""
    prior: dict[str, float] = {}
    for path in prior_rows_files(paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
                rel, secs = row["file"], prior_seconds(row, phase)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            prior[rel] = max(secs, prior.get(rel, 0.0))
    return prior


def estimates(root: Path, rels: list[str], prior: dict[str, float]) -> dict[str, float]:
    """Seconds per file: the prior's own, or its size times the prior's
    seconds per byte (size alone with no prior)."""
    sizes: dict[str, int] = {}
    for rel in rels:
        try:
            sizes[rel] = (root / rel).stat().st_size
        except OSError:
            sizes[rel] = 0
    known_secs = known_bytes = 0.0
    for rel in rels:
        if rel in prior:
            known_secs += prior[rel]
            known_bytes += sizes[rel]
    per_byte = known_secs / known_bytes if known_bytes > 0 else 1.0
    return {rel: prior[rel] if rel in prior else sizes[rel] * per_byte for rel in rels}


def slowest_first(root: Path, rels: list[str], prior: dict[str, float]) -> list[str]:
    """Longest estimated file first (LPT), so the tail is one short file.
    Ties keep the enrollment order."""
    estimate = estimates(root, rels, prior)
    order = {rel: n for n, rel in enumerate(rels)}
    return sorted(rels, key=lambda rel: (-estimate[rel], order[rel]))


def prove_reserve(
    root: Path, rels: list[str], prior_prove: dict[str, float], workers: int,
    budget: float, file_cap: float,
) -> float:
    """Seconds phase 1 leaves for phase 2: the prior's prove seconds over the
    workers plus one ceiling, or half the budget with no prior; never more
    than ``PROVE_RESERVE_MAX_SHARE`` of it."""
    if not any(prior_prove.get(rel) for rel in rels):
        return budget / 2
    total = sum(estimates(root, rels, prior_prove).values())
    reserve = total / max(1, workers) + file_cap + ADMIT_MARGIN_S
    return min(reserve, budget * PROVE_RESERVE_MAX_SHARE)


# --------------------------------------------------------------------------
# One seat


def read_rows(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            rows[row["file"]] = row
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return rows


def read_done(rows_path: Path) -> set[str]:
    return set(read_rows(rows_path))


def ends_mid_line(path: Path) -> bool:
    """A seat killed mid-write leaves a partial last line."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                return False
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) != b"\n"
    except OSError:
        return False


def guarded(rel: str, work: Callable[[], dict]) -> dict:
    try:
        return work()
    except Exception as exc:  # the instrument names its own failure
        return {
            "file": rel,
            "instrumentError": f"{type(exc).__name__}: {exc}"[:ERROR_CHARS],
            "status": "crash",
        }


def killed_by_signal(row: dict, phase: str) -> bool:
    rc = (row.get(phase) or {}).get("rc")
    return isinstance(rc, int) and rc < 0


def run_phase(
    args: argparse.Namespace,
    *,
    phase: str,
    rels: list[str],
    work: Callable[[str], dict],
    sink_path: Path,
    workers: int,
    cpus: int,
    t0: float,
    last_start: float | None,
    total: int,
) -> list[str]:
    """Run ``work`` on every rel, ``workers`` at once while the host has room,
    appending each row to ``sink_path``; returns the rels never started."""
    queue = deque(rels)
    statuses: Counter[str] = Counter()
    retried: set[str] = set()
    unreached: list[str] = []
    running: dict = {}
    measured = 0
    held_since: float | None = None
    phase_t0 = time.monotonic()
    if ends_mid_line(sink_path):
        with sink_path.open("a", encoding="utf-8") as sink:
            sink.write("\n")
    with ThreadPoolExecutor(max_workers=workers) as pool, sink_path.open("a", encoding="utf-8") as sink:
        while queue or running:
            # Start files while there is a worker and the host has room.
            while queue and len(running) < workers:
                if last_start is not None and time.monotonic() - t0 > last_start:
                    unreached = list(queue)
                    queue.clear()
                    print(
                        f"seat budget: no {phase} starts after {last_start:.0f}s; "
                        f"{len(unreached)} files unreached in the {phase} phase",
                        flush=True,
                    )
                    break
                if running:
                    room, why = host_has_room(args, cpus)
                    if not room:
                        if held_since is None:
                            held_since = time.monotonic()
                            print(f"holding new files: {why}", flush=True)
                        break
                if held_since is not None:
                    print(f"resuming after {time.monotonic() - held_since:.0f}s held", flush=True)
                    held_since = None
                rel = queue.popleft()
                running[pool.submit(work, rel)] = rel
            if not running:
                break
            finished, _ = wait(list(running), timeout=5, return_when=FIRST_COMPLETED)
            for future in finished:
                rel = running.pop(future)
                row = future.result()
                if killed_by_signal(row, phase) and rel not in retried:
                    # Most likely the OOM killer under load: once more.
                    retried.add(rel)
                    queue.append(rel)
                    print(f"retry {rel}: {phase} rc={row[phase]['rc']}", flush=True)
                    continue
                if rel in retried:
                    row["retried"] = 1
                sink.write(json.dumps(row, sort_keys=True) + "\n")
                sink.flush()
                measured += 1
                status = row.get("status") or file_status(row)
                statuses[status] += 1
                print(
                    f"[{phase} {measured}/{total}] {status} {rel} "
                    f"{row.get('seconds', '?')}s running={len(running)}",
                    flush=True,
                )
    names = ("lifted", "refused", "timeout", "crash")
    names += tuple(sorted(set(statuses) - set(names)))
    tally = " ".join(f"{name}={statuses[name]}" for name in names)
    print(
        f"{args.label} seat {phase} phase done in {time.monotonic() - phase_t0:.0f}s: "
        f"measured={measured} {tally} unreached={len(unreached)}",
        flush=True,
    )
    return unreached


def seat(args: argparse.Namespace) -> int:
    t0 = time.monotonic()
    root = Path(args.corpus_root).resolve()
    files = enrolled_files(root)
    corpus = CorpusModules.scan(root, files)
    i, k = args.slice
    mine = [p.relative_to(root).as_posix() for p in files[i::k]]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "rows.jsonl"
    minted_path = out_dir / "minted.jsonl"
    store = out_dir / "store"
    store.mkdir(exist_ok=True)
    work_dir = out_dir / "work"
    work_dir.mkdir(exist_ok=True)
    done = read_done(rows_path)
    # A minted row counts only while its proof is still in the store (a row
    # with no proof is a finished mint: it has nothing to prove).
    minted = {
        rel: row
        for rel, row in read_rows(minted_path).items()
        if rel in mine and "instrumentError" not in row
        and (not row.get("stored") or (store / row["stored"]).is_file())
    }
    # While any file still needs its final row, every module's proof must be
    # in the store: a file finished on an earlier attempt is still imported
    # by the files left (its row stays; only its proof is minted again).
    unfinished = any(rel not in done for rel in mine)
    to_mint = [rel for rel in mine if rel not in minted] if unfinished else []
    prior_mint = load_prior(args.prior or [], "mint")
    prior_prove = load_prior(args.prior or [], "prove")
    sugar_bin = resolve_sugar_bin(args.sugar_bin)
    cpus = usable_cpus()
    workers = args.workers or default_workers(args.mem_floor_gb)
    last_mint = last_prove = None
    reserve = 0.0
    if args.seat_budget:
        reserve = prove_reserve(root, mine, prior_prove, workers, args.seat_budget, args.file_cap)
        last_mint = args.seat_budget - reserve - (args.file_cap + DUMP_CAP_S + ADMIT_MARGIN_S)
        last_prove = args.seat_budget - (args.file_cap + ADMIT_MARGIN_S)
    raise_own_oom_score()
    print(
        f"{args.label} seat {i}/{k}: {len(mine)} of {len(files)} enrolled files, "
        f"{len(done)} already measured (resumed), {len(minted)} already minted, "
        f"{len(to_mint)} to mint; workers={workers} cpus={cpus} "
        f"mem_available_gb={mem_available_gb()} "
        f"prior_files={sum(1 for rel in to_mint if rel in prior_mint)} "
        f"file_cap={args.file_cap}s seat_budget={args.seat_budget or '-'}s "
        f"prove_reserve={reserve:.0f}s compiled_modules={len(corpus.compiled)} bin={sugar_bin}",
        flush=True,
    )

    # Phase 1: every module mints its own proof (the kit sampling its stack
    # under --profile-timeouts, kept for the files whose mint stalls).
    profiles_dir = (out_dir / "profiles").resolve() if args.profile_timeouts > 0 else None

    def mint(rel: str) -> dict:
        return guarded(rel, lambda: mint_one(
            sugar_bin, root, root / rel, work_dir, store, args.file_cap, corpus,
            profiles_dir))

    never_minted = run_phase(
        args, phase="mint", rels=slowest_first(root, to_mint, prior_mint), work=mint,
        sink_path=minted_path, workers=workers, cpus=cpus, t0=t0, last_start=last_mint,
        total=len(to_mint),
    )
    minted.update(
        (rel, row) for rel, row in read_rows(minted_path).items()
        if rel in mine and rel not in minted
    )

    # Phase 2: each module proved with the proofs it imports staged.
    index = BindIndex(corpus, minted, set(mine))
    print(
        f"{args.label} seat bind index: {len(index.proofs)} proofs answer "
        f"{len(index.answering)} symbols",
        flush=True,
    )
    to_prove: list[str] = []
    with rows_path.open("a", encoding="utf-8") as sink:
        if ends_mid_line(rows_path):
            sink.write("\n")
        for rel in mine:
            if rel in done or rel not in minted:
                continue
            row = minted[rel]
            if row.get("stored"):
                to_prove.append(rel)
            else:
                # Mint packaged no proof (or the instrument failed): the row
                # is final as it stands, with no edge to bind.
                sink.write(json.dumps(row, sort_keys=True) + "\n")

    def prove(rel: str) -> dict:
        # The mint row is real whatever the instrument does in phase 2: a
        # failure here is that file's prove error, never a lost row.
        try:
            return prove_one(sugar_bin, root, minted[rel], work_dir, store, args.file_cap, index)
        except Exception as exc:
            row = unproved_row(minted[rel], index, "error")
            row["prove"]["instrumentError"] = f"{type(exc).__name__}: {exc}"[:ERROR_CHARS]
            return row

    never_proved = run_phase(
        args, phase="prove", rels=slowest_first(root, to_prove, prior_prove), work=prove,
        sink_path=rows_path, workers=workers, cpus=cpus, t0=t0, last_start=last_prove,
        total=len(to_prove),
    )
    with rows_path.open("a", encoding="utf-8") as sink:
        for rel in never_proved:
            sink.write(json.dumps(unproved_row(minted[rel], index, "unreached"), sort_keys=True) + "\n")

    # Phase 3 (instrument only): the stalled files' profiles, left by their
    # own mint in phase 1 (sampled, never minted again). Nothing here touches
    # rows.jsonl.
    if profiles_dir is not None:
        profiles_path = out_dir / "profiles.jsonl"
        profiled = read_rows(profiles_path)
        stalled = [
            rel for rel in slowest_first(root, mine, prior_mint)
            if rel in minted and mint_stalled(minted[rel])
        ]
        keep = [rel for rel in stalled if rel not in profiled][
            : max(0, args.profile_timeouts - len(profiled))
        ]
        for rel in stalled:
            if rel not in profiled and rel not in keep:
                shutil.rmtree(profiles_dir / profile_slug(rel), ignore_errors=True)
        with profiles_path.open("a", encoding="utf-8") as sink:
            for rel in keep:
                sink.write(json.dumps(profile_row(minted[rel], profiles_dir), sort_keys=True) + "\n")
        print(f"{args.label} seat profiles: {len(keep)} stalled files profiled", flush=True)
    print(
        f"{args.label} seat {i}/{k} done in {time.monotonic() - t0:.0f}s: "
        f"minted={len(minted)} never_minted={len(never_minted)} "
        f"proved={len(to_prove) - len(never_proved)} prove_unreached={len(never_proved)} "
        f"resumed={len(done)}",
        flush=True,
    )
    return 0


# --------------------------------------------------------------------------
# Join


EDGE_KEYS = (
    ("corpusEdges", "corpus_edges"),
    ("bound", "corpus_edges_bound"),
    ("crossModule", "cross_module_edges"),
    ("crossModuleBound", "cross_module_edges_bound"),
    ("sameModule", "same_module_edges"),
    ("sameModuleBound", "same_module_edges_bound"),
    ("boundaryEdges", "boundary_edges"),
    ("dispatchEdges", "dispatch_edges"),
    ("dispatchAnswered", "dispatch_edges_answered"),
)


def join_edges(rows: dict[str, dict]) -> tuple[dict, list[dict]]:
    """Summary edge counts over every row's binding, and every miss."""
    totals: Counter[str] = Counter()
    misses: list[dict] = []
    imports = load_errors = 0
    for rel in sorted(rows):
        binding = rows[rel].get("binding")
        if not isinstance(binding, dict):
            continue
        for source, _ in EDGE_KEYS:
            totals[source] += int(binding.get(source) or 0)
        prove = rows[rel].get("prove") or {}
        imports += int(prove.get("imports") or 0)
        load_errors += int(prove.get("loadErrors") or 0)
        for miss in binding.get("misses") or []:
            misses.append({**miss, "file": rel})
    summary = {target: totals[source] for source, target in EDGE_KEYS}
    summary["corpus_edge_misses"] = len(misses)
    summary["corpus_edge_misses_by_reason"] = dict(
        Counter(miss["reason"] for miss in misses).most_common()
    )
    summary["imports_staged"] = imports
    summary["prove_load_errors"] = load_errors
    return summary, misses


def join(args: argparse.Namespace) -> int:
    rows: dict[str, dict] = {}
    for directory in args.join:
        path = Path(directory) / "rows.jsonl"
        if not path.is_file():
            print(f"join: no rows at {path}", file=sys.stderr)
            continue
        rows.update(read_rows(path))
    enrolled = args.enrolled if args.enrolled is not None else len(rows)
    files_lifted = files_minted = funcs_total = funcs_lifted = 0
    instrument_errors = 0
    refusal_rows: list[dict] = []
    # A label per file (lifted / refused / timeout / crash), never a count
    # the numbers below are computed from.
    by_status: Counter[str] = Counter(
        rows[rel].get("status") or file_status(rows[rel]) for rel in rows
    )
    prove_timeouts = sum(
        1 for row in rows.values() if (row.get("prove") or {}).get("error") == "timeout"
    )
    for rel in sorted(rows):
        row = rows[rel]
        if "instrumentError" in row:
            instrument_errors += 1
            continue
        defs = int(row.get("defs") or 0)
        funcs_total += defs
        refusals = row.get("refusals") or []
        refusal_rows.extend(refusals)
        if row.get("minted"):
            files_minted += 1
            funcs_lifted += max(0, defs - int(row.get("refusedDefs") or 0))
            if not refusals:
                files_lifted += 1
    owners = Counter(r["owner"] for r in refusal_rows)
    top = owners.most_common(args.top)
    refusals_top = "; ".join(f"{owner} x{count}" for owner, count in top)
    edges, misses = join_edges(rows)
    misses_top = "; ".join(
        f"{reason} x{count}"
        for reason, count in list(edges["corpus_edge_misses_by_reason"].items())[: args.top]
    )
    label = args.label
    summary = {
        "label": label,
        "files_lifted": files_lifted,
        "files_total": enrolled,
        "files_minted": files_minted,
        "files_measured": len(rows),
        "files_missing": max(0, enrolled - len(rows)),
        "instrument_errors": instrument_errors,
        "funcs_lifted": funcs_lifted,
        "funcs_total": funcs_total,
        "refused": len(refusal_rows),
        "unanswered_edges": sum(int(r.get("unanswered") or 0) for r in rows.values()),
        "files_by_status": {
            name: by_status[name] for name in ("lifted", "refused", "timeout", "crash")
        },
        "prove_timeouts": prove_timeouts,
        "refusals_top": refusals_top,
        **edges,
        "edge_misses_top": misses_top,
        "line": (
            f"{label}_lift_files={files_lifted}/{enrolled} "
            f"{label}_lift_funcs={funcs_lifted}/{funcs_total} "
            f"{label}_refused={len(refusal_rows)}"
        ),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.refusals:
        by_owner: dict[str, list[dict]] = {}
        for r in refusal_rows:
            site = {k: r.get(k) for k in ("symbol", "file", "line", "observed")}
            if r.get("diagnostic"):
                # A file mint packaged no proof for: the kit's own testimony
                # (owner, blame, observed, requested, fix), structured.
                site["diagnostic"] = r["diagnostic"]
            by_owner.setdefault(r["owner"], []).append(site)
        listing = [
            {"owner": owner, "count": count, "sites": by_owner[owner]}
            for owner, count in owners.most_common()
        ]
        Path(args.refusals).parent.mkdir(parents=True, exist_ok=True)
        Path(args.refusals).write_text(
            json.dumps({"label": label, "refusals": listing}, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.edge_misses:
        Path(args.edge_misses).parent.mkdir(parents=True, exist_ok=True)
        Path(args.edge_misses).write_text(
            json.dumps({"label": label, "misses": edge_miss_listing(misses)}, indent=2) + "\n",
            encoding="utf-8",
        )
    print(summary["line"], flush=True)
    print(f"{label}_refusals_top={refusals_top}", flush=True)
    print(
        f"{label}_files_minted={files_minted} {label}_files_missing={summary['files_missing']} "
        f"{label}_instrument_errors={instrument_errors} "
        f"{label}_unanswered_edges={summary['unanswered_edges']}",
        flush=True,
    )
    status_line = " ".join(f"{name}={count}" for name, count in summary["files_by_status"].items())
    print(
        f"{label}_files_by_status: {status_line} missing={summary['files_missing']} "
        f"prove_timeouts={prove_timeouts}",
        flush=True,
    )
    print(
        f"{label}_edges: corpus={edges['corpus_edges_bound']}/{edges['corpus_edges']} "
        f"cross_module={edges['cross_module_edges_bound']}/{edges['cross_module_edges']} "
        f"same_module={edges['same_module_edges_bound']}/{edges['same_module_edges']} "
        f"missed={edges['corpus_edge_misses']} boundary={edges['boundary_edges']} "
        f"dispatch={edges['dispatch_edges_answered']}/{edges['dispatch_edges']} "
        f"imports_staged={edges['imports_staged']} "
        f"prove_load_errors={edges['prove_load_errors']}",
        flush=True,
    )
    print(f"{label}_edge_misses_top={misses_top}", flush=True)
    return 0


def edge_miss_listing(misses: list[dict], symbols_per_reason: int = 50, files_per_symbol: int = 5) -> list[dict]:
    """reason -> its count and its most-missed symbols (with a few callers)."""
    by_reason: dict[str, list[dict]] = {}
    for miss in misses:
        by_reason.setdefault(miss["reason"], []).append(miss)
    listing = []
    for reason, items in sorted(by_reason.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        by_symbol: dict[str, list[dict]] = {}
        for miss in items:
            by_symbol.setdefault(miss["symbol"], []).append(miss)
        symbols = [
            {
                "symbol": symbol,
                "count": len(hits),
                "target": hits[0].get("target"),
                "files": sorted({hit["file"] for hit in hits})[:files_per_symbol],
            }
            for symbol, hits in sorted(by_symbol.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ][:symbols_per_reason]
        listing.append({"reason": reason, "count": len(items), "symbols": symbols})
    return listing


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--corpus-root")
    parser.add_argument("--label", default="corpus")
    parser.add_argument("--slice", type=parse_slice, default=(0, 1))
    parser.add_argument("--out-dir")
    parser.add_argument("--sugar-bin")
    parser.add_argument("--file-cap", type=float, default=FILE_CAP_S_DEFAULT)
    parser.add_argument(
        "--workers", type=int, default=0,
        help="files at once in this seat (0: usable CPUs, bounded by memory)",
    )
    parser.add_argument("--mem-floor-gb", type=float, default=MEM_FLOOR_GB_DEFAULT)
    parser.add_argument("--max-load", type=float, default=MAX_LOAD_DEFAULT)
    parser.add_argument(
        "--seat-budget", type=float, default=0,
        help="seconds this seat may run; no file starts once the rest cannot finish",
    )
    parser.add_argument(
        "--prior", nargs="*", metavar="ROWS",
        help="rows.jsonl files or directories from an earlier run (order only)",
    )
    parser.add_argument(
        "--profile-timeouts", type=int, default=0, metavar="N",
        help="every mint runs with the kit's stack sampler on "
        f"({KIT_PROFILE_DIR_ENV}); the profiles of up to N files whose mint "
        "stalled are kept in OUT_DIR/profiles/, rows in OUT_DIR/profiles.jsonl, "
        "never in rows.jsonl",
    )
    parser.add_argument("--count", action="store_true", help="print the enrolled file count")
    parser.add_argument("--join", nargs="+", metavar="DIR")
    parser.add_argument("--enrolled", type=int)
    parser.add_argument("--out")
    parser.add_argument("--refusals")
    parser.add_argument("--edge-misses", help="write the corpus edges that did not bind, by reason")
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args(argv)
    if args.join:
        if not args.out:
            parser.error("--join needs --out SUMMARY.json")
        return join(args)
    if not args.corpus_root:
        parser.error("--corpus-root is required")
    if args.count:
        print(len(enrolled_files(Path(args.corpus_root).resolve())))
        return 0
    if not args.out_dir:
        parser.error("seat mode needs --out-dir")
    return seat(args)


if __name__ == "__main__":
    raise SystemExit(main())
