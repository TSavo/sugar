"""Non-constructing lexical authentication for imported uses.

This pass owns only Python def-use.  It never imports a module, opens a target
module, or constructs Sugar.  Its output is the source-authenticated half of
the import-to-contract bridge protocol.

Two receipt faces share one reaching-definition walk:

- **Call targets** — ``authenticated_import_use_receipts`` (existing).
- **Value occurrences** — ``authenticated_import_value_use_receipts`` for
  source-visible imported ``Name`` and ``Attribute`` loads (caller actuals,
  helper identity operands).  Call-target rows stay a separate surface.
"""

from __future__ import annotations

import json
from functools import cached_property
from dataclasses import dataclass, field as dataclass_field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .canonicalizer import blake3_512_of, encode_jcs
from .context_manager_contract import _json_value

from sugar_source_tree.nodes import Expression, Module, Node, Statement


class UnsupportedStatementGrammar(RuntimeError):
    pass


TYPED_STATEMENT_KINDS = frozenset(
    {
        "FunctionDef",
        "AsyncFunctionDef",
        "ClassDef",
        "Return",
        "Delete",
        "Assign",
        "TypeAlias",
        "AugAssign",
        "AnnAssign",
        "For",
        "AsyncFor",
        "While",
        "If",
        "With",
        "AsyncWith",
        "Match",
        "Raise",
        "Try",
        "TryStar",
        "Assert",
        "Import",
        "ImportFrom",
        "Global",
        "Nonlocal",
        "Expr",
        "Pass",
        "Break",
        "Continue",
    }
)


class UnsupportedStatementVariant(RuntimeError):
    pass


def _hash(value: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(value)).encode("utf-8"))


def _site(source_cid: str, node: Node) -> dict[str, Any]:
    # Preserve the established module-scope coordinate: CPython's Module has
    # no span, so its authenticated coordinate is the body extent rather than
    # trailing whitespace at EOF.  The typed adapter's Module span includes
    # that whitespace; projecting the typed body keeps existing CIDs stable.
    if node.kind == "Module":
        if not node.body:
            return {
                "sourceCid": source_cid,
                "startLine": 1,
                "startCol": 0,
                "endLine": 1,
                "endCol": 0,
            }
        end = node.body[-1].line_col_span()
        return {
            "sourceCid": source_cid,
            "startLine": 1,
            "startCol": 0,
            "endLine": end.end_line,
            "endCol": end.end_col,
        }
    span = node.line_col_span()
    return {
        "sourceCid": source_cid,
        "startLine": span.start_line,
        "startCol": span.start_col,
        "endLine": span.end_line,
        "endCol": span.end_col,
    }


@dataclass(frozen=True)
class _ImportDef:
    cid: str
    target_symbol: str
    payload_jcs: str
    # ``import a.b.c`` (no ``as``) binds the local ``a`` while the binding's
    # module is ``a.b.c``: a use ``a.b.c.x`` names ``x`` of that module, so
    # its member path is read after the ``("b", "c")`` it spells.  ``a.y`` is
    # a member of the package ``a``, which this binding does not name.
    submodule_tail: tuple[str, ...] = ()
    # The optional-provider gate this binding came through, or ``None`` for an
    # ordinary import statement (see ``ImportReference.provider_gate``).
    provider_gate: str | None = None


# ``name = pytest.importorskip("m")``: an absent provider halts at that call,
# so every path past the statement reads the import.
PROVIDER_GATE_IMPORTORSKIP = "pytest.importorskip"
# ``try: import m`` / ``except ImportError``: an absent provider leaves the
# name unbound, so a reference reads the import only where the provider exists.
PROVIDER_GATE_TRY_IMPORT = "try-import"


@dataclass(frozen=True)
class ImportReference:
    """One row of the import reference table (#7837, #7851).

    ``target_symbol`` is the import-bound reference's target.  ``provider_gate``
    is the gate fact the binding carries: ``None`` for an import statement,
    ``PROVIDER_GATE_IMPORTORSKIP`` or ``PROVIDER_GATE_TRY_IMPORT`` for an
    optional provider.  Only a try-import row is not bound on every path that
    reaches it; a reader that cannot carry the provider-absent face (a call,
    a value use) does not read it.
    """

    target_symbol: str
    provider_gate: str | None = None

    @property
    def bound_on_every_path(self) -> bool:
        return self.provider_gate != PROVIDER_GATE_TRY_IMPORT


@dataclass(frozen=True)
class _ModuleFunctionDef:
    target_symbol: str
    definition_site: tuple[int, int, int, int]


_IMPORT_AUTHORITY = object()

# Closed demand-kind admission for AuthenticatedImportUseV1.  Unknown kinds
# must refuse — there is no fallthrough third surface.
_ADMITTED_IMPORT_DEMAND_KINDS = frozenset(
    {
        "call-contract-demand",
        "import-value-use-demand",
    }
)


@dataclass(frozen=True)
class ImportBindingV1:
    """A final-checked #6090 import binding, never a caller-owned mapping."""

    value: dict[str, Any]
    cid: str
    _authority: object = dataclass_field(
        repr=False, compare=False, metadata={"testimony": "authority"}
    )

    def __post_init__(self) -> None:
        if self._authority is not _IMPORT_AUTHORITY:
            raise ValueError("ImportBindingV1 was not minted by the lexical pass")
        if self.value.get("kind") != "python-import-binding":
            raise ValueError("ImportBindingV1 requires a python-import-binding")
        if _hash(self.value) != self.cid:
            raise ValueError("ImportBindingV1 CID does not match its preimage")

    def to_value(self) -> dict[str, Any]:
        return json.loads(encode_jcs(_json_value(self.value)))

    @property
    def preimage(self) -> dict[str, Any]:
        """The exact JSON ``cid`` authenticates (``__post_init__`` checks it).

        With ``cid`` this is a self-authenticating pair, so a constructed value
        that seats this binding references it by its validated native CID.
        """
        return self.to_value()


