from __future__ import annotations

import ast
import math
from dataclasses import dataclass

import json as _json

from sugar_lift_py_tests.ir import Term, ctor, num, str_const


def _encode_value_term(value: object) -> "Term | None":
    """Encode a resolved Python value as a canonical IR Term that z3 can
    distinguish concretely using the String theory.

    Encoding (all as ``str_const`` so the String theory's decidable equality
    gives the solver real teeth — EUF uninterpreted-sort ctors are trivially
    consistent and would only give undecidable/vacuous discharges):

    - ``dict[str, list[int]]`` (pd.DataFrame) ->
          str_const("pdframe:" + JSON of sorted-key dict)
          e.g. str_const('pdframe:{"a":[1,2,3]}')
    - ``list[int]`` (pd.Series / np array) ->
          str_const("pdseries:" + JSON of list)
          e.g. str_const('pdseries:[1,2,3]')
    - ``int`` (bare scalar) -> num(value)

    Returns None for anything else (honest -- no fake encoding).
    The encoding is INJECTIVE: two distinct values produce distinct str_const
    (sorted column order = canonical; different ints/lengths → different JSON).
    In z3's String theory, distinct string literals are always distinct, so
    two frames with different columns or values produce distinct constants and
    the equality obligation becomes UNSAT when the frames differ, giving the
    solver's UNSAT certificate real teeth.
    """
    if isinstance(value, dict):
        # Must be dict[str, list[int]] -- DataFrame shape
        for k, v in value.items():
            if not isinstance(k, str):
                return None
            if not isinstance(v, list):
                return None
            if not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
                return None
        # Sort keys for canonicality; JSON with compact separators for uniqueness.
        canonical = _json.dumps(
            {k: value[k] for k in sorted(value.keys())},
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return str_const("pdframe:" + canonical)
    if isinstance(value, list):
        # Must be list[int] -- Series/array shape
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in value):
            return None
        canonical = _json.dumps(value, separators=(",", ":"))
        return str_const("pdseries:" + canonical)
    if isinstance(value, int) and not isinstance(value, bool):
        return num(value)
    return None


def _nested_int_literal(node: ast.AST):
    """An ast node -> a nested Python list of ints (or a bare int), or None.
    A leaf is an int `ast.Constant` (bool excluded); a branch is an `ast.List`
    whose every element is itself a nested-int-literal. Any non-int leaf,
    a non-List/non-Constant node, or a mixed shape -> None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.List):
        out: list = []
        for el in node.elts:
            v = _nested_int_literal(el)
            if v is None:
                return None
            out.append(v)
        return out
    return None


def _np_array_nested_int(node: ast.AST):
    """If `node` is `np.array(<nested int literal>)` of ANY rank (1-D, 2-D, ...),
    return the nested Python list (or bare int); else None."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "array"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "np"
        and len(node.args) == 1
    ):
        return None
    return _nested_int_literal(node.args[0])


def _literal_label_list(node: ast.AST) -> "list | None":
    """Extract a flat homogeneous list of str or int constants from an ast.List.

    Rules:
    - All elements must be ast.Constant of the same type (all str OR all int).
    - bool is excluded even though bool is a subclass of int.
    - Mixed types, empty lists, float/None/other leaves -> None (opaque).

    Returns list[str] or list[int], never mixed.
    """
    if not isinstance(node, ast.List):
        return None
    if not node.elts:
        return None  # empty -> opaque
    result = []
    elem_type = None  # str or int (type object)
    for el in node.elts:
        if not isinstance(el, ast.Constant):
            return None
        v = el.value
        if isinstance(v, bool):
            return None
        if isinstance(v, str):
            if elem_type is None:
                elem_type = str
            elif elem_type is not str:
                return None  # mixed
        elif isinstance(v, int):
            if elem_type is None:
                elem_type = int
            elif elem_type is not int:
                return None  # mixed
        else:
            return None  # float, None, bytes, etc.
        result.append(v)
    return result


