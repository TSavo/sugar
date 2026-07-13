from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

from sugar_lift_python_source.lifter import lift_source

PACKAGES = ("numpy", "pandas")

DATACLASS_FAMILY_NAMES = {
    "dataclass",
    "dataclasses.dataclass",
    "attr.s",
    "attrs.define",
    "attr.attrs",
    "attrs.frozen",
}
CACHE_FAMILY_NAMES = {"lru_cache", "functools.lru_cache", "cache", "functools.cache"}


def package_root(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    assert spec is not None and spec.origin is not None
    return Path(spec.origin).resolve().parent


def python_files(root: Path):
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def bucket_decorator_name(name: str) -> str:
    if name in DATACLASS_FAMILY_NAMES:
        return "dataclass-family(already-named-by-lifter)"
    if name in CACHE_FAMILY_NAMES:
        return "cache-family(lru_cache/cache)"
    if name.startswith(("np.", "numpy.")):
        return "numpy-namespaced-decorator"
    if name.startswith(("pd.", "pandas.")):
        return "pandas-namespaced-decorator"
    if name.startswith(("contextlib.", "functools.")):
        return "stdlib-other(contextlib/functools, not yet modeled)"
    return "opaque-user-or-third-party-decorator"


def bucket_subscript_base(base_text: str) -> str:
    root = base_text.split("[")[0]
    tail = root.rsplit(".", 1)[-1]
    if tail == "Generic":
        return "Generic[T]()"
    if tail in {"list", "dict", "tuple", "set", "frozenset", "type"}:
        return "builtin-generic[...]()"
    if root.startswith(("typing.", "t.")) or tail in {
        "Callable",
        "Optional",
        "Union",
        "Sequence",
        "Mapping",
        "TypeVar",
    }:
        return "typing.*[...]()"
    return "dynamic-subscript-dispatch(genuine-runtime-lookup)"


def find_subscript_call_at_line(root: Path, rel_path: str, line: int) -> str | None:
    # rel_path is "package/relative/path.py"; strip package prefix to locate under root
    _, _, sub = rel_path.partition("/")
    path = root / sub
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Subscript)
            and node.func.lineno == line
        ):
            try:
                return ast.unparse(node.func.value)
            except Exception:
                return type(node.func.value).__name__
    return None


def main() -> None:
    package_versions = {p: importlib.metadata.version(p) for p in PACKAGES}
    roots = {p: package_root(p) for p in PACKAGES}

    counts_by_kind: Counter = Counter()
    total_files = 0

    decorator_shape_counts: Counter = Counter()
    subscript_shape_counts: Counter = Counter()
    default_shape_counts: Counter = Counter()

    for package in PACKAGES:
        root = roots[package]
        for path in python_files(root):
            total_files += 1
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                counts_by_kind["io-error"] += 1
                continue
            except UnicodeDecodeError:
                source = path.read_text(encoding="utf-8", errors="replace")
            rel = f"{package}/{path.relative_to(root).as_posix()}"
            result = lift_source(source, rel)
            for refusal in result.refusals:
                kind = str(refusal.get("kind"))
                counts_by_kind[kind] += 1
                reason = str(refusal.get("reason", ""))
                line = refusal.get("line")

                if kind == "decorator-refused":
                    m = re.match(r"decorator '(.*)' is not transparent", reason)
                    name = m.group(1) if m else reason
                    decorator_shape_counts[bucket_decorator_name(name)] += 1
                elif kind == "non-literal-default":
                    m = re.match(r"non-literal default: (\w+)", reason)
                    node_type = m.group(1) if m else reason
                    default_shape_counts[node_type] += 1
                elif kind == "callee-subscript-refused":
                    base = None
                    if isinstance(line, int):
                        base = find_subscript_call_at_line(root, rel, line)
                    if base is None:
                        subscript_shape_counts[
                            "unresolved(could-not-relocate-node)"
                        ] += 1
                    else:
                        subscript_shape_counts[bucket_subscript_base(base)] += 1

    report = {
        "package_versions": package_versions,
        "total_files": total_files,
        "counts_by_kind": dict(sorted(counts_by_kind.items())),
        "front_3262_decorator_refused_shapes": dict(
            sorted(decorator_shape_counts.items(), key=lambda kv: -kv[1])
        ),
        "front_3263_callee_subscript_refused_shapes": dict(
            sorted(subscript_shape_counts.items(), key=lambda kv: -kv[1])
        ),
        "front_3264_non_literal_default_shapes": dict(
            sorted(default_shape_counts.items(), key=lambda kv: -kv[1])
        ),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
