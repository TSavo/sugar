from pathlib import Path


def test_tree_and_sugar_construction_have_no_linker_catalog_or_metadata_door():
    python_root = Path(__file__).resolve().parents[2]
    sugar_root = python_root / "sugar-lift-py-tests/src/sugar_lift_py_tests/sugar"
    tree_root = python_root / "sugar-source-tree/src/sugar_source_tree"
    tree_construction = [
        tree_root / "nodes.py",
        tree_root / "backend.py",
        *tree_root.glob("*_adapter.py"),
    ]
    files = [*sugar_root.rglob("*.py"), *tree_construction]
    forbidden = (
        "sugar_linker",
        "sugar-linker",
        "proof_catalog",
        "member_envelope",
        "decode_context_manager_contract",
        "path_source(",
        "installed_module_source(",
    )
    offenders = []
    for path in files:
        text = path.read_text()
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{path.relative_to(python_root)}: {needle}")
    assert offenders == [], "construction-law offenders:\n" + "\n".join(offenders)


def test_with_sugar_does_not_retain_raw_cm_json_or_invoke_resolution():
    python_root = Path(__file__).resolve().parents[2]
    files = [
        python_root / "sugar-source-tree/src/sugar_source_tree/nodes.py",
        *(
            python_root / "sugar-lift-py-tests/src/sugar_lift_py_tests/sugar"
        ).glob("with*_sugar.py"),
    ]
    forbidden = (
        "resolve_context_manager",
        "decode_context_manager",
        "member_json",
        "payload_json",
        "catalog_json",
    )
    offenders = [
        f"{path.name}: {needle}"
        for path in files
        for needle in forbidden
        if needle in path.read_text()
    ]
    assert offenders == [], "With boundary offenders:\n" + "\n".join(offenders)