@dataclass(frozen=True)
class AuthenticatedImportUseV1:
    """The final lexical-pass receipt consumed by source-artifact resolution."""

    import_binding: ImportBindingV1
    target_symbol: str
    use: dict[str, Any]
    demand: dict[str, Any]
    root: Path = dataclass_field(repr=False, compare=False)
    path: Path = dataclass_field(repr=False, compare=False)
    source: str = dataclass_field(repr=False, compare=False)
    source_cid: str = dataclass_field(repr=False, compare=False)
    module_identities: dict[str, dict[str, Any]] = dataclass_field(
        repr=False, compare=False
    )
    _authority: object = dataclass_field(
        repr=False, compare=False, metadata={"testimony": "authority"}
    )

    def __post_init__(self) -> None:
        if self._authority is not _IMPORT_AUTHORITY:
            raise ValueError(
                "AuthenticatedImportUseV1 was not minted by the lexical pass"
            )
        if blake3_512_of(self.source.encode("utf-8")) != self.source_cid:
            raise ValueError("authenticated import-use source CID is stale")
        if self.use.get("kind") != "authenticated-import-use":
            raise ValueError("authenticated import use has the wrong kind")
        use_without_cid = {
            key: value for key, value in self.use.items() if key != "cid"
        }
        if self.use.get("cid") != _hash(use_without_cid):
            raise ValueError("authenticated import-use CID does not match its preimage")
        if self.use.get("importBindingCid") != self.import_binding.cid:
            raise ValueError("authenticated import use cites another binding")
        for key, value in (
            ("authenticatedImportUse", self.use),
            ("importBinding", self.import_binding.to_value()),
            ("targetSymbol", self.target_symbol),
            ("importBindingCid", self.import_binding.cid),
        ):
            if self.demand.get(key) != value:
                raise ValueError(f"authenticated demand has stale {key}")
        # Closed kind admission: exactly two surfaces.  Unknown kinds and
        # cross-surface relabeling refuse at mint — not by observing output sets.
        demand_kind = self.demand.get("kind")
        if demand_kind not in _ADMITTED_IMPORT_DEMAND_KINDS:
            raise ValueError(
                f"authenticated import demand has unadmitted kind {demand_kind!r}"
            )
        if demand_kind == "import-value-use-demand":
            _require_value_use_role(self)
        else:
            # call-contract-demand — closed call shape only.
            _require_call_contract_demand(self)

    @cached_property
    def preimage(self) -> dict[str, Any]:
        """The authenticated demand row: this receipt's complete content.

        ``__post_init__`` checks the row carries this receipt's use (with its
        own CID), binding, binding CID and target symbol; the use site carries
        the consumer source CID.  ``root``/``path``/``source`` and
        ``module_identities`` are where resolution LOOKS, not what this use
        is.  So the row's CID authenticates the receipt's content, and a
        constructed value seating the receipt (an import member read) cites it
        by that validated native CID instead of walking file-system paths.
        """
        return json.loads(encode_jcs(_json_value(self.demand)))

    @cached_property
    def cid(self) -> str:
        return _hash(self.demand)

    def revalidate(self) -> None:
        """Demand byte identity against one shared #6090 snapshot per module.

        Full-module lexical recompute is amortized: many receipts from one
        consumer module share one lexical pass.  Byte identity is unchanged —
        only recompute frequency (see
        docs/audits/pandas-recensus-latency-bisect.md).

        Call-target and value-use demands revalidate against their own
        row/outcome surfaces so Call receipts stay unchanged and neither
        surface can authorize the other.

        Ask once per content, not once per path: the same authenticated use
        face (``use["cid"]``) is revalidated at every seating / resolve /
        roster retain door.  Measured cold open of
        ``pandas/tests/io/json/test_pandas.py``: 1011 revalidate calls over
        only 75 unique use CIDs (max 67× one face).  The answer cannot change
        for a given content address; memo success so later doors free.
        """
        use_cid = self.use.get("cid")
        if use_cid is not None and use_cid in _REVALIDATED_USE_CIDS:
            return
        site = self.use["useSite"]
        key = (
            site["startLine"],
            site["startCol"],
            site["endLine"],
            site["endCol"],
        )
        if self.demand.get("kind") == "import-value-use-demand":
            snapshot = _lexical_value_revalidation_snapshot(
                self.root,
                self.path,
                self.source,
                self.source_cid,
                self.module_identities,
            )
            expected = "authenticated-import-value-use"
        else:
            snapshot = _lexical_revalidation_snapshot(
                self.root,
                self.path,
                self.source,
                self.source_cid,
                self.module_identities,
            )
            expected = "authenticated-import-use"
        if snapshot.outcome_at(key) != expected or not (
            snapshot.contains_row(self.demand)
        ):
            raise ValueError(
                "authenticated import use is not byte-identical to lexical revalidation"
            )
        if use_cid is not None:
            _REVALIDATED_USE_CIDS.add(use_cid)


def _authenticated_binding_target_symbol(binding: ImportBindingV1) -> str:
    """Closed target coordinate of an authenticated import binding.

    Recovered only from the binding preimage (module identity + binding
    exportedPath) — never from the receipt's targetSymbol string.
    """
    value = binding.to_value()
    if value.get("kind") != "python-import-binding":
        raise ValueError("authenticated import binding has the wrong kind")
    target = value.get("target")
    if not isinstance(target, dict):
        raise ValueError("authenticated import binding target is missing")
    identity = target.get("moduleIdentity")
    if not isinstance(identity, dict):
        raise ValueError("authenticated import binding module identity is missing")
    kind = identity.get("kind")
    if kind == "unavailable-python-module":
        module_name = identity.get("name")
    elif kind == "authenticated-python-module":
        module_name = identity.get("moduleName")
    else:
        raise ValueError(
            "authenticated import binding module identity kind is unsupported"
        )
    if not isinstance(module_name, str) or not module_name:
        raise ValueError("authenticated import binding module name is invalid")
    path = target.get("exportedPath")
    if not isinstance(path, list) or any(
        not isinstance(part, str) or not part for part in path
    ):
        raise ValueError("authenticated import binding exportedPath is invalid")
    return "python:" + module_name + "".join(f".{part}" for part in path)


def _require_call_contract_demand(receipt: AuthenticatedImportUseV1) -> None:
    """Final-check a call-target demand: closed shape, no value-use fields."""
    use = receipt.use
    demand = receipt.demand
    if use.get("role") == "value-use" or demand.get("role") == "value-use":
        raise ValueError("call-contract-demand cannot carry value-use role")
    if "role" in use or "role" in demand:
        raise ValueError("call-contract-demand cannot carry a use role")
    if "exportedMemberPath" in use or "exportedMemberPath" in demand:
        raise ValueError("call-contract-demand cannot carry exportedMemberPath")
    if "sourceCid" in use:
        raise ValueError("call-contract-demand use cannot carry sourceCid")
    if demand.get("importSignature") is None:
        raise ValueError("call-contract-demand requires importSignature")


def _require_value_use_role(receipt: AuthenticatedImportUseV1) -> None:
    """Final-check the value-use role and its bound identity fields.

    A value-use receipt authenticates together: exact source occurrence,
    import binding CID, exported member path, consumer source CID, and the
    value-use role.  ``targetSymbol`` must equal the authenticated binding
    target composed with structural ``exportedMemberPath`` exactly — suffix
    checks are not enough (a forged head can endswith the same path).
    """
    use = receipt.use
    demand = receipt.demand
    if use.get("role") != "value-use" or demand.get("role") != "value-use":
        raise ValueError("import-value-use-demand requires value-use role")
    if "importSignature" in demand:
        raise ValueError("import-value-use-demand cannot carry importSignature")
    if use.get("sourceCid") != receipt.source_cid:
        raise ValueError("authenticated import value-use sourceCid is stale")
    if demand.get("sourceCid") != receipt.source_cid:
        raise ValueError("authenticated import value-use demand sourceCid is stale")
    site = use.get("useSite")
    if not isinstance(site, dict) or site.get("sourceCid") != receipt.source_cid:
        raise ValueError("authenticated import value-use site sourceCid is stale")
    if demand.get("useSite") != site:
        raise ValueError("authenticated import value-use demand has stale useSite")
    exported = use.get("exportedMemberPath")
    if not isinstance(exported, list) or any(
        not isinstance(part, str) or not part for part in exported
    ):
        raise ValueError("authenticated import value-use exportedMemberPath is invalid")
    if demand.get("exportedMemberPath") != exported:
        raise ValueError(
            "authenticated import value-use demand has stale exportedMemberPath"
        )
    binding = receipt.import_binding.to_value()
    if binding.get("sourceCid") != receipt.source_cid:
        raise ValueError("authenticated import value-use binding sourceCid is stale")
    if use.get("importBindingCid") != receipt.import_binding.cid:
        raise ValueError("authenticated import value-use cites another binding")
    # Exact composition: binding target (from binding preimage only) + structural
    # Attribute segments.  endswith(exportedMemberPath) is not authentication.
    binding_target = _authenticated_binding_target_symbol(receipt.import_binding)
    expected = binding_target + "".join(f".{part}" for part in exported)
    if receipt.target_symbol != expected:
        raise ValueError(
            "authenticated import value-use targetSymbol disagrees with "
            "binding target and exportedMemberPath"
        )


