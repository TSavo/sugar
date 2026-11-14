"""Same-module ClassDef CM derivation — receipt-less populate door.

Local ``with M():`` has no import receipt. Populate must still derive a
``SourceDerivedContextManagerRefV1`` when ``M`` is a module ClassDef with
``__enter__``/``__exit__``, so With constructs through the L3d require door.
"""

from __future__ import annotations

import csv
import importlib.metadata
import textwrap
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedContextManagerRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.nodes import With
from sugar_source_tree.panic import ContextManagerResolutionConstructionGap
from sugar_source_tree.tree import SourceFile


def _source_file(
    tmp_path: Path, source: str
) -> tuple[SourceFile, TreeConstructionContextV1, Path]:
    path = tmp_path / "consumer.py"
    path.write_text(source, encoding="utf-8")
    cid = blake3_512_of(source.encode())
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile((source, str(path), cid), construction_context=context)
    return tree, context, path


def _installed_distribution(
    root: Path,
    *,
    package: str,
    source: str,
    duplicate_module_seat: bool = False,
) -> importlib.metadata.Distribution:
    package_dir = root / package
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(source, encoding="utf-8")
    recorded = [f"{package}/__init__.py"]
    if duplicate_module_seat:
        (root / f"{package}.py").write_text(source, encoding="utf-8")
        recorded.append(f"{package}.py")
    metadata = root / f"{package}_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {package}-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(f"{package}\n", encoding="utf-8")
    recorded.extend(
        (
            f"{package}_dist-1.0.dist-info/METADATA",
            f"{package}_dist-1.0.dist-info/top_level.txt",
            f"{package}_dist-1.0.dist-info/RECORD",
        )
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for seat in recorded:
            writer.writerow((seat, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _imported_manager_gap(
    tmp_path: Path,
    *,
    package: str,
    distribution: importlib.metadata.Distribution | None = None,
):
    source = textwrap.dedent(f"""\
        from {package} import M
        def f():
            with M():
                return 1
        """)
    tree, context, path = _source_file(tmp_path, source)
    distribution_index = None if distribution is None else {package: distribution}
    enrolled_distribution = (
        "consumer" if distribution is None else distribution.metadata["Name"]
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index=distribution_index,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({enrolled_distribution})
        ),
    )
    assert len(context.source_derived_contract_refs) == 1
    gap = next(iter(context.source_derived_contract_refs.values()))
    assert type(gap).__name__ == "ContextManagerResolutionGapV1"
    with_node = next(node for node in tree.nodes() if isinstance(node, With))
    with pytest.raises(ContextManagerResolutionConstructionGap) as caught:
        with_node.sugar()
    return gap, caught.value.observed


def test_local_classdef_cm_derives_and_constructs(tmp_path: Path):
    """Visible same-module ClassDef CM: populate derives; With constructs."""
    source = textwrap.dedent("""\
        class M:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        def f():
            with M():
                return 1
        """)
    tree, context, path = _source_file(tmp_path, source)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )

    assert len(context.source_derived_contract_refs) == 1
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(ref, SourceDerivedContextManagerRefV1)

    with_node = next(n for n in tree.nodes() if isinstance(n, With))
    sugar = with_node.sugar()
    assert isinstance(sugar, WithSourceResourceSugar)


def test_isinstance_tuple_wrap_derives_expected_exceptions(tmp_path: Path):
    """RaisesExc-style isinstance wrap keeps the constructed expected_exceptions.

    ``if isinstance(expected_exception, tuple): ... else: (expected,)``
    partitions the constructor. The completed leaf already stores
    ``expected_exceptions``; rejecting the partition as a provenance mismatch
    dropped that field before EffectBoundary derivation could see it.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
    )

    source = textwrap.dedent("""\
        class RaisesExc:
            def __init__(self, expected_exception=None):
                if isinstance(expected_exception, tuple):
                    expected_exceptions = expected_exception
                elif expected_exception is None:
                    expected_exceptions = ()
                else:
                    expected_exceptions = (expected_exception,)
                self.expected_exceptions = expected_exceptions
            def __enter__(self):
                return self
            def __exit__(self, effect_type, effect, traceback):
                if effect_type is None:
                    raise RuntimeError()
                return effect_type is self.expected_exceptions[0]
        def use():
            with RaisesExc(ValueError):
                raise ValueError("nested")
        """)
    tree, context, path = _source_file(tmp_path, source)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )

    assert len(context.source_derived_contract_refs) == 1
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(ref, SourceDerivedContextManagerRefV1), ref
    assert getattr(ref, "kind", None) is None, ref
    assert isinstance(ref.semantics, EffectBoundarySemanticsV1), ref.semantics
    assert isinstance(ref.semantics.mode, ExpectsModeV1)


def test_last_init_wins_over_ellipsis_overload_stub(tmp_path: Path):
    """Python's live ``__init__`` is the last same-name method, not an overload stub.

    ``@overload`` / ``def __init__(...): ...`` precedes the implementation on
    RaisesExc. Selecting the first ``__init__`` constructed through an ellipsis
    body and left ``expected_exceptions`` unwritten.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
    )

    source = textwrap.dedent("""\
        class RaisesExc:
            def __init__(self, expected_exception: type) -> None: ...
            def __init__(self, expected_exception=None):
                if isinstance(expected_exception, tuple):
                    expected_exceptions = expected_exception
                elif expected_exception is None:
                    expected_exceptions = ()
                else:
                    expected_exceptions = (expected_exception,)
                self.expected_exceptions = expected_exceptions
            def __enter__(self):
                return self
            def __exit__(self, effect_type, effect, traceback):
                if effect_type is None:
                    raise RuntimeError()
                return effect_type is self.expected_exceptions[0]
        def use():
            with RaisesExc(ValueError):
                raise ValueError("nested")
        """)
    tree, context, path = _source_file(tmp_path, source)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )

    assert len(context.source_derived_contract_refs) == 1
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(ref, SourceDerivedContextManagerRefV1), ref
    assert isinstance(ref.semantics, EffectBoundarySemanticsV1), ref.semantics
    assert isinstance(ref.semantics.mode, ExpectsModeV1)


