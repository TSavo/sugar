"""Opt-in refusal trace: what the reduction held where the kit refused.

Instrument only. Off unless ``SUGAR_KIT_TRACE_REFUSALS=1``; nothing it does
changes a refusal, a member or a proof byte.

A refusal names its owner and what it observed, and the proof keeps exactly
that (``tree_enumerate._refused_row``). That is not enough to find why a read
refused: ``EvaluationRefSugar`` refuses a read whose key "is unbound" where
both arms of an ``if`` bind the name, and only the binding state at the
refusing read says which key the read took and which keys the path did bind.
An agent that may only drive CI (``.github/workflows/lift-trace.yml``) reads
that state from this trace.

With the switch on, every construction refusal raised through the one panic
door (``gap.panic.construction_panic``) appends one JSON line to
``$SUGAR_KIT_TRACE_DIR/refusals-<pid>.jsonl`` (to stderr, prefixed
``SUGAR_KIT_REFUSAL_TRACE``, when no directory is named) holding:

* the refusal's testimony whole: ``owner``, ``blame`` (the coordinate),
  ``observed``, ``requested``, ``fix`` (each kept to ``TEXT_CHARS``);
* ``detail``: what the refusing door passed (for an unbound evaluation: the
  ``name`` read, the ``key`` it took, the construct-time ``evaluation``);
* ``liveIterations`` and ``occurrencePath``: where the reduction is;
* ``evaluating``: the sugar whose evaluation is running and its site;
* ``bindings``: the temporal at the refusal, newest last, every key bound on
  the current path (builtin names omitted) with the binding's kind, its blame
  and its value's type (never the value's ``repr``: reading it may construct);
* ``near``: the bound keys that share the read key's construct-time
  evaluation (the same coordinate under another live-item qualification, a
  projection of it), so a key bound under a neighbour spelling is in view;
* ``trace``: the Python frames from the lift's entry to the panic site
  (module, qualname, file, line), the same shape as the enumerate RPC's
  ``construction_trace``.

Every refusal raised is recorded, including one a caller later answers (a
refusal is a ``BaseException`` some doors catch and state as a member); the
lane's refusal list says which ones reached the proof.  At most
``SUGAR_KIT_TRACE_MAX`` records (default 2000) are written per process.
"""

from __future__ import annotations

import json
import os
import sys

ENV_ON = "SUGAR_KIT_TRACE_REFUSALS"
ENV_DIR = "SUGAR_KIT_TRACE_DIR"
ENV_MAX = "SUGAR_KIT_TRACE_MAX"
STDERR_PREFIX = "SUGAR_KIT_REFUSAL_TRACE "
TEXT_CHARS = 4096
MAX_BINDINGS = 4000
MAX_FRAMES = 300
DEFAULT_MAX_RECORDS = 2000
_FRAME_MODULE_PREFIXES = ("sugar_lift_py_tests", "sugar_source_tree", "sugar_lift_python_source")

_written = 0
_builtin_values: dict[str, object] | None = None


def enabled() -> bool:
    return os.environ.get(ENV_ON) == "1"


def _text(value: object) -> str:
    text = value if isinstance(value, str) else str(value)
    return text[:TEXT_CHARS]


def _max_records() -> int:
    try:
        return int(os.environ.get(ENV_MAX) or DEFAULT_MAX_RECORDS)
    except ValueError:
        return DEFAULT_MAX_RECORDS


def _builtins() -> dict[str, object]:
    """The builtin names' bindings (``TemporalContext.empty``), by key: a
    binding holding the very same value is the builtin, never traced."""
    global _builtin_values
    if _builtin_values is None:
        from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

        _builtin_values = {b.name: b.value for b in builtin_name_temporal().bindings}
    return _builtin_values


def _bindings(temporal) -> tuple[list[dict], int]:
    rows: list[dict] = []
    bindings = tuple(getattr(temporal, "bindings", ()) or ())
    builtin = _builtins()
    for binding in bindings:
        name = getattr(binding, "name", None)
        value = getattr(binding, "value", None)
        if name in builtin and builtin[name] is value:
            continue
        blame = getattr(binding, "blame", None)
        rows.append(
            {
                "key": name,
                "kind": type(binding).__name__,
                "blame": None if blame is None else _text(blame),
                "valueType": type(value).__name__,
            }
        )
    return rows[-MAX_BINDINGS:], len(rows)


