from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.collect_dunder_frontier import collect_dunder_frontier

ROOT = Path(__file__).resolve().parents[4]


def test_dunder_frontier_vector_names_current_missing_families() -> None:
    report = collect_dunder_frontier(ROOT)

    assert report.r.values == {
        "attribute_descriptor_slots": 0,
        "call_container_slots": 0,
        "comparison_slots": 0,
        "inplace_binary_slots": 0,
        "lifecycle_slots": 0,
        "mutation_container_slots": 0,
        "numeric_binary_slots": 0,
        "numeric_conversion_slots": 0,
        "reflected_binary_slots": 0,
        "truth_hash_slots": 0,
        "unary_numeric_slots": 0,
        "display_conversion_slots": 0,
        "context_async_slots": 0,
    }
    assert report.r.total == 0
    assert report.is_zero


def test_dunder_frontier_distinguishes_owned_and_missing_slots() -> None:
    report = collect_dunder_frontier(ROOT)
    by_name = {slot.name: slot for slot in report.slots}

    for name in (
        "__call__",
        "__getitem__",
        "__contains__",
        "__iter__",
        "__next__",
        "__setitem__",
        "__delitem__",
        "__reversed__",
        "__missing__",
        "__bool__",
        "__len__",
        "__hash__",
        "__repr__",
        "__eq__",
        "__ge__",
        "__truediv__",
        "__divmod__",
        "__rdivmod__",
        "__rxor__",
        "__iadd__",
        "__ior__",
        "__invert__",
        "__abs__",
        "__round__",
        "__floor__",
        "__ceil__",
        "__trunc__",
        "__int__",
        "__float__",
        "__complex__",
        "__index__",
        "__str__",
        "__bytes__",
        "__format__",
        "__getattr__",
        "__getattribute__",
        "__setattr__",
        "__delattr__",
        "__dir__",
        "__get__",
        "__set__",
        "__delete__",
        "__set_name__",
        "__enter__",
        "__exit__",
    ):
        assert by_name[name].status == "owned", name
        assert by_name[name].owner

    for name in (
        "__aenter__",
        "__aexit__",
        "__await__",
        "__aiter__",
        "__anext__",
    ):
        assert by_name[name].status == "owned", name
        assert by_name[name].owner


def test_dunder_frontier_cli_exits_red_until_tracked_slots_are_owned(
    capsys,
) -> None:
    status = cli.main(["--root", str(ROOT), "--dunder-frontier"])

    assert status == 0
    stdout = capsys.readouterr().out
    assert "python dunder frontier audit" in stdout
    assert "R:" in stdout
    assert "  inplace_binary_slots: 0" in stdout
    assert "  mutation_container_slots: 0" in stdout
    assert "  attribute_descriptor_slots: 0" in stdout
    assert "  total: 0" in stdout
    assert "missing dunder slots:" not in stdout
    owned = stdout.split("owned dunder slots:", 1)[1]
    missing = ""
    assert "  - call_container __next__" not in missing
    assert "  - call_container __next__: NextOperation" in owned
    assert "  - display_conversion __repr__" not in missing
    assert (
        "  - display_conversion __repr__: BuiltinCallSugar._BUILTIN_DUNDER_METHODS"
        in owned
    )
    assert "  - display_conversion __str__" not in missing
    assert "  - display_conversion __str__: StrCoercionOperation" in owned
    assert "  - display_conversion __bytes__" not in missing
    assert (
        "  - display_conversion __bytes__: BuiltinCallSugar._BUILTIN_DUNDER_METHODS"
        in owned
    )
    assert "  - display_conversion __format__" not in missing
    assert "  - display_conversion __format__: FormatBuiltinSugar" in owned
    assert "  - mutation_container __reversed__" not in missing
    assert (
        "  - mutation_container __reversed__: BuiltinCallSugar._BUILTIN_DUNDER_METHODS"
        in owned
    )
    assert "  - mutation_container __setitem__" not in missing
    assert "  - mutation_container __setitem__: SetItemOperation" in owned
    assert "  - mutation_container __delitem__" not in missing
    assert "  - mutation_container __delitem__: DelItemOperation" in owned
    assert "  - mutation_container __missing__" not in missing
    assert "  - mutation_container __missing__: DictMissingOperation" in owned
    assert "  - attribute_descriptor __getattr__" not in missing
    assert "  - attribute_descriptor __getattr__: AttributeLookupOperation" in owned
    assert "  - attribute_descriptor __getattribute__" not in missing
    assert (
        "  - attribute_descriptor __getattribute__: "
        "AttributeLookupOperation.__getattribute__"
    ) in owned
    assert "  - attribute_descriptor __setattr__" not in missing
    assert "  - attribute_descriptor __setattr__: AttributeMutationOperation" in owned
    assert "  - attribute_descriptor __delattr__" not in missing
    assert "  - attribute_descriptor __delattr__: AttributeDeleteOperation" in owned
    assert "  - attribute_descriptor __dir__" not in missing
    assert (
        "  - attribute_descriptor __dir__: BuiltinCallSugar._BUILTIN_DUNDER_METHODS"
        in owned
    )
    assert "  - attribute_descriptor __get__" not in missing
    assert "  - attribute_descriptor __get__: DescriptorOperation.__get__" in owned
    assert "  - attribute_descriptor __set__" not in missing
    assert "  - attribute_descriptor __set__: DescriptorOperation.__set__" in owned
    assert "  - attribute_descriptor __delete__" not in missing
    assert (
        "  - attribute_descriptor __delete__: DescriptorOperation.__delete__" in owned
    )
    assert "  - attribute_descriptor __set_name__" not in missing
    assert (
        "  - attribute_descriptor __set_name__: "
        "ConstructorStrategy.__set_name__ floor"
    ) in owned
    assert "  - context_async __enter__" not in missing
    assert "  - context_async __enter__: ContextManagerOperation" in owned
    assert "  - context_async __exit__" not in missing
    assert "  - context_async __exit__: ContextManagerOperation" in owned
    assert "  - context_async __aenter__" not in missing
    assert "  - context_async __aenter__: AsyncContextManagerOperation" in owned
    assert "  - context_async __aexit__" not in missing
    assert "  - context_async __aexit__: AsyncContextManagerOperation" in owned
    assert "  - context_async __await__" not in missing
    assert "  - context_async __await__: AwaitOperation" in owned
    assert "  - context_async __aiter__" not in missing
    assert "  - context_async __aiter__: AsyncIteratorOperation" in owned
    assert "  - context_async __anext__" not in missing
    assert "  - context_async __anext__: AsyncIteratorOperation" in owned
    assert "  - inplace_binary __iadd__" not in missing
    assert (
        "  - inplace_binary __iadd__: ObjectValue._INPLACE_BINARY_DUNDER_METHODS"
        in owned
    )
