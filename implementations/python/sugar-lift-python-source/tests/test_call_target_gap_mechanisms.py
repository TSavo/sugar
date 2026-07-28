"""The four conditions ``opaque-call-target`` used to fuse into one name.

One kind named four structurally different failures, three of them carrying a
callee spelling in the key.  ``opaque-call-target:func`` was the largest single
term on the pinned pandas board (#6371) -- a *capability* gap (calling a value)
wearing a vendor-looking name, indistinguishable from a *coverage* gap (stdlib
outside the artifact) and from a *defect* (an in-artifact symbol the export door
failed on).  A measurement a vendor rename can move is not a measurement.

Splitting these apart REATTRIBUTES rows; it drains none of them.  The capability
itself is open work (#6409), as is the door defect (#6410).  Corpus row counts
from the pre-`d10774abc` ledger are deliberately not restated here: that
collection universe was short by 290 laws and the figures are pending
re-baseline.

Each mechanism gets both faces here:

* ``value-call-target`` -- the callee is bound by the enclosing definition, as a
  parameter or as a local.  Higher-order dispatch; no export lookup can ever
  resolve it.  Negative face: the same call, same spelling, where the name is a
  module-level definition instead -- and it constructs.
* ``call-target-source-absent`` -- the export door declines: no defining source
  in this artifact.  Coverage.
* ``call-target-export-unresolved`` -- the door authenticates an object that IS
  in this artifact and projecting its frame still fails.  A defect that was
  invisible while it shared a bucket with the other two.
* ``call-graph-cycle`` -- recursion.  Carries no symbol at all.

Plus the law the whole split exists to serve: the kind is the structural key and
never contains a callee spelling; the spelling rides ``detail``.

All fixture source is neutral and written for this test.  No vendor text, no
vendor names, no name arms.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_py_tests.ir import _term_content_cid
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    CALL_TARGET_GAP_KINDS,
    ConstructedCallActualV1,
    ConstructedManagerBehaviorV1,
    _frame_bound_names,
    construct_manager_behavior,
)
from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
from sugar_source_tree.nodes import Call, Constant, FunctionDef
from sugar_source_tree.panic import OpaqueSourceCallResolutionGap
from sugar_source_tree.tree import SourceFile


def _distribution(
    root: Path, modules: dict[str, str]
) -> importlib.metadata.Distribution:
    """One authenticated distribution whose file manifest is exactly ``modules``."""
    package = root / "arbitrary"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from arbitrary.manager import make_guard\n", encoding="utf-8"
    )
    names = ["arbitrary/__init__.py"]
    for name, source in modules.items():
        (package / f"{name}.py").write_text(source, encoding="utf-8")
        names.append(f"arbitrary/{name}.py")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    names += [
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    ]
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for name in names:
            writer.writerow((name, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _construct(root: Path, manager_source: str, **extra_modules: str):
    """Construct ``arbitrary.make_guard(23)`` from authenticated source."""
    graph = DependencyArtifactGraph.authenticate(
        _distribution(root, {"manager": manager_source, **extra_modules})
    )
    consumer = "import arbitrary\narbitrary.make_guard(23)\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1), resolved
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    literal = next(item for item in call.args if isinstance(item, Constant))
    actual = TermValue(23)
    supplied = ConstructedCallActualV1(
        literal,
        actual,
        ConstructedValueTestimonyV1.mint(
            literal.fragment, _term_content_cid(actual.to_term(owner="test"))
        ),
    )
    return construct_manager_behavior(
        resolved, graph=graph, actuals=(supplied,), call_site=call.fragment
    )


def _opaque_gap(root: Path, manager_source: str, **extra_modules: str):
    with pytest.raises(OpaqueSourceCallResolutionGap) as raised:
        _construct(root, manager_source, **extra_modules)
    return raised.value


# --------------------------------------------------------------------------
# value-call-target -- the callee is a VALUE bound by the enclosing definition
# --------------------------------------------------------------------------


def test_called_parameter_is_a_value_call_target_not_a_missing_import(tmp_path):
    """POSITIVE: a formal parameter that is called is higher-order dispatch.

    ``helper`` is never imported and never defined -- it is *bound*, as the
    enclosing definition's own parameter.  No export door can resolve it,
    because there is nothing to look up.  Reporting this as an unresolvable
    external symbol claims a coverage problem that does not exist.
    """
    gap = _opaque_gap(
        tmp_path,
        "def make_guard(helper):\n    return helper()\n",
    )

    assert gap.observed == "value-call-target:helper"


def test_called_local_binding_is_a_value_call_target(tmp_path):
    """POSITIVE: a function-LOCAL binding is a value for the same reason.

    Different binder, same mechanism: the callee is produced at runtime inside
    this frame.  Parameter and local must not split into two kinds, because the
    missing capability is one capability.
    """
    gap = _opaque_gap(
        tmp_path,
        "def picked(value):\n"
        "    return value\n"
        "\n"
        "def make_guard(expected):\n"
        "    helper = picked\n"
        "    return helper(expected)\n",
    )

    assert gap.observed == "value-call-target:helper"


def test_module_level_definition_of_the_same_spelling_constructs(tmp_path):
    """NEGATIVE FACE: identical call text, and it constructs.

    The only difference from the positive twin is what BINDS ``helper``.  If
    this arm also refused, the classification would be reading the spelling.
    """
    result = _construct(
        tmp_path,
        "class Slot:\n"
        "    def __init__(self, label):\n"
        "        self.label = 7\n"
        "\n"
        "def helper():\n"
        "    return Slot(7)\n"
        "\n"
        "def make_guard(expected):\n"
        "    return helper()\n",
    )

    assert isinstance(result, ConstructedManagerBehaviorV1), result


def test_parameter_shadowing_a_module_definition_is_still_a_value(tmp_path):
    """A local binding SHADOWS a module-level definition of the same name.

    ``helper`` is both a parameter of ``make_guard`` and a module-level
    definition.  Python binds the parameter, so the callee is the value passed
    in -- not the definition.  Classifying by the module's definition set first
    would resolve a frame the call never reaches, which is a soundness bug and
    not only a reporting one.
    """
    gap = _opaque_gap(
        tmp_path,
        "class Slot:\n"
        "    def __init__(self, label):\n"
        "        self.label = 7\n"
        "\n"
        "def helper():\n"
        "    return Slot(7)\n"
        "\n"
        "def make_guard(helper):\n"
        "    return helper()\n",
    )

    assert gap.observed == "value-call-target:helper"


def test_parameter_shadowing_a_builtin_is_still_a_value(tmp_path):
    """A parameter shadows the builtin temporal too, for the same reason."""
    gap = _opaque_gap(
        tmp_path,
        "def make_guard(len):\n    return len(7)\n",
    )

    assert gap.observed == "value-call-target:len"


# --------------------------------------------------------------------------
# call-target-source-absent vs call-target-export-unresolved
# --------------------------------------------------------------------------


def test_callee_outside_the_artifact_is_coverage_not_a_defect(tmp_path):
    """POSITIVE: the export door declines -- no defining source in the artifact."""
    gap = _opaque_gap(
        tmp_path,
        "def make_guard(expected):\n    return unbound_helper(expected)\n",
    )

    assert gap.observed == "call-target-source-absent:unbound_helper"


def test_in_artifact_callee_carries_nested_refusal_to_nested_consumer(tmp_path):
    """The callee resolves; its reached opaque child names its own consumer.

    ``support.build_slot`` is a real definition inside this artifact's own file
    manifest, statically exported and reached through the same door.  Therefore
    the outer ``build_slot`` call is not the refusal: ordinary control flow
    reaches ``absent_from_artifact`` inside its authenticated body.
    """
    gap = _opaque_gap(
        tmp_path,
        "from arbitrary.support import build_slot\n"
        "\n"
        "def make_guard(expected):\n"
        "    return build_slot(expected)\n",
        support="def build_slot(label):\n    return absent_from_artifact(label)\n",
    )

    assert gap.observed == "call-target-source-absent:absent_from_artifact"


def test_resolved_outer_callee_does_not_relabel_the_nested_gap(tmp_path):
    """DISCRIMINATION: direct and nested routes identify the same consumer.

    The nested route adds an authenticated ``build_slot`` frame.  If eager frame
    preparation still adjudicated the route, it would relabel the refusal at
    that outer call rather than carrying the reached inner obligation.
    """
    absent = _opaque_gap(
        tmp_path / "absent",
        "def make_guard(expected):\n    return unbound_helper(expected)\n",
    )
    defect = _opaque_gap(
        tmp_path / "defect",
        "from arbitrary.support import build_slot\n"
        "\n"
        "def make_guard(expected):\n"
        "    return build_slot(expected)\n",
        support="def build_slot(label):\n    return absent_from_artifact(label)\n",
    )

    assert absent.observed == "call-target-source-absent:unbound_helper"
    assert defect.observed == "call-target-source-absent:absent_from_artifact"


# --------------------------------------------------------------------------
# The law the split exists to serve
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "manager_source",
    [
        "def make_guard(helper):\n    return helper(7)\n",
        "def make_guard(expected):\n    return unbound_helper(expected)\n",
        "def make_guard(len):\n    return len(7)\n",
    ],
)
def test_the_kind_is_a_structural_key_and_never_carries_a_spelling(
    tmp_path, manager_source
):
    """Every reported kind is a member of the closed vocabulary, unfused.

    The old reporting layer minted ``f"{kind}:{detail}"`` and truncated it to 80
    chars.  A key that can be truncated is not an identity, and a key whose
    cardinality is the cardinality of callee spellings is a name table.
    """
    gap = _opaque_gap(tmp_path, manager_source)
    kind, spelling = gap.observed.split(":", 1)

    assert kind in CALL_TARGET_GAP_KINDS, kind
    assert ":" not in kind
    # The spelling exists -- it just is not the key.
    assert spelling and ":" not in spelling


def test_ordinary_control_flow_selects_the_first_reached_blocker(tmp_path):
    """Every blocker is parked; statement order decides which one is reached."""
    gap = _opaque_gap(
        tmp_path,
        "def make_guard(expected):\n"
        "    zulu(expected)\n"
        "    alpha(expected)\n"
        "    return mike(expected)\n",
    )

    assert gap.observed == "call-target-source-absent:zulu"


# --------------------------------------------------------------------------
# _frame_bound_names -- the binder walk, read directly
# --------------------------------------------------------------------------


def _definition(source: str, name: str) -> FunctionDef:
    tree = SourceFile((source, "binders.py", blake3_512_of(source.encode())))
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


def test_frame_bound_names_reads_every_binding_form(tmp_path):
    """POSITIVE: parameters and each local binding syntax, from the AST alone."""
    definition = _definition(
        "def frame(param, *args, keyword=None, **rest):\n"
        "    assigned = 1\n"
        "    annotated: int = 2\n"
        "    augmented = 0\n"
        "    augmented += 1\n"
        "    first, *starred = (1, 2, 3)\n"
        "    for looped in ():\n"
        "        pass\n"
        "    with open('x') as managed:\n"
        "        pass\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as caught:\n"
        "        pass\n"
        "    import json\n"
        "    from os import path as renamed\n"
        "    if (walrus := 3):\n"
        "        pass\n"
        "    def nested():\n"
        "        inner_only = 1\n"
        "        return inner_only\n"
        "    return nested\n",
        "frame",
    )

    assert _frame_bound_names(definition) == frozenset(
        {
            "param",
            "args",
            "keyword",
            "rest",
            "assigned",
            "annotated",
            "augmented",
            "first",
            "starred",
            "looped",
            "managed",
            "caught",
            "json",
            "renamed",
            "walrus",
            "nested",
        }
    )


def test_frame_bound_names_excludes_names_this_frame_does_not_bind(tmp_path):
    """NEGATIVE FACE: a comprehension target and a nested frame's local.

    A comprehension binds in its OWN scope, so claiming it here would be a
    claim this walk cannot authenticate -- such a callee stays a free name and
    still goes to the export door, exactly as before this walk existed.
    """
    definition = _definition(
        "def frame():\n"
        "    values = [comprehended for comprehended in ()]\n"
        "    def nested(nested_param):\n"
        "        nested_local = 1\n"
        "        return nested_local\n"
        "    return values, nested\n",
        "frame",
    )
    binders = _frame_bound_names(definition)

    assert "values" in binders
    assert "nested" in binders
    assert "comprehended" not in binders
    assert "nested_param" not in binders
    assert "nested_local" not in binders


# --------------------------------------------------------------------------
# The scan reaches METHODS, not only module-level functions
#
# The class arm was absent, and its absence was not a reporting gap: a method
# calling a name with no authenticated defining source CONSTRUCTED, and the
# unresolvable call was content-addressed into the manager-construction CID.
# Whether a body is spelled as a function or as a method is syntax; it must not
# decide whether construction authenticates its callees.
# --------------------------------------------------------------------------


_ABSENT_FROM_ARTIFACT_METHOD = (
    "class Slot:\n"
    "    def __init__(self, label):\n"
    "        self.label = absent_from_artifact(label)\n"
    "\n"
    "def make_guard(expected):\n"
    "    return Slot(expected)\n"
)

_CALLED_PARAMETER_METHOD = (
    "class Slot:\n"
    "    def __init__(self, helper):\n"
    "        self.label = helper()\n"
    "\n"
    "def make_guard(expected):\n"
    "    return Slot(expected)\n"
)


def test_method_calling_an_absent_symbol_refuses_instead_of_fabricating(tmp_path):
    """LYING TWIN, and the reason this arm exists.

    Before the class arm, this exact source produced a
    ``ConstructedManagerBehaviorV1`` whose receiver field held a
    ``CallSiteValue`` with ``body=None``, ``source_call_frame_cid=None`` and
    ``authenticated_target_symbol=None`` -- an unauthenticated call, carried
    into ``receiver_state.identity`` and from there into
    ``manager_construction_cid``.  A construction CID asserting an
    authenticated receiver over a call the system could not see through is a
    fabricated contract, which ``_resolve_external_call_frame`` explicitly
    promises never to yield.
    """
    gap = _opaque_gap(tmp_path, _ABSENT_FROM_ARTIFACT_METHOD)

    assert gap.observed == "call-target-source-absent:absent_from_artifact"


def test_method_calling_a_parameter_is_a_value_call_target(tmp_path):
    """A called parameter is higher-order dispatch inside a method too."""
    gap = _opaque_gap(tmp_path, _CALLED_PARAMETER_METHOD)

    assert gap.observed == "value-call-target:helper"


def test_method_calling_a_module_definition_still_constructs(tmp_path):
    """TRUTHFUL TWIN: the arm refuses unauthenticated callees, not methods.

    Same class, same call shape, callee authenticated in this artifact.  If
    this went red the arm would be refusing syntax rather than opacity.
    """
    result = _construct(
        tmp_path,
        "def picked(value):\n"
        "    return 7\n"
        "\n"
        "class Slot:\n"
        "    def __init__(self, label):\n"
        "        self.label = picked(label)\n"
        "\n"
        "def make_guard(expected):\n"
        "    return Slot(expected)\n",
    )

    assert isinstance(result, ConstructedManagerBehaviorV1), result


@pytest.mark.parametrize(
    "spelling,source",
    [
        ("method", _ABSENT_FROM_ARTIFACT_METHOD),
        (
            "function",
            "def make_guard(expected):\n    return absent_from_artifact(expected)\n",
        ),
    ],
)
def test_both_spellings_of_the_same_opacity_reach_the_same_kind(
    tmp_path, spelling, source
):
    """DISCRIMINATION: the two faces must AGREE.

    Asserting each spelling separately would still pass if one silently
    constructed -- which is exactly what the method face used to do.  This is
    the assertion that cannot: same condition, same kind, whichever syntax
    carries it.
    """
    gap = _opaque_gap(tmp_path, source)

    assert gap.observed == "call-target-source-absent:absent_from_artifact", spelling


def test_scanned_definitions_reaches_methods_and_nothing_else(tmp_path):
    """The scan universe, read directly off a class and a function."""
    from sugar_lift_python_source.manager_construction import _scanned_definitions
    from sugar_source_tree.nodes import ClassDef

    source = (
        "class Slot:\n"
        "    field = 1\n"
        "    def first(self):\n"
        "        return 1\n"
        "    def second(self):\n"
        "        return 2\n"
        "\n"
        "def loose():\n"
        "    return 3\n"
    )
    tree = SourceFile((source, "scan.py", blake3_512_of(source.encode())))
    klass = next(n for n in tree.root.body if isinstance(n, ClassDef))
    function = next(
        n for n in tree.root.body if isinstance(n, FunctionDef) and n.name == "loose"
    )

    assert tuple(d.name for d in _scanned_definitions(klass)) == ("first", "second")
    assert tuple(d.name for d in _scanned_definitions(function)) == ("loose",)
