'''Construction is memoized at the construction COORDINATE, not per DAG path.

Substitution SHARES node objects (a bound name substitutes to the bound node
itself), so the constructed graph is a DAG while ``walk``/``_construct_sugar``
traverse it as a tree. Without a memo a shared site re-constructs -- and
re-answers the roll -- once per incoming PATH (measured 433x on one pandas
function). ``Node.sugar`` therefore memoizes at ``(ref, reporter,
control_context)`` -- the SAME coordinate the field row already uses.

These twins pin what the coordinate must NOT merge and what it must NOT lose:

  * a rewritten SHADOW carries a different ref, so it never collides with the
    node it replaced (both directions checked);
  * the same ref under two different ``ControlConstructionContextV1`` stays two
    constructions (both faces: two loop targets, and loop vs no loop);
  * a transient shadow's address is never recycled under a live memo row --
    the #6212 id-reuse bug class;
  * a gap stays a gap on EVERY call: the panic is remembered and re-raised,
    never swallowed, never softened into a value;
  * and the point of it all: each coordinate constructs exactly once.
'''
import gc
import os
import tempfile

from sugar_source_tree.backend import materialize
from sugar_source_tree.nodes import ControlConstructionContextV1, Node
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.shadow import rewrite
from sugar_source_tree.tree import SourceFile


def _node_classes():
    from sugar_source_tree.nodes import KIND_REGISTRY

    return [cls for cls in KIND_REGISTRY.values() if issubclass(cls, Node)]


def _function(src, name=None):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.py")
    with open(p, "w") as fh:
        fh.write(src)
    reporter = CollectingReporter()
    sf = SourceFile.from_path(p, reporter=reporter)
    for fn in sf.functions():
        if name is None or getattr(fn, "name", None) == name:
            return fn, reporter
    raise AssertionError(f"no function {name!r} in fixture")


def test_rewritten_shadow_does_not_collide_with_the_node_it_replaced():
    # The origin constructs FIRST, filling its memo row. Then a shadow rewrite
    # of that same origin -- same kind, same span, DIFFERENT ref -- must
    # construct its OWN sugar. If the memo were keyed by anything the two
    # share (span, kind, the transient shell) the shadow would be served the
    # origin's `x + 1`.
    fn, _ = _function("def f(x):\n    a = x + 1\n    b = x + 2\n    return (a, b)\n")
    one, two = [n for n in fn.walk() if n.kind == "BinOp"]
    origin_sugar = one.sugar()
    assert origin_sugar.right.value == 1, origin_sugar

    shadow = rewrite(one, right=two.right)
    shadow_sugar = shadow.sugar()
    assert shadow_sugar.right.value == 2, shadow_sugar
    assert shadow_sugar != origin_sugar

    # ...and the other direction: the origin is NOT overwritten by its shadow.
    assert one.sugar().right.value == 1
    assert one.sugar() == origin_sugar


def test_shadow_constructed_first_does_not_poison_its_origin():
    # Same twin with the order reversed, so neither arm can pass by accident
    # of "whoever ran first wins".
    fn, _ = _function("def f(x):\n    a = x + 1\n    b = x + 2\n    return (a, b)\n")
    one, two = [n for n in fn.walk() if n.kind == "BinOp"]
    shadow = rewrite(one, right=two.right)
    assert shadow.sugar().right.value == 2
    assert one.sugar().right.value == 1


def test_distinct_control_contexts_construct_separately():
    # ONE `continue` ref, TWO loop targets. The construction depends on the
    # control context, so merging the contexts would wire the statement to the
    # wrong loop -- silently.
    fn, _ = _function(
        "def f(xs, ys):\n"
        "    for a in xs:\n"
        "        continue\n"
        "    for b in ys:\n"
        "        pass\n"
        "    return 0\n"
    )
    first, second = [n for n in fn.walk() if n.kind == "For"]
    cont = [n for n in fn.walk() if n.kind == "Continue"][0]
    assert first.owned_loop_target != second.owned_loop_target

    made = []
    for target in (first.owned_loop_target, second.owned_loop_target):
        ctx = ControlConstructionContextV1().enter_loop(target)
        node = materialize(cont.unit, cont.ref, cont.reporter, ctx)
        made.append(node.sugar())
    assert made[0].target_cid != made[1].target_cid, made
    # Re-asking the FIRST context still answers the first target: the second
    # construction did not overwrite the first coordinate's row.
    ctx = ControlConstructionContextV1().enter_loop(first.owned_loop_target)
    again = materialize(cont.unit, cont.ref, cont.reporter, ctx).sugar()
    assert again.target_cid == made[0].target_cid


