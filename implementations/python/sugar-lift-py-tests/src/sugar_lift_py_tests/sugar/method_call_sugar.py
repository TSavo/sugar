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
    import_target: str | None
    receiver: SugarBody
    args: tuple[SugarBody, ...]
    # Keyword names in source order for the trailing keyword value slots of
    # `args` (empty when the call is positional-only).
    keyword_names: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # Method Call with a receiver Attribute func. OsSugar keeps os.exit.
        # KeywordCallSugar owns every keyword-bearing call shape.
        return (
            site.observed == "Call"
            and site.call_receiver() is not None
            and site.call_qualified_target_name() != "os.exit"
            and not site.call_has_keywords()
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
            keyword_bodies.append(ctx.build_body(kw.keyword_value(), SugarRole.TERM))
        return cls(
            method_name=site.call_target_name(),
            import_target=site.call_import_target_name(
                ctx.import_aliases, ctx.from_imports
            ),
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
        prefix = "def A(z):\n" "    y = z.groupby(level=3)\n" "    return 1\n" "\n"
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
            lambda recv: self._collect_value(self.args, (), recv, ctx)
        )

    def _collect_value(
        self, remaining: tuple, accumulated: tuple, value, ctx: object
    ) -> Outcome:
        from sugar_lift_py_tests.floor import GuardedValue
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Incomplete

        if isinstance(value, GuardedValue):
            true_outcome = self._collect_value(
                remaining, accumulated, value.when_true, ctx
            )
            if isinstance(true_outcome, Incomplete):
                return true_outcome.guarded(value.guard)
            false_outcome = self._collect_value(
                remaining, accumulated, value.when_false, ctx
            )
            if isinstance(false_outcome, Incomplete):
                return false_outcome.guarded(not_(value.guard))
            return Complete(
                GuardedValue(
                    value.guard, true_outcome.value, false_outcome.value
                )
            )
        return self._collect(remaining, (*accumulated, value), ctx)

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if not remaining:
            from sugar_lift_py_tests.floor import CallSiteValue, ObjectValue
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.sugar.install_source_dig import (
                build_dig_body,
                bind_positional_defaults,
                resolve_method_funcdef,
            )

            source_values = accumulated[1:] if self.import_target else accumulated
            source_name = self.import_target or self.method_name
            receiver_floor = accumulated[0] if accumulated else None
            if (
                self.import_target == "operator.index"
                and source_values
                and isinstance(source_values[0], ObjectValue)
            ):
                return source_values[0].call_method_value(
                    "__index__", (), owner=type(self).__name__,
                    blame=str(self.site), ctx=ctx,
                )
            numpy_value = _numpy_literal_call(source_name, source_values)
            if numpy_value is not None:
                return Complete(numpy_value)

            # Method body dig: receiver is accumulated[0]. Resolve class.method
            # from name_resolver / from_imports / install-source. body=None is
            # still lawful coordinate-only when resolve fails.
            fn = resolve_method_funcdef(self.method_name, receiver_floor, ctx)
            body = (
                build_dig_body(fn, ctx, require_attachable=True)
                if fn is not None
                else None
            )
            if body is None:
                return Complete(
                    CallSiteValue(
                        target_name=source_name,
                        arg_values=source_values,
                        parameters=self.keyword_names,
                        term=ctor(
                            f"call:{source_name}",
                            [
                                value.to_term(owner=str(self.site))
                                for value in source_values
                            ],
                        ),
                        body=body,
                        site=self.site,
                    )
                )

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
            lambda value: self._collect_value(
                tuple(rest), accumulated, value, ctx
            )
        )

    def walk_children(self):
        return (self.receiver, *self.args)


_NUMPY_INTEGER_UFUNCS = frozenset(
    {
        "numpy.add",
        "numpy.floor_divide",
        "numpy.maximum",
        "numpy.minimum",
        "numpy.mod",
        "numpy.multiply",
        "numpy.power",
        "numpy.subtract",
    }
)
_NUMPY_INT64_MIN = -(2**63)
_NUMPY_INT64_MAX = 2**63 - 1


def _numpy_literal_call(callee: str, values: tuple):
    if callee not in (*_NUMPY_INTEGER_UFUNCS, "numpy.divide") or len(values) != 2:
        return None
    from sugar_lift_py_tests.floor import OpaqueOpCallsite, TermValue

    left, right = values
    if type(left) is not TermValue or type(right) is not TermValue:
        return None
    if type(left.value) not in (int, float) or type(right.value) not in (int, float):
        return None

    result = _numpy_literal_result(callee, left.value, right.value)
    if result is None:
        return None
    return OpaqueOpCallsite(
        callee=callee,
        arg=left,
        extra_args=(right,),
        computed=TermValue(result),
    )


def _numpy_literal_result(callee: str, left, right):
    if callee == "numpy.divide":
        if right == 0:
            return None
        result = left / right
        # Preserve the exact Int construction when true division lands on an
        # integer. Fractional results retain their Real construction. The call
        # coordinate is shared; each assertion's typed sibling determines its
        # result sort without weakening either fact.
        if result.is_integer():
            integral = int(result)
            return integral if _fits_numpy_int64(integral) else None
        return result
    if type(left) is not int or type(right) is not int:
        return None
    if not (_fits_numpy_int64(left) and _fits_numpy_int64(right)):
        return None
    if callee == "numpy.add":
        result = left + right
    elif callee == "numpy.multiply":
        result = left * right
    elif callee == "numpy.subtract":
        result = left - right
    elif callee == "numpy.mod":
        if right == 0:
            return None
        result = left % right
    elif callee == "numpy.floor_divide":
        if right == 0:
            return None
        result = left // right
    elif callee == "numpy.power":
        if right < 0 or (left not in {-1, 0, 1} and right > 63):
            return None
        result = left**right
    elif callee == "numpy.maximum":
        result = max(left, right)
    elif callee == "numpy.minimum":
        result = min(left, right)
    else:
        return None
    return result if _fits_numpy_int64(result) else None


def _fits_numpy_int64(value: int) -> bool:
    return _NUMPY_INT64_MIN <= value <= _NUMPY_INT64_MAX