def _member_path_after_submodule(
    binding: _ImportDef, exported_path: tuple[str, ...]
) -> tuple[str, ...] | None:
    """The member path relative to the binding's module, or ``None``.

    ``import a.b`` binds ``a``; ``a.b.x`` is ``x`` of ``a.b`` and ``a.y`` is
    not a member of ``a.b`` at all, so it is not this binding's use.
    """
    tail = binding.submodule_tail
    if not tail:
        return exported_path
    if exported_path[: len(tail)] != tail:
        return None
    return exported_path[len(tail) :]


def member_target_symbol(target_symbol: str, member: tuple[str, ...]) -> str:
    """The one speller of an import-bound reference's target (#7837): the
    binding's target followed by the static member path read off the
    reference."""
    return target_symbol + "".join(f".{part}" for part in member)


def _target_symbol(binding: _ImportDef, member: tuple[str, ...]) -> str:
    return member_target_symbol(binding.target_symbol, member)


_NON_IMPORT = "non-import"
_UNBOUND = "unbound"
# The unbound face of a closed try-import provider gate: the name is unbound
# because the provider's import failed into an ``except ImportError`` handler.
_PROVIDER_ABSENT = "provider-absent"
Definition = _ImportDef | _ModuleFunctionDef | str
State = dict[str, frozenset[Definition]]


def _join(*states: State) -> State:
    names = set().union(*(state for state in states))
    return {
        name: frozenset().union(
            *(state.get(name, frozenset({_UNBOUND})) for state in states)
        )
        for name in names
    }


def _bound_names(target: Node) -> set[str]:
    if target.kind == "Name":
        return {target.id}
    if target.kind in ("Tuple", "List"):
        return set().union(*(_bound_names(item) for item in target.elts), set())
    if target.kind == "Starred":
        return _bound_names(target.value)
    return set()


def module_name_for_path(root: Path, path: Path) -> str:
    """The module name an import of ``path`` spells: the one speller of it.

    The path under ``root``, without ``.py`` and a package's ``__init__``. A
    src layout (``root/src/<package>/...`` with no ``root/src/__init__.py``)
    is imported from inside ``src``: the distribution installs ``<package>``,
    never ``src``, so a consumer's ``from <package> import <name>`` and the
    defining module's own symbols name the same module (#7757).
    """
    parts = list(path.relative_to(root).with_suffix("").parts)
    if (
        len(parts) > 1
        and parts[0] == "src"
        and not (Path(root) / "src" / "__init__.py").exists()
    ):
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_from_module(
    current: str, node: Node, *, current_is_package: bool
) -> str | None:
    if node.level == 0:
        return node.module
    package = current.split(".")
    # A non-package module's package excludes its final component.  An
    # authenticated ``__init__.py`` already names the package itself.
    if package and not current_is_package:
        package.pop()
    ascend = node.level - 1
    if ascend > len(package):
        return None
    base = package[: len(package) - ascend]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base) or None


def _unique_import_def_from_state(
    state: "State | None", local_name: str
) -> "_ImportDef | None":
    """The sole import definition reaching ``local_name``, or None."""
    if state is None:
        return None
    reaching = state.get(local_name, frozenset({_UNBOUND}))
    imports = {value for value in reaching if isinstance(value, _ImportDef)}
    if len(imports) != 1:
        return None
    rest = reaching - imports
    if rest:
        return None
    return next(iter(imports))


def _importorskip_module(value: Node | None, state: "State | None") -> str | None:
    """Module name of authenticated ``pytest.importorskip("mod")``.

    Head must be a reaching import binding — ``python:pytest.importorskip``
    for a bare name, or ``python:pytest`` for an attribute head whose member
    path is ``importorskip``. Unbound lexical text (``func.id ==
    "importorskip"``, ``func.value.id == "pytest"``) never mints a module
    availability fact: the analyzer's own ``state`` is the authority.
    """
    if value is None or value.kind != "Call":
        return None
    if value.keywords or any(arg.kind == "Starred" for arg in value.args):
        return None
    if len(value.args) != 1 or value.args[0].kind != "Constant":
        return None
    module = value.args[0].value
    if not isinstance(module, str) or not module:
        return None
    from sugar_source_tree.nodes import LanguageCallee

    func = value.func
    if func.kind == "Name":
        binding = _unique_import_def_from_state(state, func.id)
        target = None if binding is None else binding.target_symbol
    elif func.kind == "Attribute" and func.value.kind == "Name":
        binding = _unique_import_def_from_state(state, func.value.id)
        target = (
            None
            if binding is None
            else member_target_symbol(binding.target_symbol, (func.attr,))
        )
    else:
        return None
    if LanguageCallee.of(target) is LanguageCallee.PYTEST_IMPORTORSKIP:
        return module
    return None


