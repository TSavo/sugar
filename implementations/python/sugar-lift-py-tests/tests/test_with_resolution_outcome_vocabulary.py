# SPDX-License-Identifier: MIT OR Apache-2.0
"""The intake gate and the partition must read ONE outcome vocabulary.

`_tally_cm_resolutions` validates incoming With resolution events against a
closed outcome set, and `_with_census_partition` counts them into buckets.
They are two doors onto one question, and the gate runs FIRST.

#7388 added `cited-opaque` to the conservation identity and to the partition
and left the gate's set at two values. Every cited row was then rejected as a
malformed event before the bucket built for it could count it -- 86 instrument
failures in run 31128314243 where the previous census had zero. An instrument
failure voids the whole file, so this did not merely miscount: it destroyed the
measurement for every file containing a cited manager.

The repair is one vocabulary read by both doors. These teeth fail if they
diverge again.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

_SCRIPTS = (
    pathlib.Path(__file__).resolve().parents[1] / "scripts"
)


def _load():
    path = _SCRIPTS / "control_effect_recensus.py"
    spec = importlib.util.spec_from_file_location("_cer_vocab", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_identity_names_exactly_the_vocabulary_the_gate_admits() -> None:
    """The LAW string and the gate's closed set must agree, term for term.

    The identity is the human-readable statement of the partition; the set is
    what the gate enforces. If they drift, the board's stated law stops
    describing what it actually admits.
    """
    cer = _load()
    identity = cer.WITH_CENSUS_CONSERVATION_IDENTITY
    named = set(re.findall(r"[a-z]+(?:-[a-z]+)*", identity.split("==", 1)[1]))
    for outcome in cer._WITH_RESOLUTION_OUTCOMES:
        assert outcome in named, (
            f"gate admits {outcome!r} but the conservation identity does not "
            f"name it: {identity!r}"
        )


def test_cited_opaque_is_admitted_by_the_intake_gate() -> None:
    """The planted arm: a cited row must survive intake.

    Before the repair this raised `malformed With resolution event` and the
    file became an instrument failure.
    """
    cer = _load()
    assert "cited-opaque" in cer._WITH_RESOLUTION_OUTCOMES


def test_the_partition_counts_every_outcome_the_gate_admits() -> None:
    """No admitted value may fall outside the buckets.

    A value the gate lets in but the partition does not count would break the
    closed-outcomes reconciliation downstream -- the arithmetic stops matching
    and the row is dropped without anyone naming it.
    """
    cer = _load()
    source = (_SCRIPTS / "control_effect_recensus.py").read_text()
    body = source.split("def _with_census_partition", 1)[1]
    for outcome in cer._WITH_RESOLUTION_OUTCOMES:
        assert f'"{outcome}"' in body, (
            f"gate admits {outcome!r} but _with_census_partition never "
            "mentions it; an admitted value with no bucket is dropped silently"
        )