def test_tuple_parse_generator_floors_expected_exceptions(tmp_path: Path):
    """``tuple(self._parse_exc(e) for e in ...)`` is TupleCoordinateValue testimony.

    With one class actual the source-visible non-tuple/non-None arm is
    ``(actual,)`` after parse identity. Floor that coordinate to TupleValue
    so ``self.expected_exceptions[0]`` can derive EffectBoundary.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
    )

    source = textwrap.dedent("""\
        class RaisesExc:
            def __init__(self, expected_exception=None):
                if isinstance(expected_exception, tuple):
                    expected_exceptions = expected_exception
                elif expected_exception is None:
                    expected_exceptions = ()
                else:
                    expected_exceptions = (expected_exception,)
                self.expected_exceptions = tuple(
                    self._parse_exc(e, expected="a BaseException type")
                    for e in expected_exceptions
                )
            def _parse_exc(self, exc, expected="a BaseException type"):
                return exc
            def __enter__(self):
                return self
            def __exit__(self, effect_type, effect, traceback):
                if effect_type is None:
                    raise RuntimeError()
                return effect_type is self.expected_exceptions[0]
        def use():
            with RaisesExc(ValueError):
                raise ValueError("nested")
        """)
    tree, context, path = _source_file(tmp_path, source)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )

    assert len(context.source_derived_contract_refs) == 1
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(ref, SourceDerivedContextManagerRefV1), ref
    assert isinstance(ref.semantics, EffectBoundarySemanticsV1), ref.semantics
    assert isinstance(ref.semantics.mode, ExpectsModeV1)


def test_generic_subscript_base_derives_expected_exceptions(tmp_path: Path):
    """``class RaisesExc(AbstractRaises[T])`` keeps AbstractRaises so super() runs.

    Desugar used to drop a Subscript base, leaving ``super()`` with zero
    direct bases and no field stores from AbstractRaises.__init__ or the
    isinstance wrap that follows it.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
    )

    source = textwrap.dedent("""\
        class AbstractRaises:
            def __init__(self, match=None, check=None):
                self.match = match
                self.check = check
        class RaisesExc(AbstractRaises[object]):
            def __init__(self, expected_exception=None, match=None, check=None):
                super().__init__(match=match, check=check)
                if isinstance(expected_exception, tuple):
                    expected_exceptions = expected_exception
                elif expected_exception is None:
                    expected_exceptions = ()
                else:
                    expected_exceptions = (expected_exception,)
                self.expected_exceptions = expected_exceptions
            def __enter__(self):
                return self
            def __exit__(self, effect_type, effect, traceback):
                if effect_type is None:
                    raise RuntimeError()
                return effect_type is self.expected_exceptions[0]
        def use():
            with RaisesExc(ValueError):
                raise ValueError("nested")
        """)
    tree, context, path = _source_file(tmp_path, source)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )

    assert len(context.source_derived_contract_refs) == 1
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(ref, SourceDerivedContextManagerRefV1), ref
    assert isinstance(ref.semantics, EffectBoundarySemanticsV1), ref.semantics
    assert isinstance(ref.semantics.mode, ExpectsModeV1)