class _Pass:
    def __init__(
        self,
        *,
        source_cid: str,
        module_name: str,
        module_is_package: bool,
        module_identities: dict[str, dict[str, Any]],
        module_state: State | None = None,
        analyze_nested: bool = True,
    ):
        self.source_cid = source_cid
        self.module_name = module_name
        self.module_is_package = module_is_package
        self.module_identities = module_identities
        self.rows: list[dict[str, Any]] = []
        self.outcomes: dict[tuple[int, int, int, int], str] = {}
        # Value-occurrence rows (Name / Attribute loads), separate from Call.
        self.value_rows: list[dict[str, Any]] = []
        self.value_outcomes: dict[tuple[int, int, int, int], str] = {}
        # THE import reference table (#7837): the target symbol of every
        # import-bound reference -- a Name, or a ``Name.attr...`` chain whose
        # head is import-bound -- keyed by that reference's own coordinate.
        # One law (the strict one calls and value uses follow). Every reader
        # (calls of any callee shape, value reads, the exception
        # authenticator, ``typing.cast``, ``importorskip``) looks here.  A row
        # carries its binding's provider-gate fact (``ImportReference``).
        self.reference_targets: dict[tuple[int, int, int, int], ImportReference] = {}
        # The same table's row for each binding an import statement makes,
        # keyed by ``(statement coordinate, local name)``: what the module
        # threading binds the name to (``SourceUnit.import_binding_reference``).
        # A binding whose local names nothing the table rows (``import a.b``
        # binds the package ``a``) has none.
        self.binding_targets: dict[
            tuple[int, int, int, int, str], ImportReference
        ] = {}
        self.module_state = module_state or {}
        self.analyze_nested = analyze_nested
        self.class_outer_states: dict[int, State] = {}

    def module_import_target(self, name: str) -> str | None:
        """The target symbol an import binds the module-level ``name`` to at
        the module's end (#7757), or ``None`` when anything else reaches it
        there (a rebinding, an unbound path, a provider gate, a submodule
        chain). The table's binding, read where no reference uses it: a
        package's re-export (``from .errors import E`` in ``__init__``)."""
        binding = _unique_import_def_from_state(self.module_state, name)
        if (
            binding is None
            or binding.submodule_tail
            or binding.provider_gate is not None
        ):
            return None
        return binding.target_symbol

    def _state_only_statement(
        self, node: Statement, state: State, scope: Node
    ) -> State:
        """Transfer one statement without enrolling any use-site testimony."""
        transfer = _Pass(
            source_cid=self.source_cid,
            module_name=self.module_name,
            module_is_package=self.module_is_package,
            module_identities=self.module_identities,
            module_state=self.module_state,
            analyze_nested=False,
        )
        return transfer.statement(node, state, scope)

    def _loop_entry(
        self,
        node: Statement,
        state: State,
        scope: Node,
    ) -> State:
        """Least fixed point for definitions that can arrive on a back-edge."""
        entry = dict(state)
        while True:
            body_in = dict(entry)
            if hasattr(node, "target"):
                for name in _bound_names(node.target):
                    body_in[name] = frozenset({_NON_IMPORT})
            body_out = body_in
            for statement in node.body:
                body_out = self._state_only_statement(statement, body_out, scope)
            widened = _join(state, body_out)
            if widened == entry:
                return entry
            entry = widened

    def expression(self, node: Node | None, state: State, scope: Node) -> None:
        if node is None:
            return
        if node.kind == "Name":
            # A name USE whose sole reaching definition is an import statement
            # is lexically bound to that import's target coordinate. One law:
            # unique ImportDef only -- shadowing, reassignment, an unbound join
            # and wildcard ambiguity bind nothing.  A closed try-import gate
            # (the import, or unbound because the provider is absent) records
            # its row with that gate fact and enrolls no value use.
            value_binding = self._unique_import_def(node.id, state, allow_unbound=False)
            if value_binding is not None and not value_binding.submodule_tail:
                self._record_reference(node, value_binding, ())
                self._enroll_value_use(node, value_binding, ())
                return
            gated = self._try_import_gated_def(node.id, state)
            if gated is not None and not gated.submodule_tail:
                self._record_reference(node, gated, ())
            return
        if node.kind == "Attribute":
            # Value occurrence of ``head.attr...`` when head is uniquely
            # import-bound.  Recurse first so each chained Attribute keeps its
            # own exact coordinate; exportedMemberPath is structural Attribute
            # segments only — never spelling resolution or first-candidate.
            self.expression(node.value, state, scope)
            path = self._attribute_export_path(node)
            if path is not None:
                local_name, exported_path = path
                binding = self._unique_import_def(
                    local_name, state, allow_unbound=False
                )
                gated = (
                    self._try_import_gated_def(local_name, state)
                    if binding is None
                    else None
                )
                member = (
                    _member_path_after_submodule(binding or gated, exported_path)
                    if (binding or gated) is not None
                    else None
                )
                if member is not None:
                    self._record_reference(node, binding or gated, member)
                    if binding is not None:
                        self._enroll_value_use(node, binding, member)
            return
        if node.kind == "Call":
            self.expression(node.func, state, scope)
            for arg in node.args:
                self.expression(arg, state, scope)
            for keyword in node.keywords:
                self.expression(keyword.value, state, scope)
            if (
                node.func.kind in ("Name", "Attribute")
                and (node.func.kind == "Attribute" or not node.keywords)
                and not any(arg.kind == "Starred" for arg in node.args)
                and not any(keyword.arg is None for keyword in node.keywords)
            ):
                self._call(node, state, scope)
            return
        if node.kind == "Lambda":
            inner = dict(state)
            for param in node.params:
                inner[param.name] = frozenset({_NON_IMPORT})
            self.expression(node.body, inner, node)
            return
        if node.kind in ("ListComp", "SetComp", "GeneratorExp", "DictComp"):
            inner = dict(state)
            for generator in node.generators:
                self.expression(generator.iter, inner, scope)
                for name in _bound_names(generator.target):
                    inner[name] = frozenset({_NON_IMPORT})
                for condition in generator.ifs:
                    self.expression(condition, inner, scope)
            if node.kind == "DictComp":
                self.expression(node.key, inner, scope)
                self.expression(node.value, inner, scope)
            else:
                self.expression(node.elt, inner, scope)
            return
        for _, _, child in node.children():
            if isinstance(child, Expression):
                self.expression(child, state, scope)

    def _unique_import_def(
        self, local_name: str, state: State, *, allow_unbound: bool
    ) -> _ImportDef | None:
        reaching = state.get(local_name, frozenset({_UNBOUND}))
        imports = {value for value in reaching if isinstance(value, _ImportDef)}
        if len(imports) != 1:
            return None
        rest = reaching - imports
        if allow_unbound:
            rest = rest - {_UNBOUND}
        if rest:
            return None
        return next(iter(imports))

    @staticmethod
    def _try_import_gated_def(local_name: str, state: State) -> _ImportDef | None:
        """The try-import gated definition reaching ``local_name``, or None:
        exactly that import, or unbound because its provider is absent."""
        reaching = state.get(local_name, frozenset({_UNBOUND}))
        if _PROVIDER_ABSENT not in reaching or len(reaching) != 2:
            return None
        (definition,) = reaching - {_PROVIDER_ABSENT}
        if (
            not isinstance(definition, _ImportDef)
            or definition.provider_gate != PROVIDER_GATE_TRY_IMPORT
        ):
            return None
        return definition

    @staticmethod
    def _catches_import_error(handler: Node, state: State) -> bool:
        """Whether ``handler`` catches the language's ``ImportError`` (or
        ``ModuleNotFoundError``), alone or in a tuple, read as builtins: a
        name this pass sees bound is not the builtin."""

        def builtin_import_error(node: Node) -> bool:
            return (
                node.kind == "Name"
                and node.id in ("ImportError", "ModuleNotFoundError")
                and state.get(node.id, frozenset({_UNBOUND}))
                == frozenset({_UNBOUND})
            )

        type_node = handler.type_
        if type_node is None:
            return False
        if type_node.kind == "Tuple":
            return any(builtin_import_error(item) for item in type_node.elts)
        return builtin_import_error(type_node)

    def _provider_gate(
        self, node: Statement, before: State, body_out: State, joined: State
    ) -> State:
        """Record the closed optional-provider gate ``try: import m`` (or
        ``try: from m import X``) / ``except ImportError`` in ``joined``.

        A name an ``import`` or ``from ... import`` statement in the try body binds, unbound before
        the ``try``, whose every handler catches ``ImportError`` and leaves
        the name as it found it: after the handlers join, it reaches as that
        import or as unbound because the provider is absent.  That unbound
        face is recorded as ``_PROVIDER_ABSENT`` and the import carries the
        ``PROVIDER_GATE_TRY_IMPORT`` fact, so its references have rows in the
        one table that say so.  Any other shape keeps the plain join.
        """
        if not node.handlers or not all(
            self._catches_import_error(handler, before) for handler in node.handlers
        ):
            return joined
        gated = dict(joined)
        for statement in node.body:
            if statement.kind not in ("Import", "ImportFrom"):
                continue
            for alias in statement.names:
                if alias.name == "*":
                    continue
                local = alias.asname or (
                    alias.name.split(".")[0]
                    if statement.kind == "Import"
                    else alias.name
                )
                if before.get(local, frozenset({_UNBOUND})) != frozenset({_UNBOUND}):
                    continue
                bound = body_out.get(local, frozenset())
                if len(bound) != 1:
                    continue
                (definition,) = bound
                if not isinstance(definition, _ImportDef):
                    continue
                if joined.get(local) != frozenset({definition, _UNBOUND}):
                    continue
                gated[local] = frozenset(
                    {
                        replace(definition, provider_gate=PROVIDER_GATE_TRY_IMPORT),
                        _PROVIDER_ABSENT,
                    }
                )
        return gated

    @staticmethod
    def _attribute_export_path(
        node: Node,
    ) -> tuple[str, tuple[str, ...]] | None:
        """``(local_name, exported_path)`` for an Attribute chain to a Name."""
        attrs: list[str] = []
        link = node
        while link.kind == "Attribute":
            attrs.append(link.attr)
            link = link.value
        if link.kind != "Name":
            return None
        return link.id, tuple(reversed(attrs))

    def _record_binding(self, node: Node, local: str, binding: _ImportDef) -> None:
        """The row of the binding import statement ``node`` makes of
        ``local``: the import's own target, as a reference to ``local``
        right after the statement reads it.  ``import a.b`` binds the
        package ``a``, which this binding does not name: no row."""
        if binding.submodule_tail:
            return
        span = node.line_col_span()
        self.binding_targets[
            (span.start_line, span.start_col, span.end_line, span.end_col, local)
        ] = ImportReference(_target_symbol(binding, ()))

    def _record_reference(
        self, node: Node, binding: _ImportDef, member: tuple[str, ...]
    ) -> None:
        span = node.line_col_span()
        self.reference_targets[
            (span.start_line, span.start_col, span.end_line, span.end_col)
        ] = ImportReference(_target_symbol(binding, member), binding.provider_gate)

    def _enroll_value_use(
        self,
        node: Node,
        binding: _ImportDef,
        exported_path: tuple[str, ...],
    ) -> None:
        """Final-checked value-occurrence row at the exact Name/Attribute site.

        Authenticates together: exact occurrence (useSite), import binding,
        structural exported member path, consumer sourceCid, and value-use role.
        Call-target enrollment is a separate row surface; sets stay disjoint.
        """
        span = node.line_col_span()
        key = (span.start_line, span.start_col, span.end_line, span.end_col)
        self.value_outcomes[key] = "authenticated-import-value-use"
        use_site = _site(self.source_cid, node)
        member_path = list(exported_path)
        use = {
            "kind": "authenticated-import-use",
            "schemaVersion": "1",
            "role": "value-use",
            "sourceCid": self.source_cid,
            "useSite": use_site,
            "importBindingCid": binding.cid,
            "exportedMemberPath": member_path,
        }
        self.value_rows.append(
            {
                "schemaVersion": "1",
                "kind": "import-value-use-demand",
                "role": "value-use",
                "sourceCid": self.source_cid,
                "authenticatedImportUse": {**use, "cid": _hash(use)},
                "importBinding": json.loads(binding.payload_jcs),
                "targetSymbol": _target_symbol(binding, exported_path),
                "exportedMemberPath": member_path,
                "importBindingCid": binding.cid,
                "useSite": use_site,
            }
        )

    def _call(self, node: Node, state: State, scope: Node) -> None:
        if node.func.kind == "Name":
            local_name = node.func.id
            exported_path: tuple[str, ...] = ()
        elif node.func.kind == "Attribute":
            path = self._attribute_export_path(node.func)
            if path is None:
                return
            local_name, exported_path = path
        else:
            return
        reaching = state.get(local_name, frozenset({_UNBOUND}))
        imports = {value for value in reaching if isinstance(value, _ImportDef)}
        nonimports = reaching - imports
        span = node.line_col_span()
        key = (span.start_line, span.start_col, span.end_line, span.end_col)
        if len(imports) == 1 and not nonimports:
            binding = next(iter(imports))
            member = _member_path_after_submodule(binding, exported_path)
            if member is None:
                return
            exported_path = member
            self.outcomes[key] = "authenticated-import-use"
            use_site = _site(self.source_cid, node)
            use = {
                "kind": "authenticated-import-use",
                "schemaVersion": "1",
                "useSite": use_site,
                "importBindingCid": binding.cid,
            }
            self.rows.append(
                {
                    "schemaVersion": "1",
                    "kind": "call-contract-demand",
                    "authenticatedImportUse": {**use, "cid": _hash(use)},
                    "importBinding": json.loads(binding.payload_jcs),
                    "targetSymbol": _target_symbol(binding, exported_path),
                    "importBindingCid": binding.cid,
                    "importSignature": {
                        "formals": [],
                        "sorts": [
                            {"kind": "primitive", "name": "Value"} for _ in node.args
                        ],
                    },
                    "useSite": use_site,
                }
            )
        elif imports:
            self.outcomes[key] = "ambiguous-lexical-binding"
        elif reaching == frozenset({_NON_IMPORT}):
            self.outcomes[key] = "shadowed-non-import"
        else:
            self.outcomes[key] = "no-lexical-binding"

    def statements(
        self, statements: Iterable[Statement], state: State, scope: Node
    ) -> State:
        state = dict(state)
        for statement in statements:
            state = self.statement(statement, state, scope)
        return state

    def statement(self, node: Statement, state: State, scope: Node) -> State:
        state = dict(state)
        if node.kind == "ImportFrom":
            module = _import_from_module(
                self.module_name,
                node,
                current_is_package=self.module_is_package,
            )
            if module is None:
                return state
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                payload = {
                    "kind": "python-import-binding",
                    "schemaVersion": "1",
                    "sourceCid": self.source_cid,
                    "scope": _site(self.source_cid, scope),
                    "definitionSite": _site(self.source_cid, node),
                    "localSlot": local,
                    "target": {
                        "moduleIdentity": self.module_identities.get(
                            module,
                            {
                                "kind": "unavailable-python-module",
                                "name": module,
                            },
                        ),
                        "exportedPath": [alias.name],
                    },
                }
                definition = _ImportDef(
                    _hash(payload),
                    f"python:{module}.{alias.name}",
                    encode_jcs(_json_value(payload)),
                )
                self._record_binding(node, local, definition)
                state[local] = frozenset({definition})
            return state
        if node.kind == "Import":
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                payload = {
                    "kind": "python-import-binding",
                    "schemaVersion": "1",
                    "sourceCid": self.source_cid,
                    "scope": _site(self.source_cid, scope),
                    "definitionSite": _site(self.source_cid, node),
                    "localSlot": local,
                    "target": {
                        "moduleIdentity": self.module_identities.get(
                            alias.name,
                            {
                                "kind": "unavailable-python-module",
                                "name": alias.name,
                            },
                        ),
                        "exportedPath": [],
                    },
                }
                definition = _ImportDef(
                    _hash(payload),
                    f"python:{alias.name}",
                    encode_jcs(_json_value(payload)),
                    () if alias.asname else tuple(alias.name.split(".")[1:]),
                )
                self._record_binding(node, local, definition)
                state[local] = frozenset({definition})
            return state
        if node.kind in ("FunctionDef", "AsyncFunctionDef"):
            for deco in node.decorators:
                self.expression(deco, state, scope)
            for default in (
                *(p.default for p in node.params if p.default is not None),
            ):
                self.expression(default, state, scope)
            if scope.kind == "Module":
                state[node.name] = frozenset(
                    {
                        _ModuleFunctionDef(
                            f"python:{self.module_name}.{node.name}",
                            (
                                node.line_col_span().start_line,
                                node.line_col_span().start_col,
                                node.line_col_span().end_line,
                                node.line_col_span().end_col,
                            ),
                        )
                    }
                )
            else:
                state[node.name] = frozenset({_NON_IMPORT})
            if not self.analyze_nested:
                return state
            inner = dict(
                self.class_outer_states.get(id(scope), state)
                if scope.kind == "ClassDef"
                else state
            )
            # One tree visit: locals + global/nonlocal declarations.
            # Previously _function_locals and _function_declarations each did a
            # full recursive children() walk of the same immutable body.
            local_names, globals_, _nonlocals = _function_scope_bindings(node)
            for name in local_names:
                inner[name] = frozenset({_UNBOUND})
            for param in node.params:
                inner[param.name] = frozenset({_NON_IMPORT})
            for name in globals_:
                inner[name] = self.module_state.get(name, frozenset({_UNBOUND}))
            self.statements(node.body, inner, node)
            return state
        if node.kind == "ClassDef":
            for expr in (*node.decorators, *node.bases):
                self.expression(expr, state, scope)
            state[node.name] = frozenset({_NON_IMPORT})
            if not self.analyze_nested:
                return state
            self.class_outer_states[id(node)] = dict(state)
            self.statements(node.body, dict(state), node)
            return state
        if node.kind in ("Assign", "AnnAssign", "AugAssign", "NamedExpr"):
            value = getattr(node, "value", None)
            self.expression(value, state, scope)
            targets = node.targets if node.kind == "Assign" else [node.target]
            importorskip = (
                _importorskip_module(value, state)
                if node.kind == "Assign" and len(targets) == 1
                else None
            )
            for target in targets:
                names = _bound_names(target)
                if (
                    importorskip is not None
                    and len(names) == 1
                    and target.kind == "Name"
                ):
                    local = next(iter(names))
                    module = importorskip
                    payload = {
                        "kind": "python-import-binding",
                        "schemaVersion": "1",
                        "sourceCid": self.source_cid,
                        "scope": _site(self.source_cid, scope),
                        "definitionSite": _site(self.source_cid, node),
                        "localSlot": local,
                        "target": {
                            "moduleIdentity": self.module_identities.get(
                                module,
                                {
                                    "kind": "unavailable-python-module",
                                    "name": module,
                                },
                            ),
                            "exportedPath": [],
                        },
                    }
                    state[local] = frozenset(
                        {
                            _ImportDef(
                                _hash(payload),
                                f"python:{module}",
                                encode_jcs(_json_value(payload)),
                                provider_gate=PROVIDER_GATE_IMPORTORSKIP,
                            )
                        }
                    )
                    continue
                for name in names:
                    state[name] = frozenset({_NON_IMPORT})
            return state
        if node.kind == "If":
            self.expression(node.test, state, scope)
            return _join(
                self.statements(node.body, state, scope),
                self.statements(node.orelse, state, scope),
            )
        if node.kind in ("For", "AsyncFor", "While"):
            self.expression(getattr(node, "iter", None), state, scope)
            body_in = self._loop_entry(node, state, scope)
            self.expression(getattr(node, "test", None), body_in, scope)
            if hasattr(node, "target"):
                for name in _bound_names(node.target):
                    body_in[name] = frozenset({_NON_IMPORT})
            body = self.statements(node.body, body_in, scope)
            return _join(
                state,
                body,
                self.statements(node.orelse, _join(state, body), scope),
            )
        if node.kind in ("Try", "TryStar"):
            exceptional_prefixes = [dict(state)]
            prefix = dict(state)
            for statement in node.body:
                prefix = self._state_only_statement(statement, prefix, scope)
                exceptional_prefixes.append(prefix)
            handler_entry = _join(*exceptional_prefixes)
            paths = [self.statements(node.body, state, scope)]
            for handler in node.handlers:
                # The except-TYPE expression is a value use on the exceptional
                # path (``except re.error`` reads the import-bound ``re``); it
                # must be enrolled so a dotted handler type can later
                # authenticate its import identity, exactly as a With
                # context_expr is enrolled below.
                if handler.type_ is not None:
                    self.expression(handler.type_, handler_entry, scope)
                handler_state = dict(handler_entry)
                if handler.name:
                    handler_state[handler.name] = frozenset({_NON_IMPORT})
                paths.append(self.statements(handler.body, handler_state, scope))
            joined = self._provider_gate(node, state, paths[0], _join(*paths))
            joined = self.statements(node.orelse, joined, scope)
            return self.statements(node.finalbody, joined, scope)
        if node.kind in ("With", "AsyncWith"):
            for item in node.items:
                self.expression(item.context_expr, state, scope)
                if item.optional_vars:
                    for name in _bound_names(item.optional_vars):
                        state[name] = frozenset({_NON_IMPORT})
            return self.statements(node.body, state, scope)
        if node.kind == "Delete":
            for target in node.targets:
                for name in _bound_names(target):
                    state[name] = frozenset({_UNBOUND})
            return state
        if node.kind in TYPED_STATEMENT_KINDS:
            for _, _, child in node.children():
                if isinstance(child, Expression):
                    self.expression(child, state, scope)
            return state
        raise UnsupportedStatementVariant(type(node).__name__)


