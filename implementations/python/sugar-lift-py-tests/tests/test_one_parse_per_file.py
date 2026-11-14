"""One parse, one unit per file per session (#7757 item 5, follow-up to #8088).

The step-3 readers (the With rows and the lexical import pass) open a file
through the opener's first stage with no construction context, because their
rows are what the context's table is built from. The opener then opens the
same file under its context. Before this, the opener's open missed residency
(a different context) and parsed the file again: two parses, two units. Now
the opener attaches its context to the unit the readers parsed
(``SourceUnit.attach_construction_context``), once.

One entry (follow-up to #8098): residency is entered only through the
opener's first stage (``lift_rpc._open_at_seat``). A plain ``SourceFile(...)``
forwards to it and every production construction calls it, so a contextless
caller between the readers and the opener no longer costs a second parse.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc
from sugar_source_tree.nodes import SourceUnit
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.reporter import CollectingReporter

_PRODUCER = (
    "from contextlib import nullcontext\n"
    "\n"
    "\n"
    "def produce(carrier):\n"
    "    with nullcontext():\n"
    '        return carrier.mint(operator="floor_method")\n'
)


def _count_parses(monkeypatch: pytest.MonkeyPatch) -> list:
    bound: list = []
    original = SourceUnit.bind_typed_module

    def counted(self, module, **kwargs):
        bound.append(self.source_cid)
        return original(self, module, **kwargs)

    monkeypatch.setattr(SourceUnit, "bind_typed_module", counted)
    return bound


def test_the_readers_then_the_opener_parse_the_file_once_into_one_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sugar_lift_py_tests.import_binding import _run_lexical_import_pass

    path = tmp_path / "producer.py"
    path.write_text(_PRODUCER, encoding="utf-8")
    bound = _count_parses(monkeypatch)

    # Step 3: the With rows and the lexical import pass, through the first
    # stage with no context.
    rows = lift_rpc._context_manager_rows_for_paths([path], root=tmp_path)
    assert [row["kind"] for row in rows] == ["context-manager-demand"]
    source, _seat, source_cid = lift_rpc._read_at_seat(path, root=tmp_path)
    _run_lexical_import_pass(tmp_path, path, source, source_cid)
    read = lift_rpc._open_at_seat(path, root=tmp_path)
    assert read.unit.construction_context is None
    assert bound == [source_cid]

    opened = lift_rpc.open_source_file_for_construction(
        path, root=tmp_path, reporter=CollectingReporter()
    )

    assert bound == [source_cid], "the opener parsed the file a second time"
    assert opened is read
    assert opened.unit is read.unit
    assert opened.unit.construction_context is not None

    # A reader after the opener reads the opener's unit, and parses nothing.
    assert lift_rpc._open_at_seat(path, root=tmp_path).unit is opened.unit
    assert bound == [source_cid]


def test_the_context_a_caller_names_is_the_one_the_opener_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit leaf names the context; the enumerate levels do not. One open."""
    import sugar_lift_python_source.manager_summary_derivation as derivation

    path = tmp_path / "producer.py"
    path.write_text(_PRODUCER, encoding="utf-8")
    bound = _count_parses(monkeypatch)
    populated = []
    original_populate = derivation.populate_source_derived_resource_refs

    def counted_populate(source_file, **kwargs):
        populated.append(source_file.unit.filename)
        return original_populate(source_file, **kwargs)

    monkeypatch.setattr(
        derivation, "populate_source_derived_resource_refs", counted_populate
    )

    named = lift_rpc.construction_context_for_open(path, root=tmp_path)
    level = lift_rpc.open_source_file_for_construction(
        path, root=tmp_path, reporter=CollectingReporter()
    )
    leaf = lift_rpc.open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=named,
    )

    assert level.unit.construction_context is named
    assert leaf is level
    assert len(bound) == 1
    assert populated == ["producer.py"]


