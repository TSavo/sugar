"""An import-bound callee head is a CLOSED coordinate, never a free Var.

`np.rot90(m)` under `import numpy as np` is not a method call on a value: `np`
is a lexical import binding, so the callee names the closed coordinate
`numpy.rot90`. Constructing the head as a receiver minted `np` as a universe
Var that no contract ever declared, and `ScopedFormula` refused it (correctly)
with `illegal free var(s): np`.

The binding comes from the ONE lexical import pass (reaching definitions in
``import_binding``), never from spelling. So the discrimination arm matters as
much as the positive one: a head that is NOT uniquely import-bound -- a plain
undeclared global, a shadowed alias -- must still mint its Var and must still
trip the same panic. A fix that silences that case has broken the detector.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile

from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.proofir.formulas import formula_from_ir
from sugar_lift_py_tests.proofir.scope import ScopedFormula
from sugar_lift_py_tests.proofir.sorts import UnknownSort


def _post(source: str):
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "m.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    function = next(iter(SourceFile(path_source(path)).functions()))
    return function.sugar().desugar(None).value.post()


def _scoped(post, formals: tuple[str, ...]) -> ScopedFormula:
    sort = UnknownSort(reason="lift is sort-silent; the compiler decides")
    allowed = {name: sort for name in (*formals, "out")}
    return ScopedFormula(formula_from_ir(post, var_sorts=allowed), allowed_vars=allowed)


def test_module_alias_call_head_projects_a_closed_coordinate() -> None:
    post = _post("import numpy as np\n\n\ndef turn(m):\n    return np.rot90(m)\n")
    assert post.args[1].name == "call:numpy.rot90"
    scoped = _scoped(post, ("m",))
    assert scoped.formula.free_vars == {"m", "out"}


def test_dotted_import_head_closes_the_whole_chain() -> None:
    # `os.path.join` -- the same gap shape the pandas census catalogues with
    # `os` (docs/audits/pandas-gap-census.md, pandas-gap-21).
    post = _post("import os\n\n\ndef j(a, b):\n    return os.path.join(a, b)\n")
    assert post.args[1].name == "call:os.path.join"
    assert _scoped(post, ("a", "b")).formula.free_vars == {"a", "b", "out"}


def test_from_import_module_binding_closes_too() -> None:
    post = _post(
        "from numpy import testing as t\n\n\ndef e(a, b):\n"
        "    return t.assert_equal(a, b)\n"
    )
    assert post.args[1].name == "call:numpy.testing.assert_equal"


def test_showcase_shape_binds_through_the_local_assignment() -> None:
    post = _post(
        "import numpy as np\n\n\ndef test_rot90_quarter_turn():\n"
        "    r = np.rot90([[1, 2], [3, 4]])\n    return r[0][0]\n"
    )
    assert _scoped(post, ()).formula.free_vars == {"out"}


def test_a_head_that_is_not_import_bound_still_refuses_scope() -> None:
    # THE DISCRIMINATION. `zz` is bound by nothing: it must still mint a Var
    # and ScopedFormula must still refuse the undeclared free var.
    post = _post("def turn(m):\n    return zz.rot90(m)\n")
    with pytest.raises(ConstructionPanic, match="illegal free var.*zz"):
        _scoped(post, ("m",))


def test_a_shadowed_import_alias_is_not_import_bound() -> None:
    # The alias is rebound before the use, so the reaching definition is no
    # longer the import: the head constructs as an ordinary receiver.
    post = _post(
        "import numpy as np\n\n\ndef turn(m):\n    np = m\n    return np.rot90(m)\n"
    )
    assert post.args[1].name == "call:rot90"


def test_a_parameter_method_call_is_untouched() -> None:
    post = _post("def turn(m):\n    return m.copy()\n")
    assert post.args[1].name == "call:copy"
    assert _scoped(post, ("m",)).formula.free_vars == {"m", "out"}
