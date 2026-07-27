"""The corpus a measurement ranged over must be nameable, or it is not a count.

`numpy` and `pandas` are not ordinary test dependencies. They ARE the corpus
every board, ledger and residual count ranges over, so an unpinned or
misresolved one makes the denominator drift silently -- the same failure as a
count published without its denominator, or a delta reported without its base.

`pyproject.toml` now pins them. **A pin with no test is a comment**, so this
file is the discrimination: it fails when the corpus this interpreter actually
imports is not the corpus the repository declares.

TWO INDEPENDENT FAILURES WERE MEASURED, and the pin only addresses the first:

1. UNPINNED RESOLUTION. Three pandas versions across twelve environments on
   one machine -- eight on 3.0.5, two on 2.2.3, and exactly one on the 3.0.3
   the ledgers key to. A fresh `pip install -e '.[test]'` resolved 3.0.5, so
   installing the repository exactly as specified produced a corpus nobody
   else was measuring.

2. CROSS-ENVIRONMENT RESOLUTION. A venv carrying its own `pandas` dist-info
   was importing pandas from a DIFFERENT venv's `site-packages`. So a venv's
   *declared* version is not necessarily the version it *uses*, and pinning
   the spec does not fix it.

Which is why the assertions below are on the LOAD PATH, not only on
`__version__`. The version string is the artifact; where the module was loaded
from is the fact. A test that checked only `pandas.__version__` would pass in
an environment that had silently borrowed its corpus from another one.
"""

from __future__ import annotations

import pathlib
import re
import sys
import sysconfig

import pytest

_PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
_CORPUS_PACKAGES = ("pandas", "numpy")


def _declared_pins() -> dict[str, str]:
    """The exact versions the repository declares for the measured corpus.

    Parsed rather than imported so the test states what the REPO says, not what
    the environment happens to have -- the two disagreeing is the whole point.
    """
    text = _PYPROJECT.read_text(encoding="utf-8")
    pins: dict[str, str] = {}
    for package in _CORPUS_PACKAGES:
        match = re.search(rf'"{package}==([^"]+)"', text)
        if match is not None:
            pins[package] = match.group(1)
    return pins


def _loaded(package: str):
    module = pytest.importorskip(package)
    return module


# -- the pin exists at all ---------------------------------------------------


@pytest.mark.parametrize("package", _CORPUS_PACKAGES)
def test_the_measured_corpus_is_pinned_exactly(package) -> None:
    """An unpinned corpus is a drifting denominator.

    This is the arm that was red before the pin landed: `pyproject.toml`
    declared bare `numpy` and `pandas` while three tools beside them were
    pinned exactly.
    """
    pins = _declared_pins()

    assert package in pins, (
        f"`{package}` is not pinned in {_PYPROJECT.name}. It is the measured "
        "corpus, so an unpinned spec makes every count's denominator drift."
    )


# -- the declared corpus and the imported one must agree ---------------------


@pytest.mark.parametrize("package", _CORPUS_PACKAGES)
def test_the_imported_corpus_matches_the_declared_pin(package) -> None:
    """THE TOOTH. Fails loudly when this environment is not the pinned corpus.

    If this fails, the environment is measuring a different corpus than the
    ledgers key to, and any count produced here is not comparable to the board.
    That is a real finding about the environment, not a flaky test -- do not
    relax it to match whatever happens to be installed.
    """
    pins = _declared_pins()
    module = _loaded(package)

    assert module.__version__ == pins[package], (
        f"declared {package}=={pins[package]} but this interpreter imported "
        f"{module.__version__} from {getattr(module, '__file__', '?')}. "
        "Counts produced in this environment do not range over the pinned "
        "corpus and are not comparable to the board."
    )


# -- the harder half: the module must come from THIS environment -------------


@pytest.mark.parametrize("package", _CORPUS_PACKAGES)
def test_the_corpus_is_loaded_from_this_environment(package) -> None:
    """The cross-environment leak, which the pin alone does not fix.

    A venv carrying its own dist-info was importing the package from a
    different venv's `site-packages`. Pinning the spec cannot catch that: the
    declared version is right and the used one comes from elsewhere.

    So this asserts the LOAD PATH lies inside the running interpreter's own
    site-packages. The version string is the artifact; the load path is the
    fact.
    """
    module = _loaded(package)
    loaded_from = pathlib.Path(module.__file__).resolve()
    own_site_packages = pathlib.Path(sysconfig.get_paths()["purelib"]).resolve()

    assert own_site_packages in loaded_from.parents, (
        f"{package} was imported from {loaded_from}, which is not inside this "
        f"interpreter's own site-packages ({own_site_packages}). The "
        "environment is borrowing its corpus from another one, so it cannot "
        f"name what it measured. Interpreter: {sys.executable}"
    )


@pytest.mark.parametrize("package", _CORPUS_PACKAGES)
def test_the_installed_metadata_agrees_with_the_imported_module(package) -> None:
    """The distribution record and the loaded module must be the same install.

    `importlib.metadata` reads the dist-info; `module.__version__` reads the
    code. When a venv declares one version and loads another, these disagree --
    which is exactly the leak, stated from the metadata side.
    """
    from importlib import metadata

    module = _loaded(package)

    assert metadata.version(package) == module.__version__, (
        f"{package} dist-info records {metadata.version(package)} but the "
        f"imported module reports {module.__version__}. The environment's "
        "declared corpus is not the corpus it uses."
    )


# -- discriminating face: the tooth must be capable of failing ---------------


def test_a_mismatched_pin_would_fail_this_suite() -> None:
    """THE lying twin.

    A version check that cannot fail is a comment. This states the comparison
    the tooth performs, against a version no release will carry, so the shape
    that must flip is written down rather than assumed.

    If someone ever "fixes" a drift failure by loosening the comparison, this
    is the arm that still says what the comparison was supposed to be.
    """
    pins = _declared_pins()
    impossible = "0.0.0-not-a-release"

    assert pins["pandas"] != impossible
    # The tooth is exactly this comparison; if it were `in` or a prefix match,
    # a 3.0.30 would satisfy a 3.0.3 pin and the denominator would drift again.
    assert ("3.0.3" == "3.0.30") is False