def _is_label_encoder_call(node: ast.AST) -> bool:
    """Return True iff ``node`` is a LabelEncoder() constructor call.

    Recognises both:
    - ``LabelEncoder()``                (ast.Name func)
    - ``preprocessing.LabelEncoder()``  (ast.Attribute func, attr=="LabelEncoder")
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "LabelEncoder":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "LabelEncoder":
        return True
    return False


def _find_label_encoder_labels(receiver_node: ast.AST, fn: ast.FunctionDef) -> "list | None":
    """For a Name node that is bound to LabelEncoder(), find the literal labels
    used in the single fit_transform([labels]) call in fn.body.

    Returns the raw list[str|int] of labels (not yet sorted/encoded), or None
    if any of these fail:
    - receiver_node is not ast.Name
    - the name is not bound exactly once to a LabelEncoder() constructor
    - no unique fit_transform([literal-labels]) call on that name found in fn.body
    """
    if not isinstance(receiver_node, ast.Name):
        return None
    name = receiver_node.id
    # Confirm single binding to LabelEncoder()
    le_bound = None
    le_count = 0
    fit_labels = None
    fit_count = 0
    for stmt in fn.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id == name:
            le_bound = stmt.value
            le_count += 1
            continue
        # Check: some_var = le.fit_transform([...])
        rhs = stmt.value
        if (
            isinstance(rhs, ast.Call)
            and isinstance(rhs.func, ast.Attribute)
            and rhs.func.attr == "fit_transform"
            and isinstance(rhs.func.value, ast.Name)
            and rhs.func.value.id == name
            and len(rhs.args) == 1
        ):
            labels = _literal_label_list(rhs.args[0])
            if labels is not None:
                fit_labels = labels
                fit_count += 1
    if le_count != 1 or le_bound is None or not _is_label_encoder_call(le_bound):
        return None
    if fit_count != 1 or fit_labels is None:
        return None
    return fit_labels


def _resolve_np_array_element(
    fn: ast.FunctionDef,
    root_name: str,
    indices: list[int],
) -> int | None:
    """Walk fn.body for `root_name = np.array(<nested int literal>)` of ANY rank,
    then index the nested literal by the FULL integer path (1-D `a[i]`, 2-D
    `r[i][j]`, 3-D, ...).

    Returns the resolved integer element, or None (opaque fallback) for ANY
    ambiguity: no binding / non-simple binding, a non-literal value, an
    out-of-range or over/under-indexed path, or a non-int leaf. Never guesses.
    """
    for stmt in fn.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name) or target.id != root_name:
            continue
        nested = _np_array_nested_int(stmt.value)
        if nested is None:
            # Bound, but not to a resolvable np.array int literal -- opaque.
            return None
        cur: object = nested
        for idx in indices:
            if not isinstance(cur, list) or idx < 0 or idx >= len(cur):
                return None  # out of range, or indexing past a scalar
            cur = cur[idx]
        if not isinstance(cur, int) or isinstance(cur, bool):
            return None  # under-indexed (still a list) or non-int leaf
        return cur
    # No assignment found for root_name -- opaque.
    return None


def _index_nested(value: object, indices: list[int]) -> int | None:
    """Walk a nested list of ints by ``indices`` and return the int leaf.
    Returns None if any index is out-of-range, the path bottoms out early (int
    where a list was expected), the path is under-indexed (a list remains), or
    the leaf is not a plain int (bool excluded)."""
    cur: object = value
    for idx in indices:
        if not isinstance(cur, list):
            return None
        if idx < 0 or idx >= len(cur):
            return None
        cur = cur[idx]
    if not isinstance(cur, int) or isinstance(cur, bool):
        return None
    return cur


def _is_2d_int_matrix(m: object) -> bool:
    """True iff ``m`` is a non-empty list of equal-length lists of plain ints."""
    if not isinstance(m, list) or len(m) == 0:
        return False
    ncols = None
    for row in m:
        if not isinstance(row, list):
            return False
        if ncols is None:
            ncols = len(row)
        elif len(row) != ncols:
            return False
        for el in row:
            if not isinstance(el, int) or isinstance(el, bool):
                return False
    return True


def _resolve_value(node: ast.AST, fn: ast.FunctionDef) -> object:
    """Recursively resolve a numpy value expression to a nested Python list of
    ints (or a bare int) that exactly mirrors the numpy array's contents.

    Returns None (opaque — never guesses) for anything unrecognised, any
    non-int leaf, a shape mismatch, or an out-of-range operation.

    Supported shapes:
    - ``np.array(<nested int literal>)``          -> the nested list
    - ``np.arange(n)``                            -> [0, 1, ..., n-1]
    - ``np.arange(start, stop)``                  -> [start, ..., stop-1]
    - ``np.arange(start, stop, step)``            -> [start, start+step, ...]
    - ``np.rot90(x)`` or ``np.rot90(x, k)``      -> 2-D CCW rotation (ints)
    - ``np.transpose(x)``                         -> 2-D transpose
    - ``x.T``  (ast.Attribute .T)                 -> 2-D transpose
    - ``x.reshape(R, C)``                         -> row-major reshape to 2-D
    - ``ast.Name``                                -> look up single assignment
                                                     in fn.body, recurse
    """
    # --- np.array(<nested int literal>) ---
    np_arr = _np_array_nested_int(node)
    if np_arr is not None:
        return np_arr

    # --- Raw nested int literal: ast.Constant (int) or ast.List ---
    raw = _nested_int_literal(node)
    if raw is not None:
        return raw

    # --- ast.Name: look up in fn.body ---
    if isinstance(node, ast.Name):
        name = node.id
        found = None
        found_tuple_idx: int | None = None
        count = 0
        for stmt in fn.body:
            if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                continue
            target = stmt.targets[0]
            if isinstance(target, ast.Name) and target.id == name:
                found = stmt.value
                found_tuple_idx = None
                count += 1
            elif isinstance(target, ast.Tuple):
                for i, elt in enumerate(target.elts):
                    if isinstance(elt, ast.Name) and elt.id == name:
                        found = stmt.value
                        found_tuple_idx = i
                        count += 1
                        break
        if count != 1 or found is None:
            return None
        resolved = _resolve_value(found, fn)
        if found_tuple_idx is not None:
            # Tuple-unpack: index into the resolved RHS at position found_tuple_idx.
            if not isinstance(resolved, list) or found_tuple_idx >= len(resolved):
                return None
            return resolved[found_tuple_idx]
        return resolved

    # --- ast.Call: dispatch on callee ---
    if isinstance(node, ast.Call):
        func = node.func

        # np.<something>(...)
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "np"
        ):
            op = func.attr

            # np.arange(n) / np.arange(a, b) / np.arange(a, b, s)
            if op == "arange":
                args = node.args
                if len(args) == 1:
                    n = _const_int(args[0])
                    if n is None or n < 0:
                        return None
                    return list(range(n))
                if len(args) == 2:
                    a, b = _const_int(args[0]), _const_int(args[1])
                    if a is None or b is None:
                        return None
                    return list(range(a, b))
                if len(args) == 3:
                    a, b, s = _const_int(args[0]), _const_int(args[1]), _const_int(args[2])
                    if a is None or b is None or s is None or s == 0:
                        return None
                    return list(range(a, b, s))
                return None

            # np.rot90(x) or np.rot90(x, k)
            if op == "rot90":
                if len(node.args) < 1:
                    return None
                src = _resolve_value(node.args[0], fn)
                if src is None or not _is_2d_int_matrix(src):
                    return None
                # k defaults to 1 (CCW 90°); may be positional or keyword
                k = 1
                if len(node.args) >= 2:
                    k_val = _const_int(node.args[1])
                    if k_val is None:
                        return None
                    k = k_val
                else:
                    for kw in node.keywords:
                        if kw.arg == "k":
                            k_val = _const_int(kw.value)
                            if k_val is None:
                                return None
                            k = k_val
                            break
                k = k % 4
                m = src  # type: ignore[assignment]
                for _ in range(k):
                    R = len(m)
                    C = len(m[0])
                    # CCW 90°: result[i][j] = m[j][C-1-i], result is C×R
                    m = [[m[j][C - 1 - i] for j in range(R)] for i in range(C)]
                return m

            # np.transpose(x)
            if op == "transpose":
                if len(node.args) != 1:
                    return None
                src = _resolve_value(node.args[0], fn)
                if src is None or not _is_2d_int_matrix(src):
                    return None
                R = len(src)
                C = len(src[0])
                return [[src[i][j] for i in range(R)] for j in range(C)]

            # np.flip(x) — reverse all axes (2-D)
            if op == "flip":
                if len(node.args) != 1:
                    return None
                src = _resolve_value(node.args[0], fn)
                if src is None or not _is_2d_int_matrix(src):
                    return None
                R = len(src)
                C = len(src[0])
                return [[src[R - 1 - i][C - 1 - j] for j in range(C)] for i in range(R)]

            # np.fliplr(x) — reverse columns
            if op == "fliplr":
                if len(node.args) != 1:
                    return None
                src = _resolve_value(node.args[0], fn)
                if src is None or not _is_2d_int_matrix(src):
                    return None
                R = len(src)
                C = len(src[0])
                return [[src[i][C - 1 - j] for j in range(C)] for i in range(R)]

            # np.flipud(x) — reverse rows
            if op == "flipud":
                if len(node.args) != 1:
                    return None
                src = _resolve_value(node.args[0], fn)
                if src is None or not _is_2d_int_matrix(src):
                    return None
                R = len(src)
                C = len(src[0])
                return [[src[R - 1 - i][j] for j in range(C)] for i in range(R)]

            # np.diagonal(x) — main diagonal of a 2-D matrix -> 1-D list
            if op == "diagonal":
                if len(node.args) != 1:
                    return None
                src = _resolve_value(node.args[0], fn)
                if src is None or not _is_2d_int_matrix(src):
                    return None
                R = len(src)
                C = len(src[0])
                return [src[i][i] for i in range(min(R, C))]

            # np.ravel(x) — row-major flatten -> 1-D list
            if op == "ravel":
                if len(node.args) != 1:
                    return None
                src = _resolve_value(node.args[0], fn)
                if src is None:
                    return None
                flat_r: list[int] = []
                _flatten(src, flat_r)
                return flat_r

            # np.concatenate / np.hstack / np.vstack / np.stack
            if op in ("concatenate", "hstack", "vstack", "stack"):
                if len(node.args) < 1 or not isinstance(node.args[0], ast.List):
                    return None
                parts = []
                for elt in node.args[0].elts:
                    v = _resolve_value(elt, fn)
                    if v is None:
                        return None
                    parts.append(v)
                if not parts:
                    return None
                # Classify each part: 1-D (list[int]) or 2-D (list[list[int]])
                def _is_1d(p: object) -> bool:
                    return (
                        isinstance(p, list)
                        and len(p) > 0
                        and all(isinstance(e, int) and not isinstance(e, bool) for e in p)
                    )
                all_1d = all(_is_1d(p) for p in parts)
                all_2d = all(_is_2d_int_matrix(p) for p in parts)
                if not all_1d and not all_2d:
                    return None  # mixed dims -> opaque

                if op == "concatenate":
                    if all_1d:
                        # flat concat
                        result: list = []
                        for p in parts:
                            result.extend(p)  # type: ignore[arg-type]
                        return result
                    else:
                        # row concat (2-D)
                        result = []
                        for p in parts:
                            result.extend(p)  # type: ignore[arg-type]
                        if not _is_2d_int_matrix(result):
                            return None
                        return result

                if op == "hstack":
                    if all_1d:
                        # same as concatenate 1-D
                        result = []
                        for p in parts:
                            result.extend(p)  # type: ignore[arg-type]
                        return result
                    else:
                        # column concat: result[i] = p0[i] ++ p1[i] ++ ...
                        nrows = len(parts[0])  # type: ignore[arg-type]
                        if any(len(p) != nrows for p in parts):  # type: ignore[arg-type]
                            return None
                        return [
                            sum((p[i] for p in parts), [])  # type: ignore[index]
                            for i in range(nrows)
                        ]

                if op == "vstack":
                    if all_1d:
                        # each 1-D part becomes a row; require equal lengths
                        ncols = len(parts[0])  # type: ignore[arg-type]
                        if any(len(p) != ncols for p in parts):  # type: ignore[arg-type]
                            return None
                        return [list(p) for p in parts]  # type: ignore[arg-type]
                    else:
                        # row concat (same as concatenate 2-D)
                        result = []
                        for p in parts:
                            result.extend(p)  # type: ignore[arg-type]
                        if not _is_2d_int_matrix(result):
                            return None
                        return result

                if op == "stack":
                    if all_1d:
                        # new axis 0: [p0, p1, ...], require equal lengths
                        ncols = len(parts[0])  # type: ignore[arg-type]
                        if any(len(p) != ncols for p in parts):  # type: ignore[arg-type]
                            return None
                        return [list(p) for p in parts]  # type: ignore[arg-type]
                    else:
                        # 3-D result -> out of scope
                        return None

                return None  # unreachable but satisfies control flow

            # np.array already handled above by _np_array_nested_int
            return None

        # pd.<something>(...)
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "pd"
        ):
            pd_op = func.attr

            # pd.DataFrame({"col": [ints], ...})  -> dict {col: list[int]}
            if pd_op == "DataFrame":
                if len(node.args) != 1 or not isinstance(node.args[0], ast.Dict):
                    return None
                d = node.args[0]
                result_dict: dict[str, list[int]] = {}
                for k_node, v_node in zip(d.keys, d.values):
                    if not (isinstance(k_node, ast.Constant) and isinstance(k_node.value, str)):
                        return None  # non-string key -> opaque
                    col_name = k_node.value
                    col_val = _nested_int_literal(v_node)
                    if col_val is None or not isinstance(col_val, list):
                        return None  # non-int-list column -> opaque
                    if not all(isinstance(x, int) and not isinstance(x, bool) for x in col_val):
                        return None
                    result_dict[col_name] = col_val
                return result_dict

            # pd.Series([ints])  -> list[int]
            if pd_op == "Series":
                if len(node.args) != 1:
                    return None
                col_val = _nested_int_literal(node.args[0])
                if col_val is None or not isinstance(col_val, list):
                    return None
                if not all(isinstance(x, int) and not isinstance(x, bool) for x in col_val):
                    return None
                return col_val

            return None

        # x.reshape(R, C)  — method call on some value expression
        if isinstance(func, ast.Attribute) and func.attr == "reshape":
            if len(node.args) != 2:
                return None
            R, C = _const_int(node.args[0]), _const_int(node.args[1])
            if R is None or C is None or R < 0 or C < 0:
                return None
            src = _resolve_value(func.value, fn)
            if src is None:
                return None
            # Flatten row-major
            flat: list[int] = []
            _flatten(src, flat)
            if len(flat) != R * C:
                return None
            return [[flat[i * C + j] for j in range(C)] for i in range(R)]

        # x.ravel() / x.flatten() — method call, row-major flatten -> 1-D list
        if isinstance(func, ast.Attribute) and func.attr in ("ravel", "flatten"):
            if len(node.args) != 0:
                return None
            src = _resolve_value(func.value, fn)
            if src is None:
                return None
            flat_m: list[int] = []
            _flatten(src, flat_m)
            return flat_m

        # train_test_split(arr, shuffle=False, test_size=T|train_size=S)
        # -> [train_list, test_list] using sklearn ceiling/floor rule.
        # ONLY when shuffle=False is explicitly given; otherwise opaque.
        if (
            (isinstance(func, ast.Name) and func.id == "train_test_split")
            or (isinstance(func, ast.Attribute) and func.attr == "train_test_split")
        ):
            if len(node.args) < 1:
                return None
            data = _resolve_value(node.args[0], fn)
            if not isinstance(data, list):
                return None
            if not all(isinstance(x, int) and not isinstance(x, bool) for x in data):
                return None
            n = len(data)
            shuffle_explicit_false = False
            test_size_type: str | None = None  # 'f' or 'i'
            test_size_num: float | int | None = None
            train_size_type: str | None = None
            train_size_num: float | int | None = None
            for kw in node.keywords:
                if kw.arg == "shuffle":
                    if isinstance(kw.value, ast.Constant) and kw.value.value is False:
                        shuffle_explicit_false = True
                    else:
                        return None  # shuffle=True or non-literal -> opaque
                elif kw.arg == "test_size":
                    if isinstance(kw.value, ast.Constant):
                        v = kw.value.value
                        if isinstance(v, float) and not isinstance(v, bool):
                            test_size_type = 'f'
                            test_size_num = v
                        elif isinstance(v, int) and not isinstance(v, bool):
                            test_size_type = 'i'
                            test_size_num = v
                        else:
                            return None
                    else:
                        return None
                elif kw.arg == "train_size":
                    if isinstance(kw.value, ast.Constant):
                        v = kw.value.value
                        if isinstance(v, float) and not isinstance(v, bool):
                            train_size_type = 'f'
                            train_size_num = v
                        elif isinstance(v, int) and not isinstance(v, bool):
                            train_size_type = 'i'
                            train_size_num = v
                        else:
                            return None
                    else:
                        return None
                # random_state, stratify, etc. -> ignore (don't affect shuffle=False)
            if not shuffle_explicit_false:
                return None  # opaque: shuffle omitted or True
            # Compute n_test using sklearn ceiling rule for float, exact for int.
            if test_size_type == 'f':
                n_test: int | None = math.ceil(float(test_size_num) * n)
            elif test_size_type == 'i':
                n_test = int(test_size_num)  # type: ignore[arg-type]
            else:
                # test_size is None
                if train_size_type is None:
                    # Both None: default_test_size = 0.25
                    n_test = math.ceil(0.25 * n)
                else:
                    n_test = None  # will compute from n_train below
            # Compute n_train using sklearn floor rule for float, exact for int.
            if train_size_type == 'f':
                n_train: int | None = math.floor(float(train_size_num) * n)
            elif train_size_type == 'i':
                n_train = int(train_size_num)  # type: ignore[arg-type]
            else:
                n_train = None
            # Fill in missing side
            if n_test is None and n_train is not None:
                n_test = n - n_train
            elif n_train is None and n_test is not None:
                n_train = n - n_test
            if n_test is None or n_train is None:
                return None
            if n_train < 0 or n_test < 0 or n_train + n_test > n:
                return None
            train_arr = data[:n_train]
            test_arr = data[n_train:n_train + n_test]
            return [train_arr, test_arr]

        # confusion_matrix(y_true_literal, y_pred_literal, labels=...) -> 2-D int matrix.
        # labels sorted ascending (int) or lexicographic (str) when not given explicitly.
        if (
            (isinstance(func, ast.Name) and func.id == "confusion_matrix")
            or (isinstance(func, ast.Attribute) and func.attr == "confusion_matrix")
        ):
            if len(node.args) < 2:
                return None
            yt = _literal_label_list(node.args[0])
            yp = _literal_label_list(node.args[1])
            if yt is None or yp is None:
                return None
            if len(yt) != len(yp):
                return None
            if not yt:
                return None
            # Both must be same homogeneous type (all int or all str).
            yt_type = type(yt[0])
            yp_type = type(yp[0])
            if yt_type is not yp_type:
                return None
            # Handle optional labels= keyword.
            cm_labels: list | None = None
            for kw in node.keywords:
                if kw.arg == "labels":
                    cm_labels = _literal_label_list(kw.value)
                    if cm_labels is None:
                        return None  # non-literal labels -> opaque
            if cm_labels is None:
                cm_labels = sorted(set(yt) | set(yp))
            n_labels = len(cm_labels)
            label_idx = {lbl: idx for idx, lbl in enumerate(cm_labels)}
            C = [[0] * n_labels for _ in range(n_labels)]
            for yt_val, yp_val in zip(yt, yp):
                if yt_val not in label_idx or yp_val not in label_idx:
                    return None  # label outside matrix -> opaque
                C[label_idx[yt_val]][label_idx[yp_val]] += 1
            return C

        # NOTE: accuracy_score is intentionally NOT handled here. Its result is a
        # bare scalar, so the only assertion forms (`assert accuracy_score(...) == n`
        # and `a = accuracy_score(...); assert a == n`) reach the factory's
        # callsite-equality / scalar-name paths, both of which currently PANIC
        # (observed=callsite-arg:List / assert-eq-lhs:Name) before _resolve_value is
        # ever consulted. A _resolve_value arm here would be dead code. It is also
        # semantically float: accuracy_score(..., normalize=False) returns 2.0, not
        # int 2. Grounding the scalar-equality surface is a separate future round.

        # LabelEncoder().fit_transform([labels])  — inline form
        # le.fit_transform([labels])              — bound form (le = LabelEncoder())
        # Returns list[int] encoding using sklearn's sorted-unique mapping:
        #   classes = sorted(set(labels)); result[i] = classes.index(labels[i])
        if isinstance(func, ast.Attribute) and func.attr == "fit_transform":
            receiver = func.value
            is_label_encoder = False
            if _is_label_encoder_call(receiver):
                # Inline: LabelEncoder().fit_transform(...)
                is_label_encoder = True
            elif isinstance(receiver, ast.Name):
                # Bound: le = LabelEncoder(); le.fit_transform(...)
                bound_val = None
                bound_count = 0
                for _stmt in fn.body:
                    if not isinstance(_stmt, ast.Assign) or len(_stmt.targets) != 1:
                        continue
                    _target = _stmt.targets[0]
                    if isinstance(_target, ast.Name) and _target.id == receiver.id:
                        bound_val = _stmt.value
                        bound_count += 1
                if bound_count == 1 and bound_val is not None and _is_label_encoder_call(bound_val):
                    is_label_encoder = True
            if is_label_encoder:
                if len(node.args) != 1:
                    return None
                labels = _literal_label_list(node.args[0])
                if labels is None:
                    return None  # empty, mixed, or non-literal -> opaque
                # Sklearn semantics: sorted unique classes, then encode each label.
                # sorted() works correctly for all-str or all-int (never mixed, enforced above).
                classes = sorted(set(labels))
                mapping = {c: i for i, c in enumerate(classes)}
                return [mapping[x] for x in labels]

        return None

    # --- x.T (Attribute access, not a Call) ---
    if isinstance(node, ast.Attribute) and node.attr == "T":
        src = _resolve_value(node.value, fn)
        if src is None or not _is_2d_int_matrix(src):
            return None
        R = len(src)
        C = len(src[0])
        return [[src[i][j] for i in range(R)] for j in range(C)]

    # --- df.values -> row-major 2-D int matrix ---
    if isinstance(node, ast.Attribute) and node.attr == "values":
        src = _resolve_value(node.value, fn)
        if not isinstance(src, dict):
            return None
        cols = list(src.keys())
        if not cols:
            return None
        col_lists = [src[c] for c in cols]
        nrows = len(col_lists[0])
        # All columns must be equal-length lists of plain ints
        for col in col_lists:
            if not isinstance(col, list) or len(col) != nrows:
                return None
            if not all(isinstance(x, int) and not isinstance(x, bool) for x in col):
                return None
        return [[col_lists[j][i] for j in range(len(cols))] for i in range(nrows)]

    # --- df.shape -> [nrows, ncols] ---
    if isinstance(node, ast.Attribute) and node.attr == "shape":
        src = _resolve_value(node.value, fn)
        if not isinstance(src, dict):
            return None
        cols = list(src.keys())
        if not cols:
            return None
        col_lists = [src[c] for c in cols]
        nrows = len(col_lists[0])
        for col in col_lists:
            if not isinstance(col, list) or len(col) != nrows:
                return None
            if not all(isinstance(x, int) and not isinstance(x, bool) for x in col):
                return None
        return [nrows, len(cols)]

    # --- x.iloc -> row-major 2-D (DataFrame) or the list itself (Series) ---
    if isinstance(node, ast.Attribute) and node.attr == "iloc":
        src = _resolve_value(node.value, fn)
        if isinstance(src, dict):
            cols = list(src.keys())
            if not cols:
                return None
            col_lists = [src[c] for c in cols]
            nrows = len(col_lists[0])
            for col in col_lists:
                if not isinstance(col, list) or len(col) != nrows:
                    return None
                if not all(isinstance(x, int) and not isinstance(x, bool) for x in col):
                    return None
            return [[col_lists[j][i] for j in range(len(cols))] for i in range(nrows)]
        if isinstance(src, list):
            return src
        return None

    # --- le.classes_ -> sorted unique labels list from a fitted LabelEncoder ---
    # Works only for the bound form (le = LabelEncoder(); le.fit_transform([...]))
    # because the inline form LabelEncoder().fit_transform(...) discards the object.
    # Returns list[str] or list[int] (the sorted unique classes).
    # Opaque for: non-LabelEncoder receiver, unfitted (no fit_transform found),
    # ambiguous / multi-assignment, or non-literal label arguments.
    if isinstance(node, ast.Attribute) and node.attr == "classes_":
        labels = _find_label_encoder_labels(node.value, fn)
        if labels is None:
            return None
        return sorted(set(labels))

    return None


def _flatten(value: object, out: list) -> None:
    """Recursively flatten a nested list of ints into ``out`` (row-major)."""
    if isinstance(value, list):
        for el in value:
            _flatten(el, out)
    elif isinstance(value, int) and not isinstance(value, bool):
        out.append(value)


def _const_int(node: ast.AST) -> int | None:
    """Return the int value of a bare int ast.Constant, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None