def _function_scope_bindings(
    node: Node,
) -> tuple[set[str], set[str], set[str]]:
    """One visit: local bindings, global names, nonlocal names.

    Nested scopes are barriers.  Binding sites are read from their typed roles;
    identifier spelling is never treated as evidence that a read is a store.

    Replaces the old dual walk (``_function_locals`` + ``_function_declarations``)
    that each did a full recursive ``children()`` pass over the same immutable body.
    """
    globals_: set[str] = set()
    nonlocals: set[str] = set()
    names: set[str] = set()

    def visit(child: Node, *, root: bool = False) -> None:
        if child.kind in ("FunctionDef", "AsyncFunctionDef"):
            if not root:
                names.add(child.name)
                return
        elif child.kind == "ClassDef":
            names.add(child.name)
            return
        elif child.kind == "Lambda":
            return
        if child.kind == "Global":
            globals_.update(child.names)
        elif child.kind == "Nonlocal":
            nonlocals.update(child.names)
        elif child.kind in ("Import", "ImportFrom"):
            names.update(
                alias.asname or alias.name.split(".")[0] for alias in child.names
            )
        elif child.kind == "ExceptHandler" and child.name:
            names.add(child.name)
        elif child.kind == "Assign":
            for target in child.targets:
                names.update(_bound_names(target))
        elif child.kind in ("AnnAssign", "AugAssign", "NamedExpr"):
            names.update(_bound_names(child.target))
        elif child.kind in ("For", "AsyncFor"):
            names.update(_bound_names(child.target))
        elif child.kind in ("With", "AsyncWith"):
            for item in child.items:
                if item.optional_vars is not None:
                    names.update(_bound_names(item.optional_vars))
        elif child.kind == "Delete":
            for target in child.targets:
                names.update(_bound_names(target))
        for _, _, descendant in child.children():
            visit(descendant)

    visit(node, root=True)
    locals_ = names - globals_ - nonlocals
    return locals_, globals_, nonlocals


