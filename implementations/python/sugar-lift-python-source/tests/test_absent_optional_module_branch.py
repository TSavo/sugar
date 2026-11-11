"""A ``with`` under a branch an absent optional module never selects (#7665).

``pandas.io.common._get_binary_io_classes`` reads::

    zstd = import_optional_dependency("zstandard", errors="ignore")
    if zstd is not None:
        with zstd.ZstdDecompressor().stream_reader(b"") as reader:
            ...

zstandard is not installed in the pinned environment, so ``import_module``
raises ``ModuleNotFoundError``, the helper returns ``None`` and the suite is
dead.  Three laws carry that:

- ``importlib.import_module(<constant top-level name>)`` halts with
  ``ModuleNotFoundError`` when the pinned interpreter's finders have no such
  module (a present module keeps the two-faced off-population call);
- a ``with`` in a branch suite constructs when its suite is reduced, so a suite
  a ground condition never selects never demands its manager contract;
- a reached ``with`` still constructs only through the require door (a
  present off-population module's chain is cited, #7742).
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.source_call_resolution import pinned_absent_top_level_module

from test_contextmanager_generator_protocol import _function_rows, _imported

_ABSENT = "zz_sugar_absent_module_7665"

_IMPL = (
    "import importlib\n"
    "def opt(name):\n"
    "    try:\n"
    "        module = importlib.import_module(name)\n"
    "    except ImportError:\n"
    "        return None\n"
    "    return module\n"
    "def helper():\n"
    "    z = opt({name!r})\n"
    "    if z is not None:\n"
    "        with z.D().r(b'') as reader:\n"
    "            pass\n"
    "    return 1\n"
    "class M:\n"
    "    def __enter__(self):\n"
    "        helper()\n"
    "        return 1\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
    "def cm():\n"
    "    return M()\n"
)

_RAISE_IMPL = _IMPL.replace(
    "        with z.D().r(b'') as reader:\n            pass\n",
    "        raise KeyError(1)\n",
)


def test_absence_is_read_from_the_pinned_finders_without_importing():
    assert pinned_absent_top_level_module(_ABSENT)
    assert not pinned_absent_top_level_module("json")
    assert not pinned_absent_top_level_module("os.path")  # dotted: not asked
    assert not pinned_absent_top_level_module("")
    assert not pinned_absent_top_level_module(None)


def test_absent_module_import_halts_so_its_suite_is_dead(tmp_path: Path) -> None:
    tree, with_node = _imported(
        tmp_path, _RAISE_IMPL.format(name=_ABSENT), "pass", contextlib_enrolled=False
    )
    _consumer, rows = _function_rows(tree, with_node)
    assert rows == [("return", 7)]


def test_a_with_in_a_dead_suite_never_demands_its_manager(tmp_path: Path) -> None:
    tree, with_node = _imported(
        tmp_path, _IMPL.format(name=_ABSENT), "pass", contextlib_enrolled=False
    )
    _consumer, rows = _function_rows(tree, with_node)
    assert rows == [("return", 7)]


def test_a_present_module_keeps_the_with_demanded(tmp_path: Path) -> None:
    # json is installed: the suite may run, so its with must still construct
    # through the require door.  import_module completes with the module
    # (#7742) and json is off the enrolled population, so the manager
    # ``z.D().r(b'')`` produces is cited (never read, never dropped): the
    # helper reduces, and the with's opaque faces are on it.
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset
    from sugar_source_tree.nodes import FunctionDef

    tree, _with_node = _imported(
        tmp_path, _IMPL.format(name="json"), "pass", contextlib_enrolled=False
    )
    func = next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    exits = outcome_to_exitset(func.sugar().desugar()).exits
    owners = {
        getattr(face.effect, "producer_node_owner", None)
        for face in exits
        if isinstance(face, Halted)
    }
    assert exits
    assert not any("CONTEXT MANAGER RESOLUTION GAP" in str(o) for o in owners)
