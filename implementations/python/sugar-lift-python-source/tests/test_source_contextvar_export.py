"""A ContextVar a module builds in source, with ``default=``.

``numpy._core.printoptions`` binds ``format_options = ContextVar(
"format_options", default=...)``.  Two laws:

* ``ContextVar(name, *, default=...)`` constructs the language-owned
  ContextVar; ``default`` only changes ``get()``, which then never raises.
  Any other keyword stays loud.
* A module-level export bound exactly once to ``ContextVar(...)``, with
  ``ContextVar`` bound exactly once by ``from contextvars import ContextVar``,
  is that language-owned ContextVar (applied through the same constructor
  law).  ``get()`` on it returns the running context's value, which source
  never decides: one opaque read per occurrence.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedContextVarReadValue,
    LanguageOwnedContextVarType,
    LanguageOwnedContextVarValue,
)
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source.dependency_artifact import (
    authenticate_dependency_top_level,
)
from sugar_lift_python_source.dependency_export_adapter import resolve_export
from sugar_lift_python_source.language_owned_c_export import (
    floor_source_contextvar_export,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.panic import SugarNotWritten

from test_numpy_errstate_construction import _corpus, _with_resolution


def _construct(*arguments, keyword_names=()):
    return LanguageOwnedContextVarType().callable_application_with(
        CallableApplication(arguments, keyword_names, site="contextvar-site"), None
    )


def test_a_default_keyword_constructs_a_contextvar_whose_get_never_raises():
    outcome = _construct(StringValue("v"), TermValue(1), keyword_names=("default",))
    assert isinstance(outcome, Complete)
    assert outcome.value == LanguageOwnedContextVarValue(name="v", has_default=True)
    plain = _construct(StringValue("v"))
    assert plain.value.has_default is False


def test_another_keyword_stays_loud():
    with pytest.raises(SugarNotWritten):
        _construct(StringValue("v"), TermValue(1), keyword_names=("initial",))


def test_get_reads_one_opaque_value_per_occurrence_only_with_a_default():
    variable = LanguageOwnedContextVarValue(name="v", has_default=True)
    first = variable.call_method_with(
        SimpleNamespace(name="get", arguments=(), keyword_names=(), blame="a"), None
    )
    second = variable.call_method_with(
        SimpleNamespace(name="get", arguments=(), keyword_names=(), blame="b"), None
    )
    assert isinstance(first.value, LanguageOwnedContextVarReadValue)
    assert first.value != second.value
    assert isinstance(variable.attribute("get", "s"), Complete)
    no_default = LanguageOwnedContextVarValue(name="v")
    with pytest.raises(ConstructionPanic):
        no_default.attribute("get", "s")


def test_numpy_format_options_is_a_source_contextvar_with_a_default():
    graph = authenticate_dependency_top_level("numpy")
    session = SourceResolutionSession(enrolled_distributions=frozenset({"numpy"}))
    gap = resolve_export(
        graph,
        "bind-cid",
        "numpy._core.printoptions",
        "format_options",
        (),
        frozenset(),
        session=session,
    )
    assert gap.kind == "dynamic-export"
    assert floor_source_contextvar_export(gap, graph=graph) == (
        LanguageOwnedContextVarValue(name="format_options", has_default=True)
    )


def _floor(source, name="var"):
    graph = SimpleNamespace(modules={"m": SimpleNamespace(source=source)})
    gap = SimpleNamespace(kind="dynamic-export", module_name="m", exported_name=name)
    return floor_source_contextvar_export(gap, graph=graph)


def test_the_source_shape_is_exact():
    assert _floor("from contextvars import ContextVar\nvar = ContextVar('n')\n") == (
        LanguageOwnedContextVarValue(name="n")
    )
    assert _floor(
        "from contextvars import ContextVar as CV\nvar = CV('n', default=1)\n"
    ) == LanguageOwnedContextVarValue(name="n", has_default=True)


@pytest.mark.parametrize(
    "source",
    [
        # rebound later
        "from contextvars import ContextVar\nvar = ContextVar('n')\nvar = 1\n",
        # rebound through global
        "from contextvars import ContextVar\nvar = ContextVar('n')\n"
        "def f():\n    global var\n    var = 2\n",
        # ContextVar is not the contextvars class
        "from mylib import ContextVar\nvar = ContextVar('n')\n",
        # ContextVar rebound
        "from contextvars import ContextVar\nContextVar = dict\nvar = ContextVar('n')\n",
        # computed name
        "from contextvars import ContextVar\nvar = ContextVar(name)\n",
        # an unknown keyword
        "from contextvars import ContextVar\nvar = ContextVar('n', other=1)\n",
        # a ** spread
        "from contextvars import ContextVar\nvar = ContextVar('n', **kw)\n",
        # star import may rebind anything
        "from contextvars import ContextVar\nfrom x import *\nvar = ContextVar('n')\n",
    ],
)
def test_any_other_shape_keeps_the_gap(source):
    assert _floor(source) is None


def test_with_np_printoptions_now_resolves_its_generator_manager(tmp_path):
    root = _corpus(
        tmp_path,
        **{
            "e.py": (
                "import numpy as np\n"
                "def f():\n"
                "    with np.printoptions(precision=3):\n"
                "        return 1\n"
            )
        },
    )
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({"tiny-corpus", "numpy"})
    )
    ref = _with_resolution(root, "e.py", session=session)
    assert type(ref).__name__ == "SourceDerivedGeneratorResourceRefV1"
