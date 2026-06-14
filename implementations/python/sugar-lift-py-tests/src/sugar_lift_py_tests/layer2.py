# SPDX-License-Identifier: Apache-2.0
#
# sugar-lift-py-tests / layer 2
#
# Layer 2 sits ABOVE the (future) Python Layer 0 ("mechanical assert
# recognition") and below the eventual Layer 3 LLM lift. It walks the
# Python AST of a source file and recognizes five structural patterns:
#
#   PATTERN 1 - bounded for loop as universal quantifier
#       def test_x():
#           for i in range(lo, hi):           # range(hi) accepted, step skipped
#               assert <comp> ...             # single-stmt body
#   Lift to: forall i:Int. (lo <= i AND i < hi) -> phi(i).
#   Memento name: ``<test>::loop::<var>``.
#
#   Variant 1b - bounded loop over a literal list:
#       def test_x():
#           for v in [1, 2, 3]:
#               assert <comp involving v>
#   Lift to: enumerated and-conjunction of phi[v_i] across the list.
#   Same memento name shape.
#
#   PATTERN 2 - helper function inlined at each call site
#       def assert_is_42(x: int):
#           assert x == 42
#       def test_x():
#           assert_is_42(42)
#           assert_is_42(42)
#   Lift to: ONE memento per call site, ``<test>::call::<i>`` zero-indexed.
#   The helper must have one TYPED parameter and a body that is exactly one
#   liftable assertion.
#
#   PATTERN 3 - multi-assertion characterization
#       def test_x():
#           assert f(1) == 1
#           assert f(2) == 2
#           assert f(3) != 0
#   Lift to: ONE conjunction memento at ``<test>``. >=2 atoms required;
#   <2 releases the claim back to Layer 0.
#
#   PATTERN 4 - @pytest.mark.parametrize over a literal arg list
#       @pytest.mark.parametrize("v", [1, 2, 3])
#       def test_x(v):
#           assert v >= 0
#   Lift to: ONE ContractDecl per row, each checked independently.
#   Memento name: ``<test>::parametrize::<param-names>::row<i>``.
#   SOUNDNESS: pytest runs each row as an independent test instance; a free
#   non-param variable k in the body must not be tied across rows.
#   Conjoining rows into a single formula (eq(k,1) ^ eq(k,2)) would be UNSAT
#   (a false-refuse) when k is free.  Per-row contracts are the correct model.
#
#   PATTERN 5 - callsite value-scope facts plus implications
#       def test_parse():
#           actual = parse_int("42")
#           assert actual == 42
#   Lift to: two callsite-owned contracts,
#       ``parse_int@<file>:<line>:<col>::facts`` and
#       ``parse_int@<file>:<line>:<col>::assertion``,
#   plus an implication edge from facts to assertion. The test is evidence
#   describing the callsite contract; it does not own the contract name.
#
# CLAIM SET:
#   ``lift_file_layer2`` returns a ``claimed_tests`` set: each test name
#   Layer 2 took ownership of. The dispatcher passes that set to Layer 0
#   (when Python Layer 0 lands) so each test fn is lifted by AT MOST one
#   layer. Out-of-scope shapes (hypothesis ``@given``, pytest fixtures,
#   ``with pytest.raises``, etc.) are left for Layer 0 / Layer 3.

from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from .ir import (
    ContractDecl,
    Formula,
    Int,
    Term,
    _Atomic,
    _Connective,
    _Ctor,
    and_,
    atomic,
    bool_const,
    comparison_with_none_guard,
    connective,
    ctor,
    eq,
    gt,
    gte,
    implies,
    lt,
    lte,
    make_var,
    ne,
    not_,
    num,
    or_,
    str_const,
    subst_var_in_formula,
)
from .translate_universe import (
    ISINSTANCE_CONCRETE_BUILTINS,
    branch_selected_raise_universe_for_callee,
    branch_selected_return_universe_for_callee,
    branch_literal_universe_for_callee,
    bytes_identity_universe_for_callee,
    callee_is_nondeterministic,
    collection_literal_canonical,
    conditional_chain_universe_for_callee,
    constructor_field_universe_for_callee,
    constructor_param_defaults_for_callee,
    constructor_param_names_for_callee,
    constant_universe_for_callee,
    delegation_universe_for_callee,
    eval_predicate,
    exception_bool_return_universe_for_callee,
    exception_handler_raise_universe_for_callee,
    guard_universe_for_callee,
    instance_field_universe_for_callee,
    list_adapter_universe_for_callee,
    predicate_universe_for_callee,
    raise_locus_universe_for_callee,
    return_isinstance_universe_for_callee,
    return_regex_universe_for_callee,
    separator_guard_raise_universe_for_callee,
    translate_universe_for_callee,
)

try:
    from sugar_lift_python_source.bind_lifter import (
        _body_source_locator as _source_oracle_body_source_locator,
        source_memento_of as _source_oracle_memento_of,
    )
except ModuleNotFoundError:
    import sys
    from pathlib import Path

    _SIBLING_SOURCE_SRC = (
        Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
    )
    if str(_SIBLING_SOURCE_SRC) not in sys.path:
        sys.path.insert(0, str(_SIBLING_SOURCE_SRC))
    from sugar_lift_python_source.bind_lifter import (
        _body_source_locator as _source_oracle_body_source_locator,
        source_memento_of as _source_oracle_memento_of,
    )


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class LiftWarning:
    source_path: str
    item_name: str
    reason: str


def _empty_source_ledger() -> dict[str, int]:
    return {
        "source_loci": 0,
        "source_warranted": 0,
        "source_support": 0,
        "source_refused": 0,
        "source_inactive": 0,
        "source_refuted": 0,
        "unclassified_source": 0,
    }


@dataclass
class Layer2Output:
    decls: List[ContractDecl] = field(default_factory=list)
    warnings: List[LiftWarning] = field(default_factory=list)
    seen: int = 0
    lifted: int = 0
    claimed_tests: Set[str] = field(default_factory=set)
    bounded_loop_lifted: int = 0
    bounded_loop_skipped: int = 0
    embedded_for_lifted: int = 0
    embedded_for_skipped: int = 0
    if_guarded_lifted: int = 0
    if_guarded_skipped: int = 0
    with_body_lifted: int = 0
    with_body_skipped: int = 0
    helper_inlined_lifted: int = 0
    helper_inlined_skipped: int = 0
    characterization_lifted: int = 0
    characterization_skipped: int = 0
    parametrize_lifted: int = 0
    parametrize_skipped: int = 0
    value_scope_lifted: int = 0
    value_scope_skipped: int = 0
    mixed_body_lifted: int = 0
    mixed_body_skipped: int = 0
    raises_lifted: int = 0
    raises_skipped: int = 0
    implications: List["ImplicationDecl"] = field(default_factory=list)
    source_audits: List[dict[str, Any]] = field(default_factory=list)
    source_ledger: dict[str, int] = field(default_factory=_empty_source_ledger)


@dataclass
class ImplicationDecl:
    name: str
    antecedent: str
    consequent: str
    antecedent_slot: str = "inv"
    consequent_slot: str = "inv"
    prover: str = "python-test-value-scope"
    proof_witness: str = ""


@dataclass
class _HelperDef:
    """A function with one typed param + a single liftable assertion."""
    param_name: str
    assertion: ast.stmt  # the single body statement


@dataclass
class _CallOrigin:
    callee: str
    lineno: int
    col: int
    # ARGUMENT-CARRYING EUF: when the call result was lifted to an
    # argument-keyed ctor (``callresult_<callee>_a<n>``), ``arg_sig`` holds a
    # deterministic canonical signature of the SSA-resolved arg-terms.  This
    # makes the callsite contract base argument-keyed (``<callee>#<arg_sig>``)
    # instead of location-keyed, so mint's coalesce-by-name conjoins TWO
    # cross-location assertions about the SAME (callee, args) into a single
    # ``::assertion`` inv → the contradiction fires UNSAT.  None when the call
    # fell back to the location-keyed free var (no cross-location unification).
    arg_sig: Optional[str] = None
    # BINDING-FORM EUF SUBSTITUTION: when a local ``r = f(5)`` is bound via
    # ``_apply_value_scope_binding`` and the RHS is a concrete-arg call, these
    # two fields carry the EUF ctor term and the SSA var name so that
    # ``_assertion_callsite_context`` can substitute the SSA var for the EUF
    # ctor in the assertion formula.  None when the origin came from a direct
    # call in the assertion expression (not a binding), or when the binding RHS
    # has symbolic args (location-keyed path, no substitution).
    euf_term: Optional["Term"] = None
    ssa_name: Optional[str] = None
    # INSTANCE CONSTRUCTION: when a scoped variable is bound by ``C(args...)``,
    # remember those constructor argument terms. A later ``var.method()``
    # origin copies them so a source walk over ``__init__`` + ``method`` can
    # instantiate constructor-field getter relations.
    constructor_args: Optional[Tuple["Term", ...]] = None
    constructor_default_params: Tuple[str, ...] = ()
    receiver_constructor: Optional[str] = None
    # Instantiated call argument terms even when the call result itself is
    # location-keyed. Source universes over symbolic callsites still need the
    # parameter -> argument map.
    arg_terms: Optional[Tuple["Term", ...]] = None
    # The actual result term that appears in the assertion for direct calls:
    # either the argument-keyed callresult ctor or the location-keyed Var.
    result_term: Optional["Term"] = None


@dataclass
class _ValueScope:
    current: Dict[str, Term] = field(default_factory=dict)
    projections: Dict[str, Dict[Term, Term]] = field(default_factory=dict)
    origins: Dict[str, _CallOrigin] = field(default_factory=dict)
    facts: List[Formula] = field(default_factory=list)

    def copy(self) -> "_ValueScope":
        return _ValueScope(
            current=dict(self.current),
            projections={
                name: dict(projection)
                for name, projection in self.projections.items()
            },
            origins=dict(self.origins),
            facts=list(self.facts),
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def lift_file_layer2(source: str, source_path: str) -> Layer2Output:
    """Parse ``source`` and lift Layer 2 patterns. ``source`` is the file
    text; ``source_path`` is informational (used in warnings).
    """
    out = Layer2Output()
    try:
        tree = ast.parse(source, filename=source_path)
    except SyntaxError as e:
        out.warnings.append(
            LiftWarning(source_path, "<file>", f"layer2: failed to parse Python source: {e}")
        )
        return out

    global _CURRENT_MODULE_ALIASES, _CURRENT_FROM_IMPORT_MEMBERS
    prev_aliases = _CURRENT_MODULE_ALIASES
    prev_members = _CURRENT_FROM_IMPORT_MEMBERS
    _CURRENT_MODULE_ALIASES = _collect_module_aliases(tree)
    _CURRENT_FROM_IMPORT_MEMBERS = _collect_from_import_members(
        tree, _CURRENT_MODULE_ALIASES
    )
    try:
        helpers = _collect_helpers(tree)
        test_fns = list(_iter_test_functions(tree))
        for fn, class_name in test_fns:
            _classify_and_lift(fn, source_path, source, helpers, out, class_name=class_name)

        _coalesce_same_named_decls(out)
        _refresh_source_accounting(out)
    finally:
        _CURRENT_MODULE_ALIASES = prev_aliases
        _CURRENT_FROM_IMPORT_MEMBERS = prev_members
    return out


def _iter_conjuncts(formula: Formula):
    if isinstance(formula, _Atomic):
        yield formula
        return
    if getattr(formula, "kind", None) == "and":
        for operand in formula.operands:
            yield from _iter_conjuncts(operand)


def _assertion_call_subject(assertion: Formula) -> Optional[Term]:
    """The call-shaped side of the assertion's value-relation atom: the term the
    assertion ACTUALLY swears about, and therefore the only sound subject
    for a sibling universe row. Returns None when no equality/inequality
    conjunct has a call-shaped (callval_*/callresult_*) ctor side."""
    for atom in _iter_conjuncts(assertion):
        if atom.name not in {"=", "≠"} or len(atom.args) != 2:
            continue
        for side in atom.args:
            if isinstance(side, _Ctor) and (
                side.name.startswith("callval_")
                or side.name.startswith("callresult_")
            ):
                return side
    return None


def _assertion_origin_attribute_subject(
    assertion: Formula,
    origin: "_CallOrigin",
) -> Optional[Tuple[Term, str]]:
    if origin.ssa_name is None:
        return None
    prefix = f"{origin.ssa_name}."
    for atom in _iter_conjuncts(assertion):
        if atom.name not in {"=", "≠"} or len(atom.args) != 2:
            continue
        for side in atom.args:
            found = _origin_attribute_term(side, prefix)
            if found is not None:
                return found
    return None


def _origin_attribute_term(term: Term, prefix: str) -> Optional[Tuple[Term, str]]:
    name = getattr(term, "name", "")
    if not isinstance(term, _Ctor) and isinstance(name, str):
        if name.startswith(prefix) and len(name) > len(prefix):
            field_name = name[len(prefix):].split(".", 1)[0]
            return term, field_name
    if isinstance(term, _Ctor):
        for arg in term.args:
            found = _origin_attribute_term(arg, prefix)
            if found is not None:
                return found
    return None


# NOTE on ∀⊨sample: the gate lives in translate_universe_for_callee and runs
# over the VENDOR's own test corpus (test.test_<module> / test_<module>) --
# the same party that swore the walked body. It deliberately does NOT read
# the file being lifted: a consumer claim contradicting the universe is the
# refutation working (decided by check), never gate evidence. The first
# version of this gate read same-file assertions and ate the bad twin's own
# refutation; that evidence model was wrong and is intentionally gone.


def _coalesce_same_named_decls(out: Layer2Output) -> None:
    """FILE-LEVEL coalescing for ARGUMENT-CARRYING EUF cross-FUNCTION
    contradictions.

    ``_classify_value_scope`` conjoins assertions about the same call-site base
    WITHIN one test function (its per-base ``assertion_atoms_by_base`` dict).
    But each test function is classified independently, so two DIFFERENT
    functions that assert about the SAME argument-keyed EUF base
    (``make_value#euf#...::assertion``) emit TWO separate ``ContractDecl``s with
    the SAME name and DIFFERENT invs (``=(cr(x),1)`` and ``=(cr(x),2)``).

    The verifier's load path treats two same-name / different-CID contracts as a
    DUPLICATE-NAME error and keeps one, dropping the other — so the cross-
    function contradiction would silently vanish (each survivor is a single,
    non-contradictory assertion → spurious PROVEN).  To make the contradiction
    visible, we conjoin same-named ``inv``-bearing decls HERE, at file scope,
    into ONE decl whose inv is ``and_([inv_0, inv_1, ...])``.  Then
    ``=(cr(x),1) ∧ =(cr(x),2)`` lands in a single inv → z3 UNSAT → REFUSED.

    SCOPE: this only ever merges decls that actually share a name.  Location-
    keyed bases embed ``line:col`` and are therefore unique per call site, so
    they NEVER collide and are left untouched.  Only the argument-keyed
    (``#euf#``) bases — which intentionally drop line:col so identical
    (callee, args) collapse — can collide, and merging them is exactly the
    cross-function unification we want.

    SOUNDNESS: conjoining ``A: f(x)=1`` with ``B: f(x)=2`` on the shared bare
    parameter name ``x`` treats the two independently-bound parameters as the
    same input.  That is the CONSERVATIVE direction — it can only OVER-REFUSE
    (the two ``x``s could differ at runtime), never produce a falsePass.  It is
    consistent with the EUF purity assumption documented at the call site.

    Order is preserved (first-seen name order; invs in append order) for
    deterministic, content-addressable output.
    """
    decls = out.decls
    # Group indices by name, preserving first-seen order.
    order: List[str] = []
    by_name: Dict[str, List[int]] = {}
    for i, d in enumerate(decls):
        if d.name not in by_name:
            by_name[d.name] = []
            order.append(d.name)
        by_name[d.name].append(i)

    # Nothing to do if every name is unique.
    if all(len(idxs) == 1 for idxs in by_name.values()):
        return

    new_decls: List[ContractDecl] = []
    for name in order:
        idxs = by_name[name]
        if len(idxs) == 1:
            new_decls.append(decls[idxs[0]])
            continue
        group = [decls[i] for i in idxs]
        # Only coalesce when EVERY member is a pure ``inv`` contract (the shape
        # the value-scope ::assertion path emits).  If any member carries
        # pre/post/evidence (not produced by this path), fall back to keeping
        # the FIRST decl unchanged rather than risk merging incompatible shapes.
        if not all(
            d.inv is not None
            and d.pre is None
            and d.post is None
            and d.evidence is None
            for d in group
        ):
            new_decls.append(group[0])
            continue
        invs = [d.inv for d in group]
        merged_inv = invs[0] if len(invs) == 1 else and_(invs)
        source_warrants: List[dict] = []
        for d in group:
            for warrant in d.source_warrants:
                _append_unique_source_warrant(source_warrants, warrant)
        new_decls.append(
            ContractDecl(name=name, inv=merged_inv, source_warrants=source_warrants)
        )

    out.decls = new_decls


def _refresh_source_accounting(out: Layer2Output) -> None:
    audits: List[dict[str, Any]] = []
    ledger = _empty_source_ledger()
    seen: Set[str] = set()

    for decl in out.decls:
        for warrant in decl.source_warrants:
            key = json.dumps(warrant, sort_keys=True, separators=(",", ":"))
            if key in seen:
                continue
            seen.add(key)
            audit = _source_audit_for_warrant(decl.name, warrant, out)
            audits.append(audit)
            totals = audit["totals"]
            for field in ledger:
                ledger[field] += int(totals.get(field, 0))

    out.source_audits = audits
    out.source_ledger = ledger


def _source_audit_for_warrant(
    contract_name: str,
    warrant: dict[str, Any],
    out: Layer2Output,
) -> dict[str, Any]:
    source_memento = _lean_source_memento(warrant)
    role = _string_field(warrant, "role")
    universe_kind = _string_field(warrant, "universe_kind")
    table_name = _string_field(warrant, "table_name")
    file = _string_field(source_memento, "file")
    loci: List[dict[str, Any]] = []

    try:
        _, root = _resolve_source_memento_for_accounting(source_memento)
        loci = _source_loci_for_memento(
            source_memento,
            root,
            role,
            universe_kind,
        )
    except Exception as exc:
        out.warnings.append(
            LiftWarning(
                file or "<source>",
                contract_name,
                f"source-audit: source oracle failed to resolve SourceMemento: {exc}",
            )
        )
        loci.append(
            _source_line_locus(
                file,
                _source_memento_start_line(source_memento),
                "unclassified",
                role,
                universe_kind,
                reason="source-oracle resolution failed",
            )
        )

    audit: dict[str, Any] = {
        "kind": "source-audit",
        "language": "python",
        "contract": {"name": contract_name},
        "role": role,
        "universe_kind": universe_kind,
        "source_memento": source_memento,
        "loci": loci,
        "totals": _source_totals(loci),
    }
    if table_name:
        audit["table_name"] = table_name
    return audit


def _resolve_source_memento_for_accounting(memento: dict[str, Any]) -> Tuple[dict[str, Any], str]:
    try:
        from sugar_lift_python_source.source_oracle import (
            SourceOracleRefusal,
            importlib_package_root,
            resolve_source_memento,
        )
    except ModuleNotFoundError:
        import sys
        from pathlib import Path

        sibling_src = (
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.source_oracle import (
            SourceOracleRefusal,
            importlib_package_root,
            resolve_source_memento,
        )

    roots = ["", os.getcwd()]
    package_root = importlib_package_root(_string_field(memento, "file"))
    if package_root is not None:
        roots.append(package_root)

    last: Optional[Exception] = None
    for root in roots:
        try:
            resolved = resolve_source_memento(root, memento)
            return resolved, root
        except SourceOracleRefusal as exc:
            last = exc
    if last is not None:
        raise last
    raise RuntimeError("no root resolved the source memento")


def _lean_source_memento(warrant: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": "source-memento"}
    for field_name in (
        "file",
        "source_function_name",
        "span",
        "source_cid",
        "template_cid",
        "param_names",
        "field_name",
        "field_projection",
        "constructor_param_name",
        "constructor_default_param_names",
        "constructor_default_attr_name",
        "constructor_default_literal",
        "constructor_default_literal_kind",
        "adapter_callee",
        "helper_callee",
        "list_adapter_branch",
        "branch_field_name",
        "branch_field_value",
        "branch_field_value_kind",
        "branch_return_param_name",
        "branch_return_adapter_callee",
        "branch_param_name",
        "branch_param_index",
        "branch_excluded_value",
        "branch_excluded_value_kind",
        "branch_if_line",
        "branch_raise_line",
        "branch_raise_exception_type",
        "exception_handler_raise_type",
        "exception_handler_try_line",
        "exception_bool_return_exception_type",
        "exception_bool_return_try_line",
        "exception_bool_return_delegate",
        "exception_bool_return_success_value",
        "exception_bool_return_exception_value",
        "guard_lines",
        "regex_pattern",
        "regex_param_name",
        "regex_compile_var",
        "regex_match_kind",
        "regex_membership_pattern",
        "regex_true_implies_membership",
        "regex_false_implies_nonmembership",
        "separator_guard_exception_type",
        "separator_guard_field_name",
        "separator_guard_param_name",
        "separator_guard_line",
        "separator_guard_raise_line",
        "separator_guard_adapter_callee",
        "separator_guard_adapter_line",
    ):
        if field_name not in warrant:
            continue
        value = warrant[field_name]
        if field_name == "span" and isinstance(value, dict):
            out[field_name] = dict(value)
        elif field_name == "param_names" and isinstance(value, list):
            out[field_name] = list(value)
        elif field_name == "constructor_default_param_names" and isinstance(value, list):
            out[field_name] = list(value)
        elif field_name == "field_projection" and isinstance(value, list):
            out[field_name] = list(value)
        elif field_name == "guard_lines" and isinstance(value, list):
            out[field_name] = list(value)
        else:
            out[field_name] = value
    return out


def _source_line_locus(
    file: str,
    line: int,
    status: str,
    role: str,
    universe_kind: str,
    *,
    ast_kind: Optional[str] = None,
    ast_path: Optional[str] = None,
    span: Optional[dict[str, int]] = None,
    reason: str = "",
) -> dict[str, Any]:
    locus_span = span or {
        "start_line": line,
        "start_col": 0,
        "end_line": line,
        "end_col": 0,
    }
    locus: dict[str, Any] = {
        "kind": "source-line",
        "file": file,
        "line": line,
        "span": dict(locus_span),
        "line_range": [locus_span["start_line"], locus_span["end_line"]],
        "ast_path": ast_path or f"$.line[{line}]",
        "status": status,
        "role": role,
        "universe_kind": universe_kind,
    }
    if ast_kind:
        locus["ast_kind"] = ast_kind
    if reason:
        locus["reason"] = reason
    return locus


def _source_loci_for_memento(
    source_memento: dict[str, Any],
    root: str,
    role: str,
    universe_kind: str,
) -> List[dict[str, Any]]:
    file = _string_field(source_memento, "file")
    if role == "python.guard-universe":
        return _source_loci_for_guard_memento(
            source_memento,
            root,
            role,
            universe_kind,
        )
    if role not in {
        "python.translate-universe",
        "python.bytes-identity-universe",
        "python.list-adapter-universe",
        "python.constant-universe",
        "python.delegation-universe",
        "python.branch-selected-universe",
        "python.instance-field-universe",
        "python.raise-locus-universe",
        "python.exception-handler-raise-universe",
        "python.return-isinstance-universe",
        "python.regex-universe",
    }:
        return [
            _source_line_locus(file, line, "warranted", role, universe_kind)
            for line in _source_memento_lines(source_memento)
        ]

    path = os.path.join(root, file) if root else file
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source, filename=path)
    fn = _locate_source_function_for_accounting(tree, source_memento)
    if fn is None:
        return [
            _source_line_locus(
                file,
                _source_memento_start_line(source_memento),
                "unclassified",
                role,
                universe_kind,
                reason="source function not found after source-oracle resolution",
            )
        ]

    loci: List[dict[str, Any]] = []
    loci.extend(
        _source_header_loci_for_memento(
            fn,
            source_memento,
            file,
            role,
            universe_kind,
        )
    )
    for index, stmt in enumerate(fn.body):
        for node, ast_path in _iter_ast_nodes_with_paths(stmt, f"$.body[{index}]"):
            if not hasattr(node, "lineno"):
                continue
            status, reason = _classify_universe_source_node(
                role,
                universe_kind,
                stmt,
                node,
                source_memento,
            )
            loci.append(
                _source_line_locus(
                    file,
                    getattr(node, "lineno", _source_memento_start_line(source_memento)),
                    status,
                    role,
                    universe_kind,
                    ast_kind=type(node).__name__,
                    ast_path=ast_path,
                    span=_ast_node_span(node),
                    reason=reason,
                )
            )
    return loci


def _source_loci_for_guard_memento(
    source_memento: dict[str, Any],
    root: str,
    role: str,
    universe_kind: str,
) -> List[dict[str, Any]]:
    file = _string_field(source_memento, "file")
    path = os.path.join(root, file) if root else file
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source, filename=path)
    fn = _locate_source_function_for_accounting(tree, source_memento)
    if fn is None:
        return [
            _source_line_locus(
                file,
                _source_memento_start_line(source_memento),
                "unclassified",
                role,
                universe_kind,
                reason="source function not found after source-oracle resolution",
            )
        ]

    guard_lines = {
        int(line)
        for line in source_memento.get("guard_lines", [])
        if isinstance(line, int)
    }
    loci: List[dict[str, Any]] = []
    loci.extend(
        _source_header_loci_for_memento(
            fn,
            source_memento,
            file,
            role,
            universe_kind,
        )
    )
    for index, stmt in enumerate(fn.body):
        if not _is_docstring_stmt(stmt) and getattr(stmt, "lineno", 0) not in guard_lines:
            continue
        for node, ast_path in _iter_ast_nodes_with_paths(stmt, f"$.body[{index}]"):
            if not hasattr(node, "lineno"):
                continue
            status, reason = _classify_guard_source_node(
                stmt,
                node,
                source_memento,
            )
            if status == "unclassified":
                continue
            loci.append(
                _source_line_locus(
                    file,
                    getattr(node, "lineno", _source_memento_start_line(source_memento)),
                    status,
                    role,
                    universe_kind,
                    ast_kind=type(node).__name__,
                    ast_path=ast_path,
                    span=_ast_node_span(node),
                    reason=reason,
                )
            )
    return loci


def _source_header_loci_for_memento(
    fn: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    source_memento: dict[str, Any],
    file: str,
    role: str,
    universe_kind: str,
) -> List[dict[str, Any]]:
    if role != "python.instance-field-universe":
        return []
    raw_default_params = source_memento.get("constructor_default_param_names")
    default_params = {
        param
        for param in raw_default_params
        if isinstance(param, str)
    } if isinstance(raw_default_params, list) else set()
    params = [arg.arg for arg in (*fn.args.posonlyargs, *fn.args.args)]
    if params and params[0] == "self":
        params = params[1:]
    defaults = list(fn.args.defaults)
    if not defaults or len(defaults) > len(params):
        return []
    start = len(params) - len(defaults)
    loci: List[dict[str, Any]] = []
    for offset, default_node in enumerate(defaults):
        param_name = params[start + offset]
        status = "warranted" if param_name in default_params else "support"
        reason = (
            "default constructor argument emitted into python.instance-field-universe"
            if status == "warranted"
            else "constructor default metadata supports callsite argument mapping"
        )
        for node, ast_path in _iter_ast_nodes_with_paths(
            default_node,
            f"$.args.defaults[{offset}]",
        ):
            if not hasattr(node, "lineno"):
                continue
            loci.append(
                _source_line_locus(
                    file,
                    getattr(node, "lineno", _source_memento_start_line(source_memento)),
                    status,
                    role,
                    universe_kind,
                    ast_kind=type(node).__name__,
                    ast_path=ast_path,
                    span=_ast_node_span(node),
                    reason=reason,
                )
            )
    return loci


def _iter_ast_nodes_with_paths(
    node: ast.AST,
    path: str,
):
    yield node, path
    for field_name, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            yield from _iter_ast_nodes_with_paths(value, f"{path}.{field_name}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, ast.AST):
                    yield from _iter_ast_nodes_with_paths(
                        item,
                        f"{path}.{field_name}[{index}]",
                    )


def _ast_node_span(node: ast.AST) -> dict[str, int]:
    start_line = getattr(node, "lineno", 0)
    start_col = getattr(node, "col_offset", 0)
    end_line = getattr(node, "end_lineno", start_line)
    end_col = getattr(node, "end_col_offset", start_col)
    return {
        "start_line": start_line,
        "start_col": start_col,
        "end_line": end_line,
        "end_col": end_col,
    }


def _source_memento_for_statement(
    fn: ast.FunctionDef,
    stmt: ast.stmt,
    source_path: str,
    source: str,
    *,
    role: str,
    claim_name: str,
    contract_name: str,
) -> Optional[dict[str, Any]]:
    try:
        full = _source_oracle_body_source_locator(
            fn,
            source_path,
            source.splitlines(keepends=True),
        )
        memento = dict(_source_oracle_memento_of(full))
    except Exception:
        return None
    memento["kind"] = "source-memento"
    memento["role"] = role
    memento["claimName"] = claim_name
    memento["contractName"] = contract_name
    memento["source_function_name"] = fn.name
    memento["span"] = _ast_node_span(stmt)
    memento.pop("body_text", None)
    memento.pop("ast_template", None)
    return memento


def _locate_source_function_for_accounting(
    tree: ast.AST,
    source_memento: dict[str, Any],
) -> Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
    function_name = _string_field(source_memento, "source_function_name")
    function_leaf = function_name.rsplit(".", 1)[-1] if function_name else ""
    span = source_memento.get("span") if isinstance(source_memento.get("span"), dict) else {}
    start = _int_field(span, "start_line", 0)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (
            not function_name
            or node.name == function_name
            or node.name == function_leaf
        )
    ]
    if not matches:
        return None
    if start > 0:
        for node in matches:
            node_start = min((d.lineno for d in node.decorator_list), default=node.lineno)
            node_end = node.end_lineno or node.lineno
            if node_start <= start <= node_end:
                return node
    return matches[0]


def _classify_universe_source_node(
    role: str,
    universe_kind: str,
    stmt: ast.stmt,
    node: ast.AST,
    source_memento: dict[str, Any],
) -> Tuple[str, str]:
    if role == "python.delegation-universe" and isinstance(stmt, ast.Assign):
        return (
            "warranted",
            "SSA chain assignment emitted into python.delegation-universe",
        )
    if role == "python.delegation-universe" and isinstance(node, ast.Call):
        if _is_transparent_typing_cast_call(node):
            return (
                "warranted",
                "transparent typing cast admitted as compiler axiom",
            )
        if universe_kind == "delegation-stdlib":
            return "warranted", "emitted into python.delegation-universe"
        return "support", "queued delegate dig for recursive universe walk"
    if role == "python.branch-selected-universe":
        return _classify_branch_selected_source_node(stmt, node, source_memento)
    if role == "python.guard-universe":
        return _classify_guard_source_node(stmt, node, source_memento)
    if role == "python.branch-selected-raise-universe":
        return _classify_branch_selected_raise_source_node(stmt, node, source_memento)
    if role == "python.exception-handler-raise-universe":
        return _classify_exception_handler_raise_source_node(stmt, node, source_memento)
    if role == "python.exception-bool-return-universe":
        return _classify_exception_bool_return_source_node(stmt, node, source_memento)
    if role == "python.separator-guard-raise-universe":
        return _classify_separator_guard_raise_source_node(stmt, node, source_memento)
    if (
        role == "python.return-isinstance-universe"
        and isinstance(stmt, ast.Return)
        and isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
    ):
        return "warranted", "isinstance predicate emitted into python.return-isinstance-universe"
    if role == "python.regex-universe":
        return _classify_regex_source_node(stmt, node, source_memento)
    return _classify_universe_source_statement(role, stmt, source_memento)


def _classify_universe_source_statement(
    role: str,
    stmt: ast.stmt,
    source_memento: dict[str, Any],
) -> Tuple[str, str]:
    if role == "python.translate-universe":
        return _classify_translate_source_statement(stmt)
    if role == "python.constant-universe":
        if _is_docstring_stmt(stmt):
            return "support", "docstring metadata supports source accounting only"
        if _is_constant_return(stmt):
            return "warranted", "emitted into python.constant-universe"
        if isinstance(stmt, (ast.If, ast.Assert)):
            return "support", "guard support for constant return universe"
        return "support", "non-constraint source support for constant-universe accounting"
    if role == "python.bytes-identity-universe":
        if _is_docstring_stmt(stmt):
            return "support", "docstring metadata supports source accounting only"
        if isinstance(stmt, ast.If):
            return "inactive", "str encode branch inactive for concrete bytes callsite"
        if isinstance(stmt, ast.Return):
            return "warranted", "emitted into python.bytes-identity-universe"
        return "support", "non-constraint source support for bytes-identity accounting"
    if role == "python.list-adapter-universe":
        if _is_docstring_stmt(stmt):
            return "support", "docstring metadata supports source accounting only"
        branch = _string_field(source_memento, "list_adapter_branch")
        if _is_list_adapter_active_if(stmt):
            if branch == "iterable":
                return "inactive", "scalar branch inactive for concrete iterable callsite"
            return "warranted", "emitted into python.list-adapter-universe"
        if _is_list_adapter_iterable_return(stmt):
            if branch == "iterable":
                return "warranted", "iterable branch emitted into python.list-adapter-universe"
            return "inactive", "iterable branch inactive for concrete str/bytes callsite"
        return "unclassified", "list-adapter source not emitted"
    if role == "python.delegation-universe":
        if _is_docstring_stmt(stmt):
            return "support", "docstring metadata supports source accounting only"
        if isinstance(stmt, ast.Return):
            return "warranted", "emitted into python.delegation-universe"
        if isinstance(stmt, ast.Assign):
            return "warranted", "SSA chain assignment emitted into python.delegation-universe"
        if isinstance(stmt, (ast.If, ast.Assert)):
            return "support", "guard support for delegation universe"
        return "support", "non-constraint source support for delegation-universe accounting"
    if role == "python.branch-selected-universe":
        return _classify_branch_selected_source_node(stmt, stmt, source_memento)
    if role == "python.guard-universe":
        return _classify_guard_source_node(stmt, stmt, source_memento)
    if role == "python.branch-selected-raise-universe":
        return _classify_branch_selected_raise_source_node(stmt, stmt, source_memento)
    if role == "python.instance-field-universe":
        if _is_docstring_stmt(stmt):
            return "support", "docstring metadata supports source accounting only"
        if _is_super_init_expr(stmt):
            return "support", "base constructor call supports construction accounting"
        if _is_instance_field_validation_guard(stmt):
            return "support", "constructor validation guard supports construction accounting"
        default_params = _constructor_default_param_names(source_memento)
        default_if_param = _instance_field_default_if_param(stmt)
        if default_if_param is not None:
            if not default_params or default_if_param in default_params:
                return "warranted", "emitted into python.instance-field-universe"
            return "support", "unrelated constructor default branch supports source accounting"
        normalized_param = _instance_field_normalized_param(stmt)
        if normalized_param is not None:
            if normalized_param == _string_field(source_memento, "constructor_param_name"):
                return "warranted", "constructor parameter normalization emitted into python.instance-field-universe"
            return "support", "unrelated constructor parameter normalization supports source accounting"
        adapter_callee = _string_field(source_memento, "adapter_callee")
        helper_callee = _string_field(source_memento, "helper_callee")
        assign_param = _instance_field_assign_param(stmt)
        if assign_param is not None:
            if not default_params or assign_param in default_params:
                return "warranted", "emitted into python.instance-field-universe"
            return "support", "unrelated constructor field assignment supports source accounting"
        if adapter_callee and _is_instance_field_adapter_assign(stmt, adapter_callee):
            return "warranted", "emitted into python.instance-field-universe"
        if helper_callee and _is_instance_field_helper_assign(stmt, helper_callee):
            return "warranted", "emitted into python.instance-field-universe"
        if _is_instance_field_call_assign(stmt):
            return "support", "unrelated constructor field call assignment supports source accounting"
        if _is_instance_field_bool_or_default_assign(stmt):
            return "warranted", "constructor bool-or default emitted into python.instance-field-universe"
        if _is_instance_field_return(stmt):
            return "warranted", "emitted into python.instance-field-universe"
        return "unclassified", "instance-field source not emitted"
    if role == "python.raise-locus-universe":
        if _is_docstring_stmt(stmt):
            return "support", "docstring metadata supports source accounting only"
        if isinstance(stmt, (ast.Raise, ast.If)):
            return "warranted", "emitted into python.raise-locus-universe"
        return "support", "prelude support for raise-locus accounting"
    if role == "python.exception-handler-raise-universe":
        return _classify_exception_handler_raise_source_node(stmt, stmt, source_memento)
    if role == "python.exception-bool-return-universe":
        return _classify_exception_bool_return_source_node(stmt, stmt, source_memento)
    if role == "python.separator-guard-raise-universe":
        return _classify_separator_guard_raise_source_node(stmt, stmt, source_memento)
    if role == "python.return-isinstance-universe":
        if _is_docstring_stmt(stmt):
            return "support", "docstring metadata supports source accounting only"
        if _is_return_isinstance_stmt(stmt):
            return "warranted", "emitted into python.return-isinstance-universe"
        return "unclassified", "return-isinstance source not emitted"
    if role == "python.regex-universe":
        return _classify_regex_source_node(stmt, stmt, source_memento)
    return "unclassified", "source warrant role has no source-audit classifier"


def _classify_regex_source_node(
    stmt: ast.stmt,
    node: ast.AST,
    source_memento: dict[str, Any],
) -> Tuple[str, str]:
    if _is_docstring_stmt(stmt):
        return "support", "docstring metadata supports source accounting only"
    if _is_regex_compile_stmt(stmt, source_memento):
        return (
            "warranted",
            "regex constructor emitted as source support for str.in-regex",
        )
    regex_expr = _regex_expr_from_return_stmt(stmt, source_memento)
    if regex_expr is not None and _regex_source_node_is_emitted(stmt, node, regex_expr):
        match_kind = _string_field(source_memento, "regex_match_kind") or "fullmatch"
        if isinstance(node, ast.Call):
            return "warranted", f"regex {match_kind} emitted into str.in-regex"
        return "warranted", f"regex {match_kind} return emitted into python.regex-universe"
    return "unclassified", "regex source not emitted"


def _is_regex_compile_stmt(
    stmt: ast.stmt,
    source_memento: dict[str, Any],
) -> bool:
    compile_var = _string_field(source_memento, "regex_compile_var")
    return (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and (not compile_var or stmt.targets[0].id == compile_var)
        and isinstance(stmt.value, ast.Call)
        and _static_call_name(stmt.value.func) in {"re.compile", "compile"}
    )


def _is_return_regex_stmt(stmt: ast.stmt) -> bool:
    return _regex_expr_from_return_stmt(stmt, {}) is not None


def _regex_expr_from_return_stmt(
    stmt: ast.stmt,
    source_memento: dict[str, Any],
) -> Optional[ast.expr]:
    if not isinstance(stmt, ast.Return) or stmt.value is None:
        return None
    return _regex_fullmatch_expr_from_return_expr(stmt.value, source_memento)


def _regex_source_node_is_emitted(
    stmt: ast.stmt,
    node: ast.AST,
    regex_call: ast.Call,
) -> bool:
    if node is stmt:
        return True
    if _ast_contains_node(node, regex_call):
        return True
    return _ast_contains_node(regex_call, node)


def _regex_fullmatch_expr_from_return_expr(
    node: ast.expr,
    source_memento: dict[str, Any],
) -> Optional[ast.expr]:
    if (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and len(node.comparators) == 1
        and isinstance(node.ops[0], (ast.IsNot, ast.NotEq))
    ):
        if (
            isinstance(node.left, ast.Call)
            and _is_none_literal_node(node.comparators[0])
            and _regex_call_matches_source_memento(node.left, source_memento)
        ):
            return node
        if (
            isinstance(node.comparators[0], ast.Call)
            and _is_none_literal_node(node.left)
            and _regex_call_matches_source_memento(node.comparators[0], source_memento)
        ):
            return node
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "bool"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Call)
        and _regex_call_matches_source_memento(node.args[0], source_memento)
    ):
        return node
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            expr = _regex_fullmatch_expr_from_return_expr(value, source_memento)
            if expr is not None:
                return expr
    return None