def _near(rows: list[dict], detail: dict) -> list[str]:
    """The bound keys spelling the read's construct-time evaluation: itself,
    under a live-item qualification (``<evaluation>@...``), or a projection
    of it (``<evaluation>/<name>``, ``projection_key``)."""
    bases = {
        value.split("@", 1)[0]
        for value in (detail.get("key"), detail.get("evaluation"))
        if isinstance(value, str) and value
    }
    if not bases:
        return []

    def spells(key: object) -> bool:
        return isinstance(key, str) and any(
            key == base or key.startswith((f"{base}@", f"{base}/")) for base in bases
        )

    return [row["key"] for row in rows if spells(row["key"])]


def _frames(skip: int) -> list[dict]:
    frames: list[dict] = []
    frame = sys._getframe(skip)
    while frame is not None and len(frames) < MAX_FRAMES:
        module = str(frame.f_globals.get("__name__") or "")
        if module.startswith(_FRAME_MODULE_PREFIXES):
            frames.append(
                {
                    "module": module,
                    "qualname": getattr(frame.f_code, "co_qualname", frame.f_code.co_name),
                    "file": frame.f_code.co_filename.rsplit("/src/", 1)[-1],
                    "line": frame.f_lineno,
                }
            )
        frame = frame.f_back
    frames.reverse()  # outermost first, the panic site last
    return frames


def _evaluating() -> tuple[object, dict | None]:
    """The temporal of the evaluation running now, and what it is."""
    from sugar_lift_py_tests.sugar.sugar_base import evaluating

    running = evaluating()
    if not running:
        return None, None
    sugar, ctx = running
    site = getattr(sugar, "site", None)
    return getattr(ctx, "temporal", None), {
        "sugar": type(sugar).__name__,
        "site": None if site is None else _text(site),
    }


def _write(record: dict) -> None:
    line = json.dumps(record, sort_keys=True, default=str)
    directory = os.environ.get(ENV_DIR)
    if directory:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"refusals-{os.getpid()}.jsonl")
        with open(path, "a", encoding="utf-8") as sink:
            sink.write(line + "\n")
    else:
        sys.stderr.write(STDERR_PREFIX + line + "\n")
        sys.stderr.flush()


def record_refusal(info, *, temporal=None, detail: dict | None = None) -> None:
    """One trace line for the refusal ``info`` (a ``ConstructionGap``) about
    to be raised, when the switch is on.  ``temporal``: the binding state at
    the refusing read where the door has it (else the running evaluation's);
    ``detail``: the door's own names (key, evaluation, name).  Never raises:
    a trace that cannot be written is dropped, and the refusal stands."""
    global _written
    if not enabled() or _written >= _max_records():
        return
    _written += 1
    detail = {k: v for k, v in (detail or {}).items() if v is not None}
    try:
        from sugar_lift_py_tests.occurrence import current_path, live_iterations

        running_temporal, running = _evaluating()
        if temporal is None:
            temporal = running_temporal
        rows, total = _bindings(temporal) if temporal is not None else ([], 0)
        record = {
            "owner": _text(getattr(info, "owner", "")),
            "blame": _text(getattr(info, "blame", "")),
            "observed": _text(getattr(info, "observed", "")),
            "requested": _text(getattr(info, "requested", "")),
            "fix": _text(getattr(info, "fix", "")),
            "detail": {k: _text(v) for k, v in detail.items()},
            "liveIterations": list(live_iterations()),
            "occurrencePath": list(current_path()),
            "evaluating": running,
            "temporal": temporal is not None,
            "bindingsTotal": total,
            "bindings": rows,
            "near": _near(rows, detail),
            "trace": _frames(2),
        }
        _write(record)
    except (OSError, ValueError, TypeError, AttributeError, LookupError, RecursionError):
        return
