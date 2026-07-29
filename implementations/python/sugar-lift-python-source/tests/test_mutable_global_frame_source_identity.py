from dataclasses import replace

import pytest

from sugar_lift_py_tests.source_call_frame import (
    MutableGlobalBindingV1,
    SourceCallBindingGap,
)
from sugar_lift_python_source.value_pins import scan_module_value_pins
from sugar_source_tree import SourceFile


def _source(tmp_path, name, *, key="OPTIONS"):
    path = tmp_path / name
    path.write_text(f"{key} = {{}}\n\ndef selected():\n    return {key}\n")
    return SourceFile.from_path(path)


def _binding(source_file):
    pin, = scan_module_value_pins(source_file.root).mutable_global_pins
    return MutableGlobalBindingV1(
        source_cid=pin.source_cid,
        binding_occurrence=pin.binding_occurrence,
        name=pin.name,
        kind=pin.kind,
        term=pin.term,
        line=pin.line,
        col=pin.col,
    )


def test_source_frame_accepts_its_exact_mutable_global_binding(tmp_path):
    source_file = _source(tmp_path, "truth.py")
    function, = source_file.functions()
    binding = _binding(source_file)

    frame = replace(
        function.source_visible_call_frame(),
        mutable_global_bindings=(binding,),
    )

    assert frame.mutable_global_bindings == (binding,)
    assert frame.mutable_global_bindings[0] is binding


def test_source_frame_refuses_foreign_mutable_global_before_frame_cid(tmp_path):
    local = _source(tmp_path, "local.py")
    foreign = _source(tmp_path, "foreign.py", key="FOREIGN_OPTIONS")
    function, = local.functions()
    foreign_binding = _binding(foreign)

    with pytest.raises(SourceCallBindingGap, match="foreign mutable-global source"):
        replace(
            function.source_visible_call_frame(),
            mutable_global_bindings=(foreign_binding,),
        )
