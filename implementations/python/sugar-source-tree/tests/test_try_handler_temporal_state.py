"""Law twins for the temporal state a ``try`` handler begins from (#6283).

#6242 proved ``Try`` rides the shared ``ExitSet`` algebra and contributes no
sequencing of its own.  It deliberately left ONE thing unpinned, because
pinning it would have asserted a defect: ``Try.substitute`` built the handler's
scope as ``dict(scope)`` -- the **pre-try** snapshot -- so a binding the body
established before the raise was invisible in the handler and the lift
fabricated a ``NameErrorEffect`` for a name Python guarantees is bound.

The law, one layer up from #6239's ``_prefixed`` and in the same shape:

    Each halted edge carries the temporal binding state at its precise halt
    occurrence; the selected handler begins from that edge's state.

So the repair CONSUMES what the block threading already computes, per
occurrence -- ``_substitute_body_tracked(..., edge_states=...)`` reports the
state in effect as each statement begins, ``_body_halt_edges`` turns the
statements that can halt into edges carrying that state, ``_route_halt_edges``
sends each edge to the arm that receives it (source order, first match; an
untyped occurrence reaches every arm), and ``_incoming_halt_state`` is what the
edges reaching ONE arm agree on.

It is explicitly NOT ``{**scope, **body_net}``.  That repairs the first twin
and over-claims on every body that can halt before an assignment; twins two,
three and eight exist to catch exactly that.

Each twin carries a discrimination arm: the production rule is perturbed to
the defective one, the observation is shown to flip, and the perturbation is
reverted.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path

from sugar_source_tree.nodes import Try
from with_resolution_fixture import source_file_with_preconstruction

CLASSES = (
    "class RootFault(Exception):\n"
    "    pass\n"
    "class LeafFault(RootFault):\n"
    "    pass\n"
)


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\nimport tm\n" + src)
        path = f.name
    return next(source_file_with_preconstruction(Path(path)).functions())


def _out(src: str):
    return _fn(src).sugar().desugar()


def _incompletes(src: str):
    """The Incomplete effects the whole function carries, outer or recorded."""
    from sugar_lift_py_tests.outcome import Incomplete

    out = _out(src)
    if isinstance(out, Incomplete):
        return [out]
    return [e for e in out.value.record.contribution() if isinstance(e, Incomplete)]


def _post(src: str):
    return _out(src).value.post()


def _missing_names(src: str):
    return sorted(
        name
        for name in (
            getattr(e.effect, "name", None)
            for e in _incompletes(src)
            if type(e.effect).__name__ == "NameErrorEffect"
        )
        if name
    )


@contextmanager
def _observed():
    """Record every halt-edge routing decision the production path makes."""
    log: dict = {"edges": [], "routed": [], "incoming": []}
    route, incoming, edges = (
        Try._route_halt_edges,
        Try._incoming_halt_state,
        Try._body_halt_edges,
    )

    def spy_edges(self, edge_states, scope):
        result = edges(self, edge_states, scope)
        log["edges"].append(result)
        return result

    def spy_route(self, halt_edges):
        result = route(self, halt_edges)
        log["routed"].append(result)
        return result

    def spy_incoming(self, states):
        result = incoming(self, states)
        log["incoming"].append((states, result))
        return result

    Try._body_halt_edges = spy_edges
    Try._route_halt_edges = spy_route
    Try._incoming_halt_state = spy_incoming
    try:
        yield log
    finally:
        Try._body_halt_edges = edges
        Try._route_halt_edges = route
        Try._incoming_halt_state = incoming


@contextmanager
def _rewritten():
    """Capture the rewritten ``Try`` nodes the substitution produces."""
    log: list = []
    original = Try.substitute

    def spy(self, scope):
        result = original(self, scope)
        log.append(result)
        return result

    Try.substitute = spy
    try:
        yield log
    finally:
        Try.substitute = original


def _unresolved_reads(src: str):
    """The names each rewritten handler arm reads WITHOUT a routed binding.

    A name the arm's routed edge carried is substituted away; a name it did
    not carry survives as a ``GuardedBindingRead`` -- the honest unresolved
    read that becomes a NameError. This is how the twins show the routed state
    is CONSUMED, not merely computed.
    """
    from sugar_source_tree.nodes import GuardedBindingRead

    with _rewritten() as log:
        _fn(src).sugar()
    node = log[0]
    node = node.statements[0] if hasattr(node, "statements") else node
    return [
        sorted({n.name for n in handler.walk() if isinstance(n, GuardedBindingRead)})
        for handler in node.handlers
    ]


@contextmanager
def _rule(replacement):
    """Perturb the incoming-state rule; revert on exit."""
    original = Try._incoming_halt_state
    Try._incoming_halt_state = replacement
    try:
        yield
    finally:
        Try._incoming_halt_state = original


def _pre_try_snapshot(self, states):
    """The #6283 defect: the handler begins from the pre-try scope."""
    return {}