def _regex_call_matches_source_memento(
    call: ast.Call,
    source_memento: dict[str, Any],
) -> bool:
    match_kind = _string_field(source_memento, "regex_match_kind")
    compile_var = _string_field(source_memento, "regex_compile_var")
    if isinstance(call.func, ast.Attribute):
        if match_kind and call.func.attr != match_kind:
            return False
        if compile_var:
            receiver = call.func.value
            if isinstance(receiver, ast.Name):
                return receiver.id == compile_var
            return (
                isinstance(receiver, ast.Attribute)
                and receiver.attr == compile_var
            )
        return call.func.attr in {"fullmatch", "match", "search"}
    static_name = _static_call_name(call.func)
    if match_kind:
        return static_name in {f"re.{match_kind}", match_kind}
    return static_name in {
        "re.fullmatch",
        "fullmatch",
        "re.match",
        "match",
        "re.search",
        "search",
    }


def _is_none_literal_node(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _classify_guard_source_node(
    stmt: ast.stmt,
    node: ast.AST,
    source_memento: dict[str, Any],
) -> Tuple[str, str]:
    if _is_docstring_stmt(stmt):
        return "support", "docstring metadata supports source accounting only"
    guard_lines = {
        int(line)
        for line in source_memento.get("guard_lines", [])
        if isinstance(line, int)
    }
    if getattr(stmt, "lineno", 0) in guard_lines and _is_guard_universe_stmt(stmt):
        return "warranted", "guard emitted into python.guard-universe"
    return "unclassified", "guard source not emitted"


def _is_guard_universe_stmt(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Assert):
        return True
    return (
        isinstance(stmt, ast.If)
        and len(stmt.body) == 1
        and isinstance(stmt.body[0], ast.Raise)
        and not stmt.orelse
    )


def _classify_exception_handler_raise_source_node(
    stmt: ast.stmt,
    node: ast.AST,
    source_memento: dict[str, Any],
) -> Tuple[str, str]:
    if _is_docstring_stmt(stmt):
        return "support", "docstring metadata supports source accounting only"
    if not isinstance(stmt, ast.Try):
        return "support", "non-selected path support for exception-handler accounting"
    raise_type = _string_field(source_memento, "exception_handler_raise_type")
    if isinstance(node, ast.Try):
        return "warranted", "try/except path emitted into python.exception-handler-raise-universe"
    if isinstance(node, ast.ExceptHandler):
        if _handler_raises_exception_type(node, raise_type):
            return "warranted", "exception handler emitted into python.exception-handler-raise-universe"
        return "support", "non-selected handler support for exception-handler accounting"
    if isinstance(node, ast.Raise):
        if _raise_node_exception_name(node) == raise_type:
            return "warranted", "raised exception emitted into python.exception-handler-raise-universe"
        return "support", "unrelated raise path supports exception-handler accounting"
    if _node_inside_handler_raise(stmt, node, raise_type):
        return "warranted", "raised exception expression emitted into python.exception-handler-raise-universe"
    return "support", "try body value path support for exception-handler accounting"


def _handler_raises_exception_type(handler: ast.ExceptHandler, raise_type: str) -> bool:
    return any(
        isinstance(child_stmt, ast.Raise)
        and _raise_node_exception_name(child_stmt) == raise_type
        for child_stmt in handler.body
    )


def _node_inside_handler_raise(stmt: ast.Try, node: ast.AST, raise_type: str) -> bool:
    for handler in stmt.handlers:
        for child_stmt in handler.body:
            if not isinstance(child_stmt, ast.Raise):
                continue
            if _raise_node_exception_name(child_stmt) != raise_type:
                continue
            if any(
                candidate is node
                for candidate, _ast_path in _iter_ast_nodes_with_paths(child_stmt, "$")
            ):
                return True
    return False


def _classify_exception_bool_return_source_node(
    stmt: ast.stmt,
    node: ast.AST,
    source_memento: dict[str, Any],
) -> Tuple[str, str]:
    if _is_docstring_stmt(stmt):
        return "support", "docstring metadata supports source accounting only"
    if not isinstance(stmt, ast.Try):
        return "support", "non-wrapper path support for exception-bool-return accounting"
    raise_type = _string_field(
        source_memento,
        "exception_bool_return_exception_type",
    )
    if isinstance(node, ast.Try):
        return "warranted", "try/except path emitted into python.exception-bool-return-universe"
    if isinstance(node, ast.ExceptHandler):
        if _exception_handler_catches_type(node, raise_type):
            return "warranted", "exception handler emitted into python.exception-bool-return-universe"
        return "support", "non-selected handler support for exception-bool-return accounting"
    if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
        if isinstance(node.value.value, bool):
            return "warranted", "boolean return emitted into python.exception-bool-return-universe"
    if _node_inside_try_body_call(stmt, node):
        return "warranted", "inner call emitted into python.exception-bool-return-universe"
    if _node_inside_exception_bool_return(stmt, node):
        return "warranted", "caught exception return path emitted into python.exception-bool-return-universe"
    return "support", "wrapper context support for exception-bool-return accounting"


def _exception_handler_catches_type(handler: ast.ExceptHandler, raise_type: str) -> bool:
    typ = handler.type
    if isinstance(typ, ast.Name):
        return typ.id == raise_type
    if isinstance(typ, ast.Attribute):
        return typ.attr == raise_type
    return False


def _node_inside_try_body_call(stmt: ast.Try, node: ast.AST) -> bool:
    if not stmt.body:
        return False
    first = stmt.body[0]
    if not isinstance(first, ast.Expr) or not isinstance(first.value, ast.Call):
        return False
    return any(
        candidate is node
        for candidate, _ast_path in _iter_ast_nodes_with_paths(first.value, "$")
    )


def _node_inside_exception_bool_return(stmt: ast.Try, node: ast.AST) -> bool:
    for handler in stmt.handlers:
        for child_stmt in handler.body:
            if (
                not isinstance(child_stmt, ast.Return)
                or not isinstance(child_stmt.value, ast.Constant)
                or not isinstance(child_stmt.value.value, bool)
            ):
                continue
            if any(
                candidate is node
                for candidate, _ast_path in _iter_ast_nodes_with_paths(child_stmt, "$")
            ):
                return True
    return False


def _classify_separator_guard_raise_source_node(
    stmt: ast.stmt,
    node: ast.AST,
    source_memento: dict[str, Any],
) -> Tuple[str, str]:
    if _is_docstring_stmt(stmt):
        return "support", "docstring metadata supports source accounting only"
    adapter_line = _int_field(source_memento, "separator_guard_adapter_line", 0)
    guard_line = _int_field(source_memento, "separator_guard_line", 0)
    if adapter_line and getattr(stmt, "lineno", 0) == adapter_line:
        return (
            "warranted",
            "parameter normalization emitted into python.separator-guard-raise-universe",
        )
    if isinstance(stmt, ast.If) and getattr(stmt, "lineno", 0) == guard_line:
        return (
            "warranted",
            "membership guard raise emitted into python.separator-guard-raise-universe",
        )
    if getattr(node, "lineno", 0) in {adapter_line, guard_line}:
        return (
            "warranted",
            "membership guard expression emitted into python.separator-guard-raise-universe",
        )
    return "support", "non-selected path support for separator-guard accounting"


def _raise_node_exception_name(node: ast.Raise) -> Optional[str]:
    exc = node.exc
    if exc is None:
        return None
    if isinstance(exc, ast.Call):
        exc = exc.func
    if isinstance(exc, ast.Name):
        return exc.id
    if isinstance(exc, ast.Attribute):
        return exc.attr
    return None


def _classify_branch_selected_source_node(
    stmt: ast.stmt,
    node: ast.AST,
    source_memento: dict[str, Any],
) -> Tuple[str, str]:
    if _is_docstring_stmt(stmt):
        return "support", "docstring metadata supports source accounting only"
    if isinstance(node, ast.If):
        field_name = _string_field(source_memento, "branch_field_name")
        field_value = source_memento.get("branch_field_value")
        if _branch_selected_if_matches(node, field_name, field_value):
            return "warranted", "emitted into python.branch-selected-universe"
        if _branch_adapter_prelude_if_matches(node, source_memento):
            return "warranted", "argument normalization emitted into python.branch-selected-universe"
        return "inactive", "non-selected branch inactive for this callsite relation"
    if isinstance(node, ast.Assign):
        if _branch_adapter_assign_matches(node, source_memento):
            return "warranted", "argument normalization emitted into python.branch-selected-universe"
        return "inactive", "default argument branch inactive for this callsite relation"
    if isinstance(node, ast.Return):
        return_param = _string_field(source_memento, "branch_return_param_name")
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == return_param
        ):
            return "warranted", "emitted into python.branch-selected-universe"
        return "inactive", "non-selected return inactive for this callsite relation"
    if isinstance(node, ast.Raise):
        return "inactive", "raise path inactive for selected branch relation"
    if isinstance(stmt, ast.If):
        return "support", "branch condition/source support for selected relation"
    if isinstance(stmt, ast.Raise):
        return "inactive", "raise path inactive for selected branch relation"
    return "support", "non-constraint source support for branch-selected accounting"


def _branch_adapter_prelude_if_matches(
    node: ast.If,
    source_memento: dict[str, Any],
) -> bool:
    return_param = _string_field(source_memento, "branch_return_param_name")
    if not return_param:
        return False
    if _param_none_check(node.test) != return_param and _param_not_none_check(node.test) != return_param:
        return False
    return any(
        isinstance(stmt, ast.Assign)
        and _branch_adapter_assign_matches(stmt, source_memento)
        for stmt in [*node.body, *node.orelse]
    )


def _branch_adapter_assign_matches(
    node: ast.Assign,
    source_memento: dict[str, Any],
) -> bool:
    return_param = _string_field(source_memento, "branch_return_param_name")
    adapter_callee = _string_field(source_memento, "branch_return_adapter_callee")
    if not return_param or not adapter_callee:
        return False
    adapter_name = adapter_callee.rsplit(".", 1)[-1]
    return (
        len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == return_param
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == adapter_name
        and not node.value.keywords
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id == return_param
    )


def _branch_selected_if_matches(
    node: ast.If,
    field_name: str,
    field_value: Any,
) -> bool:
    test = node.test
    if (
        not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.Eq)
        or len(test.comparators) != 1
    ):
        return False
    left = _self_field_name_for_accounting(test.left)
    right = _literal_for_accounting(test.comparators[0])
    if left == field_name and right == field_value:
        return True
    right_field = _self_field_name_for_accounting(test.comparators[0])
    left_lit = _literal_for_accounting(test.left)
    return right_field == field_name and left_lit == field_value


def _classify_branch_selected_raise_source_node(
    stmt: ast.stmt,
    node: ast.AST,
    source_memento: dict[str, Any],
) -> Tuple[str, str]:
    if _is_docstring_stmt(stmt):
        return "support", "docstring metadata supports source accounting only"
    param_name = _string_field(source_memento, "branch_param_name")
    excluded_value = source_memento.get("branch_excluded_value")
    raise_type = _string_field(source_memento, "branch_raise_exception_type")
    if isinstance(stmt, ast.If) and _branch_selected_raise_if_matches(
        stmt,
        param_name,
        excluded_value,
    ):
        if node is stmt or _ast_contains_node(stmt.test, node):
            return (
                "warranted",
                "branch guard emitted into python.branch-selected-raise-universe",
            )
        return "inactive", "return branch inactive for selected raise relation"
    if isinstance(stmt, ast.Raise):
        if (
            _raise_node_exception_name(stmt) == raise_type
            and _ast_contains_node(stmt, node)
        ):
            return (
                "warranted",
                "raised exception emitted into python.branch-selected-raise-universe",
            )
        return (
            "support",
            "unrelated raise path supports branch-selected raise accounting",
        )
    return (
        "support",
        "non-constraint source support for branch-selected raise accounting",
    )


def _branch_selected_raise_if_matches(
    node: ast.If,
    param_name: str,
    excluded_value: Any,
) -> bool:
    test = node.test
    if (
        not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.Eq)
        or len(test.comparators) != 1
    ):
        return False
    if (
        isinstance(test.left, ast.Name)
        and test.left.id == param_name
        and _literal_for_accounting(test.comparators[0]) == excluded_value
    ):
        return True
    return (
        isinstance(test.comparators[0], ast.Name)
        and test.comparators[0].id == param_name
        and _literal_for_accounting(test.left) == excluded_value
    )


def _ast_contains_node(root: ast.AST, node: ast.AST) -> bool:
    return any(
        candidate is node
        for candidate, _ast_path in _iter_ast_nodes_with_paths(root, "$")
    )


def _self_field_name_for_accounting(node: ast.AST) -> Optional[str]:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"self", "cls"}
    ):
        return node.attr
    return None


def _literal_for_accounting(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _constructor_default_param_names(source_memento: dict[str, Any]) -> Set[str]:
    raw = source_memento.get("constructor_default_param_names")
    if not isinstance(raw, list):
        return set()
    return {value for value in raw if isinstance(value, str)}


def _classify_translate_source_statement(stmt: ast.stmt) -> Tuple[str, str]:
    if _is_docstring_stmt(stmt):
        return "support", "docstring metadata supports source accounting only"
    if _is_translate_return(stmt):
        return "warranted", "emitted into python.translate-universe"
    if _is_rstrip_return(stmt):
        return "warranted", "emitted into python no-suffix-chars universe"
    if _is_lstrip_return(stmt):
        return "warranted", "emitted into python no-prefix-chars universe"
    return "support", "prelude/context support for translate-universe accounting"


def _is_docstring_stmt(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _is_translate_return(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Return):
        return False
    value = stmt.value
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "translate"
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
    )


def _is_rstrip_return(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Return):
        return False
    value = stmt.value
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "rstrip"
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, (bytes, str))
    )


def _is_lstrip_return(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Return):
        return False
    value = stmt.value
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "lstrip"
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, (bytes, str))
    )


def _is_instance_field_assign(stmt: ast.stmt) -> bool:
    return _instance_field_assign_param(stmt) is not None


def _instance_field_assign_param(stmt: ast.stmt) -> Optional[str]:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return None
        target = stmt.targets[0]
        value = stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        value = stmt.value
    else:
        return None
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
        and isinstance(value, ast.Name)
    ):
        return value.id
    return None


def _is_instance_field_adapter_assign(stmt: ast.stmt, adapter_callee: str) -> bool:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return False
        target = stmt.targets[0]
        value = stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        value = stmt.value
    else:
        return False
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
        and isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == adapter_callee.rsplit(".", 1)[-1]
        and not value.keywords
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
    )


def _is_instance_field_helper_assign(stmt: ast.stmt, helper_callee: str) -> bool:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return False
        target = stmt.targets[0]
        value = stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        value = stmt.value
    else:
        return False
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
        and isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == helper_callee.rsplit(".", 1)[-1]
        and not value.keywords
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
    )


def _is_instance_field_call_assign(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return False
        target = stmt.targets[0]
        value = stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        value = stmt.value
    else:
        return False
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
        and isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
    )


def _is_instance_field_bool_or_default_assign(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return False
        target = stmt.targets[0]
        value = stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        value = stmt.value
    else:
        return False
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
        and isinstance(value, ast.BoolOp)
        and isinstance(value.op, ast.Or)
        and len(value.values) == 2
        and isinstance(value.values[0], ast.Name)
        and (
            _literal_value_kind_for_accounting(value.values[1]) is not None
            or isinstance(value.values[1], (ast.Dict, ast.List, ast.Tuple, ast.Set))
        )
    )


def _is_list_adapter_active_if(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.If) or stmt.orelse or len(stmt.body) != 1:
        return False
    if not isinstance(stmt.body[0], ast.Return):
        return False
    value = stmt.body[0].value
    return (
        isinstance(value, ast.List)
        and len(value.elts) == 1
        and isinstance(value.elts[0], ast.Call)
    )


def _is_list_adapter_iterable_return(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Return)
        and isinstance(stmt.value, ast.ListComp)
        and len(stmt.value.generators) == 1
    )


def _static_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _static_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _is_transparent_typing_cast_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and not node.keywords
        and len(node.args) == 2
        and _static_call_name(node.func) in {"t.cast", "typing.cast"}
    )


def _is_instance_field_default_if(stmt: ast.stmt) -> bool:
    return _instance_field_default_if_param(stmt) is not None


def _instance_field_default_if_param(stmt: ast.stmt) -> Optional[str]:
    if not isinstance(stmt, ast.If) or stmt.orelse or len(stmt.body) != 1:
        return None
    param_name = _param_none_check(stmt.test)
    if param_name is None:
        return None
    body_stmt = stmt.body[0]
    if not isinstance(body_stmt, ast.Assign) or len(body_stmt.targets) != 1:
        return None
    target = body_stmt.targets[0]
    value = body_stmt.value
    if (
        isinstance(target, ast.Name)
        and target.id == param_name
        and isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "self"
    ):
        return param_name
    return None


def _is_instance_field_validation_guard(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.If)
        and not stmt.orelse
        and len(stmt.body) == 1
        and isinstance(stmt.body[0], ast.Raise)
    )


def _instance_field_normalized_param(stmt: ast.stmt) -> Optional[str]:
    if not isinstance(stmt, ast.If) or len(stmt.body) != 1 or len(stmt.orelse) > 1:
        return None
    param_name = _param_not_none_check(stmt.test)
    if param_name is None:
        param_name = _param_none_check(stmt.test)
    if param_name is None:
        return None
    if not _is_name_rebind(stmt.body[0], param_name):
        return None
    if stmt.orelse and not _is_name_rebind(stmt.orelse[0], param_name):
        return None
    return param_name


def _param_none_check(node: ast.expr) -> Optional[str]:
    if (
        not isinstance(node, ast.Compare)
        or len(node.ops) != 1
        or not isinstance(node.ops[0], ast.Is)
        or len(node.comparators) != 1
    ):
        return None
    left = node.left
    right = node.comparators[0]
    if (
        isinstance(left, ast.Name)
        and isinstance(right, ast.Constant)
        and right.value is None
    ):
        return left.id
    if (
        isinstance(right, ast.Name)
        and isinstance(left, ast.Constant)
        and left.value is None
    ):
        return right.id
    return None


def _param_not_none_check(node: ast.expr) -> Optional[str]:
    if (
        not isinstance(node, ast.Compare)
        or len(node.ops) != 1
        or not isinstance(node.ops[0], ast.IsNot)
        or len(node.comparators) != 1
    ):
        return None
    left = node.left
    right = node.comparators[0]
    if (
        isinstance(left, ast.Name)
        and isinstance(right, ast.Constant)
        and right.value is None
    ):
        return left.id
    if (
        isinstance(right, ast.Name)
        and isinstance(left, ast.Constant)
        and left.value is None
    ):
        return right.id
    return None


def _is_name_rebind(stmt: ast.stmt, name: str) -> bool:
    return (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and stmt.targets[0].id == name
    )


def _is_param_none_check(node: ast.expr) -> bool:
    if (
        not isinstance(node, ast.Compare)
        or len(node.ops) != 1
        or not isinstance(node.ops[0], ast.Is)
        or len(node.comparators) != 1
    ):
        return False
    left = node.left
    right = node.comparators[0]
    return (
        isinstance(left, ast.Name)
        and isinstance(right, ast.Constant)
        and right.value is None
    ) or (
        isinstance(right, ast.Name)
        and isinstance(left, ast.Constant)
        and left.value is None
    )


def _is_instance_field_return(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Return):
        return False
    value = stmt.value
    if (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "self"
    ):
        return True
    return (
        isinstance(value, ast.Subscript)
        and isinstance(value.value, ast.Attribute)
        and isinstance(value.value.value, ast.Name)
        and value.value.value.id == "self"
        and _constant_int_index(value.slice) is not None
    )


def _constant_int_index(node: ast.AST) -> Optional[int]:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return int(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) is int
    ):
        return -int(node.operand.value)
    return None


def _is_super_init_expr(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return False
    call = stmt.value
    if call.keywords:
        return False
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "__init__"
        and isinstance(func.value, ast.Call)
        and isinstance(func.value.func, ast.Name)
        and func.value.func.id == "super"
        and not func.value.args
        and not func.value.keywords
    )


def _is_constant_return(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Return) or stmt.value is None:
        return False
    return _literal_value_kind_for_accounting(stmt.value) is not None


def _is_return_isinstance_stmt(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Return):
        return False
    value = stmt.value
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "isinstance"
        and len(value.args) == 2
        and not value.keywords
    )


def _literal_value_kind_for_accounting(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, str):
            return "str"
        if isinstance(value, bytes):
            return "bytes"
        if value is None:
            return "none"
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) is int
    ):
        return "int"
    return None


def _source_totals(loci: List[dict[str, Any]]) -> dict[str, int]:
    totals = _empty_source_ledger()
    totals["source_loci"] = len(loci)
    for locus in loci:
        status = locus.get("status")
        if status == "warranted":
            totals["source_warranted"] += 1
        elif status == "support":
            totals["source_support"] += 1
        elif status == "refused":
            totals["source_refused"] += 1
        elif status == "inactive":
            totals["source_inactive"] += 1
        elif status == "refuted":
            totals["source_refuted"] += 1
        else:
            totals["unclassified_source"] += 1
    return totals


def _source_memento_lines(memento: dict[str, Any]) -> range:
    span = memento.get("span") if isinstance(memento.get("span"), dict) else {}
    start = _int_field(span, "start_line", 0)
    end = _int_field(span, "end_line", start)
    if start <= 0:
        return range(0, 1)
    if end < start:
        end = start
    return range(start, end + 1)


def _source_memento_start_line(memento: dict[str, Any]) -> int:
    span = memento.get("span") if isinstance(memento.get("span"), dict) else {}
    return _int_field(span, "start_line", 0)


def _string_field(obj: dict[str, Any], field_name: str) -> str:
    value = obj.get(field_name)
    return value if isinstance(value, str) else ""


def _int_field(obj: dict[str, Any], field_name: str, default: int) -> int:
    value = obj.get(field_name)
    return value if isinstance(value, int) else default


# ---------------------------------------------------------------------------
# Test-function recognition
# ---------------------------------------------------------------------------


def _iter_test_functions(tree: ast.AST):
    """Yield (FunctionDef, class_name_or_None) pairs for test functions:
    free function ``test_*`` OR method ``test_*`` on a class.

    Class name is the enclosing class so the caller can qualify the decl
    name as ``ClassName::test_method`` and keep each class-method's
    scope isolated from same-named methods in other classes.
    Methods inside a class carry ``self`` (or ``cls``) as their first
    arg which ``_strip_self`` strips before classification.
    """
    # Build a mapping from function-node id -> enclosing class name.
    # ast.walk yields nodes in no particular order, so we do a targeted
    # traversal of top-level and nested statements to find ClassDef bodies.
    class_of: Dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    class_of[id(child)] = node.name

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                yield node, class_of.get(id(node))


def _collect_helpers(tree: ast.AST) -> Dict[str, _HelperDef]:
    """Find module-level (and class-level) functions whose body is exactly
    one liftable assertion and that take one typed parameter.
    """
    out: Dict[str, _HelperDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("test"):
            continue
        helper = _helper_def_from_fn(node)
        if helper is not None:
            out[node.name] = helper
    return out


def _helper_def_from_fn(fn: ast.FunctionDef) -> Optional[_HelperDef]:
    args = fn.args
    # No *args / **kwargs / kw-only / pos-only.
    if args.vararg is not None or args.kwarg is not None:
        return None
    if args.kwonlyargs or args.kw_defaults:
        return None
    if args.defaults:
        return None
    positional = list(args.posonlyargs) + list(args.args)
    # Skip ``self`` for method helpers.
    if positional and positional[0].arg == "self":
        positional = positional[1:]
    if len(positional) != 1:
        return None
    arg = positional[0]
    if arg.annotation is None:
        # Mirrors Rust's FnArg::Typed requirement.
        return None
    body = fn.body
    if len(body) != 1:
        return None
    stmt = body[0]
    if not _is_assertion_stmt(stmt):
        return None
    return _HelperDef(param_name=arg.arg, assertion=stmt)


# ---------------------------------------------------------------------------
# Pattern classifier
# ---------------------------------------------------------------------------


def _strip_self(stmts: Sequence[ast.stmt], fn: ast.FunctionDef) -> List[ast.stmt]:
    """unittest TestCase methods carry ``self`` as their first arg. The
    body is unchanged, but we filter out docstring expression statements
    so they don't break the "every stmt is an assert" rule.
    """
    out: List[ast.stmt] = []
    for i, s in enumerate(stmts):
        # Drop a docstring at index 0.
        if (
            i == 0
            and isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Constant)
            and isinstance(s.value.value, str)
        ):
            continue
        out.append(s)
    return out


def _classify_and_lift(
    fn: ast.FunctionDef,
    source_path: str,
    source: str,
    helpers: Dict[str, _HelperDef],
    out: Layer2Output,
    class_name: Optional[str] = None,
) -> None:
    # Qualify the test name with the enclosing class so that same-named
    # methods in different classes produce independent decl scopes.
    # ``TestFoo::test_bar`` is distinct from ``TestBaz::test_bar`` even
    # though both have ``fn.name == "test_bar"``.  Free functions keep
    # their bare name.
    test_name = f"{class_name}::{fn.name}" if class_name else fn.name
    body = _strip_self(fn.body, fn)

    # PATTERN 4: parametrize decorator is the strongest claim. If a
    # ``@pytest.mark.parametrize`` decorator is present with a literal
    # arg list, claim regardless of body shape (we may still skip lift
    # if the body isn't a single liftable assert OR rows are non-literal).
    presence = _find_parametrize(fn)
    if presence is not None:
        if presence.mark is None:
            out.claimed_tests.add(test_name)
            out.seen += 1
            out.parametrize_skipped += 1
            out.warnings.append(
                LiftWarning(source_path, test_name, f"layer2 {presence.reason}")
            )
            return
        _classify_parametrize(fn, body, presence.mark, test_name, source_path, out)
        return

    # PATTERN 1: single bounded for-loop with single-stmt body.
    if len(body) == 1 and isinstance(body[0], ast.For):
        _classify_for_loop(body[0], test_name, source_path, out)
        return

    # PATTERN 2: every top-level stmt is a single-arg call to a known helper.
    helper_calls = _collect_helper_calls(body, helpers)
    if helper_calls is not None and helper_calls:
        _classify_helper_inlining(helper_calls, helpers, test_name, source_path, out)
        return

    # PATTERN 3: every stmt is an assertion AND there are >= 2. A single
    # constructor operator dispatch is also admitted because routing it through
    # value-scope would treat the constructor operands as call-result EUF
    # subjects and mint vacuous callresult facts instead of the source equality.
    asserts: List[ast.stmt] = []
    all_asserts = bool(body)
    for stmt in body:
        if _is_assertion_stmt(stmt):
            asserts.append(stmt)
        else:
            all_asserts = False
            break
    if all_asserts and (
        len(asserts) >= 2
        or (len(asserts) == 1 and _single_assertion_is_operator_dispatch(asserts[0]))
    ):
        _classify_characterization(
            asserts,
            test_name,
            source_path,
            out,
            allow_single_operator_dispatch=len(asserts) == 1,
        )
        return

    if _classify_value_scope(fn, body, test_name, source_path, source, out):
        return

    # PATTERN 7: pytest.raises blocks — must fire before mixed-body so any
    # With-bearing body is claimed (either lifted or loudly refused) rather
    # than falling through to Layer 0 silently.
    if _classify_raises_body(body, test_name, source_path, out):
        return

    if _classify_mixed_body(body, test_name, source_path, out):
        return

    # PATTERN 1c: mixed body with a terminal For[literal-iter, assert-only-body].
    # Must fire BEFORE the catch-all so nested asserts in an embedded literal-iter
    # For are lifted (or loudly refused with a useful message) rather than hitting
    # the generic catch-all.
    if _classify_embedded_for(body, test_name, source_path, out):
        return

    # PATTERN 8: if-guarded assertions — `if cond: assert P` lifts as implies(cond,P).
    # Must fire BEFORE the catch-all so nested asserts inside if-bodies are claimed.
    if _classify_if_guarded(body, test_name, source_path, out):
        return

    # PATTERN 9: with-body assertions — `with <non-suppressing-CM>: assert P`.
    # Must fire BEFORE the catch-all so nested asserts inside with-bodies are claimed.
    if _classify_with_body(body, test_name, source_path, out):
        return

    unsupported_unittest_asserts = _unsupported_unittest_assertions(body)
    if unsupported_unittest_asserts:
        out.claimed_tests.add(test_name)
        out.seen += 1
        for name in unsupported_unittest_asserts:
            out.warnings.append(
                LiftWarning(
                    source_path,
                    test_name,
                    f"layer2 unittest lift-gap: unsupported assertion method `{name}`",
                )
            )
        return

    # FIX 2a — LOUD-REFUSE CATCH-ALL (Δ=0 coverage):
    # If the test body contains ANY assert statement but no pattern above claimed
    # it, the assert is SILENTLY dropped — a Δ>0 gap.  Common cases:
    #   - asserts nested inside a for/with/if body (has_assert/has_binding
    #     pre-screen in _classify_mixed_body only checks TOP-LEVEL stmts)
    #   - FunctionDef+assert inside the test body
    #   - single assert with no binding and no qualifying condition for P3
    #
    # Rather than silently leaving these for Layer 0 (which produces ZERO
    # contracts with ZERO warnings), we CLAIM the test and emit a LOUD warning
    # naming the construct.  Zero contracts are produced — this is a valid
    # loudly-refused outcome and satisfies per-lifter Δ=0.
    has_any_assert = any(isinstance(s, ast.Assert) for s in ast.walk(fn))
    if has_any_assert:
        out.claimed_tests.add(test_name)
        out.seen += 1
        # Find the first construct that caused the fall-through.
        reasons: List[str] = []
        for s in fn.body:
            if isinstance(s, (ast.For, ast.While, ast.With, ast.If)):
                nested_asserts = [n for n in ast.walk(s) if isinstance(n, ast.Assert)]
                if nested_asserts:
                    kind = type(s).__name__
                    reasons.append(
                        f"asserts nested in {kind.lower()}-body not lifted "
                        f"(construct: {_unparse(s)[:60]})"
                    )
            elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nested_asserts = [n for n in ast.walk(s) if isinstance(n, ast.Assert)]
                if nested_asserts:
                    reasons.append(
                        f"asserts nested in inner FunctionDef `{s.name}` not lifted"
                    )
        if not reasons:
            # Single assert, no binding, and no call-result scope — residual case.
            reasons.append("single assert with no recognized binding or call-result scope; not lifted in v0")
        for reason in reasons:
            out.warnings.append(
                LiftWarning(
                    source_path,
                    test_name,
                    f"layer2 loud-refuse: assert present but pattern unclaimed — {reason}",
                )
            )
        return

    # No Layer 2 pattern claimed it. Leave for Layer 0.


# ---------------------------------------------------------------------------
# Assertion-statement recognition (Python flavor)
# ---------------------------------------------------------------------------


_UNITTEST_BINARY_PREDICATES = {
    "assertEqual": "=",
    "assertEquals": "=",
    "assertNotEqual": "≠",
    "assertGreater": ">",
    "assertGreaterEqual": "≥",
    "assertLess": "<",
    "assertLessEqual": "≤",
}

_UNITTEST_IDENTITY_PREDICATES = {
    "assertIs": "=",
    "assertIsNot": "≠",
}

_UNITTEST_NONE_PREDICATES = {
    "assertIsNone": "=",
    "assertIsNotNone": "≠",
}

_UNITTEST_TRUTH_PREDICATES = {"assertTrue", "assertFalse"}


def _is_assertion_stmt(stmt: ast.stmt) -> bool:
    """Return True iff ``stmt`` looks like a liftable assertion in either
    pytest (``assert <comp>``) or unittest (``self.assertX(...)``) form.
    Liftability is checked here only at the surface; ``_lift_assertion_stmt``
    does the actual term/formula construction and may still error.
    """
    if isinstance(stmt, ast.Assert):
        return True
    if isinstance(stmt, ast.Expr):
        call = stmt.value
        if isinstance(call, ast.Call):
            name = _attr_method_name(call.func)
            if name is not None and name in _UNITTEST_BINARY_PREDICATES:
                return True
            if name is not None and name in _UNITTEST_IDENTITY_PREDICATES:
                return True
            if name is not None and name in _UNITTEST_NONE_PREDICATES:
                return True
            if name in _UNITTEST_TRUTH_PREDICATES:
                return True
    return False


def _attr_method_name(func: ast.expr) -> Optional[str]:
    """``self.assertEqual`` -> ``"assertEqual"``. Returns None if shape
    doesn't fit ``self.<name>``.
    """
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _unsupported_unittest_assertions(stmts: Sequence[ast.stmt]) -> List[str]:
    out: List[str] = []
    for stmt in stmts:
        if not isinstance(stmt, ast.Expr):
            continue
        call = stmt.value
        if not isinstance(call, ast.Call):
            continue
        name = _attr_method_name(call.func)
        if name is None:
            continue
        if not name.startswith("assert"):
            continue
        if (
            name in _UNITTEST_BINARY_PREDICATES
            or name in _UNITTEST_IDENTITY_PREDICATES
            or name in _UNITTEST_NONE_PREDICATES
            or name in _UNITTEST_TRUTH_PREDICATES
        ):
            continue
        out.append(name)
    return out


# ---------------------------------------------------------------------------
# Term and formula translation
# ---------------------------------------------------------------------------