def test_a_plain_caller_between_the_readers_and_the_opener_costs_no_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A contextless caller that is not a step-3 reader picks the unit up
    first. Before, that cleared the waiting mark and the opener parsed its own
    copy: two parses, two units. Now every route is the one entry."""
    from sugar_lift_python_source.typed_node_api import parse
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / "producer.py"
    path.write_text(_PRODUCER, encoding="utf-8")
    bound = _count_parses(monkeypatch)

    read = lift_rpc._open_at_seat(path, root=tmp_path)
    identity = lift_rpc._read_at_seat(path, root=tmp_path)
    source, seat, source_cid = identity

    # Plain callers, in between: the class call and the typed parse.
    plain = SourceFile(identity)
    typed_root = parse(source, filename=seat)
    assert plain is read
    assert typed_root is read.root
    assert read.unit.construction_context is None

    opened = lift_rpc.open_source_file_for_construction(
        path, root=tmp_path, reporter=CollectingReporter()
    )

    assert bound == [source_cid], "the opener parsed the file a second time"
    assert opened is read
    assert opened.unit is read.unit
    assert opened.unit.construction_context is not None


_PACKAGES = ("sugar-source-tree", "sugar-lift-python-source", "sugar-lift-py-tests")
_SCANNED = ("src", "scripts")
# The one entry, and the residency door behind it.
_ENTRY = "_open_at_seat"
_RESIDENCY_DOOR = "_source_file_from_identity"
_UNCACHED_PREPARE = "_prepare_uncached"


def _python_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "python" and (parent / "sugar-source-tree").is_dir():
            return parent
    raise AssertionError(f"cannot locate implementations/python from {here}")


class _CallsByScope(ast.NodeVisitor):
    """Every call, with the name of the innermost function it is written in."""

    def __init__(self) -> None:
        self.scopes: list[str] = ["<module>"]
        self.calls: list[tuple[str, ast.Call]] = []

    def _scoped(self, node) -> None:
        self.scopes.append(node.name)
        self.generic_visit(node)
        self.scopes.pop()

    visit_FunctionDef = _scoped
    visit_AsyncFunctionDef = _scoped

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append((self.scopes[-1], node))
        self.generic_visit(node)


def _called_name(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _entry_offenders_in(text: str, *, where: str) -> list[str]:
    """Every construction of a ``SourceFile`` that is not the one entry."""
    visitor = _CallsByScope()
    visitor.visit(ast.parse(text, filename=where))
    found: list[str] = []
    for scope, call in visitor.calls:
        name = _called_name(call)
        if name in ("SourceFile", "source_file_from_identity"):
            found.append(f"{where}:{call.lineno} {scope}() calls {name}")
        elif name == _RESIDENCY_DOOR and scope != _ENTRY:
            found.append(f"{where}:{call.lineno} {scope}() calls {name}")
        elif name == _UNCACHED_PREPARE and scope != _RESIDENCY_DOOR:
            found.append(f"{where}:{call.lineno} {scope}() calls {name}")
    return found


def test_no_source_file_is_constructed_outside_the_one_entry() -> None:
    """THE LAW. In the three packages' ``src/`` and ``scripts/``, nothing calls
    ``SourceFile(...)`` and only ``_open_at_seat`` calls the residency door, so
    no caller can reach a resident unit except through the one entry."""
    root = _python_root()
    offenders: list[str] = []
    scanned = 0
    for package in _PACKAGES:
        for directory in _SCANNED:
            base = root / package / directory
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.py")):
                scanned += 1
                offenders.extend(
                    _entry_offenders_in(
                        path.read_text(encoding="utf-8"),
                        where=str(path.relative_to(root)),
                    )
                )
    assert scanned > 0, "the law scanned nothing"
    assert offenders == [], (
        "a SourceFile is constructed outside the one entry "
        "(lift_rpc._open_at_seat); route it through _open_at_seat, passing an "
        "identity already read as seated=:\n  " + "\n  ".join(offenders)
    )


def test_the_entry_law_can_fail() -> None:
    """A law that cannot fail proves nothing."""
    planted = (
        "def reader(identity):\n"
        "    return SourceFile(identity)\n"
        "def other(identity):\n"
        "    return _source_file_from_identity(identity)\n"
        "def prepare(identity):\n"
        "    return SourceFile._prepare_uncached(identity)\n"
    )
    assert len(_entry_offenders_in(planted, where="<planted>")) == 3

    clean = (
        "def _open_at_seat(path, *, root, seated=None):\n"
        "    return _source_file_from_identity(seated)\n"
        "def _source_file_from_identity(identity):\n"
        "    return SourceFile._prepare_uncached(identity)\n"
        "def reader(path, root):\n"
        "    return _open_at_seat(path, root=root)\n"
    )
    assert _entry_offenders_in(clean, where="<clean>") == []


def test_the_waiting_mark_and_the_public_residency_door_are_gone() -> None:
    import sugar_source_tree.process_resident_file as residency

    assert not hasattr(residency, "source_file_from_identity")
    assert not hasattr(residency, "AWAITING_CONSTRUCTION_CONTEXT")
    assert "awaits_context" not in {
        field.name
        for field in residency.ProcessResidentFileContext.__dataclass_fields__.values()
    }


def test_a_unit_with_a_context_is_never_given_another(tmp_path: Path) -> None:
    """The slot is written once (#7772)."""
    path = tmp_path / "producer.py"
    path.write_text(_PRODUCER, encoding="utf-8")
    opened = lift_rpc.open_source_file_for_construction(path, root=tmp_path)
    context = opened.unit.construction_context

    with pytest.raises(BackendDefect):
        opened.unit.attach_construction_context(object())
    assert opened.unit.construction_context is context
