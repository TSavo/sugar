from pathlib import Path

from sugar_lift_py_tests import engine_log


def test_exact_pandas_make_doc_shape_has_bounded_reduction_events(monkeypatch) -> None:
    import pandas
    import sugar_lift_py_tests.lift_rpc as lift_rpc

    path = Path(pandas.__file__).parent / "core/generic.py"
    source = path.read_text(encoding="utf-8")
    original_emit = engine_log._emit
    events = 0

    def bounded_emit(*args, **kwargs):
        nonlocal events
        events += 1
        assert events <= 100_000, "make_doc reduction exceeded event bound"
        return original_emit(*args, **kwargs)

    monkeypatch.setattr(engine_log, "_emit", bounded_emit)
    monkeypatch.setattr(
        lift_rpc,
        "_iter_liftable_function_defs",
        lambda module: (
            stmt
            for stmt in module.statements()
            if stmt.observed == "FunctionDef" and stmt.function_name() == "make_doc"
        ),
    )

    lift_rpc.audit_lift_file(source, "core/generic.py", recover_panics=True)

    assert events < 100_000