def test_constructor_validation_halt_still_derives_expected_exceptions(tmp_path: Path):
    """A validation ``raise`` next to field stores is an ExitSet, not None.

    RaisesExc's empty-args ``ValueError`` keeps constructor application as an
    ExitSet whose completed face already holds the receiver. Reading
    ``Complete.value`` on that ExitSet invented ``non-manager-result:
    NoneType`` after ``super()`` and the isinstance wrap had run.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
    )

    source = textwrap.dedent("""\
        class AbstractRaises:
            def __init__(self, match=None, check=None):
                self.match = match
                self.check = check
        class RaisesExc(AbstractRaises[object]):
            def __init__(self, expected_exception=None, match=None, check=None):
                super().__init__(match=match, check=check)
                if isinstance(expected_exception, tuple):
                    expected_exceptions = expected_exception
                elif expected_exception is None:
                    expected_exceptions = ()
                else:
                    expected_exceptions = (expected_exception,)
                if expected_exceptions == () and match is None and check is None:
                    raise ValueError("Expected exception must be passed")
                self.expected_exceptions = expected_exceptions
            def __enter__(self):
                return self
            def __exit__(self, effect_type, effect, traceback):
                if effect_type is None:
                    raise RuntimeError()
                return effect_type is self.expected_exceptions[0]
        def use():
            with RaisesExc(ValueError):
                raise ValueError("nested")
        """)
    tree, context, path = _source_file(tmp_path, source)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )

    assert len(context.source_derived_contract_refs) == 1
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(ref, SourceDerivedContextManagerRefV1), ref
    assert isinstance(ref.semantics, EffectBoundarySemanticsV1), ref.semantics
    assert isinstance(ref.semantics.mode, ExpectsModeV1)


def test_installed_like_absent_effect_exit_derives_expected_exceptions(tmp_path: Path):
    """RaisesExc's absent-effect diagnostic uses ``not`` / ``len == 1`` / ``[0]``.

    When the constructor actual is a class, the isinstance wrap floors to a
    one-element tuple, so those checks fold and EffectBoundary still seals.
    A formal without that class actual must not invent members to pass the
    same ``[0]``.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
    )

    source = textwrap.dedent("""\
        class RaisesExc:
            def __init__(self, expected_exception=None):
                if isinstance(expected_exception, tuple):
                    expected_exceptions = expected_exception
                elif expected_exception is None:
                    expected_exceptions = ()
                else:
                    expected_exceptions = (expected_exception,)
                self.expected_exceptions = expected_exceptions
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    if not self.expected_exceptions:
                        raise RuntimeError("DID NOT RAISE any exception")
                    if len(self.expected_exceptions) == 1:
                        raise RuntimeError(self.expected_exceptions[0].__name__)
                    raise RuntimeError("several")
                return exc_type is self.expected_exceptions[0]
        def use():
            with RaisesExc(ValueError):
                raise ValueError("nested")
        """)
    tree, context, path = _source_file(tmp_path, source)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )

    assert len(context.source_derived_contract_refs) == 1
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(ref, SourceDerivedContextManagerRefV1), ref
    assert isinstance(ref.semantics, EffectBoundarySemanticsV1), ref.semantics
    assert isinstance(ref.semantics.mode, ExpectsModeV1)


