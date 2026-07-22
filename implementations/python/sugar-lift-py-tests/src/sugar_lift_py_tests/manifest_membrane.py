"""The hashed kit-manifest enrollment membrane (issue #5994, implementation
order items 1 and 6).

Community coordinates (`pytest.raises`, `contextlib.suppress`,
`tm.assert_produces_warning`, ...) enter the typed context-manager contract
(`sugar_lift_py_tests.context_manager_contract`) ONLY through an explicitly
loaded, hashed manifest. No vendor spelling may appear in this file, or in
any other `.py` file that consumes it — spellings live exclusively in the
manifest JSON data loaded at runtime.

Manifest format (JCS-canonicalized JSON)::

    {
      "rows": [
        {"spelling": "pytest.raises", "arity": "one-exception-arg",
         "contract": "expects", "effect_kind": "raise"},
        ...
      ],
      "cid": "blake3-512:<128 lowercase hex>"
    }

The `cid` is the BLAKE3-512 JCS hash (see `canonicalizer.jcs_hash`) of the
`rows` array alone. `load_manifest` recomputes that hash from the bytes on
disk and REFUSES (raises `ManifestIntegrityError`) on any mismatch — never a
warning. A manifest carries its own integrity; nothing loads implicitly, and
nothing loads silently-wrong.

The membrane's other half, `contract_for_manager`, inspects a `with`-item's
manager expression STRUCTURALLY: a `Call` whose callee is a dotted
`Name`/`Attribute` chain, matched against enrolled spellings; the single
positional argument must itself be a dotted `Name`/`Attribute` chain, whose
dotted string becomes the matcher's exception/warning name. Keyword
arguments, extra positional arguments, or a non-dotted argument all yield
`None` — unauthenticated, loud, never guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from sugar_lift_py_tests.canonicalizer import Value, jcs_hash, varr, vobj, vstr
from sugar_lift_py_tests.context_manager_contract import (
    Contract,
    EffectMatcher,
    Expects,
    Suppresses,
)

# Manifest schema vocabulary. ``never-suppresses`` is deliberately reserved
# without an issuer below or an enrolled row in the committed manifest: the
# tree cannot yet represent its finally-faithful exceptional exit. Naming the
# future proof kind is not permission to infer it from a manager call.
MANIFEST_CONTRACT_KINDS = frozenset(
    {"expects", "suppresses", "never-suppresses"}
)

def _expects_with_binding(matcher: EffectMatcher) -> Expects:
    """Issue Expects with the membrane-declared as-binding projection.

    raise → exception_info (pytest.raises as ei; ei.value is the effect slot)
    warning → warning_observation
    Tree never names pytest; it only sees the typed projection string.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EXCEPTION_INFO,
        WARNING_OBSERVATION,
    )

    binding = None
    if matcher.kind == "raise":
        binding = EXCEPTION_INFO
    elif matcher.kind == "warning":
        binding = WARNING_OBSERVATION
    return Expects(matcher=matcher, binding=binding)


_CONTRACT_BUILDERS = {
    "expects": _expects_with_binding,
    "suppresses": Suppresses,
}


class ManifestIntegrityError(Exception):
    """Raised, loudly, when a manifest's `cid` does not match its `rows`."""


@dataclass(frozen=True)
class ManifestRow:
    spelling: str
    arity: str
    contract: str
    effect_kind: str


@dataclass(frozen=True)
class Manifest:
    rows: Tuple[ManifestRow, ...]
    cid: str
    path: Path

    def row_for_spelling(self, spelling: str) -> Optional[ManifestRow]:
        for row in self.rows:
            if row.spelling == spelling:
                return row
        return None


def _row_to_value(row: dict) -> Value:
    return vobj(
        [
            ("spelling", vstr(row["spelling"])),
            ("arity", vstr(row["arity"])),
            ("contract", vstr(row["contract"])),
            ("effect_kind", vstr(row["effect_kind"])),
        ]
    )


def _rows_hash(rows: list) -> str:
    return jcs_hash(varr([_row_to_value(row) for row in rows]))


