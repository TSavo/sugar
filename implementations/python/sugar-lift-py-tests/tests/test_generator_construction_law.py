import importlib.util
import sys
from pathlib import Path


_REPOSITORY = Path(__file__).resolve().parents[4]
_SCANNER_PATH = (
    _REPOSITORY
    / "implementations/python/sugar-lift-py-tests/scripts/generator_construction_law.py"
)
_SPEC = importlib.util.spec_from_file_location("generator_construction_law", _SCANNER_PATH)
assert _SPEC and _SPEC.loader
_SCANNER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SCANNER
_SPEC.loader.exec_module(_SCANNER)


def test_current_repository_has_one_suspended_generator_construction_path():
    discovered, offenders = _SCANNER.scan(_REPOSITORY)

    assert discovered > 0
    assert not offenders, "\n".join(
        f"{item.coordinate}: {item.observed} -> {item.requested}" for item in offenders
    )


def test_scanner_flags_all_four_planted_eager_or_name_gated_shapes(tmp_path):
    files = {
        "implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py": "class Yield: pass",
        "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/source_call_frame.py": "class SourceVisibleCallFrameV1: pass",
        "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/call_site_sugar.py": "source_body.desugar()",
        "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/generator_with_sugar.py": "if contextlib.contextmanager: warning",
    }
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    discovered, offenders = _SCANNER.scan(tmp_path)

    assert discovered == 4
    assert len(offenders) == 4
