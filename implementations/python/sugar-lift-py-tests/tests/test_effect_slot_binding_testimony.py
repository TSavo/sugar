"""Effect slots: pure coordinates + explicit binding facts (no ambient auth)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


from sugar_lift_py_tests.repo_root import python_implementations_root, sugar_lift_py_tests_package_root

_ROOT = sugar_lift_py_tests_package_root()
_SRC = _ROOT / "src" / "sugar_lift_py_tests"


def test_no_effect_auth_contextvar_side_door() -> None:
    """R: ambient effect auth must stay zero."""
    assert not (_SRC / "effect_auth.py").exists()
    banned = ("effect_auth", "authenticate_slot", "lookup_slot", "effect_auth_wave")
    offenders: list[str] = []
    for path in _SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                offenders.append(f"{path.relative_to(_SRC)}:{token}")
    assert offenders == [], f"ambient effect auth residual: {offenders}"


def test_effect_coordinate_never_embeds_effect_payload() -> None:
    from sugar_lift_py_tests.floor.effect_coordinate import (
        EffectCoordinate,
        ExceptionInfoCoordinate,
    )

    fields = {f.name for f in EffectCoordinate.__dataclass_fields__.values()}
    assert "effect" not in fields
    fields = {f.name for f in ExceptionInfoCoordinate.__dataclass_fields__.values()}
    assert "effect" not in fields
    coord = EffectCoordinate(slot_id="file.py:1:0:1:10")
    term = coord.to_term(owner="test")
    assert term.name == "python:effect_slot"
    assert term.args[0].value == "file.py:1:0:1:10"


def test_observed_effect_projects_only_an_authenticated_context_preimage() -> None:
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.floor.effect_coordinate import (
        EffectCoordinate,
        ObservedEffectValue,
    )
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    inner_value = TermValue(7)
    inner = RaiseEffect.for_builtin(
        "ImportError",
        raised_value=inner_value,
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_effect_slot_binding_testimony.py:101:0",
    )
    outer = RaiseEffect.for_builtin(
        "ValueError",
        context_effect=inner,
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_effect_slot_binding_testimony.py:102:0",
    )

    projected = ObservedEffectValue(slot_id="S", effect=outer).attribute(
        "__context__", site=None, ctx=None
    )
    assert projected.completed_value() is inner_value

    with pytest.raises(ConstructionPanic) as caught:
        EffectCoordinate(slot_id="S").attribute("__context__", site=None, ctx=None)
    assert caught.value.info.owner == "EffectCoordinate.attribute.__context__"
    assert "no authenticated context preimage" in caught.value.info.observed


def test_effect_ref_observes_the_same_effect_the_route_deposited() -> None:
    """``except ... as e`` → EffectRef: bound name is the routed RaiseEffect.

    Truthful: observed context for slot S yields ObservedEffectValue whose
    ``effect`` is the exact object deposited (identity, not type spelling).
    Lying: without the observed preimage the projection is a pure coordinate
    that cannot answer ``__context__``.
    """
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.floor.effect_coordinate import (
        EffectCoordinate,
        ObservedEffectValue,
    )
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.sugar.effect_ref_sugar import EffectRefSugar

    inner_value = TermValue(11)
    inner = RaiseEffect.for_builtin(
        "ImportError",
        raised_value=inner_value,
        occurrence="inner.py:1:0",
    )
    routed = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="outer.py:2:4",
        context_effect=inner,
    )
    other = RaiseEffect.for_builtin("ValueError", occurrence="other.py:9:0")

    ctx = ReduceContext.root(owner="as-e-identity").with_observed_effect("S", routed)
    out = EffectRefSugar(slot_id="S").desugar(ctx)
    observed = out.completed_value()
    assert observed is not None
    assert isinstance(observed, ObservedEffectValue)
    assert observed.effect is routed
    assert observed.effect is not other
    assert observed.effect.occurrence_id == "outer.py:2:4"
    # Same occurrence the boundary routed: context preimage is authentic.
    projected = observed.attribute("__context__", site=None, ctx=None)
    assert projected.completed_value() is inner_value

    # Unauthenticated twin: pure coordinate stays loud on the same projection.
    bare = EffectRefSugar(slot_id="S").desugar(None)
    assert bare.completed_value() is not None
    assert type(bare.completed_value()) is EffectCoordinate
    with pytest.raises(ConstructionPanic) as caught:
        bare.completed_value().attribute("__context__", site=None, ctx=None)
    assert "no authenticated context preimage" in caught.value.info.observed


def test_function_universe_threads_observed_effect_binding_into_next_statement() -> (
    None
):
    """ObservedEffectBinding in the prefix authenticates the next EffectRef.

    ``reduce_block_to_exitset`` must install prior ObservedEffectBinding rows
    onto the statement context before desugaring — the same seam With/Try use
    after a consumed halt deposits producer testimony into the block record.
    """
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.effect_router import ObservedEffectBinding
    from sugar_lift_py_tests.floor.effect_coordinate import (
        EffectCoordinate,
        ObservedEffectValue,
    )
    from sugar_lift_py_tests.outcome.exit_set import ExitSet
    from sugar_lift_py_tests.sugar.effect_ref_sugar import EffectRefSugar
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        reduce_block_to_exitset,
    )

    routed = RaiseEffect.for_builtin("ValueError", occurrence="route.py:3:0")

    # Unauthenticated: no observed preimage → pure coordinate.
    bare = reduce_block_to_exitset((EffectRefSugar(slot_id="S"),)).completed_value()
    assert bare is not None
    assert type(bare.entries[0]) is EffectCoordinate

    # Authenticated via ctx (handler path): same RaiseEffect object.
    via_ctx = reduce_block_to_exitset(
        (EffectRefSugar(slot_id="S"),),
        ReduceContext.root(owner="seed").with_observed_effect("S", routed),
    ).completed_value()
    assert via_ctx is not None
    assert isinstance(via_ctx.entries[0], ObservedEffectValue)
    assert via_ctx.entries[0].effect is routed

    # Authenticated via prior entry (function_universe thread path).
    # ObservedEffectBinding.contribution() is empty on purpose (preimage, not
    # FOL); producers deposit it into _ReducedBlock.entries the way Try/With
    # prepend facts after a consumed halt. The next statement must then see it.
    class _Deposit:
        def desugar(self, ctx):
            del ctx
            return ExitSet.completed(
                _ReducedBlock(
                    entries=(ObservedEffectBinding(slot_id="S", effect=routed),),
                    can_fall_through=True,
                    fall_through=(),
                )
            )

    class _Read:
        def desugar(self, ctx):
            return EffectRefSugar(slot_id="S").desugar(ctx)

    via_entries = reduce_block_to_exitset((_Deposit(), _Read())).completed_value()
    assert via_entries is not None
    read = via_entries.entries[-1]
    assert isinstance(read, ObservedEffectValue)
    assert read.effect is routed


def test_observed_exception_info_type_is_the_language_class() -> None:
    """``excinfo.type`` cites the raise effect's already-authenticated type."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.floor.builtin_exception_class_value import (
        BuiltinExceptionClassValue,
    )
    from sugar_lift_py_tests.floor.effect_coordinate import (
        ExceptionInfoCoordinate,
        ObservedExceptionInfoValue,
    )
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    routed = RaiseEffect.for_builtin("ValueError", occurrence="route.py:3:0")
    observed = ObservedExceptionInfoValue(slot_id="S", effect=routed)
    projected = observed.attribute("type", site=None, ctx=None)
    typ = projected.completed_value()
    assert typ is not None
    assert isinstance(typ, BuiltinExceptionClassValue)
    assert typ.name == "ValueError"
    assert typ is builtin_name_temporal().value_if_bound("ValueError")

    # Without a raised instance, .value stays loud rather than substituting
    # the observation wrapper for the exception.
    with pytest.raises(ConstructionPanic) as caught:
        observed.attribute("value", site=None, ctx=None)
    assert caught.value.info.observed == "ObservedExceptionInfoValue"

    from sugar_lift_py_tests.floor.string_value import StringValue

    instance = StringValue("boom")
    with_instance = ObservedExceptionInfoValue(
        slot_id="S",
        effect=RaiseEffect.for_builtin(
            "ValueError", occurrence="route.py:3:0", raised_value=instance
        ),
    )
    value = with_instance.attribute("value", site=None, ctx=None)
    assert value.completed_value() is not None
    assert value.completed_value() is instance

    with pytest.raises(ConstructionPanic) as caught:
        ExceptionInfoCoordinate(slot_id="S").attribute("type", site=None, ctx=None)
    assert caught.value.info.observed == "ExceptionInfoCoordinate"

    foreign = RaiseEffect(
        exception_type_coordinate=ctor(
            "python:exception_type_identity",
            [str_const("mypkg"), str_const("Oops")],
        ),
        occurrence="foreign.py:1:0",
        exception_name="Oops",
    )
    with pytest.raises(ConstructionPanic) as caught:
        ObservedExceptionInfoValue(slot_id="S", effect=foreign).attribute(
            "type", site=None, ctx=None
        )
    assert caught.value.info.observed == "ObservedExceptionInfoValue"


