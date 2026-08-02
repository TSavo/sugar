"""The binding Python construction job must invoke every permanent R axis.

The axes moved out of the workflow YAML and into tools/run_sole_construction_
floors.sh, because the whole floor set now runs inside ONE machine-wide heavy
lease. Twenty leased steps would have let a pandas census interleave between
two axes, and then "the complete floor set from one pinned run" would have been
a fiction.

What must not change is the property this file has always pinned: every
permanent axis is invoked, none is silently dropped, and no axis is skipped
because an earlier one was honestly red. The `if: always()` guarantee is now
carried by the script's `axis` helper, which runs EVERY axis, collects the red
ones, and fails at the end -- so the check below is that each axis goes through
that helper, rather than that each has its own YAML step.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "factory-zero-tolerance.yml"
FLOOR_SET = ROOT / "tools" / "run_sole_construction_floors.sh"

# Permanent axes with live instruments. factory_zero_tolerance and
# construction_cache_context_law retired with the factory era (#6028).
AXIS_COMMANDS = {
    "R_ownership = 0": "factory_ownership_law.py",
    "R_construction_panic_catches_outside_membrane = 0": (
        "construction_panic_catch_law.py"
    ),
    # Criterion-2 process floors: axis names carry no "= 0" (pre-measure crash
    # must not paint a bankable zero in the group header).
    "R_silent": "silent_zero_tolerance.py",
    "R_native_crashes": "native_crash_zero_tolerance.py",
    "R_bare_exceptions": "bare_exception_zero_tolerance.py",
    "R_timeouts": "timeout_zero_tolerance.py",
    "R_vendor_special_case = 0": "vendor_special_case_law.py",
    "R_factory_walk_unclassified = 0": "factory_walk_unclassified_law.py",
    "R_finite_cap_opaque_completions = 0": ("finite_cap_opaque_completion_law.py"),
    "R_finite_unfold_compact_gaps = 0": ("finite_unfold_compact_projection_law.py"),
    "R_source_via_execution = 0": "source_via_execution_law.py",
    "R_no_sugar_in_desugar = 0": "no_sugar_in_desugar_law.py",
    # Whole-kit construction currency (adapters only may name stdlib ast).
    # Live R includes dual-body sugar-lift-python-source residual — exit 1 until 0.
    "R_construction_side_doors = 0": "construction_side_door_law.py",
}


def test_binding_job_invokes_every_permanent_axis() -> None:
    workflow = WORKFLOW.read_text()
    floors = FLOOR_SET.read_text()

    assert "python-sole-construction-floors:" in workflow
    assert "tools/run_sole_construction_floors.sh" in workflow, (
        "the binding job no longer runs the floor set at all"
    )
    # And it runs it via run_sole_construction_floors.sh -- an unleased floor set is a floor set
    # measured beside whatever else the box happened to be doing.
    assert "tools/run_sole_construction_floors.sh" in workflow
    assert "tools/heavy_measurement_lease.py" not in workflow

    for axis, command in AXIS_COMMANDS.items():
        axis_start = floors.find(f'axis "{axis}"')
        if axis_start < 0:
            axis_start = floors.find(f"axis '{axis}'")
        assert axis_start >= 0, f"{axis} is not bound to merge CI"
        axis_end = floors.find("\naxis ", axis_start + 1)
        step = floors[axis_start : axis_end if axis_end >= 0 else None]
        assert command in step, f"{axis} does not invoke {command}"
        if axis == "R_factory_walk_unclassified = 0":
            assert "--live-root" in step, (
                "R_factory_walk_unclassified only runs a fixture/discrimination; "
                "binding CI must census the checked-in production surface"
            )
        if axis in {
            "R_native_crashes",
            "R_bare_exceptions",
            "R_timeouts",
            "R_silent",
        }:
            # Process floors + Criterion-2 silent must name a population.
            # Bare silent_zero_tolerance used to default to kit production_roots
            # (~444 files) — false green while authenticated pandas was unmeasured.
            assert "PANDAS_CORPUS" in step or "authenticated_pandas" in step, (
                f"{axis} must pass an explicit corpus path; silent default "
                "to kit production_roots is a wrong-population false green"
            )
            # Not only the script name: a path argument must follow.
            assert '"$PANDAS_CORPUS"' in step or "'$PANDAS_CORPUS'" in step, (
                f"{axis} must pass \"$PANDAS_CORPUS\" as the scan root"
            )
            # Scratch must not default under the population root.
            assert "--out-dir" in step or "FLOOR_SCRATCH" in step, (
                f"{axis} must direct floor scratch outside the population "
                "(S0.2: mkdir under site-packages/pandas is measurement crime)"
            )
            # Group header must not embed a bankable zero.
            assert " = 0" not in step.split("\n", 1)[0], (
                f"{axis} group name must not embed '= 0' (pre-measure crash bank)"
            )


def test_process_floors_resolve_authenticated_pandas_population() -> None:
    """The floor set must authenticate pandas before the four corpus axes."""
    floors = FLOOR_SET.read_text()
    assert "authenticated_pandas_corpus" in floors, (
        "process floors must resolve the authenticated pandas corpus root"
    )
    assert "PANDAS_CORPUS=" in floors
    # Order: corpus resolved once, then all four Criterion-2 population axes use it.
    corpus_at = floors.find("PANDAS_CORPUS=")
    native_at = floors.find('axis "R_native_crashes"')
    bare_at = floors.find('axis "R_bare_exceptions"')
    timeout_at = floors.find('axis "R_timeouts"')
    silent_at = floors.find('axis "R_silent"')
    assert 0 <= corpus_at < native_at < bare_at < timeout_at < silent_at, (
        "PANDAS_CORPUS must be bound before native/bare/timeout/silent axes"
    )


def test_no_axis_is_skipped_after_an_earlier_honest_red() -> None:
    """What `if: always()` used to buy, now bought by the runner itself.

    Every axis runs, reds are COLLECTED rather than short-circuited, and the
    verdict comes at the end. A floor set that stopped at the first red would
    report a smaller R than the truth.
    """
    floors = FLOOR_SET.read_text()
    assert "set -uo pipefail" in floors and "set -e\n" not in floors, (
        "the floor set must not abort on the first red axis"
    )
    assert "red_axes+=" in floors and "exit 1" in floors, (
        "red axes must be collected and reported, then fail the job"
    )
    # Every axis in the ledger goes through the one helper. No side doors.
    for axis in AXIS_COMMANDS:
        assert f'axis "{axis}"' in floors or f"axis '{axis}'" in floors
