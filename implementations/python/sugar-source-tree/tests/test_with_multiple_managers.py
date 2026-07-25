"""Multi-manager resource ``with``: Python's own nesting, one control model.

    with A() as a, B() as b:
        body

IS

    with A() as a:
        with B() as b:
            body

so multi-manager routing is not a second sequencing mechanism. Construction
rewrites the multi-item ``With`` into single-item ``With`` nodes and the SAME
``WithResourceSugar`` / ``ExitSet.and_exit`` algebra carries every law:

- enter order is left-to-right (A is the outer node, entered first);
- exit order is right-to-left (B is inner, so its ``__exit__`` runs first);
- **failure entering B still exits A**, because B's whole With — including its
  enter-halt exit — is the *body* of A, and ``and_exit`` runs A's ``__exit__``
  over EVERY outgoing body edge, never only the completed one;
- a manager whose disposition is not authenticated stays typed-loud: routing
  admits nothing.

Every law twin here is paired 1:1 with a discrimination arm that perturbs the
expectation and asserts the perturbation fails.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    EnterResultContractV1,
    ExitContractV1,
    NeverSuppresses,
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ImportSignatureV2,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SourceTreePanic
from sugar_source_tree.tree import SourceFile


# ---------------------------------------------------------------- tree fixture


def _cid(char: str) -> str:
    return "blake3-512:" + char * 128


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _resolved(use_site) -> ContextManagerContractRefV1:
    """A total Value / NeverSuppresses authenticated protocol-resource member."""
    return ContextManagerContractRefV1(
        resolution_cid=_cid("r"),
        demand_cid=_cid("d"),
        use_site=use_site,
        use_site_cid=_hash_json(use_site.wire()),
        authenticated_import_use_cid=_cid("u"),
        import_binding_cid=_cid("i"),
        construction_context_generation_cid=_cid("g"),
        contract_cid=_cid("m"),
        payload_cid=_cid("p"),
        provenance_cid=_cid("v"),
        distribution_artifact_cid=_cid("a"),
        dependency_artifact_graph_cid=_cid("b"),
        module_source_cid=_cid("s"),
        resolved_definition_cid=_cid("f"),
        manager_construction_cid=_cid("n"),
        enter_testimony_cid=_cid("1"),
        exit_testimony_cid=_cid("2"),
        import_signature=ImportSignatureV2(()),
        semantics=ProtocolResourceSemanticsV1(
            enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
            exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
        ),
    )


def _function_sugar(tmp_path, src: str, *, resolve_items=None, name="f"):
    """Construct ``name``'s sugar with every With manager authenticated.

    ``resolve_items`` selects which manager item indices (per With node, in
    source order) get an authenticated row; the rest are left unresolved so the
    typed-loud face can be exercised.
    """
    path = tmp_path / "case.py"
    path.write_text(src, encoding="utf-8")
    identity = path_source(str(path))
    probe = SourceFile(identity)
    rows = {}
    for node in probe.nodes():
        if node.kind != "With":
            continue
        for index, item in enumerate(node.items):
            if resolve_items is not None and index not in resolve_items:
                continue
            coordinate = _coordinate(item.context_expr)
            rows[coordinate] = _resolved(coordinate)
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType(rows))
    )
    source = SourceFile(identity, construction_context=context)
    for fn in source.functions():
        if fn.name == name:
            return fn.sugar()
    raise AssertionError(f"no function {name}")


def _with_chain(sugar):
    """The chain of nested WithResourceSugars reachable from a function sugar."""
    chain = []

    def walk(node):
        if isinstance(node, WithResourceSugar):
            chain.append(node)
            for child in node.body:
                walk(child)
            return
        for field in ("body", "statements", "entries"):
            for child in getattr(node, field, ()) or ():
                walk(child)

    walk(sugar)
    return chain


TWO_MANAGERS = "def f(m, n):\n    with m, n:\n        pass\n    return m\n"
NESTED_SPELLING = (
    "def f(m, n):\n    with m:\n        with n:\n            pass\n    return m\n"
)


# ------------------------------------------------------- law / discrimination


def test_two_managers_nest_into_single_item_with_nodes(tmp_path):
    """LAW: `with m, n:` constructs A-outer / B-inner, one manager each."""
    chain = _with_chain(_function_sugar(tmp_path, TWO_MANAGERS))
    assert len(chain) == 2, f"expected two nested resource withs, got {len(chain)}"
    outer, inner = chain
    assert inner in outer.body
    assert outer.manager_slot_id != inner.manager_slot_id


def test_discrimination_two_managers_do_not_collapse_to_one(tmp_path):
    """BITE: a single flattened With would satisfy a naive `>=1` assertion."""
    chain = _with_chain(_function_sugar(tmp_path, TWO_MANAGERS))
    with pytest.raises(AssertionError):
        assert len(chain) == 1, "two managers must not collapse into one With"


def test_enter_order_is_left_to_right(tmp_path):
    """LAW: the FIRST source manager is the OUTER node — entered first."""
    sugar = _function_sugar(tmp_path, TWO_MANAGERS)
    outer, inner = _with_chain(sugar)
    path = tmp_path / "case.py"
    node = next(n for n in SourceFile(path_source(str(path))).nodes() if n.kind == "With")
    first_slot = node.items[0]._manager_slot_id()
    second_slot = node.items[1]._manager_slot_id()
    assert outer.manager_slot_id == first_slot
    assert inner.manager_slot_id == second_slot


def test_discrimination_enter_order_is_not_right_to_left(tmp_path):
    """BITE: swapping the expectation fails — order is real, not incidental."""
    sugar = _function_sugar(tmp_path, TWO_MANAGERS)
    outer, inner = _with_chain(sugar)
    path = tmp_path / "case.py"
    node = next(n for n in SourceFile(path_source(str(path))).nodes() if n.kind == "With")
    with pytest.raises(AssertionError):
        assert outer.manager_slot_id == node.items[1]._manager_slot_id()


def test_exit_order_is_right_to_left(tmp_path):
    """LAW: B is inner, so B.__exit__ is applied before A.__exit__.

    Nesting IS the exit order: the inner With's ExitSet (already past B's exit)
    is what A's ``and_exit`` consumes.
    """
    outer, inner = _with_chain(_function_sugar(tmp_path, TWO_MANAGERS))
    assert inner in outer.body
    assert outer not in inner.body


def test_discrimination_exit_order_is_not_left_to_right(tmp_path):
    """BITE: the reversed containment must not hold."""
    outer, inner = _with_chain(_function_sugar(tmp_path, TWO_MANAGERS))
    with pytest.raises(AssertionError):
        assert outer in inner.body


def test_multi_item_spelling_equals_nested_spelling(tmp_path):
    """LAW: `with m, n:` and the nested spelling build the SAME arm structure.

    Same instrument, both sides: identical WithResourceSugar chain shape, same
    dispositions, same body — proof that no parallel sequencing model was added.
    """
    flat = _with_chain(_function_sugar(tmp_path, TWO_MANAGERS))
    nested = _with_chain(_function_sugar(tmp_path, NESTED_SPELLING))
    assert len(flat) == len(nested) == 2
    assert [type(s).__name__ for s in flat] == [type(s).__name__ for s in nested]
    assert [s.disposition for s in flat] == [s.disposition for s in nested]
    assert [len(s.body) for s in flat] == [len(s.body) for s in nested]


def test_discrimination_equivalence_is_not_vacuous(tmp_path):
    """BITE: the equivalence would fail against a genuinely different shape."""
    flat = _with_chain(_function_sugar(tmp_path, TWO_MANAGERS))
    one = _with_chain(
        _function_sugar(tmp_path, "def f(m, n):\n    with m:\n        pass\n    return m\n")
    )
    with pytest.raises(AssertionError):
        assert len(flat) == len(one)


def test_second_manager_without_authentication_stays_typed_loud(tmp_path):
    """LAW: routing is not admission — an unauthenticated B is still loud.

    Nesting gives the second manager its own construction door, and that door
    still demands an authenticated disposition. The exact panic class depends
    on *how* the authority is missing (an absent table row is a
    ``BackendDefect``; a published resolution gap is a
    ``ContextManagerResolutionConstructionGap``); both are typed panics under
    ``SourceTreePanic`` and neither yields a constructed sugar.
    """
    with pytest.raises(SourceTreePanic):
        _function_sugar(tmp_path, TWO_MANAGERS, resolve_items={0})


def test_discrimination_authenticated_pair_is_not_loud(tmp_path):
    """BITE: the loudness above is caused by the MISSING row, not by nesting."""
    chain = _with_chain(_function_sugar(tmp_path, TWO_MANAGERS))
    assert len(chain) == 2


# --------------------------------------- routing law at the sugar/ExitSet layer


class _FixedSugar(Sugar):
    def __init__(self, outcome, *, probe=None):
        self._outcome = outcome
        self._probe = probe

    def desugar(self, ctx=None):
        del ctx
        if self._probe is not None:
            self._probe.append(1)
        return self._outcome

    @classmethod
    def witnesses(cls):
        return ()


class _FloorValue:
    def __init__(self, label: str):
        self.label = label

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import str_const

        return str_const(self.label)


def _resource(*, enter=None, body=None, slot="M", exit_probe=None):
    exit_sugar = _FixedSugar(Complete(_FloorValue("exited")), probe=exit_probe)
    return WithResourceSugar(
        manager=_FixedSugar(Complete(_FloorValue(f"mgr{slot}"))),
        manager_slot_id=slot,
        enter=enter or _FixedSugar(Complete(_FloorValue("entered"))),
        exit=exit_sugar,
        exit_face_id=f"{slot}#exit_face",
        body=body if body is not None else (),
        disposition=NeverSuppresses(),
        site=None,
    )


def _nested_pair(inner_enter, *, outer_exit_probe, inner_exit_probe):
    inner = _resource(enter=inner_enter, slot="B", exit_probe=inner_exit_probe)
    return _resource(body=(inner,), slot="A", exit_probe=outer_exit_probe)


def test_failure_entering_second_manager_still_exits_first():
    """LAW: B's ``__enter__`` halting still runs A's ``__exit__``.

    B's own exit must NOT run (B was never entered); A's exit MUST, because the
    enter-halt is an outgoing edge of A's body and ``and_exit`` fans over every
    outgoing edge, not only the completed one.
    """
    outer_exit, inner_exit = [], []
    halt = RaiseEffect(exception_name="OSError", occurrence="b.py:1:0")
    sugar = _nested_pair(
        _FixedSugar(Incomplete(halt)),
        outer_exit_probe=outer_exit,
        inner_exit_probe=inner_exit,
    )
    out = sugar.desugar()
    assert inner_exit == [], "B was never entered; B.__exit__ must not run"
    assert outer_exit == [1], "A was entered; A.__exit__ must run on B's enter halt"
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert any(r.effect == halt for r in reds), "the enter halt must be preserved"


def test_discrimination_first_exit_is_not_skipped_on_the_halted_edge():
    """BITE: approximating ``__exit__`` as completion-only would leave A's exit
    unran. Assert the wrong expectation and show it fails."""
    outer_exit, inner_exit = [], []
    sugar = _nested_pair(
        _FixedSugar(Incomplete(RaiseEffect(exception_name="OSError"))),
        outer_exit_probe=outer_exit,
        inner_exit_probe=inner_exit,
    )
    sugar.desugar()
    with pytest.raises(AssertionError):
        assert outer_exit == [], "normal-path-only exit would leave this empty"


def test_body_completion_still_runs_both_exits():
    """LAW: the completed edge runs both exits too (inner then outer)."""
    outer_exit, inner_exit = [], []
    sugar = _nested_pair(
        _FixedSugar(Complete(_FloorValue("entered"))),
        outer_exit_probe=outer_exit,
        inner_exit_probe=inner_exit,
    )
    sugar.desugar()
    assert inner_exit == [1]
    assert outer_exit == [1]


def test_discrimination_completion_path_does_not_skip_the_inner_exit():
    outer_exit, inner_exit = [], []
    sugar = _nested_pair(
        _FixedSugar(Complete(_FloorValue("entered"))),
        outer_exit_probe=outer_exit,
        inner_exit_probe=inner_exit,
    )
    sugar.desugar()
    with pytest.raises(AssertionError):
        assert inner_exit == []


def test_body_halt_inside_nested_managers_runs_both_exits():
    """LAW: a halting BODY still exits B then A; the halt is preserved under
    NeverSuppresses."""
    outer_exit, inner_exit = [], []
    halt = RaiseEffect(exception_name="ValueError", occurrence="body.py:2:4")
    inner = _resource(
        body=(_FixedSugar(Incomplete(halt)),), slot="B", exit_probe=inner_exit
    )
    sugar = _resource(body=(inner,), slot="A", exit_probe=outer_exit)
    out = sugar.desugar()
    assert inner_exit == [1]
    assert outer_exit == [1]
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert any(r.effect == halt for r in reds)


def test_discrimination_body_halt_is_not_suppressed_by_never_suppresses():
    outer_exit, inner_exit = [], []
    halt = RaiseEffect(exception_name="ValueError", occurrence="body.py:2:4")
    inner = _resource(
        body=(_FixedSugar(Incomplete(halt)),), slot="B", exit_probe=inner_exit
    )
    out = _resource(body=(inner,), slot="A", exit_probe=outer_exit).desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    with pytest.raises(AssertionError):
        assert reds == [], "NeverSuppresses must not consume the body halt"


assert BlockValue is not None  # imported for the block-shape contract above