def _static_union(self, states):
    """The over-claim T ruled out: every binding the body could have made."""
    merged: dict = {}
    for state in states or ():
        merged.update(state)
    return merged


# ---------------------------------------------------------------------------
# 1. assignment before an explicit raise IS available in the handler
# ---------------------------------------------------------------------------

BOUND_THEN_RAISE = (
    "def A(z):\n"
    "    try:\n"
    "        x = z\n"
    "        raise ValueError\n"
    "    except ValueError:\n"
    "        return x\n"
)


def test_binding_before_an_explicit_raise_is_available_in_the_handler():
    """``x = z`` cannot fail, so the only halt is the raise -- which carries x."""
    assert _incompletes(BOUND_THEN_RAISE) == []
    assert _post(BOUND_THEN_RAISE).args[1].name == "z"

    # BITE: hand the handler the pre-try snapshot and the fabrication returns.
    with _rule(_pre_try_snapshot):
        assert _missing_names(BOUND_THEN_RAISE) == ["x"]


# ---------------------------------------------------------------------------
# 2. a halt BEFORE the assignment leaves the name unavailable
# ---------------------------------------------------------------------------

HALT_THEN_BIND = (
    "def A(z):\n"
    "    try:\n"
    "        tm.step()\n"
    "        x = z\n"
    "        raise ValueError\n"
    "    except ValueError:\n"
    "        return x\n"
)


def test_a_halt_before_the_assignment_leaves_the_name_unavailable():
    """``tm.step()`` may halt first; on THAT edge x was never bound.

    Never fabricate a binding: the handler must not see x.
    """
    assert _missing_names(HALT_THEN_BIND) == ["x"]
    with _observed() as log:
        _fn(HALT_THEN_BIND).sugar()
    assert [sorted(net) for _i, _m, net in log["edges"][0]] == [[], ["x"]]

    # BITE: the {**scope, **body_net} over-claim invents x on the opaque edge.
    with _rule(_static_union):
        assert _missing_names(HALT_THEN_BIND) == []


# ---------------------------------------------------------------------------
# 3. two possible halt sites preserve DIFFERENT prefix states
# ---------------------------------------------------------------------------

TWO_HALT_SITES = (
    "def A(z, flag):\n"
    "    try:\n"
    "        a = z\n"
    "        if flag:\n"
    "            raise ValueError\n"
    "        b = z\n"
    "        raise ValueError\n"
    "    except ValueError:\n"
    "        c = a\n"
    "        return b\n"
)


def test_two_halt_sites_preserve_different_prefix_states():
    """Edge one carries {a}; edge two carries {a, b}.  They are not merged
    into one state, and the arm both reach may only rely on their agreement --
    so ``b`` is unavailable while ``a`` would not be."""
    with _observed() as log:
        _fn(TWO_HALT_SITES).sugar()
    assert [sorted(net) for _i, _m, net in log["edges"][0]] == [["a"], ["a", "b"]]
    states, incoming = log["incoming"][0]
    assert [sorted(s) for s in states] == [["a"], ["a", "b"]]
    assert sorted(incoming) == ["a"]
    # CONSUMED: ``a`` (carried by BOTH edges) resolves; only ``b`` is left as
    # an unresolved read -- the honest NameError asserted next.
    assert _unresolved_reads(TWO_HALT_SITES) == [["b"]]
    assert _missing_names(TWO_HALT_SITES) == ["b"]

    # BITE: union the two prefixes and b is fabricated onto the early edge.
    # Read structurally, not end-to-end: with b fabricated both arms complete,
    # and two completed edges reaching ``ExitSet.normalize`` trip a PRE-EXISTING
    # IR gap (``term_to_value`` cannot encode the ``effect_slot_kind`` atomic
    # that ``EffectBinding.to_facts`` puts in a term position).  That gap is on
    # main, independent of this repair, and is left loud rather than papered
    # over here.
    with _rule(_static_union):
        with _observed() as poisoned:
            _fn(TWO_HALT_SITES).sugar()
        assert [sorted(r) for _s, r in poisoned["incoming"]] == [["a", "b"]]


