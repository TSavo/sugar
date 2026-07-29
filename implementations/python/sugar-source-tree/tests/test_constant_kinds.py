"""The remaining Constant literal kinds: bytes, complex, Ellipsis.

bytes and Ellipsis both have a canonical floor representation already
consumed downstream (SMT emitter / verifier ground-ctor whitelist /
isinstance fold table), so they lift. complex ALSO has an established
canonical ``py.complex(<real>, <imag>)`` representation in that same
whitelist and fold table, so it lifts too -- this is not a new vocabulary
decision, it mirrors vocabulary already agreed elsewhere in the kit.
"""

from dataclasses import replace
import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.sugar.bytes_literal_sugar import BytesLiteralSugar
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _return_value(src):
    """desugar `def A(): return <expr>` and return the floor value."""
    return _fn(src).sugar().desugar().value.post().args[1]


def test_bytes_literal_lifts_to_canonical_python_bytes_term():
    term = _return_value('def A():\n    return b"ab"\n')
    assert term.name == "python:bytes"
    assert len(term.args) == 1
    assert term.args[0].value == b"ab".hex()


def test_bytes_literal_discriminates_on_content():
    ab = _return_value('def A():\n    return b"ab"\n')
    ac = _return_value('def A():\n    return b"ac"\n')
    assert ab != ac


def test_bytes_literal_is_an_authenticated_call_operand():
    function = _fn('def A():\n    return sink(b"ab")\n')
    call = next(node for node in function.walk() if node.kind == "Call")

    constructed = call.sugar()

    assert isinstance(constructed, CallSiteSugar)
    assert isinstance(constructed.args[0], BytesLiteralSugar)
    constructed.args[0].to_term(owner="bytes call operand")
    with pytest.raises(
        TypeError,
        match="requires an authenticated source occurrence for BytesLiteralSugar",
    ):
        replace(constructed.args[0], site=object()).to_term(owner="foreign bytes")

    integer_call = next(
        node
        for node in _fn("def A():\n    return sink(1)\n").walk()
        if node.kind == "Call"
    )
    assert isinstance(integer_call.sugar(), CallSiteSugar)


def test_ellipsis_literal_lifts_to_canonical_py_ellipsis_term():
    term = _return_value("def A():\n    return ...\n")
    assert term.name == "py.ellipsis"
    assert term.args == ()


def test_complex_literal_lifts_to_canonical_py_complex_term():
    term = _return_value("def A():\n    return 2j\n")
    assert term.name == "py.complex"
    assert len(term.args) == 2


def test_complex_literal_discriminates_on_imaginary_part():
    two_j = _return_value("def A():\n    return 2j\n")
    three_j = _return_value("def A():\n    return 3j\n")
    assert two_j != three_j


if __name__ == "__main__":
    test_bytes_literal_lifts_to_canonical_python_bytes_term()
    test_bytes_literal_discriminates_on_content()
    test_ellipsis_literal_lifts_to_canonical_py_ellipsis_term()
    test_complex_literal_lifts_to_canonical_py_complex_term()
    test_complex_literal_discriminates_on_imaginary_part()
    print("ok: bytes / Ellipsis / complex literal kinds")
