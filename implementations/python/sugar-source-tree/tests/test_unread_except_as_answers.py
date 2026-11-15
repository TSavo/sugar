"""An ``except ... as`` name no read reaches answers the roll where its
binding is minted (#7757).

A handler binds its ``as`` name to its effect slot (``EffectRef``,
``ExceptHandler.substitute``, ``Try``'s handler scope).  A name the handler
never reads (``except (TypeError, ValueError) as _: return False``,
``plotting/_matplotlib/core.py:1449``) left that binding built by nothing and
registered: the file ended in ``EffectRef registered but never answered the
roll call`` on the pandas board at ``d54a43717`` (run 43739300912).  It now
answers where it is minted (``_minted_binding_reference``), as a ``with ...
as _`` name's ``ObservationRef`` does; a read that reaches it builds it.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _report(source: str):
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(source)
    f.close()
    return discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def test_an_unread_except_as_name_leaves_nothing_unanswered():
    report = _report(
        "def f(g):\n    try:\n        g()\n        return True\n"
        "    except (TypeError, ValueError) as _:\n        return False\n"
    )
    assert not [e for e in report.minority if e.kind == "EffectRef"], report.minority