def _function_locals(node: Node) -> set[str]:
    """Local names only — thin projection of the single scope walk."""
    locals_, _globals, _nonlocals = _function_scope_bindings(node)
    return locals_


def _function_declarations(node: Node) -> tuple[set[str], set[str]]:
    """Global/nonlocal declarations — thin projection of the single scope walk."""
    _locals, globals_, nonlocals = _function_scope_bindings(node)
    return globals_, nonlocals


def _final_module_state(
    *,
    module: Module,
    source_cid: str,
    module_name: str,
    module_is_package: bool,
    module_identities: dict[str, dict[str, Any]],
) -> State:
    prepass = _Pass(
        source_cid=source_cid,
        module_name=module_name,
        module_is_package=module_is_package,
        module_identities=module_identities,
        analyze_nested=False,
    )
    return prepass.statements(module.body, {}, module)


@dataclass(frozen=True, eq=False)
class _LexicalRevalidationSnapshotV1:
    """The served revalidation value: content-addressed and unwritable.

    #6273: the cache key was already complete (consumer ``source_cid`` plus a
    hash of ``module_identities``), so the residual was the value.  A shared
    ``(list, dict)`` pair handed out by reference lets one consumer's write
    corrupt every later hit at that key.  Both faces are closed here: rows are
    served as a ``frozenset`` of row CIDs (membership is the only question the
    consumer asks) and outcomes as a read-only view over the pass's map.
    Every write path raises; see
    ``tests/test_revalidation_snapshot_immutability.py``.
    """

    row_cids: frozenset[str]
    outcomes: Mapping[tuple[int, int, int, int], str]

    @staticmethod
    def row_cid(row: dict[str, Any]) -> str:
        return _hash(row)

    def contains_row(self, row: dict[str, Any]) -> bool:
        """Byte identity against the pass's rows, by content address."""
        return _hash(row) in self.row_cids

    def outcome_at(self, site: tuple[int, int, int, int]) -> str | None:
        return self.outcomes.get(site)


