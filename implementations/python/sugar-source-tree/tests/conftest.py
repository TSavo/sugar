import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "sugar-lift-python-source" / "src")
)


def oracle_source_file(source: str, backend=None, suffix: str = ".py"):
    """Test door that honors the law: text enters only through the oracle.

    Writes the literal to a real file and constructs the SourceFile through
    the oracle's path-addressed identity — there is no raw-string door to
    bypass, in tests or anywhere else.
    """
    from sugar_source_tree.tree import SourceFile

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=suffix, delete=False
    ) as handle:
        handle.write(source)
        path = handle.name
    return SourceFile.from_path(path, backend=backend)