def test_control_context_discrimination_no_loop_still_refuses():
    # The other face: the same `continue` ref with NO enclosing loop has no
    # target to wire, and must keep refusing even after the in-loop coordinate
    # constructed successfully. A memo that dropped the context would hand the
    # unwired occurrence the in-loop answer.
    from sugar_lift_py_tests.loop_construction import LoopWireError

    fn, _ = _function("def f(xs):\n    for a in xs:\n        continue\n    return 0\n")
    loop = [n for n in fn.walk() if n.kind == "For"][0]
    cont = [n for n in fn.walk() if n.kind == "Continue"][0]

    in_loop = materialize(
        cont.unit,
        cont.ref,
        cont.reporter,
        ControlConstructionContextV1().enter_loop(loop.owned_loop_target),
    )
    assert in_loop.sugar().action == "continue"

    unwired = materialize(
        cont.unit, cont.ref, cont.reporter, ControlConstructionContextV1()
    )
    raised = False
    try:
        unwired.sugar()
    except LoopWireError:
        raised = True
    assert raised, "an unwired `continue` must refuse, memo or no memo"


def test_indistinguishable_shadows_never_share_a_construction_coordinate():
    # The luck-free half of the #6212 bug class: TWO shadows that are alike in
    # every observable way -- same kind, same span, structurally equal slots --
    # are still two constructions, because they are two refs. If the coordinate
    # ever collapsed them, one would be served the other's row; if a dead one's
    # address were recycled, a live one would be served a corpse's row. Neither
    # is possible while each keyed ref is pinned for its row's lifetime.
    fn, _ = _function("def f(x):\n    a = x + 1\n    b = x + 1\n    return (a, b)\n")
    one, two = [n for n in fn.walk() if n.kind == "BinOp"]
    left = rewrite(one, right=two.right)
    right = rewrite(one, right=two.right)
    assert left.ref is not right.ref
    assert left.span == right.span and left.kind == right.kind

    cache = left._construction_cache()
    left_key = cache.key(left.ref, left.reporter, left.control_context)
    right_key = cache.key(right.ref, right.reporter, right.control_context)
    assert left_key != right_key, "two distinct shadow refs shared one coordinate"
    assert cache._pinned[left_key] is left.ref
    assert cache._pinned[right_key] is right.ref
    assert left.sugar() == right.sugar()  # equal content, separately constructed


def test_transient_shadow_addresses_are_never_recycled_under_a_live_memo():
    # The #6212 bug class, exercised the way it actually bites: mint a shadow,
    # construct it, drop every reference to it, repeat. The cache key embeds
    # ``id(ref)``, so a recycled address under a live memo row would serve a
    # DEAD shadow's construction. Every constructed value must be its own, and
    # no address may be reused while its row lives.
    parts = ", ".join(f"x + {i}" for i in range(60))
    fn, _ = _function(f"def f(x):\n    return ({parts})\n")
    binops = [n for n in fn.walk() if n.kind == "BinOp"]
    origin = binops[0]

    addresses = []
    for i, other in enumerate(binops):
        shadow = rewrite(origin, right=other.right)
        addresses.append(id(shadow.ref))
        assert shadow.sugar().right.value == i, (i, shadow.sugar())
        del shadow
        gc.collect()

    assert len(set(addresses)) == len(addresses), (
        "a transient shadow ref's address was recycled while its memo row was "
        "live -- the memo would serve a DEAD shadow's construction"
    )
    # And the origin, constructed last, is still its own.
    assert origin.sugar().right.value == 0


def test_gap_stays_a_gap_on_every_call():
    # Memoization must never de-duplicate a panic into silence. A kind with no
    # sugar written throws on the first call AND on every call after it, with
    # the same panic -- the reporter's roll call still fingers the site.
    fn, reporter = _function("def f(x):\n    del x\n    return 0\n")
    gap_node = [n for n in fn.walk() if n.kind == "Delete"][0]

    panics = []
    for _ in range(3):
        try:
            gap_node.sugar()
        except SugarNotWritten as panic:
            panics.append(panic)
    assert len(panics) == 3, "a gap that stops throwing is a swallowed gap"
    assert panics[0] is panics[1] is panics[2]
    assert gap_node.kind in {node.kind for node, _ in reporter.gaps}


def test_each_coordinate_constructs_exactly_once():
    # The capability itself. A bound name substitutes to the bound NODE, so a
    # value used many times is one shared node reached by many paths. Every
    # coordinate must be constructed once regardless of how many paths reach it.
    src = (
        "def f(x):\n"
        "    a = x + 1\n"
        "    b = a * a\n"
        "    c = b + b\n"
        "    d = c * c\n"
        "    e = d + d\n"
        "    return e + e\n"
    )
    fn, _ = _function(src)

    constructed = []
    # Each concrete class writes its OWN _construct_sugar (the absence of an
    # override IS the loud MISSING), so instrument every override, not the base.
    patched = []
    for cls in _node_classes():
        original = cls.__dict__.get("_construct_sugar")
        if original is None:
            continue

        def counting(self, _original=original):
            cache = self._construction_cache()
            constructed.append(
                cache.key(self.ref, self.reporter, self.control_context)
            )
            return _original(self)

        patched.append((cls, original))
        cls._construct_sugar = counting
    try:
        fn.sugar()
    finally:
        for cls, original in patched:
            cls._construct_sugar = original

    assert constructed, "nothing was constructed -- the twin is not exercising"
    assert len(constructed) == len(set(constructed)), (
        "a construction coordinate was entered twice: "
        f"{len(constructed)} constructions for {len(set(constructed))} coordinates"
    )
