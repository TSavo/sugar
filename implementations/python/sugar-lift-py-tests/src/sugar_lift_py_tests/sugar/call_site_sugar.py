from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class CallSiteSugar(Sugar):
    """`<name>(<args>)` -> a call-site coordinate: THE DIG CUE.

    Reduce each argument, then stand as a CallSiteValue whose term is the bridge
    coordinate `call:<name>(<arg terms>)`. That coordinate is the cue: an assert
    that consumes it carries it into the InvValue's operand_callsites, which
    projects the callEdge -- and a cue is the signal that this call warrants a
    dig (reduce the callee into its universe; its call sites cue further digs).

    The dig itself is NOT done here (`body=None`). Digging is cued, not eager:
    an assertion cues digs, and digs cue digs, so the recursion is driven by the
    cueing mechanism (the enumeration), not by inlining the callee at every call.

    Meaning-only, node-constructed. Plain positional calls to a named callee;
    method/attribute/computed callees and keyword args stay gaps (the tree node
    guards them).
    """

    target_name: str
    args: tuple  # the argument sugars, in source order
    site: object = dataclass_field(compare=False)
    keywords: tuple = ()  # (name, sugar) pairs, in source order

    @classmethod
    def witnesses(cls):
        # A user callee's returned value is asserted through the call site: the
        # truthful twin asserts the dug value, the lying twin another -- the pair
        # proves the lift discriminates on what the call computes.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="call_site_return",
            owner_sugar="CallSiteSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self._collect(self.args, (), ctx)

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.desugar(ctx).and_then(
                lambda value: self._collect(
                    tuple(rest), accumulated + (value,), ctx
                )
            )
        return self._collect_kwargs(self.keywords, (), accumulated, ctx)

    def _collect_kwargs(
        self, remaining: tuple, kw_values: tuple, positional: tuple, ctx: object
    ) -> Outcome:
        if remaining:
            (name, sugar), *rest = remaining
            return sugar.desugar(ctx).and_then(
                lambda value: self._collect_kwargs(
                    tuple(rest), kw_values + ((name, value),), positional, ctx
                )
            )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const

        owner = str(self.site)
        kwarg_terms = [
            ctor("py.kwarg", [str_const(name), value.to_term(owner=owner)])
            for name, value in kw_values
        ]
        term = ctor(
            f"call:{self.target_name}",
            [value.to_term(owner=owner) for value in positional] + kwarg_terms,
            # Spelling is never builtin authority.  An authenticated builtin
            # recognizer may refine its own coordinate later; a plain Name
            # call (including a shadowed ``len``/``sum`` twin) stays generic.
            symbol_kind="coordinate",
        )
        return Complete(
            CallSiteValue(
                target_name=self.target_name,
                arg_values=positional + tuple(value for _, value in kw_values),
                parameters=(),
                term=term,
                body=None,  # the dig is CUED, not inlined here
                site=self.site,
            )
        )