# Shared #6090 snapshot for revalidation only.  Keyed by consumer module
# content + identities map so many receipts share one full-module pass.
# See docs/audits/pandas-recensus-latency-bisect.md.
_REVALIDATION_SNAPSHOTS: dict[
    tuple[str, str, str, str], _LexicalRevalidationSnapshotV1
] = {}
_VALUE_REVALIDATION_SNAPSHOTS: dict[
    tuple[str, str, str, str], _LexicalRevalidationSnapshotV1
] = {}
# Content-addressed "this use face already passed revalidate".  Process-global
# is legitimate: the key is the use CID (complete preimage of the face), and
# the value is pure success — never a live context.  Cleared with snapshots.
_REVALIDATED_USE_CIDS: set[str] = set()


def clear_lexical_revalidation_snapshots() -> None:
    """Drop amortized revalidation snapshots (tests / hermetic process reuse)."""
    _REVALIDATION_SNAPSHOTS.clear()
    _VALUE_REVALIDATION_SNAPSHOTS.clear()
    _REVALIDATED_USE_CIDS.clear()


def _revalidation_cache_key(
    root: Path,
    path: Path,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]],
) -> tuple[str, str, str, str]:
    return (
        str(root.resolve()),
        str(path.resolve()),
        source_cid,
        _hash(module_identities),
    )


def _lexical_revalidation_snapshot(
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]],
) -> _LexicalRevalidationSnapshotV1:
    """One full-module call-use pass per consumer module for revalidation."""
    cache_key = _revalidation_cache_key(root, path, source_cid, module_identities)
    hit = _REVALIDATION_SNAPSHOTS.get(cache_key)
    if hit is not None:
        return hit
    rows, outcomes = authenticated_import_uses(
        root,
        path,
        source,
        source_cid,
        module_identities=module_identities,
    )
    snapshot = _LexicalRevalidationSnapshotV1(
        row_cids=frozenset(_hash(row) for row in rows),
        outcomes=MappingProxyType(dict(outcomes)),
    )
    _REVALIDATION_SNAPSHOTS[cache_key] = snapshot
    return snapshot


def _lexical_value_revalidation_snapshot(
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]],
) -> _LexicalRevalidationSnapshotV1:
    """One full-module value-use pass per consumer module for revalidation."""
    cache_key = _revalidation_cache_key(root, path, source_cid, module_identities)
    hit = _VALUE_REVALIDATION_SNAPSHOTS.get(cache_key)
    if hit is not None:
        return hit
    rows, outcomes = authenticated_import_value_uses(
        root,
        path,
        source,
        source_cid,
        module_identities=module_identities,
    )
    snapshot = _LexicalRevalidationSnapshotV1(
        row_cids=frozenset(_hash(row) for row in rows),
        outcomes=MappingProxyType(dict(outcomes)),
    )
    _VALUE_REVALIDATION_SNAPSHOTS[cache_key] = snapshot
    return snapshot


def _require_source_cid_matches_text(source: str, source_cid: str) -> None:
    """Refuse dual-door identity at the import-use mint boundary.

    Claimed ``(source, source_cid)`` must satisfy the path_source law:
    ``source_cid == blake3(source.encode("utf-8"))``. A mismatched tuple is
    not repaired — that would rewrite authenticated testimony after minting.
    Fix the identity at the source door (``path_source`` / oracle triple).
    """
    expected = blake3_512_of(source.encode("utf-8"))
    if source_cid != expected:
        raise ValueError("authenticated import-use source CID is stale")