# ---------------------------------------------------------------------------
# 4. matched ``as e`` EXTENDS -- not replaces -- the incoming state
# ---------------------------------------------------------------------------

AS_BINDING = (
    "def A(z):\n"
    "    try:\n"
    "        x = z\n"
    "        raise ValueError\n"
    "    except ValueError as error:\n"
    "        return x\n"
)

AS_BINDING_SLOT = (
    "def A(z):\n"
    "    try:\n"
    "        x = z\n"
    "        raise ValueError\n"
    "    except ValueError as error:\n"
    "        return error\n"
)


def test_matched_as_binding_extends_the_incoming_state():
    """The exception slot is added to the routed state, not substituted for it:
    x still resolves, and ``error`` is still the routed effect slot."""
    assert _incompletes(AS_BINDING) == []
    assert _post(AS_BINDING).args[1].name == "z"
    assert _post(AS_BINDING_SLOT).args[1].name == "python:effect_slot"

    # BITE: replace the incoming state instead of extending it -- x is lost
    # while the slot survives, which is exactly the asymmetry being pinned.
    with _rule(_pre_try_snapshot):
        assert _missing_names(AS_BINDING) == ["x"]
        assert _post(AS_BINDING_SLOT).args[1].name == "python:effect_slot"


# ---------------------------------------------------------------------------
# 5. an UNMATCHED halt preserves its exact state and effect occurrence
# ---------------------------------------------------------------------------

UNMATCHED = (
    CLASSES + "def A(z):\n"
    "    try:\n"
    "        x = z\n"
    "        raise RootFault\n"
    "    except LeafFault:\n"
    "        return x\n"
)


def test_unmatched_halt_preserves_its_exact_state_and_occurrence():
    """A base-class raise does not match a leaf arm.  The edge is not routed,
    not absorbed, and not reconstructed -- the same RootFault occurrence leaves
    the try, and the leaf arm receives no edge at all."""
    from sugar_lift_py_tests.outcome import Incomplete

    out = _out(UNMATCHED)
    assert isinstance(out, Incomplete)
    assert type(out.effect).__name__ == "RaiseEffect"
    assert out.effect.exception_name == "RootFault"

    with _observed() as log:
        _fn(UNMATCHED).sugar()
    assert log["routed"][0] == {}, "an unmatched edge routes to no arm"

    # BITE: route the unmatched edge anyway and the arm absorbs the halt.
    original = Try._route_halt_edges
    Try._route_halt_edges = lambda self, edges: {
        index: [state for _i, _m, state in edges] for index in range(len(self.handlers))
    }
    try:
        absorbed = _out(UNMATCHED)
        assert not isinstance(absorbed, Incomplete) or absorbed.effect is not out.effect
    finally:
        Try._route_halt_edges = original


# ---------------------------------------------------------------------------
# 6. handler failure carries the HANDLER's updated state
# ---------------------------------------------------------------------------

HANDLER_UPDATES = (
    "def A(z):\n"
    "    try:\n"
    "        x = z\n"
    "        raise ValueError\n"
    "    except ValueError:\n"
    "        y = x\n"
    "    return y\n"
)


def test_handler_edge_carries_the_handlers_own_updated_state():
    """The handler starts from its routed edge and then threads its own body;
    what leaves the try on that edge is the edge's state UPDATED by the
    handler, so ``y`` -- bound from ``x`` inside the arm -- is available after."""
    assert _incompletes(HANDLER_UPDATES) == []
    assert _post(HANDLER_UPDATES).args[1].name == "z"

    # BITE: start the handler from the pre-try snapshot and its own binding is
    # built from a fabricated NameError instead of the routed state.
    with _rule(_pre_try_snapshot):
        assert _missing_names(HANDLER_UPDATES) == ["x"]


# ---------------------------------------------------------------------------
# 7. body COMPLETION alone feeds ``else``
# ---------------------------------------------------------------------------

ELSE_BODY = (
    "def A(z):\n"
    "    try:\n"
    "        x = z\n"
    "    except ValueError:\n"
    "        return 0\n"
    "    else:\n"
    "        return x\n"
)