def _dotted_attr_path(node: ast.expr) -> Optional[str]:
    """Extract the dotted path from an attribute-access chain.

    ``out.bounded_loop_lifted`` -> ``"out.bounded_loop_lifted"``.
    ``a.b.c`` -> ``"a.b.c"``.
    Returns None if the base is not a simple Name (e.g. ``f().attr``).
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_attr_path(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _ssa_dotted_attr_path(node: ast.Attribute, scope: "_ValueScope") -> Optional[str]:
    """Build a dotted attribute path whose base is SSA-keyed.

    Walks the attribute chain to find the leftmost Name base.  If that
    base is tracked in ``scope.current`` (i.e. it is an SSA-renamed
    local variable), replace it with its SSA name and return the
    reassembled path.  Otherwise return None so the caller falls back
    to the unscoped (raw) dotted path.

    Examples with ``scope.current = {"out": make_var("out$1")}``:
      ``out.val``   -> ``"out$1.val"``
      ``out.a.b``   -> ``"out$1.a.b"``
      ``other.val`` -> None  (``other`` not in scope)
    """
    raw = _dotted_attr_path(node)
    if raw is None:
        return None
    # Find the leftmost Name segment (root of the dotted chain).
    root: ast.expr = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return None
    root_name = root.id
    if root_name not in scope.current:
        return None
    ssa_term = scope.current[root_name]
    # Extract the SSA var name from the Term (always a _Var here).
    from .ir import _Var as _IrVar
    if not isinstance(ssa_term, _IrVar):
        return None
    ssa_base = ssa_term.name
    # Replace the root segment with its SSA name.  The raw path starts
    # with root_name; everything after the root is the suffix.
    suffix = raw[len(root_name):]   # e.g. ".val" or ".a.b" or ""
    return f"{ssa_base}{suffix}"


def _subscript_key_term(key_node: ast.expr) -> Term:
    """Translate a subscript key to a Term, for use in the ``subscript`` Ctor.

    ONLY literal keys are supported: string, integer, bool, None.  A
    non-literal / computed key (``parsed[i]``, ``parsed[CONST]``) raises
    ValueError with an explicit message — these must LOUDLY REFUSE because
    we cannot soundly establish that two subscript expressions refer to the
    same slot without knowing the key's value.

    Design: literal string keys produce ``str_const(s)`` (encoded as
    ``strlit_<hash>`` in SMT, sort-safe Int constant).  Integer and bool keys
    produce ``num``/``bool_const`` concrete Int values.  None produces the
    ``None`` nullary ctor.  All of these reuse the existing literal-encoding
    machinery, so cross-type distinctness axioms are emitted correctly.
    """
    if isinstance(key_node, ast.Constant):
        v = key_node.value
        if isinstance(v, bool):
            return bool_const(v)
        if isinstance(v, int):
            return num(v)
        if isinstance(v, str):
            return str_const(v)
        if v is None:
            return ctor("None", [])
        raise ValueError(
            f"subscript-index: non-literal key type {type(v)!r} is not liftable"
        )
    if isinstance(key_node, ast.UnaryOp) and isinstance(key_node.op, ast.USub):
        if (
            isinstance(key_node.operand, ast.Constant)
            and isinstance(key_node.operand.value, int)
            and not isinstance(key_node.operand.value, bool)
        ):
            return num(-key_node.operand.value)
    # Non-literal key: LOUD REFUSE.  We cannot establish slot identity.
    raise ValueError(
        "subscript-index: non-literal key (computed key or variable) is not "
        "soundly liftable — cannot establish that two subscript expressions "
        "refer to the same slot without knowing the key value at lift time"
    )


def _translate_subscript_term(node: ast.Subscript, base_term: Term) -> Term:
    """Build ``ctor('subscript', [base_term, key_term])`` for a subscript node.

    The ``subscript`` Ctor is an uninterpreted 2-arg function in SMT.
    Sound because:
      - same base + same key  -> same Ctor term -> same-subject contradictions fire UNSAT
      - different key or base -> distinct Ctor terms -> independent facts
      - attribute ``obj.attr`` and subscript ``obj['attr']`` NEVER share a term
        (attribute uses a raw Var; subscript uses a Ctor) — no accidental aliasing.

    Non-literal keys raise ValueError (LOUD REFUSE); see ``_subscript_key_term``.
    """
    key_term = _subscript_key_term(node.slice)
    return _subscript_term_or_projection(base_term, key_term)


def _subscript_term_or_projection(base_term: Term, key_term: Term) -> Term:
    projected = _static_subscript_projection(base_term, key_term)
    if projected is not None:
        return projected
    return ctor("subscript", [base_term, key_term])


def _static_subscript_projection(base_term: Term, key_term: Term) -> Optional[Term]:
    from .ir import _ConstInt

    if isinstance(base_term, _Ctor) and base_term.name in {"python:list", "python:tuple"}:
        if not isinstance(key_term, _ConstInt):
            return None
        try:
            return base_term.args[key_term.value]
        except IndexError:
            return None
    if isinstance(base_term, _Ctor) and base_term.name.startswith("python:dict_a"):
        for entry in reversed(base_term.args):
            if (
                isinstance(entry, _Ctor)
                and entry.name == "python:dict-entry_a2"
                and len(entry.args) == 2
                and entry.args[0] == key_term
            ):
                return entry.args[1]
    return None


def _static_container_projection_map_from_expr(
    node: ast.expr,
    translate_element,
) -> Optional[Dict[Term, Term]]:
    try:
        if isinstance(node, (ast.List, ast.Tuple)):
            if any(isinstance(element, ast.Starred) for element in node.elts):
                return None
            elements = [translate_element(element) for element in node.elts]
            projections: Dict[Term, Term] = {}
            count = len(elements)
            for index, element in enumerate(elements):
                projections[num(index)] = element
                projections[num(index - count)] = element
            return projections or None
        if isinstance(node, ast.Dict):
            projections: Dict[Term, Term] = {}
            for key, value in zip(node.keys, node.values):
                if key is None:
                    return None
                projections[_subscript_key_term(key)] = translate_element(value)
            return projections or None
    except ValueError:
        return None
    return None


def _static_container_projection_from_expr(
    container: ast.expr,
    key: ast.expr,
    translate_element,
) -> Optional[Term]:
    try:
        key_term = _subscript_key_term(key)
    except ValueError:
        return None
    projections = _static_container_projection_map_from_expr(
        container,
        translate_element,
    )
    if projections is None:
        return None
    return projections.get(key_term)


def _callval_head(method: str, arity: int) -> str:
    """Build an ASCII-safe, arity-stable ctor name for a method-call-result term.

    Shape: ``callval_<method>_a<arity>`` where ``<method>`` has non-alphanumeric
    chars replaced by ``_``, and ``<arity>`` is the total number of ctor args
    (receiver is arg 0).

    Encoding arity in the name ensures that calls with different arities
    (``x.m()`` vs ``x.m(k)``) produce different ctor heads and therefore
    different SMT declarations, preventing ill-sorted ctor applications.
    """
    safe = "".join(c if (c.isascii() and c.isalnum()) else "_" for c in method)
    return f"callval_{safe}_a{arity}"


def _translate_dict_set_literal_term(node: ast.expr) -> Term:
    """Translate a collection literal (dict/set/tuple/list) to an opaque
    ``str_const`` keyed by its canonical content.

    SOUNDNESS RULE: two structurally-different literals MUST produce DISTINCT
    str_const values (different strings → different strlit_<hash> SMT consts →
    z3 can distinguish them → ``x == L1 ∧ x == L2`` with L1≠L2 is UNSAT →
    REFUSED).  Identical literals produce the SAME str_const → SAT → PROVEN.

    The canonical form lives in ONE place —
    translate_universe.collection_literal_canonical — shared with the
    vendor-side constant walk, so the universe equality and the consumer
    term are byte-identical by construction (a drifted mirror would make
    every collection universe vacuously disjoint).

    Content restriction (unchanged): every key/value/element must itself be
    a literal leaf (int / str / bool / None / unary-neg int).  Computed
    contents, unpacking, and nesting LOUDLY REFUSE via ValueError — content
    identity cannot be established without evaluating at lift time.
    """
    canonical = collection_literal_canonical(node)
    if canonical is None:
        raise ValueError(
            "collection literal contents must be literal leaves (int / str "
            "/ bool / None); computed values, unpacking, and nesting are "
            "not liftable — cannot establish content identity at lift time"
        )
    return str_const(canonical)


def _translate_str_bytes_sequence_literal_term(node: ast.expr, translate_element) -> Optional[Term]:
    if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
        return None
    elements: List[Term] = []
    for element_node in node.elts:
        if isinstance(element_node, ast.Starred):
            return None
        element = translate_element(element_node)
        if not _is_str_or_bytes_literal_term(element):
            return None
        elements.append(element)
    head = "python:list" if isinstance(node, ast.List) else "python:tuple"
    return ctor(head, elements)


def _literal_leaf_value(node: ast.expr):
    """Extract the Python value from a literal leaf node (int/str/bool/None).

    Raises ValueError for any non-literal or non-leaf node so the caller can
    produce a LOUD REFUSE (never a silent lift of a computed value).
    """
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, (int, str, bool)) or v is None:
            return v
        raise ValueError(
            f"dict/set literal leaf has unsupported constant type {type(v)!r}; "
            "only int / str / bool / None are liftable"
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, int) and not isinstance(node.operand.value, bool):
            return -node.operand.value
    raise ValueError(
        f"dict/set literal element is not a literal leaf ({type(node).__name__}); "
        "computed values are not liftable — cannot establish content identity at lift time"
    )


def _translate_term(node: ast.expr) -> Term:
    """Whitelist:
      - identifier (Var)
      - integer / string / bool literal
      - unary-neg of an integer literal
      - dict / set literal (opaque str_const keyed by canonical content)
      - function call with simple-Name func (Ctor with args)
      - method call ``recv.method(args)`` → ``ctor('callval_<method>_a<n>', [recv, args...])``
      - attribute access (Var named by dotted path, e.g. ``obj.attr``)
      - subscript-index with a literal key (``obj['key']``, ``obj[0]``)
    Everything else raises ValueError.
    """
    if isinstance(node, ast.Name):
        if node.id == "None":
            return ctor("None", [])
        if node.id == "True":
            return bool_const(True)
        if node.id == "False":
            return bool_const(False)
        return make_var(node.id)
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return bool_const(v)
        if isinstance(v, int):
            return num(v)
        if isinstance(v, str):
            return str_const(v)
        if v is None:
            return ctor("None", [])
        if isinstance(v, bytes):
            # ASCII-gated bytes: lifted as a python:bytes ctor wrapping the
            # decoded content. The wrapper keeps b"a" and "a" DISTINCT terms
            # (python == between them is kind-constant False); the substrate
            # unwraps the content for string-theory contact so equality rows
            # conjoin with charset universes. Non-ASCII refuses loudly: the
            # String-sorted encoding cannot carry it honestly.
            try:
                return ctor("python:bytes", [str_const(v.decode("ascii"))])
            except UnicodeDecodeError:
                raise ValueError(
                    "non-ASCII bytes literal is not liftable; the "
                    "String-sorted bytes encoding is ASCII-gated"
                ) from None
        raise ValueError(f"only int / str / bool / None literals are liftable; got {type(v)!r}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, int) and not isinstance(node.operand.value, bool):
            return num(-node.operand.value)
        raise ValueError("unary-neg only liftable on integer literals")
    if isinstance(node, (ast.Dict, ast.Set, ast.Tuple, ast.List)):
        structured = _translate_str_bytes_sequence_literal_term(node, _translate_term)
        if structured is not None:
            return structured
        # Dict/set literal: opaque str_const keyed by canonical content.
        # Non-literal contents → ValueError (LOUD REFUSE at call site).
        return _translate_dict_set_literal_term(node)
    if isinstance(node, ast.Call):
        # pytest.approx as a sub-term: LOUD REFUSE.  approx calls must be
        # intercepted at the comparison level (_lift_approx_comparison); if
        # they reach here they are in an unsupported position (e.g. nested
        # inside another call, or on a non-Eq/NotEq comparison side).
        # Silently lifting them as a ctor would create a term that looks like
        # a plain function call — ``x == approx(5); x == approx(99)`` would
        # become ``eq(x, ctor(approx,5)) ^ eq(x, ctor(approx,99))`` — UNSAT
        # — REFUSED — a falsePass on overlapping ranges.  Always refuse here.
        if _is_pytest_approx_call(node):
            raise ValueError(
                "approx: pytest.approx(...) in an unsupported position — "
                "approx is only liftable as the comparand of == or != "
                "(e.g. `assert x == pytest.approx(target)`); "
                "use it in a direct == or != comparison at the top level of an assert"
            )
        module_attr_callee = _module_attr_callee(node.func)
        if (
            module_attr_callee is not None
            and _is_constructor_call_name(module_attr_callee)
        ):
            if node.keywords:
                raise ValueError("qualified constructor call with kwargs is not liftable")
            return ctor(
                f"call:{module_attr_callee}",
                [_translate_term(arg) for arg in node.args],
            )
        if isinstance(node.func, ast.Attribute):
            # Method call: ``recv.method(args)`` → callval ctor.
            # LOUD REFUSE on keyword args: cannot order-stably translate.
            method = node.func.attr
            if node.keywords:
                raise ValueError(
                    f"method call `{method}` with keyword args is not liftable as a term "
                    "(keyword args cannot be order-stably translated without knowing "
                    "the function signature)"
                )
            recv_term = _translate_term(node.func.value)
            arg_terms = [recv_term]
            for i, arg in enumerate(node.args):
                try:
                    arg_terms.append(_translate_term(arg))
                except ValueError as e:
                    raise ValueError(
                        f"method call `{method}` arg[{i}] not liftable as term: {e}"
                    )
            head = _callval_head(method, len(arg_terms))
            return ctor(head, arg_terms)
        if not isinstance(node.func, ast.Name):
            raise ValueError("call target must be a simple name or method (recv.method)")
        if node.keywords:
            raise ValueError("call with kwargs is not liftable")
        if _is_constructor_call_name(node.func.id):
            return ctor(
                f"call:{node.func.id}",
                [_translate_term(arg) for arg in node.args],
            )
        if len(node.args) == 0:
            return ctor(node.func.id, [])
        if len(node.args) > 1:
            raise ValueError(f"call `{node.func.id}` with {len(node.args)} args is not liftable in v0 (single-arg only)")
        inner = _translate_term(node.args[0])
        return ctor(node.func.id, [inner])
    if isinstance(node, ast.Attribute):
        # Attribute access (``obj.attr``): lift as an opaque Var named by the
        # dotted path.  The subject ``obj`` must itself reduce to a simple Var
        # or attribute chain so the resulting dotted name is stable and unique.
        # Sound because: same dotted path -> same Var name -> same-term
        # contradictions fire UNSAT; different paths remain independent.
        # Restriction: no method calls (``obj.method()``); those must go
        # through the Call branch with an Attribute func.
        obj_name = _dotted_attr_path(node)
        if obj_name is None:
            raise ValueError(
                "attribute access on a non-name/non-attribute subject is not liftable"
            )
        return make_var(obj_name)
    if isinstance(node, ast.Subscript):
        # Subscript-index (``obj['key']``, ``obj[0]``): lift as
        # ``ctor('subscript', [base_term, key_term])``.  The base is
        # recursively translated so nested subscripts (``a['b']['c']``) and
        # attribute-then-subscript (``a.b['c']``) chain naturally.
        # Non-literal keys LOUDLY REFUSE via ``_subscript_key_term``.
        projected = _static_container_projection_from_expr(
            node.value,
            node.slice,
            _translate_term,
        )
        if projected is not None:
            return projected
        base_term = _translate_term(node.value)
        return _translate_subscript_term(node, base_term)
    raise ValueError("expression shape not in v0 lift whitelist")


_COMPARE_OP_MAP = {
    ast.Eq: "=",
    ast.NotEq: "≠",
    ast.Lt: "<",
    ast.LtE: "≤",
    ast.Gt: ">",
    ast.GtE: "≥",
}

_IDENTITY_OP_MAP = {
    ast.Is: "=",
    ast.IsNot: "≠",
}


def _is_none_term(term: Term) -> bool:
    return isinstance(term, _Ctor) and term.name == "None" and not term.args


def _comparison_from_identity_symbol(sym: str, left: Term, right: Term) -> Formula:
    if _is_none_term(left) == _is_none_term(right):
        raise ValueError("identity comparison is only supported against None")
    return comparison_with_none_guard(
        sym,
        left,
        right,
        emit_none_guard=True,
    )


_OPERATOR_CALL_NAMES = {
    "=": "eq",
    "≠": "eq",
    "<": "lt",
    "≤": "le",
    ">": "gt",
    "≥": "ge",
}


def _is_constructor_call_name(name: str) -> bool:
    final_segment = name.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
    return bool(final_segment) and final_segment[0].isupper()


def _constructor_operator_tag(term: Term) -> Optional[str]:
    if not isinstance(term, _Ctor):
        return None
    callee = term.name.removeprefix("call:")
    if _is_constructor_call_name(callee):
        return callee
    return None


def _operator_dispatch_operand(term: Term) -> Term:
    if isinstance(term, _Ctor):
        callee = term.name.removeprefix("call:")
        if _is_constructor_call_name(callee) and not term.name.startswith("call:"):
            return ctor(f"call:{callee}", list(term.args))
    return term


def _is_bytes_literal_term(term: Term) -> bool:
    from .ir import _ConstStr

    return (
        isinstance(term, _Ctor)
        and term.name == "python:bytes"
        and len(term.args) == 1
        and isinstance(term.args[0], _ConstStr)
    )


def _is_str_or_bytes_literal_term(term: Term) -> bool:
    from .ir import _ConstStr

    return isinstance(term, _ConstStr) or _is_bytes_literal_term(term)


def _str_bytes_sequence_literal_elements(term: Term) -> Optional[Tuple[Term, ...]]:
    if not (
        isinstance(term, _Ctor)
        and term.name in {"python:list", "python:tuple"}
        and term.args
    ):
        return None
    if not all(_is_str_or_bytes_literal_term(element) for element in term.args):
        return None
    return tuple(term.args)


def _comparison_from_symbol(sym: str, left: Term, right: Term) -> Formula:
    from .ir import _ConstStr

    # KIND-CONSTANT GUARD: python `==`/`!=` between a bytes literal and a str
    # literal never consults content -- it is constant by kind (b"a" == "a" is
    # False, always). Lifting it as a content comparison would be a wrong row
    # in both directions; refuse by name instead.
    if sym in ("=", "≠") and (
        (_is_bytes_literal_term(left) and isinstance(right, _ConstStr))
        or (isinstance(left, _ConstStr) and _is_bytes_literal_term(right))
    ):
        raise ValueError(
            "bytes-vs-str literal comparison is kind-constant in python "
            "(never content-equal); row refused -- assert within one kind"
        )
    tag = _constructor_operator_tag(left) or _constructor_operator_tag(right)
    if tag is not None:
        call_name = _OPERATOR_CALL_NAMES.get(sym)
        if call_name is None:
            raise ValueError(f"unsupported comparison symbol: {sym!r}")
        return eq(
            ctor(
                f"call:{call_name}:{tag}",
                [
                    _operator_dispatch_operand(left),
                    _operator_dispatch_operand(right),
                ],
            ),
            bool_const(sym != "≠"),
        )
    return comparison_with_none_guard(sym, left, right, emit_none_guard=False)


def _lift_literal_membership(
    op: ast.cmpop, left_node: ast.expr, right_node: ast.expr, term_fn
) -> Optional[Formula]:
    """``x in (1, 2)`` over a LITERAL tuple/list/set container is exactly
    the disjunction ``or_(eq(x, 1), eq(x, 2))`` — strictly stronger than
    the uninterpreted member atom, and the contact surface where a
    consumer's membership claim meets the branch-literal universes
    (``f(1) in ("c", "d")`` against a body swearing output ∈ {"a", "b"}
    conjoins to UNSAT).

    Falls back to None (the documented member atom) for everything else:
    computed or mixed-kind elements (cross-sort hazard: one subject, two
    theories), empty containers, dict containers (membership is KEYS),
    and string containers (containment is SUBSTRING semantics, never
    element equality)."""
    from .ir import _ConstBool, _ConstInt, _ConstStr

    if not isinstance(op, (ast.In, ast.NotIn)):
        return None
    if not isinstance(right_node, (ast.Tuple, ast.List, ast.Set)):
        return None
    if not right_node.elts:
        return None
    terms = []
    for el in right_node.elts:
        try:
            terms.append(term_fn(el))
        except ValueError:
            return None
    if len({type(t) for t in terms}) != 1 or not isinstance(
        terms[0], (_ConstInt, _ConstStr, _ConstBool)
    ):
        return None
    left = term_fn(left_node)
    disjunction = or_([eq(left, t) for t in terms])
    return not_(disjunction) if isinstance(op, ast.NotIn) else disjunction


def _comparison_from_ast_op(op: ast.cmpop, left: Term, right: Term) -> Formula:
    identity_sym = _IDENTITY_OP_MAP.get(type(op))
    if identity_sym is not None:
        return _comparison_from_identity_symbol(identity_sym, left, right)
    # Membership: ``x in coll`` -> ``member(x,coll)``; ``x not in coll`` ->
    # ``not(member(x,coll))``.  Using the SAME predicate symbol for both forms
    # is intentional and necessary for discrimination: ``member(x,c) ∧
    # ¬member(x,c)`` is propositionally UNSAT without any theory; z3 discharges
    # it trivially.  The SMT emitter declares unknown predicates as uninterpreted
    # Bool fns (``(declare-fun member (Int Int) Bool)``), so no Undecidable
    # result fires.  ASCII name chosen deliberately: the Unicode ``∈`` (U+2208)
    # is not a valid SMT-LIB simple-symbol char and z3 rejects it with a parse
    # error -- the same class of bug as the bare-string-literal encoding before
    # the strlit_<hash> fix.
    if isinstance(op, ast.In):
        return atomic("member", [left, right])
    if isinstance(op, ast.NotIn):
        return not_(atomic("member", [left, right]))
    sym = _COMPARE_OP_MAP.get(type(op))
    if sym is None:
        raise ValueError(f"unsupported comparison op: {type(op).__name__}")
    return _comparison_from_symbol(sym, left, right)


def _is_pytest_approx_call(node: ast.expr) -> bool:
    """Return True iff ``node`` is ``pytest.approx(...)`` or bare ``approx(...)``.

    Both forms are in scope; this check is purely syntactic.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    # bare: ``approx(target)``
    if isinstance(func, ast.Name) and func.id == "approx":
        return True
    # ``pytest.approx(target)``
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "approx"
        and isinstance(func.value, ast.Name)
        and func.value.id == "pytest"
    ):
        return True
    return False


def _lift_approx_comparison(
    op: ast.cmpop,
    left_node: ast.expr,
    right_node: ast.expr,
    term_fn,  # callable: ast.expr -> Term
) -> Optional[Formula]:
    """Try to lift ``x == pytest.approx(target)`` / ``x != pytest.approx(target)``.

    SOUND MODEL: conservative uninterpreted predicate.
      ``x == approx(t)`` -> ``atomic("approx_eq", [x_term, target_term])``
      ``x != approx(t)`` -> ``not_(atomic("approx_eq", [x_term, target_term]))``

    This catches ``x == approx(t); x != approx(t)`` (SAME x, SAME t) ->
    ``P ^ not P`` -> UNSAT -> REFUSED.  Different x or different t -> independent
    atoms -> PROVEN.

    DOCUMENTED LIMITATION (conservative under-refusal, never falsePass):
      Two assertions with DISJOINT approx targets (``x == approx(5.0); x ==
      approx(99.0)``) are treated as INDEPENDENT -> consistent -> PROVEN.
      This misses a real contradiction when the tolerance intervals don't overlap,
      but because we NEVER assert target distinctness, overlapping ranges are
      never falsely refused.  The under-refusal is acceptable and explicitly
      documented.

    LOUD REFUSE (raises ValueError) when:
      - op is not Eq or NotEq (``x < approx(5)`` is meaningless for tolerance)
      - kwargs (``rel=``, ``abs=``) present on the approx call — different
        tolerances produce different effective intervals; treating them as the
        same atom with the same target would model them identically, hiding the
        fact that the user specified different tolerances (potential for subtle
        falsePass if we ever extend the model)
      - the target is not a translatable numeric literal (computed / variable
        target cannot be content-addressed)
      - the approx arg is a list or dict (approx-of-collection is a different
        shape not modelled here)
      - approx appears on BOTH sides of the comparison (``approx(a) == approx(b)``
        is meaningless for our model)

    Returns None if neither side is a pytest.approx call (not our pattern).
    """
    left_is_approx = _is_pytest_approx_call(left_node)
    right_is_approx = _is_pytest_approx_call(right_node)

    if not left_is_approx and not right_is_approx:
        return None  # Not an approx comparison; caller falls through.

    if left_is_approx and right_is_approx:
        raise ValueError(
            "approx: both sides of comparison are pytest.approx calls; "
            "this shape is not soundly liftable"
        )

    # Only Eq and NotEq are meaningful for tolerance comparisons.
    if not isinstance(op, (ast.Eq, ast.NotEq)):
        raise ValueError(
            f"approx: operator {type(op).__name__!r} with pytest.approx is not "
            "soundly liftable — only == and != are in scope for the approx lifter"
        )

    # Identify the value side and the approx call.
    if right_is_approx:
        val_node = left_node
        approx_call = right_node
    else:
        val_node = right_node
        approx_call = left_node

    assert isinstance(approx_call, ast.Call)  # guaranteed by _is_pytest_approx_call

    # kwargs (rel=, abs=) -> LOUD REFUSE.
    if approx_call.keywords:
        kw_names = [k.arg or "**" for k in approx_call.keywords]
        raise ValueError(
            f"approx: keyword arguments {kw_names!r} on pytest.approx are not "
            "soundly liftable — different rel=/abs= tolerances produce different "
            "effective intervals; refusing rather than silently collapsing them"
        )

    # Must have exactly one positional arg: the target.
    if len(approx_call.args) != 1:
        raise ValueError(
            f"approx: expected exactly 1 positional argument (the target), "
            f"got {len(approx_call.args)}"
        )

    target_node = approx_call.args[0]

    # LOUD REFUSE for list/dict targets (approx-of-collection).
    if isinstance(target_node, (ast.List, ast.Tuple, ast.Dict, ast.Set)):
        raise ValueError(
            "approx: list/tuple/dict/set target is not soundly liftable — "
            "pytest.approx of a collection requires element-wise tolerance "
            "comparison which is out of scope for the approx lifter"
        )

    # Target must be a numeric literal (int or float) or unary-neg thereof.
    # We encode it as str_const(canonical_repr) so that:
    #   - int AND float targets work uniformly (num() is Int-only)
    #   - same literal -> same str_const -> same atom -> discrimination fires
    #   - different literals -> different str_const -> different atoms -> independent
    target_repr = _approx_target_repr(target_node)
    if target_repr is None:
        raise ValueError(
            "approx: target is not a translatable numeric literal (int or float); "
            "computed / variable targets cannot be content-addressed at lift time — "
            "refusing soundly rather than silently lifting an unstable term"
        )

    # Translate the value side using the caller's term function.
    try:
        val_term = term_fn(val_node)
    except ValueError as e:
        raise ValueError(f"approx: value side not liftable: {e}")

    target_term = str_const(target_repr)
    atom = atomic("approx_eq", [val_term, target_term])

    if isinstance(op, ast.NotEq):
        return not_(atom)
    return atom


def _approx_target_repr(node: ast.expr) -> Optional[str]:
    """Return a canonical string representation for a numeric literal target,
    or None if the node is not a liftable numeric literal.

    Accepted: int literal, float literal, unary-neg of int or float literal.
    Rejected: bool literals (bool is a subtype of int; approx(True) is
              semantically approx(1) but not a meaningful test value — refuse).
              Non-literal expressions (names, calls, etc.).

    The repr is chosen to be:
      - stable across Python versions for the same value
      - distinct for distinct numeric values
      - shared for identical numeric values

    We use ``repr(value)`` which is deterministic for int and float.
    """
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return None  # Bool is subtype of int; refuse for approx context.
        if isinstance(v, int):
            return repr(v)
        if isinstance(v, float):
            return repr(v)
        return None  # str, None, etc.
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = node.operand
        if isinstance(inner, ast.Constant):
            v = inner.value
            if isinstance(v, bool):
                return None
            if isinstance(v, int):
                return repr(-v)
            if isinstance(v, float):
                return repr(-v)
    return None


def _truthiness_call_head(callee: str, arity: int) -> str:
    """Build an ASCII-safe, arity-stable SMT predicate head for a truthiness
    call assertion.

    Shape: ``call_<callee>_a<arity>`` where ``<callee>`` is the callee name
    with non-alphanumeric chars replaced by ``_``, and ``<arity>`` is the
    total number of SMT arguments (receiver counts as arg 0 for method calls).

    Encoding arity in the name guarantees that the SMT emitter never sees two
    declarations with the same head at different arities (which would silently
    adopt the first arity, producing ill-sorted applications).
    """
    safe = "".join(c if (c.isascii() and c.isalnum()) else "_" for c in callee)
    return f"call_{safe}_a{arity}"


## ---------------------------------------------------------------------------
## isinstance: recognized concrete builtin Python types for soundness.
##
## ONLY concrete (leaf) builtin types are recognized. Abstract types
## (Iterable, Sequence, etc.), user-defined classes, and typing generics
## are LOUDLY REFUSED because their subtype relationships are unknown.
##
## bool IS a subtype of int: isinstance(True, int) is True, so
## isinstance(x, int) ∧ isinstance(x, bool) is CONSISTENT. The encoder
## must never assert pytype_int and pytype_bool disjoint.
## ---------------------------------------------------------------------------

_ISINSTANCE_CONCRETE_BUILTINS: Set[str] = set(ISINSTANCE_CONCRETE_BUILTINS)


def _lift_isinstance_call(node: ast.Call, translate_term_fn) -> Formula:
    """Lift ``isinstance(x, T)`` to ``atomic("isinstance", [x_term, ctor("pytype_T", [])])``.

    SOUND MODEL:
      - arg[0] (subject): translated via ``translate_term_fn`` (any liftable term).
      - arg[1] (type):    MUST be a bare ``ast.Name`` whose id is in
        ``_ISINSTANCE_CONCRETE_BUILTINS``. Any other shape → LOUD REFUSE.

    EXPLICIT LOUD REFUSES (raise ValueError with descriptive message):
      - tuple-of-types second arg: ``isinstance(x, (int, str))``
      - attribute second arg:      ``isinstance(x, typing.Sequence)``
      - non-builtin Name:          ``isinstance(x, MyClass)``
      - wrong arity (not exactly 2 positional args):
      - keyword args:

    The type constant is encoded as a NULLARY CTOR ``pytype_<T>`` (ASCII
    alnum+underscore only) so the SMT encoder declares it as an
    uninterpreted Int constant, distinct per type, with no semantic
    content beyond identity.

    Disjointness axioms are emitted by the Rust SMT encoder (isinstance_encoding.rs)
    for pairwise-disjoint pairs present in the same formula. The encoder
    MUST NOT assert int/bool disjoint (bool⊂int is Python-true).
    """
    # Arity check.
    if node.keywords:
        raise ValueError(
            "isinstance: keyword arguments are not supported; expected exactly "
            "2 positional args (subject, type)"
        )
    if len(node.args) != 2:
        raise ValueError(
            f"isinstance: expected exactly 2 positional args, got {len(node.args)}"
        )

    subject_node = node.args[0]
    type_node = node.args[1]

    # Type arg: MUST be a bare Name in the recognized builtin set.
    if isinstance(type_node, ast.Tuple):
        raise ValueError(
            "isinstance: tuple-of-types second arg ``isinstance(x, (A, B))`` is "
            "not soundly liftable as a single type constant; LOUD REFUSE"
        )
    if isinstance(type_node, ast.Attribute):
        raise ValueError(
            "isinstance: attribute type expression (e.g. ``typing.Sequence``, "
            "``collections.abc.Mapping``) has unknown subtype hierarchy; "
            "type-lattice required for soundness; LOUD REFUSE"
        )
    if not isinstance(type_node, ast.Name):
        raise ValueError(
            f"isinstance: unsupported type-arg shape {type(type_node).__name__!r}; "
            "only a bare builtin Name is liftable"
        )
    type_name = type_node.id
    if type_name not in _ISINSTANCE_CONCRETE_BUILTINS:
        raise ValueError(
            f"isinstance: ``{type_name}`` is not a recognized concrete builtin type; "
            "subtype relationships unknown; type-lattice required for soundness; "
            "LOUD REFUSE (deferred to type-lattice lifter)"
        )

    # Subject term.
    try:
        subject_term = translate_term_fn(subject_node)
    except ValueError as e:
        raise ValueError(
            f"isinstance: subject expression not liftable: {e}"
        )

    # Type constant: nullary ctor ``pytype_<name>``.
    type_const = ctor(f"pytype_{type_name}", [])
    return atomic("isinstance", [subject_term, type_const])


def _translate_truthiness_call_formula(
    node: ast.Call,
    translate_term_fn,  # callable: ast.expr -> Term
) -> Formula:
    """Lift a bare call expression used as a boolean assertion to an
    UNINTERPRETED predicate atom.

    Handles two shapes:
      - Method call: ``recv.method(args...)``  -> ``atomic("call_method_a<n>", [recv_term, arg_terms...])``
      - Function call: ``func(args...)``        -> ``atomic("call_func_a<n>", [arg_terms...])``

    Special case: ``isinstance(x, T)`` is lifted to
    ``atomic("isinstance", [x_term, ctor("pytype_T", [])])`` for recognized
    concrete builtin types T. Non-builtin / abstract / tuple-of-types T raises
    ValueError (LOUD REFUSE). See ``_lift_isinstance_call`` for the full
    soundness contract and the disjointness model.

    Any argument that cannot be translated by ``translate_term_fn`` raises
    ValueError (LOUD REFUSE at call site, never silent).
    """
    if isinstance(node.func, ast.Name):
        callee = node.func.id
        # isinstance: lift soundly for known concrete builtins; loud-refuse rest.
        if callee == "isinstance":
            return _lift_isinstance_call(node, translate_term_fn)
        # Regular function call.
        if node.keywords:
            raise ValueError(
                f"call `{callee}` with keyword args is not soundly liftable "
                "(keyword args cannot be order-stably translated without knowing "
                "the function signature)"
            )
        arg_terms = []
        for i, arg in enumerate(node.args):
            try:
                arg_terms.append(translate_term_fn(arg))
            except ValueError as e:
                raise ValueError(
                    f"call `{callee}` arg[{i}] not liftable: {e}"
                )
        head = _truthiness_call_head(callee, len(arg_terms))
        return atomic(head, arg_terms)

    if isinstance(node.func, ast.Attribute):
        method = node.func.attr
        recv_node = node.func.value
        if node.keywords:
            raise ValueError(
                f"method call `{method}` with keyword args is not soundly liftable"
            )
        try:
            recv_term = translate_term_fn(recv_node)
        except ValueError as e:
            raise ValueError(
                f"method call `{method}` receiver not liftable: {e}"
            )
        arg_terms = [recv_term]
        for i, arg in enumerate(node.args):
            try:
                arg_terms.append(translate_term_fn(arg))
            except ValueError as e:
                raise ValueError(
                    f"method call `{method}` arg[{i}] not liftable: {e}"
                )
        head = _truthiness_call_head(method, len(arg_terms))
        return atomic(head, arg_terms)

    raise ValueError(
        "call with non-Name/non-Attribute func is not liftable as a truthiness predicate"
    )


def _translate_chained_compare(node: ast.Compare, translate_term_fn) -> Formula:
    """Translate an n-way chained comparison (``a == b == c``, ``a < b <= c``, etc.)
    to a CONJUNCTION of pairwise comparisons.

    Python semantics: ``a op1 b op2 c`` means ``(a op1 b) and (b op2 c)`` with
    each intermediate operand evaluated once.  We model this exactly by
    building pairwise (left_i, op_i, right_i) pairs and conjoining the results.

    Generalises to n-way (any number of operators).  Mixed ops (``<``, ``<=``,
    ``==``) are handled by the existing ``_comparison_from_ast_op`` dispatcher.

    Sound because:
      - The conjunction is SATISFIABLE iff all pairwise comparisons are
        simultaneously satisfiable (correct model of Python chain semantics).
      - A contradictory chain (e.g. ``x == 1 == 2``) produces
        ``and_([eq(x,1), eq(1,2)])``; ``eq(1,2)`` is UNSAT in any Int model
        → the conjunction is UNSAT → REFUSED.
    """
    operands: list = [node.left] + list(node.comparators)
    pairs: list = []
    for i, op in enumerate(node.ops):
        member_formula = _lift_literal_membership(
            op, operands[i], operands[i + 1], translate_term_fn
        )
        if member_formula is not None:
            pairs.append(member_formula)
            continue
        l = translate_term_fn(operands[i])
        r = translate_term_fn(operands[i + 1])
        pairs.append(_comparison_from_ast_op(op, l, r))
    return and_(pairs) if len(pairs) > 1 else pairs[0]


def _translate_bool_expr(node: ast.expr) -> Formula:
    """``assert <expr>``: only a single-comparison, chained-comparison, or
    truthiness-call expression is liftable.

    Handles:
      - ``assert <comparison>``         -> comparison formula
      - ``assert a op1 b op2 c ...``   -> conjunction of pairwise comparisons
      - ``assert <call>``              -> uninterpreted predicate atom (TRUTHINESS)
      - ``assert not <call>``          -> not_(predicate atom)
      - ``assert not <comparison>``    -> not_(comparison formula)
    """
    if isinstance(node, ast.Compare):
        if len(node.ops) == 1:
            # pytest.approx interception: must happen BEFORE generic term
            # translation so approx calls are never silently lifted as ctor terms.
            approx_formula = _lift_approx_comparison(
                node.ops[0], node.left, node.comparators[0], _translate_term
            )
            if approx_formula is not None:
                return approx_formula
            member_formula = _lift_literal_membership(
                node.ops[0], node.left, node.comparators[0], _translate_term
            )
            if member_formula is not None:
                return member_formula
            l = _translate_term(node.left)
            r = _translate_term(node.comparators[0])
            return _comparison_from_ast_op(node.ops[0], l, r)
        # Chained comparison: n >= 2 operators.
        return _translate_chained_compare(node, _translate_term)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = _translate_bool_expr(node.operand)
        return not_(inner)
    if isinstance(node, ast.Call):
        return _translate_truthiness_call_formula(node, _translate_term)
    if isinstance(node, ast.NamedExpr):
        # Walrus inside an assert: skip.
        raise ValueError("walrus operator in assert is not liftable")
    raise ValueError("assert body must be a comparison expression or a call/not-call")


def _lift_assertion_stmt(stmt: ast.stmt) -> Formula:
    """Translate a recognized assertion statement to a Formula. Raises
    ValueError if the stmt's surface looked liftable but a leaf isn't.
    """
    if isinstance(stmt, ast.Assert):
        return _translate_bool_expr(stmt.test)
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        call = stmt.value
        name = _attr_method_name(call.func)
        if name in _UNITTEST_IDENTITY_PREDICATES:
            if len(call.args) < 2:
                raise ValueError(f"{name} expects at least 2 positional args")
            l = _translate_term(call.args[0])
            r = _translate_term(call.args[1])
            return _comparison_from_identity_symbol(
                _UNITTEST_IDENTITY_PREDICATES[name],
                l,
                r,
            )
        if name in _UNITTEST_BINARY_PREDICATES:
            if len(call.args) < 2:
                raise ValueError(f"{name} expects at least 2 positional args")
            l = _translate_term(call.args[0])
            r = _translate_term(call.args[1])
            sym = _UNITTEST_BINARY_PREDICATES[name]
            return _comparison_from_symbol(sym, l, r)
        if name in _UNITTEST_NONE_PREDICATES:
            if len(call.args) < 1:
                raise ValueError(f"{name} expects 1 positional arg")
            t = _translate_term(call.args[0])
            return comparison_with_none_guard(
                _UNITTEST_NONE_PREDICATES[name],
                t,
                ctor("None", []),
                emit_none_guard=True,
            )
        if name == "assertTrue":
            if len(call.args) < 1:
                raise ValueError("assertTrue expects 1 positional arg")
            return _translate_truth_assertion(call.args[0], True)
        if name == "assertFalse":
            if len(call.args) < 1:
                raise ValueError("assertFalse expects 1 positional arg")
            return _translate_truth_assertion(call.args[0], False)
        raise ValueError(f"unrecognized assertion method: {name!r}")
    raise ValueError("statement is not a liftable assertion")


def _translate_truth_assertion(node: ast.expr, expected: bool) -> Formula:
    try:
        formula = _translate_bool_expr(node)
    except ValueError as bool_error:
        try:
            t = _translate_term(node)
        except ValueError:
            raise bool_error
        return eq(t, bool_const(expected))
    return formula if expected else not_(formula)


# ---------------------------------------------------------------------------
# PATTERN 1: bounded for-loop
# ---------------------------------------------------------------------------


def _classify_for_loop(
    fl: ast.For,
    test_name: str,
    source_path: str,
    out: Layer2Output,
) -> None:
    out.claimed_tests.add(test_name)
    out.seen += 1

    if not isinstance(fl.target, ast.Name):
        out.bounded_loop_skipped += 1
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        "layer2 bounded-loop: loop target is not a simple identifier")
        )
        return
    var_name = fl.target.id

    if len(fl.body) != 1:
        out.bounded_loop_skipped += 1
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        f"layer2 bounded-loop: body has {len(fl.body)} stmts (only single-stmt bodies in v0)")
        )
        return
    if fl.orelse:
        out.bounded_loop_skipped += 1
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        "layer2 bounded-loop: for/else clause is not liftable in v0")
        )
        return

    # Reject nested for-loop bodies.
    if _has_nested_for(fl.body[0]):
        out.bounded_loop_skipped += 1
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        "layer2 bounded-loop: nested for-loop detected; deferred to Layer 2.5")
        )
        return

    body_stmt = fl.body[0]
    if not _is_assertion_stmt(body_stmt):
        out.bounded_loop_skipped += 1
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        "layer2 bounded-loop: body stmt is not an assertion")
        )
        return

    # Iterator must be a literal-bounded numeric range OR a literal list.
    iter_node = fl.iter
    if _is_range_call(iter_node):
        rng = _parse_range_call(iter_node)
        if rng is None:
            out.bounded_loop_skipped += 1
            out.warnings.append(
                LiftWarning(source_path, test_name,
                            "layer2 bounded-loop: range() arg shape not in v0 whitelist (literal int / unary-neg int / bare ident only; no step)")
            )
            return
        lo_term, hi_term = rng
        try:
            inner_formula = _lift_assertion_stmt(body_stmt)
        except ValueError as e:
            out.bounded_loop_skipped += 1
            out.warnings.append(
                LiftWarning(source_path, test_name,
                            f"layer2 bounded-loop: inner assertion not liftable: {e}")
            )
            return
        var_term = make_var(var_name)
        antecedent = and_([gte(var_term, lo_term), lt(var_term, hi_term)])
        body_formula = implies(antecedent, inner_formula)
        from .ir import _Quantifier  # type: ignore
        q = _Quantifier("forall", var_name, Int(), body_formula)
        memento_name = f"{test_name}::loop::{var_name}"
        out.decls.append(ContractDecl(name=memento_name, inv=q))
        out.lifted += 1
        out.bounded_loop_lifted += 1
        return

    if isinstance(iter_node, (ast.List, ast.Tuple)):
        # for v in [1, 2, 3]: assert phi(v)   ->  and_( phi[v_i] )
        # for v in (1, 2, 3): assert phi(v)   ->  same (Tuple literal is identical semantics)
        # SOUNDNESS: each element is a CONCRETE literal value; substituting it into phi
        # produces a closed formula with no free occurrence of v.  The conjunction of
        # all per-element formulas is EXACTLY the semantics of the bounded loop.
        elements: List[Term] = []
        for el in iter_node.elts:
            try:
                elements.append(_translate_term(el))
            except ValueError as e:
                out.bounded_loop_skipped += 1
                out.warnings.append(
                    LiftWarning(source_path, test_name,
                                f"layer2 bounded-loop: list/tuple element not liftable: {e}")
                )
                return
        if not elements:
            out.bounded_loop_skipped += 1
            out.warnings.append(
                LiftWarning(source_path, test_name,
                            "layer2 bounded-loop: empty list/tuple iterator yields a vacuous conjunction; skipping")
            )
            return
        try:
            inner_formula = _lift_assertion_stmt(body_stmt)
        except ValueError as e:
            out.bounded_loop_skipped += 1
            out.warnings.append(
                LiftWarning(source_path, test_name,
                            f"layer2 bounded-loop: inner assertion not liftable: {e}")
            )
            return
        substituted = [subst_var_in_formula(inner_formula, var_name, t) for t in elements]
        body_formula = and_(substituted) if len(substituted) > 1 else substituted[0]
        memento_name = f"{test_name}::loop::{var_name}"
        out.decls.append(ContractDecl(name=memento_name, inv=body_formula))
        out.lifted += 1
        out.bounded_loop_lifted += 1
        return

    out.bounded_loop_skipped += 1
    out.warnings.append(
        LiftWarning(source_path, test_name,
                    "layer2 bounded-loop: iterator is not a literal-bounded numeric range, list, or tuple")
    )


