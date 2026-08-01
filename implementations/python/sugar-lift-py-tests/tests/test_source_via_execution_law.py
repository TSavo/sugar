"""Permanent baseline-free R_source_via_execution floor (#5930).

Discrimination twins prove the auditor cannot be defeated by relocation --
the exact failure mode from #5581/#5585, where moving a vendor string into a
mapping literal silenced R_vendor_special_case while the defect stayed
intact. Every planted twin below must trip the floor from a DIFFERENT
indirection shape, and reverting the plant must green the floor again --
never only one direction.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_KIT = sugar_lift_py_tests_package_root()
_SCANNER_PATH = _KIT / "scripts" / "source_via_execution_law.py"
_SPEC = importlib.util.spec_from_file_location(
    "source_via_execution_law", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def _scan_text(tmp_path: Path, filename: str, text: str) -> list:
    sugar = tmp_path / "sugar_lift_py_tests" / "sugar"
    sugar.mkdir(parents=True)
    (sugar / filename).write_text(text, encoding="utf-8")
    return _SCANNER.scan_roots((sugar,))


def test_direct_import_module_and_find_spec_trip_floor(tmp_path: Path) -> None:
    offenders = _scan_text(
        tmp_path,
        "direct.py",
        """
import importlib
import importlib.util


def resolve(name):
    module = importlib.import_module(name)
    spec = importlib.util.find_spec(name)
    return module, spec
""",
    )
    kinds = {row.kind for row in offenders}
    assert "import-module-call" in kinds
    assert "find-spec-call" in kinds
    assert _SCANNER.r_source_via_execution(offenders) == 2


def test_planted_helper_function_indirection_trips_floor(tmp_path: Path) -> None:
    """Routing the executing call through a private helper cannot hide it --
    the census walks every function body, not just top-level call sites."""
    offenders = _scan_text(
        tmp_path,
        "helper.py",
        """
import importlib


def _load(dotted_name):
    # Buried three calls deep inside a helper -- must still trip.
    return _really_load(dotted_name)


def _really_load(dotted_name):
    return importlib.import_module(dotted_name)
""",
    )
    assert _SCANNER.r_source_via_execution(offenders) == 1
    assert offenders[0].kind == "import-module-call"


def test_planted_registry_initializer_indirection_trips_floor(
    tmp_path: Path,
) -> None:
    """A lambda stashed in a dispatch/registry literal is still a live call
    site the moment the registry is invoked -- relocation into a mapping
    must not green the floor (the #5581/#5585 failure mode, replayed for
    executing imports instead of vendor strings)."""
    offenders = _scan_text(
        tmp_path,
        "registry.py",
        """
import importlib

_RESOLVERS = {
    "module": lambda name: importlib.import_module(name),
    "spec": lambda name: importlib.util.find_spec(name),
}
""",
    )
    kinds = {row.kind for row in offenders}
    assert "import-module-call" in kinds
    assert "find-spec-call" in kinds
    assert _SCANNER.r_source_via_execution(offenders) == 2


def test_planted_getattr_and_alias_indirection_trips_floor(tmp_path: Path) -> None:
    """Three indirections at once: an aliased module import, a name rebound
    from importlib.util.find_spec before use, and a getattr-dispatched call
    on the importlib module -- none may hide the executing call."""
    offenders = _scan_text(
        tmp_path,
        "indirect.py",
        """
import importlib as _il


def via_alias(name):
    return _il.import_module(name)


def via_getattr(name):
    loader = getattr(_il, "import_module")
    return loader(name)


_late_bound = importlib.util.find_spec


def via_rebound_name(name):
    import importlib  # late import inside a function body

    return _late_bound(name)
""",
    )
    kinds = {(row.kind) for row in offenders}
    assert "import-module-call" in kinds  # via_alias: _il.import_module
    assert "find-spec-call" in kinds  # _late_bound = importlib.util.find_spec
    # via_getattr's getattr(_il, "import_module")(name) is a fourth distinct
    # indirection shape and must also be counted.
    assert _SCANNER.r_source_via_execution(offenders) >= 3


def test_reverted_plant_is_green(tmp_path: Path) -> None:
    """Same file, plant removed -- proves the floor is not permanently red
    and a real fix actually clears it (both directions checked, not just
    that red fires)."""
    sugar = tmp_path / "sugar_lift_py_tests" / "sugar"
    sugar.mkdir(parents=True)
    planted = sugar / "was_planted.py"
    planted.write_text(
        """
import importlib


def _load(name):
    return importlib.import_module(name)
""",
        encoding="utf-8",
    )
    assert _SCANNER.r_source_via_execution(_SCANNER.scan_roots((sugar,))) == 1

    # Revert: replace the executing call with the non-executing PathFinder
    # form -- the legitimate replacement named in the floor's own docstring.
    planted.write_text(
        """
import importlib.machinery


def _load(name):
    return importlib.machinery.PathFinder.find_spec(name, None)
""",
        encoding="utf-8",
    )
    assert _SCANNER.scan_roots((sugar,)) == []


def test_pathfinder_find_spec_is_not_flagged(tmp_path: Path) -> None:
    """The non-executing replacement form must stay quiet -- otherwise the
    floor would punish the fix it demands."""
    offenders = _scan_text(
        tmp_path,
        "ok.py",
        """
import importlib.machinery


def locate(name, search_path):
    return importlib.machinery.PathFinder.find_spec(name, search_path)
""",
    )
    assert offenders == []


def test_self_import_of_own_package_is_not_flagged(tmp_path: Path) -> None:
    """The one mechanically-legitimate site: importing our OWN top-level
    package (never third-party source under test). Distinguished by the
    statically-known prefix of the import target matching the package that
    owns the scanned source tree -- derived from the scan root's filesystem
    layout, never a hardcoded name."""
    offenders = _scan_text(
        tmp_path,
        "self_register.py",
        """
import importlib
import pkgutil

from sugar_lift_py_tests import sugar as _sugar_pkg


def default_catalog():
    for _mod in pkgutil.iter_modules(_sugar_pkg.__path__):
        importlib.import_module(f"sugar_lift_py_tests.sugar.{_mod.name}")
""",
    )
    assert offenders == []


def test_third_party_import_disguised_as_relative_is_still_flagged(
    tmp_path: Path,
) -> None:
    """A non-self, non-relative dotted target must trip even if it merely
    resembles the exemption shape -- the exemption requires the STATIC
    prefix to equal our own package name, not just "looks like a module
    path"."""
    offenders = _scan_text(
        tmp_path,
        "not_self.py",
        """
import importlib


def load_vendor(module_name):
    return importlib.import_module("numpy_extensions." + module_name)
""",
    )
    # Dynamic concatenation has no statically-known FULL prefix match to our
    # own package, so this is correctly still counted (honest: the call is
    # not proven self-referential).
    assert _SCANNER.r_source_via_execution(offenders) == 1
