from __future__ import annotations

from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver
from sugar_lift_py_tests.lift_rpc import lift_file_payload


def test_exact_pandas_option_callback_carries_list_mutation() -> None:
    payload = lift_file_payload(
        "from pandas._config import config as cf\n"
        "\n"
        "def test_callback():\n"
        "    keys = [None]\n"
        "\n"
        "    def callback(key):\n"
        "        keys.append(key)\n"
        "\n"
        "    cf.register_option('d.a', 'foo', cb=callback)\n"
        "    del keys[-1]\n"
        "    cf.set_option('d.a', 'bar')\n"
        "    assert keys[-1] == 'd.a'\n"
        "    del keys[-1]\n"
        "    cf.reset_option('d.a')\n"
        "    assert keys[-1] == 'd.a'\n",
        "test_callback.py",
    )

    assert payload.effects == []
    assert len(payload.ir) == 2


def test_exact_pandas_options_attribute_assignment_replays_callback() -> None:
    source = (
        "from pandas._config import config as cf\n"
        "\n"
        "def test_callback():\n"
        "    keys = []\n"
        "\n"
        "    def callback(key):\n"
        "        keys.append(key)\n"
        "\n"
        "    cf.register_option('c', 0, cb=callback)\n"
        "    options = cf.options\n"
        "    options.c = 1\n"
        "    assert keys[-1] == 'c'\n"
    )
    payload = lift_file_payload(source, "test_callback.py")
    accounting = account_lift_coverage(
        census_source(source, file="test_callback.py"),
        payload.to_rpc(),
    ).to_json()["assertions"]

    assert payload.effects == []
    assert accounting["silently_unaccounted"] == 0
    assert accounting["lifted_cited"] == 1


def test_similar_project_callback_methods_do_not_gain_pandas_semantics() -> None:
    source = (
        "def test_callback(project):\n"
        "    keys = [None]\n"
        "\n"
        "    def callback(key):\n"
        "        keys.append(key)\n"
        "\n"
        "    project.register_option('d.a', 'foo', cb=callback)\n"
        "    del keys[-1]\n"
        "    project.set_option('d.a', 'bar')\n"
        "    assert keys[-1] == 'd.a'\n"
    )

    try:
        lift_file_payload(source, "test_project_callback.py")
    except FactoryPanic as exc:
        assert "RuntimeEffect" in str(exc)
        assert "py.subscript" in str(exc)
    else:
        raise AssertionError("similar project methods must remain loud")


def test_similar_project_options_attribute_does_not_replay_callback() -> None:
    source = (
        "def test_callback(project):\n"
        "    keys = []\n"
        "\n"
        "    def callback(key):\n"
        "        keys.append(key)\n"
        "\n"
        "    project.register_option('c', 0, cb=callback)\n"
        "    options = project.options\n"
        "    options.c = 1\n"
        "    assert keys[-1] == 'c'\n"
    )

    try:
        lift_file_payload(source, "test_project_callback.py")
    except FactoryPanic as exc:
        assert "RuntimeEffect" in str(exc)
        assert "py.subscript" in str(exc)
    else:
        raise AssertionError("project options lookalike must remain loud")


def test_exact_pandas_runtime_callback_stays_loud() -> None:
    source = (
        "from pandas._config import config as cf\n"
        "\n"
        "def test_callback(callback):\n"
        "    cf.register_option('d.a', 'foo', cb=callback)\n"
    )

    try:
        lift_file_payload(source, "test_runtime_callback.py")
    except FactoryPanic as exc:
        assert exc.info.owner == "pandas.option_callback"
        assert "local callback registration" in exc.info.requested
    else:
        raise AssertionError("runtime callback registration must remain loud")


def test_pandas_option_callback_truthful_and_lying_twins_refute(tmp_path) -> None:
    prefix = (
        "from pandas._config import config as cf\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
        "\n"
        "def test_a():\n"
        "    keys = [None]\n"
        "\n"
        "    def callback(key):\n"
        "        keys.append(key)\n"
        "\n"
        "    cf.register_option('sugar.callback', 'old', cb=callback)\n"
        "    del keys[-1]\n"
        "    cf.set_option('sugar.callback', 'new')\n"
    )
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        prefix + "    assert echo(keys[-1]) == 'sugar.callback'\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        prefix + "    assert echo(keys[-1]) == 'other'\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


def test_pandas_option_attribute_callback_truthful_and_lying_twins_refute(
    tmp_path,
) -> None:
    prefix = (
        "from pandas._config import config as cf\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
        "\n"
        "def test_a():\n"
        "    keys = []\n"
        "\n"
        "    def callback(key):\n"
        "        keys.append(key)\n"
        "\n"
        "    cf.register_option('c', 0, cb=callback)\n"
        "    options = cf.options\n"
        "    options.c = 1\n"
    )
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        prefix + "    assert echo(keys[-1]) == 'c'\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        prefix + "    assert echo(keys[-1]) == 'other'\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
