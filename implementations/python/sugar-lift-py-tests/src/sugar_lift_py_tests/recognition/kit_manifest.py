"""Process-level kit/bridge contract loader (#5907).

The empty-by-construction protocol tables in ``native_shape.py`` and
``callee_universe.py`` (#5618, #5400-class re-earns) only ever get populated
by calling their ``load_*_protocol`` functions. Tests do that in-process. The
gap #5907 names: nothing wired those loaders into the actual corpus mint
path (``corpus_fatal_triage.py``), so no real corpus row ever saw a loaded
contract — every re-earned family stayed FactoryPanic/unclassified in the
corpus even though the recognizer was correct.

This module is the bridge: it reads a **kit manifest** — a JSON file that is
evidence, not ambient configuration — and installs its coordinates into the
in-memory protocol tables for the current process before mint runs.

Evidence discipline:
  - The manifest is a file on disk, named explicitly (``--kit-manifest`` /
    ``SUGAR_KIT_MANIFEST``). Nothing here invents a default path or falls
    back to a hard-coded dict.
  - Every load computes and records the manifest's sha256 content hash
    (its CID) so the loaded contract is traceable to the exact bytes that
    authorized it, not to "whatever the dict happens to hold right now".
  - An unrecognized enum name in the manifest is a loud error (``ValueError``),
    never a silently-dropped coordinate.
  - With no manifest declared (env var unset, no --kit-manifest), this module
    installs nothing. The protocol tables stay empty. Rows stay loud. That is
    the law (#5907 requirement 3), not a bug to route around.

Manifest schema (JSON)::

    {
      "imported_callee": {"numpy.issubdtype": "NUMPY_ISSUBDTYPE", ...},
      "call_shape": {"sqlalchemy.orm.registry": "KIT_LOADED_CONSTRUCTOR", ...},
      "fixture_decorator": {"pytest.fixture": "FIXTURE_DECORATOR", ...},
      "instance_class_decorator": {
        "KIT_LOADED_CONSTRUCTOR.mapped": "CLASS_IDENTITY_DECORATOR"
      },
      "instance_call": {
        "PANDAS_DATAFRAME.equals": "pandas.DataFrame.equals"
      }
    }

Every top-level key is optional; an empty manifest is legal (loads nothing).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeUniverseSupport,
    clear_imported_callee_protocol,
    load_imported_callee_protocol,
)
from sugar_lift_py_tests.recognition.native_shape import (
    NativeShape,
    clear_call_shape_protocol,
    clear_fixture_protocol,
    clear_instance_call_protocol,
    clear_instance_class_decorator_protocol,
    load_call_shape_protocol,
    load_fixture_protocol,
    load_instance_call_protocol,
    load_instance_class_decorator_protocol,
)

KIT_MANIFEST_ENV_VAR = "SUGAR_KIT_MANIFEST"

_IMPORTED_CALLEE_SECTION = "imported_callee"
_CALL_SHAPE_SECTION = "call_shape"
_FIXTURE_DECORATOR_SECTION = "fixture_decorator"
_INSTANCE_CLASS_DECORATOR_SECTION = "instance_class_decorator"
_INSTANCE_CALL_SECTION = "instance_call"

_KNOWN_SECTIONS = frozenset(
    {
        _IMPORTED_CALLEE_SECTION,
        _CALL_SHAPE_SECTION,
        _FIXTURE_DECORATOR_SECTION,
        _INSTANCE_CLASS_DECORATOR_SECTION,
        _INSTANCE_CALL_SECTION,
    }
)


@dataclass(frozen=True)
class KitManifestProvenance:
    """Receipt for a loaded kit manifest: what loaded, from where, under what hash."""

    path: str
    sha256: str
    loaded_counts: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "loaded_counts": dict(self.loaded_counts),
        }


class KitManifestError(ValueError):
    """A kit manifest named a coordinate this process cannot honor.

    Raised loudly — never caught to silently drop a coordinate. A manifest
    that cannot be fully honored is a manifest that must not load partially.
    """


def _resolve_enum(kind: type, name: str, *, section: str, key: str) -> object:
    try:
        return kind[name]
    except KeyError as error:
        raise KitManifestError(
            f"kit manifest section {section!r} names unknown "
            f"{kind.__name__} member {name!r} for coordinate {key!r}"
        ) from error


def clear_all_kit_protocols() -> None:
    """Unload every kit-loaded protocol table (test isolation / re-load)."""

    clear_imported_callee_protocol()
    clear_call_shape_protocol()
    clear_fixture_protocol()
    clear_instance_class_decorator_protocol()
    clear_instance_call_protocol()


def load_kit_manifest_text(text: str, *, source: str) -> KitManifestProvenance:
    """Parse and install a kit manifest given as text (source is its label)."""

    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise KitManifestError(f"kit manifest {source!r} is not valid JSON") from error
    if not isinstance(document, dict):
        raise KitManifestError(f"kit manifest {source!r} must be a JSON object")
    unknown = set(document) - _KNOWN_SECTIONS
    if unknown:
        raise KitManifestError(
            f"kit manifest {source!r} names unknown section(s): {sorted(unknown)}"
        )

    sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    counts: dict[str, int] = {}

    imported_callee_raw = document.get(_IMPORTED_CALLEE_SECTION) or {}
    if imported_callee_raw:
        coordinates = {
            key: _resolve_enum(
                CalleeUniverseSupport, value, section=_IMPORTED_CALLEE_SECTION, key=key
            )
            for key, value in imported_callee_raw.items()
        }
        load_imported_callee_protocol(coordinates)
        counts[_IMPORTED_CALLEE_SECTION] = len(coordinates)

    call_shape_raw = document.get(_CALL_SHAPE_SECTION) or {}
    if call_shape_raw:
        coordinates = {
            key: _resolve_enum(NativeShape, value, section=_CALL_SHAPE_SECTION, key=key)
            for key, value in call_shape_raw.items()
        }
        load_call_shape_protocol(coordinates)
        counts[_CALL_SHAPE_SECTION] = len(coordinates)

    fixture_raw = document.get(_FIXTURE_DECORATOR_SECTION) or {}
    if fixture_raw:
        coordinates = {
            key: _resolve_enum(
                NativeShape, value, section=_FIXTURE_DECORATOR_SECTION, key=key
            )
            for key, value in fixture_raw.items()
        }
        load_fixture_protocol(coordinates)
        counts[_FIXTURE_DECORATOR_SECTION] = len(coordinates)

    instance_class_raw = document.get(_INSTANCE_CLASS_DECORATOR_SECTION) or {}
    if instance_class_raw:
        coordinates = {}
        for key, value in instance_class_raw.items():
            head, _sep, tail = key.partition(".")
            if not _sep:
                raise KitManifestError(
                    f"kit manifest {source!r} instance_class_decorator key "
                    f"{key!r} must be 'NativeShapeMember.attr'"
                )
            shape = _resolve_enum(
                NativeShape, head, section=_INSTANCE_CLASS_DECORATOR_SECTION, key=key
            )
            result_shape = _resolve_enum(
                NativeShape,
                value,
                section=_INSTANCE_CLASS_DECORATOR_SECTION,
                key=key,
            )
            coordinates[(shape, tail)] = result_shape
        load_instance_class_decorator_protocol(coordinates)
        counts[_INSTANCE_CLASS_DECORATOR_SECTION] = len(coordinates)

    instance_call_raw = document.get(_INSTANCE_CALL_SECTION) or {}
    if instance_call_raw:
        coordinates_str: dict[tuple[NativeShape, str], str] = {}
        for key, value in instance_call_raw.items():
            head, _sep, tail = key.partition(".")
            if not _sep:
                raise KitManifestError(
                    f"kit manifest {source!r} instance_call key "
                    f"{key!r} must be 'NativeShapeMember.attr'"
                )
            shape = _resolve_enum(
                NativeShape, head, section=_INSTANCE_CALL_SECTION, key=key
            )
            if not isinstance(value, str):
                raise KitManifestError(
                    f"kit manifest {source!r} instance_call value for "
                    f"{key!r} must be a coordinate string, not {value!r}"
                )
            coordinates_str[(shape, tail)] = value
        load_instance_call_protocol(coordinates_str)
        counts[_INSTANCE_CALL_SECTION] = len(coordinates_str)

    return KitManifestProvenance(path=source, sha256=sha256, loaded_counts=counts)


def load_kit_manifest_file(path: str | os.PathLike[str]) -> KitManifestProvenance:
    """Read, hash, and install a kit manifest from an explicit file path.

    The path is evidence: a real file the caller named. There is no implicit
    default manifest and no ambient dict a coordinate could sneak into.
    """

    text = Path(path).read_text(encoding="utf-8")
    return load_kit_manifest_text(text, source=str(path))


def load_kit_manifest_from_env(
    env: dict[str, str] | None = None,
) -> KitManifestProvenance | None:
    """Install the manifest named by ``SUGAR_KIT_MANIFEST``, if any.

    Returns ``None`` (and loads nothing) when the variable is unset — the
    empty-by-construction default. This is the entry point the corpus mint
    child process calls before lift, so a declared contract reaches real
    corpus rows without any coordinate ever living in production recognition
    source.
    """

    source = env if env is not None else os.environ
    manifest_path = source.get(KIT_MANIFEST_ENV_VAR)
    if not manifest_path:
        return None
    return load_kit_manifest_file(manifest_path)