def test_body_completion_alone_feeds_else():
    """``else`` is the completed edge -- it reads the body's completion state,
    never a halted edge's, and the handler-routing repair does not touch it."""
    assert _incompletes(ELSE_BODY) == []
    assert _post(ELSE_BODY).args[1].name == "z"
    with _observed() as log:
        _fn(ELSE_BODY).sugar()
    assert log["edges"][0] == [], "an all-safe body contributes no halted edge"

    # BITE: withhold the body's completion net and ``else`` loses the binding.
    original = Try._substitute_body_tracked

    def starved(self, statements, scope, *, edge_states=None):
        items, changed, net = original(self, statements, scope, edge_states=edge_states)
        if edge_states is not None:
            return items, changed, {}
        return items, changed, net

    Try._substitute_body_tracked = starved
    try:
        assert _missing_names(ELSE_BODY) == ["x"]
    finally:
        Try._substitute_body_tracked = original


# ---------------------------------------------------------------------------
# 8. NO static union of all body bindings is handed to every handler
# ---------------------------------------------------------------------------

TWO_ARMS = (
    CLASSES + "def A(z, flag):\n"
    "    try:\n"
    "        a = z\n"
    "        if flag:\n"
    "            raise LeafFault\n"
    "        b = z\n"
    "        raise RootFault\n"
    "    except LeafFault:\n"
    "        return a\n"
    "    except RootFault:\n"
    "        return b\n"
)


def test_no_static_union_of_body_bindings_reaches_every_handler():
    """Each arm receives ONLY the edges routed to it: the leaf arm gets the
    early raise ({a}), the base arm gets the late one ({a, b}).  A union would
    have handed both arms {a, b}."""
    with _observed() as log:
        _fn(TWO_ARMS).sugar()
    routed = log["routed"][0]
    assert {k: [sorted(s) for s in v] for k, v in routed.items()} == {
        0: [["a"]],
        1: [["a", "b"]],
    }
    incoming = [sorted(result) for _states, result in log["incoming"]]
    assert incoming == [["a"], ["a", "b"]]
    assert incoming[0] != ["a", "b"], "the leaf arm is not handed the union"
    # CONSUMED per arm: the leaf arm resolved ``a``; the base arm resolved both.
    assert _unresolved_reads(TWO_ARMS) == [[], []]

    # BITE: union every edge into every arm and the leaf arm over-claims b.
    with _rule(_static_union):
        with _observed() as poisoned:
            _fn(TWO_ARMS).sugar()
        assert [sorted(r) for _s, r in poisoned["incoming"]] == [["a"], ["a", "b"]]
    # (with a single arm the union is visible directly)
    with _rule(_static_union):
        with _observed() as poisoned:
            _fn(TWO_HALT_SITES).sugar()
        assert [sorted(r) for _s, r in poisoned["incoming"]] == [["a", "b"]]


# ---------------------------------------------------------------------------
# 9. NO name map and NO reconstructed sugar
# ---------------------------------------------------------------------------


def test_routed_state_is_the_threaded_entry_not_a_name_map():
    """What reaches the handler is the very entry the body threaded -- the same
    object, carried along the edge.  Nothing is looked up by name, rebuilt, or
    re-substituted from source."""
    with _observed() as log:
        _fn(BOUND_THEN_RAISE).sugar()
    edges = log["edges"][0]
    assert len(edges) == 1
    _identity, _mro, edge_state = edges[0]
    _states, incoming = log["incoming"][0]
    assert set(incoming) == {"x"}
    assert incoming["x"] is edge_state["x"], "the routed entry is carried, not rebuilt"
    # And it is CONSUMED: the arm has no unresolved read of x at all.
    assert _unresolved_reads(BOUND_THEN_RAISE) == [[]]

    # BITE: rebuild the same names into fresh entries -- the identity fails
    # even though every name and value still matches.
    original = Try._incoming_halt_state

    def rebuilt(self, states):
        from copy import copy

        return {name: copy(entry) for name, entry in original(self, states).items()}

    Try._incoming_halt_state = rebuilt
    try:
        with _observed() as log2:
            _fn(BOUND_THEN_RAISE).sugar()
        _identity, _mro, edge_state2 = log2["edges"][0][0]
        _states2, incoming2 = log2["incoming"][0]
        assert incoming2["x"] is not edge_state2["x"]
    finally:
        Try._incoming_halt_state = original
