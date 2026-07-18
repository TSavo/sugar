from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleForSugar(Sugar, role=SugarRole.STATEMENT):
    """A flat all-name loop target over one iterable element address.

    The loop element remains the existing ``py.iter_elem(iterable)``
    coordinate. Each target name binds to its indexed projection before the
    body reduces. Nested or starred targets and loop ``else`` remain separate
    loud partitions.
    """

    names: tuple[str, ...]
    iterable: SugarBody
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @staticmethod
    def recognize_target_names(site) -> tuple[str, ...] | None:
        from sugar_lift_py_tests.recognition.binding_shapes import (
            BindingShapeRecognition,
        )

        return BindingShapeRecognition.for_flat_tuple_target_names(site)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "For" or site.for_orelse_count() != 0:
            return False
        names = site.for_flat_tuple_target_names()
        return names is not None and len(names) >= 2

    @classmethod
    def new(cls, site, ctx) -> "TupleForSugar":
        names = site.for_flat_tuple_target_names()
        return cls(
            names=tuple(names),
            iterable=ctx.build_body(site.for_iter(), SugarRole.TERM),
            body=ctx.build_body(site.for_body_block(), SugarRole.STATEMENT),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    for left, right in [(z, 2)]:\n"
            "        return 1\n"
            "    return 0\n\n"
        )
        nditer_prefix = (
            "import numpy as np\n"
            "\n"
            "def B():\n"
            "    it = np.nditer([np.arange(1), np.arange(1)])\n"
            "    for left, right in it:\n"
            "        pass\n"
            "    del left, right, it\n"
            "    return 1\n"
            "\n"
        )
        return (
            _call_pair(
                name="tuple_for_return",
                owner_sugar="TupleForSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
                lying=prefix + "def test_a():\n    assert A(5) == 0\n",
            ),
            _call_pair(
                name="tuple_for_nonempty_nditer_cleanup",
                owner_sugar="TupleForSugar",
                truthful=nditer_prefix + "def test_b():\n    assert B() == 1\n",
                lying=nditer_prefix + "def test_b():\n    assert B() == 0\n",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.iterable.reduce(ctx).and_then(
            lambda iterable: self._bind_targets_and_body(iterable, ctx)
        )

    def _bind_targets_and_body(self, iterable, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import (
            ArrayLiteral,
            BlockValue,
            CallSiteValue,
            ComprehensionValue,
            ListValue,
            ScopeRebind,
            TupleValue,
        )
        from sugar_lift_py_tests.ir import ctor, num

        # Finite concrete sequences construct each iteration — same door as
        # ForSugar. Ground py.subscript(iter_elem(...), i) targets cannot mint
        # truth/RuntimeEffect authority (#5147 format.py / TupleFor representatives).
        elements = None
        if type(iterable) in (ListValue, TupleValue):
            elements = iterable.elements
        elif type(iterable) is ArrayLiteral:
            elements = iterable.items
        elif (
            type(iterable) is ComprehensionValue
            and iterable.finite_elements is not None
        ):
            elements = iterable.finite_elements
        if elements is not None:
            return self._unfold_values(elements, ctx)

        element = CallSiteValue(
            target_name="iter_elem",
            arg_values=(iterable,),
            parameters=(),
            term=ctor(
                "py.iter_elem",
                [iterable.to_term(owner=str(self.site))],
            ),
            body=None,
            site=self.site,
        )
        temporal = ctx.temporal
        target_values = {}
        for index, name in enumerate(self.names):
            target = CallSiteValue(
                target_name="py.subscript",
                arg_values=(element,),
                parameters=(),
                term=ctor("py.subscript", [element.term, num(index)]),
                body=None,
                site=self.site,
            )
            target_values[name] = target
            temporal = temporal.bind_value(
                name,
                target,
            )
        body_ctx = ctx.with_temporal(temporal)
        if not _proves_nonempty_nditer(iterable):
            return self.body.reduce(body_ctx)

        record, final_ctx = self.body.sugar.reduce_with_scope(body_ctx)
        post_loop_bindings = tuple(
            ScopeRebind(
                name,
                final_ctx.temporal.value_if_bound(name) or target_values[name],
            )
            for name in self.names
        )
        return Complete(
            BlockValue(
                (*record.statements, *post_loop_bindings),
                fall_through=record.fall_through,
                can_fall_through=record.can_fall_through,
            )
        )

    def _unfold_values(self, values, ctx: object) -> Outcome:
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.floor import BlockValue
        from sugar_lift_py_tests.sugar.for_sugar import (
            STATIC_UNFOLD_LIMIT,
            _post_loop_bindings,
        )

        if len(values) > STATIC_UNFOLD_LIMIT:
            factory_panic_gap(
                owner="TupleForSugar",
                blame=self.site,
                observed=f"finite iterable length {len(values)}",
                requested="static tuple-for unfold within budget",
                fix=(
                    f"tuple-for over {len(values)} elements exceeds "
                    f"STATIC_UNFOLD_LIMIT={STATIC_UNFOLD_LIMIT}; project through "
                    "callable floors or shrink the constructed iterable"
                ),
            )

        accumulated = []
        current_ctx = ctx
        for value in values:
            parts = _unpack_tuple_element(value, arity=len(self.names), site=self.site)
            temporal = current_ctx.temporal
            for name, part in zip(self.names, parts):
                temporal = temporal.bind_value(name, part)
            iteration_ctx = current_ctx.with_temporal(temporal)
            record, current_ctx = self.body.sugar.reduce_with_scope(iteration_ctx)
            accumulated.extend(record.contribution())
        bindings = _post_loop_bindings(ctx, current_ctx)
        return Complete(BlockValue((*accumulated, *bindings)))

    def walk_children(self):
        return (self.iterable, self.body)


def _unpack_tuple_element(value, *, arity: int, site) -> tuple:
    """Project one constructed sequence element into flat tuple-for targets.

    Only concrete ListValue/TupleValue/ArrayLiteral members of matching arity
    unfold. Opaque residual stays loud at the construction door.
    """
    from sugar_lift_py_tests.factory import factory_panic_gap
    from sugar_lift_py_tests.floor import ArrayLiteral, ListValue, TupleValue

    parts = None
    if type(value) in (ListValue, TupleValue):
        parts = value.elements
    elif type(value) is ArrayLiteral:
        parts = value.items
    if parts is None or len(parts) != arity:
        factory_panic_gap(
            owner="TupleForSugar",
            blame=site,
            observed=type(value).__name__,
            requested=f"finite sequence of length {arity} for tuple-for unpack",
            fix=(
                "construct each tuple-for iterable member as ListValue/TupleValue "
                f"with exactly {arity} elements before unfold; opaque or wrong-arity "
                "members cannot project target bindings"
            ),
        )
    return parts


def _proves_nonempty_nditer(iterable) -> bool:
    """Prove the closed NumPy nditer subset that executes at least once.

    Tuple targets survive a Python ``for`` only after an iteration.  Unknown
    iterables therefore retain the existing loud post-loop unbound-name
    behavior.  This door admits only the source-resolved NumPy constructors
    whose ground shape is visible in the call coordinate.
    """

    from sugar_lift_py_tests.floor import CallSiteValue, ImportAliasValue, ListValue

    if type(iterable) is not CallSiteValue or not _is_numpy_call(
        iterable, qualified="numpy.nditer", member="nditer"
    ):
        return False
    args = iterable.arg_values
    if args and type(args[0]) is ImportAliasValue:
        args = args[1:]
    if not args or type(args[0]) is not ListValue or not args[0].elements:
        return False
    return all(_proves_nonempty_numpy_array(value) for value in args[0].elements)


def _proves_nonempty_numpy_array(value) -> bool:
    from sugar_lift_py_tests.floor import CallSiteValue, TermValue

    if type(value) is not CallSiteValue:
        return False
    if value.target_name == "astype":
        args = _without_import_receiver(value.arg_values)
        return bool(args) and _proves_nonempty_numpy_array(args[0])
    if _is_numpy_call(value, qualified="numpy.arange", member="arange"):
        args = _without_import_receiver(value.arg_values)
        bounds = [
            arg.value
            for arg in args
            if type(arg) is TermValue and type(arg.value) is int
        ]
        if len(bounds) != len(args) or not 1 <= len(bounds) <= 3:
            return False
        try:
            return len(range(*bounds)) > 0
        except ValueError:
            return False
    if value.target_name == "numpy.random.randint":
        size = _ground_keyword_int(value, "size")
        return size is not None and size > 0
    return False


def _without_import_receiver(args):
    from sugar_lift_py_tests.floor import ImportAliasValue

    if args and type(args[0]) is ImportAliasValue:
        return args[1:]
    return args


def _is_numpy_call(callsite, *, qualified: str, member: str) -> bool:
    from sugar_lift_py_tests.floor import ImportAliasValue

    if callsite.target_name == qualified:
        return True
    receiver = callsite.runtime_dispatch_receiver
    return (
        callsite.target_name == member
        and type(receiver) is ImportAliasValue
        and receiver.name == "numpy"
        and receiver.import_target == "numpy"
    )


def _ground_keyword_int(callsite, name: str) -> int | None:
    from sugar_lift_py_tests.ir import _ConstInt, _ConstStr, _Ctor

    if not isinstance(callsite.term, _Ctor):
        return None
    for arg in callsite.term.args:
        if (
            isinstance(arg, _Ctor)
            and arg.name == "kw"
            and len(arg.args) == 2
            and isinstance(arg.args[0], _ConstStr)
            and arg.args[0].value == name
            and isinstance(arg.args[1], _ConstInt)
        ):
            return arg.args[1].value
    return None
