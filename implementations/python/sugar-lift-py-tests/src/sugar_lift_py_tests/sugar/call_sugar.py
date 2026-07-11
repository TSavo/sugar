from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.sugar.install_source_dig import (
    module_sibling_function_nodes as _module_sibling_function_nodes,
    resolve_install_source_funcdef as _resolve_install_source_funcdef,
)


@dataclass(frozen=True)
class CallSugar(Sugar, role=SugarRole.TERM):
    """A plain-name call `f(<args>)` / `f(<args>, k=v)`.

    A call is a COORDINATE into the vendor universe: reduce the arguments
    (positional then keyword VALUES in source order), and the result is the
    callsite -- a CallSiteValue whose term IS `call:f(<arg terms>)`. Keyword
    names ride in `parameters` (not dropped). The lift does not derive f
    (dig the universe when body resolves; else coordinate only). Method receivers
    stay MethodCallSugar's; ``**kwargs`` expansion stays a loud gap (unowned).
    Body dig: install_source_dig.resolve_call_funcdef + build_dig_body."""

    target_name: str
    args: tuple[SugarBody, ...]
    # Keyword names in source order for the trailing keyword value slots of
    # `args` (empty when the call is positional-only).
    keyword_names: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # Plain-name calls (positional and/or keyword). os.exit stays OsSugar's
        # (it has a receiver). **kwargs expansion is unowned -- loud gap.
        return (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() is not None
            and not site.call_has_kwargs_expansion()
        )

    @classmethod
    def new(cls, site, ctx) -> "CallSugar":
        # Arguments and keyword VALUES are factory-built (audited), never reduced here.
        positional = tuple(
            ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()
        )
        keyword_names: list[str] = []
        keyword_bodies: list[SugarBody] = []
        for kw in site.call_keywords():
            name = kw.keyword_arg_name()
            # owns() already excluded **kwargs expansion; double-check.
            if name is None:
                raise AssertionError(
                    "CallSugar.new saw **kwargs expansion after owns() filter"
                )
            keyword_names.append(name)
            keyword_bodies.append(
                ctx.build_body(kw.keyword_value(), SugarRole.TERM)
            )
        return cls(
            target_name=site.call_target_name(),
            args=(*positional, *keyword_bodies),
            keyword_names=tuple(keyword_names),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Keyword-call return face: B is reached as B(w=z) so the keyword value
        # rides the call coordinate. Truthful/lying twins discriminate on the
        # enclosing assert face.
        prefix = (
            "def B(w):\n"
            "    return w\n"
            "\n"
            "def A(z):\n"
            "    y = B(w=z)\n"
            "    return y\n"
            "\n"
        )
        return _call_pair(
            name="call_return",
            owner_sugar="CallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce each argument (positional then keyword values), and the
        # result is the callsite coordinate.
        return self._collect(self.args, (), ctx)

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if not remaining:
            from sugar_lift_py_tests.floor import CallSiteValue
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.sugar.install_source_dig import (
                build_dig_body,
                dig_parameters_for_body,
                resolve_call_funcdef,
            )

            # Install-source / same-module body dig: attach factory-built body
            # when resolve succeeds. body=None remains lawful coordinate-only.
            fn = resolve_call_funcdef(self.target_name, ctx)
            body = build_dig_body(fn, ctx) if fn is not None else None
            parameters = dig_parameters_for_body(
                fn, len(accumulated), self.keyword_names
            )
            if body is None:
                # Fall back to keyword names when no dig body (prior behavior).
                parameters = self.keyword_names

            return Complete(
                CallSiteValue(
                    target_name=self.target_name,
                    arg_values=accumulated,
                    parameters=parameters,
                    term=ctor(
                        f"call:{self.target_name}",
                        [value.to_term(owner=str(self.site)) for value in accumulated],
                    ),
                    body=body,
                    site=self.site,
                )
            )
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda value: self._collect(tuple(rest), (*accumulated, value), ctx)
        )

    def walk_children(self):
        return self.args