def _run_lexical_import_pass_on_module(
    module,
    *,
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]] | None = None,
) -> _Pass:
    """One reaching-definition walk over an already-materialized Module root.

    Call rows, value rows, and the reference table come from this single walk. Callers
    that already hold a SourceFile for ``source_cid`` (prefix door, frame door)
    MUST use this entry so the walk does not rebuild the typed tree.

    Prefer ``get_or_prepare_lexical_import_pass`` (§4 process residency) at
    public doors so the same content CID does not re-walk in one process.
    """
    _require_source_cid_matches_text(source, source_cid)
    module_name = module_name_for_path(root, path)
    identities = module_identities or {}
    module_state = _final_module_state(
        module=module,
        source_cid=source_cid,
        module_name=module_name,
        module_is_package=path.name == "__init__.py",
        module_identities=identities,
    )
    runner = _Pass(
        source_cid=source_cid,
        module_name=module_name,
        module_is_package=path.name == "__init__.py",
        module_identities=identities,
        module_state=module_state,
    )
    runner.statements(module.body, {}, module)
    return runner


def _run_lexical_import_pass(
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]] | None = None,
) -> _Pass:
    """One reaching-definition walk: call rows, value rows, and name targets.

    The file is read at its own seat (``_source_file_at_own_seat``), the seat
    the one opener reads, with no construction context: these rows are what
    that context's table is built from, so the opener itself cannot be used
    here. Lexical product is §4-resident so a second open does not re-walk.
    """
    from sugar_lift_py_tests.lift_rpc import _source_file_at_own_seat
    from sugar_source_tree.process_resident_file import (
        get_or_prepare_lexical_import_pass,
    )

    _require_source_cid_matches_text(source, source_cid)
    source_file = _source_file_at_own_seat(Path(path), root=Path(root))
    if source_file.unit.source_cid != source_cid:
        # The seat read different bytes than the claimed text: the claim is
        # stale against the file, refused like any other stale claim.
        raise ValueError("authenticated import-use source CID is stale")
    module = source_file.root
    return get_or_prepare_lexical_import_pass(
        module,
        root=root,
        path=path,
        source=source,
        source_cid=source_cid,
        module_identities=module_identities,
    )


def authenticated_import_uses(
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[tuple[int, int, int, int], str]]:
    runner = _run_lexical_import_pass(root, path, source, source_cid, module_identities)
    return runner.rows, runner.outcomes


def authenticated_import_value_uses(
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[tuple[int, int, int, int], str]]:
    """Raw value-occurrence rows for imported Name and Attribute loads.

    Same lexical pass as call uses; separate row surface so Call-target
    receipts stay byte-identical.
    """
    runner = _run_lexical_import_pass(root, path, source, source_cid, module_identities)
    return runner.value_rows, runner.value_outcomes


def _mint_import_use_receipts(
    rows: list[dict[str, Any]],
    *,
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]] | None,
) -> list[AuthenticatedImportUseV1]:
    receipts: list[AuthenticatedImportUseV1] = []
    for row in rows:
        binding_value = row["importBinding"]
        binding = ImportBindingV1(
            binding_value, row["importBindingCid"], _IMPORT_AUTHORITY
        )
        receipts.append(
            AuthenticatedImportUseV1(
                import_binding=binding,
                target_symbol=row["targetSymbol"],
                use=row["authenticatedImportUse"],
                demand=row,
                root=root,
                path=path,
                source=source,
                source_cid=source_cid,
                module_identities=dict(module_identities or {}),
                _authority=_IMPORT_AUTHORITY,
            )
        )
    return receipts


def authenticated_import_use_receipts(
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]] | None = None,
    *,
    module=None,
) -> tuple[list[AuthenticatedImportUseV1], dict[tuple[int, int, int, int], str]]:
    """Return typed, final-checked Call-target receipts from the lexical pass.

    ``module`` — already-materialized Module root for this ``source_cid``. When
    the caller just opened a SourceFile (populate after open), pass its root so
    the pass does not re-Materialize the same body (measured: second full
    ``_json.py`` SourceFile inside populate equaled ~0.25s of residual wall).

    Enumeration protocol §4: the lexical pass is module temporal preparation for
    this content CID — process-resident, once per CID (+ package role). Seat-bound
    receipts are minted per call with the caller's root/path; the pass product is not.
    """
    # Refuse mismatched claims here (same boundary as AuthenticatedImportUseV1);
    # never rewrite source_cid after minting.
    if module_identities is None:
        module_identities = {}
    if module is not None:
        from sugar_source_tree.process_resident_file import (
            get_or_prepare_lexical_import_pass,
        )

        runner = get_or_prepare_lexical_import_pass(
            module,
            root=root,
            path=path,
            source=source,
            source_cid=source_cid,
            module_identities=module_identities,
        )
        rows, outcomes = runner.rows, runner.outcomes
    else:
        rows, outcomes = authenticated_import_uses(
            root, path, source, source_cid, module_identities=module_identities
        )
    # Same pass fills revalidation snapshot so receipt.revalidate() does not
    # re-Materialize the module (mint+revalidate was a second SourceFile).
    cache_key = _revalidation_cache_key(root, path, source_cid, module_identities)
    if cache_key not in _REVALIDATION_SNAPSHOTS:
        _REVALIDATION_SNAPSHOTS[cache_key] = _LexicalRevalidationSnapshotV1(
            row_cids=frozenset(_hash(row) for row in rows),
            outcomes=MappingProxyType(dict(outcomes)),
        )
    return (
        _mint_import_use_receipts(
            rows,
            root=root,
            path=path,
            source=source,
            source_cid=source_cid,
            module_identities=module_identities,
        ),
        outcomes,
    )


def authenticated_import_value_use_receipts(
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]] | None = None,
    *,
    module=None,
) -> tuple[list[AuthenticatedImportUseV1], dict[tuple[int, int, int, int], str]]:
    """Final-checked receipts for imported Name and Attribute value occurrences.

    Exact-coordinate rows so preconstruction can resolve caller actuals and
    helper identity operands to authenticated object CIDs without spelling
    authority.  Call-target receipts remain on
    ``authenticated_import_use_receipts`` unchanged.

    When ``module`` is provided (or the body is process-resident under §4), the
    lexical pass is reused with the call-target door — one walk fills both.
    """
    if module_identities is None:
        module_identities = {}
    if module is not None:
        from sugar_source_tree.process_resident_file import (
            get_or_prepare_lexical_import_pass,
        )

        runner = get_or_prepare_lexical_import_pass(
            module,
            root=root,
            path=path,
            source=source,
            source_cid=source_cid,
            module_identities=module_identities,
        )
        rows, outcomes = runner.value_rows, runner.value_outcomes
    else:
        rows, outcomes = authenticated_import_value_uses(
            root, path, source, source_cid, module_identities=module_identities
        )
    cache_key = _revalidation_cache_key(root, path, source_cid, module_identities)
    if cache_key not in _VALUE_REVALIDATION_SNAPSHOTS:
        _VALUE_REVALIDATION_SNAPSHOTS[cache_key] = _LexicalRevalidationSnapshotV1(
            row_cids=frozenset(_hash(row) for row in rows),
            outcomes=MappingProxyType(dict(outcomes)),
        )
    return (
        _mint_import_use_receipts(
            rows,
            root=root,
            path=path,
            source=source,
            source_cid=source_cid,
            module_identities=module_identities,
        ),
        outcomes,
    )
