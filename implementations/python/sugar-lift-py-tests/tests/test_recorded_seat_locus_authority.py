"""An installed file's address is the seat its distribution recorded.

`is_absolute()` is a string test standing in for a property. The law it serves
is "another checkout can resolve this address"; what it checks is "this string
starts with a slash". Those come apart, and the gap is one character wide:

    workspace_path_source(".../site-packages/pandas/core/frame.py", root="/")
      -> "Users/tsavo/provekit/.venv/lib/python3.14/site-packages/pandas/core/frame.py"

That locus is exactly as machine-specific and unresolvable as the absolute path
it came from, and the absolute-locus law accepts it. Every intermediate root is
the same defect in milder form, so a fix that catches only `/` is a special
case rather than a law.

An installed distribution states the answer itself: its RECORD lists the seat of
every file it installed. This module pins that the locus must EQUAL that seat.

Scope is the other half of the law and is pinned just as hard: a first-party
file has no RECORD, so this arm must NOT fire there. A refusal is never widened
to a population that cannot satisfy it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import (

    SourceUnavailable,
    recorded_seat_for,
    workspace_path_source,
)


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

def _installed_file():
    """One file of an installed distribution, with the seat it recorded."""
    from importlib.metadata import distribution

    dist = distribution("pandas")
    recorded = [f for f in (dist.files or []) if str(f).endswith("frame.py")]
    if not recorded:
        pytest.skip("installed distribution records no frame.py to address")
    seat = str(recorded[0])
    return Path(dist.locate_file(recorded[0])).resolve(), seat


def _install_root(path: Path, seat: str) -> Path:
    """The directory the seat is stated relative to."""
    return Path(str(path)[: -len(seat) - 1])


# -- the truthful arm: the recorded root mints the recorded seat ---------------


def test_the_install_root_mints_exactly_the_recorded_seat() -> None:
    path, seat = _installed_file()

    _source, locus, _cid = workspace_path_source(
        str(path), root=str(_install_root(path, seat))
    )

    assert locus == seat
    assert not Path(locus).is_absolute()


def test_the_seat_is_read_from_the_distribution_not_guessed() -> None:
    path, seat = _installed_file()

    assert recorded_seat_for(str(path)) == seat


# -- the lying arms: every root that produces a non-seat is refused -----------


def test_the_root_slash_bypass_is_refused() -> None:
    """THE REPRODUCER. `root=/` strips the leading slash and nothing else.

    The result passes `is_absolute()` while being exactly as unresolvable as
    the absolute path. This is the arm the whole change exists for.
    """
    path, _seat = _installed_file()

    with pytest.raises(SourceUnavailable) as raised:
        workspace_path_source(str(path), root="/")

    message = str(raised.value)
    assert "records the seat" in message
    assert "no other checkout resolves" in message


def test_every_intermediate_root_is_refused_too() -> None:
    """A fix that catches only `/` would be a special case, not a law.

    Each of these yields a shorter, equally unresolvable address for the same
    file. Asserted as an exact count so this cannot pass by refusing nothing.
    """
    path, seat = _installed_file()
    install_root = _install_root(path, seat)
    intermediate = [install_root / part for part in Path(seat).parts[:-1]]
    assert (
        len(intermediate) >= 2
    ), "need at least two intermediate roots to discriminate"

    refused = 0
    for root in intermediate:
        with pytest.raises(SourceUnavailable):
            workspace_path_source(str(path), root=str(root))
        refused += 1

    assert refused == len(intermediate)


def test_one_file_no_longer_has_several_accepted_addresses() -> None:
    """The property, stated directly: exactly ONE root is accepted."""
    path, seat = _installed_file()
    install_root = _install_root(path, seat)
    roots = [install_root, Path("/")] + [
        install_root / part for part in Path(seat).parts[:-1]
    ]

    accepted = []
    for root in roots:
        try:
            accepted.append(workspace_path_source(str(path), root=str(root))[1])
        except SourceUnavailable:
            pass

    assert accepted == [seat]
    assert len(accepted) == 1


# -- scope: a population that cannot satisfy the law is not subject to it ------


def test_a_first_party_file_is_untouched_under_any_root(tmp_path) -> None:
    """No RECORD states an address for it, so the workspace law is its whole law."""
    package = tmp_path / "pkg"
    package.mkdir()
    source = package / "module.py"
    source.write_text("x = 1\n", encoding="utf-8")

    assert recorded_seat_for(str(source)) is None

    for root, expected in ((tmp_path, "pkg/module.py"), (package, "module.py")):
        _source, locus, _cid = workspace_path_source(str(source), root=str(root))
        assert locus == expected


def test_an_unrecorded_file_inside_an_install_root_is_not_claimed(tmp_path) -> None:
    """A stray in an install root has no seat, so nothing is authenticated.

    `None` here means "no distribution states an address for this file", never
    "the seat is unavailable, carry on with a guess".
    """
    dist_info = tmp_path / "somepkg-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "RECORD").write_text("somepkg/kept.py,,\n", encoding="utf-8")
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: somepkg\nVersion: 1.0\n", encoding="utf-8"
    )
    package = tmp_path / "somepkg"
    package.mkdir()
    (package / "kept.py").write_text("x = 1\n", encoding="utf-8")
    stray = package / "stray.py"
    stray.write_text("y = 2\n", encoding="utf-8")

    assert recorded_seat_for(str(stray)) is None
    _source, locus, _cid = workspace_path_source(str(stray), root=str(tmp_path))
    assert locus == "somepkg/stray.py"


def test_a_recorded_file_in_that_same_root_IS_claimed(tmp_path) -> None:
    """The discrimination for the test above: recorded and unrecorded differ.

    Without this pair, `recorded_seat_for` returning None for everything would
    satisfy the stray test and silently disable the whole law.
    """
    dist_info = tmp_path / "somepkg-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "RECORD").write_text("somepkg/kept.py,,\n", encoding="utf-8")
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: somepkg\nVersion: 1.0\n", encoding="utf-8"
    )
    package = tmp_path / "somepkg"
    package.mkdir()
    kept = package / "kept.py"
    kept.write_text("x = 1\n", encoding="utf-8")

    assert recorded_seat_for(str(kept)) == "somepkg/kept.py"

    _source, locus, _cid = workspace_path_source(str(kept), root=str(tmp_path))
    assert locus == "somepkg/kept.py"

    with pytest.raises(SourceUnavailable):
        workspace_path_source(str(kept), root=str(package))


# -- the second gate is unchanged ---------------------------------------------


def test_the_outside_root_refusal_still_fires_first(tmp_path) -> None:
    """A path with no relative name at all is still the original loud refusal."""
    source = tmp_path / "module.py"
    source.write_text("x = 1\n", encoding="utf-8")
    elsewhere = tmp_path.parent / "definitely-not-the-root-xyz"

    with pytest.raises(SourceUnavailable) as raised:
        workspace_path_source(str(source), root=str(elsewhere))

    assert "lies outside workspace root" in str(raised.value)


# -- the driver must root where the seats were recorded -----------------------


def _driver():
    """The authoritative scoreboard's own rooting decision."""
    import importlib.util
    import sys

    path = (
        sugar_lift_py_tests_package_root() / "scripts" / "control_effect_recensus.py"
    )
    spec = importlib.util.spec_from_file_location("_recensus_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_driver_roots_an_installed_corpus_at_the_install_root() -> None:
    """The break this law would otherwise cause, pinned at its source.

    The scoreboard is invoked with the package directory as its corpus, so
    before this split it rooted the locus at `.../site-packages/pandas` and
    minted `core/frame.py`. A driver that never runs is not obviously broken,
    so the rooting is pinned here rather than left to the law's refusal.
    """
    path, seat = _installed_file()
    install_root = _install_root(path, seat)
    package_directory = install_root / Path(seat).parts[0]

    assert _driver().locus_root_for_corpus(package_directory) == install_root
    assert package_directory != install_root, "the two roots must actually differ"


def test_the_rooted_corpus_then_mints_a_seat() -> None:
    """The composition, end to end: root the driver's way, get a recorded seat."""
    path, seat = _installed_file()
    install_root = _install_root(path, seat)
    package_directory = install_root / Path(seat).parts[0]

    locus_root = _driver().locus_root_for_corpus(package_directory)
    _source, locus, _cid = workspace_path_source(str(path), root=str(locus_root))

    assert locus == seat


def test_the_driver_leaves_a_first_party_corpus_root_alone(tmp_path) -> None:
    """No distribution states an address for it, so the corpus root stands."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text("x = 1\n", encoding="utf-8")

    assert _driver().locus_root_for_corpus(package) == package