# ---------------------------------------------------------------------------
# PATTERN 1c: embedded for-loop (assignments + terminal For[literal-iter])
# ---------------------------------------------------------------------------
#
# Handles test bodies of the shape:
#
#     def test_x():
#         a = setup(...)          # zero or more simple assignments
#         b = other(a)
#         for v in (x1, x2, ...):   # literal list OR tuple; simple-Name target
#             assert phi(v, a, b)   # one or more assertions (no bindings in body)
#
# The For MUST be the last statement in the test body.  All preceding statements
# MUST be simple assignments (simple-Name target) or Pass; the same allowlist as
# Pattern 6 (mixed-body).
#
# SOUNDNESS: the loop is enumerated element-by-element (identical to Pattern 1b).
# Each element is a CONCRETE literal; substituting it into the body formula yields
# a closed formula.  Preceding bindings establish SSA vars that are used in the
# body assertions — they are opaque free vars (same as mixed-body), so no false
# values are ascribed to them.  The outer SSA scope is built ONCE and reused for
# every iteration (the assignments are NOT re-executed per iteration — they are
# shared outer bindings), which is correct: Python evaluates the outer assignments
# once before the loop runs.
#
# Multi-assert bodies: each assert in the For body is lifted independently under
# the current SSA scope + loop-var substitution.  Unliftable asserts are
# warn-and-skipped (partial lift, same policy as mixed-body).  If NO assert
# lifts for ANY iteration, the pattern loud-refuses.
#
# GATE: fires ONLY when:
#   - body[-1] is a For
#   - For target is a simple Name
#   - For iterator is ast.List or ast.Tuple with at least one liftable element
#   - For body contains at least one ast.Assert
#   - For body contains NO bindings (Assign/AnnAssign) — only Asserts + Pass
#     (bindings INSIDE the loop body would need per-iteration SSA versioning,
#     which is a separate pattern; keep loud-refused for now)
#   - All preceding stmts are simple assignments or Pass (no For/With/If/While)
#
# If the gate fires but a soundness check fails, the pattern CLAIMS the test and
# emits a LOUD REFUSAL (never silent).


def _classify_embedded_for(
    body: Sequence[ast.stmt],
    test_name: str,
    source_path: str,
    out: Layer2Output,
) -> bool:
    """Pattern 1c: mixed body with a terminal For[literal-iter, assert-only-body].

    Returns True if this pattern claimed the test (even on a loud refusal),
    False if the body does not match the embedded-for shape (caller tries next).
    """
    # Gate: last statement must be a For.
    if not body or not isinstance(body[-1], ast.For):
        return False

    fl = body[-1]

    # Gate: For target must be a simple Name.
    if not isinstance(fl.target, ast.Name):
        return False
    var_name = fl.target.id

    # Gate: For iterator must be a literal List or Tuple.
    iter_node = fl.iter
    if not isinstance(iter_node, (ast.List, ast.Tuple)):
        return False

    # Gate: For body must contain at least one Assert.
    if not any(isinstance(s, ast.Assert) for s in fl.body):
        return False

    # Gate: For body must NOT contain bindings (Assign/AnnAssign) — those would
    # need per-iteration SSA versioning which is out of scope for v0.
    # SOUNDNESS: if bindings exist in the loop body, they are re-executed each
    # iteration and may be loop-var-dependent (e.g. ``val = f(v)``).  We cannot
    # soundly substitute the outer SSA scope into those bindings without
    # per-iteration versioning.  Keep loud-refused for this shape.
    for s in fl.body:
        if isinstance(s, (ast.Assign, ast.AnnAssign)):
            return False

    # Gate: For body must not have unsupported stmt kinds (For, With, If, etc.).
    for s in fl.body:
        if not isinstance(s, (ast.Assert, ast.Pass)):
            return False

    # Gate: For/else clause is not liftable.
    if fl.orelse:
        return False

    # Gate: preceding statements (body[:-1]) must all be simple assignments or Pass.
    # Any unsupported kind (For, With, If, While, etc.) → not our pattern; let
    # catch-all handle it.
    for s in body[:-1]:
        if isinstance(s, ast.Pass):
            continue
        if isinstance(s, ast.Assign):
            if len(s.targets) != 1 or not isinstance(s.targets[0], ast.Name):
                return False
            continue
        if isinstance(s, ast.AnnAssign):
            if not isinstance(s.target, ast.Name):
                return False
            continue
        # Docstring (Expr with a string constant at index 0) — skip.
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str):
            continue
        return False

    # --- Pattern claimed: all gates passed ---
    out.claimed_tests.add(test_name)
    out.seen += 1

    # Translate iterator elements.
    elements: List[Term] = []
    for el in iter_node.elts:
        try:
            elements.append(_translate_term(el))
        except ValueError as e:
            out.embedded_for_skipped += 1
            out.warnings.append(
                LiftWarning(
                    source_path, test_name,
                    f"layer2 embedded-for: LOUD REFUSAL — iterator element not liftable: {e}",
                )
            )
            return True
    if not elements:
        out.embedded_for_skipped += 1
        out.warnings.append(
            LiftWarning(
                source_path, test_name,
                "layer2 embedded-for: LOUD REFUSAL — empty iterator yields a vacuous conjunction",
            )
        )
        return True

    # Build outer SSA scope from preceding bindings (opaque free vars — same as
    # mixed-body: no value constraints on non-translatable RHS bindings).
    ssa_current: Dict[str, Term] = {}
    ssa_versions: Dict[str, int] = {}
    for s in body[:-1]:
        if isinstance(s, (ast.Pass, ast.Expr)):
            continue
        if isinstance(s, ast.Assign):
            target_name = s.targets[0].id  # simple name guaranteed by gate
            value_node = s.value
        else:  # AnnAssign
            target_name = s.target.id
            value_node = s.value
            if value_node is None:
                # Bare annotation (no value) — just bump the SSA version.
                version = ssa_versions.get(target_name, 0)
                ssa_versions[target_name] = version + 1
                ssa_current[target_name] = make_var(f"{target_name}${version}")
                continue

        version = ssa_versions.get(target_name, 0)
        ssa_versions[target_name] = version + 1
        ssa_name = f"{target_name}${version}"
        ssa_current[target_name] = make_var(ssa_name)

    # Per element: substitute loop var, translate assertions under SSA scope.
    # ALL per-element, per-assert atoms are collected into ONE flat list and
    # conjoined into a SINGLE ContractDecl named ``<test>::loop::<var>``.
    #
    # SOUNDNESS: the for-loop iterations share the SAME Python environment —
    # only the loop variable changes; outer bindings (encoded as SSA vars) are
    # evaluated ONCE before the loop and are shared across all iterations.
    # Therefore a free var ``enc$0`` that appears in assertions from two
    # different iterations refers to the SAME object; constraining it to two
    # different values in separate contracts would make each contract
    # independently SAT (enc$0==1 alone is consistent, enc$0==2 alone is
    # consistent) — a falsePass.  Conjoining all atoms into one contract
    # ``enc$0==1 ∧ enc$0==2`` correctly reflects the full constraint set and
    # fires UNSAT → REFUSED when a genuine contradiction exists.
    #
    # This is the same model as Pattern 1b (list literal) and Pattern 1 (range),
    # which already conjoin all per-element substituted atoms into one formula.
    #
    # CONTRAST with Pattern 4 (parametrize): pytest.mark.parametrize rows ARE
    # independent test INSTANCES (pytest invokes the function once per row with
    # fresh local bindings); per-row contracts are correct there.  A for-loop
    # body is NOT independently re-invoked; it shares the outer scope.
    all_atoms: List[Formula] = []
    skip_reasons: List[str] = []

    for elem_idx, elem_term in enumerate(elements):
        # Build scope for this iteration: outer SSA + loop var bound to element.
        iter_scope_current = dict(ssa_current)
        iter_scope_current[var_name] = elem_term
        scope = _ValueScope(current=iter_scope_current)

        for s in fl.body:
            if not isinstance(s, ast.Assert):
                continue
            try:
                atom = _lift_assertion_stmt_scoped(s, scope)
                all_atoms.append(atom)
            except ValueError as e:
                skip_reasons.append(
                    f"elem {elem_idx} `{_unparse(s)[:60]}`: {e}"
                )

    if not all_atoms:
        # No atom lifted from any element — loud refuse.
        out.embedded_for_skipped += 1
        out.warnings.append(
            LiftWarning(
                source_path, test_name,
                "layer2 embedded-for: LOUD REFUSAL — 0 atoms lifted across all elements "
                "(all assert bodies failed to lift — likely f-strings or unsupported "
                f"expressions in assert conditions; skipped: {'; '.join(skip_reasons[:3])})",
            )
        )
        return True

    inv = all_atoms[0] if len(all_atoms) == 1 else and_(all_atoms)
    memento_name = f"{test_name}::loop::{var_name}"
    out.decls.append(ContractDecl(name=memento_name, inv=inv))
    out.lifted += 1
    out.embedded_for_lifted += 1

    if skip_reasons:
        out.warnings.append(
            LiftWarning(
                source_path, test_name,
                f"layer2 embedded-for: {len(skip_reasons)} assert(s) skipped "
                f"(unliftable): {'; '.join(skip_reasons[:3])}",
            )
        )
    return True


# ---------------------------------------------------------------------------
# PATTERN 8: if-guarded assertions — ``if cond: assert P``
# ---------------------------------------------------------------------------
#
# Handles test bodies where asserts are nested under ``if`` guards.  Each
# ``if cond: assert P`` is lifted as ``implies(cond_formula, P_formula)``
# where ``cond_formula`` is translated via ``_translate_bool_expr_scoped``
# (supports comparison / membership / truthiness / BoolOp / not).
#
# SOUNDNESS RULES:
#   - The guard is lifted via ``_translate_bool_expr_scoped``.  We do NOT
#     use ``_lift_branch_guard`` because its ``python_branch_condition``
#     opaque fallback turns any unliftable condition into an always-SAT
#     atom, making the implication vacuously hold — a falsePass.  If the
#     condition is not soundly liftable, the branch LOUDLY REFUSES.
#   - ``if cond: assert P`` → ``implies(cond, P)`` — the assert only claims
#     P holds WHEN cond.  Lifting P unconditionally would be a falsePass
#     (P may only hold under cond).
#   - ``else`` branch: if ``orelse`` contains an ``assert Q``, it is guarded
#     by ``not_(cond)`` → ``implies(not_(cond), Q)``.  This correctly models
#     the else-branch condition.
#   - Tautology: ``if True: assert P`` — ``True``/``False`` are ast.Constant,
#     rejected by ``_translate_bool_expr_scoped`` (not a Compare/Call/BoolOp).
#     We map bare ``ast.Constant(True)`` to ``bool_const(True)`` and
#     ``ast.Constant(False)`` to ``bool_const(False)`` as special cases so
#     tautological guards reduce correctly in z3 (implies(true, P) = P).
#   - A ``tautological`` guard (cond = bool_const(True)) makes the implication
#     equivalent to P, so ``if 1==1: assert x==1`` + ``assert x==2`` produces
#     ``and_(implies(eq(1,1),eq(x,1)), eq(x,2))`` which z3 sees as
#     ``eq(x,1) ∧ eq(x,2)`` → UNSAT → REFUSED.  This is the correct model.
#   - FALSE-REFUSAL GUARD: ``implies(cond,x==1) ∧ implies(cond,x==2)`` is SAT
#     (set cond=False) so two if-guarded contradictory asserts on the same var
#     are CONSISTENTLY PROVEN, not refused — the guard absorbs the contradiction.
#
# GATE:
#   - Body contains at least one ``ast.If`` whose nested assert count > 0.
#   - All non-If, non-Assert, non-Pass, non-binding stmts → LOUD REFUSE.
#   - Bindings (Assign/AnnAssign) at the top level are allowed (SSA scoping
#     same as mixed-body); bindings INSIDE the if-body → LOUD REFUSE for that
#     branch (only asserts + pass allowed in branch bodies).
#
# INTEGRATION with sibling asserts:
#   Top-level asserts alongside ``if`` guards are lifted as plain atoms and
#   conjoined with the implication atoms into ONE contract (same as mixed-body's
#   partial-lift model for unliftable assertions).


_TAUTOLOGY_BOOLCONST: Dict[object, object] = {True: True, False: False}


def _lift_if_cond(node: ast.expr, scope: "_ValueScope") -> Formula:
    """Translate an ``if`` condition to a Formula for use as a guard.

    Supports everything ``_translate_bool_expr_scoped`` supports, PLUS
    bare ``ast.Constant(True)`` and ``ast.Constant(False)`` literals which
    the generic translator rejects (they are not Compare/Call/BoolOp nodes).

    Raises ValueError for any unliftable condition so the caller can LOUD REFUSE
    that branch (and never emit a vacuous always-SAT guard).
    """
    if isinstance(node, ast.Constant):
        if node.value is True:
            return eq(bool_const(True), bool_const(True))   # tautology: z3 reduces to true
        if node.value is False:
            return eq(bool_const(False), bool_const(True))  # contradiction: z3 reduces to false
    return _translate_bool_expr_scoped(node, scope)


def _if_branch_only_asserts_and_pass(stmts: Sequence[ast.stmt]) -> bool:
    """Return True iff every stmt in the branch is an Assert or Pass."""
    return all(isinstance(s, (ast.Assert, ast.Pass)) for s in stmts)


def _classify_if_guarded(
    body: Sequence[ast.stmt],
    test_name: str,
    source_path: str,
    out: Layer2Output,
) -> bool:
    """Pattern 8: test body containing ``if cond: assert P`` guards.

    Returns True if this pattern claimed the test (even on a loud refusal),
    False if the body has no If statement at the top level (caller tries next).
    """
    # Gate: at least one top-level If with a nested assert.
    has_if_with_assert = any(
        isinstance(s, ast.If)
        and any(isinstance(n, ast.Assert) for n in ast.walk(s))
        for s in body
    )
    if not has_if_with_assert:
        return False

    # Gate: every top-level stmt must be one of the allowed kinds.
    # Allowed: Assert, Pass, Assign (simple name), AnnAssign (simple name),
    #          Expr (docstring or bare call), If.
    # NOT allowed: For, While, With, Try, FunctionDef, etc.
    for s in body:
        if isinstance(s, (ast.Assert, ast.Pass, ast.If)):
            continue
        if isinstance(s, ast.Assign):
            if all(isinstance(t, ast.Name) for t in s.targets):
                continue
        if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
            continue
        if isinstance(s, ast.Expr):
            continue
        # Unsupported stmt kind — not our pattern.
        return False

    # --- Pattern claimed ---
    out.claimed_tests.add(test_name)
    out.seen += 1

    # Build SSA scope from top-level bindings.
    ssa_current: Dict[str, Term] = {}
    ssa_versions: Dict[str, int] = {}
    all_atoms: List[Formula] = []
    skip_reasons: List[str] = []

    for s in body:
        if isinstance(s, ast.Pass):
            continue
        if isinstance(s, ast.Expr):
            continue

        if isinstance(s, (ast.Assign, ast.AnnAssign)):
            if isinstance(s, ast.Assign):
                target_name = s.targets[0].id
                value_node = s.value
            else:
                target_name = s.target.id
                value_node = s.value
            version = ssa_versions.get(target_name, 0)
            ssa_versions[target_name] = version + 1
            ssa_current[target_name] = make_var(f"{target_name}${version}")
            continue

        if isinstance(s, ast.Assert):
            # Top-level assert — lift as plain atom under current scope.
            scope = _ValueScope(current=dict(ssa_current))
            try:
                atom = _lift_assertion_stmt_scoped(s, scope)
                all_atoms.append(atom)
            except ValueError as e:
                skip_reasons.append(f"top-level assert `{_unparse(s)[:60]}`: {e}")
            continue

        if isinstance(s, ast.If):
            scope = _ValueScope(current=dict(ssa_current))

            # Try to lift the condition.
            try:
                cond_formula = _lift_if_cond(s.test, scope)
            except ValueError as e:
                skip_reasons.append(
                    f"if-cond `{_unparse(s.test)[:60]}` not liftable: {e}"
                )
                continue

            # Validate then-branch: only Asserts + Pass allowed.
            if not _if_branch_only_asserts_and_pass(s.body):
                skip_reasons.append(
                    f"if-body has non-assert stmts (bindings/for/with in branch not supported)"
                )
                continue

            # Validate else-branch: only Asserts + Pass allowed (or empty).
            else_stmts = s.orelse
            if else_stmts and not _if_branch_only_asserts_and_pass(else_stmts):
                skip_reasons.append(
                    f"else-body has non-assert stmts (bindings/for/with in branch not supported)"
                )
                continue

            # Lift then-branch asserts as implies(cond, P).
            for branch_stmt in s.body:
                if not isinstance(branch_stmt, ast.Assert):
                    continue
                try:
                    p = _lift_assertion_stmt_scoped(branch_stmt, scope)
                    all_atoms.append(implies(cond_formula, p))
                except ValueError as e:
                    skip_reasons.append(
                        f"if-body assert `{_unparse(branch_stmt)[:60]}` not liftable: {e}"
                    )

            # Lift else-branch asserts as implies(not_(cond), Q).
            for else_stmt in else_stmts:
                if not isinstance(else_stmt, ast.Assert):
                    continue
                try:
                    q = _lift_assertion_stmt_scoped(else_stmt, scope)
                    all_atoms.append(implies(not_(cond_formula), q))
                except ValueError as e:
                    skip_reasons.append(
                        f"else-body assert `{_unparse(else_stmt)[:60]}` not liftable: {e}"
                    )
            continue

    if not all_atoms:
        out.if_guarded_skipped += 1
        out.warnings.append(
            LiftWarning(
                source_path, test_name,
                "layer2 if-guarded: LOUD REFUSAL — 0 atoms lifted from if-guarded body "
                f"(skipped: {'; '.join(skip_reasons[:3])})",
            )
        )
        return True

    inv = all_atoms[0] if len(all_atoms) == 1 else and_(all_atoms)
    out.decls.append(ContractDecl(name=test_name, inv=inv))
    out.lifted += 1
    out.if_guarded_lifted += 1

    if skip_reasons:
        out.warnings.append(
            LiftWarning(
                source_path, test_name,
                f"layer2 if-guarded: {len(skip_reasons)} atom(s) skipped: "
                f"{'; '.join(skip_reasons[:3])}",
            )
        )
    return True


# ---------------------------------------------------------------------------
# PATTERN 9: with-body assertions — ``with <non-suppressing-CM>: assert P``
# ---------------------------------------------------------------------------
#
# Handles test bodies where asserts are inside a ``with`` block backed by a
# non-suppressing context manager (e.g., ``open(...)``).
#
# SOUNDNESS RULES:
#   - ``pytest.raises`` is Pattern 7 — already handled; Pattern 9 must NOT
#     fire for raises blocks (the gate excludes them).
#   - ``contextlib.suppress`` and ``contextlib.ExitStack`` can swallow
#     exceptions, making the body asserts non-load-bearing; LOUD REFUSE.
#   - Unknown / user-defined context managers: LOUD REFUSE.  We cannot
#     know whether they suppress assertions.
#   - ALLOWLIST of non-suppressing CMs: ``open``, ``tempfile.NamedTemp-
#     oraryFile``, ``tempfile.TemporaryDirectory``, ``io.StringIO``,
#     ``io.BytesIO``.  The ``as`` target (if present) becomes an opaque
#     free var (no value constraint — we treat it as an unknown but known-
#     non-None reference).
#   - Body asserts are lifted as plain facts (NOT guarded by the CM) because
#     the CM does not suppress them — the assert holds unconditionally if
#     control reaches it.
#   - Body may contain Pass statements alongside asserts.
#   - Multi-statement bodies with bindings inside the with-body:
#     LOUD REFUSE (would need per-with-body SSA versioning).
#
# GATE:
#   - Body contains at least one ``ast.With`` that is NOT a pytest.raises block.
#   - All With items must be single-item with the CM in the allowlist.
#   - Mixed with-body (binding + assert) → LOUD REFUSE for that block.

_WITH_CM_ALLOWLIST: Set[str] = {
    "open",
    "NamedTemporaryFile",
    "TemporaryDirectory",
    "StringIO",
    "BytesIO",
}


def _with_cm_name(ce: ast.expr) -> Optional[str]:
    """Extract the CM call name from a withitem context_expr.

    Accepts:
      - ``open(...)`` → ``"open"``
      - ``tempfile.NamedTemporaryFile(...)`` → ``"NamedTemporaryFile"``
      - ``io.StringIO(...)`` → ``"StringIO"``
    Returns None for any other shape.
    """
    if isinstance(ce, ast.Call):
        func = ce.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def _classify_with_body(
    body: Sequence[ast.stmt],
    test_name: str,
    source_path: str,
    out: Layer2Output,
) -> bool:
    """Pattern 9: test bodies containing non-suppressing with-blocks with asserts.

    Returns True if this pattern claimed the test (even on a loud refusal),
    False if the body has no eligible With statement (caller tries next).
    """
    # Gate: at least one top-level With that is NOT a pytest.raises block and
    # has a nested assert.
    def _is_raises_with(s: ast.With) -> bool:
        return (
            len(s.items) == 1
            and isinstance(s.items[0].context_expr, ast.Call)
            and _is_pytest_raises_func(s.items[0].context_expr.func)
        )

    eligible_withs = [
        s for s in body
        if isinstance(s, ast.With)
        and not _is_raises_with(s)
        and any(isinstance(n, ast.Assert) for n in ast.walk(s))
    ]
    if not eligible_withs:
        return False

    # Gate: all top-level stmts must be allowed kinds.
    for s in body:
        if isinstance(s, (ast.Assert, ast.Pass, ast.Expr, ast.With)):
            continue
        if isinstance(s, ast.Assign) and all(isinstance(t, ast.Name) for t in s.targets):
            continue
        if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
            continue
        return False

    # --- Pattern claimed ---
    out.claimed_tests.add(test_name)
    out.seen += 1

    ssa_current: Dict[str, Term] = {}
    ssa_versions: Dict[str, int] = {}
    all_atoms: List[Formula] = []
    skip_reasons: List[str] = []

    for s in body:
        if isinstance(s, ast.Pass):
            continue
        if isinstance(s, ast.Expr):
            continue

        if isinstance(s, (ast.Assign, ast.AnnAssign)):
            if isinstance(s, ast.Assign):
                target_name = s.targets[0].id
            else:
                target_name = s.target.id
            version = ssa_versions.get(target_name, 0)
            ssa_versions[target_name] = version + 1
            ssa_current[target_name] = make_var(f"{target_name}${version}")
            continue

        if isinstance(s, ast.Assert):
            scope = _ValueScope(current=dict(ssa_current))
            try:
                atom = _lift_assertion_stmt_scoped(s, scope)
                all_atoms.append(atom)
            except ValueError as e:
                skip_reasons.append(f"top-level assert `{_unparse(s)[:60]}`: {e}")
            continue

        if isinstance(s, ast.With):
            # Check: single withitem.
            if len(s.items) != 1:
                skip_reasons.append(
                    f"with multi-item clause is not soundly liftable"
                )
                continue

            item = s.items[0]
            ce = item.context_expr
            cm_name = _with_cm_name(ce)

            if cm_name is None or cm_name not in _WITH_CM_ALLOWLIST:
                # Unknown or suppressing CM — LOUD REFUSE the entire pattern.
                out.with_body_skipped += 1
                out.warnings.append(
                    LiftWarning(
                        source_path, test_name,
                        f"layer2 with-body: LOUD REFUSAL — context manager "
                        f"`{_unparse(ce)[:60]}` is not in the non-suppressing allowlist "
                        "(only open/NamedTemporaryFile/TemporaryDirectory/StringIO/BytesIO "
                        "are soundly liftable; other CMs may suppress assertions)",
                    )
                )
                return True

            # with-body must contain only Asserts + Pass (no bindings inside).
            if not _if_branch_only_asserts_and_pass(s.body):
                skip_reasons.append(
                    f"with-body has non-assert stmts (bindings inside with are not supported)"
                )
                continue

            # Bind the ``as`` target as an opaque free var if present.
            scope_current = dict(ssa_current)
            if item.optional_vars is not None and isinstance(item.optional_vars, ast.Name):
                as_name = item.optional_vars.id
                version = ssa_versions.get(as_name, 0)
                ssa_versions[as_name] = version + 1
                scope_current[as_name] = make_var(f"{as_name}${version}")

            scope = _ValueScope(current=scope_current)

            for branch_stmt in s.body:
                if not isinstance(branch_stmt, ast.Assert):
                    continue
                try:
                    atom = _lift_assertion_stmt_scoped(branch_stmt, scope)
                    all_atoms.append(atom)
                except ValueError as e:
                    skip_reasons.append(
                        f"with-body assert `{_unparse(branch_stmt)[:60]}`: {e}"
                    )
            continue

    if not all_atoms:
        out.with_body_skipped += 1
        out.warnings.append(
            LiftWarning(
                source_path, test_name,
                "layer2 with-body: LOUD REFUSAL — 0 atoms lifted from with-body "
                f"(skipped: {'; '.join(skip_reasons[:3])})",
            )
        )
        return True

    inv = all_atoms[0] if len(all_atoms) == 1 else and_(all_atoms)
    out.decls.append(ContractDecl(name=test_name, inv=inv))
    out.lifted += 1
    out.with_body_lifted += 1

    if skip_reasons:
        out.warnings.append(
            LiftWarning(
                source_path, test_name,
                f"layer2 with-body: {len(skip_reasons)} atom(s) skipped: "
                f"{'; '.join(skip_reasons[:3])}",
            )
        )
    return True


def _is_range_call(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
    )


def _parse_range_call(node: ast.Call) -> Optional[Tuple[Term, Term]]:
    """Parse ``range(hi)`` / ``range(lo, hi)`` into (lo_term, hi_term).
    ``range(lo, hi, step)`` is rejected (out of v0 spec). Endpoints must
    be int literals, unary-neg int literals, or bare identifiers.
    """
    if node.keywords:
        return None
    n = len(node.args)
    if n == 1:
        hi = _literal_int_or_var(node.args[0])
        if hi is None:
            return None
        return (num(0), hi)
    if n == 2:
        lo = _literal_int_or_var(node.args[0])
        hi = _literal_int_or_var(node.args[1])
        if lo is None or hi is None:
            return None
        return (lo, hi)
    return None


def _literal_int_or_var(node: ast.expr) -> Optional[Term]:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return num(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = node.operand
        if isinstance(inner, ast.Constant) and isinstance(inner.value, int) and not isinstance(inner.value, bool):
            return num(-inner.value)
        return None
    if isinstance(node, ast.Name):
        return make_var(node.id)
    return None


def _has_nested_for(stmt: ast.stmt) -> bool:
    """``stmt`` is the body[0] of the outer for-loop. A nested for-loop is
    either ``stmt`` itself (``for x in ...: for y in ...: ...``) OR a for
    anywhere inside its descendants (the body[0] is some other compound
    that contains a for).
    """
    if isinstance(stmt, ast.For):
        return True
    for sub in ast.walk(stmt):
        if isinstance(sub, ast.For):
            return True
    return False


# ---------------------------------------------------------------------------
# PATTERN 2: helper-inlined calls
# ---------------------------------------------------------------------------


@dataclass
class _HelperCall:
    helper_name: str
    arg: ast.expr


def _collect_helper_calls(
    stmts: Sequence[ast.stmt],
    helpers: Dict[str, _HelperDef],
) -> Optional[List[_HelperCall]]:
    """If every top-level stmt is a single-arg call to a known helper,
    return the list of calls. Otherwise None.
    """
    if not stmts:
        return None
    out: List[_HelperCall] = []
    for stmt in stmts:
        if not isinstance(stmt, ast.Expr):
            return None
        call = stmt.value
        if not isinstance(call, ast.Call):
            return None
        if not isinstance(call.func, ast.Name):
            return None
        callee = call.func.id
        if callee not in helpers:
            return None
        if call.keywords or len(call.args) != 1:
            return None
        out.append(_HelperCall(helper_name=callee, arg=call.args[0]))
    return out


def _classify_helper_inlining(
    calls: List[_HelperCall],
    helpers: Dict[str, _HelperDef],
    test_name: str,
    source_path: str,
    out: Layer2Output,
) -> None:
    out.claimed_tests.add(test_name)
    for i, call in enumerate(calls):
        out.seen += 1
        memento_name = f"{test_name}::call::{i}"
        helper = helpers[call.helper_name]
        try:
            arg_term = _translate_term(call.arg)
        except ValueError as e:
            out.helper_inlined_skipped += 1
            out.warnings.append(
                LiftWarning(source_path, memento_name,
                            f"layer2 helper-inline: argument not liftable: {e}")
            )
            continue
        try:
            raw = _lift_assertion_stmt(helper.assertion)
        except ValueError as e:
            out.helper_inlined_skipped += 1
            out.warnings.append(
                LiftWarning(source_path, memento_name,
                            f"layer2 helper-inline: helper `{call.helper_name}` body not liftable: {e}")
            )
            continue
        inlined = subst_var_in_formula(raw, helper.param_name, arg_term)
        out.decls.append(ContractDecl(name=memento_name, inv=inlined))
        out.lifted += 1
        out.helper_inlined_lifted += 1


# ---------------------------------------------------------------------------
# PATTERN 3: direct characterization asserts
# ---------------------------------------------------------------------------


def _formula_has_operator_dispatch(formula: Formula) -> bool:
    if isinstance(formula, _Atomic):
        if formula.name != "=" or not formula.args:
            return False
        lhs = formula.args[0]
        if not isinstance(lhs, _Ctor):
            return False
        return any(
            lhs.name.startswith(f"call:{operator_name}:")
            for operator_name in set(_OPERATOR_CALL_NAMES.values())
        )
    if isinstance(formula, _Connective):
        return any(_formula_has_operator_dispatch(operand) for operand in formula.operands)
    return False


def _single_assertion_is_operator_dispatch(stmt: ast.stmt) -> bool:
    try:
        return _formula_has_operator_dispatch(_lift_assertion_stmt(stmt))
    except ValueError:
        return False


def _classify_characterization(
    asserts: Sequence[ast.stmt],
    test_name: str,
    source_path: str,
    out: Layer2Output,
    *,
    allow_single_operator_dispatch: bool = False,
) -> None:
    out.claimed_tests.add(test_name)
    out.seen += 1

    atoms: List[Formula] = []
    skipped: List[str] = []
    lifted_pairs: List[Tuple[ast.stmt, Formula]] = []
    for i, stmt in enumerate(asserts):
        try:
            atom = _lift_assertion_stmt(stmt)
            atoms.append(atom)
            lifted_pairs.append((stmt, atom))
        except ValueError as e:
            skipped.append(f"#{i}: {e}")

    single_operator_dispatch = (
        allow_single_operator_dispatch
        and len(atoms) == 1
        and _formula_has_operator_dispatch(atoms[0])
    )
    if len(atoms) < 2 and not single_operator_dispatch:
        out.claimed_tests.discard(test_name)
        out.characterization_skipped += 1
        skip_detail = f"; skipped: {'; '.join(skipped)}" if skipped else ""
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        f"layer2 characterization: only {len(atoms)} of {len(asserts)} asserts were liftable; releasing to layer 0{skip_detail}")
        )
        return

    # UNIVERSE INJECTION (the pre-conjoined path): each single-call assert's
    # subject gets its callee's walked universes as extra conjuncts in the
    # SAME pre-conjoined inv -- one shared implementation with the
    # value-scope path, same contact rule. Injected AFTER the liftability
    # check so universes never rescue an otherwise-released test.
    universe_extras: List[Formula] = []
    source_warrants: List[dict] = []
    for stmt, atom in lifted_pairs:
        calls = _collect_assertion_calls(stmt)
        if len(calls) != 1:
            continue  # multi-call asserts keep point semantics (named v1 bound)
        origin = _call_origin_from_expr(calls[0])
        if origin is None:
            continue
        subject = _assertion_call_subject(atom)
        if subject is None:
            continue
        for conjunct in _universe_conjuncts(
            origin.callee,
            subject,
            out,
            source_path,
            test_name,
            source_warrants=source_warrants,
        ):
            if conjunct not in atoms and conjunct not in universe_extras:
                universe_extras.append(conjunct)
    atoms = atoms + universe_extras

    inv = atoms[0] if len(atoms) == 1 else and_(atoms)
    out.decls.append(
        ContractDecl(name=test_name, inv=inv, source_warrants=source_warrants)
    )
    out.lifted += 1
    out.characterization_lifted += 1
    if skipped:
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        f"layer2 characterization: {len(skipped)} atoms skipped from conjunction: {'; '.join(skipped)}")
        )


# ---------------------------------------------------------------------------
# PATTERN 4: @pytest.mark.parametrize
# ---------------------------------------------------------------------------


@dataclass
class _ParametrizeMark:
    """A literal-arg-list ``parametrize`` decorator we can lift."""
    param_names: List[str]   # ["x"] or ["x", "y"]
    rows: List[List[ast.expr]]   # each row is a list of arg exprs (one per param_name)


@dataclass
class _ParametrizePresence:
    """Records that a parametrize decorator is present, alongside the
    parsed mark (or None if the decorator is malformed / non-literal so
    we want the lift path to warn rather than silently fall through).
    """
    mark: Optional[_ParametrizeMark]
    reason: Optional[str]  # set when mark is None


def _find_parametrize(fn: ast.FunctionDef) -> Optional[_ParametrizePresence]:
    """Return None iff no parametrize decorator at all. Otherwise return
    a presence record; ``mark`` may be None when the decorator is present
    but its arg shape isn't liftable.
    """
    for dec in fn.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        if not _is_parametrize_attr(dec.func):
            continue
        if len(dec.args) < 2:
            return _ParametrizePresence(None, "parametrize: expected at least 2 positional args")
        names_node = dec.args[0]
        rows_node = dec.args[1]
        param_names = _parse_parametrize_names(names_node)
        if param_names is None:
            return _ParametrizePresence(None, "parametrize: param-names arg is not a literal string or list of strings")
        rows = _parse_parametrize_rows(rows_node, len(param_names))
        if rows is None:
            return _ParametrizePresence(None, "parametrize: row arg is not a literal list of leaf values")
        return _ParametrizePresence(_ParametrizeMark(param_names=param_names, rows=rows), None)
    return None


def _is_parametrize_attr(func: ast.expr) -> bool:
    # bare ``parametrize`` (rare)
    if isinstance(func, ast.Name) and func.id == "parametrize":
        return True
    # ``mark.parametrize``
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "parametrize"
        and isinstance(func.value, ast.Name)
        and func.value.id == "mark"
    ):
        return True
    # ``pytest.mark.parametrize``
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "parametrize"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "pytest"
    ):
        return True
    return False


def _parse_parametrize_names(node: ast.expr) -> Optional[List[str]]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        # "x" or "x, y" or "x,y"
        parts = [p.strip() for p in node.value.split(",")]
        parts = [p for p in parts if p]
        if not parts:
            return None
        return parts
    if isinstance(node, (ast.List, ast.Tuple)):
        out: List[str] = []
        for el in node.elts:
            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                out.append(el.value)
            else:
                return None
        return out or None
    return None


def _parse_parametrize_rows(node: ast.expr, n_params: int) -> Optional[List[List[ast.expr]]]:
    """Strictly literal-leaf rows: int / str / bool / None / unary-neg-int.
    A row containing a call (e.g., ``some_helper()``) is rejected here so
    the calling pattern can warn rather than silently lift a free-var Ctor
    that the verifier would later reject.
    """
    if not isinstance(node, ast.List):
        return None
    rows: List[List[ast.expr]] = []
    for el in node.elts:
        if n_params == 1:
            if not _is_literal_leaf(el):
                return None
            rows.append([el])
        else:
            if not isinstance(el, (ast.Tuple, ast.List)):
                return None
            if len(el.elts) != n_params:
                return None
            if not all(_is_literal_leaf(x) for x in el.elts):
                return None
            rows.append(list(el.elts))
    return rows


def _is_literal_leaf(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        v = node.value
        return isinstance(v, (int, str, bool)) or v is None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return (
            isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, int)
            and not isinstance(node.operand.value, bool)
        )
    return False


def _classify_parametrize(
    fn: ast.FunctionDef,
    body: Sequence[ast.stmt],
    pmark: _ParametrizeMark,
    test_name: str,
    source_path: str,
    out: Layer2Output,
) -> None:
    out.claimed_tests.add(test_name)
    out.seen += 1

    # Body must be ONE OR MORE liftable assertion statements (all asserts; bare
    # ``assert`` or unittest ``self.assertX``).  A non-assert statement (setup /
    # binding / loop) makes this a MIXED body — out of scope for the parametrize
    # pattern (that is Pattern-6 work) — so we loudly refuse.
    if not body or not all(_is_assertion_stmt(s) for s in body):
        out.parametrize_skipped += 1
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        "layer2 parametrize: body must be one or more liftable "
                        "assertions in v0 (a non-assert statement is a mixed "
                        "body, not lifted)")
        )
        return

    # Lift each assertion.  Unliftable asserts are recorded (partial lift): we
    # still lift the liftable SUBSET — a WEAKER but sound claim, since we never
    # assert more than we lifted — and emit a loud warning naming the skipped.
    atoms: List[Formula] = []
    skipped: List[str] = []
    for i, stmt in enumerate(body):
        try:
            atoms.append(_lift_assertion_stmt(stmt))
        except ValueError as e:
            skipped.append(f"#{i}: {e}")

    if not atoms:
        out.parametrize_skipped += 1
        skip_detail = f"; skipped: {'; '.join(skipped)}" if skipped else ""
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        f"layer2 parametrize: no liftable assertion in body{skip_detail}")
        )
        return

    if not pmark.rows:
        out.parametrize_skipped += 1
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        "layer2 parametrize: empty row list; nothing to lift")
        )
        return

    # WITHIN-ROW conjunction is SOUND: every assert in the body runs in the SAME
    # pytest instance for a given row, so they must all hold simultaneously ->
    # conjoin them.  A single surviving atom stays RAW (byte-stable with the v0
    # single-assert path); >=2 atoms are wrapped in ``and_``.
    raw = atoms[0] if len(atoms) == 1 else and_(atoms)

    # CROSS-ROW independence is preserved: each parametrize row is an INDEPENDENT
    # test instance, so we substitute each row into the (conjoined) template
    # independently and emit ONE ContractDecl per row named
    # ``<test>::parametrize::<params>::row<i>``.  A free non-param variable k is
    # NOT tied across rows (eq(k,1) and eq(k,2) live in separate decls), so the
    # verifier never false-refuses a consistent test.  Decls are staged locally
    # and committed only once every row substitutes cleanly (no partial emit).
    suffix = "_".join(pmark.param_names)
    row_decls: List[ContractDecl] = []
    for row_idx, row in enumerate(pmark.rows):
        f = raw
        failed = False
        for pname, arg_node in zip(pmark.param_names, row):
            try:
                arg_term = _translate_term(arg_node)
            except ValueError as e:
                out.parametrize_skipped += 1
                out.warnings.append(
                    LiftWarning(source_path, test_name,
                                f"layer2 parametrize: row {row_idx} arg not liftable: {e}")
                )
                failed = True
                break
            f = subst_var_in_formula(f, pname, arg_term)
        if failed:
            return
        memento_name = f"{test_name}::parametrize::{suffix}::row{row_idx}"
        row_decls.append(ContractDecl(name=memento_name, inv=f))

    out.decls.extend(row_decls)
    out.lifted += 1
    out.parametrize_lifted += 1
    if skipped:
        out.warnings.append(
            LiftWarning(source_path, test_name,
                        f"layer2 parametrize: {len(skipped)} assert(s) skipped "
                        f"from per-row conjunction: {'; '.join(skipped)}")
        )


