"""Hand-built quirk shapes for memento span-stability differential (issue #5940).

Each shape targets a specific span-semantics edge case called out in the
#5940 design comment. Kept small and deterministic; no execution required,
only ast.parse.
"""

import re


# --- f-strings (span semantics changed in CPython 3.12; PEP 701) ---
name = "world"
plain_fstring = f"hello {name}"
fstring_with_expr = f"{1 + 2}"
fstring_with_format_spec = f"{3.14159:.2f}"
fstring_with_conversion = f"{name!r}"
nested_fstring = f"outer {f'inner {name}'} end"
multiline_fstring = f"""
{name}
{1 + 1}
"""
fstring_with_nested_quotes = f"{'a' + 'b'}"

# --- parenthesized expressions ---
paren_simple = (1 + 2)
paren_redundant = ((1 + 2))
paren_tuple = (1, 2, 3)
paren_generator = (x for x in range(3))
paren_walrus = (y := 10)

# --- decorated functions/classes ---
def plain_decorator(f):
    return f


@plain_decorator
def decorated_function():
    return 1


@plain_decorator
@plain_decorator
class DecoratedClass:
    @plain_decorator
    def decorated_method(self):
        return 2


# --- multi-line calls ---
def multiline_call_target(a, b, c):
    return a + b + c


multiline_call_result = multiline_call_target(
    1,
    2,
    3,
)

# --- implicit string concatenation ---
implicit_concat = (
    "part one "
    "part two "
    "part three"
)
implicit_concat_single_line = "abc" "def"

# --- lambdas ---
simple_lambda = lambda x: x + 1
multi_arg_lambda = lambda x, y=1, *args, **kwargs: (x, y, args, kwargs)

# --- comprehensions ---
list_comp = [x * 2 for x in range(10) if x % 2 == 0]
dict_comp = {x: x * x for x in range(5)}
set_comp = {x for x in range(5)}
nested_comp = [[y for y in range(x)] for x in range(5)]
gen_comp_expr = sum(x for x in range(10))

# --- match statements (3.10+) ---
def match_example(value):
    match value:
        case 0:
            return "zero"
        case [a, b]:
            return a + b
        case {"key": v}:
            return v
        case str() as s:
            return s
        case _:
            return None


# --- walrus operator ---
def walrus_in_while():
    data = [1, 2, 3]
    total = 0
    while (n := len(data)) > 0:
        total += data.pop()
    return total


if (m := re.match(r"\d+", "123abc")) is not None:
    walrus_in_if = m.group()

# --- star-args ---
def star_args_target(*args, **kwargs):
    return args, kwargs


star_args_call = star_args_target(1, 2, *[3, 4], key="value", **{"other": 1})


def star_args_def(a, *, b, **kwargs):
    return a, b, kwargs


def unpack_assignment():
    first, *rest = [1, 2, 3, 4]
    return first, rest
