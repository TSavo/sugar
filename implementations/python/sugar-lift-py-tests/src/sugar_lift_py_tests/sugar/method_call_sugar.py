from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MethodCallSugar(Sugar, role=SugarRole.TERM):
    """A method call `recv.method(<args>)` / `recv.method(<args>, k=v)`.

    Composes on the AttributeSugar coordinate family: the term is
    `call:<method>(receiver, *positional, *keyword_values)` -- receiver first,
    then positional args, then keyword VALUES in source order. Keyword names
    ride in `parameters` (not dropped). Disjoint from CallSugar (plain-name,
    no receiver) and OsSugar (`os.exit`). ``**kwargs`` / ``*args`` ride coordinates. Body dig via install_source_dig when receiver class resolves.
    """

    method_name: str
    receiver: SugarBody
    args: tuple[SugarBody, ...]
    # Keyword names in source order for the trailing keyword value slots of
    # `args` (empty when the call is positional-only).
    keyword_names: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # Method Call with a receiver Attribute func. OsSugar keeps os.exit.
        # Keywords are owned (values ride the coordinate). **kwargs expansion
        # stays unowned so it panics loud at recognition, not dropped.
        return (
            site.observed == "Call"
            and site.call_receiver() is not None
            and site.call_qualified_target_name() != "os.exit"
            # *args / **kwargs ride as coordinates (StarredSugar / ** param)
        )

    @classmethod
    def new(cls, site, ctx) -> "MethodCallSugar":
        # Receiver, positional args, and keyword VALUES are factory-built
        # (audited), never reduced here.
        positional = tuple(
            ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()
        )
        keyword_names: list[str] = []
        keyword_bodies: list[SugarBody] = []
        for kw in site.call_keywords():
            name = kw.keyword_arg_name()
            # **kwargs expansion: parameter name is "**" (not dropped).
            keyword_names.append(name if name is not None else "**")
            keyword_bodies.append(
                ctx.build_body(kw.keyword_value(), SugarRole.TERM)
            )
        return cls(
            method_name=site.call_target_name(),
            receiver=ctx.build_body(site.call_receiver(), SugarRole.TERM),
            args=(*positional, *keyword_bodies),
            keyword_names=tuple(keyword_names),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Keyword method call on the return-adjacent face: groupby(level=3)
        # so the keyword value rides the coordinate; the pair discriminates
        # on the enclosing return face (coordinates stay symbolic).
        prefix = (
            "def A(z):\n"
            "    y = z.groupby(level=3)\n"
            "    return 1\n"
            "\n"
        )
        return _call_pair(
            name="method_call_return",
            owner_sugar="MethodCallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce receiver, then each arg (positional then keyword values);
        # the result is the method coordinate.
        return self.receiver.reduce(ctx).and_then(
            lambda recv: self._collect(self.args, (recv,), ctx)
        )

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if not remaining:
            from sugar_lift_py_tests.floor import CallSiteValue
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.sugar.install_source_dig import (
                build_dig_body,
                bind_positional_defaults,
                resolve_method_funcdef,
            )

            # Method body dig: receiver is accumulated[0]. Resolve class.method
            # from name_resolver / from_imports / install-source. body=None is
            # still lawful coordinate-only when resolve fails.
            receiver_floor = accumulated[0] if accumulated else None
            fn = resolve_method_funcdef(self.method_name, receiver_floor, ctx)
            body = (
                build_dig_body(fn, ctx, require_attachable=True)
                if fn is not None
                else None
            )
            if body is None:
                return Complete(CallSiteValue(
                    target_name=self.method_name,
                    arg_values=accumulated,
                    parameters=self.keyword_names,
                    term=ctor(
                        f"call:{self.method_name}",
                        [
                            value.to_term(owner=str(self.site))
                            for value in accumulated
                        ],
                    ),
                    body=body,
                    site=self.site,
                ))

            source_term = ctor(
                f"call:{self.method_name}",
                [value.to_term(owner=str(self.site)) for value in accumulated],
            )
            return bind_positional_defaults(fn, accumulated, ctx).and_then(
                lambda binding: Complete(
                    CallSiteValue(
                        target_name=self.method_name,
                        arg_values=binding[1],
                        parameters=binding[0],
                        term=source_term,
                        body=body,
                        site=self.site,
                    )
                )
            )
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda value: self._collect(tuple(rest), (*accumulated, value), ctx)
        )

    def walk_children(self):
        return (self.receiver, *self.args)