# ---------------------------------------------------------------------------
# PATTERN 5: callsite-scoped value facts from tests
# ---------------------------------------------------------------------------


def _classify_value_scope(
    fn: ast.FunctionDef,
    body: Sequence[ast.stmt],
    test_name: str,
    source_path: str,
    source: str,
    out: Layer2Output,
) -> bool:
    scopes: List[_ValueScope] = [_ValueScope()]
    versions: Dict[str, int] = {}
    decls: List[ContractDecl] = []
    implications: List[ImplicationDecl] = []
    used_names: Set[str] = set()
    assertion_index = 0
    # Accumulate assertion formulas per call-site base so we can emit ONE
    # conjoined ::assertion contract per base (same shape as Pattern 3's
    # pre-conjoined ContractDecl). This is what makes same-subject
    # contradictions visible to the consistency pass without any CLI-side
    # conjoin logic: and(=(y,None), ≠(y,None)) lands in one memento -> UNSAT.
    # Order is preserved so the conjunction is deterministic.
    assertion_atoms_by_base: Dict[str, List[Formula]] = {}
    source_warrants_by_base: Dict[str, List[dict]] = {}
    base_order: List[str] = []

    for stmt in body:
        if _is_assertion_stmt(stmt):
            pairs = _collect_value_scope_assertion_facts(
                stmt,
                scopes,
                test_name,
                assertion_index,
                source_path,
                decls,
                implications,
                used_names,
                assertion_atoms_by_base,
                source_warrants_by_base,
                base_order,
                fn,
                source,
                out,
            )
            assertion_index += 1
            if pairs:
                continue
            if not decls:
                return False
            # FIX 2b — LOUD WARNING on silent value-scope assertion drop:
            # ``pairs == 0`` but ``decls`` is non-empty means a prior assertion
            # in this test produced callsite facts (so value_scope will claim
            # the test and return True), but THIS assertion has no tracked
            # call-origin in scope — e.g. ``assert MODULE_CONST == 5`` after
            # ``result = parse_int(...)`` — and the bare ``continue`` would
            # silently drop it.  Value_scope will claim the test so the Fix 2a
            # catch-all never fires; the drop is only visible here.
            # Emit a warning so nothing is silent (Δ=0).
            out.warnings.append(
                LiftWarning(
                    source_path,
                    test_name,
                    f"layer2 value-scope: assertion produced no callsite facts; "
                    f"not lifted (no tracked call-origin in scope): "
                    f"`{_unparse(stmt)[:80]}`",
                )
            )
            continue

        next_scopes = _apply_value_scope_statement(stmt, scopes, versions)
        if next_scopes is None:
            return False
        scopes = next_scopes

    if not implications:
        return False

    # Emit ONE conjoined ::assertion contract per call-site base.  Multiple
    # assertions about the same subject (e.g. both `assert y is None` and
    # `assert y is not None`) are conjoined here into a single inv so the
    # consistency pass sees the full fact set and can detect contradictions.
    for base in base_order:
        atoms = assertion_atoms_by_base[base]
        conjoined_inv = atoms[0] if len(atoms) == 1 else and_(atoms)
        assertion_name = f"{base}::assertion"
        decls.append(
            ContractDecl(
                name=assertion_name,
                inv=conjoined_inv,
                source_warrants=source_warrants_by_base.get(base, []),
            )
        )

    out.claimed_tests.add(test_name)
    out.seen += 1
    out.decls.extend(decls)
    out.implications.extend(implications)
    out.lifted += len(decls)
    out.value_scope_lifted += 1
    return True


def _apply_value_scope_statement(
    stmt: ast.stmt,
    scopes: List[_ValueScope],
    versions: Dict[str, int],
) -> Optional[List[_ValueScope]]:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            return None
        return _apply_value_scope_binding(stmt.targets[0].id, stmt.value, scopes, versions)

    if isinstance(stmt, ast.AnnAssign):
        if stmt.value is None or not isinstance(stmt.target, ast.Name):
            return None
        return _apply_value_scope_binding(stmt.target.id, stmt.value, scopes, versions)

    if isinstance(stmt, ast.If):
        return _apply_value_scope_if(stmt, scopes, versions)

    if isinstance(stmt, ast.Pass):
        return scopes

    return None


def _apply_value_scope_if(
    stmt: ast.If,
    scopes: List[_ValueScope],
    versions: Dict[str, int],
) -> Optional[List[_ValueScope]]:
    out: List[_ValueScope] = []
    for scope in scopes:
        guard = _lift_branch_guard(stmt.test, scope)

        then_scope = scope.copy()
        then_scope.facts.append(guard)
        then_scopes = _apply_value_scope_block(stmt.body, [then_scope], versions)
        if then_scopes is None:
            return None
        out.extend(then_scopes)

        else_scope = scope.copy()
        else_scope.facts.append(not_(guard))
        else_scopes = _apply_value_scope_block(stmt.orelse, [else_scope], versions)
        if else_scopes is None:
            return None
        out.extend(else_scopes or [else_scope])

    return out


def _apply_value_scope_block(
    stmts: Sequence[ast.stmt],
    scopes: List[_ValueScope],
    versions: Dict[str, int],
) -> Optional[List[_ValueScope]]:
    current = scopes
    for stmt in stmts:
        if _is_assertion_stmt(stmt):
            return None
        next_scopes = _apply_value_scope_statement(stmt, current, versions)
        if next_scopes is None:
            return None
        current = next_scopes
    return current


def _apply_value_scope_binding(
    name: str,
    value: ast.expr,
    scopes: List[_ValueScope],
    versions: Dict[str, int],
) -> List[_ValueScope]:
    out: List[_ValueScope] = []
    for scope in scopes:
        next_scope = scope.copy()
        origin = _call_origin_from_expr(value)
        constructor_args: Optional[Tuple[Term, ...]] = None
        constructor_default_params: Tuple[str, ...] = ()
        if (
            isinstance(value, ast.Call)
            and origin is not None
            and _is_constructor_call_name(origin.callee)
            and value.keywords
        ):
            constructor_mapping = _constructor_call_arg_mapping(
                value,
                origin.callee,
                scope,
            )
            if constructor_mapping is None:
                next_scope.current.pop(name, None)
                next_scope.projections.pop(name, None)
                next_scope.origins.pop(name, None)
                out.append(next_scope)
                continue
            constructor_args, constructor_default_params = constructor_mapping
            rhs = ctor(f"call:{origin.callee}", list(constructor_args))
        else:
            try:
                rhs = _translate_term_scoped(value, scope)
            except ValueError:
                next_scope.current.pop(name, None)
                next_scope.projections.pop(name, None)
                next_scope.origins.pop(name, None)
                out.append(next_scope)
                continue

        version = versions.get(name, 0)
        versions[name] = version + 1
        ssa_name = f"{name}${version}"
        ssa = make_var(ssa_name)
        next_scope.current[name] = ssa
        projections = _static_container_projection_map_from_expr(
            value,
            lambda element: _translate_term_scoped(element, scope),
        )
        if projections is not None:
            next_scope.projections[name] = projections
        else:
            next_scope.projections.pop(name, None)
        if origin is not None:
            if _is_constructor_call_name(origin.callee):
                try:
                    assert isinstance(value, ast.Call)
                    if constructor_args is None:
                        constructor_mapping = _constructor_call_arg_mapping(
                            value,
                            origin.callee,
                            scope,
                        )
                        if constructor_mapping is not None:
                            constructor_args, constructor_default_params = (
                                constructor_mapping
                            )
                        else:
                            constructor_args = tuple(
                                _translate_term_scoped(arg, scope)
                                for arg in value.args
                            )
                    origin.constructor_args = constructor_args
                    origin.constructor_default_params = constructor_default_params
                    origin.receiver_constructor = origin.callee
                    origin.ssa_name = ssa_name
                except (AssertionError, ValueError):
                    origin.constructor_args = None
                    origin.constructor_default_params = ()
                    origin.receiver_constructor = origin.callee
            else:
                # BINDING-FORM EUF SUBSTITUTION: check whether the RHS call has
                # ALL-CONCRETE literal args.  If so, compute the EUF ctor term and
                # store it alongside the SSA var name on the origin so
                # ``_assertion_callsite_context`` can substitute the EUF ctor for
                # the SSA var in the assertion formula.
                #
                # CARDINAL SOUNDNESS -- concrete-only rule:
                #   Concrete args (``r = f(5)``): EUF ctor keyed by (callee, args);
                #     ``assert r == 1`` becomes ``callresult_f_a1(5) == 1``.
                #   Symbolic args (``r = f(x)``): origin.euf_term stays None.
                #   ZERO-arg calls (``r = f()``): no input to unify on, so stay
                #     location-keyed/SSA-var.
                euf_term = _call_result_term(value, origin, scope, {})
                if isinstance(euf_term, _Ctor):
                    origin.arg_terms = tuple(euf_term.args)
                origin.result_term = ssa
                if (
                    euf_term is not None
                    and isinstance(euf_term, _Ctor)
                    and euf_term.args  # >=1 arg required (zero-arg -> no input to key on)
                    and _euf_args_all_concrete(euf_term)
                    and not callee_is_nondeterministic(origin.callee)
                ):
                    origin.arg_sig = _canonical_term_sig(euf_term)
                    origin.euf_term = euf_term
                    origin.ssa_name = ssa_name
            next_scope.origins[name] = origin
        else:
            next_scope.origins.pop(name, None)
        next_scope.facts.append(eq(ssa, rhs))
        out.append(next_scope)
    return out


def _constructor_call_arg_mapping(
    call: ast.Call,
    callee: str,
    scope: _ValueScope,
) -> Optional[Tuple[Tuple[Term, ...], Tuple[str, ...]]]:
    params = constructor_param_names_for_callee(callee)
    if params is None:
        if call.keywords:
            return None
        try:
            return (
                tuple(_translate_term_scoped(arg, scope) for arg in call.args),
                (),
            )
        except ValueError:
            return None
    defaults = constructor_param_defaults_for_callee(callee)
    if defaults is None:
        defaults = tuple(None for _ in params)
    if len(call.args) > len(params):
        return None
    terms: List[Optional[Term]] = [None for _ in params]
    try:
        for index, arg in enumerate(call.args):
            terms[index] = _translate_term_scoped(arg, scope)
        for keyword in call.keywords:
            if keyword.arg is None or keyword.arg not in params:
                return None
            index = params.index(keyword.arg)
            if terms[index] is not None:
                return None
            terms[index] = _translate_term_scoped(keyword.value, scope)
    except ValueError:
        return None
    defaulted: List[str] = []
    for index, term in enumerate(terms):
        if term is not None:
            continue
        default = defaults[index] if index < len(defaults) else None
        if default is None:
            return None
        terms[index] = _constructor_default_term(default)
        defaulted.append(params[index])
    return tuple(term for term in terms if term is not None), tuple(defaulted)


def _constructor_default_term(default: Tuple[object, str]) -> Term:
    value, kind = default
    if kind == "none":
        return ctor("None", [])
    if kind == "bool":
        return bool_const(bool(value))
    if kind == "int":
        return num(int(value))
    if kind == "str":
        return str_const(str(value))
    if kind == "bytes" and isinstance(value, bytes):
        return ctor("python:bytes", [str_const(value.decode("ascii"))])
    raise ValueError(f"unsupported constructor default kind: {kind}")


def _collect_value_scope_assertion_facts(
    stmt: ast.stmt,
    scopes: List[_ValueScope],
    test_name: str,
    assertion_index: int,
    source_path: str,
    decls: List[ContractDecl],
    implications: List[ImplicationDecl],
    used_names: Set[str],
    assertion_atoms_by_base: Dict[str, List[Formula]],
    source_warrants_by_base: Dict[str, List[dict]],
    base_order: List[str],
    fn: ast.FunctionDef,
    source: str,
    out: Layer2Output,
) -> int:
    """Collect ::facts contracts and implication wiring for one assertion
    statement.  The ::assertion contract itself is NOT emitted here; the
    caller (_classify_value_scope) emits ONE conjoined ::assertion per
    call-site base after processing all statements.  This keeps the kit
    dumb: it just admits facts; the conjunction (and all consistency
    checking) lives in the single conjoined invariant per base."""
    made = 0
    for scope in scopes:
        context = _assertion_callsite_context(stmt, scope)
        if context is None:
            continue
        origins, facts, assertion = context

        for origin in origins:
            base = _callsite_contract_base(origin, source_path)
            facts_name = _unique_contract_name(f"{base}::facts", used_names)
            implication_name = _unique_contract_name(
                f"{base}::facts-implies-assertion", used_names
            )
            assertion_name = f"{base}::assertion"
            fact_warrant = _source_memento_for_statement(
                fn,
                stmt,
                source_path,
                source,
                role="python.test-fact",
                claim_name=facts_name,
                contract_name=assertion_name,
            )
            fact_formula = facts[0] if len(facts) == 1 else and_(facts)
            fact_warrants = [fact_warrant] if fact_warrant is not None else []
            decls.append(
                ContractDecl(
                    name=facts_name,
                    inv=fact_formula,
                    source_warrants=fact_warrants,
                )
            )
            # Accumulate assertion formula for this base; the conjoined
            # ::assertion contract is emitted once at the end of
            # _classify_value_scope so all assertions about the same
            # call-site subject land in one inv.
            if base not in assertion_atoms_by_base:
                assertion_atoms_by_base[base] = []
                source_warrants_by_base[base] = []
                base_order.append(base)
            if fact_warrant is not None:
                _append_unique_source_warrant(
                    source_warrants_by_base[base],
                    fact_warrant,
                )
            assertion_atoms_by_base[base].append(assertion)
            # Wire the implication antecedent to the (not-yet-emitted)
            # conjoined assertion name; the contract will exist in the
            # same .proof bundle by the time the verifier loads it.
            implications.append(
                ImplicationDecl(
                    name=implication_name,
                    antecedent=facts_name,
                    consequent=assertion_name,
                    proof_witness=f"{test_name} assertion {assertion_index}",
                )
            )
            made += 1
            # TRANSLATE-UNIVERSE WALK (rung 2a): when the callee's installed
            # vendor body is translate-shaped, the universe atom is appended
            # INTO this base's conjoined ::assertion -- one more conjunct in
            # the existing conjoin, never a sibling contract. The verifier
            # conjoins by NAME: a separate ::universe decl verifies alone and
            # is vacuously consistent (live-fired and observed: the bad twin
            # DISCHARGED). The universal claim instantiates at this base's
            # concrete subject -- sound, since translate totality holds for
            # every input. Refused walks surface as loud warnings;
            # non-candidates stay silent by design.
            #
            # CONTACT RULE: the subject is extracted from THIS assertion's own
            # equality atom (the call-shaped side), never assumed from
            # origin.euf_term -- attribute-calls lift as callval terms while
            # the origin carries a callresult ctor, and a universe over a term
            # the assertion never mentions is vacuously SAT (the disjointness
            # failure). Same-statement extraction makes contact structural.
            # UNIVERSE CONJUNCTS (one shared implementation for every lift
            # path -- see _universe_conjuncts for the contact rule and the
            # per-family doctrine). Appended INTO this base's conjoined
            # ::assertion: the verifier conjoins by NAME, so a sibling decl
            # would verify alone and be vacuously consistent.
            subject_term = (
                _assertion_call_subject(assertion)
                or origin.euf_term
                or origin.result_term
            )
            subject_field_name: Optional[str] = None
            if subject_term is None:
                attribute_subject = _assertion_origin_attribute_subject(
                    assertion,
                    origin,
                )
                if attribute_subject is not None:
                    subject_term, subject_field_name = attribute_subject
            if subject_term is not None:
                for conjunct in _universe_conjuncts(
                    origin.callee,
                    subject_term,
                    out,
                    source_path,
                    test_name,
                    source_warrants=source_warrants_by_base[base],
                    origin=origin,
                    subject_field_name=subject_field_name,
                ):
                    if conjunct not in assertion_atoms_by_base[base]:
                        assertion_atoms_by_base[base].append(conjunct)
    return made


def _universe_conjuncts(
    callee: str,
    subject_term: Term,
    out: Layer2Output,
    source_path: str,
    test_name: str,
    source_warrants: Optional[List[dict]] = None,
    origin: Optional[_CallOrigin] = None,
    subject_field_name: Optional[str] = None,
    _seen: Optional[Set[Tuple[str, str]]] = None,
) -> List[Formula]:
    """Every walked universe for ``callee``, instantiated at
    ``subject_term`` -- the call-shaped side of the assertion's OWN equality
    atom (the contact rule: a universe over a term the assertion never
    mentions is vacuously SAT). Families: translate (chars-not-in-set),
    rstrip (negated suffix-of per char), table-loop (positive chars-in-set),
    table-subscript (membership disjunction), guard-then-raise (negated
    comparisons at the callsite's concrete args), return-constant
    (equality with the literal), return-predicate (ground-evaluated bool),
    and pure-delegation/identity (equality between call terms in EUF).
    Refused walks surface as loud warnings; non-candidates contribute
    nothing."""
    conjuncts: List[Formula] = []
    seen = _seen if _seen is not None else set()
    seen_key = (callee, _canonical_term_sig(subject_term))
    if seen_key in seen:
        return conjuncts
    seen.add(seen_key)
    universe, walk_refusal = translate_universe_for_callee(callee)
    if walk_refusal is not None:
        out.warnings.append(
            LiftWarning(
                source_path=source_path,
                item_name=f"{test_name}::translate-universe",
                reason=f"{walk_refusal.callee}: {walk_refusal.reason}",
            )
        )
    elif universe is not None:
        if universe.kind == "no-suffix-chars":
            conjuncts.extend(
                not_(atomic("suffix-of", [str_const(ch), subject_term]))
                for ch in universe.forbidden
            )
        elif universe.kind == "no-prefix-chars":
            conjuncts.extend(
                not_(atomic("prefix-of", [str_const(ch), subject_term]))
                for ch in universe.forbidden
            )
        elif universe.kind == "chars-in-set":
            conjuncts.append(
                atomic(
                    "str.chars-in-set",
                    [subject_term, str_const(universe.forbidden)],
                )
            )
        elif universe.kind == "member-of-values":
            conjuncts.append(
                or_([eq(subject_term, str_const(v)) for v in universe.values])
            )
        elif universe.kind == "prefix":
            # return-format: the output starts with the format's literal
            # prefix. prefix-of(prefix, subject).
            conjuncts.append(
                atomic(
                    "prefix-of",
                    [str_const(universe.forbidden), subject_term],
                )
            )
        else:
            conjuncts.append(
                atomic(
                    "str.chars-not-in-set",
                    [subject_term, str_const(universe.forbidden)],
                )
            )
        if source_warrants is not None and universe.source_memento is not None:
            _append_unique_source_warrant(
                source_warrants,
                _source_warrant_for_translate_universe(universe),
            )
        if isinstance(subject_term, _Ctor):
            call_args = (
                subject_term.args[1:]
                if subject_term.name.startswith("callval_")
                else subject_term.args
            )
            for prelude_call in universe.queued_calls:
                mapped = _mapped_delegate_args(prelude_call.args, call_args)
                if mapped is None:
                    continue
                head = _call_result_head(prelude_call.delegate, len(mapped))
                delegate_term = ctor(head, mapped)
                conjuncts.extend(
                    _universe_conjuncts(
                        prelude_call.delegate,
                        delegate_term,
                        out,
                        source_path,
                        test_name,
                        source_warrants=source_warrants,
                        _seen=seen,
                    )
                )

    # BRANCH-LITERAL DISJUNCTION (census non-return:If, 75k bodies, and
    # the multi-return residual of return-constant): every Return in the
    # body returns a same-kind literal and the body cannot fall off the
    # end, so the output is ONE OF the walked literals — no condition
    # evaluation needed. A consumer asserting any value outside the set
    # conjoins to UNSAT.
    branch_u, branch_refusal = branch_literal_universe_for_callee(callee)
    if branch_refusal is not None:
        out.warnings.append(
            LiftWarning(
                source_path=source_path,
                item_name=f"{test_name}::branch-literal-universe",
                reason=f"{branch_refusal.callee}: {branch_refusal.reason}",
            )
        )
    elif branch_u is not None:
        k = branch_u.value_kind
        if k == "int":
            mk = num
        elif k == "bool":
            mk = bool_const
        elif k == "str":
            mk = str_const
        else:  # bytes (walk admits ascii only)
            def mk(v):
                return ctor("python:bytes", [str_const(v.decode("ascii"))])
        conjuncts.append(
            or_([eq(subject_term, mk(v)) for v in branch_u.values])
        )

    # RAISE LOCUS (census non-return:Raise, 30k bodies): every path
    # through the body raises — no value exists, so ANY sworn equality
    # about this call carries the canonical contradiction 0 = 1: you
    # swore a return value from a call the vendor's own source says
    # always raises. (A consumer's pytest.raises expectation lifts
    # through the raises machinery, never through a value equality, so
    # it makes no contact with this conjunct.)
    raise_u, _raise_refusal = raise_locus_universe_for_callee(callee)
    if raise_u is not None:
        if source_warrants is not None and raise_u.source_memento is not None:
            _append_unique_source_warrant(
                source_warrants,
                _source_warrant_for_universe(
                    raise_u,
                    role="python.raise-locus-universe",
                    universe_kind="raise-locus",
                ),
            )
        conjuncts.append(eq(num(0), num(1)))

    branch_raise_u, branch_raise_refusal = branch_selected_raise_universe_for_callee(
        callee
    )
    if branch_raise_refusal is not None:
        out.warnings.append(
            LiftWarning(
                source_path=source_path,
                item_name=f"{test_name}::branch-selected-raise-universe",
                reason=f"{branch_raise_refusal.callee}: {branch_raise_refusal.reason}",
            )
        )
    elif branch_raise_u is not None and _branch_selected_raise_applies(
        branch_raise_u,
        subject_term,
        origin,
    ):
        if (
            source_warrants is not None
            and branch_raise_u.source_memento is not None
        ):
            _append_unique_source_warrant(
                source_warrants,
                _source_warrant_for_universe(
                    branch_raise_u,
                    role="python.branch-selected-raise-universe",
                    universe_kind="branch-selected-raise",
                ),
            )
        conjuncts.append(eq(num(0), num(1)))

    # RETURN-ISINSTANCE: the body returns `isinstance(expr, T)`, so the
    # function result is equivalent to the existing ProofIR isinstance
    # predicate instantiated over this callsite's argument terms. Unlike
    # guard/constant/predicate ground-eval families, this can make contact
    # with a location-keyed result Var as long as the origin carried arg terms.
    isinst_u, isinst_refusal = return_isinstance_universe_for_callee(callee)
    if isinst_refusal is not None:
        out.warnings.append(
            LiftWarning(
                source_path,
                f"{test_name}::return-isinstance-universe",
                reason=f"{isinst_refusal.callee}: {isinst_refusal.reason}",
            )
        )
    elif isinst_u is not None:
        try:
            isinst_conjuncts = _return_isinstance_universe_conjuncts(
                isinst_u,
                subject_term,
                _universe_call_args(subject_term, origin),
            )
        except ValueError as exc:
            out.warnings.append(
                LiftWarning(
                    source_path,
                    f"{test_name}::return-isinstance-universe",
                    reason=f"{callee}: {exc}",
                )
            )
            isinst_conjuncts = []
        if isinst_conjuncts:
            if source_warrants is not None and isinst_u.source_memento is not None:
                _append_unique_source_warrant(
                    source_warrants,
                    _source_warrant_for_universe(
                        isinst_u,
                        role="python.return-isinstance-universe",
                        universe_kind="return-isinstance",
                    ),
                )
            conjuncts.extend(isinst_conjuncts)

    regex_u, regex_refusal = return_regex_universe_for_callee(callee)
    if regex_refusal is not None:
        out.warnings.append(
            LiftWarning(
                source_path,
                f"{test_name}::regex-universe",
                reason=f"{regex_refusal.callee}: {regex_refusal.reason}",
            )
        )
    elif regex_u is not None:
        try:
            regex_conjuncts = _return_regex_universe_conjuncts(
                regex_u,
                subject_term,
                _universe_call_args(subject_term, origin),
            )
        except ValueError as exc:
            out.warnings.append(
                LiftWarning(
                    source_path,
                    f"{test_name}::regex-universe",
                    reason=f"{callee}: {exc}",
                )
            )
            regex_conjuncts = []
        if regex_conjuncts:
            if source_warrants is not None and regex_u.source_memento is not None:
                warrant = _source_warrant_for_universe(
                    regex_u,
                    role="python.regex-universe",
                    universe_kind="return-regex",
                )
                warrant["regex_pattern"] = regex_u.pattern
                warrant["regex_param_name"] = regex_u.param_name
                warrant["regex_match_kind"] = regex_u.match_kind
                warrant["regex_membership_pattern"] = regex_u.membership_pattern
                warrant["regex_true_implies_membership"] = (
                    regex_u.true_implies_membership
                )
                warrant["regex_false_implies_nonmembership"] = (
                    regex_u.false_implies_nonmembership
                )
                if regex_u.compile_var is not None:
                    warrant["regex_compile_var"] = regex_u.compile_var
                _append_unique_source_warrant(source_warrants, warrant)
            conjuncts.extend(regex_conjuncts)

    if isinstance(subject_term, _Ctor):
        guards, guard_refusal = guard_universe_for_callee(callee)
        if guard_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::guard-universe",
                    reason=f"{guard_refusal.callee}: {guard_refusal.reason}",
                )
            )
        elif guards is not None:
            call_args = (
                subject_term.args[1:]
                if subject_term.name.startswith("callval_")
                else subject_term.args
            )
            if source_warrants is not None and guards.source_memento is not None:
                warrant = _source_warrant_for_universe(
                    guards,
                    role="python.guard-universe",
                    universe_kind="guard",
                )
                warrant["guard_lines"] = list(guards.guard_lines)
                _append_unique_source_warrant(source_warrants, warrant)
            cmp_ctor = {"<": lt, "≤": lte, ">": gt, "≥": gte, "=": eq, "≠": ne}
            for clause in guards.clauses:
                if clause.param_index >= len(call_args):
                    continue
                arg_term = call_args[clause.param_index]
                if isinstance(clause.literal, int):
                    lit_term = num(clause.literal)
                elif isinstance(clause.literal, str):
                    lit_term = str_const(clause.literal)
                elif clause.literal is None:
                    lit_term = ctor("None", [])
                else:
                    continue
                conjuncts.append(not_(cmp_ctor[clause.op](arg_term, lit_term)))

        # RETURN-CONSTANT (census family, 34k bodies): the body
        # unconditionally returns one literal, so the output EQUALS it for
        # every input -- the strongest universal (equality, not membership).
        # Emit subject == <literal>; any consumer asserting another value
        # for any input refutes against it.
        const_u, const_refusal = constant_universe_for_callee(callee)
        if const_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::constant-universe",
                    reason=f"{const_refusal.callee}: {const_refusal.reason}",
                )
            )
        elif const_u is not None:
            if source_warrants is not None and const_u.source_memento is not None:
                _append_unique_source_warrant(
                    source_warrants,
                    _source_warrant_for_universe(
                        const_u,
                        role="python.constant-universe",
                        universe_kind="constant",
                    ),
                )
            k, v = const_u.value_kind, const_u.value
            if k == "int":
                lit = num(v)
            elif k == "bool":
                lit = bool_const(v)
            elif k == "str":
                lit = str_const(v)
            elif k == "none":
                lit = ctor("None", [])
            elif k == "bytes":
                lit = ctor("python:bytes", [str_const(v.decode("ascii"))])
            elif k == "collection":
                # v IS the canonical content string (one source of truth:
                # collection_literal_canonical), identical to the term the
                # consumer side builds for the same literal.
                lit = str_const(v)
            else:
                lit = None
            if lit is not None:
                conjuncts.append(eq(subject_term, lit))

        # RETURN-PREDICATE (census family, 24k bodies): the body returns a
        # pure boolean over its params. At THIS callsite's concrete args the
        # predicate ground-evaluates -- evaluating the vendor's own body at
        # the consumer's input, recompute not solver-invention -- so the
        # output EQUALS that bool. Emit subject == bool; a consumer asserting
        # the opposite truth value refutes.
        pred_u, pred_refusal = predicate_universe_for_callee(callee)
        if pred_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::predicate-universe",
                    reason=f"{pred_refusal.callee}: {pred_refusal.reason}",
                )
            )
        if pred_u is not None:
            call_args = (
                subject_term.args[1:]
                if subject_term.name.startswith("callval_")
                else subject_term.args
            )
            env = {}
            for i, pname in enumerate(pred_u.params):
                if i < len(call_args):
                    pv = _term_python_value(call_args[i])
                    if pv is not _PRED_MISSING:
                        env[pname] = pv
            result = eval_predicate(pred_u.expr, env)
            if result is not None:
                conjuncts.append(eq(subject_term, bool_const(result)))

        # BYTES IDENTITY ADAPTER: for want_bytes-style bodies, a concrete
        # python:bytes callsite takes the inactive str-encode branch and
        # returns the same value. Emit the existing compiler shape exactly:
        #   =(callresult_want_bytes_a1(python:bytes("abc")),
        #     python:bytes("abc"))
        bytes_u, bytes_refusal = bytes_identity_universe_for_callee(callee)
        if bytes_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::bytes-identity-universe",
                    reason=f"{bytes_refusal.callee}: {bytes_refusal.reason}",
                )
            )
        elif bytes_u is not None:
            call_args = (
                subject_term.args[1:]
                if subject_term.name.startswith("callval_")
                else subject_term.args
            )
            if bytes_u.param_index < len(call_args):
                arg = call_args[bytes_u.param_index]
                if _is_bytes_literal_term(arg):
                    if (
                        source_warrants is not None
                        and bytes_u.source_memento is not None
                    ):
                        _append_unique_source_warrant(
                            source_warrants,
                            _source_warrant_for_universe(
                                bytes_u,
                                role="python.bytes-identity-universe",
                                universe_kind="bytes-identity",
                            ),
                        )
                    conjuncts.append(eq(subject_term, arg))

        # LIST ADAPTER: for `_make_keys_list`-style helpers, concrete
        # str/bytes arguments take the scalar branch, while concrete
        # str/bytes sequence literals take the iterable list-comprehension
        # branch. In both cases the adapter's own universe is queued
        # recursively so concrete bytes collapse to the original bytes.
        list_u, list_refusal = list_adapter_universe_for_callee(callee)
        if list_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::list-adapter-universe",
                    reason=f"{list_refusal.callee}: {list_refusal.reason}",
                )
            )
        elif list_u is not None:
            call_args = (
                subject_term.args[1:]
                if subject_term.name.startswith("callval_")
                else subject_term.args
            )
            if list_u.param_index < len(call_args):
                arg = call_args[list_u.param_index]
                adapter_args: Tuple[Term, ...] = ()
                branch = ""
                if _is_str_or_bytes_literal_term(arg):
                    adapter_args = (arg,)
                    branch = "scalar"
                else:
                    sequence_elements = _str_bytes_sequence_literal_elements(arg)
                    if sequence_elements is not None:
                        adapter_args = sequence_elements
                        branch = "iterable"
                if adapter_args:
                    if (
                        source_warrants is not None
                        and list_u.source_memento is not None
                    ):
                        warrant = _source_warrant_for_universe(
                            list_u,
                            role="python.list-adapter-universe",
                            universe_kind="list-adapter",
                        )
                        warrant["list_adapter_branch"] = branch
                        _append_unique_source_warrant(
                            source_warrants,
                            warrant,
                        )
                    adapter_terms = [
                        ctor(
                            _call_result_head(list_u.adapter_callee, 1),
                            [adapter_arg],
                        )
                        for adapter_arg in adapter_args
                    ]
                    list_term = ctor("python:list", adapter_terms)
                    conjuncts.append(eq(subject_term, list_term))
                    for adapter_term in adapter_terms:
                        conjuncts.extend(
                            _universe_conjuncts(
                                list_u.adapter_callee,
                                adapter_term,
                                out,
                                source_path,
                                test_name,
                                source_warrants=source_warrants,
                                _seen=seen,
                            )
                        )

        # BRANCH-SELECTED RETURN OVER SELF FIELD: a constructor-backed receiver
        # field selects a method branch that returns one call argument. Emit the
        # existing implication/equality ProofIR shape:
        #   (self.field == "none") => (callval_derive_key(recv, x) == x)
        # The self.field term comes from the constructor-field universe for the
        # actual receiver constructor at this callsite.
        branch_ret_u, branch_ret_refusal = branch_selected_return_universe_for_callee(
            callee
        )
        if branch_ret_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::branch-selected-universe",
                    reason=f"{branch_ret_refusal.callee}: {branch_ret_refusal.reason}",
                )
            )
        elif (
            branch_ret_u is not None
            and origin is not None
            and origin.receiver_constructor is not None
            and origin.constructor_args is not None
        ):
            field_u, field_refusal = constructor_field_universe_for_callee(
                origin.receiver_constructor,
                branch_ret_u.field_name,
            )
            if field_refusal is not None:
                out.warnings.append(
                    LiftWarning(
                        source_path=source_path,
                        item_name=f"{test_name}::branch-selected-universe",
                        reason=f"{field_refusal.callee}: {field_refusal.reason}",
                    )
                )
            elif (
                field_u is not None
                and field_u.constructor_param_index < len(origin.constructor_args)
            ):
                call_args = _universe_call_args(subject_term, origin)
                selected_value = _universe_literal_term(
                    branch_ret_u.field_value_kind,
                    branch_ret_u.field_value,
                )
                if (
                    selected_value is not None
                    and branch_ret_u.return_param_index < len(call_args)
                ):
                    return_term = call_args[branch_ret_u.return_param_index]
                    return_adapter_callee = getattr(
                        branch_ret_u,
                        "return_adapter_callee",
                        None,
                    )
                    if return_adapter_callee:
                        if _is_none_term(return_term):
                            return_term = None
                        else:
                            return_term = ctor(
                                _call_result_head(return_adapter_callee, 1),
                                [return_term],
                            )
                    if return_term is not None:
                        field_term = _constructor_field_universe_value_term(
                            subject_term,
                            branch_ret_u.field_name,
                            field_u,
                            origin,
                        )
                        if source_warrants is not None:
                            _append_unique_source_warrant(
                                source_warrants,
                                _source_warrant_for_branch_selected_universe(
                                    branch_ret_u
                                ),
                            )
                            _append_unique_source_warrant(
                                source_warrants,
                                _source_warrant_for_instance_field_universe(
                                    field_u,
                                    source_memento=field_u.constructor_source_memento,
                                    source_function_name=_local_qualname(
                                        field_u.module,
                                        field_u.constructor_qualname,
                                    ),
                                    constructor_default_params=tuple(
                                        param
                                        for param in origin.constructor_default_params
                                        if param == field_u.constructor_param_name
                                    ),
                                ),
                            )
                        conjuncts.append(
                            implies(
                                eq(field_term, selected_value),
                                eq(
                                    subject_term,
                                    return_term,
                                ),
                            )
                        )
                        if return_adapter_callee and isinstance(return_term, _Ctor):
                            conjuncts.extend(
                                _universe_conjuncts(
                                    return_adapter_callee,
                                    return_term,
                                    out,
                                    source_path,
                                    test_name,
                                    source_warrants=source_warrants,
                                    _seen=seen,
                                )
                            )

        # CONDITIONAL SSA CHAIN: branch guards select assignment values before
        # the final return. Emit the same implication/equality ProofIR shape
        # used by branch-selected receiver-field universes, but with guard
        # and return terms read from the vendor's straight-line source.
        conditional_u, conditional_refusal = conditional_chain_universe_for_callee(
            callee
        )
        if conditional_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::conditional-chain-universe",
                    reason=(
                        f"{conditional_refusal.callee}: "
                        f"{conditional_refusal.reason}"
                    ),
                )
            )
        elif conditional_u is not None:
            if (
                source_warrants is not None
                and conditional_u.source_memento is not None
            ):
                _append_unique_source_warrant(
                    source_warrants,
                    _source_warrant_for_universe(
                        conditional_u,
                        role="python.conditional-chain-universe",
                        universe_kind=conditional_u.kind,
                    ),
                )
            call_args = _conditional_chain_universe_call_args(
                conditional_u,
                subject_term,
                origin,
            )
            receiver_term = _receiver_term_for_callval_subject(subject_term)
            for branch in conditional_u.branches:
                branch_formula = _conditional_chain_condition_formula(
                    branch.conditions,
                    call_args,
                    receiver_term=receiver_term,
                    origin=origin,
                    subject_term=subject_term,
                )
                mapped_expr = _expr_spec_term_and_queued(
                    branch.expr_spec,
                    call_args,
                    receiver_term=receiver_term,
                    origin=origin,
                    subject_term=subject_term,
                    receiver_context=False,
                )
                if branch_formula is None or mapped_expr is None:
                    continue
                term, nested_delegates, field_terms, _term_kind = mapped_expr
                condition_field_terms = _conditional_chain_condition_field_terms(
                    branch.conditions,
                    origin,
                    subject_term,
                )
                conjuncts.append(implies(branch_formula, eq(subject_term, term)))
                for field_u, _field_term in condition_field_terms:
                    if source_warrants is not None:
                        _append_unique_source_warrant(
                            source_warrants,
                            _source_warrant_for_instance_field_universe(
                                field_u,
                                source_memento=field_u.constructor_source_memento,
                                source_function_name=_local_qualname(
                                    field_u.module,
                                    field_u.constructor_qualname,
                                ),
                                constructor_default_params=tuple(
                                    param
                                    for param in (
                                        origin.constructor_default_params
                                        if origin is not None
                                        else ()
                                    )
                                    if param == field_u.constructor_param_name
                                ),
                            ),
                        )
                for field_u, field_term in field_terms:
                    if source_warrants is not None:
                        _append_unique_source_warrant(
                            source_warrants,
                            _source_warrant_for_instance_field_universe(
                                field_u,
                                source_memento=field_u.constructor_source_memento,
                                source_function_name=_local_qualname(
                                    field_u.module,
                                    field_u.constructor_qualname,
                                ),
                                constructor_default_params=tuple(
                                    param
                                    for param in (
                                        origin.constructor_default_params
                                        if origin is not None
                                        else ()
                                    )
                                    if param == field_u.constructor_param_name
                                ),
                            ),
                        )
                    for recursive_callee in _constructor_field_recursive_callees(
                        field_u,
                        field_term,
                    ):
                        conjuncts.extend(
                            _universe_conjuncts(
                                recursive_callee,
                                field_term,
                                out,
                                source_path,
                                test_name,
                                source_warrants=source_warrants,
                                _seen=seen,
                            )
                        )
                for nested_delegate, nested_args, nested_term in nested_delegates:
                    nested_origin = _receiver_delegate_origin(
                        nested_delegate,
                        origin,
                        nested_args,
                        nested_term,
                    )
                    conjuncts.extend(
                        _universe_conjuncts(
                            nested_delegate,
                            nested_term,
                            out,
                            source_path,
                            test_name,
                            source_warrants=source_warrants,
                            origin=nested_origin,
                            _seen=seen,
                        )
                    )

        # PURE-DELEGATION + IDENTITY (census families, 57k + the param arm
        # of return-name's 146k): the body forwards verbatim, so the
        # output EQUALS the forwarded term — eq between call terms in EUF,
        # zero new atoms. The delegate term uses the SAME callresult head
        # a consumer's direct call builds, so claims about f and claims
        # about g meet in one term and contradictions THROUGH the
        # delegation edge conjoin and fire UNSAT.
        deleg_u, deleg_refusal = delegation_universe_for_callee(callee)
        if deleg_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::delegation-universe",
                    reason=f"{deleg_refusal.callee}: {deleg_refusal.reason}",
                )
            )
        elif deleg_u is not None:
            if source_warrants is not None and deleg_u.source_memento is not None:
                _append_unique_source_warrant(
                    source_warrants,
                    _source_warrant_for_universe(
                        deleg_u,
                        role="python.delegation-universe",
                        universe_kind=deleg_u.kind,
                    ),
                )
            call_args = _delegation_universe_call_args(deleg_u, subject_term)
            if deleg_u.kind == "identity":
                if deleg_u.param_index < len(call_args):
                    conjuncts.append(
                        eq(subject_term, call_args[deleg_u.param_index])
                    )
            elif deleg_u.kind == "delegation-splat":
                head = _call_result_head(deleg_u.delegate, len(call_args))
                delegate_term = ctor(head, list(call_args))
                conjuncts.append(eq(subject_term, delegate_term))
                conjuncts.extend(
                    _universe_conjuncts(
                        deleg_u.delegate,
                        delegate_term,
                        out,
                        source_path,
                        test_name,
                        source_warrants=source_warrants,
                        _seen=seen,
                    )
                )
            elif deleg_u.kind == "chain-expr":
                # arithmetic/concat structure: + - * / % use the same term
                # shape as the consumer side. A + whose callsite leaves are
                # string/bytes-compatible lowers to the existing str.++
                # ProofIR op instead of the Int + op.
                receiver_term = _receiver_term_for_callval_subject(subject_term)
                mapped_expr = _expr_spec_term_and_queued(
                    deleg_u.expr_spec,
                    call_args,
                    receiver_term=receiver_term,
                    origin=origin,
                    subject_term=subject_term,
                    receiver_context=False,
                )
                if mapped_expr is not None:
                    term, nested_delegates, field_terms, _term_kind = mapped_expr
                    if _chain_expr_emittable_term(term):
                        conjuncts.append(eq(subject_term, term))
                        for field_u, field_term in field_terms:
                            if source_warrants is not None:
                                _append_unique_source_warrant(
                                    source_warrants,
                                    _source_warrant_for_instance_field_universe(
                                        field_u,
                                        source_memento=field_u.constructor_source_memento,
                                        source_function_name=_local_qualname(
                                            field_u.module,
                                            field_u.constructor_qualname,
                                        ),
                                        constructor_default_params=tuple(
                                            param
                                            for param in (
                                                origin.constructor_default_params
                                                if origin is not None
                                                else ()
                                            )
                                            if param == field_u.constructor_param_name
                                        ),
                                    ),
                                )
                                _append_constructor_field_projection_source_warrant(
                                    source_warrants,
                                    field_u,
                                    origin,
                                )
                            for recursive_callee in _constructor_field_recursive_callees(
                                field_u,
                                field_term,
                            ):
                                conjuncts.extend(
                                    _universe_conjuncts(
                                        recursive_callee,
                                        field_term,
                                        out,
                                        source_path,
                                        test_name,
                                        source_warrants=source_warrants,
                                        _seen=seen,
                                    )
                                )
                        for nested_delegate, nested_args, nested_term in nested_delegates:
                            nested_origin = _receiver_delegate_origin(
                                nested_delegate,
                                origin,
                                nested_args,
                                nested_term,
                            )
                            conjuncts.extend(
                                _universe_conjuncts(
                                    nested_delegate,
                                    nested_term,
                                    out,
                                    source_path,
                                    test_name,
                                    source_warrants=source_warrants,
                                    origin=nested_origin,
                                    _seen=seen,
                                )
                            )
            elif deleg_u.kind == "chain-constant":
                # `x = 5; return x`: the chain resolves the returned
                # name to a literal — the output EQUALS it, no delegate
                mapped = _mapped_delegate_args(deleg_u.args, call_args)
                if mapped is not None:
                    conjuncts.append(eq(subject_term, mapped[0]))
            elif deleg_u.kind == "delegation-receiver-method":
                receiver_term = _receiver_term_for_callval_subject(subject_term)
                mapped_and_queued = (
                    _mapped_receiver_delegate_args_and_queued(
                        deleg_u.args,
                        call_args,
                        receiver_term,
                    )
                    if receiver_term is not None
                    else None
                )
                if mapped_and_queued is not None:
                    mapped, nested_delegates = mapped_and_queued
                    delegate_args = [receiver_term, *mapped]
                    method_name = deleg_u.delegate.rsplit(".", 1)[-1]
                    head = _callval_head(method_name, len(delegate_args))
                    delegate_term = ctor(head, delegate_args)
                    conjuncts.append(eq(subject_term, delegate_term))
                    for nested_delegate, nested_args, nested_term in nested_delegates:
                        nested_origin = _receiver_delegate_origin(
                            nested_delegate,
                            origin,
                            nested_args,
                            nested_term,
                        )
                        conjuncts.extend(
                            _universe_conjuncts(
                                nested_delegate,
                                nested_term,
                                out,
                                source_path,
                                test_name,
                                source_warrants=source_warrants,
                                origin=nested_origin,
                                _seen=seen,
                            )
                        )
                    delegate_origin = _receiver_delegate_origin(
                        deleg_u.delegate,
                        origin,
                        mapped,
                        delegate_term,
                    )
                    conjuncts.extend(
                        _universe_conjuncts(
                            deleg_u.delegate,
                            delegate_term,
                            out,
                            source_path,
                            test_name,
                            source_warrants=source_warrants,
                            origin=delegate_origin,
                            _seen=seen,
                        )
                    )
            else:
                receiver_term = _receiver_term_for_callval_subject(subject_term)
                mapped_and_queued = _mapped_delegate_args_and_queued(
                    deleg_u.args,
                    call_args,
                    receiver_term,
                )
                mapped = (
                    None if mapped_and_queued is None else mapped_and_queued[0]
                )
                if mapped is not None and deleg_u.kind in {
                    "delegation",
                    "delegation-stdlib",
                }:
                    head = _call_result_head(deleg_u.delegate, len(mapped))
                    delegate_term = ctor(head, mapped)
                    conjuncts.append(eq(subject_term, delegate_term))
                    for nested_delegate, nested_args, nested_term in (
                        mapped_and_queued[1]
                    ):
                        nested_origin = _receiver_delegate_origin(
                            nested_delegate,
                            origin,
                            nested_args,
                            nested_term,
                        )
                        conjuncts.extend(
                            _universe_conjuncts(
                                nested_delegate,
                                nested_term,
                                out,
                                source_path,
                                test_name,
                                source_warrants=source_warrants,
                                origin=nested_origin,
                                _seen=seen,
                            )
                        )
                    if deleg_u.kind == "delegation":
                        conjuncts.extend(
                            _universe_conjuncts(
                                deleg_u.delegate,
                                delegate_term,
                                out,
                                source_path,
                                test_name,
                                source_warrants=source_warrants,
                                _seen=seen,
                            )
                        )
                elif mapped is not None:  # delegation-method
                    # No vendor body backs a method delegate (the
                    # receiver's type is not static), so the equality
                    # only bridges GROUND instantiations: every mapped
                    # term — receiver included — must be a concrete
                    # literal, the same discipline
                    # _euf_args_all_concrete enforces for cross-location
                    # unification.
                    head = _callval_head(deleg_u.delegate, len(mapped))
                    term = ctor(head, mapped)
                    if _euf_args_all_concrete(term):
                        conjuncts.append(eq(subject_term, term))

        sep_guard_u, sep_guard_refusal = separator_guard_raise_universe_for_callee(
            callee
        )
        if sep_guard_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::separator-guard-raise-universe",
                    reason=(
                        f"{sep_guard_refusal.callee}: "
                        f"{sep_guard_refusal.reason}"
                    ),
                )
            )
        elif sep_guard_u is not None:
            conjuncts.extend(
                _separator_guard_raise_conjuncts(
                    sep_guard_u,
                    subject_term,
                    out,
                    source_path,
                    test_name,
                    source_warrants,
                    origin,
                    seen,
                )
            )

        exception_bool_u, exception_bool_refusal = (
            exception_bool_return_universe_for_callee(callee)
        )
        if exception_bool_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::exception-bool-return-universe",
                    reason=(
                        f"{exception_bool_refusal.callee}: "
                        f"{exception_bool_refusal.reason}"
                    ),
                )
            )
        elif exception_bool_u is not None:
            if (
                source_warrants is not None
                and exception_bool_u.source_memento is not None
            ):
                _append_unique_source_warrant(
                    source_warrants,
                    _source_warrant_for_universe(
                        exception_bool_u,
                        role="python.exception-bool-return-universe",
                        universe_kind="exception-bool-return",
                    ),
                )
            inner_call = _exception_bool_inner_call(
                exception_bool_u,
                subject_term,
            )
            if inner_call is not None:
                inner_call_term, mapped_args = inner_call
                raised_term = ctor("raised_exc_a1", [inner_call_term])
                caught = eq(raised_term, str_const(exception_bool_u.exception_name))
                exception_result = eq(
                    subject_term,
                    bool_const(exception_bool_u.exception_value),
                )
                success_result = eq(
                    subject_term,
                    bool_const(exception_bool_u.success_value),
                )
                conjuncts.extend(
                    [
                        implies(exception_result, caught),
                        implies(caught, exception_result),
                        implies(success_result, not_(caught)),
                    ]
                )
                nested_origin = _receiver_delegate_origin(
                    exception_bool_u.delegate,
                    origin,
                    mapped_args,
                    inner_call_term,
                )
                conjuncts.extend(
                    _universe_conjuncts(
                        exception_bool_u.delegate,
                        inner_call_term,
                        out,
                        source_path,
                        test_name,
                        source_warrants=source_warrants,
                        origin=nested_origin,
                        _seen=seen,
                    )
                )

        # INSTANCE FIELD GETTER: the source pair
        # ``__init__: self.a = value`` and ``get: return self.a`` maps the
        # method result to the observed constructor argument at this callsite.
        inst_u, inst_refusal = instance_field_universe_for_callee(callee)
        if inst_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::instance-field-universe",
                    reason=f"{inst_refusal.callee}: {inst_refusal.reason}",
                )
            )
        elif (
            inst_u is not None
            and origin is not None
            and origin.receiver_constructor is not None
            and origin.constructor_args is not None
        ):
            constructor_callee = inst_u.constructor_qualname.removesuffix(
                ".__init__"
            )
            if (
                origin.receiver_constructor == constructor_callee
                and inst_u.constructor_param_index < len(origin.constructor_args)
            ):
                value_term = _constructor_field_universe_value_term(
                    subject_term,
                    inst_u.field_name,
                    inst_u,
                    origin,
                )
                if source_warrants is not None:
                    _append_unique_source_warrant(
                        source_warrants,
                        _source_warrant_for_instance_field_universe(
                            inst_u,
                            source_memento=inst_u.constructor_source_memento,
                            source_function_name=_local_qualname(
                                inst_u.module,
                                inst_u.constructor_qualname,
                            ),
                            constructor_default_params=tuple(
                                param
                                for param in origin.constructor_default_params
                                if param == inst_u.constructor_param_name
                            ),
                        ),
                    )
                    _append_unique_source_warrant(
                        source_warrants,
                        _source_warrant_for_instance_field_universe(
                            inst_u,
                            source_memento=inst_u.source_memento,
                            source_function_name=_local_qualname(
                                inst_u.module,
                                inst_u.qualname,
                            ),
                        ),
                    )
                    _append_constructor_field_projection_source_warrant(
                        source_warrants,
                        inst_u,
                        origin,
                    )
                conjuncts.append(eq(subject_term, value_term))
                for recursive_callee in _constructor_field_recursive_callees(
                    inst_u,
                    value_term,
                ):
                    conjuncts.extend(
                        _universe_conjuncts(
                            recursive_callee,
                            value_term,
                            out,
                            source_path,
                            test_name,
                            source_warrants=source_warrants,
                            _seen=seen,
                        )
                    )
    if (
        subject_field_name is not None
        and origin is not None
        and origin.constructor_args is not None
    ):
        field_u, field_refusal = constructor_field_universe_for_callee(
            callee,
            subject_field_name,
        )
        if field_refusal is not None:
            out.warnings.append(
                LiftWarning(
                    source_path=source_path,
                    item_name=f"{test_name}::instance-field-universe",
                    reason=f"{field_refusal.callee}: {field_refusal.reason}",
                )
            )
        elif (
            field_u is not None
            and field_u.constructor_param_index < len(origin.constructor_args)
        ):
            value_term = _constructor_field_universe_value_term(
                subject_term,
                field_u.field_name,
                field_u,
                origin,
            )
            if source_warrants is not None:
                _append_unique_source_warrant(
                    source_warrants,
                    _source_warrant_for_instance_field_universe(
                        field_u,
                        source_memento=field_u.constructor_source_memento,
                        source_function_name=_local_qualname(
                            field_u.module,
                            field_u.constructor_qualname,
                        ),
                        constructor_default_params=tuple(
                            param
                            for param in origin.constructor_default_params
                            if param == field_u.constructor_param_name
                        ),
                    ),
                )
                forwarder_memento = getattr(field_u, "forwarder_source_memento", None)
                forwarder_qualname = getattr(
                    field_u,
                    "forwarder_constructor_qualname",
                    None,
                )
                if forwarder_memento is not None and forwarder_qualname is not None:
                    _append_unique_source_warrant(
                        source_warrants,
                        _source_warrant_for_instance_field_universe(
                            field_u,
                            source_memento=forwarder_memento,
                            source_function_name=_local_qualname(
                                field_u.module,
                                forwarder_qualname,
                            ),
                        ),
                    )
            conjuncts.append(eq(subject_term, value_term))
            for recursive_callee in _constructor_field_recursive_callees(
                field_u,
                value_term,
            ):
                conjuncts.extend(
                    _universe_conjuncts(
                        recursive_callee,
                        value_term,
                        out,
                        source_path,
                        test_name,
                        source_warrants=source_warrants,
                        _seen=seen,
                    )
                )
        if field_refusal is None and field_u is None:
            property_callee = f"{callee}.{subject_field_name}"
            property_u, property_refusal = instance_field_universe_for_callee(
                property_callee
            )
            if property_refusal is not None:
                out.warnings.append(
                    LiftWarning(
                        source_path=source_path,
                        item_name=f"{test_name}::instance-field-universe",
                        reason=f"{property_refusal.callee}: {property_refusal.reason}",
                    )
                )
            elif property_u is not None and property_u.constructor_param_index < len(
                origin.constructor_args
            ):
                constructor_callee = property_u.constructor_qualname.removesuffix(
                    ".__init__"
                )
                if constructor_callee == callee:
                    value_term = _constructor_field_universe_value_term(
                        subject_term,
                        property_u.field_name,
                        property_u,
                        origin,
                    )
                    if source_warrants is not None:
                        _append_unique_source_warrant(
                            source_warrants,
                            _source_warrant_for_instance_field_universe(
                                property_u,
                                source_memento=property_u.constructor_source_memento,
                                source_function_name=_local_qualname(
                                    property_u.module,
                                    property_u.constructor_qualname,
                                ),
                                constructor_default_params=tuple(
                                    param
                                    for param in origin.constructor_default_params
                                    if param == property_u.constructor_param_name
                                ),
                            ),
                        )
                        _append_unique_source_warrant(
                            source_warrants,
                            _source_warrant_for_instance_field_universe(
                                property_u,
                                source_memento=property_u.source_memento,
                                source_function_name=_local_qualname(
                                    property_u.module,
                                    property_u.qualname,
                                ),
                            ),
                        )
                        _append_constructor_field_projection_source_warrant(
                            source_warrants,
                            property_u,
                            origin,
                        )
                    conjuncts.append(eq(subject_term, value_term))
                    for recursive_callee in _constructor_field_recursive_callees(
                        property_u,
                        value_term,
                    ):
                        conjuncts.extend(
                            _universe_conjuncts(
                                recursive_callee,
                                value_term,
                                out,
                                source_path,
                                test_name,
                                source_warrants=source_warrants,
                                _seen=seen,
                            )
                        )
    return conjuncts