def test_exception_callsite_args_are_the_constructor_arguments() -> None:
    """An authenticated exception instance projects ``.args`` as what its
    construction stored (``constructed_args``, #7757)."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.ir import ctor, str_const

    boom = StringValue("boom")
    identity = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("ValueError")],
    )
    instance = CallSiteValue(
        target_name="ValueError",
        arg_values=(boom,),
        parameters=(),
        term=ctor("call:ValueError", [str_const("boom")]),
        body=None,
        exception_type_coordinate=identity,
        constructed_args=TupleValue(elements=(boom,)),
    )
    projected = instance.attribute("args", site=None, ctx=None)
    assert projected.completed_value() is not None
    assert projected.completed_value() == TupleValue(elements=(boom,))

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    site = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 1, 6)
    ordinary = CallSiteValue(
        target_name="ValueError",
        arg_values=(boom,),
        parameters=(),
        term=ctor("call:ValueError", [str_const("boom")]),
        body=None,
    )
    # An ordinary unexecuted call has no decided type: ``.args`` is the
    # #7585 two-faced lookup of the coordinate ``attr:args``, never a tuple.
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    faces = ordinary.attribute("args", site=site, ctx=None)
    assert isinstance(faces, ExitSet)
    (completed,) = [f for f in faces.exits if isinstance(f, Completed)]
    assert [f for f in faces.exits if isinstance(f, Halted)]
    assert not isinstance(completed.value, TupleValue)
    assert completed.value.term.name == "attr:args"


def test_no_process_identity_in_slot_fallback() -> None:
    """nodes._effect_slot_id must not call id(self) as a fallback."""
    import re

    text = (
        python_implementations_root()
        / "sugar-source-tree"
        / "src"
        / "sugar_source_tree"
        / "nodes.py"
    ).read_text(encoding="utf-8")
    start = text.find("def _effect_slot_id")
    end = text.find("\n    def ", start + 1)
    body = text[start:end]
    # Executable expressions only: ban the call form `id(self)`.
    assert re.search(r"(?<![A-Za-z_])id\(\s*self\s*\)", body) is None