@dataclass(frozen=True)
class _IndexOp:
    """Single integer index: a[i]."""
    i: int


@dataclass(frozen=True)
class _SliceOp:
    """Integer-bounded slice: a[lo:hi:step] with None meaning omitted."""
    lower: int | None
    upper: int | None
    step: int | None


@dataclass(frozen=True)
class _KeyOp:
    """String key lookup: df[col]."""
    key: str


def _apply_ops(value: object, ops: list[_IndexOp | _SliceOp | _KeyOp]) -> object:
    """Apply a sequence of index/slice ops left-to-right to a resolved nested value.

    Returns the final value (int or list) after all ops, or None if anything
    goes wrong (out-of-range, wrong type, symbolic bound, etc.).  The caller
    is responsible for checking that the final value is a scalar int.
    """
    cur: object = value
    for op in ops:
        if isinstance(op, _IndexOp):
            if not isinstance(cur, list):
                return None
            if op.i < 0 or op.i >= len(cur):
                return None
            cur = cur[op.i]
        elif isinstance(op, _SliceOp):
            if not isinstance(cur, list):
                return None
            # Negative indices or step != 1 (and step != None) treated as opaque.
            lo = op.lower
            hi = op.upper
            st = op.step
            if (lo is not None and lo < 0) or (hi is not None and hi < 0):
                return None
            if st is not None and st != 1:
                return None
            cur = cur[lo:hi]  # Python slice semantics match numpy on int lists
        elif isinstance(op, _KeyOp):
            if not isinstance(cur, dict):
                return None
            if op.key not in cur:
                return None  # missing column -> opaque
            cur = cur[op.key]
    return cur