def _universe_call_args(
    subject_term: Term,
    origin: Optional[_CallOrigin],
) -> Tuple[Term, ...]:
    if origin is not None and origin.arg_terms is not None:
        return origin.arg_terms
    if isinstance(subject_term, _Ctor):
        if subject_term.name.startswith("callval_"):
            return tuple(subject_term.args[1:])
        if subject_term.name.startswith("callresult_"):
            return tuple(subject_term.args)
    return ()


def _conditional_chain_universe_call_args(
    universe,
    subject_term: Term,
    origin: Optional[_CallOrigin],
) -> Tuple[Term, ...]:
    source_memento = getattr(universe, "source_memento", None) or {}
    param_names = source_memento.get("param_names") or ()
    if (
        param_names
        and param_names[0] in {"self", "cls"}
        and isinstance(subject_term, _Ctor)
        and subject_term.name.startswith("callval_")
    ):
        return tuple(subject_term.args)
    return _universe_call_args(subject_term, origin)


def _universe_literal_term(value_kind: str, value: Any) -> Optional[Term]:
    if value_kind == "int":
        return num(value)
    if value_kind == "bool":
        return bool_const(value)
    if value_kind == "str":
        return str_const(value)
    if value_kind == "none":
        return ctor("None", [])
    if value_kind == "bytes":
        try:
            return ctor("python:bytes", [str_const(value.decode("ascii"))])
        except UnicodeDecodeError:
            return None
    if value_kind == "collection" and isinstance(value, str):
        return str_const(value)
    return None


def _branch_selected_raise_applies(
    universe,
    subject_term: Term,
    origin: Optional[_CallOrigin],
) -> bool:
    call_args = _universe_call_args(subject_term, origin)
    if universe.param_index >= len(call_args):
        return False
    value = _term_python_value(call_args[universe.param_index])
    if value is _PRED_MISSING:
        return False
    return value != universe.excluded_value


def _delegation_universe_call_args(
    universe,
    subject_term: Term,
) -> Tuple[Term, ...]:
    if not isinstance(subject_term, _Ctor):
        return ()
    if not subject_term.name.startswith("callval_"):
        return tuple(subject_term.args)
    if universe.kind == "delegation-receiver-method":
        return tuple(subject_term.args[1:])
    source_memento = getattr(universe, "source_memento", None) or {}
    param_names = source_memento.get("param_names") or ()
    if param_names and param_names[0] in {"self", "cls"}:
        return tuple(subject_term.args)
    return tuple(subject_term.args[1:])


def _return_isinstance_universe_conjuncts(
    universe,
    subject_term: Term,
    call_args: Tuple[Term, ...],
) -> List[Formula]:
    param_terms = {
        param_name: call_args[index]
        for index, param_name in enumerate(universe.params)
        if index < len(call_args)
    }
    missing = sorted(
        {
            node.id
            for node in ast.walk(universe.expr)
            if isinstance(node, ast.Name)
            and node.id in universe.params
            and node.id not in param_terms
        }
    )
    if missing:
        raise ValueError(
            "return-isinstance: missing callsite terms for params "
            + ", ".join(missing)
        )
    scope = _ValueScope(current=param_terms)

    def _term(node: ast.expr) -> Term:
        return _translate_term_scoped(node, scope)

    predicate = _translate_truthiness_call_formula(universe.expr, _term)
    return [
        implies(eq(subject_term, bool_const(True)), predicate),
        implies(eq(subject_term, bool_const(False)), not_(predicate)),
    ]


def _return_regex_universe_conjuncts(
    universe,
    subject_term: Term,
    call_args: Tuple[Term, ...],
) -> List[Formula]:
    if universe.param_index >= len(call_args):
        raise ValueError(
            "return-regex: missing callsite term for param "
            + universe.param_name
        )
    predicate = atomic(
        "str.in-regex",
        [call_args[universe.param_index], str_const(universe.membership_pattern)],
    )
    conjuncts: List[Formula] = []
    if universe.true_implies_membership:
        conjuncts.append(implies(eq(subject_term, bool_const(True)), predicate))
    if universe.false_implies_nonmembership:
        conjuncts.append(implies(eq(subject_term, bool_const(False)), not_(predicate)))
    return conjuncts


def _constructor_field_universe_value_term(
    subject_term: Term,
    field_name: str,
    universe,
    origin: _CallOrigin,
) -> Term:
    arg_term = origin.constructor_args[universe.constructor_param_index]
    default_literal_kind = getattr(universe, "constructor_default_literal_kind", None)
    if default_literal_kind:
        if (
            universe.constructor_param_name in origin.constructor_default_params
            or _is_none_term(arg_term)
        ):
            default_term = _universe_literal_term(
                default_literal_kind,
                getattr(universe, "constructor_default_literal", None),
            )
            if default_term is not None:
                return _constructor_field_projection_term(
                    universe,
                    default_term,
                    origin,
                )
        return _constructor_field_projection_term(
            universe,
            _constructor_field_adapter_term(universe, arg_term),
            origin,
        )
    default_attr_name = getattr(universe, "constructor_default_attr_name", None)
    if not default_attr_name:
        return _constructor_field_projection_term(
            universe,
            _constructor_field_adapter_term(universe, arg_term),
            origin,
        )
    if (
        universe.constructor_param_name not in origin.constructor_default_params
        and not _is_none_term(arg_term)
    ):
        return _constructor_field_projection_term(
            universe,
            _constructor_field_adapter_term(universe, arg_term),
            origin,
        )
    receiver_name = _receiver_name_for_constructor_field_subject(
        subject_term,
        field_name,
    )
    if receiver_name is None:
        return _constructor_field_projection_term(
            universe,
            _constructor_field_adapter_term(universe, arg_term),
            origin,
        )
    return _constructor_field_projection_term(
        universe,
        make_var(f"{receiver_name}.{default_attr_name}"),
        origin,
    )


def _constructor_field_projection_term(
    universe,
    field_term: Term,
    origin: _CallOrigin,
) -> Term:
    projection = getattr(universe, "field_projection", None)
    if not projection:
        return field_term
    projection_kind, index = projection
    if projection_kind != "index":
        return field_term
    projected = _project_list_adapter_index_term(universe, origin, int(index))
    if projected is not None:
        return projected
    return ctor("index", [field_term, num(int(index))])


def _project_list_adapter_index_term(
    universe,
    origin: _CallOrigin,
    index: int,
) -> Optional[Term]:
    helper_callee = getattr(universe, "helper_callee", None)
    if not helper_callee or origin.constructor_args is None:
        return None
    list_u, refusal = list_adapter_universe_for_callee(helper_callee)
    if refusal is not None or list_u is None:
        return None
    if universe.constructor_param_index >= len(origin.constructor_args):
        return None
    arg = origin.constructor_args[universe.constructor_param_index]
    if _is_str_or_bytes_literal_term(arg):
        adapter_args = (arg,)
    else:
        adapter_args = _str_bytes_sequence_literal_elements(arg) or ()
    if not adapter_args:
        return None
    try:
        projected_arg = adapter_args[index]
    except IndexError:
        return None
    return ctor(_call_result_head(list_u.adapter_callee, 1), [projected_arg])


def _constructor_field_recursive_callees(universe, value_term: Term) -> Tuple[str, ...]:
    if not isinstance(value_term, _Ctor):
        return ()
    field_projection = getattr(universe, "field_projection", None)
    if field_projection:
        adapter_callee = _projected_list_adapter_callee(universe)
        if (
            adapter_callee
            and value_term.name == _call_result_head(adapter_callee, 1)
        ):
            return (adapter_callee,)
        return ()
    adapter_callee = getattr(universe, "adapter_callee", None)
    if adapter_callee:
        return (adapter_callee,)
    helper_callee = getattr(universe, "helper_callee", None)
    if helper_callee:
        return (helper_callee,)
    return ()


def _projected_list_adapter_callee(universe) -> Optional[str]:
    helper_callee = getattr(universe, "helper_callee", None)
    if not helper_callee:
        return None
    list_u, refusal = list_adapter_universe_for_callee(helper_callee)
    if refusal is not None or list_u is None:
        return None
    return list_u.adapter_callee


def _append_constructor_field_projection_source_warrant(
    source_warrants: List[dict],
    universe,
    origin: _CallOrigin,
) -> None:
    if not getattr(universe, "field_projection", None):
        return
    helper_callee = getattr(universe, "helper_callee", None)
    if not helper_callee or origin.constructor_args is None:
        return
    list_u, refusal = list_adapter_universe_for_callee(helper_callee)
    if refusal is not None or list_u is None or list_u.source_memento is None:
        return
    if universe.constructor_param_index >= len(origin.constructor_args):
        return
    arg = origin.constructor_args[universe.constructor_param_index]
    if _is_str_or_bytes_literal_term(arg):
        branch = "scalar"
    elif _str_bytes_sequence_literal_elements(arg) is not None:
        branch = "iterable"
    else:
        return
    warrant = _source_warrant_for_universe(
        list_u,
        role="python.list-adapter-universe",
        universe_kind="list-adapter",
    )
    warrant["list_adapter_branch"] = branch
    _append_unique_source_warrant(source_warrants, warrant)


def _constructor_field_adapter_term(universe, arg_term: Term) -> Term:
    helper_callee = getattr(universe, "helper_callee", None)
    if helper_callee:
        return ctor(_call_result_head(helper_callee, 1), [arg_term])
    adapter_callee = getattr(universe, "adapter_callee", None)
    if not adapter_callee:
        return arg_term
    return ctor(_call_result_head(adapter_callee, 1), [arg_term])


def _receiver_name_for_constructor_field_subject(
    subject_term: Term,
    field_name: str,
) -> Optional[str]:
    name = getattr(subject_term, "name", "")
    if not isinstance(subject_term, _Ctor) and isinstance(name, str):
        suffix = f".{field_name}"
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    if isinstance(subject_term, _Ctor) and subject_term.name.startswith("callval_"):
        if not subject_term.args:
            return None
        receiver = subject_term.args[0]
        receiver_name = getattr(receiver, "name", "")
        if not isinstance(receiver, _Ctor) and isinstance(receiver_name, str):
            return receiver_name
    return None


def _source_warrant_for_translate_universe(universe) -> dict:
    warrant = dict(universe.source_memento or {})
    warrant["kind"] = "source-memento"
    warrant["role"] = "python.translate-universe"
    warrant["source_function_name"] = _universe_source_function_name(universe)
    warrant["universe_kind"] = universe.kind
    warrant["table_name"] = universe.table_name
    return warrant


def _source_warrant_for_universe(
    universe,
    *,
    role: str,
    universe_kind: str,
) -> dict:
    warrant = dict(universe.source_memento or {})
    warrant["kind"] = "source-memento"
    warrant["role"] = role
    warrant["source_function_name"] = _universe_source_function_name(universe)
    warrant["universe_kind"] = universe_kind
    return warrant


def _source_warrant_for_branch_selected_universe(universe) -> dict:
    warrant = _source_warrant_for_universe(
        universe,
        role="python.branch-selected-universe",
        universe_kind="branch-selected-return",
    )
    warrant["branch_field_name"] = universe.field_name
    warrant["branch_field_value"] = _json_safe_literal_value(
        universe.field_value,
        universe.field_value_kind,
    )
    warrant["branch_field_value_kind"] = universe.field_value_kind
    warrant["branch_return_param_name"] = universe.return_param_name
    adapter_callee = getattr(universe, "return_adapter_callee", None)
    if adapter_callee:
        warrant["branch_return_adapter_callee"] = adapter_callee
    return warrant


def _json_safe_literal_value(value: Any, value_kind: str) -> Any:
    if value_kind == "bytes":
        try:
            return value.decode("ascii")
        except UnicodeDecodeError:
            return repr(value)
    return value


def _source_warrant_for_instance_field_universe(
    universe,
    *,
    source_memento: Optional[dict[str, Any]],
    source_function_name: str,
    constructor_default_params: Tuple[str, ...] = (),
) -> dict:
    warrant = dict(source_memento or {})
    warrant["kind"] = "source-memento"
    warrant["role"] = "python.instance-field-universe"
    warrant["source_function_name"] = source_function_name
    warrant["universe_kind"] = "constructor-field-getter"
    warrant["field_name"] = universe.field_name
    warrant["constructor_param_name"] = universe.constructor_param_name
    field_projection = getattr(universe, "field_projection", None)
    if field_projection:
        warrant["field_projection"] = list(field_projection)
    default_attr_name = getattr(universe, "constructor_default_attr_name", None)
    if default_attr_name:
        warrant["constructor_default_attr_name"] = default_attr_name
    default_literal_kind = getattr(
        universe,
        "constructor_default_literal_kind",
        None,
    )
    if default_literal_kind:
        warrant["constructor_default_literal_kind"] = default_literal_kind
        warrant["constructor_default_literal"] = _json_safe_literal_value(
            getattr(universe, "constructor_default_literal", None),
            default_literal_kind,
        )
    adapter_callee = getattr(universe, "adapter_callee", None)
    if adapter_callee:
        warrant["adapter_callee"] = adapter_callee
    helper_callee = getattr(universe, "helper_callee", None)
    if helper_callee:
        warrant["helper_callee"] = helper_callee
    if constructor_default_params:
        warrant["constructor_default_param_names"] = list(constructor_default_params)
    return warrant


def _universe_source_function_name(universe) -> str:
    return _local_qualname(universe.module, str(universe.qualname))


def _local_qualname(module: str, qualname: str) -> str:
    prefix = f"{module}."
    if qualname.startswith(prefix):
        return qualname[len(prefix):]
    return qualname.rsplit(".", 1)[-1]


def _append_unique_source_warrant(warrants: List[dict], warrant: dict) -> None:
    if warrant not in warrants:
        warrants.append(warrant)


def _expr_spec_term(spec, call_args):
    """Instantiate a chain-expr spec tree at this callsite's argument
    terms. None when a forwarded param is defaulted here."""
    mapped = _expr_spec_term_and_queued(
        spec,
        call_args,
        receiver_term=None,
        origin=None,
        subject_term=None,
        receiver_context=False,
    )
    return None if mapped is None else mapped[0]


def _expr_spec_term_and_queued(
    spec,
    call_args,
    *,
    receiver_term: Optional[Term],
    origin: Optional[_CallOrigin],
    subject_term: Optional[Term],
    receiver_context: bool,
):
    """Instantiate a chain-expr and retain the recursive digs it exposes."""
    if isinstance(spec, tuple) and spec and spec[0] == "binop":
        _tag, op, left, right = spec
        left_mapped = _expr_spec_term_and_queued(
            left,
            call_args,
            receiver_term=receiver_term,
            origin=origin,
            subject_term=subject_term,
            receiver_context=receiver_context,
        )
        right_mapped = _expr_spec_term_and_queued(
            right,
            call_args,
            receiver_term=receiver_term,
            origin=origin,
            subject_term=subject_term,
            receiver_context=receiver_context,
        )
        if left_mapped is None or right_mapped is None:
            return None
        lt_, left_delegates, left_fields, left_kind = left_mapped
        rt_, right_delegates, right_fields, right_kind = right_mapped
        term, term_kind = _chain_expr_binop_term(
            op,
            lt_,
            rt_,
            left_kind,
            right_kind,
        )
        return (
            term,
            [*left_delegates, *right_delegates],
            [*left_fields, *right_fields],
            term_kind,
        )
    if isinstance(spec, tuple) and spec and spec[0] == "subscript":
        base_mapped = _expr_spec_term_and_queued(
            spec[1],
            call_args,
            receiver_term=receiver_term,
            origin=origin,
            subject_term=subject_term,
            receiver_context=receiver_context,
        )
        index_mapped = _expr_spec_term_and_queued(
            spec[2],
            call_args,
            receiver_term=receiver_term,
            origin=origin,
            subject_term=subject_term,
            receiver_context=receiver_context,
        )
        if base_mapped is None or index_mapped is None:
            return None
        base_term, base_delegates, base_fields, _base_kind = base_mapped
        index_term, index_delegates, index_fields, _index_kind = index_mapped
        return (
            _subscript_term_or_projection(base_term, index_term),
            [*base_delegates, *index_delegates],
            [*base_fields, *index_fields],
            "unknown",
        )
    if isinstance(spec, tuple) and spec and spec[0] == "ctor-call":
        mapped_exprs = _expr_specs_terms_and_queued(
            spec[2],
            call_args,
            receiver_term,
            origin,
            subject_term,
            receiver_context=receiver_context,
        )
        if mapped_exprs is None:
            return None
        mapped, queued, fields, _arg_kinds = mapped_exprs
        term = ctor(spec[1], mapped)
        return term, queued, fields, _chain_expr_concat_kind(term)
    if isinstance(spec, tuple) and spec and spec[0] == "method-call":
        mapped_exprs = _expr_specs_terms_and_queued(
            spec[2],
            call_args,
            receiver_term,
            origin,
            subject_term,
            receiver_context=receiver_context,
        )
        if mapped_exprs is None:
            return None
        mapped, queued, fields, arg_kinds = mapped_exprs
        term = ctor(_callval_head(spec[1], len(mapped)), mapped)
        return (
            term,
            queued,
            fields,
            _method_return_concat_kind(spec[1], arg_kinds),
        )
    if isinstance(spec, tuple) and spec and spec[0] == "receiver-method-call":
        if receiver_term is None:
            return None
        receiver_call_args = (
            tuple(call_args) if receiver_context else tuple(call_args[1:])
        )
        mapped = _expr_specs_terms_and_queued(
            spec[2],
            receiver_call_args,
            receiver_term,
            origin,
            subject_term,
            receiver_context=True,
        )
        if mapped is None:
            return None
        mapped_args, queued, fields, arg_kinds = mapped
        delegate_args = [receiver_term, *mapped_args]
        method_name = spec[1].rsplit(".", 1)[-1]
        term = ctor(_callval_head(method_name, len(delegate_args)), delegate_args)
        return (
            term,
            [*queued, (spec[1], mapped_args, term)],
            fields,
            _callee_return_concat_kind(spec[1], mapped_args, arg_kinds),
        )
    if isinstance(spec, tuple) and spec and spec[0] == "function-call":
        mapped_exprs = _expr_specs_terms_and_queued(
            spec[2],
            call_args,
            receiver_term,
            origin,
            subject_term,
            receiver_context=receiver_context,
        )
        if mapped_exprs is None:
            return None
        mapped, queued, fields, arg_kinds = mapped_exprs
        delegate_term = ctor(_call_result_head(spec[1], len(mapped)), mapped)
        return (
            delegate_term,
            [*queued, (spec[1], mapped, delegate_term)],
            fields,
            _callee_return_concat_kind(spec[1], mapped, arg_kinds),
        )
    if isinstance(spec, tuple) and spec and spec[0] == "receiver-field":
        if (
            origin is None
            or origin.receiver_constructor is None
            or origin.constructor_args is None
            or subject_term is None
        ):
            return None
        field_name = spec[1]
        pinned_field = _pinned_receiver_field_term(
            receiver_term,
            field_name,
            origin,
        )
        if pinned_field is not None:
            return pinned_field
        field_u, field_refusal = constructor_field_universe_for_callee(
            origin.receiver_constructor,
            field_name,
        )
        if (
            field_refusal is not None
            or field_u is None
            or field_u.constructor_param_index >= len(origin.constructor_args)
        ):
            return None
        value_term = _constructor_field_universe_value_term(
            subject_term,
            field_name,
            field_u,
            origin,
        )
        return value_term, [], [(field_u, value_term)], _chain_expr_concat_kind(value_term)
    if isinstance(spec, tuple) and spec and spec[0] == "receiver":
        if receiver_term is None:
            return None
        return receiver_term, [], [], "unknown"
    if isinstance(spec, tuple) and spec and spec[0] == "kw":
        mapped = _expr_spec_term_and_queued(
            spec[2],
            call_args,
            receiver_term=receiver_term,
            origin=origin,
            subject_term=subject_term,
            receiver_context=receiver_context,
        )
        if mapped is None:
            return None
        value_term, queued, fields, _value_kind = mapped
        return (
            ctor("python:kwarg_a2", [str_const(spec[1]), value_term]),
            queued,
            fields,
            "unknown",
        )
    if isinstance(spec, tuple) and spec and spec[0] == "dict":
        entries = []
        queued = []
        fields = []
        for key, value_spec in spec[1]:
            mapped = _expr_spec_term_and_queued(
                value_spec,
                call_args,
                receiver_term=receiver_term,
                origin=origin,
                subject_term=subject_term,
                receiver_context=receiver_context,
            )
            if mapped is None:
                return None
            value_term, value_queued, value_fields, _value_kind = mapped
            entries.append(
                ctor("python:dict-entry_a2", [str_const(key), value_term])
            )
            queued.extend(value_queued)
            fields.extend(value_fields)
        return ctor(f"python:dict_a{len(entries)}", entries), queued, fields, "unknown"
    mapped = _mapped_delegate_args((spec,), call_args)
    return None if mapped is None else (mapped[0], [], [], _chain_expr_concat_kind(mapped[0]))


def _pinned_receiver_field_term(
    receiver_term: Optional[Term],
    field_name: str,
    origin: _CallOrigin,
):
    if not (
        isinstance(receiver_term, _Ctor)
        and receiver_term.name.startswith("callval_")
        and origin.receiver_constructor is not None
    ):
        return None
    method_name = _method_name_from_callval_head(receiver_term)
    if method_name is None:
        return None
    callee = f"{origin.receiver_constructor}.{method_name}"
    deleg_u, deleg_refusal = delegation_universe_for_callee(callee)
    if deleg_refusal is not None or deleg_u is None or deleg_u.kind != "chain-expr":
        return None
    ctor_spec = _constructor_return_spec(deleg_u.expr_spec)
    if ctor_spec is None or ctor_spec[1] != f"call:{origin.receiver_constructor}":
        return None
    field_u, field_refusal = constructor_field_universe_for_callee(
        origin.receiver_constructor,
        field_name,
    )
    if field_refusal is not None or field_u is None:
        return None
    receiver_call_args = _delegation_universe_call_args(deleg_u, receiver_term)
    receiver_receiver = _receiver_term_for_callval_subject(receiver_term)
    mapped = _expr_spec_term_and_queued(
        ctor_spec,
        receiver_call_args,
        receiver_term=receiver_receiver,
        origin=origin,
        subject_term=receiver_term,
        receiver_context=False,
    )
    if mapped is None:
        return None
    constructed, queued, fields, _kind = mapped
    if (
        not isinstance(constructed, _Ctor)
        or constructed.name != ctor_spec[1]
        or field_u.constructor_param_index >= len(constructed.args)
    ):
        return None
    value_term = _constructor_field_projection_term(
        field_u,
        _constructor_field_adapter_term(
            field_u,
            constructed.args[field_u.constructor_param_index],
        ),
        origin,
    )
    return (
        value_term,
        [*queued, (callee, list(receiver_call_args), receiver_term)],
        [*fields, (field_u, value_term)],
        _chain_expr_concat_kind(value_term),
    )


