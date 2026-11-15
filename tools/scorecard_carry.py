#!/usr/bin/env python3
"""Dependency fingerprints for the main scorecard: rerun what changed, carry the rest.

WHY THIS EXISTS

The main scorecard (.github/workflows/main-scorecard.yml) measures main on
every merge. Measured from scratch, the package suite and the pandas board take
from tens of minutes to hours, and a merge usually changes a handful of
functions. This module records, for each pytest test and each pandas board
file, which first-party code its result depended on. The next run reruns only
the tests and board files whose dependencies changed and carries every other
result forward from its stored record. The reported numbers are always full
totals for the measured SHA (rerun + carried), and every summary says how many
of each.

WHAT A RECORD DEPENDS ON (its depset)

* every first-party function that started executing while the record was open
  (``sys.monitoring`` PY_START), fingerprinted per function: the AST of the def
  at module or class level, nested defs and lambdas included. Line numbers and
  comments are not part of a fingerprint;
* the module skeleton (``<module>``: module- and class-level statements,
  imports, decorated def headers) of every module whose body ran, of every
  module with an executed function, and of every first-party module those
  modules import;
* the git blob of every tracked file opened for reading, and the tracked
  entries of every tracked directory listed.

A result produced while a subprocess was started (or the process forked) is
never stored: code in another process is not fingerprinted, so that result is
rerun every time.

WHEN A RESULT IS CARRIED

Only when every entry of its recorded depset is identical in the tree being
measured: the same blob or, for a module whose blob changed, the same
fingerprint for every recorded function and skeleton. The comparison is made
against this SHA's tree, not against a diff of two SHAs, so it holds across
reverts, skipped SHAs and force pushes. When unsure, rerun: a dirty checkout,
an unreadable record, a missing object or an unwritable store all mean rerun.

THE STORE

Content-addressed under one directory on the runner host:

    <store>/<env-key>/objects/<sha[:2]>/<sha>.json        depsets, fragments
    <store>/<env-key>/index/<kind>/<h[:2]>/<h>/<depset>.json   one result

The env key is the interpreter, platform, installed third-party distributions
and this module's own source. When any of them changes the store under the new
key is empty, everything is measured once, and the store is refilled.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

MECHANISM = "sugar-scorecard-carry/v1"
ABSENT = "-"
MODULE_KEY = "<module>"
KEEP_PER_ITEM = 4
CO_OPTIMIZED = 0x0001
BUCKETS = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")
SUMMARY_SCHEMA = "sugar-scorecard-carry-summary/v1"

_HERE = Path(__file__).resolve()
_PLUGIN = _HERE.with_name("scorecard_carry_pytest.py")

# Instruments: their code runs inside every record (hooks, heartbeat
# threads) but is not what a result depends on. Their own changes reach the
# key through MECHANISM / the module hash instead.
INSTRUMENT_FILES = frozenset(
    {
        "tools/scorecard_carry.py",
        "tools/scorecard_carry_pytest.py",
        "tools/python_package_suite_report.py",
        "tools/job_log_heartbeat.py",
    }
)
_SKIP_DIR_PARTS = frozenset(
    {".git", ".venv", "venv", "site-packages", "node_modules", "__pycache__", ".tox"}
)
_AUDIT_EVENTS = frozenset(
    {
        "open",
        "os.listdir",
        "os.scandir",
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.forkpty",
    }
)
# Source reads made to render a traceback are not dependencies.
_SKIP_CALLER_SUFFIXES = ("/linecache.py", "/tokenize.py")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_MISS = object()


def narrate(message: str) -> None:
    print(message, flush=True)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


# --------------------------------------------------------------- fingerprints


def _dump(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _dump_value(value: Any) -> str:
    if isinstance(value, ast.AST):
        return _dump(value)
    if isinstance(value, list):
        return "[" + ",".join(_dump_value(item) for item in value) + "]"
    return repr(value)


def _walk(
    body: list[ast.stmt],
    prefix: str,
    groups: dict[str, list[str]],
    skeleton: list[str],
) -> None:
    """Split ``body`` into per-def fingerprints and the skeleton that remains.

    Qualnames follow ``code.co_qualname``: class names and the def name, with
    no entry for compound statements (a def under ``if TYPE_CHECKING:`` is
    still a module-level def). An undecorated def leaves the skeleton: binding
    a name has no other effect at import. A decorated def leaves its header,
    because the decorator runs at import.
    """
    for node in body:
        if isinstance(node, _FUNCS):
            groups.setdefault(prefix + node.name, []).append(_dump(node))
            if node.decorator_list:
                skeleton.append(
                    "@def "
                    + prefix
                    + node.name
                    + " "
                    + "|".join(_dump(d) for d in node.decorator_list)
                    + " "
                    + _dump(node.args)
                )
            continue
        if isinstance(node, ast.ClassDef):
            skeleton.append("<class " + prefix + node.name)
            for name, value in ast.iter_fields(node):
                if name not in ("name", "body"):
                    skeleton.append(name + "=" + _dump_value(value))
            _walk(node.body, prefix + node.name + ".", groups, skeleton)
            skeleton.append(">")
            continue
        fields = list(ast.iter_fields(node))
        compound = any(
            isinstance(value, list)
            and value
            and isinstance(value[0], (ast.stmt, ast.excepthandler, ast.match_case))
            for _, value in fields
        )
        if not compound:
            skeleton.append(_dump(node))
            continue
        skeleton.append("<" + type(node).__name__)
        for name, value in fields:
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                skeleton.append(name + ":")
                _walk(value, prefix, groups, skeleton)
            elif (
                isinstance(value, list)
                and value
                and isinstance(value[0], (ast.excepthandler, ast.match_case))
            ):
                for part in value:
                    skeleton.append(name + "[")
                    for part_name, part_value in ast.iter_fields(part):
                        if part_name != "body":
                            skeleton.append(part_name + "=" + _dump_value(part_value))
                    _walk(part.body, prefix, groups, skeleton)
                    skeleton.append("]")
            else:
                skeleton.append(name + "=" + _dump_value(value))
        skeleton.append(">")


def fingerprint_table(
    source: bytes | str,
) -> tuple[dict[str, str], list[tuple[int, str | None, tuple[str, ...]]]]:
    """Return ``({qualname: fingerprint, "<module>": skeleton}, imports)``.

    ``imports`` lists every import statement anywhere in the module
    (function-local imports included) as ``(level, module, names)``.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        raw = source if isinstance(source, bytes) else source.encode("utf-8")
        return {MODULE_KEY: "unparsed:" + _sha(raw)[:32]}, []
    groups: dict[str, list[str]] = {}
    skeleton: list[str] = []
    _walk(tree.body, "", groups, skeleton)
    table = {q: _sha("\n".join(parts).encode("utf-8"))[:32] for q, parts in groups.items()}
    table[MODULE_KEY] = _sha("\n".join(skeleton).encode("utf-8"))[:32]
    imports: list[tuple[int, str | None, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((0, alias.name, ()))
        elif isinstance(node, ast.ImportFrom):
            imports.append(
                (node.level or 0, node.module, tuple(a.name for a in node.names))
            )
    return table, imports


def code_key(qualname: str, flags: int) -> str:
    """Map a code object's qualname to the fingerprint-table key that owns it."""
    if ".<locals>" in qualname:
        return qualname.split(".<locals>", 1)[0]
    if not flags & CO_OPTIMIZED:
        return MODULE_KEY  # module body or class body
    if qualname.rsplit(".", 1)[-1].startswith("<"):
        return MODULE_KEY  # module- or class-level lambda / genexpr
    return qualname


# ----------------------------------------------------------------------- tree


class Tree:
    """The checkout being measured: git blobs, fingerprint tables, listings."""

    def __init__(self, root: str, blobs: dict[str, str], clean: bool, reason: str = ""):
        self.root = root
        self.blobs = blobs
        self.clean = clean
        self.reason = reason
        self._rel_cache: dict[tuple[str, bool], str | None] = {}
        self._tables: dict[str, tuple[dict[str, str], list]] = {}
        self._untracked: dict[str, str] = {}
        self._children: dict[str, set[str]] | None = None
        self._listings: dict[str, str] = {}

    @classmethod
    def open(cls, start: str | os.PathLike[str]) -> "Tree":
        start = os.path.realpath(os.fspath(start))
        try:
            top = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=start,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            listing = subprocess.run(
                ["git", "ls-files", "-s", "-z"], cwd=top, capture_output=True, check=True
            ).stdout
            status = subprocess.run(
                [
                    "git",
                    "--no-optional-locks",
                    "status",
                    "--porcelain",
                    "--untracked-files=no",
                    "-z",
                ],
                cwd=top,
                capture_output=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            return cls(start, {}, False, f"git unavailable: {exc}")
        blobs: dict[str, str] = {}
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            meta, _, path = entry.partition(b"\t")
            parts = meta.split()
            if len(parts) >= 2:
                blobs[os.fsdecode(path)] = parts[1].decode("ascii")
        root = os.path.realpath(top)
        if status.strip(b"\0").strip():
            return cls(root, blobs, False, "the checkout has local modifications")
        return cls(root, blobs, True)

    def rel(self, path: str, py_only: bool = True) -> str | None:
        if not path or path.startswith("<"):
            return None
        absolute = os.path.isabs(path)
        cache_key = (path, py_only)
        if absolute:
            hit = self._rel_cache.get(cache_key, _MISS)
            if hit is not _MISS:
                return hit  # type: ignore[return-value]
        result: str | None = None
        real = os.path.realpath(path)
        if real.startswith(self.root + os.sep):
            rel = real[len(self.root) + 1 :].replace(os.sep, "/")
            parts = rel.split("/")
            if not _SKIP_DIR_PARTS.intersection(parts[:-1]) and (
                not py_only or rel.endswith(".py")
            ):
                result = rel
        if absolute:
            self._rel_cache[cache_key] = result
        return result

    def rel_dir(self, path: str) -> str | None:
        real = os.path.realpath(path)
        if real == self.root:
            return ""
        if not real.startswith(self.root + os.sep):
            return None
        rel = real[len(self.root) + 1 :].replace(os.sep, "/")
        if _SKIP_DIR_PARTS.intersection(rel.split("/")):
            return None
        return rel

    def blob(self, rel: str) -> str:
        known = self.blobs.get(rel)
        if known is not None:
            return known
        cached = self._untracked.get(rel)
        if cached is None:
            try:
                with open(os.path.join(self.root, rel), "rb") as handle:
                    cached = "u:" + _sha(handle.read())
            except OSError:
                cached = ABSENT
            self._untracked[rel] = cached
        return cached

    def table(self, rel: str) -> tuple[dict[str, str], list]:
        cached = self._tables.get(rel)
        if cached is None:
            try:
                with open(os.path.join(self.root, rel), "rb") as handle:
                    cached = fingerprint_table(handle.read())
            except OSError:
                cached = ({}, [])
            self._tables[rel] = cached
        return cached

    def listing(self, rel_dir: str) -> str:
        cached = self._listings.get(rel_dir)
        if cached is not None:
            return cached
        if self._children is None:
            children: dict[str, set[str]] = {}
            for path in self.blobs:
                parts = path.split("/")
                for depth in range(len(parts)):
                    children.setdefault("/".join(parts[:depth]), set()).add(parts[depth])
            self._children = children
        names = sorted(self._children.get(rel_dir, ()))
        cached = _sha("\n".join(names).encode("utf-8"))[:32]
        self._listings[rel_dir] = cached
        return cached


# ---------------------------------------------------------------------- store


class Store:
    def __init__(self, root: str | os.PathLike[str], key: str):
        self.root = Path(root)
        self.key = key
        self.base = self.root / key
        self._objects: dict[str, Any] = {}
        self._depset_valid: dict[str, bool] = {}
        self._fragment_valid: dict[str, bool] = {}
        self.write_error: str | None = None

    def touch(self) -> None:
        try:
            self.base.mkdir(parents=True, exist_ok=True)
            (self.base / "last-used").write_text(f"{time.time()}\n", encoding="utf-8")
        except OSError as exc:
            self.write_error = str(exc)

    def _object_path(self, sha: str) -> Path:
        return self.base / "objects" / sha[:2] / (sha + ".json")

    def _item_dir(self, kind: str, ident: str) -> Path:
        digest = _sha(canonical([kind, ident]))
        return self.base / "index" / kind / digest[:2] / digest

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)

    def put_object(self, obj: Any) -> str:
        data = canonical(obj)
        sha = _sha(data)
        path = self._object_path(sha)
        if not path.exists():
            self._atomic_write(path, data)
        self._objects[sha] = obj
        return sha

    def get_object(self, sha: str) -> Any:
        if sha in self._objects:
            return self._objects[sha]
        try:
            obj = json.loads(self._object_path(sha).read_bytes())
        except (OSError, ValueError):
            obj = None
        self._objects[sha] = obj
        return obj

    def record(self, kind: str, ident: str, depset_sha: str, payload: Any) -> None:
        item = self._item_dir(kind, ident)
        entry = {
            "kind": kind,
            "ident": ident,
            "depset": depset_sha,
            "payload": payload,
            "recordedAt": time.time(),
        }
        target = item / f"{depset_sha}.json"
        self._atomic_write(target, canonical(entry))
        try:
            entries = sorted(
                (p for p in item.iterdir() if p.suffix == ".json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for stale in entries[KEEP_PER_ITEM:]:
                if stale != target:
                    stale.unlink(missing_ok=True)
        except OSError:
            pass

    def lookup(self, kind: str, ident: str, tree: Tree) -> Any:
        item = self._item_dir(kind, ident)
        try:
            entries = sorted(
                (p for p in item.iterdir() if p.suffix == ".json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return None
        for path in entries:
            try:
                entry = json.loads(path.read_bytes())
            except (OSError, ValueError):
                continue
            if entry.get("kind") != kind or entry.get("ident") != ident:
                continue
            depset = entry.get("depset")
            if isinstance(depset, str) and self.depset_valid(depset, tree):
                try:
                    os.utime(path)  # a result in use is never pruned first
                except OSError:
                    pass
                return entry.get("payload")
        return None

    def depset_valid(self, sha: str, tree: Tree) -> bool:
        cached = self._depset_valid.get(sha)
        if cached is not None:
            return cached
        result = self._check_depset(sha, tree)
        self._depset_valid[sha] = result
        return result

    def _check_depset(self, sha: str, tree: Tree) -> bool:
        depset = self.get_object(sha)
        if not isinstance(depset, dict):
            return False
        try:
            for rel, blob, fragment in depset["mods"]:
                if tree.blob(rel) == blob:
                    continue
                if not self._fragment_ok(fragment, rel, tree):
                    return False
            for rel, blob in depset["files"]:
                if tree.blob(rel) != blob:
                    return False
            for rel, listing in depset["dirs"]:
                if tree.listing(rel) != listing:
                    return False
        except (KeyError, TypeError, ValueError):
            return False
        return True

    def _fragment_ok(self, sha: str, rel: str, tree: Tree) -> bool:
        cached = self._fragment_valid.get(sha)
        if cached is not None:
            return cached
        fragment = self.get_object(sha)
        result = False
        if isinstance(fragment, dict) and fragment.get("path") == rel:
            table, _ = tree.table(rel)
            fns = fragment.get("fns") or {}
            result = all(table.get(q, ABSENT) == fp for q, fp in fns.items())
        self._fragment_valid[sha] = result
        return result


# ------------------------------------------------------------------- recorder


class Sink:
    __slots__ = ("keys", "files", "dirs", "opaque")

    def __init__(self) -> None:
        self.keys: set[tuple[str, str]] = set()
        self.files: set[str] = set()
        self.dirs: set[str] = set()
        self.opaque: set[str] = set()

    def merge(self, other: "Sink") -> "Sink":
        self.keys |= other.keys
        self.files |= other.files
        self.dirs |= other.dirs
        self.opaque |= other.opaque
        return self

    @classmethod
    def union(cls, sinks: Iterable["Sink | None"]) -> "Sink":
        out = cls()
        for sink in sinks:
            if sink is not None:
                out.merge(sink)
        return out


_RECORDERS: list["Recorder"] = []
_AUDIT_INSTALLED = False


def _audit_hook(event: str, args: tuple) -> None:
    if event not in _AUDIT_EVENTS or not _RECORDERS:
        return
    try:
        caller = sys._getframe(1).f_code.co_filename
    except ValueError:
        caller = ""
    for recorder in tuple(_RECORDERS):
        recorder._on_audit(event, args, caller)


def _fs(path: Any) -> str:
    path = os.fspath(path)
    return os.fsdecode(path) if isinstance(path, bytes) else path


class Recorder:
    """Records executed first-party code and file reads into active sinks."""

    def __init__(self, tree: Tree):
        self.tree = tree
        self.tool: int | None = None
        self._active: list[Sink] = []
        self._codes: dict[Any, tuple[str, str] | None] = {}
        self._local = threading.local()

    def start(self) -> None:
        global _AUDIT_INSTALLED
        monitoring = getattr(sys, "monitoring", None)
        if monitoring is None:
            raise RuntimeError("sys.monitoring needs Python 3.12+")
        for tool in (4, 3):
            try:
                monitoring.use_tool_id(tool, "sugar-scorecard-carry")
            except ValueError:
                continue
            self.tool = tool
            break
        if self.tool is None:
            raise RuntimeError("no free sys.monitoring tool id")
        monitoring.register_callback(
            self.tool, monitoring.events.PY_START, self._on_start
        )
        monitoring.set_events(self.tool, monitoring.events.PY_START)
        if not _AUDIT_INSTALLED:
            sys.addaudithook(_audit_hook)
            _AUDIT_INSTALLED = True
        _RECORDERS.append(self)
        # Bodies that ran before the recorder started: every first-party
        # module already imported depends the result on its skeleton.
        self.baseline = Sink()
        for module in list(sys.modules.values()):
            rel = self.tree.rel(getattr(module, "__file__", None) or "")
            if rel is not None and rel not in INSTRUMENT_FILES:
                self.baseline.keys.add((rel, MODULE_KEY))

    def stop(self) -> None:
        if self in _RECORDERS:
            _RECORDERS.remove(self)
        if self.tool is not None:
            monitoring = sys.monitoring
            monitoring.set_events(self.tool, 0)
            monitoring.register_callback(self.tool, monitoring.events.PY_START, None)
            monitoring.free_tool_id(self.tool)
            self.tool = None

    def push(self) -> Sink:
        sink = Sink()
        self._active.append(sink)
        sys.monitoring.restart_events()
        return sink

    def resume(self, sink: Sink) -> None:
        """Make an existing sink active again (after a nested suspension)."""
        self._active.append(sink)
        sys.monitoring.restart_events()

    def pop(self, sink: Sink) -> None:
        try:
            self._active.remove(sink)
        except ValueError:
            pass

    def quiet(self) -> "_Quiet":
        return _Quiet(self._local)

    def _on_start(self, code: Any, offset: int) -> Any:
        key = self._codes.get(code, _MISS)
        if key is _MISS:
            rel = self.tree.rel(code.co_filename)
            if rel is None or rel in INSTRUMENT_FILES:
                key = None
            else:
                key = (rel, code_key(code.co_qualname, code.co_flags))
            self._codes[code] = key
        if key is not None:
            for sink in tuple(self._active):
                sink.keys.add(key)  # type: ignore[arg-type]
        return sys.monitoring.DISABLE

    def _on_audit(self, event: str, args: tuple, caller: str) -> None:
        if not self._active or getattr(self._local, "quiet", 0):
            return
        if caller.startswith("<frozen importlib") or caller.endswith(_SKIP_CALLER_SUFFIXES):
            return
        try:
            if event == "open":
                path, mode, flags = (tuple(args) + (None, None, 0))[:3]
                if path is None or isinstance(path, int):
                    return
                if isinstance(mode, str):
                    if any(c in mode for c in "wax+"):
                        return
                elif isinstance(flags, int) and flags & _WRITE_FLAGS:
                    return
                rel = self.tree.rel(_fs(path), py_only=False)
                if rel is None or rel not in self.tree.blobs:
                    return
                for sink in tuple(self._active):
                    sink.files.add(rel)
            elif event in ("os.listdir", "os.scandir"):
                path = args[0] if args else None
                if isinstance(path, int):
                    return
                rel = self.tree.rel_dir(_fs(path) if path is not None else ".")
                if rel is None:
                    return
                for sink in tuple(self._active):
                    sink.dirs.add(rel)
            else:
                reason = event
                if event == "subprocess.Popen" and args:
                    program = args[0]
                    if program is None and len(args) > 1:
                        argv = args[1]
                        program = argv if isinstance(argv, (str, bytes)) else (argv[0] if argv else "")
                    try:
                        reason = "subprocess:" + os.path.basename(_fs(program))
                    except TypeError:
                        reason = "subprocess"
                for sink in tuple(self._active):
                    sink.opaque.add(reason)
        except Exception:  # noqa: BLE001 -- an audit hook must never raise
            for sink in tuple(self._active):
                sink.opaque.add("audit-error:" + event)


class _Quiet:
    def __init__(self, local: threading.local):
        self._local = local

    def __enter__(self) -> None:
        self._local.quiet = getattr(self._local, "quiet", 0) + 1

    def __exit__(self, *exc: object) -> None:
        self._local.quiet -= 1


class _NoQuiet:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> None:
        return None


# -------------------------------------------------------------------- session


def env_key(extra: Mapping[str, Any]) -> str:
    """Interpreter + platform + third-party distributions + this module."""
    import importlib.metadata
    import platform
    import sysconfig

    paths = sorted({sysconfig.get_paths()["purelib"], sysconfig.get_paths()["platlib"]})
    dists = sorted(
        {
            f"{(dist.metadata['Name'] or '?').lower()}=={dist.version}"
            for dist in importlib.metadata.distributions(path=paths)
        }
    )
    material = {
        "mechanism": MECHANISM,
        "module": _sha(_HERE.read_bytes()),
        "python": sys.version,
        "cacheTag": sys.implementation.cache_tag,
        "platform": sys.platform,
        "machine": platform.machine(),
        "distributions": dists,
        "extra": {str(k): str(extra[k]) for k in sorted(extra)},
    }
    return _sha(canonical(material))[:24]


def pytest_key_extra(tree: Tree, rootdir: str, label: str) -> dict[str, str]:
    """The pytest part of the key: shared by the plugin and ``suite-plan``."""
    real = os.path.realpath(rootdir)
    rel = os.path.relpath(real, tree.root).replace(os.sep, "/")
    ini = []
    for name in ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg"):
        path = name if rel == "." else f"{rel}/{name}"
        ini.append(f"{name}={tree.blob(path)}")
    plugin = _sha(_PLUGIN.read_bytes()) if _PLUGIN.is_file() else ABSENT
    return {
        "tool": "pytest",
        "label": label,
        "rootdir": rel,
        "ini": ",".join(ini),
        "plugin": plugin,
    }


class CarrySession:
    """One process's view: lookups against the tree, records into the store."""

    def __init__(self, tree: Tree, store: Store, recorder: Recorder | None):
        self.tree = tree
        self.store = store
        self.recorder = recorder
        self._fragments: dict[tuple[str, frozenset[str]], str] = {}
        self._hops: dict[str, frozenset[str]] = {}
        self._module_names: dict[str, str] = {}
        self._module_count = -1
        self.carried = 0
        self.recorded = 0
        self.unrecorded: Counter[str] = Counter()
        self._write_warned = False

    @classmethod
    def open(
        cls,
        store_root: str | os.PathLike[str],
        *,
        start: str | os.PathLike[str],
        extra: Callable[[Tree], Mapping[str, Any]],
        record: bool = True,
        tree: Tree | None = None,
        recorder: Recorder | None = None,
    ) -> "CarrySession | None":
        tree = tree or Tree.open(start)
        if not tree.clean:
            narrate(
                f"SCORECARD CARRY disabled: {tree.reason}; everything reruns and "
                "nothing is recorded"
            )
            return None
        key = env_key(extra(tree))
        store = Store(store_root, key)
        store.touch()
        if record and recorder is None:
            try:
                recorder = Recorder(tree)
                recorder.start()
            except RuntimeError as exc:
                narrate(f"SCORECARD CARRY recording unavailable: {exc}")
                recorder = None
        narrate(f"SCORECARD CARRY open key={key} store={store.base}")
        return cls(tree, store, recorder if record else None)

    def quiet(self) -> Any:
        return self.recorder.quiet() if self.recorder is not None else _NoQuiet()

    def lookup(self, kind: str, ident: str) -> Any:
        with self.quiet():
            try:
                return self.store.lookup(kind, ident, self.tree)
            except OSError:
                return None

    def record(
        self, kind: str, ident: str, sinks: Iterable[Sink | None], payload: Any
    ) -> str | None:
        """Store ``payload`` under the union of ``sinks``; return why not, or None."""
        if self.recorder is None:
            self.unrecorded["no recorder"] += 1
            return "no recorder"
        with self.quiet():
            merged = Sink.union([self.recorder.baseline, *sinks])
            if merged.opaque:
                reason = "opaque " + ",".join(sorted(merged.opaque)[:3])
                self.unrecorded["opaque"] += 1
                return reason
            try:
                depset = self._depset(merged)
                depset_sha = self.store.put_object(depset)
                self.store.record(kind, ident, depset_sha, payload)
            except (OSError, TypeError, ValueError) as exc:
                if not self._write_warned:
                    narrate(f"SCORECARD CARRY store write failed: {exc}")
                    self._write_warned = True
                self.unrecorded["store"] += 1
                return f"store {exc}"
            self.recorded += 1
            return None

    def _depset(self, merged: Sink) -> dict[str, Any]:
        mods: dict[str, set[str]] = {}
        for rel, qual in merged.keys:
            mods.setdefault(rel, set()).add(qual)
        for rel in list(mods):
            mods[rel].add(MODULE_KEY)
            for other in self._one_hop(rel):
                mods.setdefault(other, set()).add(MODULE_KEY)
        entries = []
        for rel in sorted(mods):
            fragment = self._fragment(rel, frozenset(mods[rel]))
            entries.append([rel, self.tree.blob(rel), fragment])
        return {
            "mods": entries,
            "files": sorted([rel, self.tree.blob(rel)] for rel in merged.files),
            "dirs": sorted([rel, self.tree.listing(rel)] for rel in merged.dirs),
        }

    def _fragment(self, rel: str, quals: frozenset[str]) -> str:
        key = (rel, quals)
        sha = self._fragments.get(key)
        if sha is None:
            table, _ = self.tree.table(rel)
            fragment = {"path": rel, "fns": {q: table.get(q, ABSENT) for q in sorted(quals)}}
            sha = self.store.put_object(fragment)
            self._fragments[key] = sha
        return sha

    def _module_name(self, rel: str) -> str | None:
        if rel not in self._module_names and len(sys.modules) != self._module_count:
            self._module_count = len(sys.modules)
            for name, module in list(sys.modules.items()):
                file = getattr(module, "__file__", None)
                if file:
                    found = self.tree.rel(file)
                    if found is not None:
                        self._module_names.setdefault(found, name)
        return self._module_names.get(rel)

    def _one_hop(self, rel: str) -> frozenset[str]:
        cached = self._hops.get(rel)
        if cached is not None:
            return cached
        name = self._module_name(rel)
        module = sys.modules.get(name) if name else None
        package = getattr(module, "__package__", None) or ""
        _, imports = self.tree.table(rel)
        out: set[str] = set()
        for level, target, names in imports:
            if level:
                if not package:
                    continue
                parts = package.split(".")
                if level > 1:
                    parts = parts[: len(parts) - (level - 1)]
                base = ".".join(parts + ([target] if target else []))
                candidates = [base] + [f"{base}.{n}" for n in names if n != "*"]
            elif names:
                base = target or ""
                candidates = [base] + [f"{base}.{n}" for n in names if n != "*"]
            else:
                pieces = (target or "").split(".")
                candidates = [".".join(pieces[: i + 1]) for i in range(len(pieces))]
            for candidate in candidates:
                found = sys.modules.get(candidate) if candidate else None
                file = getattr(found, "__file__", None) if found is not None else None
                if file:
                    other = self.tree.rel(file)
                    if other and other != rel and other not in INSTRUMENT_FILES:
                        out.add(other)
        result = frozenset(out)
        self._hops[rel] = result
        return result

    def close(self) -> None:
        if self.recorder is not None:
            self.recorder.stop()


# ---------------------------------------------------------------------- board


class BoardCarry:
    """The pandas board's carry, for one recensus process.

    A recensus process keeps corpus-wide memos across the files it measures
    (module materialization, demand rows), so a file's row can depend on code
    that ran for an earlier file. Each file is therefore recorded with the
    CUMULATIVE depset of the process up to that file: everything that ran
    since the process started. That is sound against the memos; the price is
    that a change to code every file runs reruns every file.
    """

    TOOL = "control-effect-recensus"

    def __init__(self, store_root: str | os.PathLike[str], repo_root: str | os.PathLike[str]):
        self.store_root = store_root
        self.tree = Tree.open(repo_root)
        self.recorder: Recorder | None = None
        self.sink: Sink | None = None
        self.session: CarrySession | None = None
        self.carried = 0
        self.rerun = 0
        self.unrecorded = 0
        self.status = "open"
        if not self.tree.clean:
            self.status = f"disabled ({self.tree.reason})"
            return
        try:
            self.recorder = Recorder(self.tree)
            self.recorder.start()
            self.sink = self.recorder.push()
        except RuntimeError as exc:
            self.recorder = None
            self.status = f"recording unavailable ({exc})"

    def bind(self, extra: Mapping[str, Any]) -> None:
        """Open the store once the corpus identity is known."""
        if not self.tree.clean:
            return
        self.session = CarrySession.open(
            self.store_root,
            start=self.tree.root,
            extra=lambda _tree: {"tool": self.TOOL, **extra},
            record=self.recorder is not None,
            tree=self.tree,
            recorder=self.recorder,
        )

    def lookup(self, file: str) -> dict[str, Any] | None:
        if self.session is None:
            return None
        payload = self.session.lookup("board", file)
        row = payload.get("row") if isinstance(payload, dict) else None
        if isinstance(row, dict):
            self.carried += 1
            return row
        return None

    def record(self, file: str, row: Mapping[str, Any] | None) -> None:
        """Count a measured file; store its row when ``row`` is not None."""
        self.rerun += 1
        if row is None or self.session is None:
            self.unrecorded += 1
            return
        if self.session.record("board", file, [self.sink], {"row": row}) is not None:
            self.unrecorded += 1

    def line(self) -> str:
        key = self.session.store.key if self.session is not None else "none"
        return (
            f"carried={self.carried} rerun={self.rerun} unrecorded={self.unrecorded} "
            f"key={key} status={self.status}"
        )


# ------------------------------------------------------------------------ CLI


def _write_json(path: str | os.PathLike[str], obj: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def cmd_suite_plan(args: argparse.Namespace) -> int:
    """Split test files into fully carried (no pytest at all) and to run."""
    t0 = time.perf_counter()
    paths = [
        line.strip()
        for line in Path(args.paths_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rerun = list(paths)
    items: dict[str, dict[str, Any]] = {}
    session = CarrySession.open(
        args.store,
        start=args.rootdir,
        extra=lambda tree: pytest_key_extra(tree, args.rootdir, args.label),
        record=False,
    )
    if session is not None:
        rerun = []
        for path in paths:
            record = session.lookup("file", path)
            nodeids = record.get("nodeids") if isinstance(record, dict) else None
            if not isinstance(nodeids, list):
                rerun.append(path)
                continue
            got: dict[str, list[str]] | None = {}
            for nodeid in nodeids:
                payload = session.lookup("test", nodeid)
                buckets = payload.get("buckets") if isinstance(payload, dict) else None
                if not isinstance(buckets, list):
                    got = None
                    break
                got[nodeid] = buckets
            if got is None:
                rerun.append(path)
                continue
            for nodeid, buckets in got.items():
                items[nodeid] = {"buckets": buckets, "how": "carried"}
    wall = round(time.perf_counter() - t0, 3)
    _write_json(
        args.summary,
        {
            "schema": SUMMARY_SCHEMA,
            "label": args.label,
            "items": items,
            "collectionErrors": [],
            "opaque": {},
            "filesCarried": len(paths) - len(rerun),
            "filesRerun": len(rerun),
            "wallSeconds": wall,
        },
    )
    Path(args.rerun_paths).write_text(
        "".join(f"{p}\n" for p in rerun), encoding="utf-8"
    )
    narrate(
        f"SCORECARD CARRY PLAN label={args.label} files={len(paths)} "
        f"files_carried={len(paths) - len(rerun)} files_rerun={len(rerun)} "
        f"tests_carried={len(items)} wall_s={wall}"
    )
    return 0


def summarize(inputs: Iterable[str | os.PathLike[str]], label: str) -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}
    errors: set[str] = set()
    opaque: dict[str, str] = {}
    read = 0
    for path in inputs:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        read += 1
        for nodeid, entry in (doc.get("items") or {}).items():
            previous = items.get(nodeid)
            # A fresh result always wins over a carried one.
            if previous is None or (
                previous.get("how") == "carried" and entry.get("how") == "rerun"
            ):
                items[nodeid] = entry
        errors.update(doc.get("collectionErrors") or [])
        opaque.update(doc.get("opaque") or {})
    counts = {bucket: 0 for bucket in BUCKETS}
    not_reported = 0
    for entry in items.values():
        buckets = entry.get("buckets") or []
        if not buckets:
            not_reported += 1
        for bucket in buckets:
            if bucket in counts:
                counts[bucket] += 1
    rerun = sum(1 for entry in items.values() if entry.get("how") == "rerun")
    reasons = Counter(opaque.values())
    return {
        "schema": "sugar-scorecard-carry-totals/v1",
        "label": label,
        "inputsRead": read,
        "counts": {
            "collected": len(items),
            **counts,
            "collectionError": len(errors),
            "notReported": not_reported,
        },
        "carry": {"rerun": rerun, "carried": len(items) - rerun, "opaque": len(opaque)},
        "collectionErrorNodeIds": sorted(errors),
        "opaqueReasons": dict(reasons.most_common(10)),
    }


def cmd_summarize(args: argparse.Namespace) -> int:
    totals = summarize(args.inputs, args.label)
    _write_json(args.out, totals)
    c, k = totals["counts"], totals["carry"]
    if args.result:
        # The scorecard's view (tools/main_scorecard_post.py --put).
        t0 = os.environ.get("JOB_T0", "")
        _write_json(
            args.result,
            {
                "measured": bool(totals["inputsRead"]) and c["collected"] > 0,
                "passed": c["passed"],
                "total": c["collected"],
                "failed": c["failed"] + c["error"] + c["collectionError"],
                "carry": k,
                "jobWallSeconds": int(time.time() - float(t0)) if t0 else None,
            },
        )
    narrate(
        f"SCORECARD CARRY TOTALS label={args.label} collected={c['collected']} "
        f"passed={c['passed']} failed={c['failed']} error={c['error']} "
        f"collectionError={c['collectionError']} rerun={k['rerun']} "
        f"carried={k['carried']} opaque={k['opaque']}"
    )
    return 0


def tree_key(includes: list[str], excludes: list[str], extras: list[str]) -> str:
    """A coarse content key for a measure whose dependencies are not traced."""
    top = subprocess.run(
        ["git", "ls-tree", "HEAD"], capture_output=True, text=True, check=True
    ).stdout
    material = [line for line in top.splitlines() if line.split("\t")[-1] not in excludes]
    for path in includes:
        material.append(
            path
            + "="
            + subprocess.run(
                ["git", "rev-parse", f"HEAD:{path}"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
    material.extend(extras)
    material.append(env_key({"tool": "verdict"}))
    return _sha("\n".join(material).encode("utf-8"))[:32]


def cmd_verdict(args: argparse.Namespace) -> int:
    path = Path(args.store) / "verdicts" / args.name / f"{args.key}.json"
    if args.action == "key":
        print(tree_key(args.include, args.exclude, args.extra))
        return 0
    if args.action == "get":
        try:
            print(json.loads(path.read_text(encoding="utf-8"))["verdict"])
        except (OSError, ValueError, KeyError):
            return 3
        return 0
    _write_json(path, {"verdict": args.value, "recordedAt": time.time()})
    return 0


def cmd_gc(args: argparse.Namespace) -> int:
    root = Path(args.store)
    if not root.is_dir():
        return 0
    now = time.time()
    removed_keys = removed_objects = 0
    for keydir in root.iterdir():
        if not keydir.is_dir() or keydir.name == "verdicts":
            continue
        marker = keydir / "last-used"
        try:
            age = now - (marker if marker.exists() else keydir).stat().st_mtime
        except OSError:
            continue
        if age > args.stale_key_days * 86400:
            shutil.rmtree(keydir, ignore_errors=True)
            removed_keys += 1
            continue
        store = Store(root, keydir.name)
        live: set[str] = set()
        for entry in (keydir / "index").rglob("*.json"):
            try:
                depset_sha = json.loads(entry.read_bytes())["depset"]
            except (OSError, ValueError, KeyError):
                continue
            if depset_sha in live:
                continue
            live.add(depset_sha)
            depset = store.get_object(depset_sha)
            if isinstance(depset, dict):
                live.update(m[2] for m in depset.get("mods") or [])
        for obj in (keydir / "objects").rglob("*.json"):
            try:
                if obj.stem not in live and now - obj.stat().st_mtime > args.min_age_s:
                    obj.unlink()
                    removed_objects += 1
            except OSError:
                continue
    narrate(f"SCORECARD CARRY GC removed_keys={removed_keys} removed_objects={removed_objects}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("suite-plan", help="which test files need pytest at all")
    plan.add_argument("--store", required=True)
    plan.add_argument("--rootdir", default=".")
    plan.add_argument("--label", default="suite")
    plan.add_argument("--paths-file", required=True)
    plan.add_argument("--summary", required=True)
    plan.add_argument("--rerun-paths", required=True)
    plan.set_defaults(func=cmd_suite_plan)

    summ = sub.add_parser("summarize", help="merge carry summaries into totals")
    summ.add_argument("--out", required=True)
    summ.add_argument("--label", default="suite")
    summ.add_argument("--result", default=None, help="also write the scorecard result")
    summ.add_argument("inputs", nargs="*")
    summ.set_defaults(func=cmd_summarize)

    verdict = sub.add_parser("verdict", help="carry a PASS keyed by a tree key")
    verdict.add_argument("action", choices=["key", "get", "put"])
    verdict.add_argument("--store", default="")
    verdict.add_argument("--name", default="")
    verdict.add_argument("--key", default="")
    verdict.add_argument("--value", default="")
    verdict.add_argument("--include", action="append", default=[])
    verdict.add_argument("--exclude", action="append", default=[])
    verdict.add_argument("--extra", action="append", default=[])
    verdict.set_defaults(func=cmd_verdict)

    gc = sub.add_parser("gc", help="drop stale keys and unreferenced objects")
    gc.add_argument("--store", required=True)
    gc.add_argument("--min-age-s", type=float, default=3600.0)
    gc.add_argument("--stale-key-days", type=float, default=7.0)
    gc.set_defaults(func=cmd_gc)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
