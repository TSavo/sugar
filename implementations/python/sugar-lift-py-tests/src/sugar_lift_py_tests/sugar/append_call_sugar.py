from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AppendCallSugar(
    Sugar,
    role=SugarRole.TERM,
    comes_before=("MethodCallSugar",),
):
    """`xs.append(v)`: mutation is a rebind. Reduce the argument, look up the
    receiver's current binding, ask its floor to append, and rebind the name to
    the updated value. Concrete list history folds; the statement is support
    (scope only). Aliasing stays a loud gap."""

    receiver_name: str
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # One method, one sugar: bare-Name receiver, one positional arg, no keywords.
        # Guard observed first -- Call accessors panic on non-Call sites.
        if site.observed != "Call" or site.call_target_name() != "append":
            return False
        receiver = site.call_receiver()
        return (
            receiver is not None
            and receiver.observed == "Name"
            and len(site.call_args()) == 1
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx) -> "AppendCallSugar":
        # The argument is factory-built (audited), never reduced here.
        return cls(
            receiver_name=site.call_receiver().name_id(),
            value=ctx.build_body(site.call_args()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Append rebinds the name; the return face carries z. Truthful/lying
        # twins discriminate on the returned face -- the mutation is just present.
        prefix = "def A(z):\n    xs = [1]\n    xs.append(z)\n    return z\n\n"
        length_prefix = (
            "def A():\n" "    xs = [1]\n" "    xs.append(2)\n" "    return len(xs)\n\n"
        )
        comprehension_prefix = (
            "def A(values, z):\n"
            "    xs = [value for value in values]\n"
            "    xs.append(z)\n"
            "    return z\n"
            "\n"
        )
        finite_cast_prefix = (
            "from typing import cast\n\n"
            "def A():\n"
            '    attrs = cast("list[int]", [1])\n'
            "    attrs.append(2)\n"
            "    return len(attrs)\n"
            "\n"
        )
        finite_copy_prefix = (
            "def A():\n"
            "    xs = [1].copy()\n"
            "    xs.append(2)\n"
            "    return len(xs)\n"
            "\n"
        )
        # Diggable unpack: function returns a triple whose third face is a list
        # (pandas io.common handles residual). Annotation-free construction.
        diggable_unpack_prefix = (
            "def A():\n"
            "    def f():\n"
            "        return (1, True, [0])\n"
            "\n"
            "    h, m, handles = f()\n"
            "    handles.append(9)\n"
            "    return len(handles)\n"
            "\n"
        )
        # Diggable cast: cast of a list-returning call digs through (range.py).
        diggable_cast_prefix = (
            "from typing import cast\n"
            "\n"
            "def A():\n"
            "    def get_items():\n"
            "        return [1, 2]\n"
            "\n"
            "    attrs = cast('list', get_items())\n"
            "    attrs.append(3)\n"
            "    return len(attrs)\n"
            "\n"
        )
        return (
            _call_pair(
                name="append_return",
                owner_sugar="AppendCallSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
                lying=prefix + "def test_a():\n    assert A(5) == 6\n",
            ),
            _call_pair(
                name="append_length_return",
                owner_sugar="AppendCallSugar",
                truthful=length_prefix + "def test_a():\n    assert A() == 2\n",
                lying=length_prefix + "def test_a():\n    assert A() == 1\n",
            ),
            _call_pair(
                name="append_comprehension_return",
                owner_sugar="AppendCallSugar",
                truthful=comprehension_prefix
                + "def test_a():\n"
                + "    assert A([1, 2], 3) == 3\n",
                lying=comprehension_prefix
                + "def test_a():\n"
                + "    assert A([1, 2], 3) == 2\n",
            ),
            _call_pair(
                name="append_finite_cast_return",
                owner_sugar="AppendCallSugar",
                truthful=finite_cast_prefix
                + "def test_a():\n"
                + "    assert A() == 2\n",
                lying=finite_cast_prefix + "def test_a():\n" + "    assert A() == 1\n",
                family="finite-cast-list-append",
            ),
            _call_pair(
                name="append_finite_copy_return",
                owner_sugar="AppendCallSugar",
                truthful=finite_copy_prefix
                + "def test_a():\n"
                + "    assert A() == 2\n",
                lying=finite_copy_prefix + "def test_a():\n" + "    assert A() == 1\n",
                family="finite-copy-list-append",
            ),
            _call_pair(
                name="append_diggable_unpack_return",
                owner_sugar="AppendCallSugar",
                truthful=diggable_unpack_prefix
                + "def test_a():\n"
                + "    assert A() == 2\n",
                lying=diggable_unpack_prefix
                + "def test_a():\n"
                + "    assert A() == 1\n",
                family="diggable-unpack-list-append",
            ),
            _call_pair(
                name="append_diggable_cast_return",
                owner_sugar="AppendCallSugar",
                truthful=diggable_cast_prefix
                + "def test_a():\n"
                + "    assert A() == 3\n",
                lying=diggable_cast_prefix
                + "def test_a():\n"
                + "    assert A() == 2\n",
                family="diggable-cast-list-append",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce the arg, look up the receiver, append, rebind to the updated value.
        return self.value.reduce(ctx).and_then(
            lambda arg: ctx.temporal.value_for(self.receiver_name)
            .answer(ctx)
            .and_then(lambda receiver: self._append(receiver, arg))
        )

    def _append(self, receiver, value) -> Outcome:
        from sugar_lift_py_tests.floor import CallSiteValue

        if isinstance(receiver, CallSiteValue) and _is_pandas_index_like(receiver):
            # Index.append is non-mutating: construct the method coordinate as
            # the expression face. Do not rebind the receiver name.
            return Complete(receiver.linear_method_call("append", (value,), self.site))
        return receiver.append_with(value, self.site).and_then(
            lambda updated: Complete(ScopeRebind(self.receiver_name, updated))
        )


_PANDAS_INDEX_CALL_TARGETS = frozenset(
    {
        "pandas.DatetimeIndex",
        "pandas.Index",
        "pandas.IntervalIndex",
        "pandas.IntervalIndex.from_breaks",
        "pandas.MultiIndex.from_arrays",
        "pandas.PeriodIndex",
        "pandas.RangeIndex",
        "pandas.core.indexes.api.Index",
        "pandas.TimedeltaIndex",
        "pandas.core.indexes.datetimes.date_range",
        "pandas.core.indexes.period.period_range",
        "pandas.core.indexes.timedeltas.timedelta_range",
    }
)

# Methods that return the same Index species when invoked on an Index-like
# coordinate. Live residual: ``date_range(...).as_unit(unit).append(...)``.
_PANDAS_INDEX_PRESERVING_METHODS = frozenset({"as_unit"})


def _is_pandas_index_like(receiver) -> bool:
    """True when the callsite is a known Index constructor or Index-preserving chain."""
    from sugar_lift_py_tests.floor import CallSiteValue

    if not isinstance(receiver, CallSiteValue):
        return False
    if receiver.target_name in _PANDAS_INDEX_CALL_TARGETS:
        return True
    if (
        receiver.target_name in _PANDAS_INDEX_PRESERVING_METHODS
        and receiver.arg_values
        and isinstance(receiver.arg_values[0], CallSiteValue)
    ):
        return _is_pandas_index_like(receiver.arg_values[0])
    return False