def _method_name_from_callval_head(term: _Ctor) -> Optional[str]:
    prefix = "callval_"
    if not term.name.startswith(prefix):
        return None
    body = term.name[len(prefix):]
    marker = body.rfind("_a")
    if marker <= 0:
        return None
    arity_text = body[marker + 2 :]
    if not arity_text.isdigit() or int(arity_text) != len(term.args):
        return None
    method_name = body[:marker]
    if not method_name.isidentifier():
        return None
    return method_name


def _constructor_return_spec(spec):
    if isinstance(spec, tuple) and spec and spec[0] == "ctor-call":
        return spec
    return None


def _expr_specs_terms_and_queued(
    specs,
    call_args,
    receiver_term: Optional[Term],
    origin: Optional[_CallOrigin],
    subject_term: Optional[Term],
    *,
    receiver_context: bool,
):
    terms = []
    queued = []
    fields = []
    kinds = []
    for spec in specs:
        mapped = _expr_spec_term_and_queued(
            spec,
            call_args,
            receiver_term=receiver_term,
            origin=origin,
            subject_term=subject_term,
            receiver_context=receiver_context,
        )
        if mapped is None:
            return None
        term, term_queued, term_fields, term_kind = mapped
        terms.append(term)
        queued.extend(term_queued)
        fields.extend(term_fields)
        kinds.append(term_kind)
    return terms, queued, fields, kinds


def _chain_expr_binop_term(
    op: str,
    left: Term,
    right: Term,
    left_kind: str,
    right_kind: str,
) -> Tuple[Term, str]:
    if op == "+" and _chain_expr_concat_operands(left_kind, right_kind):
        return ctor("str.++", [left, right]), "string"
    term = ctor(op, [left, right])
    if _term_leaves_all_const_int(term):
        return term, "number"
    return term, _chain_expr_concat_kind(term)


def _chain_expr_concat_operands(left_kind: str, right_kind: str) -> bool:
    if "number" in {left_kind, right_kind}:
        return False
    return "string" in {left_kind, right_kind}


def _callee_return_concat_kind(callee: str, mapped_args, arg_kinds) -> str:
    const_u, const_refusal = constant_universe_for_callee(callee)
    if const_refusal is None and const_u is not None:
        return _literal_value_kind_concat_kind(const_u.value_kind)
    bytes_u, bytes_refusal = bytes_identity_universe_for_callee(callee)
    if bytes_refusal is None and bytes_u is not None:
        return "string"
    translate_u, translate_refusal = translate_universe_for_callee(callee)
    if translate_refusal is None and translate_u is not None:
        return "string"
    deleg_u, deleg_refusal = delegation_universe_for_callee(callee)
    if deleg_refusal is None and deleg_u is not None:
        if deleg_u.kind == "identity" and deleg_u.param_index < len(arg_kinds):
            return arg_kinds[deleg_u.param_index]
        if deleg_u.kind == "chain-constant" and deleg_u.args:
            return _spec_concat_kind(deleg_u.args[0])
    leaf = callee.rsplit(".", 1)[-1]
    if leaf in {"want_bytes", "base64_encode", "int_to_bytes"}:
        return "string"
    return "unknown"


def _method_return_concat_kind(method: str, arg_kinds) -> str:
    if method in {"decode", "encode", "join", "ljust", "lower", "lstrip", "replace", "rjust", "rstrip", "strip", "upper"}:
        return "string"
    return "unknown"


def _literal_value_kind_concat_kind(value_kind: str) -> str:
    if value_kind in {"str", "bytes"}:
        return "string"
    if value_kind == "int":
        return "number"
    return "unknown"


def _spec_concat_kind(spec) -> str:
    if not (isinstance(spec, tuple) and spec):
        return "unknown"
    if spec[0] == "lit":
        return _literal_value_kind_concat_kind(spec[2])
    return "unknown"


def _chain_expr_concat_kind(term: Term) -> str:
    from .ir import _ConstBool, _ConstInt, _ConstReal, _ConstStr, _Var

    if isinstance(term, _ConstStr) or _is_bytes_literal_term(term):
        return "string"
    if isinstance(term, (_ConstBool, _ConstInt, _ConstReal)):
        return "number"
    if isinstance(term, _Ctor):
        if term.name == "str.len":
            return "number"
        if term.name == "str.++":
            return "string"
        if term.name.startswith("callval_") or term.name.startswith("callresult_"):
            return "unknown"
        if term.name in {"python:list", "python:tuple", "python:dict-entry_a2"}:
            return "number"
        kinds = {_chain_expr_concat_kind(arg) for arg in term.args}
        if "number" in kinds:
            return "number"
        if "string" in kinds:
            return "string"
        return "unknown"
    if isinstance(term, _Var):
        return "unknown"
    return "unknown"


def _chain_expr_emittable_term(term: Term) -> bool:
    return (
        _term_leaves_all_const_int(term)
        or _chain_expr_is_concat_term(term)
        or _chain_expr_is_structural_term(term)
    )


def _chain_expr_is_concat_term(term: Term) -> bool:
    if not (isinstance(term, _Ctor) and term.name == "str.++"):
        return False
    return all(_chain_expr_concat_operand_term(arg) for arg in term.args)


def _chain_expr_concat_operand_term(term: Term) -> bool:
    if _chain_expr_concat_kind(term) != "number":
        return True
    return False


def _conditional_chain_condition_formula(
    conditions,
    call_args,
    *,
    receiver_term: Optional[Term],
    origin: Optional[_CallOrigin],
    subject_term: Term,
) -> Optional[Formula]:
    formulas = []
    for condition in conditions:
        formula = _conditional_chain_single_condition_formula(
            condition,
            call_args,
            receiver_term=receiver_term,
            origin=origin,
            subject_term=subject_term,
        )
        if formula is None:
            return None
        formulas.append(formula)
    if not formulas:
        return eq(num(1), num(1))
    return formulas[0] if len(formulas) == 1 else and_(formulas)


def _conditional_chain_single_condition_formula(
    condition,
    call_args,
    *,
    receiver_term: Optional[Term],
    origin: Optional[_CallOrigin],
    subject_term: Term,
) -> Optional[Formula]:
    if not (isinstance(condition, tuple) and condition):
        return None
    if condition[0] == "not":
        inner = _conditional_chain_single_condition_formula(
            condition[1],
            call_args,
            receiver_term=receiver_term,
            origin=origin,
            subject_term=subject_term,
        )
        return None if inner is None else not_(inner)
    if condition[0] == "compare":
        left = _expr_spec_term_and_queued(
            condition[2],
            call_args,
            receiver_term=receiver_term,
            origin=origin,
            subject_term=subject_term,
            receiver_context=False,
        )
        right = _expr_spec_term_and_queued(
            condition[3],
            call_args,
            receiver_term=receiver_term,
            origin=origin,
            subject_term=subject_term,
            receiver_context=False,
        )
        if left is None or right is None:
            return None
        left_term = left[0]
        right_term = right[0]
        return _comparison_from_symbol(condition[1], left_term, right_term)
    mapped = _expr_spec_term_and_queued(
        condition,
        call_args,
        receiver_term=receiver_term,
        origin=origin,
        subject_term=subject_term,
        receiver_context=False,
    )
    if mapped is None:
        return None
    return eq(mapped[0], bool_const(True))


def _conditional_chain_condition_field_terms(
    conditions,
    origin: Optional[_CallOrigin],
    subject_term: Term,
) -> List[Tuple[Any, Term]]:
    fields: List[Tuple[Any, Term]] = []

    def walk(condition) -> None:
        if not (isinstance(condition, tuple) and condition):
            return
        if condition[0] == "not":
            walk(condition[1])
            return
        if condition[0] == "compare":
            walk(condition[2])
            walk(condition[3])
            return
        if condition[0] == "receiver-field":
            if (
                origin is None
                or origin.receiver_constructor is None
                or origin.constructor_args is None
            ):
                return
            field_u, field_refusal = constructor_field_universe_for_callee(
                origin.receiver_constructor,
                condition[1],
            )
            if (
                field_refusal is not None
                or field_u is None
                or field_u.constructor_param_index >= len(origin.constructor_args)
            ):
                return
            fields.append(
                (
                    field_u,
                    _constructor_field_universe_value_term(
                        subject_term,
                        condition[1],
                        field_u,
                        origin,
                    ),
                )
            )
            return
        for part in condition[1:]:
            walk(part)

    for condition in conditions:
        walk(condition)
    return fields


def _chain_expr_is_structural_term(term: Term) -> bool:
    from .ir import _ConstBool, _ConstInt, _ConstReal, _ConstStr, _Var

    if isinstance(term, (_ConstBool, _ConstInt, _ConstReal, _ConstStr, _Var)):
        return True
    if not isinstance(term, _Ctor):
        return False
    if term.name in {"+", "-", "*", "/", "%"}:
        return _term_leaves_all_const_int(term)
    return all(_chain_expr_is_structural_term(arg) for arg in term.args)


def _term_leaves_all_const_int(term) -> bool:
    from .ir import _ConstInt

    if isinstance(term, _Ctor):
        return all(_term_leaves_all_const_int(a) for a in term.args)
    return isinstance(term, _ConstInt)


def _receiver_term_for_callval_subject(subject_term: Term) -> Optional[Term]:
    if (
        isinstance(subject_term, _Ctor)
        and subject_term.name.startswith("callval_")
        and subject_term.args
    ):
        return subject_term.args[0]
    return None


def _mapped_receiver_delegate_args_and_queued(
    specs,
    call_args,
    receiver_term: Term,
):
    mapped = []
    nested_delegates = []
    for spec in specs:
        mapped_spec = _receiver_delegate_spec_term(
            spec,
            call_args,
            receiver_term,
        )
        if mapped_spec is None:
            return None
        term, queued = mapped_spec
        mapped.append(term)
        nested_delegates.extend(queued)
    return mapped, nested_delegates


def _receiver_delegate_spec_term(
    spec,
    call_args,
    receiver_term: Term,
) -> Optional[Tuple[Term, List[Tuple[str, List[Term], Term]]]]:
    if spec[0] == "binop":
        left = _receiver_delegate_spec_term(spec[2], call_args, receiver_term)
        right = _receiver_delegate_spec_term(spec[3], call_args, receiver_term)
        if left is None or right is None:
            return None
        left_term, left_queued = left
        right_term, right_queued = right
        term, _kind = _chain_expr_binop_term(
            spec[1],
            left_term,
            right_term,
            _chain_expr_concat_kind(left_term),
            _chain_expr_concat_kind(right_term),
        )
        return (
            term,
            [*left_queued, *right_queued],
        )
    if spec[0] == "subscript":
        base = _receiver_delegate_spec_term(spec[1], call_args, receiver_term)
        index = _receiver_delegate_spec_term(spec[2], call_args, receiver_term)
        if base is None or index is None:
            return None
        base_term, base_queued = base
        index_term, index_queued = index
        return (
            _subscript_term_or_projection(base_term, index_term),
            [*base_queued, *index_queued],
        )
    if spec[0] == "method-call":
        mapped = _mapped_receiver_delegate_args_and_queued(
            spec[2],
            call_args,
            receiver_term,
        )
        if mapped is None:
            return None
        mapped_args, nested_queues = mapped
        return ctor(_callval_head(spec[1], len(mapped_args)), mapped_args), list(
            nested_queues
        )
    if spec[0] == "receiver":
        return receiver_term, []
    if spec[0] == "param":
        if spec[1] >= len(call_args):
            return None
        return call_args[spec[1]], []
    if spec[0] == "receiver-method-call":
        nested = _mapped_receiver_delegate_args_and_queued(
            spec[2],
            call_args,
            receiver_term,
        )
        if nested is None:
            return None
        nested_args, nested_queues = nested
        nested_delegate_args = [receiver_term, *nested_args]
        method_name = spec[1].rsplit(".", 1)[-1]
        head = _callval_head(method_name, len(nested_delegate_args))
        nested_term = ctor(head, nested_delegate_args)
        queued = list(nested_queues)
        queued.append((spec[1], nested_args, nested_term))
        return nested_term, queued
    if spec[0] == "function-call":
        mapped = _mapped_receiver_delegate_args_and_queued(
            spec[2],
            call_args,
            receiver_term,
        )
        if mapped is None:
            return None
        mapped_args, nested_queues = mapped
        delegate_term = ctor(_call_result_head(spec[1], len(mapped_args)), mapped_args)
        queued = list(nested_queues)
        queued.append((spec[1], mapped_args, delegate_term))
        return delegate_term, queued
    if spec[0] == "kw":
        return _receiver_delegate_spec_term(spec[2], call_args, receiver_term)
    if spec[0] == "dict":
        entries = []
        queued: List[Tuple[str, List[Term], Term]] = []
        for key, value_spec in spec[1]:
            mapped_value = _receiver_delegate_spec_term(
                value_spec,
                call_args,
                receiver_term,
            )
            if mapped_value is None:
                return None
            value_term, value_queued = mapped_value
            entries.append(
                ctor(
                    "python:dict-entry_a2",
                    [str_const(key), value_term],
                )
            )
            queued.extend(value_queued)
        return ctor(f"python:dict_a{len(entries)}", entries), queued

    lit = _mapped_delegate_args((spec,), call_args)
    if lit is None:
        return None
    return lit[0], []


def _receiver_delegate_origin(
    delegate: str,
    origin: Optional[_CallOrigin],
    mapped_args: List[Term],
    delegate_term: Term,
) -> Optional[_CallOrigin]:
    if origin is None:
        return None
    return _CallOrigin(
        callee=delegate,
        lineno=origin.lineno,
        col=origin.col,
        constructor_args=origin.constructor_args,
        constructor_default_params=origin.constructor_default_params,
        receiver_constructor=origin.receiver_constructor,
        arg_terms=tuple(mapped_args),
        result_term=delegate_term,
    )


def _exception_bool_inner_call_term(universe, subject_term: Term) -> Optional[Term]:
    inner = _exception_bool_inner_call(universe, subject_term)
    if inner is None:
        return None
    return inner[0]


def _exception_bool_inner_call(
    universe,
    subject_term: Term,
) -> Optional[Tuple[Term, List[Term]]]:
    if not isinstance(subject_term, _Ctor) or not subject_term.args:
        return None
    call_args = tuple(subject_term.args)
    mapped = _mapped_delegate_args(universe.args, call_args)
    if mapped is None:
        return None
    source_memento = getattr(universe, "source_memento", None) or {}
    param_names = source_memento.get("param_names") or ()
    if param_names and param_names[0] in {"self", "cls"}:
        receiver_term = call_args[0]
        method_name = universe.delegate.rsplit(".", 1)[-1]
        delegate_args = [receiver_term, *mapped]
        return (
            ctor(_callval_head(method_name, len(delegate_args)), delegate_args),
            mapped,
        )
    return ctor(_call_result_head(universe.delegate, len(mapped)), mapped), mapped


def _separator_guard_raise_conjuncts(
    universe,
    subject_term: Term,
    out: Layer2Output,
    source_path: str,
    test_name: str,
    source_warrants: Optional[List[dict]],
    origin: Optional[_CallOrigin],
    seen: Set[Tuple[str, str]],
) -> List[Formula]:
    if (
        not isinstance(subject_term, _Ctor)
        or not subject_term.name.startswith("callval_")
        or not subject_term.args
        or origin is None
        or origin.receiver_constructor is None
        or origin.constructor_args is None
    ):
        return []
    call_args = tuple(subject_term.args)
    if universe.param_index >= len(call_args):
        return []
    field_u, field_refusal = constructor_field_universe_for_callee(
        origin.receiver_constructor,
        universe.field_name,
    )
    if field_refusal is not None:
        out.warnings.append(
            LiftWarning(
                source_path=source_path,
                item_name=f"{test_name}::separator-guard-raise-universe",
                reason=f"{field_refusal.callee}: {field_refusal.reason}",
            )
        )
        return []
    if (
        field_u is None
        or field_u.constructor_param_index >= len(origin.constructor_args)
    ):
        return []

    signed_term = call_args[universe.param_index]
    adapter_callee = getattr(universe, "adapter_callee", None)
    if adapter_callee:
        signed_term = ctor(_call_result_head(adapter_callee, 1), [signed_term])
    sep_term = _constructor_field_universe_value_term(
        subject_term,
        universe.field_name,
        field_u,
        origin,
    )

    conjuncts: List[Formula] = []
    if source_warrants is not None:
        _append_unique_source_warrant(
            source_warrants,
            _source_warrant_for_universe(
                universe,
                role="python.separator-guard-raise-universe",
                universe_kind="separator-guard-raise",
            ),
        )
        _append_unique_source_warrant(
            source_warrants,
            _source_warrant_for_instance_field_universe(
                field_u,
                source_memento=field_u.constructor_source_memento,
                source_function_name=_local_qualname(
                    field_u.module,
                    field_u.constructor_qualname,
                ),
                constructor_default_params=tuple(
                    param
                    for param in origin.constructor_default_params
                    if param == field_u.constructor_param_name
                ),
            ),
        )

    if adapter_callee and isinstance(signed_term, _Ctor):
        conjuncts.extend(
            _universe_conjuncts(
                adapter_callee,
                signed_term,
                out,
                source_path,
                test_name,
                source_warrants=source_warrants,
                _seen=seen,
            )
        )
    for recursive_callee in _constructor_field_recursive_callees(field_u, sep_term):
        conjuncts.extend(
            _universe_conjuncts(
                recursive_callee,
                sep_term,
                out,
                source_path,
                test_name,
                source_warrants=source_warrants,
                _seen=seen,
            )
        )
    contains = atomic("contains", [signed_term, sep_term])
    raised = eq(
        ctor("raised_exc_a1", [subject_term]),
        str_const(universe.exception_name),
    )
    conjuncts.append(implies(not_(contains), raised))
    return conjuncts


def _mapped_delegate_args(specs, call_args):
    """Instantiate a delegation universe's arg specs at this callsite's
    argument terms. None when a forwarded param is defaulted at this
    callsite (the value is not visible here; emit nothing)."""
    mapped = []
    for spec in specs:
        if spec[0] == "param":
            if spec[1] >= len(call_args):
                return None
            mapped.append(call_args[spec[1]])
        elif spec[0] == "kw":
            kw_value = _mapped_delegate_args((spec[2],), call_args)
            if kw_value is None:
                return None
            mapped.append(
                ctor(
                    "python:kwarg_a2",
                    [str_const(spec[1]), kw_value[0]],
                )
            )
        else:
            _tag, v, k = spec
            if k == "int":
                mapped.append(num(v))
            elif k == "bool":
                mapped.append(bool_const(v))
            elif k == "str":
                mapped.append(str_const(v))
            elif k == "none":
                mapped.append(ctor("None", []))
            elif k == "collection":
                mapped.append(str_const(v))
            else:  # bytes (walk admits ascii only)
                mapped.append(
                    ctor("python:bytes", [str_const(v.decode("ascii"))])
                )
    return mapped


def _mapped_delegate_args_and_queued(
    specs,
    call_args,
    receiver_term: Optional[Term],
):
    mapped = []
    queued: List[Tuple[str, List[Term], Term]] = []
    receiver_call_args = (
        tuple(call_args[1:]) if receiver_term is not None else tuple(call_args)
    )
    for spec in specs:
        mapped_spec = _mapped_delegate_spec_and_queued(
            spec,
            call_args,
            receiver_term,
            receiver_call_args,
        )
        if mapped_spec is None:
            return None
        term, term_queued = mapped_spec
        mapped.append(term)
        queued.extend(term_queued)
    return mapped, queued


def _mapped_delegate_spec_and_queued(
    spec,
    call_args,
    receiver_term: Optional[Term],
    receiver_call_args,
) -> Optional[Tuple[Term, List[Tuple[str, List[Term], Term]]]]:
    if spec[0] == "binop":
        left = _mapped_delegate_spec_and_queued(
            spec[2],
            call_args,
            receiver_term,
            receiver_call_args,
        )
        right = _mapped_delegate_spec_and_queued(
            spec[3],
            call_args,
            receiver_term,
            receiver_call_args,
        )
        if left is None or right is None:
            return None
        left_term, left_queued = left
        right_term, right_queued = right
        term, _kind = _chain_expr_binop_term(
            spec[1],
            left_term,
            right_term,
            _chain_expr_concat_kind(left_term),
            _chain_expr_concat_kind(right_term),
        )
        return term, [*left_queued, *right_queued]
    if spec[0] == "subscript":
        base = _mapped_delegate_spec_and_queued(
            spec[1],
            call_args,
            receiver_term,
            receiver_call_args,
        )
        index = _mapped_delegate_spec_and_queued(
            spec[2],
            call_args,
            receiver_term,
            receiver_call_args,
        )
        if base is None or index is None:
            return None
        base_term, base_queued = base
        index_term, index_queued = index
        return (
            _subscript_term_or_projection(base_term, index_term),
            [*base_queued, *index_queued],
        )
    if spec[0] == "method-call":
        mapped_and_queued = _mapped_delegate_args_and_queued(
            spec[2],
            call_args,
            receiver_term,
        )
        if mapped_and_queued is None:
            return None
        mapped, queued = mapped_and_queued
        return ctor(_callval_head(spec[1], len(mapped)), mapped), queued
    if spec[0] == "receiver-method-call":
        if receiver_term is None:
            return None
        return _receiver_delegate_spec_term(
            spec,
            receiver_call_args,
            receiver_term,
        )
    if spec[0] == "function-call":
        mapped_and_queued = _mapped_delegate_args_and_queued(
            spec[2],
            call_args,
            receiver_term,
        )
        if mapped_and_queued is None:
            return None
        mapped, queued = mapped_and_queued
        delegate_term = ctor(_call_result_head(spec[1], len(mapped)), mapped)
        return delegate_term, [*queued, (spec[1], mapped, delegate_term)]
    if spec[0] == "kw":
        mapped_value = _mapped_delegate_spec_and_queued(
            spec[2],
            call_args,
            receiver_term,
            receiver_call_args,
        )
        if mapped_value is None:
            return None
        value_term, queued = mapped_value
        return (
            ctor(
                "python:kwarg_a2",
                [str_const(spec[1]), value_term],
            ),
            queued,
        )
    mapped = _mapped_delegate_args((spec,), call_args)
    if mapped is None:
        return None
    return mapped[0], []


_PRED_MISSING = object()


def _term_python_value(term):
    """The python value carried by a concrete literal term, for ground-
    evaluating a vendor predicate at a callsite. _PRED_MISSING for anything
    non-concrete (then the predicate is not evaluated here)."""
    from .ir import _ConstInt, _ConstStr, _ConstBool

    if isinstance(term, _ConstInt):
        return term.value
    if isinstance(term, _ConstBool):
        return term.value
    if isinstance(term, _ConstStr):
        return term.value
    if isinstance(term, _Ctor):
        if term.name == "None":
            return None
        if (
            term.name == "python:bytes"
            and len(term.args) == 1
            and isinstance(term.args[0], _ConstStr)
        ):
            return term.args[0].value
    return _PRED_MISSING


def _assertion_callsite_context(
    stmt: ast.stmt,
    scope: _ValueScope,
) -> Optional[Tuple[List[_CallOrigin], List[Formula], Formula]]:
    direct_calls = _collect_assertion_calls(stmt, scope)
    # ARGUMENT-CARRYING EUF (the "for input x" model).  A bare call result
    # (``f(x)`` appearing directly in an assertion) is keyed on
    # (callee, SSA-resolved arg-terms) via ``_call_result_term`` rather than on
    # source LOCATION.  Two assertions in DIFFERENT functions / lines that call
    # the SAME callee with the SAME argument terms therefore produce the SAME
    # ctor term, so a cross-location contradiction (``f(x) == 1`` at line N and
    # ``f(x) == 2`` at line M) unifies and fires UNSAT → REFUSED.  Different
    # args (``f(x)`` vs ``f(y)``) → different terms → independent → PROVEN.
    #
    # The arg-terms are SSA-resolved through ``scope``, so a reassigned arg
    # (``x = ...; x = ...`` → ``x$0`` then ``x$1``) yields a fresh term and
    # never produces a false-refuse.
    #
    # PURITY ASSUMPTION (loud — identical to the Form-3 ``callval`` tradeoff):
    #   same callee + same args → same value ASSUMES the callee is
    #   DETERMINISTIC / pure.  A STATEFUL callee (counter, generator, RNG)
    #   called twice with the same args could legitimately return different
    #   values; unifying them here can only ever produce a CONSERVATIVE
    #   FALSE-REFUSAL (we over-refuse a test that is actually fine).  It can
    #   NEVER produce a falsePass: we only ever ADD an equality between two
    #   syntactically identical call expressions, which is sound for pure fns
    #   and merely conservative for impure ones.  This is the same tradeoff
    #   the method-call-result (Form 3) and raises (Pattern 7) forms already
    #   made; EUF extends it to the bare call-result subject.
    #
    # FALLBACK: if an argument is not soundly translatable, ``_call_result_term``
    # returns None and we fall back to the LOCATION-keyed free var so the
    # callsite still anchors a ::facts/::assertion contract without over-claiming
    # argument identity (no cross-location unification, but no regression).
    call_vars: Dict[Tuple[int, int], Term] = {}
    euf_origins: Dict[Tuple[int, int], _CallOrigin] = {}
    for call in direct_calls:
        origin = _call_origin_from_expr_scoped(call, scope)
        if origin is not None:
            euf_term = _call_result_term(call, origin, scope, call_vars)
            if isinstance(euf_term, _Ctor):
                origin.arg_terms = tuple(euf_term.args)
            if (
                euf_term is not None
                and _euf_args_all_concrete(euf_term)
                and not callee_is_nondeterministic(origin.callee)
            ):
                # VALUE-AWARE EUF UNIFICATION (FIX 1 / soundness):
                # Use the argument-keyed base ONLY when EVERY argument of the
                # call-result ctor is a CONCRETE LITERAL (int / str / bool /
                # None constant).  Concrete literals denote the same value
                # regardless of call-site location, so ``f(5)`` in function A
                # and ``f(5)`` in function B genuinely refer to the same input
                # and cross-location unification is sound.
                #
                # When ANY argument is SYMBOLIC (a _Var / param / non-literal
                # _Ctor), the argument may be bound to different values at each
                # call site; unifying them is UNSOUND (causes false-refusals).
                # Fall back to the LOCATION-keyed free var (same branch as
                # ``euf_term is None``) — no cross-location unification.
                call_vars[_call_key(call)] = euf_term
                # Argument-key the origin so the callsite contract base
                # collapses to the same name across locations for same args.
                assert isinstance(euf_term, _Ctor)
                origin.arg_sig = _canonical_term_sig(euf_term)
                # Carry the subject term so the universe walk can emit a
                # sibling ::universe row over the same conjoin subject.
                origin.euf_term = euf_term
                origin.result_term = euf_term
            else:
                result_var = make_var(_call_result_var_name(origin))
                call_vars[_call_key(call)] = result_var
                origin.result_term = result_var
            euf_origins[_call_key(call)] = origin

    transient_facts: List[Formula] = []
    direct_origins: List[_CallOrigin] = []
    for call in direct_calls:
        origin = euf_origins.get(_call_key(call))
        if origin is None:
            continue
        var_term = call_vars[_call_key(call)]
        if origin.arg_sig is not None:
            # EUF subject: the ctor IS the value.  A reflexive ``eq(t, t)`` fact
            # would be vacuous, so we anchor the callsite via a tautological
            # fact only to keep the ::facts contract non-empty (the implication
            # antecedent must exist).  The cross-location contradiction fires
            # because the SAME ctor term ``t`` lands in the (mint-coalesced)
            # conjoined ::assertion inv — see _callsite_contract_base.
            transient_facts.append(eq(var_term, var_term))
            direct_origins.append(origin)
            continue
        try:
            rhs = _translate_call_rhs(call, scope, call_vars)
        except ValueError:
            continue
        transient_facts.append(eq(var_term, rhs))
        direct_origins.append(origin)

    scoped_origins = _origins_for_assertion(stmt, scope)
    if direct_origins:
        scoped_origins = [
            origin
            for origin in scoped_origins
            if not _is_constructor_call_name(origin.callee)
        ]
    origins = _unique_origins(scoped_origins + direct_origins)
    if not origins:
        return None

    facts = scope.facts + transient_facts
    if not facts:
        return None

    try:
        assertion = _lift_assertion_stmt_scoped(stmt, scope, call_vars)
    except ValueError:
        return None

    # BINDING-FORM EUF SUBSTITUTION: for each origin that came from a binding
    # ``r = f(5)`` (concrete args), substitute the EUF ctor for the SSA var
    # in the assertion formula.  This transforms ``assert r == 1`` from
    # ``=(r$0, 1)`` into ``=(callresult_f_a1(5), 1)`` — the EUF-keyed subject
    # that allows cross-function unification when another function also binds
    # the same call result to an SSA var and asserts a contradictory value.
    #
    # CARDINAL SOUNDNESS — subst_var_in_formula keyed on the bare SSA var NAME
    # (not the ctor) ensures:
    #   - Attribute/subscript vars (``r$0.x``, ``subscript(r$0, k)``) are NOT
    #     touched (they are separate Var names / Ctor args, not the bare name).
    #   - Only the exact ``r$0`` Var in the assertion is replaced → behavior
    #     change is confined to bare-var subjects of comparisons.
    #   - Symbolic-arg origins never carry euf_term (set to None in binding),
    #     so the symbolic false-refusal guard is intact.
    for origin in origins:
        if origin.euf_term is not None and origin.ssa_name is not None:
            assertion = subst_var_in_formula(assertion, origin.ssa_name, origin.euf_term)

    return origins, facts, assertion


def _unique_contract_name(name: str, used_names: Set[str]) -> str:
    if name not in used_names:
        used_names.add(name)
        return name
    i = 1
    while f"{name}::{i}" in used_names:
        i += 1
    unique = f"{name}::{i}"
    used_names.add(unique)
    return unique


def _callsite_contract_base(origin: _CallOrigin, source_path: str) -> str:
    file_name = os.path.basename(source_path) or source_path or "<unknown>"
    if origin.arg_sig is not None:
        # ARGUMENT-KEYED base (EUF).  Same callee + same SSA-resolved arg-terms
        # → same base → mint's coalesce-by-name conjoins the two cross-location
        # ``::assertion`` decls into one inv, so ``eq(t,1) ∧ eq(t,2)`` lands in
        # a single obligation and fires UNSAT.  Deliberately DROPS line:col and
        # the file name so the base is identical across functions AND files for
        # the same (callee, args) — that is exactly the cross-location unify we
        # want.  Different args → different arg_sig → different base → PROVEN.
        return f"{origin.callee}#euf#{origin.arg_sig}"
    return f"{origin.callee}@{file_name}:{origin.lineno}:{origin.col}"


def _call_result_var_name(origin: _CallOrigin) -> str:
    return f"{origin.callee}$call${origin.lineno}${origin.col}"


def _call_result_head(callee: str, arity: int) -> str:
    """ASCII-safe, arity-stable ctor head for a bare call-result EUF term.

    Shape: ``callresult_<callee>_a<arity>`` — mirrors the Form-3 ``callval_``
    and truthiness ``call_`` heads.  Encoding arity in the head guarantees the
    SMT emitter never sees the same head at two different arities (``f()`` vs
    ``f(x)``), which would otherwise silently adopt the first arity and produce
    ill-sorted applications.
    """
    safe = "".join(c if (c.isascii() and c.isalnum()) else "_" for c in callee)
    return f"callresult_{safe}_a{arity}"


def _call_result_term(
    call: ast.Call,
    origin: _CallOrigin,
    scope: _ValueScope,
    call_vars: Dict[Tuple[int, int], Term],
) -> Optional[Term]:
    """Build the ARGUMENT-CARRYING EUF term for a bare call result.

    ``f(x)`` → ``ctor("callresult_f_a1", [x_term])`` where ``x_term`` is the
    SSA-resolved translation of ``x`` through ``scope``.  Same callee + same
    (SSA-resolved) arg-terms → SAME ctor, regardless of source line; this is
    what lets a cross-location contradiction (``f(x)==1`` / ``f(x)==2`` in two
    different functions) unify and fire UNSAT.

    Returns None (caller falls back to a LOCATION-keyed free var) when:
      - the func is not a simple Name (handled by the origin filter already),
      - there are keyword args (cannot order-stably translate),
      - any argument is not soundly translatable as a term.

    NOTE on the ``callresult_`` head vs the bare ``ctor(callee, ...)`` that
    ``_translate_call_rhs`` builds: they are DELIBERATELY distinct heads.  The
    EUF subject must be a single dedicated function symbol so two cross-location
    assertions about the same call unify on it; the arity suffix keeps it
    sort-stable.  The two share the same args, so identical calls still collapse.

    Module-function attribute calls (``np.add(2, 3)``) are admitted: the receiver
    is the MODULE (in ``call.func.value``, NOT in ``call.args``), and
    ``origin.callee`` is already resolved to the qualified name (``numpy.add``).
    So the arg-terms are exactly ``[2, 3]`` and the head is
    ``callresult_numpy_add_a2`` -- identical for every call to ``numpy.add(2,3)``
    regardless of the alias (``np`` / ``numpy``) or the enclosing test. A method
    call on a non-module receiver never reaches here: ``_call_origin_from_expr``
    returns no origin for it (receiver-dependent, kept location-keyed).
    """
    if not isinstance(call.func, ast.Name) and _module_attr_callee(call.func) is None:
        return None
    if call.keywords:
        return None
    try:
        arg_terms = [
            _translate_term_scoped(arg, scope, call_vars) for arg in call.args
        ]
    except ValueError:
        return None
    head = _call_result_head(origin.callee, len(arg_terms))
    return ctor(head, arg_terms)


def _euf_args_all_concrete(euf_term: "_Ctor") -> bool:
    """Return True iff every immediate argument of the EUF call-result ctor is
    a CONCRETE LITERAL (int / str / bool / None constant).

    FIX 1 — VALUE-AWARE EUF SOUNDNESS:
    Cross-location unification is only sound when the argument IS the same
    value at every call site.  Concrete literals (``5``, ``"hello"``, True,
    None) have a fixed value known at lift time — ``f(5)`` in function A and
    ``f(5)`` in function B call f with the SAME input, so a cross-location
    contradiction is genuine.

    A SYMBOLIC argument (_Var from a param/local, or a nested non-literal
    _Ctor) has a value that depends on the binding environment — ``f(x)`` in
    function A and ``f(x)`` in function B bind ``x`` independently; they may
    refer to DIFFERENT values at runtime.  Unifying them produces a spurious
    UNSAT (false-refusal) when f(x)==1 and f(x)==2 happen to share the same
    SSA name despite being independent.

    The check is over IMMEDIATE args only (no recursion): a nested ctor arg
    is by definition non-literal (it encodes a computed sub-expression), so
    the first level is sufficient.
    """
    from .ir import _ConstInt, _ConstStr, _ConstBool
    for arg in euf_term.args:
        if isinstance(arg, (_ConstInt, _ConstStr, _ConstBool)):
            continue
        if _is_none_term(arg):
            continue
        if (
            isinstance(arg, _Ctor)
            and arg.name == "python:bytes"
            and len(arg.args) == 1
            and isinstance(arg.args[0], _ConstStr)
        ):
            # A bytes literal is a fixed value known at lift time -- exactly
            # as concrete as a str literal; the ctor wrapper only carries the
            # kind so b"x" and "x" never unify.
            continue
        return False
    return True


def _canonical_term_sig(term: Term) -> str:
    """Deterministic canonical signature for a Term, used to argument-key the
    callsite contract base so mint's coalesce-by-name conjoins cross-location
    assertions about the SAME (callee, args) into one ``::assertion`` inv.

    Stable across process invocations (no hash randomization): we recurse
    structurally over the frozen Term dataclasses and emit a fixed textual
    encoding.  Same structure → same string → same base → mint coalesces →
    contradiction fires.  Different structure → different string → distinct
    base → independent (PROVEN).
    """
    from .ir import _Var as _IrVar, _ConstInt, _ConstStr, _ConstBool

    if isinstance(term, _IrVar):
        return f"v:{term.name}"
    if isinstance(term, _ConstInt):
        return f"i:{term.value}"
    if isinstance(term, _ConstStr):
        return f"s:{term.value!r}"
    if isinstance(term, _ConstBool):
        return f"b:{term.value}"
    if isinstance(term, _Ctor):
        inner = ",".join(_canonical_term_sig(a) for a in term.args)
        return f"c:{term.name}({inner})"
    return f"?:{term!r}"


def _call_key(call: ast.Call) -> Tuple[int, int]:
    return (getattr(call, "lineno", 0), getattr(call, "col_offset", 0))


# Per-file import-as map (``import numpy as np`` -> {"np": "numpy"}), set by
# ``lift_file_layer2`` for the file currently being lifted. Used to resolve an
# attribute call's MODULE receiver to its qualified callee so a callsite keys to
# the function under test (``numpy.add``), not the surface alias (``np``) and not
# the enclosing test. Module-global is safe: lift is single-threaded, one file at
# a time, and the map is saved/restored around each file.
_CURRENT_MODULE_ALIASES: Dict[str, str] = {}

# `from X import y` where y is a FUNCTION: maps the bare local name to its
# qualified callee ("urlsafe_b64encode" -> "base64.urlsafe_b64encode") so the
# callsite base keys to the function under test (aligning cross-proof conjoin
# contact with vendor rows) and the universe walk can resolve the vendor
# module. Saved/restored around each file alongside the module aliases.
_CURRENT_FROM_IMPORT_MEMBERS: Dict[str, str] = {}


def _collect_module_aliases(tree: ast.AST) -> Dict[str, str]:
    """Map each local module name to its qualified module: ``import numpy`` ->
    {"numpy": "numpy"}, ``import numpy as np`` -> {"np": "numpy"}, and
    ``from itsdangerous import encoding`` -> {"encoding":
    "itsdangerous.encoding"} WHEN the imported member is itself a module
    (find_spec-verified; a class or instance receiver must stay
    location-keyed, so unverified members are never aliased here)."""
    aliases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    # `import numpy.linalg as nl` binds `nl` to the FULL module.
                    aliases[a.asname] = a.name
                else:
                    # `import numpy` AND `import numpy.linalg` both bind only the
                    # TOP-LEVEL name (`numpy`), referring to the top-level package.
                    # Binding `numpy` -> `numpy.linalg` would mis-resolve `numpy.add`.
                    top = a.name.split(".")[0]
                    aliases[top] = top
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                if a.name == "*":
                    continue
                qualified = f"{node.module}.{a.name}"
                if _is_importable_module(qualified):
                    aliases[a.asname or a.name] = qualified
    return aliases