def test_local_classdef_without_protocol_raises_the_interpreters_type_error(
    tmp_path: Path,
):
    """ClassDef without __enter__/__exit__, MRO proven from source: no gap row;
    the With evaluates ``NotCM()`` and halts with the interpreter's TypeError."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.manager_protocol_absence_refusal import (
        observed_non_manager_with_refusal,
    )
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset

    source = textwrap.dedent("""\
        class NotCM:
            def run(self):
                return 1
        def f():
            with NotCM():
                return 1
        """)
    tree, context, path = _source_file(tmp_path, source)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )

    assert context.source_derived_contract_refs == {}
    (proof,) = context.source_non_manager_heads.values()
    assert proof.type_name == "NotCM"
    assert (proof.has_enter, proof.has_exit) == (False, False)

    from sugar_source_tree.nodes import FunctionDef

    func = next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    (face,) = outcome_to_exitset(func.sugar().desugar()).exits
    assert isinstance(face, Halted)
    assert isinstance(face.effect, RaiseEffect)
    refusal = observed_non_manager_with_refusal(
        "NotCM", has_enter=False, has_exit=False
    )
    assert face.effect.exception_name == refusal.exception_name == "TypeError"
    assert face.effect.raised_value == refusal.message


def test_install_gap_never_attribute_errors_on_import_auth_fail(tmp_path: Path):
    """Import CM without dist: gap installs; no AttributeError on deleted ground mint."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text(
        textwrap.dedent("""\
            class M:
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return False
            """),
        encoding="utf-8",
    )
    source = textwrap.dedent("""\
        from pkg import M
        def f():
            with M():
                return 1
        """)
    tree, context, path = _source_file(tmp_path, source)
    # No distribution_index → authenticate fails → no-derived-contract gap.
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )
    assert len(context.source_derived_contract_refs) == 1
    gap = next(iter(context.source_derived_contract_refs.values()))
    assert type(gap).__name__ == "ContextManagerResolutionGapV1"
    assert gap.kind == "no-derived-contract"


def test_manager_derivation_reasons_distinguish_dependency_failure_causes(
    tmp_path: Path,
) -> None:
    """Absent, ambiguous, and contract-missing are distinct receipt reasons."""
    absent_root = tmp_path / "absent"
    absent_root.mkdir()
    absent, absent_observed = _imported_manager_gap(
        absent_root, package="absent_manager_pkg"
    )

    ambiguous_root = tmp_path / "ambiguous"
    ambiguous_root.mkdir()
    ambiguous_distribution = _installed_distribution(
        ambiguous_root,
        package="ambiguous_manager_pkg",
        source="class M:\n    pass\n",
        duplicate_module_seat=True,
    )
    ambiguous, ambiguous_observed = _imported_manager_gap(
        ambiguous_root,
        package="ambiguous_manager_pkg",
        distribution=ambiguous_distribution,
    )

    missing_contract_root = tmp_path / "missing_contract"
    missing_contract_root.mkdir()
    missing_contract_distribution = _installed_distribution(
        missing_contract_root,
        package="missing_contract_pkg",
        source="class M:\n    pass\n",
    )
    missing_contract, missing_contract_observed = _imported_manager_gap(
        missing_contract_root,
        package="missing_contract_pkg",
        distribution=missing_contract_distribution,
    )

    reasons = {
        "absent": (absent.kind, absent.detail),
        "ambiguous": (ambiguous.kind, ambiguous.detail),
        "missing-contract": (missing_contract.kind, missing_contract.detail),
    }
    assert len(set(reasons.values())) == 3, reasons
    assert "absent_manager_pkg" in (absent.detail or "")
    assert "authenticated stdlib root" in (absent.detail or "")
    assert "ambiguous_manager_pkg" in (ambiguous.detail or "")
    assert "duplicate module seat" in (ambiguous.detail or "")
    assert missing_contract.kind == "enter-missing"
    assert missing_contract.detail == "source-visible method"
    observed_reasons = {
        absent_observed,
        ambiguous_observed,
        missing_contract_observed,
    }
    assert len(observed_reasons) == 3, observed_reasons
    assert absent.detail in absent_observed
    assert ambiguous.detail in ambiguous_observed
    assert missing_contract.detail in missing_contract_observed