def load_manifest(path: str | Path) -> Manifest:
    """Load a hashed kit manifest, verifying its integrity.

    Recomputes the JCS/BLAKE3-512 hash of the `rows` array and compares it
    against the manifest's own `cid` field. A mismatch REFUSES to load: it
    raises `ManifestIntegrityError` rather than loading with a warning. This
    is the only lawful path by which community spellings enter the
    provider-neutral contract types.
    """
    manifest_path = Path(path)
    raw = manifest_path.read_text(encoding="utf-8")
    data = json.loads(raw)

    if "rows" not in data or "cid" not in data:
        raise ManifestIntegrityError(
            f"manifest at {manifest_path} is missing required 'rows' or 'cid' field"
        )

    rows_data = data["rows"]
    declared_cid = data["cid"]
    computed_cid = _rows_hash(rows_data)

    if computed_cid != declared_cid:
        raise ManifestIntegrityError(
            f"manifest at {manifest_path} FAILED integrity check: "
            f"declared cid {declared_cid!r} does not match computed cid "
            f"{computed_cid!r} over its rows. Refusing to load."
        )

    rows = tuple(
        ManifestRow(
            spelling=row["spelling"],
            arity=row["arity"],
            contract=row["contract"],
            effect_kind=row["effect_kind"],
        )
        for row in rows_data
    )
    return Manifest(rows=rows, cid=declared_cid, path=manifest_path)


def _dotted_name_of(node) -> Optional[str]:
    """Return the dotted-name string of a Name/Attribute chain, or None if
    the node is not structurally a pure dotted-name chain (e.g. a call
    result, subscript, or literal)."""
    # Local import: this module must not import sugar_source_tree.nodes at
    # module scope to stay decoupled from a specific tree revision, but the
    # membrane still needs the concrete classes to do structural isinstance
    # checks.
    from sugar_source_tree.nodes import Attribute, Name

    if isinstance(node, Name):
        return node.id
    if isinstance(node, Attribute):
        base = _dotted_name_of(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def contract_for_manager(manifest: Manifest, manager_node) -> Optional[Contract]:
    """Issue the typed contract for a `with`-item's manager expression, or
    `None` if the manager is not an authenticated, structurally-matching
    enrollment. `None` means unauthenticated: the caller stays loud.
    """
    from sugar_source_tree.nodes import Call

    if not isinstance(manager_node, Call):
        return None

    spelling = _dotted_name_of(manager_node.func)
    if spelling is None:
        return None

    row = manifest.row_for_spelling(spelling)
    if row is None:
        return None

    if row.arity == "one-exception-arg":
        if manager_node.keywords:
            return None
        if len(manager_node.args) != 1:
            return None
        name = _dotted_name_of(manager_node.args[0])
        if name is None:
            return None
        matcher = EffectMatcher(kind=row.effect_kind, name=name)
        builder = _CONTRACT_BUILDERS.get(row.contract)
        if builder is None:
            return None
        return builder(matcher)

    if row.arity == "exception-arg-optional-match":
        # `raises(E)` or `raises(E, match=<str literal>)`. ONLY the enrolled
        # kwarg is admitted; the pattern becomes an independently dischargeable
        # MessagePattern payload obligation (T's ruling: the conjunction). All
        # of these stay unauthenticated (None -> loud): unknown kwargs,
        # duplicate match, match=None (community semantics unpinned), a
        # non-literal pattern (nothing to state), an invalid regex (its own
        # effect, never folded into non-match).
        if len(manager_node.args) != 1:
            return None
        name = _dotted_name_of(manager_node.args[0])
        if name is None:
            return None
        payload: tuple = ()
        if manager_node.keywords:
            if len(manager_node.keywords) != 1:
                return None
            kw = manager_node.keywords[0]
            if kw.arg != "match":
                return None
            value = kw.value
            if value.kind != "Constant" or not isinstance(value.value, str):
                return None  # match=None / non-literal: unpinned or unstateable
            import re as _re

            try:
                _re.compile(value.value)
            except _re.error:
                return None  # invalid regex: its own effect, not a non-match
            from sugar_lift_py_tests.context_manager_contract import MessagePattern

            payload = (MessagePattern(value.value),)
        matcher = EffectMatcher(
            kind=row.effect_kind, name=name, payload_obligations=payload
        )
        builder = _CONTRACT_BUILDERS.get(row.contract)
        if builder is None:
            return None
        return builder(matcher)

    # Unknown arity discipline: refuse rather than guess.
    return None


def default_community_manifest() -> Manifest:
    """Explicitly load the committed community manifest by its known path.

    This accessor performs the load when CALLED — never at import time. No
    module-level side effect enrolls community coordinates merely by
    importing this module.
    """
    path = (
        Path(__file__).resolve().parent
        / "manifests"
        / "community_context_managers.json"
    )
    return load_manifest(path)