def _is_importable_module(qualified: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(qualified) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _collect_from_import_members(
    tree: ast.AST, module_aliases: Dict[str, str]
) -> Dict[str, str]:
    """Bare names bound by ``from X import y`` where y is NOT a module:
    {"urlsafe_b64encode": "base64.urlsafe_b64encode"}. Excludes names that
    resolved as module aliases and relative imports (no anchored module to
    qualify against)."""
    members: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                if a.name == "*":
                    continue
                local = a.asname or a.name
                if local in module_aliases:
                    continue
                members[local] = f"{node.module}.{a.name}"
    return members


def _module_attr_callee(func: ast.expr) -> Optional[str]:
    """Resolve ``np.add`` -> ``numpy.add`` when ``np`` is an imported MODULE.
    Returns None for a method call on a non-module receiver (``lst.append``):
    those are RECEIVER-DEPENDENT, so they must stay location-keyed -- unifying
    ``a.foo(5)`` with ``b.foo(5)`` would be a false refusal. Only a module-level
    function (pure, receiver-free) is safe to key to the callsite. Nested paths
    rooted at an imported module are still module-owned surfaces, e.g.
    ``pkg.Class.staticmethod`` -> ``package.pkg.Class.staticmethod``."""
    path = _attribute_path(func)
    if path is None or len(path) < 2:
        return None
    root, *attrs = path
    module = _CURRENT_MODULE_ALIASES.get(root)
    if module is not None:
        return ".".join([module, *attrs])
    return None


def _attribute_path(node: ast.expr) -> Optional[List[str]]:
    parts: List[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return list(reversed(parts))


def _call_origin_from_expr(node: ast.expr) -> Optional[_CallOrigin]:
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        # A from-imported function keys to its QUALIFIED name so the base
        # aligns with vendor-proof rows and the universe walk can resolve
        # the vendor module. Unimported bare names stay as-is.
        callee = _CURRENT_FROM_IMPORT_MEMBERS.get(node.func.id, node.func.id)
    else:
        # Attribute call: key to the callsite ONLY when the receiver is an
        # imported module (``np.add`` -> ``numpy.add``). The callsite under test
        # is the function, not the enclosing test.
        callee = _module_attr_callee(node.func)
    if callee is None:
        return None
    if node.keywords and not _is_constructor_call_name(callee):
        return None
    return _CallOrigin(
        callee=callee,
        lineno=getattr(node, "lineno", 0),
        col=getattr(node, "col_offset", 0),
    )


def _call_origin_from_expr_scoped(
    node: ast.expr,
    scope: Optional[_ValueScope],
) -> Optional[_CallOrigin]:
    origin = _call_origin_from_expr(node)
    if origin is None:
        origin = _inline_receiver_method_origin(node, scope)
    if origin is not None:
        return origin
    if scope is None:
        return None
    if not (isinstance(node, ast.Call) and not node.keywords):
        return None
    if not (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    ):
        return None
    receiver_origin = scope.origins.get(node.func.value.id)
    if receiver_origin is None:
        return None
    if not _is_constructor_call_name(receiver_origin.callee):
        return None
    return _CallOrigin(
        callee=f"{receiver_origin.callee}.{node.func.attr}",
        lineno=getattr(node, "lineno", 0),
        col=getattr(node, "col_offset", 0),
        constructor_args=receiver_origin.constructor_args,
        constructor_default_params=receiver_origin.constructor_default_params,
        receiver_constructor=receiver_origin.callee,
    )


def _inline_receiver_method_origin(
    node: ast.expr,
    scope: Optional[_ValueScope],
) -> Optional[_CallOrigin]:
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Call)
        and not node.keywords
    ):
        return None
    receiver_origin = _inline_receiver_call_origin(node.func.value, scope)
    if receiver_origin is None or receiver_origin.receiver_constructor is None:
        return None
    return _CallOrigin(
        callee=f"{receiver_origin.receiver_constructor}.{node.func.attr}",
        lineno=getattr(node, "lineno", 0),
        col=getattr(node, "col_offset", 0),
        constructor_args=receiver_origin.constructor_args,
        constructor_default_params=receiver_origin.constructor_default_params,
        receiver_constructor=receiver_origin.receiver_constructor,
    )


def _inline_receiver_call_origin(
    node: ast.Call,
    scope: Optional[_ValueScope],
) -> Optional[_CallOrigin]:
    direct = _call_origin_from_expr(node)
    if direct is not None and _is_constructor_call_name(direct.callee):
        constructor_terms = _constructor_call_terms_for_origin(node, direct, scope)
        if constructor_terms is None:
            return None
        constructor_args, constructor_default_params = constructor_terms
        direct.constructor_args = constructor_args
        direct.constructor_default_params = constructor_default_params
        direct.receiver_constructor = direct.callee
        return direct
    nested = _inline_receiver_method_origin(node, scope)
    if nested is not None:
        return nested
    return None


def _constructor_call_terms_for_origin(
    call: ast.Call,
    origin: _CallOrigin,
    scope: Optional[_ValueScope],
) -> Optional[Tuple[Tuple[Term, ...], Tuple[str, ...]]]:
    if not _is_constructor_call_name(origin.callee):
        return None
    active_scope = scope or _ValueScope()
    mapping = _constructor_call_arg_mapping(call, origin.callee, active_scope)
    if mapping is not None:
        return mapping
    if call.keywords:
        return None
    try:
        return (
            tuple(_translate_term_scoped(arg, active_scope) for arg in call.args),
            (),
        )
    except ValueError:
        return None


def _is_constructor_call_expr(
    node: ast.Call,
    scope: Optional[_ValueScope] = None,
) -> bool:
    origin = _call_origin_from_expr_scoped(node, scope)
    return origin is not None and _is_constructor_call_name(origin.callee)


def _assertion_value_exprs(stmt: ast.stmt) -> List[ast.expr]:
    exprs: List[ast.expr] = []
    if isinstance(stmt, ast.Assert):
        exprs.append(stmt.test)
    elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        name = _attr_method_name(stmt.value.func)
        if name in _UNITTEST_BINARY_PREDICATES:
            exprs.extend(stmt.value.args[:2])
        elif name in _UNITTEST_IDENTITY_PREDICATES:
            exprs.extend(stmt.value.args[:2])
        elif name in _UNITTEST_NONE_PREDICATES and stmt.value.args:
            exprs.append(stmt.value.args[0])
        elif name in _UNITTEST_TRUTH_PREDICATES and stmt.value.args:
            exprs.append(stmt.value.args[0])
    return exprs


def _collect_assertion_calls(
    stmt: ast.stmt,
    scope: Optional[_ValueScope] = None,
) -> List[ast.Call]:
    calls: List[ast.Call] = []
    seen: Set[Tuple[int, int]] = set()
    for expr in _assertion_value_exprs(stmt):
        for node in ast.walk(expr):
            if not isinstance(node, ast.Call):
                continue
            if _is_constructor_call_expr(node, scope):
                continue
            if _call_origin_from_expr_scoped(node, scope) is None:
                continue
            key = _call_key(node)
            if key in seen:
                continue
            seen.add(key)
            calls.append(node)
    return sorted(calls, key=_call_key)


def _origins_for_assertion(stmt: ast.stmt, scope: _ValueScope) -> List[_CallOrigin]:
    origins: List[_CallOrigin] = []
    for expr in _assertion_value_exprs(stmt):
        for node in ast.walk(expr):
            if isinstance(node, ast.Name) and node.id in scope.origins:
                origins.append(scope.origins[node.id])
    return _unique_origins(origins)


def _unique_origins(origins: List[_CallOrigin]) -> List[_CallOrigin]:
    out: List[_CallOrigin] = []
    seen: Set[Tuple[str, int, int]] = set()
    for origin in origins:
        key = (origin.callee, origin.lineno, origin.col)
        if key in seen:
            continue
        seen.add(key)
        out.append(origin)
    return out


def _translate_call_rhs(
    call: ast.Call,
    scope: _ValueScope,
    call_vars: Dict[Tuple[int, int], Term],
) -> Term:
    if isinstance(call.func, ast.Attribute):
        return _translate_term_scoped(call, scope, call_vars)
    if not isinstance(call.func, ast.Name):
        raise ValueError("call target must be a simple name")
    if call.keywords:
        raise ValueError("call with kwargs is not liftable")
    return ctor(
        call.func.id,
        [_translate_term_scoped(arg, scope, call_vars) for arg in call.args],
    )


def _lift_branch_guard(node: ast.expr, scope: _ValueScope) -> Formula:
    try:
        return _translate_bool_expr_scoped(node, scope)
    except ValueError:
        return atomic("python_branch_condition", [str_const(_unparse(node))])


def _lift_assertion_stmt_scoped(
    stmt: ast.stmt,
    scope: _ValueScope,
    call_vars: Optional[Dict[Tuple[int, int], Term]] = None,
) -> Formula:
    if isinstance(stmt, ast.Assert):
        return _translate_bool_expr_scoped(stmt.test, scope, call_vars)
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        call = stmt.value
        name = _attr_method_name(call.func)
        if name in _UNITTEST_IDENTITY_PREDICATES:
            if len(call.args) < 2:
                raise ValueError(f"{name} expects at least 2 positional args")
            l = _translate_term_scoped(call.args[0], scope, call_vars)
            r = _translate_term_scoped(call.args[1], scope, call_vars)
            return _comparison_from_identity_symbol(
                _UNITTEST_IDENTITY_PREDICATES[name],
                l,
                r,
            )
        if name in _UNITTEST_BINARY_PREDICATES:
            if len(call.args) < 2:
                raise ValueError(f"{name} expects at least 2 positional args")
            l = _translate_term_scoped(call.args[0], scope, call_vars)
            r = _translate_term_scoped(call.args[1], scope, call_vars)
            return _comparison_from_symbol(_UNITTEST_BINARY_PREDICATES[name], l, r)
        if name in _UNITTEST_NONE_PREDICATES:
            if len(call.args) < 1:
                raise ValueError(f"{name} expects 1 positional arg")
            t = _translate_term_scoped(call.args[0], scope, call_vars)
            return comparison_with_none_guard(
                _UNITTEST_NONE_PREDICATES[name],
                t,
                ctor("None", []),
                emit_none_guard=True,
            )
        if name == "assertTrue":
            if len(call.args) < 1:
                raise ValueError("assertTrue expects 1 positional arg")
            return _translate_bool_expr_scoped(call.args[0], scope, call_vars)
        if name == "assertFalse":
            if len(call.args) < 1:
                raise ValueError("assertFalse expects 1 positional arg")
            return not_(_translate_bool_expr_scoped(call.args[0], scope, call_vars))
    raise ValueError("statement is not a value-scope assertion")


def _translate_bool_expr_scoped(
    node: ast.expr,
    scope: _ValueScope,
    call_vars: Optional[Dict[Tuple[int, int], Term]] = None,
) -> Formula:
    if isinstance(node, ast.Compare):
        def _scoped_term_fn(n: ast.expr) -> Term:
            return _translate_term_scoped(n, scope, call_vars)
        if len(node.ops) == 1:
            # pytest.approx interception: must happen BEFORE generic term
            # translation so approx calls are never silently lifted as ctor terms.
            approx_formula = _lift_approx_comparison(
                node.ops[0], node.left, node.comparators[0], _scoped_term_fn
            )
            if approx_formula is not None:
                return approx_formula
            member_formula = _lift_literal_membership(
                node.ops[0], node.left, node.comparators[0], _scoped_term_fn
            )
            if member_formula is not None:
                return member_formula
            return _comparison_from_ast_op(
                node.ops[0],
                _scoped_term_fn(node.left),
                _scoped_term_fn(node.comparators[0]),
            )
        # Chained comparison: n >= 2 operators.
        return _translate_chained_compare(node, _scoped_term_fn)
    if isinstance(node, ast.BoolOp):
        operands = [
            _translate_bool_expr_scoped(v, scope, call_vars) for v in node.values
        ]
        if isinstance(node.op, ast.And):
            return and_(operands)
        if isinstance(node.op, ast.Or):
            return connective("or", operands)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not_(_translate_bool_expr_scoped(node.operand, scope, call_vars))
    if isinstance(node, ast.Call):
        # Truthiness call (``assert h.startswith(p)``): lift as uninterpreted
        # predicate.  Use a term-translator that honours the current SSA scope.
        def _scoped_term(n: ast.expr) -> Term:
            return _translate_term_scoped(n, scope, call_vars)
        return _translate_truthiness_call_formula(node, _scoped_term)
    # Bare-var / attribute truthiness (``assert flag``, ``assert obj.ok``):
    # encode as ``eq(term, True)``.  This path is a fallback for non-call
    # expressions that are syntactically boolean; it does NOT apply to Call
    # nodes (handled above) — so isinstance and other calls are not silently
    # wrapped here.
    term = _translate_term_scoped(node, scope, call_vars)
    return eq(term, bool_const(True))


def _translate_term_scoped(
    node: ast.expr,
    scope: _ValueScope,
    call_vars: Optional[Dict[Tuple[int, int], Term]] = None,
) -> Term:
    call_vars = call_vars or {}
    if isinstance(node, ast.Name):
        if node.id in scope.current:
            return scope.current[node.id]
        return _translate_term(node)
    if isinstance(node, ast.Constant):
        return _translate_term(node)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _translate_term(node)
    if isinstance(node, (ast.Dict, ast.Set, ast.Tuple, ast.List)):
        structured = _translate_str_bytes_sequence_literal_term(
            node,
            lambda element: _translate_term_scoped(element, scope, call_vars),
        )
        if structured is not None:
            return structured
        # Dict/set literal in value-scope: delegate to the content-hashed
        # opaque-constant translator.  SSA scope does not affect the literal
        # itself (its content is fully determined at lift time).
        return _translate_dict_set_literal_term(node)
    if isinstance(node, ast.Call):
        # pytest.approx as a sub-term in value-scope: LOUD REFUSE (same
        # reasoning as in _translate_term — see that guard for details).
        if _is_pytest_approx_call(node):
            raise ValueError(
                "approx: pytest.approx(...) in an unsupported position — "
                "approx is only liftable as the comparand of == or != "
                "(e.g. `assert x == pytest.approx(target)`); "
                "use it in a direct == or != comparison at the top level of an assert"
            )
        module_attr_callee = _module_attr_callee(node.func)
        if (
            module_attr_callee is not None
            and _is_constructor_call_name(module_attr_callee)
        ):
            mapping = _constructor_call_arg_mapping(node, module_attr_callee, scope)
            if mapping is not None:
                constructor_args, _defaulted = mapping
                return ctor(f"call:{module_attr_callee}", list(constructor_args))
            if node.keywords:
                raise ValueError("qualified constructor call with kwargs is not liftable")
            return ctor(
                f"call:{module_attr_callee}",
                [_translate_term_scoped(arg, scope, call_vars) for arg in node.args],
            )
        if isinstance(node.func, ast.Attribute):
            # Method call as a TERM: ``recv.method(args)`` → callval ctor.
            # SSA-key the receiver through the current scope so that
            # ``out = f(); assert out.m() == 1; out = g(); assert out.m() == 2``
            # produces distinct ctor terms (out$0 vs out$1 as receiver).
            # LOUD REFUSE on keyword args.
            method = node.func.attr
            if node.keywords:
                raise ValueError(
                    f"method call `{method}` with keyword args is not liftable as a term "
                    "(keyword args cannot be order-stably translated without knowing "
                    "the function signature)"
                )
            recv_term = _translate_term_scoped(node.func.value, scope, call_vars)
            arg_terms = [recv_term]
            for i, arg in enumerate(node.args):
                try:
                    arg_terms.append(_translate_term_scoped(arg, scope, call_vars))
                except ValueError as e:
                    raise ValueError(
                        f"method call `{method}` arg[{i}] not liftable as term: {e}"
                    )
            head = _callval_head(method, len(arg_terms))
            return ctor(head, arg_terms)
        if not isinstance(node.func, ast.Name):
            raise ValueError("call target must be a simple name or method (recv.method)")
        if node.keywords:
            raise ValueError("call with kwargs is not liftable")
        if _is_constructor_call_name(node.func.id):
            return ctor(
                f"call:{node.func.id}",
                [_translate_term_scoped(arg, scope, call_vars) for arg in node.args],
            )
        key = _call_key(node)
        if key in call_vars:
            return call_vars[key]
        return ctor(
            node.func.id,
            [_translate_term_scoped(arg, scope, call_vars) for arg in node.args],
        )
    if isinstance(node, ast.BinOp):
        op = _BINOP_TERM_NAMES.get(type(node.op))
        if op is None:
            raise ValueError("unsupported binary operator")
        return ctor(
            op,
            [
                _translate_term_scoped(node.left, scope, call_vars),
                _translate_term_scoped(node.right, scope, call_vars),
            ],
        )
    if isinstance(node, ast.Attribute):
        # Attribute access in value-scope context.  SSA-key the attribute
        # Var on the base's current SSA name so that ``out = f(x); assert
        # out.v == 1; out = g(y); assert out.v == 2`` produces two
        # independent Vars (``out$0.v`` and ``out$1.v``) rather than the
        # same ``out.v`` Var, which would look like a contradiction.
        # Without SSA the two atoms would share a Var and a conjunction
        # across the two assertions would be spuriously UNSAT.
        #
        # Algorithm: walk the dotted path; for each Name segment look it up
        # in scope.current; replace the FIRST Name segment that has an SSA
        # version.  Deep chains like ``a.b.c`` where only ``a`` is in scope
        # become ``a$N.b.c``.  If no segment is in scope, fall through to
        # the unscoped translator (raw dotted path = opaque free var) which
        # is unchanged behaviour for parameters and module-level names.
        ssa_attr_name = _ssa_dotted_attr_path(node, scope)
        if ssa_attr_name is not None:
            return make_var(ssa_attr_name)
        # Fall through: base not in scope → opaque free var by raw path.
        return _translate_term(node)
    if isinstance(node, ast.Subscript):
        # Subscript-index in value-scope context.  SSA-key the base: translate
        # the base expression under the scope so that if the base var has been
        # SSA-renamed (``parsed = f(); … parsed = g(); …``), the subscript Ctors
        # for the two generations are distinct (``subscript(parsed$0, k)`` vs
        # ``subscript(parsed$1, k)``).  This mirrors the SSA treatment of
        # attribute access: same-generation base + same key = same term = UNSAT
        # on contradiction; different generation = distinct terms = PROVEN.
        # Non-literal keys LOUDLY REFUSE via ``_subscript_key_term``.
        projected = _static_container_projection_from_expr(
            node.value,
            node.slice,
            lambda element: _translate_term_scoped(element, scope, call_vars),
        )
        if projected is not None:
            return projected
        try:
            key_term = _subscript_key_term(node.slice)
        except ValueError:
            key_term = None
        if key_term is not None and isinstance(node.value, ast.Name):
            projection = scope.projections.get(node.value.id, {}).get(key_term)
            if projection is not None:
                return projection
        base_term = _translate_term_scoped(node.value, scope, call_vars)
        return _translate_subscript_term(node, base_term)
    raise ValueError("expression shape not in value-scope lift whitelist")


_BINOP_TERM_NAMES = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.Mod: "%",
}


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)  # type: ignore[attr-defined]
    except Exception:
        return node.__class__.__name__


# ---------------------------------------------------------------------------
# PATTERN 7: pytest.raises blocks
# ---------------------------------------------------------------------------
#
# Handles test functions whose body contains ``with pytest.raises(ExcType):``
# blocks.  The CONSISTENCY-LEVEL model:
#
#   ``with pytest.raises(ExcType): <body-call>``
#   lifts to: ``eq(ctor("raised_exc_a1", [call_term]), str_const(ExcType_name))``
#
# This models the RAISED EXCEPTION TYPE as a function-valued term keyed on
# the callsite, exactly mirroring the ``callval`` method-call-result encoding
# (Pattern 3 / Form 3).  DISCRIMINATION follows automatically:
#
#   same callsite + two DIFFERENT ExcType names
#     -> ``eq(g, str_const("ValueError")) ∧ eq(g, str_const("KeyError"))``
#     -> same term g equated to two distinct str-constants
#     -> UNSAT by EUF / congruence (no axioms needed)
#     -> REFUSED
#
#   same callsite + same ExcType twice -> SAT -> PROVEN
#
# SOUNDNESS RULES:
#   - ExcType must be a simple Name (not a dotted attr, not a Tuple).
#     Tuples (``raises((ValueError, KeyError))``) mean "one of" — cannot be
#     modelled as a single string constant soundly; LOUD REFUSE.
#   - ``as exc_info`` clause (``optional_vars`` present): LOUD REFUSE — we
#     cannot soundly model the captured exception object.
#   - ``match=`` or any keyword on pytest.raises: LOUD REFUSE — regex-matching
#     the exception message is a softer assertion; deferred to production-bridge.
#   - Body must be exactly ONE statement.  Multi-statement bodies cannot be
#     reduced to one callsite term; LOUD REFUSE.
#   - The single body statement must be an ``ast.Expr`` (bare call expression)
#     whose call translates via ``_translate_term``.  Assignments, assertions,
#     and other statement kinds inside the with-body: LOUD REFUSE.
#   - The test body must contain ONLY ``with pytest.raises(...)`` blocks (and
#     optionally ``ast.Pass``).  Any other statement kind makes the test body
#     more complex than the raises-only shape — LOUD REFUSE with reason.
#     (Mixed binding+raises bodies are deliberately out of scope for v0;
#     the raises-only restriction prevents SSA-scope issues.)
#
# TEETH (deferred):
#   Whether the body ACTUALLY raises (i.e. a ``with pytest.raises`` around a
#   call that provably CANNOT raise = a provably-wrong test) requires
#   production-bridge reasoning (callsite postconditions / exception
#   specifications).  This is explicitly deferred to the production-bridge
#   discharge path.  The consistency-level lift here only checks that the
#   RAISE CLAIM is internally consistent (no contradictory exception types
#   for the same callsite within the same test).
#
# GATE: fires when the body contains AT LEAST ONE ``ast.With`` node.


@dataclass(frozen=True)
class _RaisesBlockLift:
    formula: Formula
    source_warrants: Tuple[dict, ...] = ()


def _is_pytest_raises_func(func: ast.expr) -> bool:
    """Return True iff ``func`` is ``pytest.raises`` or bare ``raises``."""
    # bare: ``raises(ExcType)``
    if isinstance(func, ast.Name) and func.id == "raises":
        return True
    # ``pytest.raises(ExcType)``
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "raises"
        and isinstance(func.value, ast.Name)
        and func.value.id == "pytest"
    ):
        return True
    return False


def _parse_raises_exc_name(node: ast.expr) -> Optional[str]:
    """Extract the exception type name from a simple ``Name`` node.

    Returns the name string (e.g. ``"ValueError"``) or None if the shape
    is not a simple Name (e.g. a Tuple or attribute chain).  The caller
    must LOUDLY REFUSE on None.
    """
    if isinstance(node, ast.Name):
        return node.id
    return None


def _lift_raises_block(
    stmt: ast.With,
    source_path: str,
    test_name: str,
) -> "Union[_RaisesBlockLift, str]":
    """Try to lift a single ``with pytest.raises(ExcType): <call>`` block.

    Returns:
      - A ``_RaisesBlockLift`` carrying the raised-exc eq atom on success.
      - A ``str`` loud-refuse reason on any unsupported shape.

    Callers must treat a str return as a LOUD REFUSE (claim, warn, no contract).
    """
    # Must be exactly one withitem.
    if len(stmt.items) != 1:
        return (
            f"pytest.raises: expected exactly 1 withitem, got {len(stmt.items)}; "
            "multi-target with-clause is not liftable"
        )
    item = stmt.items[0]

    # No ``as exc_info`` clause.
    if item.optional_vars is not None:
        return (
            "pytest.raises: ``as exc_info`` clause is not soundly liftable "
            "(captured exception object inspection is deferred to production-bridge)"
        )

    ce = item.context_expr
    # context_expr must be a Call whose func is pytest.raises / raises.
    if not isinstance(ce, ast.Call) or not _is_pytest_raises_func(ce.func):
        return (
            f"With statement context manager is not pytest.raises / raises: "
            f"`{_unparse(ce)[:60]}`; only pytest.raises is in scope for this lifter"
        )

    # No keyword args (e.g. match=).
    if ce.keywords:
        kw_names = [k.arg for k in ce.keywords]
        return (
            f"pytest.raises: keyword arguments {kw_names!r} are not soundly liftable "
            "(match= regex and other kwargs are deferred to production-bridge)"
        )

    # Must have exactly one positional arg: the exception type.
    if len(ce.args) != 1:
        return (
            f"pytest.raises: expected exactly 1 exception type argument, "
            f"got {len(ce.args)}"
        )

    exc_arg = ce.args[0]
    exc_name = _parse_raises_exc_name(exc_arg)
    if exc_name is None:
        return (
            f"pytest.raises: exception type argument must be a simple Name "
            f"(e.g. ValueError), got `{_unparse(exc_arg)[:60]}`; "
            "Tuple exception types (raises((A,B))) are not soundly liftable "
            "as a single constant"
        )

    # Body must be exactly one statement.
    if len(stmt.body) != 1:
        return (
            f"pytest.raises: body must be exactly 1 statement "
            f"(got {len(stmt.body)}); multi-statement bodies cannot be reduced "
            "to a single callsite term soundly"
        )

    body_stmt = stmt.body[0]
    # Body statement must be a bare ``ast.Expr`` (expression statement, i.e. a call).
    if not isinstance(body_stmt, ast.Expr):
        return (
            f"pytest.raises: body statement must be a bare call expression "
            f"(ast.Expr), got `{type(body_stmt).__name__}`; "
            "assignments, assertions, and other statement kinds inside raises "
            "body are not soundly liftable"
        )

    call_expr = body_stmt.value
    # Translate the call expression as a term.
    try:
        call_term = _translate_term(call_expr)
    except ValueError as e:
        return (
            f"pytest.raises: body call not translatable as a term: {e}"
        )

    # Build: eq(ctor("raised_exc_a1", [call_term]), str_const(exc_name))
    # "raised_exc_a1" = "the exception raised by this call" as a function-valued
    # term.  Arity suffix "_a1" encodes arity=1 (one arg: the call term).
    raised_term = ctor("raised_exc_a1", [call_term])
    exc_const = str_const(exc_name)
    formulas: List[Formula] = [eq(raised_term, exc_const)]
    source_warrants: List[dict] = []
    origin = _call_origin_from_expr(call_expr)
    if origin is not None:
        raise_u, _raise_refusal = raise_locus_universe_for_callee(origin.callee)
        if raise_u is not None and raise_u.source_memento is not None:
            _append_unique_source_warrant(
                source_warrants,
                _source_warrant_for_universe(
                    raise_u,
                    role="python.raise-locus-universe",
                    universe_kind="raise-locus",
                ),
            )
        handler_u, _handler_refusal = exception_handler_raise_universe_for_callee(
            origin.callee
        )
        if handler_u is not None:
            formulas.append(eq(raised_term, str_const(handler_u.exception_name)))
            if handler_u.source_memento is not None:
                _append_unique_source_warrant(
                    source_warrants,
                    _source_warrant_for_universe(
                        handler_u,
                        role="python.exception-handler-raise-universe",
                        universe_kind="exception-handler-raise",
                    ),
                )
        branch_raise_u, _branch_raise_refusal = (
            branch_selected_raise_universe_for_callee(origin.callee)
        )
        if branch_raise_u is not None and _branch_selected_raise_applies(
            branch_raise_u,
            call_term,
            origin,
        ):
            formulas.append(eq(raised_term, str_const(branch_raise_u.exception_name)))
            if branch_raise_u.source_memento is not None:
                _append_unique_source_warrant(
                    source_warrants,
                    _source_warrant_for_universe(
                        branch_raise_u,
                        role="python.branch-selected-raise-universe",
                        universe_kind="branch-selected-raise",
                    ),
                )
    return _RaisesBlockLift(
        formulas[0] if len(formulas) == 1 else and_(formulas),
        tuple(source_warrants),
    )


def _classify_raises_body(
    body: Sequence[ast.stmt],
    test_name: str,
    source_path: str,
    out: Layer2Output,
) -> bool:
    """Pattern 7: bodies containing ``with pytest.raises(...)`` blocks.

    Returns True if this pattern claimed the test (even on a loud refusal),
    False if the body contains NO ``ast.With`` nodes (caller tries next pattern).

    Strategy:
      - If no With nodes in body: return False (not our pattern).
      - Claim the test immediately (so Layer 0 does not silently retry it).
      - Check all non-With stmts: only ``ast.Pass`` is permitted alongside
        raises blocks in v0.  Any other stmt kind → LOUD REFUSE for entire body.
      - For each With node: attempt lift.  Loud-refuse reason → LOUD REFUSE
        for entire body (claim, warn, zero contracts).  Successful formula
        → accumulate atom.
      - If all With nodes lifted successfully AND no other stmts: conjoin atoms
        into ONE contract (Pattern-3 shape); emit as ContractDecl.
    """
    # Gate: only fire if body has at least one pytest.raises With block.
    # Non-pytest.raises With bodies fall through to mixed-body, which
    # explicitly loud-refuses any With statement it encounters.
    has_raises_with = any(
        isinstance(s, ast.With)
        and len(s.items) == 1
        and isinstance(s.items[0].context_expr, ast.Call)
        and _is_pytest_raises_func(s.items[0].context_expr.func)
        for s in body
    )
    if not has_raises_with:
        return False

    out.claimed_tests.add(test_name)
    out.seen += 1

    # Check non-With statements: only Pass is allowed alongside raises blocks.
    for stmt in body:
        if isinstance(stmt, (ast.With, ast.Pass)):
            continue
        # Any other statement kind (binding, assert, for, try, etc.) is out of scope.
        out.raises_skipped += 1
        out.warnings.append(
            LiftWarning(
                source_path,
                test_name,
                f"layer2 pytest.raises: LOUD REFUSAL — body contains a "
                f"`{type(stmt).__name__}` statement alongside raises block(s); "
                "only pure raises-block bodies (with optional pass) are liftable "
                "in v0; mixed binding+raises bodies are out of scope",
            )
        )
        return True

    # Try to lift each With block.
    atoms: List[Formula] = []
    source_warrants: List[dict] = []
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        # All remaining stmts are With (checked above).
        result = _lift_raises_block(stmt, source_path, test_name)
        if isinstance(result, str):
            # Loud refuse.
            out.raises_skipped += 1
            out.warnings.append(
                LiftWarning(
                    source_path,
                    test_name,
                    f"layer2 pytest.raises: LOUD REFUSAL — {result}",
                )
            )
            return True
        atoms.append(result.formula)
        for warrant in result.source_warrants:
            _append_unique_source_warrant(source_warrants, warrant)

    if not atoms:
        # Body was all Pass — vacuous; loud refuse.
        out.raises_skipped += 1
        out.warnings.append(
            LiftWarning(
                source_path,
                test_name,
                "layer2 pytest.raises: LOUD REFUSAL — body contains no liftable "
                "raises blocks (only pass statements)",
            )
        )
        return True

    # All blocks lifted successfully.
    inv = atoms[0] if len(atoms) == 1 else and_(atoms)
    out.decls.append(
        ContractDecl(name=test_name, inv=inv, source_warrants=source_warrants)
    )
    out.lifted += 1
    out.raises_lifted += 1
    return True


# ---------------------------------------------------------------------------
# PATTERN 6: mixed-body (opaque bindings + multiple asserts)
# ---------------------------------------------------------------------------
#
# Handles test methods / functions whose body is an interleaving of
# assignment statements (setup bindings) and ``assert`` statements, where the
# RHS of many bindings is NOT translatable (e.g. ``out = mint_contract(**kw)``,
# ``parsed = json.loads(...)``).  Pattern 5 requires a translatable call-result
# and emits ``::facts`` / ``::assertion`` contracts with implication wiring.
# Pattern 6 is simpler: it does NOT emit ``::facts`` contracts and does NOT
# require a translatable RHS.  Instead it:
#
#   1. Builds an SSA scope by walking each binding in order.  A translatable
#      RHS → SSA var bound to a term (same as Pattern 5).  An opaque RHS →
#      SSA var bound to a fresh free var (name$N) with NO value fact.  This
#      keeps attribute-access assertions (``assert out.cid == X``) scoped to
#      the correct SSA generation.
#
#   2. Collects liftable ``assert`` statements, translating each under the
#      current SSA scope.  Unliftable asserts → warn-and-skip (do NOT refuse
#      the whole method; partial lift is better than silence).
#
#   3. Conjoins all successfully lifted atoms into ONE ``ContractDecl`` named
#      by the test name.  This lands in the consistency pass as a whole-test
#      invariant (same path as Pattern 3), so contradictions in the conjoined
#      formula are detected by z3.
#
# SOUNDNESS RULES:
#   - Bindings are FACTS (definitions), never asserted properties.  They are
#     NOT emitted as contracts and do NOT enter the consistency pass.
#   - Opaque bindings produce a fresh SSA var with zero constraints → they
#     cannot create spurious UNSAT.  The consistency pass sees only the
#     asserted properties, which is correct.
#   - Reassignment: SSA bumps the version, so ``out = f(); assert out.x==1;
#     out = g(); assert out.x==2`` produces ``out$0.x`` and ``out$1.x``
#     (distinct Vars) → the two atoms are independent → CONSISTENT.
#   - Methods with unsupported control-flow or mutation (``with``, ``for``,
#     ``while``, ``try``, ``import``, subscript-assign) are LOUDLY REFUSED:
#     the method is claimed so Layer 0 does not retry it, a warning is
#     emitted, and zero contracts are produced.
#
# GATE: fires ONLY when the body has AT LEAST ONE binding AND at least one
# liftable assert.  Pure-assert bodies (all asserts, no binding) are Pattern 3.
# Pure-binding bodies (no asserts) are not test characterizations; they fall
# through to Layer 0.


def _mixed_body_unsupported_stmt(stmt: ast.stmt) -> Optional[str]:
    """Return a human-readable reason if ``stmt`` is an unsupported statement
    for the mixed-body pattern, or None if it is permitted.

    Permitted: ``ast.Assign`` (simple-name target only),
    ``ast.AnnAssign`` (simple-name target), ``ast.Assert``, ``ast.Pass``.
    Everything else (``with``, ``for``, ``while``, ``try``, ``import``,
    ``raise``, subscript-assign, etc.) is UNSUPPORTED → loud refusal.
    """
    if isinstance(stmt, ast.Assert):
        return None
    if isinstance(stmt, ast.Pass):
        return None
    if isinstance(stmt, ast.Assign):
        # Subscript or attribute ASSIGN target is mutation → unsupported.
        for tgt in stmt.targets:
            if not isinstance(tgt, ast.Name):
                return (
                    f"non-simple assignment target `{_unparse(tgt)[:60]}` "
                    "(subscript/attribute mutation is not soundly liftable)"
                )
        return None
    if isinstance(stmt, ast.AnnAssign):
        if not isinstance(stmt.target, ast.Name):
            return (
                f"non-simple annotated-assignment target `{_unparse(stmt.target)[:60]}`"
            )
        return None
    if isinstance(stmt, ast.With):
        # With statements (including pytest.raises) are handled by Pattern 7
        # (_classify_raises_body) which runs before mixed-body.  If a With
        # survives to here it is an unsupported context manager — loudly refuse.
        return (
            "With statement (context manager) in mixed-body test is not soundly "
            "liftable — use pytest.raises blocks only at top-level of a raises-only "
            "test body; other context managers are out of scope"
        )
    # Anything else is unsupported.
    kind = type(stmt).__name__
    return f"unsupported statement kind `{kind}` in mixed-body test"



def _classify_mixed_body(
    body: Sequence[ast.stmt],
    test_name: str,
    source_path: str,
    out: Layer2Output,
) -> bool:
    """Pattern 6: mixed body with opaque bindings + multiple asserts.

    Returns True if this pattern claimed the test (even on a loud refusal),
    False if the body does not fit the mixed-body shape (caller tries next).
    """
    # Pre-screen: the body must contain at least one binding AND at least one
    # assert.  Pure-assert is Pattern 3; pure-binding is not a test claim.
    has_binding = any(isinstance(s, (ast.Assign, ast.AnnAssign)) for s in body)
    has_assert = any(isinstance(s, ast.Assert) for s in body)
    if not (has_binding and has_assert):
        return False

    # Check every statement for unsupported constructs BEFORE doing any work.
    unsupported: List[str] = []
    for stmt in body:
        reason = _mixed_body_unsupported_stmt(stmt)
        if reason is not None:
            unsupported.append(reason)

    if unsupported:
        # LOUD REFUSAL: claim the test so Layer 0 does not retry it, emit
        # a warning per unsupported construct, produce zero contracts.
        out.claimed_tests.add(test_name)
        out.seen += 1
        out.mixed_body_skipped += 1
        for reason in unsupported:
            out.warnings.append(
                LiftWarning(
                    source_path,
                    test_name,
                    f"layer2 mixed-body: LOUD REFUSAL — {reason}",
                )
            )
        return True

    # --- SSA scope build + assertion collection -------------------------
    #
    # Walk the body in order.  For each binding, bump the SSA version and
    # install a fresh var in scope (opaque bindings → fresh free var with no
    # constraints; translatable bindings → term-valued var, same as P5).
    # For each assert, translate under the current scope and collect the atom.

    # SSA state: maps local name → current SSA var term.
    ssa_current: Dict[str, Term] = {}
    ssa_versions: Dict[str, int] = {}

    atoms: List[Formula] = []
    skip_reasons: List[str] = []

    for stmt in body:
        # ---- Binding ----
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            if isinstance(stmt, ast.Assign):
                target_name = stmt.targets[0].id  # simple name guaranteed above
                value_node = stmt.value
            else:  # AnnAssign
                target_name = stmt.target.id
                value_node = stmt.value  # may be None (bare annotation)

            version = ssa_versions.get(target_name, 0)
            ssa_versions[target_name] = version + 1
            ssa_name = f"{target_name}${version}"
            ssa_var = make_var(ssa_name)
            ssa_current[target_name] = ssa_var
            # We do NOT emit a facts contract. The SSA var is an opaque free
            # var unless the RHS is translatable (in which case a value
            # constraint would be useful, but for the consistency pass only
            # the asserted properties matter; we intentionally keep this
            # simple and sound).
            continue

        # ---- Assert ----
        if isinstance(stmt, ast.Assert):
            # Translate under the current SSA scope.
            scope = _ValueScope(current=dict(ssa_current))
            try:
                atom = _lift_assertion_stmt_scoped(stmt, scope)
            except ValueError as e:
                skip_reasons.append(f"`{_unparse(stmt)[:60]}`: {e}")
                continue
            atoms.append(atom)
            continue

        # ---- Pass ----
        # already permitted; nothing to do.

    if not atoms:
        # No assert was liftable. Warn and claim (so Layer 0 can try).
        out.claimed_tests.add(test_name)
        out.seen += 1
        out.mixed_body_skipped += 1
        out.warnings.append(
            LiftWarning(
                source_path,
                test_name,
                f"layer2 mixed-body: 0 of {len([s for s in body if isinstance(s, ast.Assert)])} "
                f"asserts were liftable; releasing claim to Layer 0. "
                f"Skipped: {'; '.join(skip_reasons)}",
            )
        )
        return True

    # Conjoin all lifted atoms into ONE contract (Pattern-3 shape).
    # A single lifted atom is emitted as-is (no redundant and-wrapper).
    inv = atoms[0] if len(atoms) == 1 else and_(atoms)
    out.claimed_tests.add(test_name)
    out.seen += 1
    out.decls.append(ContractDecl(name=test_name, inv=inv))
    out.lifted += 1
    out.mixed_body_lifted += 1

    if skip_reasons:
        out.warnings.append(
            LiftWarning(
                source_path,
                test_name,
                f"layer2 mixed-body: {len(skip_reasons)} of "
                f"{len([s for s in body if isinstance(s, ast.Assert)])} asserts skipped "
                f"(unliftable shape): {'; '.join(skip_reasons)}",
            )
        )

    return True
